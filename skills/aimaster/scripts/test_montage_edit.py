#!/usr/bin/env python3
"""Правки: как мышью в Studio (обрезка начала двигает исходник, сдвиг за конец удлиняет ролик),
проверка «монтаж не менялся», откат только своей последней правки."""

from __future__ import annotations

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

from montage_testkit import FakeHyperframes, fake_engine, video_state, with_titles  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage import edit as edit_module  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft_html import render_draft_html  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.edit import EditRequest, apply_edit  # noqa: E402
from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

MEDIA = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
         "asset-b": MediaInfo(1.5, 108, 192, True, False),
         "asset-v": MediaInfo(5.0, None, None, False, True)}
SOURCES = {"asset-a": "assets/asset-a.mp4", "asset-b": "assets/asset-b.mp4",
           "asset-v": "assets/asset-v.wav"}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
# Задача 10b: render_draft_html несёт ссылки на локальный GSAP в <head>.
SCRIPTS = ("assets/gsap.min.js", "assets/MotionPathPlugin.min.js")


class EditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.paths = montage_paths(base / "p")
        self.paths.current.mkdir(parents=True)
        plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v"}), MEDIA.__getitem__)
        self.bare = render_draft_html(plan, Canvas(108, 192), SOURCES, SCRIPTS)
        # титры t-1, t-2 — как после двух правок title-add: в черновике их нет
        self.paths.index.write_text(with_titles(self.bare), encoding="utf-8")
        self.runner = FakeHyperframes()
        self.engine = fake_engine(base / "engine")

    def edit(self, **kwargs):
        expected = kwargs.pop("expected_model_hash", None)
        return apply_edit(self.engine, self.paths, EditRequest(**kwargs),
                          expected_model_hash=expected, runner=self.runner)

    def text(self):
        return self.paths.index.read_text(encoding="utf-8")

    def attrs(self):
        return element_attrs(self.text())

    def test_trim_start_moves_media_start_like_studio(self):
        result = self.edit(op="trim-start", clip="v-1", seconds=0.5)
        clip = self.attrs()["v-1"]
        self.assertEqual((clip["data-start"], clip["data-duration"], clip["data-media-start"]),
                         ("0.5", "1.5", "0.5"))
        self.assertIn(["timeline", "trim", "#v-1", "--start", "0.5", "--duration", "1.5",
                       "--dir", ".", "--json"], self.runner.calls)
        self.assertNotEqual(result["model_hash"], result["model_hash_before"])

    def test_move_past_the_end_extends_the_root(self):
        self.edit(op="move", clip="v-2", at=3.0)
        self.assertEqual((self.attrs()["root"]["data-duration"], self.attrs()["v-2"]["data-start"]),
                         ("4.5", "3"))

    def test_split_drops_the_fade_on_the_new_piece(self):
        result = self.edit(op="split", clip="v-2", at=2.5)
        self.assertEqual(result["receipt"]["new_clip"], "v-2-2")
        attrs = self.attrs()
        self.assertEqual((attrs["v-2"]["class"], attrs["v-2-2"]["class"]),
                         ("am-video am-fade-in", "am-video"))
        self.assertEqual(attrs["v-2-2"]["data-media-start"], "0.5")

    def test_split_audio_clip_drops_inner_fade_only(self):
        # Round-fix-1/5, item 1: разрез настоящего <audio> с уже проставленными
        # data-fade-in/out — внешние края (начало и конец ролика) остаются,
        # внутренний стык (место разреза) чистится с обеих сторон.
        self.edit(op="fade", clip="a-voice", fade_in=0.3, fade_out=0.3)
        result = self.edit(op="split", clip="a-voice", at=1.0)
        new_id = result["receipt"]["new_clip"]
        attrs = self.attrs()
        self.assertNotIn("data-fade-out", attrs["a-voice"])
        self.assertEqual(attrs["a-voice"]["data-fade-in"], "0.3")
        self.assertNotIn("data-fade-in", attrs[new_id])
        self.assertEqual(attrs[new_id]["data-fade-out"], "0.3")

    def test_explicit_fade_survives_a_later_unrelated_split(self):
        # Round-fix-2/5, item 1: разрез не должен трогать fade на ДРУГОМ
        # клипе, даже если тот раньше был правой половиной более раннего
        # разреза того же исходника. v-1 -> v-1, v-1-2; на v-1-2 ставим
        # fade-in правкой (не копией CLI); затем разрезаем САМ v-1-2 ->
        # v-1-2, v-1-2-2 — v-1-2 в этом втором разрезе уже не «новый кусок»,
        # но старая (нескопированная) нормализация всё равно его находила
        # как правую половину пары v-1/v-1-2 и стирала fade.
        self.edit(op="split", clip="v-1", at=1.0)
        self.edit(op="fade", clip="v-1-2", fade_in=0.3)
        self.assertEqual(self.attrs()["v-1-2"]["data-fade-in"], "0.3")
        self.edit(op="split", clip="v-1-2", at=1.5)
        self.assertEqual(self.attrs()["v-1-2"]["data-fade-in"], "0.3")

    def test_volume_allowed_by_markup_even_if_the_timeline_row_omits_it(self):
        # Round-fix-2/5, item 7: _has_sound теперь смотрит на свою разметку
        # (data-has-audio/muted), а не на Clip.volume — то самое поле строки
        # `timeline --json`, о ненадёжности которого для этой же цели уже
        # предупреждал round-fix-1/5, item 8 (там — про data-am-asset/src).
        text = self.text().replace(' data-volume="0.3"', "")  # v-1: data-has-audio остаётся, data-volume снят
        self.paths.index.write_text(text, encoding="utf-8")
        self.edit(op="volume", clip="v-1", value=0.6)
        self.assertEqual(self.attrs()["v-1"]["data-volume"], "0.6")

    def test_volume_and_fade_refused_on_muted_video(self):
        # Round-fix-1/5, item 7: v-2 немой (has_audio=False) — правка volume/fade
        # раньше молча принималась и ничего не делала; теперь явный отказ.
        with self.assertRaises(MontageError) as caught:
            self.edit(op="volume", clip="v-2", value=0.5)
        self.assertIn("звука нет", str(caught.exception))
        with self.assertRaises(MontageError):
            self.edit(op="fade", clip="v-2", fade_in=0.1)

    def test_undo_refuses_when_the_note_is_missing_or_corrupt(self):
        # Round-fix-1/5, item 3: гвардия отката была «открыта по умолчанию» —
        # без отметки о состоянии файла после правки undo молча выполнялся.
        self.edit(op="delete", clip="t-2")
        note = sorted(self.paths.undo.glob("edit-*.json"))[-1]
        note.unlink()
        with self.assertRaises(MontageError) as caught:
            self.edit(op="undo")
        self.assertIn("отметк", str(caught.exception))
        self.assertNotIn("t-2", self.attrs())  # чужая (не наша) правка не потеряна откатом

        self.edit(op="delete", clip="t-1")
        note = sorted(self.paths.undo.glob("edit-*.json"))[-1]
        note.write_text("не json", encoding="utf-8")
        with self.assertRaises(MontageError):
            self.edit(op="undo")

    def test_undo_refuses_when_the_note_is_valid_json_but_not_an_object(self):
        # Round-fix-2/5, item 6: валидный JSON, но не словарь (список,
        # число, null) — .get("after") падал бы AttributeError'ом мимо
        # отказа, а не отказывал по-русски.
        self.edit(op="delete", clip="t-2")
        note = sorted(self.paths.undo.glob("edit-*.json"))[-1]
        for payload in ("[1, 2, 3]", "42", "null", '"после правки"'):
            note.write_text(payload, encoding="utf-8")
            with self.assertRaises(MontageError) as caught:
                self.edit(op="undo")
            self.assertIn("отметк", str(caught.exception))

    def test_crlf_survives_a_cli_edit(self):
        # Round-fix-1/5, item 12: FakeHyperframes сам читал/писал index.html
        # универсальным переводом строк — CRLF молча превращался в LF ещё в
        # тесте, до того как могла бы вскрыться настоящая грабля в проде.
        crlf = self.text().replace("\n", "\r\n")
        self.paths.index.write_bytes(crlf.encode("utf-8"))
        self.edit(op="volume", clip="a-voice", value=0.4)
        raw = self.paths.index.read_bytes().decode("utf-8")
        self.assertIn("\r\n", raw)
        self.assertNotRegex(raw, r"(?<!\r)\n")

    def test_timelines_script_survives_every_edit_op(self):
        # Round-fix-1/5, item 13: window.__timelines["main"] — то, без чего
        # превью Studio перематывает без звука (задача 10b) — не должно
        # пострадать ни от одной операции правки.
        baseline = self.text()
        cases = [
            dict(op="trim-start", clip="v-1", seconds=0.2),
            dict(op="trim-end", clip="v-1", duration=1.0),
            dict(op="move", clip="v-2", at=1.5),
            dict(op="split", clip="v-2", at=2.6),
            dict(op="delete", clip="t-2"),
            dict(op="volume", clip="a-voice", value=0.7),
            dict(op="fade", clip="a-voice", fade_in=0.2),
            dict(op="title-add", text="Т", at=3.0, duration=0.5),
            dict(op="title-text", clip="t-1", text="Новый текст"),
        ]
        for kwargs in cases:
            with self.subTest(op=kwargs["op"]):
                self.paths.index.write_text(baseline, encoding="utf-8")
                self.edit(**kwargs)
                self.assertIn('window.__timelines["main"]', self.text())
        self.paths.index.write_text(baseline, encoding="utf-8")
        self.edit(op="delete", clip="t-2")
        self.edit(op="undo")
        self.assertIn('window.__timelines["main"]', self.text())

    def test_titles(self):
        result = self.edit(op="title-add", text="Финал <3", at=3.0, duration=1.0)
        self.assertEqual(result["receipt"]["new_clip"], "t-3")
        self.assertEqual((self.attrs()["t-3"]["_text"], self.attrs()["root"]["data-duration"]),
                         ("Финал <3", "4"))
        self.edit(op="title-text", clip="t-1", text="Кот & мяч")
        self.assertEqual(self.attrs()["t-1"]["_text"], "Кот & мяч")

    def test_first_title_on_a_bare_draft_is_t1(self):
        self.paths.index.write_text(self.bare, encoding="utf-8")
        result = self.edit(op="title-add", text="Привет", at=0.5, duration=1.0)
        self.assertEqual(result["receipt"]["new_clip"], "t-1")
        self.assertEqual((self.attrs()["t-1"]["class"], self.attrs()["t-1"]["data-am-layer"]),
                         ("clip am-title", "titles"))

    def test_volume_and_fade(self):
        self.edit(op="volume", clip="a-voice", value=0.5)
        self.assertEqual(self.attrs()["a-voice"]["data-volume"], "0.5")
        with self.assertRaises(MontageError):
            self.edit(op="volume", clip="a-voice", value=5)
        with self.assertRaises(MontageError):
            self.edit(op="volume", clip="t-1", value=0.5)
        self.edit(op="fade", clip="a-voice", fade_in=0.5)
        self.assertEqual(self.attrs()["a-voice"]["data-fade-in"], "0.5")
        self.edit(op="fade", clip="a-voice", fade_in=0)
        self.assertNotIn("data-fade-in", self.attrs()["a-voice"])

    def test_stale_hash_is_refused_and_nothing_changes(self):
        before = self.text()
        with self.assertRaises(MontageError) as caught:
            self.edit(op="delete", clip="t-2", expected_model_hash="0" * 16)
        self.assertIn("изменился", str(caught.exception))
        self.assertEqual(self.text(), before)

    def test_refused_cli_edit_restores_the_file(self):
        self.runner.refuse["move"] = "#v-1 would overlap #v-2 at 3.4-5.4"
        before = self.text()
        with self.assertRaises(MontageError):
            self.edit(op="move", clip="v-1", at=3.4)
        self.assertEqual(self.text(), before)

    def test_undo_own_last_edit_only(self):
        before = self.text()
        self.edit(op="delete", clip="t-2")
        self.assertNotIn("t-2", self.attrs())
        self.assertEqual(self.edit(op="undo")["op"], "undo")
        self.assertEqual(self.text(), before)
        self.edit(op="delete", clip="t-2")
        self.paths.index.write_text(self.text() + " ", encoding="utf-8")  # правка мышью в столе
        with self.assertRaises(MontageError):
            self.edit(op="undo")

    def test_undo_folder_keeps_the_newest_edits_only(self):
        with mock.patch.object(edit_module, "UNDO_DEPTH", 3):
            for at in (0.1, 0.2, 0.3, 0.4, 0.5):
                self.edit(op="move", clip="t-1", at=at)
            snapshots = sorted(self.paths.undo.glob("edit-*.html"))
            notes = sorted(self.paths.undo.glob("edit-*.json"))
            self.assertEqual(len(snapshots), 3)
            self.assertEqual([path.with_suffix(".json") for path in snapshots], notes)
            for _ in range(3):  # три последние правки откатываются по одной
                self.edit(op="undo")
            self.assertEqual(self.attrs()["t-1"]["data-start"], "0.2")
            with self.assertRaises(MontageError) as caught:
                self.edit(op="undo")
        self.assertIn("отменять нечего", str(caught.exception))

    def test_unknown_op_and_missing_clip_flag(self):
        with self.assertRaises(MontageError):
            self.edit(op="jump")
        with self.assertRaises(MontageError) as caught:
            self.edit(op="move", at=1.0)
        self.assertIn("--clip", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
