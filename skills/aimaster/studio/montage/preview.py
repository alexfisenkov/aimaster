"""Short comparable probes on selected source clips, isolated from the edit desk."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import asdict, replace
from types import SimpleNamespace

from . import MontageError
from .canvas import canvas_for
from .context import open_context
from .draft import media_prober
from .draft_html import render_draft_html
from .draft_plan import plan_draft
from .engine import require_engine
from .engine_cli import EngineRunner
from .family import brief_text
from .formats import choose
from .index_io import write_index
from .locks import held_lock
from .media_sync import sync_media
from .paths import MontagePaths
from .portable import digest, verify_files, write_json
from .preset import apply_profile_text
from .probe import probe_media
from .render_run import render_mp4
from .render_steps import checked_output, preflight
from .typeface import sync_fonts
from .vendor import copy_gsap


def preview(workspace, project_id, *, style, duration=6, engine=None, runner=None, probe=None):
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 12:
        raise MontageError("длина пробы — больше 0 и не больше 12 секунд")
    ctx = open_context(workspace, project_id)
    if ctx.state["project"].get("assembly_mode", "montage") != "montage":
        raise MontageError("проба монтажа доступна после выбора montage")
    engine, runner, probe = engine or require_engine(), runner or EngineRunner(), probe or probe_media
    selected = choose(ctx.workspace, style, brief=brief_text(ctx.state))
    media = media_prober(ctx.resolve, probe)
    whole = plan_draft(ctx.state, media)
    duration = min(duration, whole.duration)
    plan = replace(whole, duration=duration, clips=tuple(
        replace(clip, duration=min(clip.duration, duration - clip.start))
        for clip in whole.clips if clip.start < duration))
    canvas = canvas_for(media(plan.first_video_asset()))
    sources = {asset: digest(ctx.resolve(asset)) for asset in plan.media_assets()}
    key = hashlib.sha256(json.dumps({"plan": asdict(plan), "canvas": asdict(canvas),
                                    "style": selected["profile"], "sources": sources,
                                    "engine": engine.version}, sort_keys=True).encode()).hexdigest()
    previews = ctx.paths.root / "previews"
    if previews.is_symlink():
        raise MontageError("папка проб не должна быть ссылкой")
    root = previews / key
    if root.is_symlink():
        raise MontageError("проба не должна быть ссылкой")
    with held_lock(previews / ("." + key + ".lock"), busy="эта проба уже собирается"):
        receipt = root / "preview.json"
        if receipt.is_file():
            try:
                data = json.loads(receipt.read_text(encoding="utf-8"))
                if data.get("key") != key:
                    raise MontageError("не совпал ключ пробы")
                verify_files(root, data.get("files"))
                return {"path": str(root / data["output"]), "style": selected["ref"],
                        "duration": duration, "reused": True, "key": key}
            except (OSError, ValueError, KeyError, TypeError, MontageError):
                pass  # Rebuild a corrupt cache entry, never report its old MP4 as ready.
        if root.exists():
            shutil.rmtree(root)
        paths = MontagePaths(root)
        scripts = copy_gsap(engine.prefix, paths.assets)
        sync_fonts(paths.assets)
        synced = sync_media(((asset, ctx.resolve(asset)) for asset in plan.media_assets()), paths.assets)
        text = apply_profile_text(render_draft_html(plan, canvas,
                                  {asset: entry["src"] for asset, entry in synced.items()}, scripts),
                                  selected["profile"])
        write_index(paths.index, text)
        model, warnings = preflight(paths, engine, runner, text)
        context = SimpleNamespace(paths=paths, media_root=root, project_id="probe", workspace=ctx.workspace)
        output = render_mp4(context, engine, runner, "v001")
        checked_output(output, model, text, probe)
        files = [{"path": path.relative_to(root).as_posix(), "sha256": digest(path)}
                 for path in sorted(root.rglob("*")) if path.is_file() and ".logs" not in path.parts
                 and ".cache" not in path.parts]
        write_json(receipt, {"key": key, "output": output.relative_to(root).as_posix(), "files": files})
        verify_files(root, files)
        return {"path": str(output), "style": selected["ref"], "duration": duration,
                "warnings": warnings, "reused": False, "key": key}
