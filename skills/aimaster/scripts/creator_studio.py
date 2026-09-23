#!/usr/bin/env python3
"""Operator CLI for the local creator studio.

`serve`/`grant`/`claim`/`finish`/`recover` (ticket 09) run the loopback
server and bridge chat-only actions to the durable ledger — see
`skills/aimaster/studio/runner.py` for that contract.

`project`/`script`/`scenes`/`prompt`/`asset`/`result`/`reference`/
`milestone`/`question` (ticket 12) are how chat writes canonical project
state and registers local media — without hand-editing `state.json` —
through `skills/aimaster/studio/authoring.py`. Same
rule as every other command here: no live provider call, no credential, no
network request beyond the loopback HTTP server itself.

`scenario reopen` (ticket 15, G05) is chat's own door onto the same
scenario-reopen transition the dashboard's `reopen-scenario` decision
applies — both now enter `studio.chat_decisions` and then
`studio/decision_stages.py`'s `build_reopen_mutation`. `scene edit` (ticket 15
repair) is chat's own door onto an independent scene-description `edit`, gated by the same
`allowed_actions` the dashboard's own `edit` decision runs through — see
`studio/authoring_scenes.py`'s `edit_scene_block`.
"""

import argparse
import json
import sys
import time
from pathlib import Path


# Amendment 2026-09-16 (ticket 09, point 4): find the `studio` package
# relative to this file, exactly like the neighboring `state_cli.py` finds
# its sibling `validate_config.py` — so this CLI runs correctly regardless
# of the caller's current working directory.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))
# Profiles are optional and are supplied explicitly with --profile <path>.
# The public package does not include any personal profile.

from studio import authoring  # noqa: E402
from studio import chat_decisions  # noqa: E402
from studio.adapters import AdapterError  # noqa: E402
from studio.assets import ASSET_ROLES, AssetError, REFERENCE_ROLES  # noqa: E402
from studio.authoring import AuthoringError  # noqa: E402
from studio.authoring_questions import resolve_cli_answer  # noqa: E402
from studio.decision_support import DecisionError  # noqa: E402
from studio.decision_reorder import REORDERABLE_COLLECTIONS  # noqa: E402
from studio.domain import derive_view_stage  # noqa: E402
from studio.ledger import GRANT_REQUIRED_ACTIONS, TERMINAL_STATUSES, LedgerError  # noqa: E402
from studio.questions import QUESTION_KINDS, QuestionError, QuestionNotFound  # noqa: E402
from studio.runner import open_ledger, open_runner  # noqa: E402
from studio.platform_compat import ensure_utf8_stdio  # noqa: E402
from studio.server import serve  # noqa: E402
from studio.store import StoreError  # noqa: E402
from studio.workspace import WorkspaceError  # noqa: E402
from studio.autopilot import AUTOPILOT_NOTICE, stop_autopilot_spending  # noqa: E402
from studio.library_projects import materialize as materialize_library_entry  # noqa: E402
from creator_studio_workspace import add_workspace_subcommands  # noqa: E402


def command_serve(args):
    running = serve(args.workspace, port=args.port)
    print(json.dumps({"base_url": running.base_url}, ensure_ascii=False), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        running.close()


def command_grant(args):
    ledger = open_ledger(args.workspace)
    grant_id = ledger.issue_grant(args.project, args.action_class, args.expires_at)
    print(json.dumps({"grant_id": grant_id}, ensure_ascii=False))


def command_claim(args):
    runner = open_runner(args.workspace, profile_path=args.profile)
    job = runner.claim(args.worker)
    print(json.dumps(job, ensure_ascii=False))


def command_finish(args):
    runner = open_runner(args.workspace)
    public_result = json.loads(args.public_result.read_text(encoding="utf-8"))
    if not isinstance(public_result, dict):
        raise ValueError("--public-result file must contain a JSON object")
    action = runner.finish(
        args.action_id, args.status, public_result, external_id=args.external_id
    )
    print(
        json.dumps(
            {
                "action_id": action["action_id"],
                "status": action["status"],
                "revision": action["revision"],
            },
            ensure_ascii=False,
        )
    )


def _recovered_summary(item):
    summary = {"action_id": item["action_id"], "status": item["status"]}
    if "refusal" in item:
        summary["refusal"] = item["refusal"]
    return summary


def report_recovery_refusals(recovered):
    """Print one stderr line per refused item; return whether any were refused.

    A refused item is a `recover_inflight` row still `running` because the
    verifier could not be trusted (see
    `studio.ledger.ActionLedger.recover_inflight`, ticket 09 second attempt
    condition 4) — distinguished from a genuinely recovered item by
    carrying a `refusal` key at all.

    Kept as a small, pure, directly testable unit rather than inlined in
    `command_recover`: this CLI's own non-interactive verifier
    (`runner._default_recovery_verifier`) always returns the same fixed
    `{"status": "outcome_unknown"}`, so it can never itself produce a
    refusal — there is nothing wrong with a hardcoded dict for it to
    report. That makes this path unreachable end to end through
    `creator_studio.py recover` today (it becomes reachable once a real
    verifier is wired in, e.g. ticket 11's in-process decision worker); a
    subprocess test asserting on it would therefore prove nothing. Testing
    this function directly, with a fabricated `recovered` list, proves the
    reporting and exit-code logic itself is correct so it is *ready* for
    that verifier.
    """

    refused = [item for item in recovered if "refusal" in item]
    for item in refused:
        print(
            f"recover: refused {item['action_id']} ({item['refusal']})",
            file=sys.stderr,
        )
    return bool(refused)


def command_recover(args):
    runner = open_runner(args.workspace)
    recovered = runner.recover()
    print(
        json.dumps(
            [_recovered_summary(item) for item in recovered],
            ensure_ascii=False,
        )
    )
    if report_recovery_refusals(recovered):
        # Condition 4 (ticket 09, second attempt): a refusal is not a usage
        # mistake (exit 2) and, unlike every other domain error in `main`'s
        # `except` block below, it was never raised as an exception —
        # `recover_inflight` isolates it per-action instead of raising, by
        # design (see its own docstring). `DOMAIN_ERROR_EXIT_CODE` is the
        # same code every other domain-level refusal already exits with,
        # so a caller does not need to parse stderr to tell "nothing was
        # confirmed for at least one action" apart from a clean recovery.
        raise SystemExit(DOMAIN_ERROR_EXIT_CODE)


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False))


