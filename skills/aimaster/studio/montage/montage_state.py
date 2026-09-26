"""Раздел state["montage"]: черновик, собранная версия, возврат к версии.

Каждая запись — одна транзакция `authoring_support.mutate` (с validate_state):
версия и `assembly` меняются вместе, иначе дашборд показал бы одно, а «Принять»
приняло бы другое. Запись в историю проекта — в той же транзакции.
"""

from __future__ import annotations

from .. import domain
from ..assets import AssetError, AssetIndex
from ..authoring_qa import apply_assembly
from ..authoring_support import (mutate, require_project, require_result_asset_role,
                                 require_stage_not_approved)
from ..store import ProjectStore, RevisionConflict
from . import MontageError
from .canvas import DEFAULT_HEIGHT, DEFAULT_WIDTH, Canvas
from .versions import VersionMeta

# domain.append_history принимает только эти два (ACTOR_LABELS дашборда:
# «Вы»/«Агент»); владелец версии монтажа (VersionMeta.by) шире —
# owner пишет её как человек («Вы»), agent/autopilot — как агент.
_HISTORY_ACTOR_FOR_BY = {"agent": "agent", "autopilot": "agent", "owner": "you"}


class StaleRevision(RevisionConflict):
    """Та же RevisionConflict (дашборд и CLI ловят её как раньше), но текст —
    человеку по-русски, а не «revision conflict: expected …»."""

    def __init__(self, expected_revision, current_revision):
        RuntimeError.__init__(self, "проект изменился — обновите номер ревизии: "
                                    f"сейчас {current_revision}")
        self.expected_revision, self.current_revision = expected_revision, current_revision


def require_revision(state: dict, expected_revision: int) -> None:
    if state.get("revision") != expected_revision:
        raise StaleRevision(expected_revision, state.get("revision"))


def _mutate(store, project_id, expected_revision, mutator):
    try:
        return mutate(store, project_id, expected_revision, mutator)
    except StaleRevision:
        raise
    except RevisionConflict as error:
        raise StaleRevision(error.expected_revision, error.current_revision) from error


def _history_actor(by: str) -> str:
    return _HISTORY_ACTOR_FOR_BY.get(by, "agent")


def _resolved_mime(assets: AssetIndex, asset_id: str) -> str:
    # round-fix-2/5, item 8: без английского текста исключения AssetIndex
    # (assets.py говорит "registered asset has changed" и т. п.) — один
    # русский отказ на любую причину: не найден, изменился, не читается.
    try:
        _, mime_type = assets.resolve(asset_id)
    except AssetError:
        raise MontageError(f"файл версии {asset_id} изменился или удалён") from None
    return mime_type


def _resolved_role(assets: AssetIndex, asset_id: str) -> str:
    try:
        return assets.role_of(asset_id)
    except AssetError:
        raise MontageError(f"файл версии {asset_id} изменился или удалён") from None


def montage_section(state: dict) -> dict:
    section = state.get("montage")
    if isinstance(section, dict):
        return section
    return {"current_version": None, "versions": [],
            "canvas": {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT}}


def check_writable(state: dict) -> None:
    project = require_project(state)
    if project.get("type") == "photo":
        raise MontageError("у фото-проекта монтажа нет: его сборка — принятая картинка")
    require_stage_not_approved(state, "assembly", "montage")


def record_draft(store: ProjectStore, project_id: str, expected_revision: int, *,
                 canvas: Canvas) -> dict:
    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        section["canvas"] = canvas.to_dict()
        state["montage"] = section
        domain.append_history(state, "agent", "montage-drafted", "assembly")

    _, new_state = _mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}


def record_version(store: ProjectStore, assets: AssetIndex, project_id: str,
                   expected_revision: int, *, meta: VersionMeta) -> dict:
    # Полное чтение файла + sha256 (до 2 ГиБ у результата монтажа) — до
    # транзакции: под файловой блокировкой store.transact держать эту работу
    # незачем (round-fix-1/5, item 10).
    mime_type = _resolved_mime(assets, meta.asset_id)
    require_result_asset_role(_resolved_role(assets, meta.asset_id), "a montage version")
    actor = _history_actor(meta.by)

    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        if any(item["id"] == meta.version for item in section["versions"]):
            raise MontageError(f"версия {meta.version} уже записана — версии не перезаписываются")
        section["versions"].append({"id": meta.version, "asset_id": meta.asset_id,
                                    "created_at": meta.created_at, "by": meta.by,
                                    "based_on": meta.based_on, "summary": meta.summary})
        section["current_version"] = meta.version
        state["montage"] = section
        apply_assembly(state, mime_type, meta.asset_id, meta.summary or None)
        domain.append_history(state, actor, "montage-built", "assembly", target_id=meta.version)

    _, new_state = _mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}


def record_restore(store: ProjectStore, assets: AssetIndex, project_id: str,
                   expected_revision: int, *, version_id: str, actor: str = "agent") -> dict:
    # Тот же порядок, что в record_version: сначала найти версию и прочитать
    # её актив (полное чтение файла — вне блокировки state), потом — короткая
    # транзакция. store.transact сам отклонит устаревший expected_revision,
    # если state успел измениться между этим чтением и записью; повторная
    # проверка внутри mutator — на случай, если сама запись о версии за это
    # время исчезла или указывает на другой актив.
    current_state = store.load(project_id)
    check_writable(current_state)
    section = montage_section(current_state)
    entry = next((item for item in section["versions"] if item["id"] == version_id), None)
    if entry is None:
        raise MontageError(f"нет версии {version_id}")
    mime_type = _resolved_mime(assets, entry["asset_id"])

    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        current_entry = next((item for item in section["versions"] if item["id"] == version_id), None)
        if current_entry is None:
            raise MontageError(f"нет версии {version_id}")
        if current_entry["asset_id"] != entry["asset_id"]:
            raise MontageError(f"версия {version_id} изменилась — повторите")
        section["current_version"] = version_id
        state["montage"] = section
        apply_assembly(state, mime_type, entry["asset_id"], entry.get("summary") or None)
        domain.append_history(state, actor, "montage-restored", "assembly", target_id=version_id)

    _, new_state = _mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}
