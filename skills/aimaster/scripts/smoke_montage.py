"""Шаг «монтаж» смоука чистой машины (`smoke_clean_machine.py`).

Без движка (чистая машина): `montage status` и отказ `montage draft` (код 3)
называют одну и ту же команду установки. С движком (`--with-engine`: движок,
уже поставленный на этой машине, находится до подмены HOME) — второй проект
доводится через CLI до сборки (клипы — ffmpeg) и проходит montage draft →
render v001 → status. Имя не test_* — unittest этот файл не запускает."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from smoke_kit import CLI, SKILL, SmokeError, cli, expect, log, run_refused, write_png

MONTAGE_PROJECT = "smoke-montage"
ENGINE_ENV = "AIMASTER_HYPERFRAMES_DIR"


def montage_without_engine(env: dict, workspace: Path, project: str, status: dict) -> None:
    install = status["engine"].get("install") or ""
    expect(install.endswith("--install-deps") and "install.py" in install,
           "montage status: без движка нет команды установки: %s" % status["engine"])
    expect(status["skills"].get("status") == "missing",
           "montage status: скиллов HyperFrames на чистой машине быть не может: %s" % status["skills"])
    err = run_refused(env, CLI, "montage", "draft", workspace, project,
                      "--expected-revision", status["revision"])
    expect("Монтажный движок не готов" in err and install in err,
           "montage draft: ждали отказ с командой установки «%s», получили %s" % (install, err[-800:]))
    log("  монтаж: движка нет — status и отказ montage draft называют одну команду установки")


def make_clip(ffmpeg: str, path: Path, seconds: float, color: str, freq: int) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=180x320:r=30:d=%s" % (color, seconds), "-f", "lavfi", "-i",
                    "sine=frequency=%s:duration=%s" % (freq, seconds), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-g", "30", "-c:a", "aac", "-shortest", str(path)],
                   check=True, stdin=subprocess.DEVNULL, timeout=120)


def project_ready_for_assembly(env: dict, workspace: Path) -> int:
    """Видеопроект в автопилоте, доведённый через CLI до сборки: две сцены с
    принятыми картинками и видео (клипы — ffmpeg); возвращает ревизию."""

    ffmpeg = shutil.which("ffmpeg")
    expect(ffmpeg, "движок монтажа стоит, а ffmpeg нет — нечем сделать клипы для черновика")
    folder = workspace / "media" / "монтаж"
    folder.mkdir(parents=True, exist_ok=True)
    write_png(folder / "кадр.png")
    make_clip(ffmpeg, folder / "клип 1.mp4", 2.0, "red", 440)
    make_clip(ffmpeg, folder / "клип 2.mp4", 1.0, "blue", 660)
    ids = {name: cli(env, "asset", "register", workspace, "--path", "media/монтаж/" + name,
                     "--role", "result")["asset_id"] for name in ("кадр.png", "клип 1.mp4", "клип 2.mp4")}
    p = MONTAGE_PROJECT
    rev = cli(env, "project", "create", workspace, p, "--title", "Проба «монтаж»", "--type", "video",
              "--mode", "autopilot")["revision"]
    rev = cli(env, "script", "add-version", workspace, p, "--text", "Кот Барсик находит клубок.",
              "--reason", "смоук", "--expected-revision", rev)["revision"]
    scenes = folder / "сцены.json"
    scenes.write_text(json.dumps([{"scene_id": "s1", "title": "Сад", "text": "Барсик идёт по саду",
                                   "duration_ms": 2000},
                                  {"scene_id": "s2", "title": "Клубок", "text": "Находит клубок",
                                   "duration_ms": 1000}], ensure_ascii=False), encoding="utf-8")
    rev = cli(env, "scenes", "set", workspace, p, "--file", scenes, "--expected-revision", rev)["revision"]
    rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    for kind in ("image", "motion"):
        for scene in ("s1", "s2"):
            rev = cli(env, "prompt", "add-version", workspace, p, "--scene", scene, "--kind", kind,
                      "--text", "кадр " + scene, "--reason", "смоук", "--expected-revision", rev)["revision"]
    rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    for kind, files in (("image", ("кадр.png", "кадр.png")), ("video", ("клип 1.mp4", "клип 2.mp4"))):
        for scene, name in zip(("s1", "s2"), files):
            rev = cli(env, "result", "add-version", workspace, p, "--scene", scene, "--kind", kind,
                      "--asset-id", ids[name], "--expected-revision", rev)["revision"]
        for scene in ("s1", "s2"):
            rev = cli(env, "decide", workspace, p, "approve", "--target",
                      "result:scene:%s:%s-v1" % (scene, kind), "--expected-revision", rev)["revision"]
        rev = cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]
    return cli(env, "stage", "approve", workspace, p, "--expected-revision", rev)["revision"]  # звук


def montage_with_engine(env: dict, workspace: Path) -> None:
    rev = project_ready_for_assembly(env, workspace)
    p = MONTAGE_PROJECT
    drafted = cli(env, "montage", "draft", workspace, p, "--expected-revision", rev)
    expect(drafted.get("clips") == 2 and drafted.get("duration") == 3.0,
           "montage draft: неожиданный черновик %s" % json.dumps(drafted, ensure_ascii=False)[:800])
    built = cli(env, "montage", "render", workspace, p, "--expected-revision", drafted["revision"])
    expect(built.get("version") == "v001" and built.get("warnings") == [] and Path(built["path"]).is_file(),
           "montage render: неожиданная сборка %s" % json.dumps(built, ensure_ascii=False)[:800])
    status = cli(env, "montage", "status", workspace, p, "--json")
    expect((status.get("current_version"), status.get("unrendered_changes")) == ("v001", False)
           and status["paths"].get("output") == built["path"],
           "montage status после сборки: %s" % json.dumps(status, ensure_ascii=False)[:800])
    log("  монтаж: движок %s, черновик → v001 (%s с), скиллы HyperFrames: %s"
        % (status["engine"]["version"], built["duration"], drafted["skills"]["status"]))


def step_montage(env: dict, workspace: Path, project: str, with_engine: bool) -> None:
    """`project` — видеопроект смоука без монтажа (для проверки статуса и отказа)."""

    status = cli(env, "montage", "status", workspace, project, "--json")
    expect(status.get("exists") is False and status.get("current_version") is None
           and status.get("layers") == [],
           "montage status: неожиданная форма %s" % json.dumps(status, ensure_ascii=False)[:800])
    state = status["engine"]["state"]
    expect(state == ("installed" if with_engine else "missing"),
           "montage status: engine.state=%s, а смоук %s движка" % (state, "с" if with_engine else "без"))
    if with_engine:
        montage_with_engine(env, workspace)
    else:
        montage_without_engine(env, workspace, project, status)


def installed_engine_prefix() -> str:
    """--with-engine: движок, уже поставленный на этой машине, — до подмены HOME."""

    if str(SKILL) not in sys.path:
        sys.path.insert(0, str(SKILL))
    from studio.montage.engine import locate
    found, reason = locate()
    if found is None:
        raise SmokeError("--with-engine: монтажный движок не найден: %s" % reason)
    return str(found.prefix)