def _with_mode_notice(payload, mode):
    """Spec 2026-09-23 §2: switching autopilot on warns once, in the output."""

    if mode == "autopilot" and isinstance(payload, dict):
        return {**payload, "notice": AUTOPILOT_NOTICE}
    return payload


def _after_mode_change(workspace, project_id, payload, mode):
    """Critic finding 1: leaving autopilot cancels its queued paid actions;
    `cancelled_actions` lists them (moved to `needs_chat`)."""

    cancelled = stop_autopilot_spending(open_ledger(workspace), project_id, mode)
    return _with_mode_notice({**payload, "cancelled_actions": cancelled}, mode)


def command_project_create(args):
    store = authoring.open_store(args.workspace)
    _print(
        _with_mode_notice(
            authoring.create_project(store, args.project_id, args.title, args.type, args.mode),
            args.mode,
        )
    )


def command_script_add_version(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.add_script_version(
            store, args.project, args.expected_revision, args.text, args.reason
        )
    )


def command_scenario_reopen(args):
    """Chat's direct door onto the dashboard's scenario-reopen mutation."""

    _print(
        chat_decisions.apply(
            authoring.open_store(args.workspace),
            open_ledger(args.workspace),
            args.project,
            args.expected_revision,
            action_type="reopen-scenario",
            target_id="scenario",
            payload=_decision_payload(args.comment),
            operation_id=args.operation_id,
        )
    )


def command_scene_edit(args):
    """Ticket 15 repair (поправка оркестратора 1): chat's own door onto a
    independent scene description's `edit`, reached through `authoring.edit_scene_block`
    rather than the ledger — same relationship `command_scenario_reopen`
    above has to `authoring.reopen_scenario`."""

    store = authoring.open_store(args.workspace)
    if args.field is None:
        if args.text is None:
            raise ValueError("scene edit requires --field/--value or legacy --text")
        field = "text"
        value = args.text
    else:
        if args.value is None or args.text is not None:
            raise ValueError("scene edit --field requires --value and cannot use --text")
        field = args.field
        value = int(args.value) if field == "duration_ms" else args.value
    _print(
        authoring.edit_scene_block(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene_id,
            field=field,
            value=value,
            reason=args.reason,
        )
    )


def command_scene_add(args):
    store = authoring.open_store(args.workspace)
    _print(authoring.add_scene(store, args.project, args.expected_revision))


def command_scenes_set(args):
    store = authoring.open_store(args.workspace)
    scenes_input = json.loads(args.file.read_text(encoding="utf-8"))
    _print(authoring.set_scenes(store, args.project, args.expected_revision, scenes_input))


def command_scenes_reorder(args):
    store = authoring.open_store(args.workspace)
    _print(authoring.reorder_scenes(store, args.project, args.expected_revision, args.order))


def command_prompt_add_version(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.add_prompt_version(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene,
            kind=args.kind,
            text=args.text,
            reason=args.reason,
            prompt_id=args.prompt_id,
            target=args.target,
        )
    )


def command_asset_register(args):
    assets = authoring.open_assets(args.workspace)
    _print(assets.register(args.path, args.role))


def command_result_add_version(args):
    store = authoring.open_store(args.workspace)
    assets = authoring.open_assets(args.workspace)
    _print(
        authoring.add_result_version(
            store,
            assets,
            args.project,
            args.expected_revision,
            scene_id=args.scene,
            kind=args.kind,
            asset_id=args.asset_id,
            result_id=args.result_id,
            caption=args.caption,
            target=args.target,
        )
    )


_LIBRARY_REFERENCE_KINDS = {"character", "product", "location", "style", "other"}


def command_reference_add(args):
    store = authoring.open_store(args.workspace)
    assets = authoring.open_assets(args.workspace)
    kind, asset_id, name, library_id = args.kind, args.asset_id, args.name, None
    if args.from_library is not None:
        # Spec 2026-09-23 §3: register the library file as a project asset
        # and create an uploaded reference from it.
        if asset_id is not None:
            raise ValueError("--from-library and --asset-id are mutually exclusive")
        materialized = materialize_library_entry(args.workspace, args.from_library)
        entry, library_id = materialized["entry"], args.from_library
        if entry["kind"] == "voice":
            raise ValueError("a voice entry attaches to a character: use `reference attach --from-library`")
        derived = "video" if materialized["media"] == "video" else entry["kind"]
        if derived not in _LIBRARY_REFERENCE_KINDS | {"video"}:
            derived = "other"
        kind = kind or derived
        asset_id = materialized["asset"]["asset_id"]
        name = name or entry["label"]
    if kind is None:
        raise ValueError("reference add requires --kind (or --from-library)")
    result = authoring.add_reference(
        store,
        assets,
        args.project,
        args.expected_revision,
        kind=kind,
        asset_id=asset_id,
        name=name,
        source="upload" if library_id else args.source,
        usage=args.usage,
        scene_id=args.scene,
        all_scenes=args.all_scenes,
    )
    if library_id is not None:
        result = {**result, "library_id": library_id, "asset_id": asset_id, "kind": kind}
    _print(result)


