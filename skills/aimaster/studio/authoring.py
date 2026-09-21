"""Chat-authored writes to canonical creator-studio state, via the CLI.

Ticket 12. Before this module, the only way to put a scenario, scenes,
prompts, a registered asset or a result into a project's `state.json` was
by hand-editing the JSON file directly -- forbidden by the project's own
rules, and unsafe regardless (no revision check, no domain validation, no
asset-signature verification). Every function reachable from here goes
through the same two safety rails every other writer in this package
already uses: `ProjectStore.transact(project_id, expected_revision,
mutation)` for an atomic, optimistic-concurrency write to `state.json`,
and (for questions) `QuestionStore`'s own schema validation. Nothing here
calls a provider, opens a socket, or writes a credential.

Repair, 2026-09-17 (ticket 12 repair, condition 15): this file used to be
one 707-line module holding every responsibility below. It is now a thin
public re-export -- `scripts/creator_studio.py` and every existing test
still do `from studio import authoring` / `authoring.create_project(...)`
unchanged -- over six focused `authoring_*` modules, mirroring how
`decisions.py` re-exports `decision_support`/`decision_stages`/
`decision_cards`/`decision_planners`/`decision_reorder`:

- `authoring_support`  -- openers, id/text validators, mime/asset-role
  checks, the shared stage-not-approved guard, and `mutate` (which now
  also runs `projection.validate_state` before every commit -- ticket 12
  repair, condition 1); none of this is part of the public contract.
  Version numbering/relinking itself lives in `domain._append_group_
  version` (condition 8), not here.
- `authoring_projects`  -- `create_project`, `set_mode`,
  `add_script_version`.
- `authoring_scenes`    -- `set_scenes`, `add_prompt_version`, and
  (ticket 15 repair, поправка 1) `edit_scene_block` -- the chat/CLI door
  onto a scene block's `edit`, gated by the same `decision_stages.
  ensure_action_allowed` the dashboard's own `edit` decision runs
  through.
- `authoring_media`     -- `add_result_version`, `add_reference`.
- `authoring_questions` -- `create_question`, `answer_question`,
  `list_questions`.
- `authoring_milestones` -- `set_milestone`, and (ticket 15, G05)
  `reopen_scenario` -- the chat/CLI door onto `decision_stages.
  build_reopen_mutation`, the same transition the dashboard's
  `reopen-scenario` decision applies.
- `authoring_qa`        -- `set_assembly` (the `qa` stage and `set_qa` are gone,
  G12).

`AuthoringError` still lives in `authoring_support` and is re-exported
here; every module above raises it (a `ValueError` subclass), never a
bare `KeyError`/`AttributeError`, so `scripts/creator_studio.py`'s
`main()` keeps mapping every domain-level refusal to exit code 3 without
needing to know which of the six modules raised it. `reopen_scenario`'s
own "another action is queued/running" refusal is `decision_stages.
DecisionError` instead (also a `ValueError` subclass, so it is caught and
exits 3 exactly the same way) -- see that function's own docstring for
why it is not re-wrapped as `AuthoringError`.
"""

from __future__ import annotations

from .authoring_media import (
    add_reference,
    add_result_version,
    attach_reference,
    edit_reference,
    toggle_scene_reference,
)
from .authoring_milestones import reopen_scenario, set_milestone
from .authoring_projects import create_project, set_mode, add_script_version
from .authoring_qa import set_assembly
from .authoring_questions import answer_question, create_question, list_questions
from .authoring_scenes import (
    add_prompt_version,
    add_scene,
    edit_scene_block,
    reorder_scenes,
    set_gen_mode,
    set_scene_frame_plan,
    set_scenes,
    set_continuity_strategy,
    set_video_mode,
)
from .authoring_support import AuthoringError, open_assets, open_questions, open_store


__all__ = [
    "AuthoringError",
    "open_store",
    "open_assets",
    "open_questions",
    "create_project",
    "set_mode",
    "add_script_version",
    "set_scenes",
    "add_scene",
    "reorder_scenes",
    "set_scene_frame_plan",
    "set_continuity_strategy",
    "set_video_mode",
    "set_gen_mode",
    "add_prompt_version",
    "edit_scene_block",
    "add_result_version",
    "add_reference",
    "attach_reference",
    "edit_reference",
    "toggle_scene_reference",
    "set_milestone",
    "reopen_scenario",
    "create_question",
    "answer_question",
    "list_questions",
    "set_assembly",
]
