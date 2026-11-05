"""Bounded Telegram attachment intake. Names never become paths or commands."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import zlib

from .assets import AssetIndex
from .family_setup.state import write_bytes, write_json
from .workspace import resolve_workspace_paths

MAX_DOWNLOAD = 20 * 1024 * 1024


def attachment(message):
    if not isinstance(message, dict):
        return None
    candidates = message.get("photo")
    if isinstance(candidates, list) and candidates:
        item, kind = candidates[-1], "photo"
    else:
        kind = next((key for key in ("video", "voice", "audio", "document") if isinstance(message.get(key), dict)), None)
        if kind is None:
            return None
        item = message[kind]
    if not isinstance(item, dict) or not isinstance(item.get("file_id"), str) or not item["file_id"] or len(item["file_id"]) > 1024:
        raise ValueError("invalid Telegram attachment identity")
    size = item.get("file_size", 0)
    if type(size) is not int or not 0 <= size <= MAX_DOWNLOAD:
        raise ValueError("Telegram attachment exceeds 20 MiB")
    identity = item.get("file_unique_id", item["file_id"])
    if not isinstance(identity, str) or not identity or len(identity) > 1024:
        raise ValueError("invalid Telegram attachment identity")
    return {"kind": kind, "file_id": item["file_id"], "file_unique_id": item.get("file_unique_id", item["file_id"]),
            "file_size": size}


def _extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if data.startswith(b"\xff\xd8\xff"): return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return ".webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE": return ".wav"
    if len(data) >= 12 and data[4:8] == b"ftyp": return ".mp4"
    if data.startswith(b"\x1aE\xdf\xa3"): return ".webm"
    if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}: return ".mp3"
    if data.startswith(b"OggS") and (b"OpusHead" in data[:256] or b"vorbis" in data[:256]): return ".ogg"
    if data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]: return ".pdf"
    if data.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2048 or sum(entry.file_size for entry in entries) > MAX_DOWNLOAD * 3:
                raise ValueError("document archive is too large")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                raise ValueError("unsupported document archive")
            if any(entry.filename.startswith(("/", "\\")) or ".." in Path(entry.filename).parts or
                   "vbaProject" in entry.filename for entry in entries):
                raise ValueError("unsafe document archive")
            if any(entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                   for entry in entries):
                raise ValueError("unsupported document archive encoding")
            if archive.testzip() is not None:
                raise ValueError("document archive checksum failed")
        return ".docx"
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise ValueError("unsupported attachment container") from None
    if not text.strip() or "\x00" in text or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ValueError("unsupported text document")
    return ".txt"


def download(workspace, update_id, spec, downloader):
    ws, _, _, private = resolve_workspace_paths(workspace)
    if private.is_symlink():
        raise ValueError("unsafe private workspace directory")
    identity = hashlib.sha256((str(update_id) + ":" + spec["file_unique_id"]).encode()).hexdigest()
    folder = private / "telegram-incoming" / identity
    if folder.is_symlink() or not folder.resolve().is_relative_to(private.resolve()):
        raise ValueError("unsafe incoming directory")
    metadata = folder / "attachment.json"
    if metadata.is_file() and not metadata.is_symlink():
        descriptor = json.loads(metadata.read_text(encoding="utf-8"))
        source = ws / descriptor["path"]
        if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != descriptor["sha256"]:
            raise ValueError("incoming attachment changed")
        return descriptor
    if downloader is None:
        raise ValueError("download unavailable; send the description as text")
    data = downloader(spec)
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_DOWNLOAD:
        raise ValueError("attachment is empty or exceeds 20 MiB")
    try:
        extension = _extension(data)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        # Container/codec/encryption errors must become the same durable refusal
        # as other invalid uploads, without reflecting untrusted archive names.
        raise ValueError("unsupported or corrupt document archive") from None
    if spec["kind"] == "photo" and extension not in {".png", ".jpg", ".webp"}:
        raise ValueError("photo has an invalid container")
    if spec["kind"] == "video" and extension not in {".mp4", ".webm"}:
        raise ValueError("video has an invalid container")
    if spec["kind"] in {"voice", "audio"} and extension not in {".wav", ".mp3", ".ogg", ".mp4"}:
        raise ValueError("audio has an invalid container")
    source = folder / ("source" + extension)
    write_bytes(source, data)
    if extension == ".ogg" or extension == ".mp4" and spec["kind"] in {"voice", "audio"}:
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise ValueError("audio decoding unavailable; send the description as text")
        decoded = folder / "decoded.wav"
        try:
            result = subprocess.run([executable, "-nostdin", "-v", "error", "-i", str(source),
                "-t", "601", "-ac", "1", "-ar", "16000", "-y", str(decoded)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("audio decoding failed; send the description as text") from None
        if result.returncode != 0 or not decoded.is_file() or decoded.stat().st_size > MAX_DOWNLOAD:
            raise ValueError("audio decoding failed; send the description as text")
        import wave
        with wave.open(str(decoded), "rb") as audio:
            if audio.getnframes() / audio.getframerate() > 600:
                raise ValueError("audio exceeds ten minutes; send a shorter file or text")
        source, extension = decoded, ".wav"
    if extension not in {".txt", ".pdf", ".docx"}:
        # Existing signature/container validation, without fixing a canonical asset
        # role before the user/agent has classified this upload's intended use.
        with tempfile.TemporaryDirectory(dir=folder) as validation:
            index = AssetIndex(ws, (folder,), max_bytes=MAX_DOWNLOAD, db_path=Path(validation) / "validation.sqlite3")
            index.register(source.relative_to(ws).as_posix(), "other")
    descriptor = {"source": "telegram", "kind": spec["kind"], "update_id": update_id,
        "file_identity": hashlib.sha256(spec["file_unique_id"].encode()).hexdigest(),
        "path": source.relative_to(ws).as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "size_bytes": source.stat().st_size, "transcription": "unavailable" if spec["kind"] in {"voice", "audio"} else "not_applicable"}
    write_json(metadata, descriptor)
    return descriptor


def materialize(workspace, project_id, descriptor):
    ws, _, media, private = resolve_workspace_paths(workspace)
    if private.is_symlink() or media.is_symlink() or not media.resolve().is_relative_to(ws):
        raise ValueError("unsafe upload root")
    source = ws / descriptor["path"]
    if source.is_symlink() or not source.resolve().is_relative_to((private / "telegram-incoming").resolve()) or \
            hashlib.sha256(source.read_bytes()).hexdigest() != descriptor["sha256"]:
        raise ValueError("incoming attachment changed")
    destination = media / project_id / "uploads" / (descriptor["sha256"] + source.suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(media.resolve()):
        raise ValueError("unsafe upload destination")
    if not destination.exists():
        write_bytes(destination, source.read_bytes())
    if hashlib.sha256(destination.read_bytes()).hexdigest() != descriptor["sha256"]:
        raise ValueError("upload destination changed")
    return {**descriptor, "path": destination.relative_to(ws).as_posix()}