def command_reference_attach(args):
    store = authoring.open_store(args.workspace)
    assets = authoring.open_assets(args.workspace)
    asset_id = args.asset_id
    if (asset_id is None) == (args.from_library is None):
        raise ValueError("reference attach needs exactly one of --asset-id or --from-library")
    if args.from_library is not None:
        asset_id = materialize_library_entry(args.workspace, args.from_library)["asset"]["asset_id"]
    result = authoring.attach_reference(
        store,
        assets,
        args.project,
        args.expected_revision,
        reference_id=args.reference,
        asset_id=asset_id,
    )
    if args.from_library is not None:
        result = {**result, "library_id": args.from_library, "asset_id": asset_id}
    _print(result)


def command_reference_edit(args):
    store = authoring.open_store(args.workspace)
    value = args.value
    if args.field == "voice_enabled":
        value = {"true": True, "false": False}.get(value.lower())
        if value is None:
            raise ValueError("voice_enabled value must be true or false")
    _print(
        authoring.edit_reference(
            store,
            args.project,
            args.expected_revision,
            reference_id=args.reference,
            field=args.field,
            value=value,
        )
    )


def command_reference_toggle(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.toggle_scene_reference(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene,
            reference_id=args.reference,
            on=args.on,
        )
    )


def command_milestone_set(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.set_milestone(
            store, args.project, args.expected_revision, args.stage, args.status
        )
    )


def command_question_create(args):
    store = authoring.open_store(args.workspace)
    questions = authoring.open_questions(args.workspace)
    options = [
        {"id": option_id, "label": label, "description": description}
        for option_id, label, description in args.option
    ]
    validation = json.loads(args.validation) if args.validation is not None else None
    _print(
        authoring.create_question(
            store,
            questions,
            args.project,
            question_id=args.question_id,
            text=args.text,
            kind=args.kind,
            options=options,
            allow_custom=args.allow_custom,
            required=args.required,
            expires_at=args.expires_at,
            validation=validation,
        )
    )


def command_project_set_mode(args):
    store = authoring.open_store(args.workspace)
    _print(
        _after_mode_change(
            args.workspace,
            args.project,
            authoring.set_mode(
                store, args.project, args.expected_revision, args.mode, operation_id=args.operation_id
            ),
            args.mode,
        )
    )


def command_mode_set(args):
    store = authoring.open_store(args.workspace)
    _print(
        _after_mode_change(
            args.workspace,
            args.project,
            chat_decisions.apply(
                store,
                None,
                args.project,
                args.expected_revision,
                action_type="set-mode",
                target_id="project",
                payload={"mode": args.mode},
                operation_id=args.operation_id,
            ),
            args.mode,
        )
    )


def _decision_payload(comment):
    return {"comment": comment} if comment is not None else {}


def command_decide(args):
    store = authoring.open_store(args.workspace)
    ledger = open_ledger(args.workspace)
    _print(
        chat_decisions.apply(
            store,
            ledger,
            args.project,
            args.expected_revision,
            action_type=args.decision,
            target_id=args.target,
            payload=_decision_payload(args.comment),
            operation_id=args.operation_id,
        )
    )


def command_stage(args):
    store = authoring.open_store(args.workspace)
    state = store.load(args.project)
    stage = derive_view_stage(state)["current_stage"]
    if args.decision == "approve":
        action_type = "approve-scenario" if stage == "scenario" else "approve"
    elif stage == "scenario":
        raise DecisionError("scenario rework is handled by revise-scenario")
    else:
        action_type = "reject"
    _print(
        chat_decisions.apply(
            store,
            open_ledger(args.workspace),
            args.project,
            args.expected_revision,
            action_type=action_type,
            target_id=stage,
            payload=_decision_payload(args.comment),
            operation_id=args.operation_id,
        )
    )


def command_reorder(args):
    _print(
        chat_decisions.apply(
            authoring.open_store(args.workspace),
            open_ledger(args.workspace),
            args.project,
            args.expected_revision,
            action_type="reorder",
            target_id=args.collection,
            payload={"order": args.order.split(",")},
            operation_id=args.operation_id,
        )
    )


def command_script_edit(args):
    _print(
        chat_decisions.apply(
            authoring.open_store(args.workspace),
            open_ledger(args.workspace),
            args.project,
            args.expected_revision,
            action_type="edit",
            target_id="scenario",
            payload={"text": args.text, "reason": "правка в чате"},
            operation_id=args.operation_id,
        )
    )


def command_prompt_edit(args):
    _print(
        chat_decisions.apply(
            authoring.open_store(args.workspace),
            open_ledger(args.workspace),
            args.project,
            args.expected_revision,
            action_type="edit",
            target_id=args.target,
            payload={"text": args.text, "reason": "правка в чате"},
            operation_id=args.operation_id,
        )
    )


def command_project_set_gen_mode(args):
    store = authoring.open_store(args.workspace)
    _print(authoring.set_gen_mode(store, args.project, args.expected_revision, args.mode))


def command_scene_plan(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.set_scene_frame_plan(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene_id,
            first=args.first,
            last=args.last,
        )
    )


def command_scene_video_mode(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.set_video_mode(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene_id,
            mode=args.mode,
        )
    )


def command_scene_continuity(args):
    store = authoring.open_store(args.workspace)
    _print(
        authoring.set_continuity_strategy(
            store,
            args.project,
            args.expected_revision,
            scene_id=args.scene_id,
            strategy=args.strategy,
        )
    )


def command_question_answer(args):
    # Ticket 12 repair, condition 7: no more "try JSON, then fall back to
    # the raw string" -- that turned a free_text answer of "2026" into
    # the integer 2026 (valid JSON) instead of the string "2026". The
    # question's own `kind`/`options` (fetched by `question_id` alone --
    # this command takes no `--project`) decide unambiguously what
    # `--answer-text`/`--answer-option-number`/`--answer-option-id` mean;
    # see `resolve_cli_answer`. Ticket 13 (spec §6): the position and the
    # literal-id flags are separate and never guess at each other's job
    # (see `--answer-option-number`/`--answer-option-id` below).
    questions = authoring.open_questions(args.workspace)
    question = questions.get(args.question_id)
    if question is None:
        raise QuestionNotFound(args.question_id)
    answer_value = resolve_cli_answer(
        question,
        answer_text=args.answer_text,
        answer_option_number=args.answer_option_number,
        answer_option_id=args.answer_option_id,
    )
    _print(
        authoring.answer_question(
            questions, args.question_id, args.revision, answer_value, args.channel
        )
    )


