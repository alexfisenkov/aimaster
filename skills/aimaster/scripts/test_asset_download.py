#!/usr/bin/env python3
"""«Скачать»: ролик монтажа — «<название проекта>-vNNN.mp4», прочие файлы —
своим именем; `?download=1` пускается только на /assets/<id>."""

from __future__ import annotations

import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import isolate_hyperframes_dir, seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.asset_download import content_disposition, download_names  # noqa: E402
from studio.authoring_support import open_assets  # noqa: E402
from studio.server import serve  # noqa: E402


class DownloadNameTests(unittest.TestCase):
    def test_montage_video_is_named_after_the_project_and_version(self):
        self.assertEqual(download_names("media/p/montage/v003.mp4", lambda project: "Проба монтажа"),
                         ("Проба монтажа-v003.mp4", "p-v003.mp4"))

    def test_forbidden_characters_and_line_breaks_are_dropped(self):
        name, fallback = download_names("media/p/montage/v001.mp4",
                                        lambda project: 'Кот «Барсик»: сад/вечер\r\n"?*')
        self.assertEqual((name, fallback), ("Кот «Барсик» сад вечер-v001.mp4", "p-v001.mp4"))

    def test_long_title_is_cut(self):
        name, _fallback = download_names("media/p/montage/v001.mp4", lambda project: "а" * 300)
        self.assertEqual(name, "а" * 80 + "-v001.mp4")

    def test_without_title_the_project_id_is_used(self):
        self.assertEqual(download_names("media/zz-1/montage/v002.mp4", lambda project: None),
                         ("zz-1-v002.mp4", "zz-1-v002.mp4"))

    def test_cyrillic_project_id_gets_a_latin_fallback(self):
        self.assertEqual(download_names("media/проект/montage/v001.mp4", lambda project: None),
                         ("проект-v001.mp4", "montage-v001.mp4"))

    def test_other_files_keep_their_own_name(self):
        self.assertEqual(download_names("media/clip 1.mp4", lambda project: "x"), ("clip 1.mp4", "clip-1.mp4"))
        self.assertEqual(download_names("media/клип.mp4", lambda project: "x"), ("клип.mp4", "file.mp4"))

    def test_header_carries_both_names(self):
        self.assertEqual(content_disposition("Проба-v001.mp4", "p-v001.mp4"),
                         "attachment; filename=\"p-v001.mp4\"; filename*=UTF-8''"
                         + quote("Проба-v001.mp4", safe=""))


class DownloadRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, base)
        seed = seed_workspace(base, {"a.mp4": tiny_mp4(b"a")}, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])]))
        folder = seed.media / "p" / "montage"
        folder.mkdir(parents=True)
        (folder / "v001.mp4").write_bytes(tiny_mp4(b"version-1"))
        self.version = open_assets(seed.workspace).register("media/p/montage/v001.mp4", "result")["asset_id"]
        self.running = serve(seed.workspace)
        self.addCleanup(self.running.close)
        self.port = int(self.running.base_url.rsplit(":", 1)[1])

    def get(self, target, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", target, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Disposition"), response.read()
        finally:
            connection.close()

    def test_download_names_the_file_after_the_project(self):
        status, disposition, body = self.get(f"/assets/{self.version}?download=1")
        self.assertEqual((status, body), (200, tiny_mp4(b"version-1")))
        self.assertEqual(disposition, "attachment; filename=\"p-v001.mp4\"; filename*=UTF-8''"
                                      + quote("Проба монтажа-v001.mp4", safe=""))

    def test_plain_get_is_not_an_attachment(self):
        status, disposition, _body = self.get(f"/assets/{self.version}")
        self.assertEqual((status, disposition), (200, None))

    def test_range_download_keeps_the_name(self):
        status, disposition, body = self.get(f"/assets/{self.version}?download=1", {"Range": "bytes=0-3"})
        self.assertEqual((status, body), (206, tiny_mp4(b"version-1")[:4]))
        self.assertTrue(disposition.startswith("attachment; "))

    def test_other_queries_are_refused(self):
        for target in (f"/assets/{self.version}?download=2", f"/assets/{self.version}?download=1&x=1",
                       f"/assets/{self.version}?download", f"/assets/{self.version}?project=p",
                       "/api/projects?download=1"):
            with self.subTest(target=target):
                self.assertEqual(self.get(target)[0], 400)

    def test_project_selector_of_the_page_still_works(self):
        self.assertEqual(self.get("/?project=p")[0], 200)


if __name__ == "__main__":
    unittest.main()
