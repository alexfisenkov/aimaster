#!/usr/bin/env python3
"""Регрессия на настоящем файле, сохранённом из HyperFrames Studio.

Fix round 3/5, item 10: реальный пробник (не наша генерация) подтвердил, что
Studio при сохранении: переписывает `<!doctype html>` → `<!DOCTYPE html>`,
`<meta ... />` → `<meta ...>` (без самозакрывающего слэша), добавляет
`data-hf-id="hf-XXXX"` КАЖДОМУ элементу (нестабильный — никогда не
использовать как идентичность) и `data-no-timeline` → `data-no-timeline=""`
на корне — но наши `data-am-scenes`/`data-am-gen-mode` (раунд 2) переживают
сохранение без изменений. Фикстуры — `fixtures/montage/studio-before.html`
(наш черновик до открытия в Studio) и `studio-after-move.html` (тот же
черновик после того, как в Studio подвинули клип v-2 на 1с — data-start
"3" → "4"; остальное совпадает с точностью до data-hf-id/DOCTYPE/meta)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import video_state  # noqa: E402
from studio.montage.html_doc import element_attrs, set_attr  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.refresh import refresh_draft  # noqa: E402
from studio.montage.stale import stale_clips  # noqa: E402

FIXTURES = _SCRIPTS / "fixtures" / "montage"
AFTER_MOVE = (FIXTURES / "studio-after-move.html").read_text(encoding="utf-8")
BEFORE = (FIXTURES / "studio-before.html").read_text(encoding="utf-8")

SCENES = [("s1", "Сад", "Барсик идёт по саду", 3000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b"),
          ("s3", "Финал", "Уносит клубок", 3000, "asset-c")]


class StudioSavedFormTests(unittest.TestCase):
    def test_element_attrs_reads_the_studio_saved_form(self):
        attrs = element_attrs(AFTER_MOVE)
        # data-hf-id есть на каждом элементе (нестабильный, не идентичность)
        # и не мешает читать наши атрибуты.
        self.assertEqual(attrs["root"]["data-hf-id"], "hf-ccys")
        self.assertEqual(attrs["root"]["data-am-scenes"], "s1 s2 s3")
        self.assertEqual(attrs["root"]["data-am-gen-mode"], "per_scene")
        self.assertEqual(attrs["root"]["data-no-timeline"], "")
        # v-2 подвинули в Studio: data-start "3" → "4".
        self.assertEqual(attrs["v-2"]["data-start"], "4")
        self.assertEqual(attrs["v-2"]["data-hf-id"], "hf-omuv")
        self.assertIn("<!DOCTYPE html>", AFTER_MOVE)
        self.assertIn('<meta charset="UTF-8">', AFTER_MOVE)

    def test_stale_clips_reads_markers_from_a_studio_saved_draft(self):
        # data-am-layers ещё нет в этом (реальном, до раунда 3) файле —
        # восстанавливается из самих клипов (item 4/5); ничего в проекте не
        # поменялось — ничего не должно быть стейл.
        self.assertNotIn("data-am-layers", AFTER_MOVE)
        state = video_state(SCENES, audio={"music": "asset-m"})
        self.assertEqual(stale_clips(AFTER_MOVE, state), [])

    def test_studio_save_does_not_change_what_is_stale(self):
        # Тот же черновик до и после сохранения в Studio (DOCTYPE, meta,
        # data-hf-id, сдвиг v-2) — одинаковый ответ stale_clips и при
        # неизменном проекте, и при заменённом результате сцены.
        for state in (video_state(SCENES, audio={"music": "asset-m"}),
                      video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-b2"),
                                   SCENES[2]], audio={"music": "asset-m"})):
            self.assertEqual(stale_clips(BEFORE, state), stale_clips(AFTER_MOVE, state))
        self.assertEqual(element_attrs(BEFORE)["v-2"]["data-start"], "3")

    def test_set_attr_edits_a_clip_and_preserves_studio_attributes(self):
        changed = set_attr(AFTER_MOVE, "v-2", "data-start", "5")
        self.assertEqual(element_attrs(changed)["v-2"]["data-start"], "5")
        # Всё, что писала Studio, остаётся как было — включая другие клипы.
        self.assertEqual(changed.count("data-hf-id"), AFTER_MOVE.count("data-hf-id"))
        self.assertIn("<!DOCTYPE html>", changed)
        self.assertIn('<meta charset="UTF-8">', changed)
        self.assertIn('data-hf-id="hf-ccys"', changed)
        self.assertIn('data-hf-id="hf-ata5"', changed)  # v-1 не тронут
        v1_before = element_attrs(AFTER_MOVE)["v-1"]
        v1_after = element_attrs(changed)["v-1"]
        self.assertEqual(v1_before, v1_after)

    def test_refresh_draft_patches_one_clip_in_a_studio_saved_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            media_dir = base / "media"
            media_dir.mkdir()
            infos = {"asset-a": MediaInfo(3.0, 360, 640, True, True),
                     "asset-b": MediaInfo(2.0, 360, 640, True, False),
                     "asset-b2": MediaInfo(2.0, 360, 640, True, False),
                     "asset-c": MediaInfo(3.0, 360, 640, True, True),
                     "asset-m": MediaInfo(10.0, None, None, False, True)}
            for asset in infos:
                suffix = ".wav" if asset == "asset-m" else ".mp4"
                (media_dir / f"{asset}{suffix}").write_bytes(asset.encode())

            def resolve(asset_id):
                return next(media_dir.glob(f"{asset_id}.*"))

            def probe(path):
                return infos[Path(path).stem]

            paths = montage_paths(base / "projects" / "p")
            paths.current.mkdir(parents=True)
            paths.index.write_text(AFTER_MOVE, encoding="utf-8")

            newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-b2"),
                                 SCENES[2]], audio={"music": "asset-m"})
            stale = refresh_draft(paths, newer, resolve, probe=probe)
            self.assertEqual([item["clip"] for item in stale], ["v-2"])

            after = paths.index.read_text(encoding="utf-8")
            after_attrs = element_attrs(after)
            self.assertEqual((after_attrs["v-2"]["data-am-asset"], after_attrs["v-2"]["src"]),
                             ("asset-b2", "assets/asset-b2.mp4"))
            # Сдвиг, сделанный владельцем в Studio, пережил замену исходника.
            self.assertEqual(after_attrs["v-2"]["data-start"], "4")
            # Studio-разметка не размылась точечной правкой.
            self.assertIn("<!DOCTYPE html>", after)
            self.assertEqual(after.count("data-hf-id"), AFTER_MOVE.count("data-hf-id"))
            self.assertEqual(after_attrs["v-1"], element_attrs(AFTER_MOVE)["v-1"])
            self.assertEqual(after_attrs["v-3"], element_attrs(AFTER_MOVE)["v-3"])


if __name__ == "__main__":
    unittest.main()
