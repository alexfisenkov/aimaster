#!/usr/bin/env python3
"""Модель монтажа из timeline --json + наших пометок; хэш не видит правок Studio; diff по-русски."""

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

from montage_testkit import (  # noqa: E402
    FakeHyperframes, fake_engine, timeline_from_html, video_state, with_titles)
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft_html import render_draft_html  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.html_doc import element_span, insert_before_root_end, set_attr, set_text  # noqa: E402
from studio.montage.model import Model, build_model, layers_view, model_hash, read_model  # noqa: E402
from studio.montage.model_diff import (  # noqa: E402
    clips_count, diff_models, fmt_len, fmt_len_precise, fmt_time)
from studio.montage.probe import MediaInfo  # noqa: E402

MEDIA = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
         "asset-b": MediaInfo(1.5, 108, 192, True, False),
         "asset-v": MediaInfo(5.0, None, None, False, True)}
SOURCES = {"asset-a": "assets/asset-a.mp4", "asset-b": "assets/asset-b.mp4",
           "asset-v": "assets/asset-v.wav"}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
NAMES = {"s1": "сцены 1 «Сад»", "s2": "сцены 2 «Клубок»"}
# Задача 10b: render_draft_html несёт ссылки на локальный GSAP в <head> —
# для разбора моделью содержимое <script> роли не играет, важен только id.
SCRIPTS = ("assets/gsap.min.js", "assets/MotionPathPlugin.min.js")


def bare_draft() -> str:
    plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v"}), MEDIA.__getitem__)
    return render_draft_html(plan, Canvas(108, 192), SOURCES, SCRIPTS)


def draft_html() -> str:
    """Черновик и два титра, добавленных правкой: титров в самом черновике нет."""
    return with_titles(bare_draft())


def model_of(text: str) -> Model:
    return build_model(timeline_from_html(text), text)


