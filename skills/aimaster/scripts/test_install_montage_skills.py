#!/usr/bin/env python3
"""Скиллы HyperFrames в кеше: сверка с выпуском, скачивание, отчёт установщика."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install_montage_fetch as fetch  # noqa: E402
import install_montage_skills as skills  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.skill_bundle import bundle_hash, verify_skills  # noqa: E402

FILES = {
    "demo/SKILL.md": b"---\nname: demo\n---\r\nhello\r\n",
    "demo/scripts/run.py": b"print(1)\r\n",
    "demo/a.json": b'{"a":1}',
    "other/SKILL.md": b"---\nname: other\n---\n",
}
PIN = {"repo": "heygen-com/hyperframes", "tag": "v9.9.9", "commit": "c" * 40, "tree": "t" * 40,
       "bundles": {"demo": {"hash": "82e2a555abf32641", "files": 3},
                   "other": {"hash": "05d1df8575671f97", "files": 1}}}


def tree_for(files):
    return [{"path": path, "type": "blob", "sha": fetch.git_blob_sha(data),
             "mode": "100755" if path.endswith(".py") else "100644"} for path, data in files.items()]


class FakeFetcher:
    def __init__(self, files):
        self.files = dict(files)
        self.gets = []

    def get(self, rel_path):
        self.gets.append(rel_path)
        return self.files[rel_path]

    def close(self):
        pass


class _Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def write(self, root: Path, files=FILES):
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        return root


class HashTests(_Temp):
    def test_git_blob_sha_matches_git(self):
        self.assertEqual(fetch.git_blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_bundle_hash_matches_reference_vectors(self):
        root = self.write(self.base / "skills")
        self.assertEqual(bundle_hash(root / "demo"), ("82e2a555abf32641", 3))
        self.assertEqual(bundle_hash(root / "other"), ("05d1df8575671f97", 1))

    def test_crlf_is_normalized_only_in_text_files(self):
        lf = dict(FILES, **{"demo/SKILL.md": b"---\nname: demo\n---\nhello\n"})
        root = self.write(self.base / "lf", lf)
        self.assertEqual(bundle_hash(root / "demo")[0], "82e2a555abf32641")
        py_lf = dict(FILES, **{"demo/scripts/run.py": b"print(1)\n"})
        root = self.write(self.base / "py", py_lf)
        self.assertNotEqual(bundle_hash(root / "demo")[0], "82e2a555abf32641")


class TreeTests(unittest.TestCase):
    def opener(self, payload):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return lambda request, timeout=None, context=None: Response(json.dumps(payload).encode())

    def test_keeps_only_pinned_skills_blobs(self):
        payload = {"truncated": False, "tree": tree_for(FILES) + [
            {"path": "figma/SKILL.md", "type": "blob", "sha": "x"},
            {"path": "demo", "type": "tree", "sha": "y"}]}
        paths = [item["path"] for item in fetch.fetch_tree(PIN, opener=self.opener(payload))]
        self.assertEqual(sorted(paths), sorted(FILES))

    def test_truncated_tree_is_refused(self):
        with self.assertRaises(OSError):
            fetch.fetch_tree(PIN, opener=self.opener({"truncated": True, "tree": []}))


class SslTests(unittest.TestCase):
    def test_empty_python_store_falls_back_to_the_system_bundle(self):
        loaded = []
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 0}),
                         load_verify_locations=lambda cafile: loaded.append(cafile))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake), \
                mock.patch.object(fetch.os.path, "isfile", side_effect=lambda path: path == "/etc/ssl/cert.pem"):
            self.assertIs(fetch.ssl_context(), fake)
        self.assertEqual(loaded, ["/etc/ssl/cert.pem"])

    def test_filled_store_is_left_alone(self):
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 150}))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake):
            fetch.ssl_context()
        fake.load_verify_locations.assert_not_called()


class DownloadTests(_Temp):
    def test_download_verifies_and_places_the_bundle(self):
        dest = self.base / "hyperframes-skills" / "v9.9.9"
        fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual(verify_skills(dest, PIN), [])
        if os.name != "nt":
            self.assertTrue(os.access(dest / "demo" / "scripts" / "run.py", os.X_OK))

    def test_tampered_file_leaves_nothing(self):
        dest = self.base / "hyperframes-skills" / "v9.9.9"
        bad = dict(FILES, **{"demo/a.json": b'{"a":2}'})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(bad))
        self.assertIn("git sha", str(caught.exception))
        self.assertFalse(dest.exists())
        self.assertEqual(list((self.base / "hyperframes-skills").iterdir()), [])

    def test_wrong_bundle_hash_is_refused(self):
        pin = dict(PIN, bundles={**PIN["bundles"], "demo": {"hash": "0" * 16, "files": 3}})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(pin, self.base / "d", tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertIn("demo", str(caught.exception))


class ReportTests(_Temp):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "tools" / "hyperframes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = self.base / "tools" / "hyperframes-skills" / "v9.9.9"

    def test_check_only_never_downloads(self):
        fetcher = FakeFetcher({})
        report = skills.skills_report(act=False, pin=PIN, tree=[], fetcher=fetcher)
        self.assertEqual((report["status"], report["path"]), ("missing", str(self.cache)))
        self.assertEqual(fetcher.gets, [])

    def test_act_downloads_into_the_cache_then_finds_it(self):
        report = skills.skills_report(act=True, pin=PIN, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual((report["status"], report["version"]), ("installed", "v9.9.9"))
        self.assertEqual(verify_skills(self.cache, PIN), [])
        again = skills.skills_report(act=True, pin=PIN, tree=[], fetcher=FakeFetcher({}))
        self.assertEqual(again["status"], "found")

    def test_rate_limit_message(self):
        error = skills.urllib.error.HTTPError("https://api.github.com", 403, "rate limit", {}, None)
        with mock.patch.object(skills, "download_skills", side_effect=error):
            report = skills.skills_report(act=True, pin=PIN)
        self.assertEqual(report["status"], "failed")
        self.assertIn("через час", report["message"])


if __name__ == "__main__":
    unittest.main()
