#!/usr/bin/env python3
"""Сборка: v001 → ассет result → assembly; ошибка на любом шаге — ни версии, ни файла."""

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

from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix,  # noqa: E402
                             seed_workspace, tiny_mp4, tiny_wav, video_state)
from studio.assets import AssetIndex, AssetValidationError  # noqa: E402
from studio.authoring_support import open_assets, open_store  # noqa: E402
from studio.montage import MontageError, render  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.context import open_context  # noqa: E402
from studio.montage.draft import build_current  # noqa: E402
from studio.montage.edit import EditRequest, apply_edit  # noqa: E402
from studio.montage.html_doc import element_attrs, set_attr  # noqa: E402
from studio.montage.index_io import read_index, write_index  # noqa: E402
from studio.montage.montage_state import record_draft  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.render import render_version  # noqa: E402
from studio.montage.verify import lint_problems, network_markers  # noqa: E402
from studio.montage.version_staging import build_lock  # noqa: E402
from studio.montage.versions import read_meta  # noqa: E402
from studio.store import RevisionConflict  # noqa: E402
from studio.workspace import MAX_ASSET_BYTES, MONTAGE_MAX_BYTES  # noqa: E402


class _StudioWritesDuringRender(FakeHyperframes):
    """Рендер, во время которого человек двигает клип мышью в монтажном столе."""

    def run(self, engine, args, *, cwd, timeout):
        result = super().run(engine, args, cwd=cwd, timeout=timeout)
        index = Path(cwd) / "index.html"
        write_index(index, set_attr(read_index(index), "v-2", "data-start", "2.1"))
        return result


class _InterruptedRender(FakeHyperframes):
    """Ctrl+C посреди рендера: часть MP4 уже на диске."""

    def run(self, engine, args, *, cwd, timeout):
        super().run(engine, args, cwd=cwd, timeout=timeout)
        raise KeyboardInterrupt


class RenderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "v.wav": tiny_wav()}
        self.seed = seed_workspace(base, files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.infos = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
                      "b.mp4": MediaInfo(1.5, 108, 192, True, False),
                      "v.wav": MediaInfo(5.0, None, None, False, True)}
        self.output_info = MediaInfo(3.5, 108, 192, True, True)
        self.engine = fake_engine(fake_gsap_prefix(base))
        ctx = open_context(self.seed.workspace, "p")
        build_current(ctx.paths, ctx.state, ctx.resolve, probe=self.probe,
                      engine_prefix=self.engine.prefix)
        record_draft(ctx.store, "p", 0, canvas=Canvas(108, 192))
        self.output = self.seed.workspace.resolve() / "media" / "p" / "montage" / "v001.mp4"

    def probe(self, path):
        return self.infos.get(Path(path).name, self.output_info)

    def render(self, runner=None, **kwargs):
        ctx = open_context(self.seed.workspace, "p")
        runner = runner or FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))
        return render_version(ctx, ctx.revision, engine=self.engine, runner=runner,
                              probe=self.probe, **kwargs)

    def state(self):
        return open_store(self.seed.workspace).load("p")

    def paths(self):
        return open_context(self.seed.workspace, "p").paths

    def test_first_render_is_v001_and_becomes_the_assembly(self):
        outcome = self.render()
        self.assertEqual((outcome.version, Path(outcome.path)), ("v001", self.output))
        self.assertTrue(self.output.is_file())
        self.assertEqual(open_assets(self.seed.workspace).role_of(outcome.asset_id), "result")
        state = self.state()
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["assembly"]["asset_id"], outcome.asset_id)
        self.assertEqual(outcome.changes, ["черновой монтаж: 3 клипа, 3,5 с"])
        self.assertEqual(outcome.warnings, [])
        self.assertEqual(outcome.revision, state["revision"])
        meta = read_meta(self.paths(), "v001")
        self.assertEqual((meta.by, meta.based_on, meta.summary), ("agent", None, "Черновой монтаж"))
        self.assertEqual(read_index(self.paths().version_dir("v001") / "index.html"),
                         read_index(self.paths().index))

    def test_second_render_tells_what_changed(self):
        self.render()
        ctx = open_context(self.seed.workspace, "p")
        apply_edit(self.engine, ctx.paths, EditRequest(op="trim-start", clip="v-1", seconds=0.5),
                   runner=FakeHyperframes())
        outcome = self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        self.assertEqual(outcome.version, "v002")
        self.assertEqual(outcome.changes, ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"])
        meta = read_meta(ctx.paths, "v002")
        self.assertEqual((meta.based_on, meta.summary), ("v001", "клип сцены 1 «Сад»: начало обрезано на 0,5 с"))

    def test_lint_error_means_no_render_and_no_version(self):
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"), lint_report={"ok": False, "findings": [
            {"severity": "error", "code": "missing_local_asset", "message": "нет файла"}]})
        with self.assertRaises(MontageError) as caught:
            self.render(runner)
        self.assertIn("missing_local_asset", str(caught.exception))
        self.assertNotIn("render", [call[0] for call in runner.calls])
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.state()["montage"]["current_version"])

    def test_external_url_is_refused_before_the_engine(self):
        ctx = open_context(self.seed.workspace, "p")
        text = ctx.paths.index.read_text(encoding="utf-8")
        ctx.paths.index.write_text(set_attr(text, "v-1", "style", "background:url(https://x.example/y.png)"),
                                   encoding="utf-8")
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"))
        with self.assertRaises(MontageError) as caught:
            self.render(runner)
        self.assertIn("внешняя ссылка", str(caught.exception))
        self.assertEqual(runner.calls, [])

    def test_bad_output_is_deleted_and_not_recorded(self):
        self.output_info = MediaInfo(2.0, 108, 192, True, True)
        with self.assertRaises(MontageError) as caught:
            self.render()
        self.assertIn("длительность", str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.state()["montage"]["versions"], [])

    def test_failed_render_is_a_clear_message(self):
        with self.assertRaises(MontageError) as caught:
            self.render(FakeHyperframes(render_bytes=None))
        self.assertIn("Сборка не удалась", str(caught.exception))
        self.assertTrue((self.paths().logs / "render-v001.log").is_file())

    def test_stale_revision_is_refused_before_any_work(self):
        ctx = open_context(self.seed.workspace, "p")
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"))
        with self.assertRaises(RevisionConflict):
            render_version(ctx, ctx.revision - 1, engine=self.engine, runner=runner, probe=self.probe)
        self.assertEqual(runner.calls, [])

    def test_state_changed_while_waiting_is_refused_under_the_lock(self):
        ctx = open_context(self.seed.workspace, "p")  # прочитан до чужой записи
        store = open_store(self.seed.workspace)
        store.transact("p", ctx.revision, lambda state: state["project"].update(title="Новое"))
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"))
        with self.assertRaises(RevisionConflict):
            render_version(ctx, ctx.revision, engine=self.engine, runner=runner, probe=self.probe)
        self.assertEqual(runner.calls, [])

    def test_network_access_fails_the_render(self):
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"), render_log=(
            '[INFO] [Compiler] Fetched 11 font face(s) for "Inter" from Google Fonts'))
        with self.assertRaises(MontageError) as caught:
            self.render(runner)
        self.assertIn("AM Inter", str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.state()["montage"]["current_version"])

    def test_network_markers_catch_fonts_and_cdn_scripts_only(self):
        cdn = "[INFO] [Compiler] Inlined CDN script: https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
        local = "[INFO] [Compiler] Embedded local font file assets/fonts/inter-latin-400-normal.woff2 → data URI"
        log = '[INFO] [Compiler] Fetched 11 font face(s) for "Inter" from Google Fonts\n' + local + "\n" + cdn
        self.assertEqual(len(network_markers(log)), 2)
        self.assertEqual(network_markers(local), [])

    def test_fonts_not_from_assets_fail_even_offline(self):
        # Без сети HyperFrames не пишет «from Google Fonts», но подставляет
        # чужой шрифт — ролик офлайн и онлайн разойдётся: это тоже ошибка.
        for line in ("[INFO] [Compiler] Injected deterministic @font-face rules for 1 requested font families",
                     "[WARN] [Compiler] No deterministic font mapping for: Roboto",
                     "[INFO] [Compiler] Rewriting missing gsap script to CDN: assets/x.js → https://cdn"):
            self.assertEqual(network_markers(line), [line], line)

    def test_lint_crash_is_a_problem_too(self):
        self.assertEqual(lint_problems({"ok": False, "error": "boom", "findings": []}),
                         ["lint не смог проверить: boom"])
        self.assertEqual(lint_problems({"ok": False, "findings": []}),
                         ["lint не прошёл, но не назвал ошибок"])

    def test_lint_warnings_travel_with_the_version(self):
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"), lint_report={"ok": True, "findings": [
            {"severity": "warning", "code": "media_without_id", "message": "у клипа нет id"}]})
        self.assertEqual(self.render(runner).warnings, ["media_without_id: у клипа нет id"])

    def test_autopilot_projects_sign_versions_as_autopilot(self):
        store = open_store(self.seed.workspace)

        def autopilot(state):
            state["project"]["mode"] = "autopilot"
        store.transact("p", 1, autopilot)
        self.render()
        self.assertEqual(read_meta(self.paths(), "v001").by, "autopilot")

    def test_edit_in_studio_during_render_is_not_recorded(self):
        with self.assertRaises(MontageError) as caught:
            self.render(_StudioWritesDuringRender(render_bytes=tiny_mp4(b"x")))
        self.assertIn("во время сборки", str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.state()["montage"]["versions"], [])
        self.assertEqual(element_attrs(read_index(self.paths().index))["v-2"]["data-start"], "2.1")

    def test_interrupted_render_leaves_no_partial_file(self):
        with self.assertRaises(KeyboardInterrupt):
            self.render(_InterruptedRender(render_bytes=tiny_mp4(b"x")))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.state()["montage"]["versions"], [])

    def test_vanished_output_is_a_russian_refusal(self):
        def probe(path):
            Path(path).unlink()  # файл пропал между ffprobe и проверкой размера
            return self.output_info
        ctx = open_context(self.seed.workspace, "p")
        with self.assertRaises(MontageError) as caught:
            render_version(ctx, ctx.revision, engine=self.engine,
                           runner=FakeHyperframes(render_bytes=tiny_mp4(b"x")), probe=probe)
        self.assertIn("v001.mp4", str(caught.exception))

    def test_a_second_build_of_the_same_project_is_refused(self):
        with build_lock(self.paths()):
            with self.assertRaises(MontageError) as caught:
                self.render()
        self.assertIn("уже идёт", str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_orphan_mp4_of_a_crashed_build_does_not_block_the_number(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(b"obryvok")
        self.assertEqual(self.render().version, "v001")
        self.assertEqual(self.output.read_bytes(), tiny_mp4(b"out-1"))

    def test_failed_state_write_leaves_no_version_and_no_file(self):
        with mock.patch.object(render, "record_version", side_effect=MontageError("state занят")):
            with self.assertRaises(MontageError):
                self.render()
        self.assertFalse(self.output.exists())
        self.assertEqual([p.name for p in self.paths().versions.iterdir()], [])
        self.assertEqual(self.state()["montage"]["versions"], [])

    def test_failed_publish_is_finished_by_the_next_build(self):
        with mock.patch.object(render, "publish_version", side_effect=OSError("занято")):
            first = self.render()
        self.assertEqual(self.state()["montage"]["current_version"], "v001")
        self.assertTrue(any("v001" in warning for warning in first.warnings))
        self.assertFalse(self.paths().version_dir("v001").exists())
        second = self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        self.assertEqual(second.version, "v002")
        self.assertTrue(self.paths().version_dir("v001").is_dir())
        self.assertEqual(read_meta(self.paths(), "v002").based_on, "v001")
        self.assertEqual(second.changes, [])

    def test_missing_base_snapshot_does_not_block_later_builds(self):
        self.render()
        snapshot = self.paths().version_dir("v001")
        snapshot.rename(snapshot.with_name("потерян"))
        outcome = self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        self.assertEqual(outcome.version, "v002")
        self.assertEqual(len(outcome.changes), 1)
        self.assertIn("v001", outcome.changes[0])
        self.assertIn("не с чем", outcome.changes[0])

    def split_in_studio(self):
        """v-1 → v-1 + v-1-2, как разрез мышью: Studio копирует края звука на обе половины."""

        paths = self.paths()
        text = set_attr(read_index(paths.index), "v-1", "data-duration", "1")
        start = text.index('<video id="v-1"')
        end = text.index("</video>", start) + len("</video>")
        piece = text[start:end]
        for name, value in (("data-start", "1"), ("data-media-start", "1"), ("data-fade-in", "0.4"),
                            ("id", "v-1-2")):
            piece = set_attr(piece, "v-1", name, value)
        write_index(paths.index, text[:end] + piece + text[end:])
        return paths

    def test_studio_split_fades_are_cleared_on_new_pieces(self):
        self.render()
        paths = self.split_in_studio()
        outcome = self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        after = element_attrs(read_index(paths.index))
        self.assertNotIn("data-fade-out", after["v-1"])            # внутренний разрез — без края
        self.assertNotIn("data-fade-in", after["v-1-2"])
        self.assertEqual(after["v-1-2"]["data-fade-out"], "0.4")   # стык сцен — край остаётся
        self.assertIn("am-fade-in", after["v-2"]["class"].split())
        self.assertEqual(read_index(paths.version_dir(outcome.version) / "index.html"),
                         read_index(paths.index))

    def test_fades_on_pieces_known_to_the_last_version_are_left_alone(self):
        paths = self.split_in_studio()
        self.render()  # v001: половина уже есть, её края нормализованы
        # человек сам вернул мягкое начало половине — это его решение, не артефакт разреза
        write_index(paths.index, set_attr(read_index(paths.index), "v-1-2", "data-fade-in", "0.2"))
        self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        self.assertEqual(element_attrs(read_index(paths.index))["v-1-2"]["data-fade-in"], "0.2")


class MontageSizeLimitTests(unittest.TestCase):
    def test_montage_output_has_its_own_limit_and_the_rest_keeps_the_common_one(self):
        self.assertEqual((MONTAGE_MAX_BYTES, MAX_ASSET_BYTES), (2 * 1024 ** 3, 128 * 1024 ** 2))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            media = root / "media"
            for rel in ("p/montage/v001.mp4", "p/montage/final.mp4", "p/clip.mp4"):
                (media / rel).parent.mkdir(parents=True, exist_ok=True)
                (media / rel).write_bytes(tiny_mp4(b"x" * 400))
            index = AssetIndex(root, (media,), max_bytes=100, montage_max_bytes=10_000,
                               db_path=root / ".studio" / "assets.sqlite3")
            asset_id = index.register("media/p/montage/v001.mp4", "result")["asset_id"]
            self.assertEqual(index.resolve(asset_id)[0], media / "p" / "montage" / "v001.mp4")
            for rel in ("media/p/montage/final.mp4", "media/p/clip.mp4"):
                with self.assertRaises(AssetValidationError):
                    index.register(rel, "result")

    def test_workspace_index_knows_the_montage_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp).resolve()
            (workspace / "media").mkdir()
            self.assertEqual(open_assets(workspace).montage_max_bytes, MONTAGE_MAX_BYTES)

    def test_bad_montage_limit_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "media").mkdir()
            for bad in (0, -1, True, 1.5):
                with self.assertRaises(AssetValidationError):
                    AssetIndex(root, (root / "media",), max_bytes=100, montage_max_bytes=bad)


if __name__ == "__main__":
    unittest.main()
