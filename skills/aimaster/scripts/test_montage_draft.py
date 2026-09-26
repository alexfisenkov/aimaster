#!/usr/bin/env python3
"""Черновик: эталонная разметка без титров и внешних ссылок, локальный GSAP и таймлайн main
(звук в превью Studio, задача 10b); свой шрифт; обновление устаревших клипов."""

from __future__ import annotations

import json
import os
import re
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

from montage_testkit import fake_gsap_prefix, video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.composition_refs import (check_composition, external_references,  # noqa: E402
                                             missing_sources)
from studio.montage.draft import create_draft, rebuild_draft  # noqa: E402
from studio.montage.draft_html import title_fragment  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.montage.html_doc import element_attrs, element_span, set_attr  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.refresh import refresh_draft  # noqa: E402
from studio.montage.stale import stale_clips  # noqa: E402

SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
# Fix round 2/5, item 3 + раунд 3/5, item 5: data-am-scenes/data-am-gen-mode/
# data-am-layers — слепок структуры проекта на момент сборки, читает
# stale_clips (stale.py). Задача 10b: без data-no-timeline — у черновика свой
# таймлайн main (иначе Studio после правки играет перемоткой, без звука).
ROOT = ('<div id="root" data-composition-id="main" data-start="0" data-duration="3.5" '
        'data-width="108" data-height="192" data-am-scenes="s1 s2" '
        'data-am-gen-mode="per_scene" data-am-layers="voice">')
V1 = ('<video id="v-1" class="am-video" src="assets/asset-a.mp4" data-media-start="0" '
      'data-start="0" data-duration="2" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s1" data-am-asset="asset-a" data-has-audio="true" data-volume="0.3" '
      'data-fade-out="0.4" playsinline></video>')
V2 = ('<video id="v-2" class="am-video am-fade-in" src="assets/asset-b.mp4" data-media-start="0" '
      'data-start="2" data-duration="1.5" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s2" data-am-asset="asset-b" muted playsinline></video>')
VOICE = ('<audio id="a-voice" src="assets/asset-v.wav" data-media-start="0" data-start="0" '
         'data-duration="3.5" data-track-index="2" data-am-layer="voice" data-am-asset="asset-v" '
         'data-volume="1"></audio>')


class DraftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.media = base / "media"
        self.media.mkdir()
        self.infos = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
                      "asset-b": MediaInfo(1.5, 108, 192, True, False),
                      "asset-c": MediaInfo(1.0, 108, 192, True, True),
                      "asset-v": MediaInfo(5.0, None, None, False, True)}
        for asset in self.infos:
            suffix = ".wav" if asset == "asset-v" else ".mp4"
            (self.media / f"{asset}{suffix}").write_bytes(asset.encode())
        self.paths = montage_paths(base / "projects" / "p")
        self.prefix = fake_gsap_prefix(base)

    def resolve(self, asset):
        return next(self.media.glob(f"{asset}.*"))

    def probe(self, path):
        return self.infos[Path(path).stem]

    def draft(self, state):
        return create_draft(self.paths, state, self.resolve, probe=self.probe,
                            engine_prefix=self.prefix)

    def test_draft_is_the_reference_composition(self):
        result = self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        text = self.paths.index.read_text(encoding="utf-8")
        self.assertEqual((result.canvas, result.duration, result.clips), (Canvas(108, 192), 3.5, 3))
        for line in (ROOT, V1, V2, VOICE):
            self.assertIn(line, text)
        self.assertNotIn('data-am-layer="titles"', text)
        self.assertNotIn("data-no-timeline", text)
        # Задача 10b: локальный GSAP из движка и таймлайн main на паузе длиной
        # в data-duration корня, зарегистрированный после корня.
        head = text[:text.index("</head>")]
        self.assertIn('<script src="assets/gsap.min.js"></script>', head)
        self.assertIn('<script src="assets/MotionPathPlugin.min.js"></script>', head)
        self.assertLess(head.index("gsap.min.js"), head.index("MotionPathPlugin.min.js"))
        body = text[text.index("<body>"):]
        self.assertLess(body.index('id="root"'), body.index('window.__timelines["main"] = tl;'))
        self.assertIn("gsap.timeline({ paused: true })", body)
        self.assertIn('root.getAttribute("data-duration")', body)
        for name in ("gsap", "MotionPathPlugin"):
            self.assertEqual((self.paths.assets / f"{name}.min.js").read_text(encoding="utf-8"),
                             f"/* {name} */\n")
        self.assertEqual(check_composition(text, self.paths.current), [])
        self.assertIn('font-family: "AM Inter", sans-serif', text)
        self.assertNotIn("font-family: sans-serif", text)
        self.assertIn('src: url("assets/fonts/inter-cyrillic-400-normal.woff2") format("woff2")', text)
        self.assertTrue((self.paths.assets / "fonts" / "inter-cyrillic-700-normal.woff2").is_file())
        # Fix round 1/5: лицензия шрифта едет рядом с файлами (условие 2 OFL).
        self.assertTrue((self.paths.assets / "fonts" / "OFL.txt").is_file())
        self.assertEqual(external_references(text), [])
        self.assertEqual(missing_sources(text, self.paths.current), [])
        config = json.loads((self.paths.current / "hyperframes.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"media": {"autoProxy": True}})

    def test_draft_without_gsap_points_to_the_install_command_and_writes_nothing(self):
        # Черновик без GSAP закреплённой версии не собирается — отказ тот же,
        # что у require_engine: «движок не готов», команда — в engine.install.
        with self.assertRaises(MontageError) as caught:
            create_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe,
                         engine_prefix=self.paths.root / "нет-движка")
        self.assertIn("GSAP", str(caught.exception))
        self.assertIn("engine.install в ответе montage status", str(caught.exception))
        self.assertNotIn(str(self.paths.root), str(caught.exception))
        self.assertFalse(self.paths.current.exists())

    def test_rebuild_without_gsap_keeps_the_draft_and_makes_no_backup(self):
        self.draft(video_state(SCENES))
        original = self.paths.index.read_text(encoding="utf-8")
        with self.assertRaises(MontageError):
            rebuild_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe,
                          engine_prefix=self.paths.root / "нет-движка")
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), original)
        self.assertFalse(self.paths.undo.exists())

    def test_draft_takes_gsap_from_the_engine_folder_by_default(self):
        # Без engine_prefix — папка движка, как у engine.locate
        # (AIMASTER_HYPERFRAMES_DIR подменяет её, как в CI и смоуке).
        with mock.patch.dict(os.environ, {PREFIX_ENV: str(self.prefix)}):
            create_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe)
        self.assertTrue((self.paths.assets / "gsap.min.js").is_file())

    def test_title_fragment_uses_the_title_style(self):
        self.assertEqual(title_fragment("t-1", "Кот & «мяч»", 0.2, 1.6),
                         '<div id="t-1" class="clip am-title" data-start="0.2" data-duration="1.6" '
                         'data-track-index="1" data-am-layer="titles"><span>Кот &amp; «мяч»</span></div>')

    def test_second_draft_is_refused(self):
        self.draft(video_state(SCENES))
        with self.assertRaises(MontageError) as caught:
            self.draft(video_state(SCENES))
        self.assertIn("--refresh", str(caught.exception))

    def test_refresh_replaces_only_the_stale_clip(self):
        self.draft(video_state(SCENES))
        before = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-c")])
        stale = refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        self.assertEqual([item["clip"] for item in stale], ["v-2"])
        after = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        self.assertEqual((after["v-2"]["src"], after["v-2"]["data-am-asset"], after["v-2"]["data-duration"]),
                         ("assets/asset-c.mp4", "asset-c", "1"))
        self.assertEqual(after["v-1"], before["v-1"])
        self.assertEqual(stale_clips(self.paths.index.read_text(encoding="utf-8"), newer), [])

    def test_refresh_refuses_a_broken_number_in_russian(self):
        self.draft(video_state(SCENES))
        text = self.paths.index.read_text(encoding="utf-8")
        self.paths.index.write_text(set_attr(text, "v-2", "data-media-start", "полсекунды"),
                                    encoding="utf-8")
        newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-c")])
        with self.assertRaises(MontageError) as caught:
            refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        self.assertEqual(str(caught.exception).split(" — ")[0],
                         "повреждённое значение data-media-start у клипа v-2: «полсекунды»")

    def test_rebuild_keeps_the_old_draft_in_undo(self):
        self.draft(video_state(SCENES))
        original = self.paths.index.read_text(encoding="utf-8")
        self.paths.index.write_text(original + "<!-- правка в столе -->", encoding="utf-8")
        result, backup = rebuild_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe,
                                       engine_prefix=self.prefix)
        self.assertEqual(result.clips, 2)
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.parent, self.paths.undo)
        self.assertTrue(backup.read_text(encoding="utf-8").endswith("<!-- правка в столе -->"))

    # Fix round 1/5: три находки reviewer'а на refresh/stale_clips.

    def test_refresh_flips_muted_state_both_directions(self):
        self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        # s1 переезжает на немой asset-b (звук должен пропасть), s2 — на
        # asset-c со звуком (звук должен появиться); voice остался принятым,
        # значит VIDEO_VOLUME[True] = 0.3.
        newer = video_state([("s1", "Сад", "Барсик идёт по саду", 2000, "asset-b"),
                             ("s2", "Клубок", "Находит клубок", 2000, "asset-c")],
                            audio={"voice": "asset-v"})
        stale = refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        changes = {item["clip"]: item.get("audio_change") for item in stale}
        self.assertEqual(changes, {"v-1": "пропал звук", "v-2": "добавился звук"})
        after = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        self.assertIn("muted", after["v-1"])
        for key in ("data-has-audio", "data-volume", "data-fade-in", "data-fade-out"):
            self.assertNotIn(key, after["v-1"])
        self.assertNotIn("muted", after["v-2"])
        self.assertEqual((after["v-2"]["data-has-audio"], after["v-2"]["data-volume"],
                          after["v-2"]["data-fade-in"], after["v-2"]["data-fade-out"]),
                         ("true", "0.3", "0.4", "0.4"))

    def test_stale_clips_reports_unaccepted_without_touching_it(self):
        self.draft(video_state(SCENES))
        newer = video_state(SCENES)
        next(r for r in newer["video_results"] if r["scene_id"] == "s2")["decision"] = "rejected"
        before = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        stale = refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        self.assertEqual([(item["clip"], item["reason"], item["current_asset_id"]) for item in stale],
                         [("v-2", "нет принятого", None)])
        after = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        self.assertEqual(after["v-2"], before["v-2"])

    def test_stale_clips_removed_scene_needs_rebuild(self):
        # Fix round 2/5, item 3: у структурных записей clip всегда None (даже
        # если в разметке технически есть повисший "v-2") и есть cause.
        self.draft(video_state(SCENES))
        newer = video_state([SCENES[0]])
        stale = stale_clips(self.paths.index.read_text(encoding="utf-8"), newer)
        self.assertEqual([(item["clip"], item["scene_id"], item["cause"], item["reason"])
                          for item in stale],
                         [(None, "s2", "scene_removed", "нужен --rebuild")])

    def test_stale_clips_added_scene_needs_rebuild(self):
        self.draft(video_state(SCENES))
        newer = video_state(SCENES + [("s3", "Финал", "Титры", 1000, "asset-c")])
        stale = stale_clips(self.paths.index.read_text(encoding="utf-8"), newer)
        self.assertEqual([(item["clip"], item["scene_id"], item["cause"], item["reason"])
                          for item in stale],
                         [(None, "s3", "scene_added", "нужен --rebuild")])

    def test_stale_clips_gen_mode_switch_is_one_project_level_item(self):
        # Fix round 2/5, item 3: ОДНА запись на весь проект, а не по клипу.
        self.draft(video_state(SCENES))
        newer = video_state([("s1", "Сад", "Барсик идёт по саду", 2000, None),
                             ("s2", "Клубок", "Находит клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-c")
        stale = stale_clips(self.paths.index.read_text(encoding="utf-8"), newer)
        self.assertEqual([(item["clip"], item["cause"], item["reason"]) for item in stale],
                         [(None, "gen_mode", "нужен --rebuild")])

    def test_stale_clips_newly_accepted_layer_without_a_clip_is_layer_added(self):
        # Fix round 2/5, item 3: слой, ставший принятым уже после сборки
        # черновика — своя причина, «нужен --rebuild», не «нет принятого».
        self.draft(video_state(SCENES))
        newer = video_state(SCENES, audio={"music": "asset-c"})
        stale = stale_clips(self.paths.index.read_text(encoding="utf-8"), newer)
        self.assertEqual([(item["clip"], item["layer"], item["cause"], item["reason"])
                          for item in stale],
                         [(None, "music", "layer_added", "нужен --rebuild")])

    def test_stale_clips_scene_deleted_from_the_desk_is_not_stale(self):
        # Fix round 2/5, item 3: сцена осталась в проекте и её знал черновик
        # (data-am-scenes), но клипа для неё в разметке уже нет — владелец
        # сам убрал её со стола; refresh это не его дело.
        self.draft(video_state(SCENES))
        text = self.paths.index.read_text(encoding="utf-8")
        begin, end = element_span(text, "v-2")
        without_v2 = text[:begin] + text[end:]
        stale = stale_clips(without_v2, video_state(SCENES))
        self.assertEqual(stale, [])

    def test_stale_clips_reconstructs_structure_when_markers_are_stripped(self):
        # Fix round 3/5, item 4: _legacy_stale_clips убран — без markers на
        # корне структура восстанавливается из самих клипов и идёт через тот
        # же (единственный) алгоритм; пока клипы не поменялись, результат
        # совпадает с тем, что дала бы разметка (test_stale_clips_removed_
        # scene_needs_rebuild — тот же newer, тот же ответ).
        self.draft(video_state(SCENES))
        text = self.paths.index.read_text(encoding="utf-8")
        stripped = text
        for name in ("data-am-scenes", "data-am-gen-mode", "data-am-layers"):
            stripped = set_attr(stripped, "root", name, None)
        for name in ("data-am-scenes", "data-am-gen-mode", "data-am-layers"):
            self.assertNotIn(name, stripped)
        newer = video_state([SCENES[0]])
        stale = stale_clips(stripped, newer)
        self.assertEqual([(item["clip"], item["scene_id"], item["cause"], item["reason"])
                          for item in stale],
                         [(None, "s2", "scene_removed", "нужен --rebuild")])

    def test_stale_clips_one_shot_without_markers_is_not_every_scene_added(self):
        # Задача 10b (перенос из батча 4): one_shot-черновик без слепка на
        # корне — видео-клип без сцены не говорит, какие сцены знал черновик;
        # сцены тогда неизвестны и разность сцен не считается (раньше каждая
        # сцена проекта выходила scene_added при неизменном проекте).
        state = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-c")
        self.draft(state)
        stripped = self.paths.index.read_text(encoding="utf-8")
        for name in ("data-am-scenes", "data-am-gen-mode", "data-am-layers"):
            stripped = set_attr(stripped, "root", name, None)
        self.assertEqual(stale_clips(stripped, state), [])
        # Замена общего видео при этом по-прежнему видна.
        newer = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-a")
        self.assertEqual([(item["clip"], item["current_asset_id"], item["cause"])
                          for item in stale_clips(stripped, newer)],
                         [("v-1", "asset-a", None)])

    def test_stale_clips_scene_added_in_one_shot_needs_rebuild(self):
        # Fix round 3/5, item 6: в one_shot один клип покрывает всю историю
        # (story_end считается по всем сценам) — добавление сцены меняет
        # раскладку и там, не только в per_scene; gen_mode не меняется.
        state = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-c")
        self.draft(state)
        newer = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None),
                             ("s3", "Финал", "Титры", 1000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-c")
        stale = stale_clips(self.paths.index.read_text(encoding="utf-8"), newer)
        self.assertEqual([(item["clip"], item["scene_id"], item["cause"], item["reason"])
                          for item in stale],
                         [(None, "s3", "scene_added", "нужен --rebuild")])

    def test_stale_clips_dedupes_scene_removed_by_scene_id(self):
        # Fix round 3/5, item 7: два клипа с одной и той же (уже удалённой из
        # проекта) сценой — запись про неё одна, не по одной на клип.
        html = ('<div id="root" data-am-scenes="s1 s2" data-am-gen-mode="per_scene" '
               'data-am-layers="">'
               '<video id="v-1" data-am-layer="video" data-am-scene="s1" '
               'data-am-asset="asset-a"></video>'
               '<video id="v-2" data-am-layer="video" data-am-scene="s2" '
               'data-am-asset="asset-b"></video>'
               '<video id="v-2b" data-am-layer="video" data-am-scene="s2" '
               'data-am-asset="asset-b"></video>'
               '</div>')
        newer = video_state([SCENES[0]])  # только s1 — s2 исчезла из проекта
        stale = stale_clips(html, newer)
        removed = [item for item in stale if item.get("cause") == "scene_removed"]
        self.assertEqual([(item["scene_id"], item["clip"]) for item in removed], [("s2", None)])

    def test_stale_clips_layer_clip_deleted_from_the_desk_is_not_stale(self):
        # Fix round 3/5, item 5: слой симметричен сцене — recorded и всё ещё
        # принятый слой, чей клип убрали со стола, не помечается вовсе.
        self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        text = self.paths.index.read_text(encoding="utf-8")
        begin, end = element_span(text, "a-voice")
        without_voice = text[:begin] + text[end:]
        newer = video_state(SCENES, audio={"voice": "asset-v"})
        self.assertEqual(stale_clips(without_voice, newer), [])

    def test_stale_clips_layer_marker_reconstructed_when_absent(self):
        # Fix round 3/5, item 5: черновик раунда 2 (data-am-scenes/
        # data-am-gen-mode есть, data-am-layers ещё нет) — слои
        # восстанавливаются из клипов отдельно от сцен/gen_mode, не
        # скатываются целиком в легаси только из-за одного нового поля.
        self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        text = self.paths.index.read_text(encoding="utf-8")
        legacy = set_attr(text, "root", "data-am-layers", None)
        self.assertNotIn("data-am-layers", legacy)
        newer = video_state(SCENES, audio={"voice": "asset-v"})
        self.assertEqual(stale_clips(legacy, newer), [])

    def test_refresh_preserves_crlf_of_an_existing_draft(self):
        self.draft(video_state(SCENES))
        crlf = self.paths.index.read_text(encoding="utf-8").replace("\n", "\r\n")
        self.paths.index.write_bytes(crlf.encode("utf-8"))
        newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-c")])
        refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        after = self.paths.index.read_bytes().decode("utf-8")
        self.assertIsNone(re.search(r"(?<!\r)\n", after))
        self.assertEqual(after.count("\r\n"), crlf.count("\r\n"))


if __name__ == "__main__":
    unittest.main()
