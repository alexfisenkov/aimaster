# Autopilot

This file is the only canon for `project.mode = autopilot`. Where another
reference says "ask", "offer a choice" or "wait for the user", that applies to
`guided`. In `autopilot`, follow this file. `guided` is unchanged.

`<skill>` below is the absolute path of the installed skill folder (the folder
that contains `SKILL.md`); from that folder the same scripts run as
`python3 scripts/…`.

## The one approval point

Autopilot has exactly one point where the user decides: **approval of the
idea/brief**. The output type (`photo`, `video`, `mixed`) and the mode are set
when the project is created, before the brief. Before approval you may ask
intake questions. Show one short brief that already contains your decisions:
duration, `one-shot` or `per-scene`, aspect ratio, audience, named references
and, if the idea names one, the model. The user's explicit "yes" to that brief
(or a request that already says "делай" / "go" with a complete idea) is the
approval. Record it in the question lifecycle.

After that: **zero questions until the finished video.** Do not ask, do not
offer choices, do not wait for confirmation, do not stop "for review". Every
choice that `guided` would ask is made by you, recorded, and reported at the
end. A question after the approval point is a defect. An available skill update
found by the [update check](update-check.md) is mentioned only in the final
report.

## Standing authorization: spending and uploads

When autopilot is switched on (`project create --mode autopilot`,
`mode set --mode autopilot` or `project set-mode --mode autopilot`), the CLI
returns a `notice`. Show it to the user once, verbatim: «Автопилот тратит
кредиты без подтверждения». Do not repeat it and do not turn it into a question.

Autopilot mode is the owner's standing authorization, for this project, to
**spend** on paid actions (no limit) and to **upload** the project's own assets
(references, frames, voices, previous clips) to the selected verified route
when a generation needs them. Nothing else is authorized: no account changes,
no publishing, no uploads of files outside the project or library.

- Do not run `grant` and do not ask for spending approval. Queue each paid
  action with
  `creator_studio.py action enqueue <ws> <project> --type generate|vary|regenerate --target <T> --expected-revision N [--payload JSON] [--idempotency-key K]`.
  In autopilot it returns `status: queued, issued_by: autopilot` and writes an
  `autopilot-grant` history entry. That entry raises the revision by one: take
  the fresh revision for the next `--expected-revision`. Then `claim`, execute,
  collect and `finish` as in [Creator Studio](creator-studio.md).
- If **enqueue** returns `needs_chat`, the project is not in autopilot: re-read
  `project.mode`; do not issue a grant on your own. This is different from a
  `needs_chat` you write with **finish** — that one is a blocker (see Allowed
  stops).
- Everything else still applies: stage preflight in the
  [completion loop](completion-loop.md), [reference binding](reference-bindings.md)
  and its validator, collection and read-back. A failed check is fixed and
  re-run by you, not turned into a question.
- A defect found in review authorizes a `vary` or `regenerate` in autopilot;
  record why in the operation record and the final report.

## Order after approval, stage by stage

Before planning, run the **tool check** (below) and the **library** step:
`creator_studio.py library match <ws> --text "<idea>"`. Every returned
character, location, product or style becomes a project reference with
`reference add <ws> <project> --from-library <library_id> --expected-revision N`
(`source=upload`). A voice (returned with its character,
`matched_via: "voice_of"`) is not a reference of its own: enable `voice_enabled`
on the character reference, then
`reference attach … --reference IMG_NN --from-library <voice_id>`. Do not
generate what the library already has; every other needed reference is added
with `--source generate`.

Guide rule used below: run the exact `guide_registry.py match` from
[writing guides](writing-guides.md), take the first entry in `matches`, else no
guide; write the decision into `--reason` (for example `autopilot: guide <id>`
or `autopilot: no matching guide`).

Model rule used below: use the model named in the idea when the verified route
exposes it and it fits; otherwise apply "Выбрать за меня" from
[model selection](model-selection.md), weighing the exact task, the number of
image references and whether video references are used
([video inputs](video-inputs.md)). Record the reason. Re-select for each new
task (image, motion, audio).

1. **`scenario`.** Scenario guide → `script add-version` → `scenes set` (with
   durations for video) → `stage approve --comment "autopilot"`.
