"""Какие поля в настоящих ответах `service` монтажа — для проверки канона
(test_montage_docs.py). Движок подменён (montage_testkit.FakeHyperframes), всё
остальное — настоящий код: черновик, правка, откат, diff, сборка, возврат, GSAP,
состояние. Имя не test_* — unittest этот файл сам не запускает."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix, seed_workspace,  # noqa: E402
                             tiny_mp4, tiny_wav, video_state)
from studio.montage import service  # noqa: E402
from studio.montage.desk import PUBLIC_KEYS  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.status import STALE_KEYS  # noqa: E402

INFOS = {"a.mp4": MediaInfo(2.0, 108, 192, True, True), "b.mp4": MediaInfo(1.0, 108, 192, True, True),
         "v.wav": MediaInfo(3.0, None, None, False, True)}


def _status_fields(status: dict) -> set[str]:
    layers = status["layers"]
    return (set(status) | set(status["engine"]) | set(status["skills"]) | set(status["versions"][0])
            | {key for layer in layers for key in layer}
            | {key for layer in layers for clip in layer["clips"] for key in clip}
            | set(status["paths"]) | set(STALE_KEYS))


def _flow(temp: Path) -> dict[str, set[str]]:
    files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "v.wav": tiny_wav()}
    ws = seed_workspace(temp, files, lambda ids: video_state(
        [("s1", "Сад", "Барсик", 2000, ids["a.mp4"]), ("s2", "Клубок", "Клубок", 1000, ids["b.mp4"])],
        audio={"voice": ids["v.wav"]})).workspace
    infos = dict(INFOS)
    engine = fake_engine(fake_gsap_prefix(temp))
    kw = {"engine": engine, "runner": FakeHyperframes(render_bytes=tiny_mp4(b"out"))}
    probe = lambda path: infos[Path(path).name]  # noqa: E731
    status = lambda: service.status(ws, "p", locate=lambda: (engine, ""), runner=kw["runner"])  # noqa: E731
    replies = {"draft": service.draft(ws, "p", 0, probe=probe, **kw)}
    rev = replies["draft"]["revision"]
    replies["draft --refresh"] = service.draft(ws, "p", rev, mode="refresh", probe=probe, **kw)
    replies["draft --rebuild"] = service.draft(ws, "p", rev, mode="rebuild", probe=probe, **kw)
    infos["v001.mp4"] = MediaInfo(status()["duration"], 108, 192, True, True)
    replies["render"] = service.render(ws, "p", replies["draft --rebuild"]["revision"], probe=probe, **kw)
    rev = replies["render"]["revision"]
    replies["edit"] = service.edit(ws, "p", rev, EditRequest(op="trim-start", clip="v-1", seconds=0.5), **kw)
    replies["diff"] = service.diff(ws, "p", **kw)
    replies["undo"] = service.edit(ws, "p", rev, EditRequest(op="undo"), **kw)
    replies["gsap"] = service.gsap(ws, "p", engine=engine)
    replies["restore"] = service.restore(ws, "p", rev, "v001")
    fields = {name: set(reply) for name, reply in replies.items()}
    fields["status (fields)"] = _status_fields(status())
    return fields


def collect_replies() -> dict[str, set[str]]:
    """{команда: поля ответа}. Стол — по коду `desk` (PUBLIC_KEYS), без запуска Studio."""

    with tempfile.TemporaryDirectory() as temp, \
            mock.patch.dict(os.environ, {PREFIX_ENV: str(Path(temp) / "нет-кеша-скиллов")}):
        fields = _flow(Path(temp))
    fields["open"] = {"project_id", "state", *PUBLIC_KEYS}
    fields["close"] = {"project_id", "state"}
    fields["desk notes"] = {"note", "forgotten"}
    return fields
