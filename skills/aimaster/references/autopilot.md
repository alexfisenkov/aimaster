# Autopilot

This file is the only canon for `project.mode = autopilot`. Where another
reference says "ask", "offer a choice" or "wait for the user", that applies to
`guided`. In `autopilot`, follow this file. `guided` is unchanged.

## The one approval point

Autopilot has exactly one point where the user decides: **approval of the
idea/brief**. Before it you may ask intake questions. Show one short brief
that already contains your decisions: output type, duration, `one-shot` or
`per-scene`, aspect ratio, audience, named references and, if the idea names
one, the model. The user's explicit "yes" to that brief (or a request that
already says "делай" / "go" with a complete idea) is the approval. Record it in
the question lifecycle.

After that: **zero questions until the finished video.** Do not ask, do not
offer choices, do not wait for confirmation, do not stop "for review". Every
choice that `guided` would ask is made by you, recorded, and reported at the
end. A question after the approval point is a defect.

## Spending

When autopilot is switched on (`project create --mode autopilot`,
`mode set --mode autopilot` or `project set-mode --mode autopilot`), the CLI
returns a `notice`. Show it to the user
once, verbatim: «Автопилот тратит кредиты без подтверждения». Do not repeat it
and do not turn it into a question.

- Do not run `grant` and do not ask for spending approval. Queue each paid
  action with
  `creator_studio.py action enqueue <ws> <project> --type generate|vary|regenerate --target <T> --expected-revision N [--payload JSON] [--idempotency-key K]`.
  In autopilot it returns `status: queued, issued_by: autopilot` and writes an
  `autopilot-grant` history entry. That entry raises the revision by one: take
  the fresh revision for the next `--expected-revision`. Then `claim`, execute,
  collect and `finish` as in [Creator Studio](creator-studio.md).
- If enqueue returns `needs_chat`, the project is not in autopilot: re-read
  `project.mode`; do not issue a grant on your own.
- Autopilot mode is the owner's standing authorization for spending in this
  project. There is no limit.
- Everything else still applies: stage preflight in the
  [completion loop](completion-loop.md), [reference binding](reference-bindings.md)
  and its validator, collection and read-back. A failed check is fixed and
  re-run by you, not turned into a question.

## Order after approval

1. **Tool check** (below). Know every route before planning.
2. **Library.** Run `creator_studio.py library match <ws> --text "<idea>"`.
   Every returned character, location, product or style becomes a project
   reference with
   `reference add <ws> <project> --from-library <library_id> --expected-revision N`
   (`source=upload`). A voice (returned with its character,
   `matched_via: "voice_of"`) is not a reference of its own: enable
   `voice_enabled` on the character reference, then
   `reference attach … --reference IMG_NN --from-library <voice_id>`.
   Do not generate what the library already has.
3. **Scenario guide.** Run the exact `guide_registry.py match` from
   [writing guides](writing-guides.md). Use the first entry in `matches`; if
   none, write without a guide. Write the decision into `--reason` of
   `script add-version` (for example `autopilot: guide <id>` or
   `autopilot: no matching guide`).
4. **Scenario and storyboard**, then `stage approve` yourself.
5. **Generation method.** Choose `one_shot` or `per_scene` from the approved
   brief and set it with `project set-gen-mode`. For each `per_scene` scene
   after the first, pick the continuity strategy recommended in
   [continuity choice](continuity-choice.md) and persist it with
   `scene continuity`.
6. **Model.** Use the model named in the idea when the verified route exposes
   it and it satisfies the task. Otherwise apply "Выбрать за меня" from
   [model selection](model-selection.md): build the compatible set from the
   exact task, the number of image references and whether video references are
   used ([video inputs](video-inputs.md)), then pick the best fit and record
   the reason. Re-select when the task changes (image → motion → audio).
7. **References** not found in the library: generate them on the verified
   route (`source=generate`).
8. **Prompt guide** for the selected model and task: exact registry match as in
   step 3, first match or none, decision written into `--reason` of
   `prompt add-version`.
9. **Prompts → generations → collection** for the current stage only:
   `action enqueue` (see Spending), `claim`, execute, collect, `finish`.
10. **Pick variants.** After your own visual review, keep the best version with
    `decide approve --target <version> --comment "autopilot: <reason>"`.
    Regenerate or vary yourself when a result has a clear defect.
11. **Approve the stage** with `stage approve --comment "autopilot"` once the
    completion-loop checklist passes, then continue with the next stage.
12. **Assembly** and the final report.

## Tool check before any "no"

Never say that an MCP, provider or tool is missing without all three steps:

1. Search your own tool list for it. In Claude Code use `ToolSearch` with the
   server or provider name; servers still connecting appear there.
2. Run `python3 <skill>/scripts/detect_tools.py --json`. It reads Claude Code,
   Codex, Gemini CLI, Cursor and aimaster preference files offline and prints
   only names, transport and host. Hosted connectors are not in those files,
   so an empty result proves nothing on its own.
3. Make one free probe call on the candidate route (balance, model list,
   catalog). Generation, upload and paid tools are not probes.

If the server is configured but not exposed in this session, say exactly that.
In `guided`, offer reconnecting or another route. In `autopilot`, take the next
available route of the same modality and continue; mention it in the report.

## Allowed stops

Stop only when continuing is physically impossible: no route at all for the
required modality after the tool check, the provider refused on payment or
balance, or an `outcome_unknown` that the provider's own history cannot
resolve (never retry it blindly). Then write a report, not a question: what
is done (with dashboard link), what blocked, which routes were checked, and the
exact command or action that resumes the work. Everything else — an unclear detail, several good
models, a mediocre variant — is decided by you.

## Final report

At the end, list the decisions you made: guides used or skipped, generation
method, continuity strategies, models and why, library items reused,
regenerations, and every provider switch. Keep technical, visual and
self-approved checks separate.