def command_question_list(args):
    questions = authoring.open_questions(args.workspace)
    _print(authoring.list_questions(questions, args.project))


def command_assembly_set(args):
    store = authoring.open_store(args.workspace)
    assets = authoring.open_assets(args.workspace)
    _print(
        authoring.set_assembly(
            store,
            assets,
            args.project,
            args.expected_revision,
            asset_id=args.asset_id,
            caption=args.caption,
        )
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_cmd = subparsers.add_parser("serve", help="start the loopback studio server")
    serve_cmd.add_argument("workspace", type=Path)
    serve_cmd.add_argument("--port", type=int, default=0)
    serve_cmd.set_defaults(handler=command_serve)

    grant_cmd = subparsers.add_parser("grant", help="issue a one-use chat-approved grant")
    grant_cmd.add_argument("workspace", type=Path)
    grant_cmd.add_argument("project")
    grant_cmd.add_argument(
        "action_class", choices=sorted(GRANT_REQUIRED_ACTIONS | {"generation"})
    )
    grant_cmd.add_argument("--expires-at", required=True)
    grant_cmd.set_defaults(handler=command_grant)

    claim_cmd = subparsers.add_parser("claim", help="claim the oldest queued chat-only action")
    claim_cmd.add_argument("workspace", type=Path)
    claim_cmd.add_argument("--worker", required=True, dest="worker")
    claim_cmd.add_argument("--profile", type=Path, default=None)
    claim_cmd.set_defaults(handler=command_claim)

    finish_cmd = subparsers.add_parser("finish", help="record a claimed action's terminal outcome")
    finish_cmd.add_argument("workspace", type=Path)
    finish_cmd.add_argument("action_id")
    finish_cmd.add_argument(
        "--status", required=True, choices=sorted(TERMINAL_STATUSES)
    )
    finish_cmd.add_argument("--public-result", required=True, type=Path, dest="public_result")
    finish_cmd.add_argument("--external-id", default=None, dest="external_id")
    finish_cmd.set_defaults(handler=command_finish)

    recover_cmd = subparsers.add_parser("recover", help="resolve in-flight actions after a restart")
    recover_cmd.add_argument("workspace", type=Path)
    recover_cmd.set_defaults(handler=command_recover)

    _add_authoring_subcommands(subparsers)
    _add_mode_subcommands(subparsers)
    _add_decision_subcommands(subparsers)
    add_workspace_subcommands(subparsers)

    return parser


def _add_authoring_subcommands(subparsers) -> None:
    """Ticket 12: `project`/`script`/`scenes`/`prompt`/`asset`/`result`/
    `reference`/`milestone`/`question`/`assembly` — chat's only way
    to write canonical project state and register local media, through
    `studio/authoring.py`. Each is a two-word command (`project create`,
    `script add-version`, ...); the verb is its own nested subparser,
    matching the ticket's own wording rather than a flat
    `project-create`-style name.

    Ticket 12 repair, condition 10: this used to be one ~220-line function
    registering all eleven command groups inline. Each group is now its
    own small `_add_*_subcommands(subparsers)` function below, and this
    is only the fixed order they run in.
    """

    _add_project_subcommands(subparsers)
    _add_script_subcommands(subparsers)
    _add_scenario_subcommands(subparsers)
    _add_scene_subcommands(subparsers)
    _add_scenes_subcommands(subparsers)
    _add_prompt_subcommands(subparsers)
    _add_asset_subcommands(subparsers)
    _add_result_subcommands(subparsers)
    _add_reference_subcommands(subparsers)
    _add_milestone_subcommands(subparsers)
    _add_question_subcommands(subparsers)
    _add_assembly_subcommands(subparsers)


def _add_mode_subcommands(subparsers) -> None:
    mode_cmd = subparsers.add_parser("mode", help="change the project interaction mode")
    mode_sub = mode_cmd.add_subparsers(dest="subcommand", required=True)
    mode_set_cmd = mode_sub.add_parser("set", help="set guided or autopilot mode")
    mode_set_cmd.add_argument("workspace", type=Path)
    mode_set_cmd.add_argument("project")
    mode_set_cmd.add_argument("--mode", required=True, choices=("guided", "autopilot"))
    mode_set_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    mode_set_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    mode_set_cmd.set_defaults(handler=command_mode_set)


def _add_decision_subcommands(subparsers) -> None:
    decide_cmd = subparsers.add_parser("decide", help="apply a decision to the current stage")
    decide_cmd.add_argument("workspace", type=Path)
    decide_cmd.add_argument("project")
    decide_cmd.add_argument("decision", choices=("approve", "reject", "hide", "unhide", "retire", "restore"))
    decide_cmd.add_argument("--target", required=True)
    decide_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    decide_cmd.add_argument("--comment", default=None)
    decide_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    decide_cmd.set_defaults(handler=command_decide)

    stage_cmd = subparsers.add_parser("stage", help="approve or rework the current stage")
    stage_cmd.add_argument("decision", choices=("approve", "reject"))
    stage_cmd.add_argument("workspace", type=Path)
    stage_cmd.add_argument("project")
    stage_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    stage_cmd.add_argument("--comment", default=None)
    stage_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    stage_cmd.set_defaults(handler=command_stage)

    reorder_cmd = subparsers.add_parser("reorder", help="reorder one complete supported collection")
    reorder_cmd.add_argument("workspace", type=Path)
    reorder_cmd.add_argument("project")
    reorder_cmd.add_argument("collection", choices=sorted(REORDERABLE_COLLECTIONS))
    reorder_cmd.add_argument("--order", required=True, help="comma-separated complete order")
    reorder_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    reorder_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    reorder_cmd.set_defaults(handler=command_reorder)


def _add_project_subcommands(subparsers) -> None:
    project_cmd = subparsers.add_parser("project", help="create a project")
    project_sub = project_cmd.add_subparsers(dest="subcommand", required=True)
    project_create_cmd = project_sub.add_parser("create", help="create a new project at revision 0")
    project_create_cmd.add_argument("workspace", type=Path)
    project_create_cmd.add_argument("project_id")
    project_create_cmd.add_argument("--title", required=True)
    # No `choices=` on `--type`/`--mode`/`--kind`/`--role`/`status` below:
    # ticket 12 requires a domain-vocabulary violation (an unknown role,
    # motion data on a photo project, ...) to exit 3 through
    # `authoring.AuthoringError`/`AssetValidationError`, not argparse's own
    # exit 2 for a bad `choices=` value — so the value is passed through
    # unchecked here and rejected by the same domain validation
    # `studio/authoring.py` already has for every one of these fields.
    project_create_cmd.add_argument(
        "--type", required=True, metavar="{photo,video,mixed}"
    )
    project_create_cmd.add_argument(
        "--mode", default="guided", metavar="{guided,autopilot}"
    )
    project_create_cmd.set_defaults(handler=command_project_create)

    project_set_mode_cmd = project_sub.add_parser(
        "set-mode", help="change a project's guided/autopilot mode"
    )
    project_set_mode_cmd.add_argument("workspace", type=Path)
    project_set_mode_cmd.add_argument("project")
    project_set_mode_cmd.add_argument("--mode", required=True, metavar="{guided,autopilot}")
    project_set_mode_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    project_set_mode_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    project_set_mode_cmd.set_defaults(handler=command_project_set_mode)
    project_set_gen_mode_cmd = project_sub.add_parser(
        "set-gen-mode", help="set a video project's per-scene or one-shot generation mode"
    )
    project_set_gen_mode_cmd.add_argument("workspace", type=Path)
    project_set_gen_mode_cmd.add_argument("project")
    project_set_gen_mode_cmd.add_argument("--mode", required=True, metavar="{per_scene,one_shot}")
    project_set_gen_mode_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    project_set_gen_mode_cmd.set_defaults(handler=command_project_set_gen_mode)

def _add_script_subcommands(subparsers) -> None:
    script_cmd = subparsers.add_parser("script", help="append a scenario version")
    script_sub = script_cmd.add_subparsers(dest="subcommand", required=True)
    script_add_version_cmd = script_sub.add_parser(
        "add-version", help="append and activate a new script version"
    )
    script_add_version_cmd.add_argument("workspace", type=Path)
    script_add_version_cmd.add_argument("project")
    script_add_version_cmd.add_argument("--text", required=True)
    script_add_version_cmd.add_argument("--reason", required=True)
    script_add_version_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    script_add_version_cmd.set_defaults(handler=command_script_add_version)
    script_edit_cmd = script_sub.add_parser("edit", help="edit the scenario as a human decision")
    script_edit_cmd.add_argument("workspace", type=Path)
    script_edit_cmd.add_argument("project")
    script_edit_cmd.add_argument("--text", required=True)
    script_edit_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    script_edit_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    script_edit_cmd.set_defaults(handler=command_script_edit)

def _add_scenario_subcommands(subparsers) -> None:
    """Ticket 15 (G05): chat's own door onto the reopen transition --
    `scenario reopen`, the CLI twin of the dashboard's `reopen-scenario`
    decision (`studio.decision_stages.build_reopen_mutation`, shared
    unchanged between the two doors)."""

    scenario_cmd = subparsers.add_parser(
        "scenario", help="reopen an approved scenario for editing"
    )
    scenario_sub = scenario_cmd.add_subparsers(dest="subcommand", required=True)
    scenario_reopen_cmd = scenario_sub.add_parser(
        "reopen",
        help="reset the scenario and every later stage to draft",
    )
    scenario_reopen_cmd.add_argument("workspace", type=Path)
    scenario_reopen_cmd.add_argument("project")
    scenario_reopen_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scenario_reopen_cmd.add_argument(
        "--comment", default=None, help="optional comment for the reopen"
    )
    scenario_reopen_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    scenario_reopen_cmd.set_defaults(handler=command_scenario_reopen)

def _add_scene_subcommands(subparsers) -> None:
    """Ticket 15 repair (поправка оркестратора 1): `scene edit`, chat's
    own door onto a scene description's `edit` -- distinct from the plural
    `scenes` group below (`scenes set`, the initial split of an approved
    scenario into scenes)."""

    scene_cmd = subparsers.add_parser("scene", help="edit one scene's description")
    scene_sub = scene_cmd.add_subparsers(dest="subcommand", required=True)
    scene_edit_cmd = scene_sub.add_parser(
        "edit", help="append and activate a new version of one scene's description"
    )
    scene_edit_cmd.add_argument("workspace", type=Path)
    scene_edit_cmd.add_argument("project")
    scene_edit_cmd.add_argument("scene_id")
    scene_edit_cmd.add_argument("--field", choices=("title", "text", "duration_ms"))
    scene_edit_cmd.add_argument("--value")
    scene_edit_cmd.add_argument("--text")
    scene_edit_cmd.add_argument("--reason")
    scene_edit_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scene_edit_cmd.set_defaults(handler=command_scene_edit)
    scene_add_cmd = scene_sub.add_parser("add", help="append one default scene")
    scene_add_cmd.add_argument("workspace", type=Path)
    scene_add_cmd.add_argument("project")
    scene_add_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scene_add_cmd.set_defaults(handler=command_scene_add)
    scene_plan_cmd = scene_sub.add_parser("plan", help="set first and last frame positions")
    scene_plan_cmd.add_argument("workspace", type=Path)
    scene_plan_cmd.add_argument("project")
    scene_plan_cmd.add_argument("--scene", required=True, dest="scene_id")
    first = scene_plan_cmd.add_mutually_exclusive_group()
    first.add_argument("--first", action="store_true", dest="first", default=None)
    first.add_argument("--no-first", action="store_false", dest="first")
    last = scene_plan_cmd.add_mutually_exclusive_group()
    last.add_argument("--last", action="store_true", dest="last", default=None)
    last.add_argument("--no-last", action="store_false", dest="last")
    scene_plan_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scene_plan_cmd.set_defaults(handler=command_scene_plan)
    scene_video_mode_cmd = scene_sub.add_parser("video-mode", help="set one scene's motion mode")
    scene_video_mode_cmd.add_argument("workspace", type=Path)
    scene_video_mode_cmd.add_argument("project")
    scene_video_mode_cmd.add_argument("--scene", required=True, dest="scene_id")
    scene_video_mode_cmd.add_argument("--mode", required=True, metavar="{first,firstlast,references}")
    scene_video_mode_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scene_video_mode_cmd.set_defaults(handler=command_scene_video_mode)
    scene_continuity_cmd = scene_sub.add_parser(
        "continuity", help="record the transition strategy for a later per-scene clip"
    )
    scene_continuity_cmd.add_argument("workspace", type=Path)
    scene_continuity_cmd.add_argument("project")
    scene_continuity_cmd.add_argument("--scene", required=True, dest="scene_id")
    scene_continuity_cmd.add_argument(
        "--strategy",
        required=True,
        choices=("previous_video", "previous_last_frame", "independent"),
    )
    scene_continuity_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scene_continuity_cmd.set_defaults(handler=command_scene_continuity)

def _add_scenes_subcommands(subparsers) -> None:
    scenes_cmd = subparsers.add_parser("scenes", help="author the stage-one storyboard")
    scenes_sub = scenes_cmd.add_subparsers(dest="subcommand", required=True)
    scenes_set_cmd = scenes_sub.add_parser(
        "set", help="replace state.scenes at the scenario stage"
    )
    scenes_set_cmd.add_argument("workspace", type=Path)
    scenes_set_cmd.add_argument("project")
    scenes_set_cmd.add_argument(
        "--file",
        required=True,
        type=Path,
        help="JSON array of {scene_id, title?, text, duration_ms?}",
    )
    scenes_set_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    scenes_set_cmd.set_defaults(handler=command_scenes_set)
    scenes_reorder_cmd = scenes_sub.add_parser(
        "reorder", help="set the complete scene order at the scenario stage"
    )
    scenes_reorder_cmd.add_argument("workspace", type=Path)
    scenes_reorder_cmd.add_argument("project")
    scenes_reorder_cmd.add_argument("--order", nargs="+", required=True)
    scenes_reorder_cmd.add_argument(
        "--expected-revision", required=True, type=int, dest="expected_revision"
    )
    scenes_reorder_cmd.set_defaults(handler=command_scenes_reorder)

def _add_prompt_subcommands(subparsers) -> None:
    prompt_cmd = subparsers.add_parser("prompt", help="version an image/motion prompt")
    prompt_sub = prompt_cmd.add_subparsers(dest="subcommand", required=True)
    prompt_add_version_cmd = prompt_sub.add_parser(
        "add-version", help="create or version an image/motion prompt for one scene"
    )
    prompt_add_version_cmd.add_argument("workspace", type=Path)
    prompt_add_version_cmd.add_argument("project")
    prompt_add_version_cmd.add_argument("--scene", dest="scene")
    prompt_add_version_cmd.add_argument("--kind", metavar="{image,motion}")
    prompt_add_version_cmd.add_argument("--target", help="generation position id; alternative to --scene/--kind")
    prompt_add_version_cmd.add_argument("--text", required=True)
    prompt_add_version_cmd.add_argument("--reason", required=True)
    prompt_add_version_cmd.add_argument("--prompt-id", default=None, dest="prompt_id")
    prompt_add_version_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    prompt_add_version_cmd.set_defaults(handler=command_prompt_add_version)
    prompt_edit_cmd = prompt_sub.add_parser("edit", help="edit a current prompt as a human decision")
    prompt_edit_cmd.add_argument("workspace", type=Path)
    prompt_edit_cmd.add_argument("project")
    prompt_edit_cmd.add_argument("--target", required=True)
    prompt_edit_cmd.add_argument("--text", required=True)
    prompt_edit_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    prompt_edit_cmd.add_argument("--operation-id", default=None, dest="operation_id")
    prompt_edit_cmd.set_defaults(handler=command_prompt_edit)

def _add_asset_subcommands(subparsers) -> None:
    asset_cmd = subparsers.add_parser("asset", help="register a local media file")
    asset_sub = asset_cmd.add_subparsers(dest="subcommand", required=True)
    asset_register_cmd = asset_sub.add_parser(
        "register", help="validate and register a file below workspace/media"
    )
    asset_register_cmd.add_argument("workspace", type=Path)
    # Ticket 12 repair, condition 10: `AssetIndex`'s allowed root is the
    # whole workspace (`root=workspace`, `allowed_roots=(media_root,)` --
    # see `authoring_support.open_assets`), so `--path` is resolved
    # relative to the *workspace*, not to `workspace/media` -- the caller
    # must spell the `media/` prefix out (`--path media/<file>`), which
    # this help text used to contradict.
    asset_register_cmd.add_argument(
        "--path",
        required=True,
        help="path relative to the workspace root (e.g. media/<file>); must resolve inside workspace/media",
    )
    asset_register_cmd.add_argument(
        "--role", required=True, metavar="{" + ",".join(sorted(ASSET_ROLES)) + "}"
    )
    asset_register_cmd.set_defaults(handler=command_asset_register)

def _add_result_subcommands(subparsers) -> None:
    result_cmd = subparsers.add_parser("result", help="link a registered asset to a scene result")
    result_sub = result_cmd.add_subparsers(dest="subcommand", required=True)
    result_add_version_cmd = result_sub.add_parser(
        "add-version", help="create or version an image/video result for one scene"
    )
    result_add_version_cmd.add_argument("workspace", type=Path)
    result_add_version_cmd.add_argument("project")
    result_add_version_cmd.add_argument("--scene", dest="scene")
    result_add_version_cmd.add_argument("--kind", metavar="{image,video}")
    result_add_version_cmd.add_argument("--target", help="generation position id; alternative to --scene/--kind")
    result_add_version_cmd.add_argument("--asset-id", required=True, dest="asset_id")
    result_add_version_cmd.add_argument("--result-id", default=None, dest="result_id")
    result_add_version_cmd.add_argument("--caption", default=None)
    result_add_version_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    result_add_version_cmd.set_defaults(handler=command_result_add_version)

def _add_reference_subcommands(subparsers) -> None:
    reference_cmd = subparsers.add_parser("reference", help="add a character/object/style reference")
    reference_sub = reference_cmd.add_subparsers(dest="subcommand", required=True)
    reference_add_cmd = reference_sub.add_parser("add", help="create a tagged project reference")
    reference_add_cmd.add_argument("workspace", type=Path)
    reference_add_cmd.add_argument("project")
    reference_add_cmd.add_argument("--kind", default=None, choices=("character", "product", "location", "style", "other", "video"),
                                   help="required unless --from-library supplies it")
    reference_add_cmd.add_argument("--name", default=None)
    reference_add_cmd.add_argument("--asset-id", default=None, dest="asset_id")
    reference_add_cmd.add_argument("--from-library", default=None, dest="from_library",
                                   help="library_id: copy that library file into media/ and use it")
    reference_add_cmd.add_argument("--source", choices=("upload", "generate"), default="upload")
    reference_add_cmd.add_argument(
        "--usage",
        choices=("reference", "motion", "continue", "edit"),
        default="reference",
        help="video-reference purpose (ignored for image references)",
    )
    inclusion = reference_add_cmd.add_mutually_exclusive_group()
    inclusion.add_argument("--scene", default=None)
    inclusion.add_argument("--all-scenes", action="store_true", dest="all_scenes")
    reference_add_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    reference_add_cmd.set_defaults(handler=command_reference_add)

    reference_attach_cmd = reference_sub.add_parser("attach", help="attach an image, video or enabled voice file")
    reference_attach_cmd.add_argument("workspace", type=Path)
    reference_attach_cmd.add_argument("project")
    reference_attach_cmd.add_argument("--reference", required=True)
    reference_attach_cmd.add_argument("--asset-id", default=None, dest="asset_id")
    reference_attach_cmd.add_argument("--from-library", default=None, dest="from_library",
                                      help="library_id (e.g. a voice entry) instead of --asset-id")
    reference_attach_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    reference_attach_cmd.set_defaults(handler=command_reference_attach)

    reference_edit_cmd = reference_sub.add_parser("edit", help="edit a reference name, source or voice flag")
    reference_edit_cmd.add_argument("workspace", type=Path)
    reference_edit_cmd.add_argument("project")
    reference_edit_cmd.add_argument("--reference", required=True)
    reference_edit_cmd.add_argument("--field", required=True, choices=("name", "source", "usage", "voice_enabled"))
    reference_edit_cmd.add_argument("--value", required=True)
    reference_edit_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    reference_edit_cmd.set_defaults(handler=command_reference_edit)

    reference_toggle_cmd = reference_sub.add_parser("toggle", help="include or exclude a project reference in one scene")
    reference_toggle_cmd.add_argument("workspace", type=Path)
    reference_toggle_cmd.add_argument("project")
    reference_toggle_cmd.add_argument("--scene", required=True)
    reference_toggle_cmd.add_argument("--reference", required=True)
    toggle = reference_toggle_cmd.add_mutually_exclusive_group(required=True)
    toggle.add_argument("--on", action="store_true", dest="on")
    toggle.add_argument("--off", action="store_false", dest="on")
    reference_toggle_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    reference_toggle_cmd.set_defaults(handler=command_reference_toggle)

def _add_milestone_subcommands(subparsers) -> None:
    milestone_cmd = subparsers.add_parser("milestone", help="mark the current stage ready or blocked")
    milestone_sub = milestone_cmd.add_subparsers(dest="subcommand", required=True)
    milestone_set_cmd = milestone_sub.add_parser(
        "set", help="set the current stage's milestone status (never approved)"
    )
    milestone_set_cmd.add_argument("workspace", type=Path)
    milestone_set_cmd.add_argument("project")
    milestone_set_cmd.add_argument("stage")
    milestone_set_cmd.add_argument("status", metavar="{ready,blocked}")
    milestone_set_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    milestone_set_cmd.set_defaults(handler=command_milestone_set)

def _add_question_subcommands(subparsers) -> None:
    """`question create`/`answer`/`list` share one `question` parser and
    its `question_sub` subparsers group; each subcommand's own arguments
    are registered by a dedicated `_add_question_*_subcommand` function
    below (ticket 12 repair, condition 10) so no one function has to
    hold all three.
    """

    question_cmd = subparsers.add_parser("question", help="create a pending question")
    question_sub = question_cmd.add_subparsers(dest="subcommand", required=True)
    _add_question_create_subcommand(question_sub)
    _add_question_answer_subcommand(question_sub)
    _add_question_list_subcommand(question_sub)


def _add_question_create_subcommand(question_sub) -> None:
    question_create_cmd = question_sub.add_parser(
        "create", help="insert one pending question into the durable QuestionStore"
    )
    question_create_cmd.add_argument("workspace", type=Path)
    question_create_cmd.add_argument("project")
    question_create_cmd.add_argument("--question-id", required=True, dest="question_id")
    question_create_cmd.add_argument("--text", required=True)
    question_create_cmd.add_argument(
        "--kind", required=True, metavar="{" + ",".join(sorted(QUESTION_KINDS)) + "}"
    )
    question_create_cmd.add_argument(
        "--option",
        nargs=3,
        action="append",
        default=[],
        metavar=("ID", "LABEL", "DESCRIPTION"),
        help="repeatable; required for kind single/multi",
    )
    question_create_cmd.add_argument("--allow-custom", action="store_true", dest="allow_custom")
    question_create_cmd.add_argument("--required", action="store_true")
    question_create_cmd.add_argument("--expires-at", default=None, dest="expires_at")
    question_create_cmd.add_argument(
        "--validation",
        default=None,
        help="JSON object; see QuestionStore validation keys (min_length, pattern, ...)",
    )
    question_create_cmd.set_defaults(handler=command_question_create)


def _add_question_answer_subcommand(question_sub) -> None:
    question_answer_cmd = question_sub.add_parser(
        "answer", help="answer a pending question from chat or Telegram"
    )
    question_answer_cmd.add_argument("workspace", type=Path)
    question_answer_cmd.add_argument("question_id")
    question_answer_cmd.add_argument("--revision", required=True, type=int)
    # Ticket 12 repair, condition 7: unambiguous flags instead of one
    # `--answer` that guessed at the value's shape by trying to JSON-parse
    # it first. `--answer-text` is always taken verbatim (never number-
    # parsed) -- the free_text/confirm answer, or a choice question's own
    # custom text when it allows one.
    #
    # Ticket 13 (spec §6's numbered fallback, "ответ номером 1/2/3";
    # replaces ticket 12's own single, ambiguous `--answer-option`):
    # `--answer-option-number` always names a choice question's option by
    # its 1-based position; `--answer-option-id` always names it by its
    # own id, literally, never re-interpreted as a position even when it
    # looks like one. Both are repeatable (for `multi`) and may be
    # combined; `resolve_cli_answer` decides which flag(s) a given
    # question's `kind` actually accepts.
    question_answer_cmd.add_argument(
        "--answer-text",
        default=None,
        dest="answer_text",
        help="verbatim text answer, or yes/no/да/нет for a confirm question; never parsed as a number",
    )
    question_answer_cmd.add_argument(
        "--answer-option-number",
        action="append",
        default=[],
        dest="answer_option_number",
        metavar="N",
        help="repeatable; an option's 1-based position (single/multi questions only)",
    )
    question_answer_cmd.add_argument(
        "--answer-option-id",
        action="append",
        default=[],
        dest="answer_option_id",
        metavar="ID",
        help="repeatable; an option's own id, taken literally (single/multi questions only)",
    )
    question_answer_cmd.add_argument("--channel", required=True, metavar="{chat,telegram}")
    question_answer_cmd.set_defaults(handler=command_question_answer)


def _add_question_list_subcommand(question_sub) -> None:
    question_list_cmd = question_sub.add_parser(
        "list", help="list every question for a project, pending or answered"
    )
    question_list_cmd.add_argument("workspace", type=Path)
    question_list_cmd.add_argument("project")
    question_list_cmd.set_defaults(handler=command_question_list)


def _add_assembly_subcommands(subparsers) -> None:
    assembly_cmd = subparsers.add_parser("assembly", help="write the final assembly result")
    assembly_sub = assembly_cmd.add_subparsers(dest="subcommand", required=True)
    assembly_set_cmd = assembly_sub.add_parser(
        "set", help="link the registered final-deliverable asset"
    )
    assembly_set_cmd.add_argument("workspace", type=Path)
    assembly_set_cmd.add_argument("project")
    assembly_set_cmd.add_argument("--asset-id", required=True, dest="asset_id")
    assembly_set_cmd.add_argument("--caption", default=None)
    assembly_set_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    assembly_set_cmd.set_defaults(handler=command_assembly_set)


#: Amendment 2026-09-16 (ticket 09 repair, condition 12): argparse's own
#: `parser.error()` always exits 2 — the same code it uses for a malformed
#: command line (an unknown flag, a missing positional). A domain-level
#: refusal caught below (an unresolved revision, a rejected public_result
#: text, ...) is not a usage mistake: the arguments were fine and the
#: operation was refused for a substantive reason, after the action's
#: state was already inspected. Giving it its own exit code lets a caller
#: — a wrapper script, `recover-after-fix`, a test — tell the two apart
#: without parsing stderr text.
DOMAIN_ERROR_EXIT_CODE = 3


def main():
    ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (
        ValueError,
        OSError,
        json.JSONDecodeError,
        LedgerError,
        StoreError,
        AdapterError,
        WorkspaceError,
        AuthoringError,
        # Repair, 2026-09-17 (ticket 12 repair, blocking condition 2):
        # `AssetNotFound`/`QuestionNotFound`/`QuestionExpired`/
        # `LateAnswerConflict` are `RuntimeError` subclasses, not
        # `ValueError` -- unlike `AssetValidationError`/
        # `QuestionValidationError`, which already were. Without their
        # base classes listed here, e.g. an unknown `--asset-id` in
        # `result add-version`/`reference add`, or answering an unknown/
        # expired/already-answered question, escaped this `except`
        # entirely: a bare Python traceback (absolute paths and all) on
        # stderr and exit code 1, instead of the ticket's own "код 3, без
        # traceback и абсолютных путей" contract every domain error here
        # must satisfy.
        AssetError,
        QuestionError,
    ) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(DOMAIN_ERROR_EXIT_CODE)


if __name__ == "__main__":
    main()
