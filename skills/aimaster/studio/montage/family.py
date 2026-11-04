"""Executable narrow format handoff: selected clips -> editable draft -> MP4."""
from __future__ import annotations

import json
import math
from dataclasses import asdict

from . import MontageError
from .context import open_context
from .draft import media_prober
from .draft_plan import plan_draft
from .edit import EditRequest
from .formats import catalog, choose, save
from .html_doc import element_attrs
from .index_io import read_index
from .montage_state import check_writable, reopen_for_improvement, require_revision
from .probe import probe_media
from .stale import stale_clips


def brief_text(state):
    script = state.get("script") or {}
    active = script.get("active_version_id")
    script_text = next((item.get("text", "") for item in script.get("versions", [])
                        if item.get("version_id") == active), "")
    blocks = []
    for scene in state.get("scenes", []):
        block = scene.get("script_block") or {}
        blocks.extend(item.get("text", "") for item in block.get("versions", [])
                      if item.get("version_id") == block.get("active_version_id"))
    return "\n".join([script_text, *blocks])


def styles(workspace):
    return {"styles": catalog(workspace)}


def handoff(workspace, project_id, *, style="basic", probe=None):
    ctx = open_context(workspace, project_id)
    if ctx.state["project"].get("assembly_mode", "montage") != "montage":
        raise MontageError("готовые материалы передаются без монтажа")
    entry = choose(ctx.workspace, style, brief=brief_text(ctx.state))
    media = media_prober(ctx.resolve, probe or probe_media)
    plan = plan_draft(ctx.state, media)
    first = media(plan.first_video_asset())
    if not first.width or not first.height:
        raise MontageError("у выбранного видео не удалось прочитать размер кадра")
    divisor = math.gcd(first.width, first.height)
    def clip_data(clip):
        return {**asdict(clip), "source_path": str(ctx.resolve(clip.asset_id))}
    return {"schema_version": 1, "project_id": project_id, "source_revision": ctx.revision,
            "format": entry["profile"], "format_ref": entry["ref"],
            "selection": "brief" if style == "auto" else "explicit",
            "duration": plan.duration, "aspect_ratio": f"{first.width // divisor}:{first.height // divisor}",
            "canvas": {"width": first.width, "height": first.height},
            "scenes": [clip_data(clip) for clip in plan.clips if clip.layer == "video"],
            "audio": [clip_data(clip) for clip in plan.clips if clip.layer != "video"],
            "subtitles": [], "output_dir": str(ctx.paths.current),
            "workshop": {"needed": False, "reason": "supported-generated-clips-format",
                         "entrypoint": "/aiediting new", "runs_automatically": False}}


def apply_preset(workspace, project_id, expected_revision, *, style, expected_model_hash=None,
                 engine=None, runner=None):
    from .service import edit
    ctx = open_context(workspace, project_id)
    require_revision(ctx.state, expected_revision)
    check_writable(ctx.state)
    entry = choose(ctx.workspace, style, brief=brief_text(ctx.state))
    result = edit(workspace, project_id, expected_revision,
                  EditRequest(op="preset", text=json.dumps(entry["profile"], ensure_ascii=False)),
                  expected_model_hash=expected_model_hash, engine=engine, runner=runner)
    return {**result, "style": entry["ref"], "profile": entry["profile"]}


def save_style(workspace, project_id, *, identity, label=None):
    ctx = open_context(workspace, project_id)
    encoded = element_attrs(read_index(ctx.paths.index)).get("root", {}).get("data-am-format")
    if not encoded:
        raise MontageError("сначала примените монтажный стиль")
    return save(ctx.workspace, identity, json.loads(encoded), label=label)


def build(workspace, project_id, expected_revision, *, style=None, improve=False,
          engine=None, runner=None, probe=None):
    from .service import draft, render
    ctx = open_context(workspace, project_id)
    require_revision(ctx.state, expected_revision)
    if improve and ctx.state.get("milestones", {}).get("assembly") == "approved":
        expected_revision = reopen_for_improvement(workspace, project_id, expected_revision)["revision"]
        ctx = open_context(workspace, project_id)
    check_writable(ctx.state)
    current = (ctx.state.get("montage") or {}).get("current_version")
    if bool(current) != bool(improve):
        raise MontageError("для улучшения существующей версии нужен --improve; сначала выдайте базовый ролик")
    style = style or ("auto" if ctx.mode == "autopilot" else "basic")
    manifest = handoff(workspace, project_id, style=style, probe=probe)
    revision = expected_revision
    if not ctx.paths.index.is_file():
        revision = draft(workspace, project_id, revision, engine=engine, runner=runner, probe=probe)["revision"]
    elif stale_clips(read_index(ctx.paths.index), ctx.state):
        raise MontageError("выбранные исходники изменились; сначала montage draft --refresh или --rebuild")
    apply_preset(workspace, project_id, revision, style=style, engine=engine, runner=runner)
    result = render(workspace, project_id, revision, engine=engine, runner=runner, probe=probe,
                    summary=("Улучшение: " if improve else "Базовый ролик: ") + manifest["format"]["label"])
    return {**result, "handoff": manifest, "improvement_optional": True,
            "next": ["montage open", "montage preview", "montage build --improve", "montage export"]}
