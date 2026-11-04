"""Small, independently constructed JPEGs for public asset validation.

The fixtures encode an 8x8 uniform grey block: DC difference zero, AC EOB.
They contain no copied Telegram bytes, metadata, or third-party image.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.assets import AssetIndex, AssetValidationError


def segment(marker, payload):
    return bytes((255, marker)) + struct.pack(">H", len(payload) + 2) + payload


def table(kind, identity):
    # One 1-bit Huffman code (0), for DC category 0 or AC end-of-block.
    return segment(0xC4, bytes((kind << 4 | identity, 1)) + bytes(15) + b"\x00")


def scan(components, start, end, high, low, *, entropy=b"\x7f"):
    return segment(0xDA, bytes((len(components),)) + bytes(value for pair in components for value in pair)
                   + bytes((start, end, high << 4 | low))) + entropy


def grey_jpeg(*, progressive=True, dc=True, ac=True, ac_selector=0,
              first_band=(0, 0, 0, 1), refinement=(0, 0, 1, 0),
              ac_band=(1, 63, 0, 0), ac_components=((1, 0),), extra_dac=False):
    header = b"\xff\xd8" + segment(0xDB, b"\x00" + bytes((1,)) * 64)
    ids = (1, 2) if len(ac_components) > 1 else (1,)
    frame = bytes((8,)) + struct.pack(">HH", 8, 8) + bytes((len(ids),))
    frame += bytes(value for identity in ids for value in (identity, 0x11, 0))
    header += segment(0xC2 if progressive else 0xC0, frame)
    if extra_dac:
        header += segment(0xCC, b"\x00\x10")
    if dc:
        header += table(0, 1)
    if not progressive:
        if ac:
            header += table(1, 0)
        # A sequential scan needs both the DC code and AC EOB: 00 + padding.
        return header + scan(((1, 0x10),), 0, 63, 0, 0, entropy=b"\x3f") + b"\xff\xd9"
    # No AC table yet: the initial DC scan uses only DC table 1.
    header += scan(tuple((identity, 0x10) for identity in ids), *first_band,
                   entropy=b"\x3f" if len(ids) > 1 else b"\x7f")
    # Refinement has no Huffman coding. DC table 0 and AC table 0 are absent.
    header += scan(tuple((identity, 0) for identity in ids), *refinement,
                   entropy=b"\x3f" if len(ids) > 1 else b"\x7f")
    if ac:
        header += table(1, 0)
    # AC scan uses only AC table 0; DC table 0 still does not exist.
    components = tuple((identity, ac_selector if len(ac_components) == 1 else selector)
                       for identity, selector in ac_components)
    return header + scan(components, *ac_band) + b"\xff\xd9"


class ProgressiveJpegAssetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.media = self.root / "media"; self.media.mkdir()
        self.index = AssetIndex(self.root, (self.media,), max_bytes=1024 * 1024)

    def register(self, data):
        (self.media / "probe.jpg").write_bytes(data)
        return self.index.register("media/probe.jpg", "other")

    def test_progressive_dc_initial_refinement_and_ac_use_only_their_required_tables(self):
        record = self.register(grey_jpeg())
        self.assertEqual((record["mime_type"], record["width"], record["height"]), ("image/jpeg", 8, 8))
        path, mime = self.index.resolve(record["asset_id"])
        self.assertEqual(path.read_bytes(), grey_jpeg())
        self.assertEqual(mime, "image/jpeg")

    def test_actual_missing_dc_or_ac_table_is_refused(self):
        for options in ({"dc":False}, {"ac":False}, {"ac_selector":1}, {"dc":False,"extra_dac":True}):
            with self.subTest(options=options), self.assertRaisesRegex(AssetValidationError, "missing table"):
                self.register(grey_jpeg(**options))
        self.assertEqual(len(self.index), 0)

    def test_baseline_still_requires_both_huffman_tables(self):
        record = self.register(grey_jpeg(progressive=False))
        self.assertEqual(record["mime_type"], "image/jpeg")
        for options in ({"dc":False}, {"ac":False}):
            with self.subTest(options=options), self.assertRaisesRegex(AssetValidationError, "missing table"):
                self.register(grey_jpeg(progressive=False, **options))

    def test_progressive_scan_headers_and_components_remain_constrained(self):
        for options in (
            {"first_band":(0,1,0,1)}, {"ac_band":(1,64,0,0)},
            {"ac_band":(3,2,0,0)}, {"refinement":(0,0,2,0)},
            {"refinement":(0,0,2,1)},
            {"first_band":(0,0,0,14)}, {"ac_components":((1,0),(2,0))},
        ):
            with self.subTest(options=options), self.assertRaises(AssetValidationError):
                self.register(grey_jpeg(**options))
        with self.assertRaises(AssetValidationError):
            self.register(grey_jpeg()[:-1])
        without_initial_dc = grey_jpeg().replace(scan(((1, 0x10),), 0, 0, 0, 1), b"", 1)
        with self.assertRaisesRegex(AssetValidationError, "progression"):
            self.register(without_initial_dc)


if __name__ == "__main__":
    unittest.main()