class ModelTests(unittest.TestCase):
    def test_build_reads_layers_scenes_and_media_start(self):
        model = model_of(draft_html())
        self.assertEqual(model.duration, 3.5)
        self.assertEqual([c.id for c in model.clips], ["v-1", "v-2", "t-1", "t-2", "a-voice"])
        clip = model.clip("v-1")
        self.assertEqual((clip.layer, clip.scene_id, clip.asset_id, clip.fade_out), ("video", "s1", "asset-a", 0.4))
        self.assertEqual(model.clip("t-1").text, "Барсик идёт по саду")
        self.assertEqual(model.clip("a-voice").layer, "voice")

    def test_clip_src_comes_from_markup_not_the_timeline_row(self):
        # Round-fix-3/5, item E: Clip.src — атрибут разметки (`src=` тега),
        # не поле `timeline --json`'s строки, которое CLI не обязан отдавать
        # одинаково с тем, что реально в разметке (тот же риск, что уже был
        # у data-am-asset, round-fix-1/5, item 8).
        text = draft_html()
        timeline = timeline_from_html(text)
        for track in timeline["timeline"]["tracks"]:
            for row in track["rows"]:
                if row["id"] == "v-1":
                    row["src"] = "не то, что в разметке"
        model = build_model(timeline, text)
        self.assertEqual(model.clip("v-1").src, "assets/asset-a.mp4")

    def test_hash_ignores_studio_ids_rows_and_doctype(self):
        text = draft_html()
        studio = set_attr(set_attr(text, "a-voice", "data-hf-id", "hf-y1f4"), "a-voice", "data-track-index", "0")
        studio = studio.replace("<!doctype html>", "<!DOCTYPE html>")
        self.assertEqual(model_hash(model_of(text)), model_hash(model_of(studio)))
        self.assertNotEqual(model_hash(model_of(text)), model_hash(model_of(set_attr(text, "v-2", "data-start", "2.5"))))

    def test_unmarked_clip_falls_back_by_kind(self):
        text = draft_html().replace(' data-am-layer="voice"', "")
        self.assertEqual(model_of(text).clip("a-voice").layer, "music")

    def test_layers_view_has_all_six_tracks_in_order(self):
        view = layers_view(model_of(draft_html()))
        self.assertEqual([item["layer"] for item in view], ["video", "titles", "voice", "music", "fx", "atmos"])
        self.assertEqual(view[0]["label"], "Видео")
        self.assertEqual([clip["id"] for clip in view[0]["clips"]], ["v-1", "v-2"])
        self.assertEqual(view[3]["clips"], [])

    def test_round_trip_and_cache(self):
        model = model_of(draft_html())
        self.assertEqual(Model.from_dict(model.to_dict()), model)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "current").mkdir()
            (base / "current" / "index.html").write_text(draft_html(), encoding="utf-8")
            runner = FakeHyperframes()
            first = read_model(fake_engine(base), base / "current", cache_dir=base / ".cache", runner=runner)
            second = read_model(fake_engine(base), base / "current", cache_dir=base / ".cache", runner=runner)
        self.assertEqual(first, second)
        self.assertEqual(runner.calls, [["timeline", "--json"]])


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.text = draft_html()
        self.old = model_of(self.text)

    def diff(self, text):
        return diff_models(self.old, model_of(text), names=NAMES)

    def test_formats(self):
        self.assertEqual((fmt_time(65.3), fmt_len(3.5)), ("1:05.3", "3,5 с"))

    def test_format_rounding_carries_into_the_next_minute(self):
        # Round-fix-1/5, item 4: округление секунд ДО divmod — иначе 59.97 с
        # печаталось как «0:60.0» вместо «1:00.0».
        self.assertEqual(fmt_time(59.97), "1:00.0")
        self.assertEqual(fmt_time(59.94), "0:59.9")

    def test_format_shows_sub_tenth_changes_as_at_least_a_tenth(self):
        # Round-fix-1/5, item 5: изменение меньше 0,1 с не должно читаться
        # как «без изменений» — округление к 0,1 с, ROUND_HALF_UP, не к нулю.
        self.assertEqual(fmt_len(0.03), "0,1 с")
        self.assertEqual(fmt_len(0.05), "0,1 с")
        self.assertEqual(fmt_len(0.0), "0,0 с")

    def test_first_version(self):
        self.assertEqual(diff_models(None, model_of(bare_draft())), ["черновой монтаж: 3 клипа, 3,5 с"])
        self.assertEqual(diff_models(None, self.old), ["черновой монтаж: 5 клипов, 3,5 с"])
        self.assertEqual([clips_count(n) for n in (1, 2, 11, 21, 22, 25)],
                         ["1 клип", "2 клипа", "11 клипов", "21 клип", "22 клипа", "25 клипов"])

    def test_trim_head_is_one_line(self):
        text = self.text
        for attr, value in (("data-start", "0.5"), ("data-duration", "1.5"), ("data-media-start", "0.5")):
            text = set_attr(text, "v-1", attr, value)
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"])

    def test_head_trim_amount_below_display_precision(self):
        # Round-fix-3/5, item D: обрезка на 0,03 с раньше показывалась как
        # «0,1 с» (fmt_len завышала мелкое ненулевое значение) — теперь точно.
        text = self.text
        for attr, value in (("data-start", "0.03"), ("data-duration", "1.97"), ("data-media-start", "0.03")):
            text = set_attr(text, "v-1", attr, value)
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: начало обрезано на 0,03 с"])

    def test_root_length_precision_escalates(self):
        # Round-fix-3/5, item D: то же самое для длины ролика (3,50 → 3,53).
        text = set_attr(self.text, "root", "data-duration", "3.53")
        self.assertEqual(self.diff(text), ["длина ролика изменилась на 0,03 с"])

    def test_fade_precision_escalates(self):
        base = set_attr(self.text, "a-voice", "data-fade-in", "0.5")
        changed = set_attr(self.text, "a-voice", "data-fade-in", "0.53")
        changes = diff_models(model_of(base), model_of(changed), names=NAMES)
        self.assertEqual(changes, ["звук «Голос» (a-voice): плавное появление звука 0,53 с"])

    def test_media_start_precision_escalates(self):
        base = set_attr(self.text, "v-1", "data-media-start", "1.00")
        changed = set_attr(self.text, "v-1", "data-media-start", "1.03")
        changes = diff_models(model_of(base), model_of(changed), names=NAMES)
        self.assertEqual(changes, ["клип сцены 1 «Сад»: из исходника берётся кусок с 0:01.03"])

    def test_move_and_longer_video(self):
        text = set_attr(set_attr(self.text, "v-2", "data-start", "2.5"), "root", "data-duration", "4")
        self.assertEqual(self.diff(text), ["длина ролика 3,5 с → 4,0 с",
                                           "клип сцены 2 «Клубок»: сдвинут 0:02.0 → 0:02.5"])

    def test_position_and_length_change_below_display_precision(self):
        # Round-fix-2/5, item 5: 0,1 с не различает 2,00 и 2,03 — раньше
        # печаталось «сдвинут 0:02.0 → 0:02.0», как будто ничего не случилось.
        self.assertEqual(fmt_len_precise(0.03), "0,03 с")
        text = set_attr(self.text, "v-2", "data-start", "2.03")
        self.assertEqual(self.diff(text), ["клип сцены 2 «Клубок»: сдвинут на 0,03 с вперёд"])
        text = set_attr(self.text, "v-1", "data-duration", "1.97")
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: укорочен на 0,03 с"])

    def test_split_is_reported_once(self):
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "index.html"
            index.write_text(self.text, encoding="utf-8")
            FakeHyperframes().json(None, ["timeline", "split", "#v-1", "1", "--dir", ".", "--json"],
                                   cwd=Path(temp), timeout=1)
            text = index.read_text(encoding="utf-8")
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: разрезан на 0:01.0"])

    def test_split_title_is_reported_as_one_cut(self):
        # Round-fix-1/5, item 8: у титра нет data-am-asset — разрез узнаётся
        # по совпадающему тексту обеих половин, не по timeline-полю src.
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "index.html"
            index.write_text(self.text, encoding="utf-8")
            FakeHyperframes().json(None, ["timeline", "split", "#t-1", "1", "--dir", ".", "--json"],
                                   cwd=Path(temp), timeout=1)
            text = index.read_text(encoding="utf-8")
        self.assertEqual(self.diff(text), ["титр «Барсик идёт по саду»: разрезан на 0:01.0"])

    def test_split_without_asset_marker_is_reported_as_a_cut(self):
        # Round-fix-2/5, item 3: Studio может перетащить в клип новый файл,
        # потеряв нашу метку data-am-asset — split всё равно узнаётся по src
        # (общее правило split_pairs.is_split_pair, то же, что у split_fades).
        text = self.text.replace(' data-am-asset="asset-b"', "")
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "index.html"
            index.write_text(text, encoding="utf-8")
            FakeHyperframes().json(None, ["timeline", "split", "#v-2", "2.5", "--dir", ".", "--json"],
                                   cwd=Path(temp), timeout=1)
            after = index.read_text(encoding="utf-8")
        changes = diff_models(model_of(text), model_of(after), names=NAMES)
        self.assertTrue(any("разрезан" in line for line in changes), changes)
        self.assertFalse(any("добавлен" in line or "укорочен" in line for line in changes), changes)

    def test_repeated_split_is_reported_as_cuts_not_additions(self):
        # Round-fix-1/5, item 8: второй разрез того же клипа (родитель — сам
        # новый кусок первого разреза, которого нет в «до») не должен
        # превращаться в «добавлен».
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "index.html"
            index.write_text(self.text, encoding="utf-8")
            runner = FakeHyperframes()
            runner.json(None, ["timeline", "split", "#v-1", "1", "--dir", ".", "--json"],
                       cwd=Path(temp), timeout=1)
            runner.json(None, ["timeline", "split", "#v-1-2", "1.5", "--dir", ".", "--json"],
                       cwd=Path(temp), timeout=1)
            text = index.read_text(encoding="utf-8")
        changes = self.diff(text)
        self.assertEqual(sum(1 for line in changes if "разрезан" in line), 2)
        self.assertTrue(all("добавлен" not in line for line in changes))

    def test_missing_volume_defaults_to_full(self):
        # Round-fix-1/5, item 6: клип без data-volume звучит на 100%, не на 0%
        # (умолчание HyperFrames) — и diff не путает "нет атрибута" со "звук выключен".
        text = self.text.replace(' data-volume="1"', "")
        self.assertIsNone(model_of(text).clip("a-voice").volume)
        self.assertEqual(self.diff(text), [])

    def test_sound_and_titles(self):
        text = set_attr(self.text, "a-voice", "data-volume", "0.5")
        text = set_attr(text, "a-voice", "data-fade-in", "0.5")
        text = set_text(text, "t-1", "Кот")
        lines = self.diff(text)
        self.assertEqual(lines, [
            "титр «Кот»: текст «Барсик идёт по саду» → «Кот»",
            "звук «Голос» (a-voice): громкость 100% (0 дБ) → 50% (−6 дБ)",
            "звук «Голос» (a-voice): плавное появление звука 0,5 с"])
        # Round-fix-2/5, item 8: один стиль минуса (U+2212) везде — не ASCII-дефис.
        self.assertIn("−", lines[1])
        self.assertNotIn("-6", lines[1])

    def test_added_and_removed(self):
        begin, end = element_span(self.text, "t-2")
        text = self.text[:begin] + self.text[end:]
        text = insert_before_root_end(text, '<div id="t-3" class="clip am-title" data-start="1" '
                                            'data-duration="1" data-am-layer="titles"><span>Новый</span></div>')
        self.assertEqual(self.diff(text), ["добавлен титр «Новый» с 0:01.0", "удалён титр «Находит клубок»"])


if __name__ == "__main__":
    unittest.main()