2. **`image_plan`.**
   - `project set-gen-mode` (`one_shot` / `per_scene` from the approved brief).
   - Choose the image model (model rule), then the prompt guide for it.
   - `scene plan` for every scene: plan first/last frames the motion mode will
     need. For `per_scene`, plan a first frame on every scene after the first
     whose likely continuity is `previous_last_frame`; planning it costs little
     and keeps that option open at `motion`.
   - `prompt add-version` for generated references, planned frames and scene
     images; motion prompts may also be prepared here (motion model chosen by
     the model rule).
   - `stage approve`.
3. **`image_results`.** For every generated reference and planned frame:
   `action enqueue` → claim → execute → collect (`result add-version`) →
   finish. Review, pick with `decide approve --target <version> --comment
   "autopilot: <reason>"`, vary/regenerate on a clear defect. Then
   `stage approve`.
4. **`motion`.** For each scene in order:
   - for `per_scene` scenes after the first, `scene continuity` with the
     strategy recommended in [continuity choice](continuity-choice.md). If that
     strategy is not available now (for example `previous_last_frame` without
     a first frame planned on `image_plan`, or the model rejects video
     continuation), take the best available one (`previous_video` or
     `independent`), record the reason, and **do not** go back to an earlier
     stage. For `previous_video`, first copy the accepted previous clip to a new
     media file, register it as `video_reference` and add it scene-locally with
     `usage=continue`, as the preconditions there require;
   - `scene video-mode` (`first`, `firstlast` or `references`) matching the
     accepted frames and the model schema;
   - enqueue → claim → execute → collect → finish → review → `decide approve`.
   Then `stage approve`.
5. **`audio`.** A layer is required only when its result group has an entry.
   If the brief needs no separate sound, create nothing and `stage approve`
   the empty stage. Otherwise, per layer: model rule, guide rule, prompt,
   enqueue → … → `decide approve`, then `stage approve`.
6. **`assembly`.** Produce the assembly (`assembly set`), review it, then the
   final report.

Photo projects skip `motion` and `audio`. Each command belongs to the stage
listed in [Creator Studio](creator-studio.md) and the completion-loop stage
gate: never generate for a future stage.

## Tool check before any "no"

Before you treat a route as unavailable, skip it, or say that an MCP, provider
or tool does not exist, do all of this. A provider named in the idea is never
skipped silently.

1. **Own tool list.** Search the tools exposed in this session for the server
   or provider name. In Claude Code use `ToolSearch` (it waits for servers that
   are still connecting). In runtimes without it (Codex, Gemini CLI), re-read
   the tool list after a short pause: servers may still be connecting.
2. **Configuration.** Run `python3 <skill>/scripts/detect_tools.py --json`. It
   reads Claude Code, Codex, Gemini CLI, Cursor and aimaster preference files
   offline and prints only names, transport and host. Hosted connectors are not
   in those files, so an empty result proves nothing on its own.
3. **Free probe**, if steps 1–2 found the tool or server: one read-only call on
   that route (balance, model list, catalog). Generation, upload and paid tools
   are not probes.

If the server is configured but not exposed in this session, say exactly that.
In `guided`, offer reconnecting or another route. In `autopilot`, take the next
verified route of the same modality and continue; mention it in the report.

## Allowed stops

A binding, collection or stale-revision blocker (a `needs_chat` you would write
with `finish`, a validator failure, a revision conflict) is not a stop by
itself: fix the cause, re-read the state, queue the action again. If it cannot
be fixed, it becomes a stop.

Stop only when continuing is physically impossible:

- no route at all for the required modality after the tool check;
- the provider refused on payment or balance;
- an `outcome_unknown` that the provider's own history cannot resolve (never
  retry it blindly);
- a binding, collection or revision blocker that you could not fix.

Then write a report, not a question: what is done (with dashboard link), what
blocked, which routes were checked, and the exact command or action that
resumes the work. Everything else — an unclear detail, several good models, a
mediocre variant — is decided by you.

## Final report

At the end, list the decisions you made: guides used or skipped, generation
method, frame plan, continuity strategies (and any fallback with its reason),
models and why, library items reused, uploads, regenerations and why, every
provider switch, and an available skill update if one was found. Keep
technical, visual and self-approved checks separate.
