"""Signature-validated local assets exposed only through opaque identifiers."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import struct
import zlib
from pathlib import Path, PurePath

from .questions import secure_sqlite_path
from .workspace import ASSETS_DB_NAME, PRIVATE_DIR_NAME


REFERENCE_ROLES = frozenset({"character", "object", "product", "style", "location", "other"})
# Ticket 12 repair, поправка оркестратора 3 (R15/R22) and condition 6: an
# asset that backs a scene's image/video *result* is not a reference to a
# character, an object, a location, ... -- it needs its own role, distinct
# from `REFERENCE_ROLES`. This is enforced twice, at registration and at
# use: `register()` below refuses any role outside `ASSET_ROLES`, and each
# call site that links a *registered* asset into canonical state checks
# the role that call actually needs against the role that asset was
# registered with (`AssetIndex.role_of`) -- `authoring_media.add_reference`
# refuses an asset registered `result`, and `authoring_media.
# add_result_version`/`authoring_qa.set_assembly` refuse one registered
# with any of `REFERENCE_ROLES` -- so a `reference add`/`result add-
# version`/`assembly set` can never be tricked into treating an asset
# registered for the other purpose as if it were its own.
RESULT_ROLE = "result"
# Ticket 26 (spec §18.4): a character's voice reference is an audio file, so
# it is neither an image reference (`REFERENCE_ROLES`, which stays exactly
# the five image kinds `reference add --role` accepts) nor a scene/layer
# result. It gets its own role: `add_reference` refuses it (wrong role and
# wrong MIME, both), `require_voice_asset_role` in `authoring_support` is
# the check a voice binding must pass, and an audio layer's *result* is
# registered `result` like every other result. As before, `register()` does
# not pair a role with a media type -- each call site that links an asset
# in checks the role *and* the MIME type it needs.
VOICE_ROLE = "voice"
VIDEO_REFERENCE_ROLE = "video_reference"
ASSET_ROLES = REFERENCE_ROLES | {RESULT_ROLE, VOICE_ROLE, VIDEO_REFERENCE_ROLE}
MAX_IMAGE_PIXELS = 25_000_000
MAX_DECODED_IMAGE_BYTES = 128 * 1024 * 1024
_DECODE_CHUNK_BYTES = 64 * 1024

_EXTENSION_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}
_DANGEROUS_EXTENSIONS = {".htm", ".html", ".svg", ".svgz", ".xhtml"}


class AssetError(RuntimeError):
    """Base failure for asset registration or resolution."""


class AssetValidationError(AssetError, ValueError):
    """A path or file does not satisfy the local media contract."""


class AssetNotFound(AssetError):
    """An opaque asset id is unknown to this index."""


def _within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


# Собранный ролик монтажа относительно корня медиа — studio/montage/paths.render_output.
_MONTAGE_OUTPUT = re.compile(r"[^/]+/montage/v\d{3,}\.mp4")


def _png(data: bytes) -> tuple[str, int, int] | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    width = height = None
    idat_chunks = []
    saw_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise AssetValidationError("PNG chunk exceeds file size")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise AssetValidationError("PNG chunk checksum is invalid")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise AssetValidationError("PNG must start with IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filtering,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise AssetValidationError("PNG dimensions are invalid")
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
                or interlace not in {0, 1}
            ):
                raise AssetValidationError("PNG header is unsupported")
        elif kind == b"IHDR":
            raise AssetValidationError("PNG contains multiple IHDR chunks")
        if kind == b"IDAT":
            idat_chunks.append(payload)
        if kind == b"IEND":
            if length != 0 or end != len(data):
                raise AssetValidationError("PNG has an invalid or non-final IEND")
            saw_iend = True
            offset = end
            break
        offset = end
    if not saw_iend or width is None or not idat_chunks or offset != len(data):
        raise AssetValidationError("PNG is incomplete")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bits_per_pixel = channels * bit_depth
    scanline_layout = []
    passes = (
        ((0, 0, 1, 1),)
        if interlace == 0
        else (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        )
    )
    for x_start, y_start, x_step, y_step in passes:
        pass_width = (
            (width - x_start + x_step - 1) // x_step if width > x_start else 0
        )
        pass_height = (
            (height - y_start + y_step - 1) // y_step if height > y_start else 0
        )
        if pass_width and pass_height:
            row_bytes = (pass_width * bits_per_pixel + 7) // 8
            scanline_layout.append((row_bytes, pass_height))
    expected_decoded = sum(
        (1 + row_bytes) * rows for row_bytes, rows in scanline_layout
    )
    if expected_decoded <= 0 or expected_decoded > MAX_DECODED_IMAGE_BYTES:
        raise AssetValidationError("PNG decoded size exceeds the safety limit")

    layout_index = 0
    rows_remaining = scanline_layout[0][1]
    row_data_remaining = 0
    decoded_count = 0

    def consume(decoded):
        nonlocal layout_index, rows_remaining, row_data_remaining, decoded_count
        decoded_count += len(decoded)
        if decoded_count > expected_decoded:
            raise AssetValidationError("PNG decoded size exceeds its dimensions")
        position = 0
        while position < len(decoded):
            while rows_remaining == 0:
                layout_index += 1
                if layout_index >= len(scanline_layout):
                    raise AssetValidationError("PNG has excess decoded scanlines")
                rows_remaining = scanline_layout[layout_index][1]
            if row_data_remaining == 0:
                if decoded[position] > 4:
                    raise AssetValidationError("PNG scanline filter is invalid")
                position += 1
                row_data_remaining = scanline_layout[layout_index][0]
            consumed = min(row_data_remaining, len(decoded) - position)
            position += consumed
            row_data_remaining -= consumed
            if row_data_remaining == 0:
                rows_remaining -= 1

    decoder = zlib.decompressobj()
    try:
        for compressed_chunk in idat_chunks:
            if decoder.eof and compressed_chunk:
                raise AssetValidationError("PNG contains data after its zlib stream")
            pending = compressed_chunk
            while pending:
                remaining_budget = expected_decoded - decoded_count + 1
                output_limit = min(_DECODE_CHUNK_BYTES, remaining_budget)
                if output_limit <= 0:
                    raise AssetValidationError("PNG decoded size exceeds its dimensions")
                before = len(pending)
                decoded = decoder.decompress(pending, output_limit)
                pending = decoder.unconsumed_tail
                consume(decoded)
                if decoder.eof:
                    if pending or decoder.unused_data:
                        raise AssetValidationError(
                            "PNG contains trailing compressed payload"
                        )
                    break
                if not decoded and len(pending) == before:
                    raise AssetValidationError("PNG decoder made no progress")
    except zlib.error as error:
        raise AssetValidationError("PNG pixel data cannot be decoded") from error
    if (
        not decoder.eof
        or decoded_count != expected_decoded
        or layout_index != len(scanline_layout) - 1
        or rows_remaining != 0
        or row_data_remaining != 0
    ):
        raise AssetValidationError("PNG decoded size does not match its dimensions")
    return "image/png", width, height


def _jpeg(data: bytes) -> tuple[str, int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    if len(data) < 8 or not data.endswith(b"\xff\xd9"):
        raise AssetValidationError("JPEG is incomplete")
    offset = 2
    width = height = None
    frame_marker = None
    frame_components = {}
    quantization_tables = set()
    huffman_tables = set()
    saw_arithmetic_tables = False
    saw_scan = False
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset < len(data):
        if data[offset] != 0xFF:
            raise AssetValidationError("JPEG marker stream is invalid")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            if not saw_scan or frame_marker is None or offset != len(data):
                raise AssetValidationError("JPEG EOI is missing or not final")
            return "image/jpeg", width, height
        if marker == 0xD8 or marker == 0x00:
            raise AssetValidationError("JPEG contains an invalid standalone marker")
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            raise AssetValidationError("JPEG restart marker is outside entropy data")
        if offset + 2 > len(data):
            raise AssetValidationError("JPEG segment is truncated")
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise AssetValidationError("JPEG segment length is invalid")
        payload_start = offset + 2
        segment_end = offset + segment_length
        payload = data[payload_start:segment_end]
        if marker == 0xDB:
            position = 0
            while position < len(payload):
                precision_and_id = payload[position]
                position += 1
                precision = precision_and_id >> 4
                table_id = precision_and_id & 0x0F
                if precision not in {0, 1} or table_id > 3:
                    raise AssetValidationError("JPEG quantization table is invalid")
                table_bytes = 64 * (precision + 1)
                if position + table_bytes > len(payload):
                    raise AssetValidationError("JPEG quantization table is truncated")
                if not all(payload[position : position + table_bytes]):
                    raise AssetValidationError("JPEG quantization values must be non-zero")
                quantization_tables.add(table_id)
                position += table_bytes
        elif marker == 0xC4:
            position = 0
            while position < len(payload):
                table_class_and_id = payload[position]
                position += 1
                table_class = table_class_and_id >> 4
                table_id = table_class_and_id & 0x0F
                if table_class not in {0, 1} or table_id > 3 or position + 16 > len(payload):
                    raise AssetValidationError("JPEG Huffman table is invalid")
                symbol_count = sum(payload[position : position + 16])
                position += 16
                if symbol_count <= 0 or position + symbol_count > len(payload):
                    raise AssetValidationError("JPEG Huffman symbols are truncated")
                huffman_tables.add((table_class, table_id))
                position += symbol_count
        elif marker == 0xCC:
            saw_arithmetic_tables = True
        elif marker in sof_markers:
            if frame_marker is not None or segment_length < 11:
                raise AssetValidationError("JPEG frame header is invalid")
            precision = payload[0]
            height, width = struct.unpack_from(">HH", payload, 1)
            component_count = payload[5]
            if (
                precision not in {8, 12}
                or component_count == 0
                or component_count > 4
                or len(payload) != 6 + 3 * component_count
            ):
                raise AssetValidationError("JPEG frame components are invalid")
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise AssetValidationError("JPEG dimensions are invalid")
            for position in range(6, len(payload), 3):
                component_id, sampling, table_id = payload[position : position + 3]
                horizontal = sampling >> 4
                vertical = sampling & 0x0F
                if (
                    component_id in frame_components
                    or horizontal not in range(1, 5)
                    or vertical not in range(1, 5)
                    or table_id > 3
                ):
                    raise AssetValidationError("JPEG frame component is invalid")
                frame_components[component_id] = table_id
            frame_marker = marker
        if marker == 0xDA:
            if frame_marker is None or len(payload) < 6:
                raise AssetValidationError("JPEG scan precedes its frame")
            component_count = payload[0]
            if component_count == 0 or len(payload) != 4 + 2 * component_count:
                raise AssetValidationError("JPEG scan header is invalid")
            scan_components = set()
            for position in range(1, 1 + 2 * component_count, 2):
                component_id = payload[position]
                selectors = payload[position + 1]
                dc_table = selectors >> 4
                ac_table = selectors & 0x0F
                if (
                    component_id not in frame_components
                    or component_id in scan_components
                    or dc_table > 3
                    or ac_table > 3
                ):
                    raise AssetValidationError("JPEG scan component is invalid")
                if not saw_arithmetic_tables and (
                    (0, dc_table) not in huffman_tables
                    or (1, ac_table) not in huffman_tables
                ):
                    raise AssetValidationError("JPEG scan references a missing table")
                scan_components.add(component_id)
            spectral_start, spectral_end, approximation = payload[-3:]
            if spectral_start > spectral_end or spectral_end > 63 or approximation > 0xDD:
                raise AssetValidationError("JPEG scan parameters are invalid")
            if frame_marker == 0xC0 and (
                spectral_start != 0 or spectral_end != 63 or approximation != 0
            ):
                raise AssetValidationError("baseline JPEG scan parameters are invalid")
            if any(table not in quantization_tables for table in frame_components.values()):
                raise AssetValidationError("JPEG frame references a missing quantization table")
            saw_scan = True
            offset = segment_end
            entropy_bytes = 0
            while offset < len(data):
                marker_start = data.find(b"\xff", offset)
                if marker_start < 0:
                    raise AssetValidationError("JPEG entropy data has no following marker")
                entropy_bytes += marker_start - offset
                marker_end = marker_start
                while marker_end < len(data) and data[marker_end] == 0xFF:
                    marker_end += 1
                if marker_end >= len(data):
                    raise AssetValidationError("JPEG entropy marker is truncated")
                entropy_marker = data[marker_end]
                if entropy_marker == 0x00:
                    entropy_bytes += 1
                    offset = marker_end + 1
                    continue
                if entropy_marker in range(0xD0, 0xD8):
                    offset = marker_end + 1
                    continue
                offset = marker_start
                break
            if entropy_bytes <= 0:
                raise AssetValidationError("JPEG entropy scan is empty")
            continue
        offset = segment_end
    raise AssetValidationError("JPEG has no final EOI marker")


def _webp(data: bytes) -> tuple[str, int, int] | None:
    if not (data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"):
        return None
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise AssetValidationError("WebP RIFF size is invalid")
    offset = 12
    chunks = []
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + size
        padded_end = end + (size & 1)
        if padded_end > len(data):
            raise AssetValidationError("WebP chunk is truncated")
        payload = data[start:end]
        if size & 1 and data[end] != 0:
            raise AssetValidationError("WebP padding byte must be zero")
        chunks.append((kind, payload))
        offset = padded_end
    if offset != len(data) or not chunks:
        raise AssetValidationError("WebP chunk layout is invalid")

    def primary_dimensions(kind, payload):
        if kind == b"VP8L":
            if len(payload) < 6 or payload[0] != 0x2F:
                raise AssetValidationError("WebP VP8L structure is invalid")
            bits = int.from_bytes(payload[1:5], "little")
            if bits >> 29:
                raise AssetValidationError("WebP VP8L version is unsupported")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8 ":
            if len(payload) < 11 or payload[3:6] != b"\x9d\x01\x2a":
                raise AssetValidationError("WebP VP8 structure is invalid")
            frame_tag = int.from_bytes(payload[:3], "little")
            partition_size = frame_tag >> 5
            if (
                frame_tag & 1
                or ((frame_tag >> 1) & 0x07) > 3
                or not ((frame_tag >> 4) & 1)
                or partition_size <= 0
                or partition_size > len(payload) - 10
            ):
                raise AssetValidationError("WebP VP8 key frame is invalid")
            return (
                struct.unpack_from("<H", payload, 6)[0] & 0x3FFF,
                struct.unpack_from("<H", payload, 8)[0] & 0x3FFF,
            )
        raise AssetValidationError("WebP primary image chunk is missing")

    first_kind, first_payload = chunks[0]
    if first_kind in {b"VP8 ", b"VP8L"}:
        if len(chunks) != 1:
            raise AssetValidationError("simple WebP must contain one primary image")
        width, height = primary_dimensions(first_kind, first_payload)
    elif first_kind == b"VP8X":
        if len(first_payload) != 10 or any(first_payload[1:4]):
            raise AssetValidationError("WebP VP8X header is invalid")
        flags = first_payload[0]
        if flags & 0xC3:
            raise AssetValidationError("animated or reserved WebP flags are unsupported")
        width = 1 + int.from_bytes(first_payload[4:7], "little")
        height = 1 + int.from_bytes(first_payload[7:10], "little")
        allowed_chunks = {b"ICCP", b"ALPH", b"VP8 ", b"VP8L", b"EXIF", b"XMP "}
        if any(kind not in allowed_chunks for kind, _ in chunks[1:]):
            raise AssetValidationError("WebP contains an unknown extended chunk")
        primaries = [(kind, payload) for kind, payload in chunks[1:] if kind in {b"VP8 ", b"VP8L"}]
        if len(primaries) != 1:
            raise AssetValidationError("extended WebP requires one primary image")
        primary_width, primary_height = primary_dimensions(*primaries[0])
        if (primary_width, primary_height) != (width, height):
            raise AssetValidationError("WebP VP8X dimensions do not match its image")
        if len({kind for kind, _ in chunks[1:]}) != len(chunks) - 1:
            raise AssetValidationError("WebP extended chunks must be unique")
        if any(kind == b"ALPH" for kind, _ in chunks[1:]) and primaries[0][0] != b"VP8 ":
            raise AssetValidationError("WebP ALPH requires a VP8 primary image")
    else:
        raise AssetValidationError("WebP must start with VP8, VP8L or VP8X")
    if not width or not height or width * height > MAX_IMAGE_PIXELS:
        raise AssetValidationError("WebP dimensions are invalid")
    return "image/webp", width, height


def _mp4(data: bytes) -> tuple[str, None, None] | None:
    if len(data) < 8 or data[4:8] != b"ftyp":
        return None
    offset = 0
    boxes = []
    while offset + 8 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > len(data):
                raise AssetValidationError("MP4 extended box is truncated")
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data):
            raise AssetValidationError("MP4 box size is invalid")
        boxes.append(kind)
        offset += size
    if offset != len(data) or not boxes or boxes[0] != b"ftyp":
        raise AssetValidationError("MP4 container is invalid")
    if len(data) < 16 or not all(32 <= byte < 127 for byte in data[8:12]):
        raise AssetValidationError("MP4 brand is invalid")
    if not any(kind in {b"moov", b"moof", b"mdat"} for kind in boxes[1:]):
        raise AssetValidationError("MP4 contains no media structure")
    return "video/mp4", None, None


def _vint_size(data: bytes, offset: int) -> tuple[int | None, int]:
    if offset >= len(data) or data[offset] == 0:
        raise AssetValidationError("WebM variable integer is invalid")
    first = data[offset]
    length = 1
    mask = 0x80
    while not first & mask:
        length += 1
        mask >>= 1
    if length > 8 or offset + length > len(data):
        raise AssetValidationError("WebM variable integer is truncated")
    value = first & (mask - 1)
    for byte in data[offset + 1 : offset + length]:
        value = (value << 8) | byte
    unknown = value == (1 << (7 * length)) - 1
    return (None if unknown else value), length


def _webm(data: bytes) -> tuple[str, None, None] | None:
    if not data.startswith(b"\x1a\x45\xdf\xa3"):
        return None
    header_size, size_length = _vint_size(data, 4)
    if header_size is None:
        raise AssetValidationError("WebM EBML header size cannot be unknown")
    header_start = 4 + size_length
    header_end = header_start + header_size
    if header_end + 5 > len(data):
        raise AssetValidationError("WebM EBML header is truncated")
    header = data[header_start:header_end]
    doctype = header.find(b"\x42\x82")
    if doctype < 0:
        raise AssetValidationError("WebM DocType is missing")
    doc_size, doc_size_length = _vint_size(header, doctype + 2)
    if doc_size is None:
        raise AssetValidationError("WebM DocType size is invalid")
    doc_start = doctype + 2 + doc_size_length
    if header[doc_start : doc_start + doc_size].lower() != b"webm":
        raise AssetValidationError("EBML file is not WebM")
    if data[header_end : header_end + 4] != b"\x18\x53\x80\x67":
        raise AssetValidationError("WebM Segment is missing")
    segment_size, segment_size_length = _vint_size(data, header_end + 4)
    content_start = header_end + 4 + segment_size_length
    if segment_size is not None and content_start + segment_size != len(data):
        raise AssetValidationError("WebM Segment size is invalid")
    if segment_size is None and content_start > len(data):
        raise AssetValidationError("WebM Segment is truncated")
    return "video/webm", None, None


# Ticket 26 (spec §8, §18.4-§18.5): audio gets the treatment the image and
# video containers already get. The signature only *selects* a detector; once
# one is selected every byte of the file must be accounted for, so a truncated
# stream, a stray tail or a chunk that does not tile the file is a refusal,
# never a best-effort guess. Duration is deliberately not extracted (§18.5
# takes it from the frame plan), so both detectors report `(mime, None, None)`
# like MP4/WebM -- the index table has no duration column either.

# `.mp3` means MPEG audio Layer III, so only Layer III frames are accepted.
# kbps by bitrate index; `None` is "free format" or "bad", neither of which
# has a frame length the chain could be walked with. MPEG-2 and MPEG-2.5
# share one bitrate table.
_MP3_KBPS_V1 = (None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None)
_MP3_KBPS_V2 = (None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None)
# Keyed by the two version bits: 0b11 MPEG-1, 0b10 MPEG-2, 0b00 MPEG-2.5
# (the unofficial extension to 8/11.025/12 kHz that LAME and ffmpeg write;
# 0b01 is reserved and therefore absent).
_MP3_KBPS = {3: _MP3_KBPS_V1, 2: _MP3_KBPS_V2, 0: _MP3_KBPS_V2}
_MP3_SAMPLE_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}
# The one thing allowed after the last frame: a fixed-size ID3v1 tag.
_MP3_ID3V1_BYTES = 128


def _mp3_frame(header: bytes) -> tuple[int, tuple[int, bool]]:
    """`(frame_length, stream_parameters)` of one 4-byte Layer III header.

    Refuses a truncated header, a missing sync word, the reserved version
    and every layer but III, "free"/"bad" bitrates, the reserved sample-rate
    index and the reserved emphasis value. `stream_parameters` is what must
    stay identical from the first frame to the last: the sample rate (which
    also pins the MPEG version, the three versions share no rate) and
    whether the stream is mono.
    """

    if len(header) != 4:
        raise AssetValidationError("MP3 frame header is truncated")
    if header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        raise AssetValidationError("MP3 frame sync is missing")
    version = (header[1] >> 3) & 3
    layer = (header[1] >> 1) & 3
    if version == 1 or layer != 1:
        raise AssetValidationError("MP3 frame is not MPEG Layer III")
    kbps = _MP3_KBPS[version][header[2] >> 4]
    rate_index = (header[2] >> 2) & 3
    if kbps is None or rate_index == 3 or header[3] & 3 == 2:
        raise AssetValidationError("MP3 frame header fields are invalid")
    sample_rate = _MP3_SAMPLE_RATES[version][rate_index]
    padding = (header[2] >> 1) & 1
    length = (144 if version == 3 else 72) * kbps * 1000 // sample_rate + padding
    return length, (sample_rate, header[3] >> 6 == 3)


def _mp3_id3v2_end(data: bytes) -> int:
    """Offset just past the leading ID3v2 tag: header, body and any footer.

    The declared size is synchsafe (seven bits per byte) and must fit in the
    file. The header flags must be ones the tag's version defines and a
    decoder can honour: ID3v2.2's "compression" bit is not one of them (the
    spec has no scheme for it, and a decoder ignores the whole tag). The tag
    body itself is opaque; the frame chain that has to start exactly at the
    returned offset is what proves the size was right.
    """

    if len(data) < 10:
        raise AssetValidationError("ID3v2 header is truncated")
    major, revision, flags = data[3], data[4], data[5]
    if major not in (2, 3, 4) or revision == 0xFF:
        raise AssetValidationError("ID3v2 version is unsupported")
    if flags & ~{2: 0x80, 3: 0xE0, 4: 0xF0}[major]:
        raise AssetValidationError("ID3v2 flags are invalid")
    if any(byte & 0x80 for byte in data[6:10]):
        raise AssetValidationError("ID3v2 size is not synchsafe")
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    footer = 10 if major == 4 and flags & 0x10 else 0
    end = 10 + size + footer
    if end > len(data):
        raise AssetValidationError("ID3v2 tag exceeds the file size")
    if footer and data[end - 10 : end] != b"3DI" + data[3:10]:
        raise AssetValidationError("ID3v2 footer does not mirror its header")
    return end


def _mp3(data: bytes) -> tuple[str, None, None] | None:
    tagged = data.startswith(b"ID3")
    if not tagged and not (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return None
    offset = _mp3_id3v2_end(data) if tagged else 0
    end = len(data)
    frames = 0
    stream = None
    # Frame headers repeat (constant bitrate has two variants, the padding
    # bit), so each distinct header is parsed once. Fewer than 200,000
    # distinct headers can be valid at all, which bounds this cache.
    known: dict[bytes, tuple[int, tuple[int, bool]]] = {}
    while offset < end:
        # A trailing ID3v1 tag is the one thing allowed after the last
        # frame: exactly 128 bytes starting with "TAG", at a frame boundary
        # (a frame header can never start with "T", so this is unambiguous).
        if frames and end - offset == _MP3_ID3V1_BYTES and data[offset : offset + 3] == b"TAG":
            offset = end
            break
        header = data[offset : offset + 4]
        parsed = known.get(header)
        if parsed is None:
            parsed = known[header] = _mp3_frame(header)
        length, parameters = parsed
        if stream is None:
            stream = parameters
        elif parameters != stream:
            raise AssetValidationError("MP3 stream parameters change between frames")
        offset += length
        if offset > end:
            raise AssetValidationError("MP3 frame is truncated")
        frames += 1
    if not frames:
        raise AssetValidationError("MP3 contains no audio frames")
    return "audio/mpeg", None, None


# Only PCM and IEEE float are accepted, directly (format tags 1 and 3) or as
# the sub-format of WAVE_FORMAT_EXTENSIBLE (0xFFFE), which ffmpeg writes for
# anything above 16 bits, 48 kHz or two channels.
_WAV_SAMPLE_BITS = {1: (8, 16, 24, 32), 3: (32, 64)}
_WAV_EXTENSIBLE_TAIL = b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
_WAV_MAX_CHANNELS = 64
_WAV_MAX_SAMPLE_RATE = 768_000
# Padding chunks must hold only zero bytes (a `JUNK` chunk is the classic
# place to hide an active payload); the metadata chunks below are opaque,
# like WebP's EXIF/XMP, and `fact` only has to hold its sample count. Any
# other chunk id is refused, as WebP does.
_WAV_FILLER_CHUNKS = frozenset({b"JUNK", b"PAD ", b"FLLR"})
_WAV_METADATA_CHUNKS = frozenset(
    {b"LIST", b"bext", b"cue ", b"smpl", b"inst", b"id3 ", b"iXML", b"PEAK"}
)


def _wav_block_align(fmt: bytes) -> int:
    """Validate a `fmt ` chunk and return its block align (bytes per frame)."""

    if len(fmt) not in (16, 18, 40):
        raise AssetValidationError("WAV fmt chunk size is unsupported")
    tag, channels, sample_rate, byte_rate, block_align, bits = struct.unpack_from(
        "<HHIIHH", fmt
    )
    if len(fmt) > 16 and struct.unpack_from("<H", fmt, 16)[0] != len(fmt) - 18:
        raise AssetValidationError("WAV fmt extension size is invalid")
    if tag == 0xFFFE:
        if len(fmt) != 40:
            raise AssetValidationError("WAV extensible format is invalid")
        valid_bits = struct.unpack_from("<H", fmt, 18)[0]
        subformat = fmt[24:40]
        if subformat[4:] != _WAV_EXTENSIBLE_TAIL or not 0 < valid_bits <= bits:
            raise AssetValidationError("WAV extensible format is invalid")
        tag = struct.unpack_from("<I", subformat)[0]
    elif len(fmt) == 40:
        raise AssetValidationError("WAV fmt chunk size does not match its format")
    if tag not in _WAV_SAMPLE_BITS:
        raise AssetValidationError(f"WAV format {tag:#06x} is neither PCM nor IEEE float")
    if bits not in _WAV_SAMPLE_BITS[tag]:
        raise AssetValidationError("WAV sample size is unsupported")
    if not 1 <= channels <= _WAV_MAX_CHANNELS or not 1 <= sample_rate <= _WAV_MAX_SAMPLE_RATE:
        raise AssetValidationError("WAV channel count or sample rate is invalid")
    frame_bytes = channels * (bits // 8)
    if block_align != frame_bytes or byte_rate != sample_rate * frame_bytes:
        raise AssetValidationError("WAV fmt chunk is internally inconsistent")
    return block_align


def _wav(data: bytes) -> tuple[str, None, None] | None:
    if not (data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE"):
        return None
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise AssetValidationError("WAV RIFF size is invalid")
    offset = 12
    block_align = None
    saw_data = False
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + size
        padded_end = end + (size & 1)
        if padded_end > len(data):
            raise AssetValidationError("WAV chunk is truncated")
        if size & 1 and data[end] != 0:
            raise AssetValidationError("WAV padding byte must be zero")
        if kind == b"fmt ":
            if block_align is not None:
                raise AssetValidationError("WAV fmt chunk is duplicated")
            block_align = _wav_block_align(data[start:end])
        elif kind == b"data":
            if block_align is None or saw_data:
                raise AssetValidationError("WAV data chunk is duplicated or precedes fmt")
            if size == 0 or size % block_align:
                raise AssetValidationError("WAV data size does not match its frame size")
            saw_data = True
        elif kind in _WAV_FILLER_CHUNKS:
            if data.count(b"\x00", start, end) != size:
                raise AssetValidationError("WAV filler chunk must be zero bytes")
        elif kind == b"fact":
            if size < 4:
                raise AssetValidationError("WAV fact chunk is truncated")
        elif kind not in _WAV_METADATA_CHUNKS:
            raise AssetValidationError(f"WAV contains an unsupported chunk {kind!r}")
        offset = padded_end
    if offset != len(data) or block_align is None or not saw_data:
        raise AssetValidationError("WAV chunk layout is invalid")
    return "audio/wav", None, None


_DETECTORS = (_png, _jpeg, _webp, _mp4, _webm, _mp3, _wav)


def _inspect_media(data: bytes) -> tuple[str, int | None, int | None]:
    for detector in _DETECTORS:
        result = detector(data)
        if result is not None:
            return result
    raise AssetValidationError("file is not a supported media signature")


class AssetIndex:
    """Map validated files below explicit project roots to opaque asset ids.

    Ticket 12: the id -> (relative path, mime, dimensions, digest, role)
    mapping is durable, in a small SQLite file at `db_path` (default
    `<root>/.studio/assets.sqlite3`) -- not the in-process dict this class
    used to keep. `register()` and `resolve()` keep the exact signatures
    every existing caller (server.py, the CLI, every test in this build)
    already uses; only the storage behind them changed, so an id one
    process registers resolves correctly in a different process that opens
    the same `root`/`db_path`, and survives a restart. A connection is
    opened and closed per call, mirroring `QuestionStore`/`ActionLedger` in
    this same package, rather than held for the object's lifetime -- so a
    server's long-lived `AssetIndex` and a short-lived CLI one never
    contend over one held handle.
    """

    def __init__(self, root, allowed_roots, max_bytes, *, db_path=None, montage_max_bytes=None):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise AssetValidationError("root must be a directory")
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes <= 0
        ):
            raise AssetValidationError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes
        if montage_max_bytes is not None and (
            isinstance(montage_max_bytes, bool)
            or not isinstance(montage_max_bytes, int)
            or montage_max_bytes <= 0
        ):
            raise AssetValidationError("montage_max_bytes must be a positive integer")
        self.montage_max_bytes = montage_max_bytes
        roots = []
        for raw_root in allowed_roots:
            candidate = Path(raw_root)
            if not candidate.is_absolute():
                candidate = self.root / candidate
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as error:
                raise AssetValidationError("allowed root does not exist") from error
            if not resolved.is_dir() or not _within(resolved, self.root):
                raise AssetValidationError("allowed roots must be directories below root")
            roots.append(resolved)
        if not roots:
            raise AssetValidationError("at least one allowed root is required")
        self.allowed_roots = tuple(dict.fromkeys(roots))
        self.db_path = (
            Path(db_path) if db_path is not None else self.root / PRIVATE_DIR_NAME / ASSETS_DB_NAME
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_db()

    def _secure_sqlite_files(self):
        # Ticket 12 repair, blocking condition 6: the exact same fail-closed
        # symlink/mode-0600 guard `QuestionStore` already uses for its own
        # private SQLite file, reused rather than re-implemented -- see
        # `questions.secure_sqlite_path`'s own docstring.
        secure_sqlite_path(self.db_path, error=AssetError)

    def _connect(self):
        self._secure_sqlite_files()
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            self._secure_sqlite_files()
            return connection
        except Exception:
            connection.close()
            raise

    def _initialize_db(self):
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            self._secure_sqlite_files()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    digest TEXT NOT NULL,
                    role TEXT NOT NULL
                );
                """
            )
        finally:
            connection.close()
        self._secure_sqlite_files()

    def __len__(self):
        connection = self._connect()
        try:
            return connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        finally:
            connection.close()

    def _is_reserved_project_path(self, resolved: Path) -> bool:
        """True if `resolved` names, or is nested inside, a directory
        called `nocturne-47`, walking up from `resolved` to `self.root`.

        Ticket 12 repair, condition 5: `store.ProjectStore` already
        excludes that reserved project by its resolved name
        (`ProjectStore._is_excluded`); `AssetIndex` had no equivalent
        check at all. Without it, a `media/` directory that is itself a
        symlink into `nocturne-47` (or that has one nested somewhere
        inside it) would resolve every file below it straight into that
        reserved project -- `__init__`'s own `allowed_roots` check only
        confirms a root is a real directory below `self.root`, and
        `resolved.is_relative_to(...)` says nothing about which project
        directory a path actually lands in once symlinks are followed.
        Applied here, inside `_resolve_candidate`, so both `register()`
        and `resolve()` (which calls this too) refuse every such path,
        however deep it is nested -- not only when `media/` itself is
        the reserved directory.
        """

        current = resolved
        while True:
            if current.name == "nocturne-47":
                return True
            if current == self.root:
                return False
            parent = current.parent
            if parent == current:
                return False
            current = parent

    def _resolve_candidate(self, path) -> Path:
        if not isinstance(path, (str, os.PathLike)):
            raise AssetValidationError("path must be relative to the project root")
        # A stored `relative_path` is POSIX text; on Windows `Path()` of it
        # would turn every `/` into the `\\` refused just below.
        raw = path.as_posix() if isinstance(path, PurePath) else os.fspath(path)
        if not raw or "\x00" in raw or "\\" in raw:
            raise AssetValidationError("path must be a portable relative path")
        candidate = Path(raw)
        # `anchor` also catches Windows' rooted `\x` and drive-relative `C:x`.
        if candidate.anchor or ".." in candidate.parts:
            raise AssetValidationError("absolute paths and traversal are forbidden")
        try:
            resolved = (self.root / candidate).resolve(strict=True)
        except OSError as error:
            raise AssetValidationError("asset file does not exist") from error
        if self._is_reserved_project_path(resolved):
            raise AssetValidationError("asset path is inside the reserved nocturne-47 project")
        if not any(_within(resolved, allowed) for allowed in self.allowed_roots):
            raise AssetValidationError("asset path is outside allowed roots")
        try:
            mode = resolved.stat().st_mode
        except OSError as error:
            raise AssetValidationError("asset file cannot be inspected") from error
        if not stat.S_ISREG(mode):
            raise AssetValidationError("asset path must name a regular file")
        return resolved

    def _size_limit(self, resolved: Path) -> int:
        """Собранный ролик монтажа (<медиа>/<проект>/montage/vNNN.mp4) — свой предел;
        любой другой файл, в том числе .mp4 рядом, — общий max_bytes."""

        if self.montage_max_bytes:
            for allowed in self.allowed_roots:
                if _within(resolved, allowed) and _MONTAGE_OUTPUT.fullmatch(
                        resolved.relative_to(allowed).as_posix()):
                    return max(self.max_bytes, self.montage_max_bytes)
        return self.max_bytes

    def _inspect_path(self, resolved: Path):
        limit = self._size_limit(resolved)
        extension = resolved.suffix.casefold()
        if extension in _DANGEROUS_EXTENSIONS or extension not in _EXTENSION_MIME:
            raise AssetValidationError("asset extension is not allowed")
        try:
            size = resolved.stat().st_size
            if size <= 0 or size > limit:
                raise AssetValidationError("asset size is outside the allowed range")
            data = resolved.read_bytes()
        except AssetValidationError:
            raise
        except OSError as error:
            raise AssetValidationError("asset file cannot be read") from error
        if len(data) != size or len(data) > limit:
            raise AssetValidationError("asset changed while it was inspected")
        mime_type, width, height = _inspect_media(data)
        if _EXTENSION_MIME[extension] != mime_type:
            raise AssetValidationError("asset extension does not match its signature")
        digest = hashlib.sha256(data).hexdigest()
        return data, digest, mime_type, width, height

    def register(self, path, role) -> dict:
        if role not in ASSET_ROLES:
            raise AssetValidationError("unsupported asset role")
        resolved = self._resolve_candidate(path)
        data, digest, mime_type, width, height = self._inspect_path(resolved)
        relative_path = resolved.relative_to(self.root).as_posix()
        opaque = hashlib.sha256(
            relative_path.encode("utf-8") + b"\0" + bytes.fromhex(digest)
        ).hexdigest()[:32]
        asset_id = f"asset-{opaque}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._secure_sqlite_files()
            try:
                # `INSERT OR REPLACE` keyed by `asset_id`: re-registering the
                # exact same file (same relative path + content digest, the
                # only two inputs `asset_id` is derived from) is idempotent
                # by construction -- every other column is recomputed to the
                # same value.
                #
                # Ticket 13 (spec §3, "роль актива неизменна"): `role` is
                # the one column that could legitimately differ between two
                # `register()` calls for the same file -- ticket 12's
                # version let the later call win silently, which let a
                # second registration bypass the role check every write
                # path that *links* an asset in (`add_result_version`,
                # `add_reference`, `set_assembly`) otherwise enforces. A
                # role is now fixed at an asset's first registration:
                # registering the same file again under a *different* role
                # refuses outright, before anything is written, and the
                # existing row is untouched. The *same* role stays
                # idempotent, matching a caller that legitimately registers
                # one file more than once for the same purpose.
                existing = connection.execute(
                    "SELECT role FROM assets WHERE asset_id = ?", (asset_id,)
                ).fetchone()
                if existing is not None and existing["role"] != role:
                    raise AssetValidationError(
                        "asset is already registered with a different role"
                    )
                connection.execute(
                    "INSERT OR REPLACE INTO assets "
                    "(asset_id, relative_path, mime_type, size_bytes, width, height, "
                    "digest, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        asset_id,
                        relative_path,
                        mime_type,
                        len(data),
                        width,
                        height,
                        digest,
                        role,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        finally:
            connection.close()
        return {
            "asset_id": asset_id,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "width": width,
            "height": height,
            "role": role,
        }

    def resolve(self, asset_id) -> tuple[Path, str]:
        if not isinstance(asset_id, str) or not asset_id:
            raise AssetNotFound(str(asset_id))
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT relative_path, mime_type, width, height, digest "
                "FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise AssetNotFound(asset_id)
        resolved = self._resolve_candidate(Path(row["relative_path"]))
        _, digest, mime_type, width, height = self._inspect_path(resolved)
        if (
            digest != row["digest"]
            or mime_type != row["mime_type"]
            or width != row["width"]
            or height != row["height"]
        ):
            raise AssetValidationError("registered asset has changed")
        return resolved, mime_type

    def role_of(self, asset_id) -> str:
        """The role `asset_id` was registered with (ticket 12 repair,
        condition 6): a plain metadata lookup, no file re-inspection --
        `role` is assigned once at `register()` time and never derived
        from file bytes, unlike `mime_type`/`width`/`height`, so it needs
        none of `resolve()`'s own re-decode-and-compare work. Callers
        that also need the file itself (`add_result_version`/
        `add_reference`/`set_assembly`) still call `resolve()` too, for
        that integrity check; this only answers "which purpose was this
        asset registered for."
        """

        if not isinstance(asset_id, str) or not asset_id:
            raise AssetNotFound(str(asset_id))
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT role FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise AssetNotFound(asset_id)
        return row["role"]
