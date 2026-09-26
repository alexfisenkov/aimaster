"""Всё о проекте, что нужно монтажу: хранилище, ассеты, state, папки, имена сцен."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..assets import AssetError, AssetIndex
from ..authoring_support import open_assets, open_store
from ..store import ProjectNotFound, ProjectStore
from ..workspace import WorkspaceError, resolve_workspace_paths
from . import MontageError
from .link_guard import check_montage_folder
from .paths import MontagePaths, montage_paths


def scene_names(state: dict) -> dict[str, str]:
    """{scene_id: "сцены N «Название»"} — для строк diff («клип сцены 1 «Сад»: …»)."""

    scenes = sorted((scene for scene in state.get("scenes") or [] if isinstance(scene, dict)),
                    key=lambda scene: scene.get("order", 0))
    return {scene["scene_id"]: f"сцены {index} «{scene.get('title') or scene['scene_id']}»"
            for index, scene in enumerate(scenes, start=1) if scene.get("scene_id")}


def project_mode(state: dict) -> str:
    return (state.get("project") or {}).get("mode", "guided")


@dataclass(frozen=True)
class ProjectContext:
    workspace: Path
    project_id: str
    store: ProjectStore
    assets: AssetIndex
    state: dict
    project_dir: Path
    media_root: Path

    @property
    def paths(self) -> MontagePaths:
        return montage_paths(self.project_dir)

    @property
    def revision(self) -> int:
        return self.state.get("revision")

    @property
    def mode(self) -> str:
        return project_mode(self.state)

    def resolve(self, asset_id: str) -> Path:
        return self.assets.resolve(asset_id)[0]

    def scene_names(self) -> dict[str, str]:
        return scene_names(self.state)


def open_context(workspace, project_id: str, *, guard: bool = True) -> ProjectContext:
    """Открывает проект заново: state мог поменять дашборд, Studio или другой агент.
    Нет папки, проекта или медиатеки — отказ по-русски, без абсолютных путей.
    `guard` — папка montage без ссылок наружу и своего ffmpeg (`link_guard`);
    выключает его только закрытие стола: своё Studio остановить нужно всегда."""

    try:
        workspace_path, _projects, media_root, _private = resolve_workspace_paths(workspace)
    except (OSError, WorkspaceError) as error:
        raise MontageError(f"нет рабочей папки «{Path(workspace).name}»") from error
    store = open_store(workspace_path)
    try:
        state, project_dir = store.load(project_id), store.project_dir(project_id)
    except ProjectNotFound as error:
        raise MontageError(f"в рабочей папке нет проекта «{project_id}»") from error
    try:
        assets = open_assets(workspace_path)
    except AssetError as error:
        raise MontageError("в рабочей папке нет медиатеки media/ — её создаёт workspace init") from error
    if guard:
        check_montage_folder(montage_paths(project_dir).root)
    return ProjectContext(workspace=workspace_path, project_id=project_id, store=store, assets=assets,
                          state=state, project_dir=project_dir, media_root=media_root)
