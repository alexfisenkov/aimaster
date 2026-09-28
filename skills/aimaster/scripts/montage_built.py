"""Проект «p» с черновиком и собранной версией — заготовка тестов экрана
«Сборка» (service_screen, эндпоинты). Движок подменён (`montage_testkit`),
Node не нужен. Имя не test_* — unittest этот файл сам не запускает."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix,  # noqa: E402
                             seed_workspace, tiny_mp4, tiny_wav, video_state)
from studio.authoring_support import open_store  # noqa: E402
from studio.montage import service  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

INFOS = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
         "b.mp4": MediaInfo(1.5, 108, 192, True, False),
         "v.wav": MediaInfo(5.0, None, None, False, True)}


class BuiltMontage:
    """Две сцены и голос; `draft()` → ревизия 1, `build(1)` → v001, ревизия 2."""

    def __init__(self, base: Path):
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "v.wav": tiny_wav()}
        self.seed = seed_workspace(Path(base), files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.workspace = self.seed.workspace
        self.engine = fake_engine(fake_gsap_prefix(base, files=("gsap", "MotionPathPlugin")))
        self.runner = FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))
        self.paths = montage_paths(self.workspace / "projects" / "p")

    def probe(self, path):
        return INFOS.get(Path(path).name, MediaInfo(3.5, 108, 192, True, True))

    def locate(self):
        return self.engine, ""

    def draft(self) -> dict:
        return service.draft(self.workspace, "p", 0, engine=self.engine, runner=self.runner,
                             probe=self.probe)

    def build(self, revision: int, *, summary=None) -> dict:
        return service.render(self.workspace, "p", revision, summary=summary, engine=self.engine,
                              runner=self.runner, probe=self.probe)

    def draft_and_build(self) -> dict:
        return self.build(self.draft()["revision"])

    def state(self) -> dict:
        return open_store(self.workspace).load("p")
