"""Export the already rendered version or prepared materials, without reopening it."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from ..completion import CompletionError, verify_assembly, verify_manifest
from . import MontageError
from .context import open_context
from .index_io import read_index
from .model import model_hash
from .paths import VERSION_ID
from .portable import copy_composition, copy_file, dependencies, digest, inside, verify_files, write_json
from .probe import probe_media
from .render_steps import checked_output
from .versions import read_meta, read_version_model

_README = """Переносимый комплект / Portable delivery
final.mp4 — готовый ролик / rendered video.
editable/index.html — редактируемая композиция HyperFrames; assets/ рядом с ней.
Open editable/ with HyperFrames Studio. Edit the timeline and Save, then render
from editable/: hyperframes render . --output ../edited.mp4 --json
Откройте editable/ в HyperFrames Studio, измените таймлайн и сохраните.
Для повторного рендера нужен движок HyperFrames версии из manifest.json.
All runtime media/fonts/scripts are local. Keep the whole directory together.
subtitles/titles.srt, if present, contains existing overlay titles, not a transcript.
Субтитры titles.srt содержат созданные титры; распознавание речи не выполнялось.
SHA-256 каждого файла / file checksums: manifest.json.
"""


def _srt_time(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def _montage(ctx, staging, version, probe):
    section = ctx.state.get("montage") or {}
    version = version or section.get("current_version")
    if not isinstance(version, str) or not VERSION_ID.fullmatch(version):
        raise MontageError("сначала соберите версию MP4")
    row = next((item for item in section.get("versions", []) if item["id"] == version), None)
    if row is None:
        raise MontageError("версия не записана в проекте")
    meta, model = read_meta(ctx.paths, version), read_version_model(ctx.paths, version)
    if meta.asset_id != row["asset_id"] or model_hash(model) != meta.model_hash:
        raise MontageError("снимок не совпадает с записанной версией")
    snapshot = ctx.paths.version_dir(version)
    text = read_index(inside(snapshot, "index.html"))
    source, mime = ctx.assets.resolve(meta.asset_id)
    if mime != "video/mp4":
        raise MontageError("готовая версия должна быть MP4")
    checked_output(source, model, text, probe)
    # New snapshots freeze dependencies; old snapshots keep the historic layout.
    if (snapshot / "files.json").is_file():
        verify_files(snapshot, json.loads((snapshot / "files.json").read_text(encoding="utf-8")))
        composition_root = snapshot
    else:
        composition_root = ctx.paths.current
    copy_composition(composition_root, text, staging / "editable")
    copy_file(source, staging / "final.mp4")
    titles = sorted((clip for clip in model.clips if clip.layer == "titles" and clip.text),
                    key=lambda clip: (clip.start, clip.id))
    subtitles = []
    if titles:
        target = staging / "subtitles" / "titles.srt"
        target.parent.mkdir()
        target.write_text("\n\n".join(f"{i}\n{_srt_time(clip.start)} --> {_srt_time(clip.end)}\n{clip.text}"
                                    for i, clip in enumerate(titles, 1)) + "\n", encoding="utf-8")
        subtitles.append("subtitles/titles.srt")
    (staging / "README.txt").write_text(_README, encoding="utf-8")
    from .engine import load_pin
    return {"schema_version": 1, "kind": "montage", "project_id": ctx.project_id,
            "version": version, "engine": {"name": "hyperframes", "version": load_pin()["version"]},
            "video": "final.mp4", "editable": "editable/index.html", "subtitles": subtitles,
            "assets": [{"asset_id": asset_id} for asset_id in dict.fromkeys(
                clip.asset_id for clip in model.clips if clip.asset_id)]}


def verify_export(manifest_path):
    path = Path(manifest_path)
    if path.is_symlink():
        raise MontageError("manifest не должен быть ссылкой")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise MontageError("неподдерживаемая версия комплекта")
        files = verify_files(path.parent, data.get("files"))
        if data.get("kind") == "materials":
            verify_manifest(path)
        elif data.get("kind") == "montage":
            for key in ("video", "editable"):
                if data.get(key) not in files:
                    raise MontageError("в комплекте отсутствует обязательный файл")
            text = inside(path.parent, data["editable"]).read_text(encoding="utf-8")
            used = dependencies(path.parent / "editable", text)
            if not all("editable/" + item in files for item in used):
                raise MontageError("зависимости композиции отсутствуют в manifest")
        else:
            raise MontageError("неизвестный вид комплекта")
    except (OSError, ValueError, KeyError, TypeError, CompletionError) as error:
        raise MontageError("комплект не прошёл проверку") from error
    return data


def export(workspace, project_id, *, destination, version=None, probe=None):
    ctx = open_context(workspace, project_id)
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise MontageError("папка назначения уже существует; выберите новую")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aimaster-export-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        if ctx.state["project"].get("assembly_mode", "montage") == "materials":
            if version is not None:
                raise MontageError("у комплекта материалов нет версии монтажа")
            try:
                data = verify_assembly(ctx.state, ctx.project_dir)
            except CompletionError as error:
                raise MontageError("сначала подготовьте выбранные материалы: assembly materials") from error
            source = inside(ctx.project_dir, ctx.state["assembly"]["manifest"]["path"]).parent
            for entry in data["assets"]:
                copy_file(inside(source, entry["path"]), staging / entry["path"])
            copy_file(inside(source, "README.txt"), staging / "README.txt")
        else:
            data = _montage(ctx, staging, version, probe or probe_media)
        data["files"] = [{"path": path.relative_to(staging).as_posix(), "sha256": digest(path)}
                         for path in sorted(staging.rglob("*")) if path.is_file()]
        write_json(staging / "manifest.json", data)
        verify_export(staging / "manifest.json")
        # Exclusive reservation: never replace an existing user directory.
        try:
            destination.mkdir()
        except FileExistsError as error:
            raise MontageError("папка назначения появилась во время экспорта") from error
        try:
            for item in staging.iterdir():
                shutil.move(str(item), str(destination / item.name))
            verify_export(destination / "manifest.json")
        except BaseException:
            shutil.rmtree(destination)
            raise
    return {"project_id": project_id, "kind": data["kind"], "version": data.get("version"),
            "destination": str(destination), "manifest_path": str(destination / "manifest.json"),
            "files": len(data["files"])}
