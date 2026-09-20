"""Chat-authored project lifecycle and scenario versions.

Ticket 12 repair, condition 15: one of six `authoring_*` responsibility
modules split out of the former monolithic `authoring.py` -- this one owns
`project create`, `project set-mode` and `script add-version`. See
`authoring_support.py`'s module docstring for the split's rationale, and
`studio/authoring.py` for the public re-export every existing caller
(`scripts/creator_studio.py`, every test) keeps using unchanged.
"""

from __future__ import annotations

from . import chat_decisions, domain
from .authoring_support import (
    _AUTHOR,
    AuthoringError,
    mutate,
    new_project_directory,
    non_empty_text,
    require_project,
    safe_id,
)
from .projection import ProjectionError, validate_state
from .store import ProjectStore


_PROJECT_TYPES = frozenset({"photo", "video", "mixed"})
_PROJECT_MODES = frozenset({"guided", "autopilot"})


def create_project(store: ProjectStore, project_id: str, title: str, project_type: str, mode: str) -> dict:
    """Create a brand-new project directory at revision 0.

    Not built on `store.transact` -- there is no existing revision to
    check yet. Refuses a duplicate id (including the reserved,
    always-excluded `nocturne-47`) by reading `store.list_projects()`
    first, which already applies `ProjectStore`'s own exclusion rules.

    The initial `state.json` is written through `ProjectStore.
    _atomic_replace` (ticket 12 repair, condition 14) -- the exact same
    fsync-then-`os.replace` routine `transact` uses for every later
    write, kept in the one place that owns it, rather than a second,
    independently-written copy of that routine living here.
    """

    safe_id(project_id, "project_id")
    non_empty_text(title, "title")
    if project_type not in _PROJECT_TYPES:
        raise AuthoringError("project type must be photo, video or mixed")
    if mode not in _PROJECT_MODES:
        raise AuthoringError("mode must be guided or autopilot")

    existing = store.list_projects()
    if project_id == "nocturne-47" or any(item["id"] == project_id for item in existing):
        raise AuthoringError(f"project already exists or is reserved: {project_id}")

    project_dir = new_project_directory(store, project_id)
    state = {
        "revision": 0,
        "project": {
            "id": project_id,
            "title": title,
            "type": project_type,
            "mode": mode,
            "status": "active",
            "order": len(existing),
        },
        "milestones": {},
        "script": {"active_version_id": None, "versions": []},
        "history": [],
    }
    if project_type in {"video", "mixed"}:
        state["gen_mode"] = "per_scene"
    # Ticket 12 repair, condition 1: `create_project` is the one write in
    # this package that does not go through `authoring_support.mutate`
    # (there is no existing revision to check yet) -- so it is the one
    # place that must call `validate_state` for itself, rather than
    # getting it for free from `mutate`'s own wrapper.
    try:
        validate_state(state)
    except ProjectionError as error:
        raise AuthoringError(str(error)) from error
    ProjectStore._atomic_replace(project_dir / "state.json", state)
    return {"project_id": project_id, "revision": 0}


def set_mode(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    mode: str,
    *,
    operation_id: str | None = None,
) -> dict:
    """Change a project's `guided`/`autopilot` mode (R13, ticket 12
    repair poправка оркестратора 2). Any stage, any milestone status --
    the mode governs how the *next* question is asked, not what has
    already been decided, so unlike `add_script_version` this needs no
    approved-stage guard.
    """

    if mode not in _PROJECT_MODES:
        raise AuthoringError("mode must be guided or autopilot")

    result = chat_decisions.apply(
        store,
        None,
        project_id,
        expected_revision,
        action_type="set-mode",
        target_id="project",
        payload={"mode": mode},
        operation_id=operation_id,
    )
    response = {"project_id": project_id, "mode": mode, "revision": result["revision"]}
    if operation_id is not None:
        response["replayed"] = result["replayed"]
    return response


def add_script_version(
    store: ProjectStore, project_id: str, expected_revision: int, text: str, reason: str
) -> dict:
    """Append and activate one independent whole-scenario version.

    Scenario prose remains locked while its milestone is approved. In a
    draft scenario, including immediately after a reopen, a new version
    never rewrites or marks scene descriptions, links or linkage status
    (D01); those records have their own version history.
    """

    non_empty_text(text, "text")
    non_empty_text(reason, "reason")

    def mutator(state):
        milestones = state.get("milestones")
        if isinstance(milestones, dict) and milestones.get("scenario") == "approved":
            raise AuthoringError(
                "scenario is already approved; script add-version would "
                "silently invalidate scenes already built on it"
            )
        version = domain.append_script_version(state, text, reason, _AUTHOR)
        domain.append_history(state, "agent", "script-ready", "scenario")
        return version

    version, new_state = mutate(store, project_id, expected_revision, mutator)
    return {
        "project_id": project_id,
        "version_id": version["version_id"],
        "revision": new_state["revision"],
    }
