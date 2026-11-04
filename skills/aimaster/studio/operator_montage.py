"""Owner-facing family montage gateway; no client-controlled filesystem paths."""
import hashlib
from pathlib import Path
import shutil
import tempfile

from . import authoring
from .family_setup import operation_lease, register_workspace
from .montage import MontageError, service
from .montage.edit import EditRequest
from .montage.context import open_context
from .montage.service_screen import desk_view
from .operator_downloads import DeliveryIndex
from .workspace import resolve_workspace_paths


def _public_edit(result):
    # Typed edit receipt has generated ids/geometry, never local paths. Unknown
    # future top-level service fields do not automatically cross this boundary.
    return {key: result[key] for key in ("revision", "op", "model_hash_before", "model_hash", "duration", "receipt", "style", "profile") if key in result}


def execute(screen, part, project_id, request):
    ws = screen.workspace
    state = authoring.open_store(ws).load(project_id)
    if part == "styles":
        return service.styles(ws)
    register_workspace(ws, state_dir=screen.family_state_dir)
    with operation_lease(screen.family_state_dir, "montage-http"):
        if "expected_revision" in request and request["expected_revision"] != state["revision"]:
            from .store import RevisionConflict
            raise RevisionConflict(request["expected_revision"], state["revision"])
        engine, _ = screen.engines()
        kw = {"engine": engine, "runner": screen.runner}
        revision = request.get("expected_revision")
        if "expected_model_hash" in request:
            from .montage.model import read_model, model_hash
            from .montage.engine import require_engine
            ctx = open_context(ws, project_id)
            current = read_model(engine or require_engine(), ctx.paths.current, cache_dir=ctx.paths.cache, runner=screen.runner)
            if model_hash(current) != request["expected_model_hash"]:
                raise MontageError("Монтаж изменился. Обновите модель перед правкой.")
        if part == "build":
            result = service.build(ws, project_id, revision, style=request["style"], improve=request["improve"], probe=getattr(screen, "family_probe", None), **kw)
            return {key: result[key] for key in ("version", "asset_id", "duration", "revision", "improvement_optional", "next") if key in result} | {"url": "/assets/" + result["asset_id"]}
        if part == "preview":
            result = service.preview(ws, project_id, style=request["style"], duration=request["duration"], probe=getattr(screen, "family_probe", None), **kw)
            source = Path(result["path"])
            with source.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            target = resolve_workspace_paths(ws)[2] / project_id / "montage" / "previews" / (digest + ".mp4")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.resolve().is_relative_to(resolve_workspace_paths(ws)[2].resolve()) or target.is_symlink():
                raise MontageError("unsafe preview destination")
            if not target.exists():
                shutil.copyfile(source, target)
            asset = authoring.open_assets(ws).register(target.relative_to(Path(ws)).as_posix(), "result")
            return {key: result[key] for key in ("style", "duration", "reused", "key")} | {"url": "/assets/" + asset["asset_id"]}
        if part == "export":
            private = resolve_workspace_paths(ws)[3]
            with tempfile.TemporaryDirectory(prefix="delivery-", dir=private) as temporary:
                result = service.export(ws, project_id, destination=Path(temporary) / "packet", version=request["version"], probe=getattr(screen, "family_probe", None))
                download = DeliveryIndex(ws).publish(result["destination"])
            return {"project_id": project_id, "kind": result["kind"], "version": result.get("version"), **download}
        if part == "preset":
            return _public_edit(service.apply_preset(ws, project_id, revision, style=request["style"],
                expected_model_hash=request["expected_model_hash"], **kw))
        if part == "edit":
            return _public_edit(service.edit(ws, project_id, revision, EditRequest(**request["edit"]),
                expected_model_hash=request["expected_model_hash"], **kw))
        if part == "save-style":
            return service.save_style(ws, project_id, identity=request["identity"], label=request["label"])
        if part == "open-edit":
            with screen.keeper.lock(project_id):
                result = service.open_desk(ws, project_id, edit=True, expected_revision=revision,
                    engine=engine, desk=screen.desk_factory(engine))
                paths = open_context(ws, project_id).paths
                screen.keeper.opened(project_id, paths)
                return {"project_id": project_id, "revision": result["revision"],
                        "reopened": result["reopened"], **desk_view(result, paths)}
        raise MontageError("unsupported montage operation")
