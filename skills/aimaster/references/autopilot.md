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

Switching back to `guided` stops spending at once: the engine voids unused
autopilot grants and moves autopilot-queued actions to `needs_chat` with
reason `autopilot_off` (listed as `cancelled_actions` in the CLI output). Do
not re-queue them under `guided` without that mode's approval.

Autopilot mode is the owner's standing authorization, for this project, to
**spend** on paid actions (no limit) and to **upload** the project's own assets
(references, frames, voices, previous clips) to the selected verified route
when a generation needs them. It also covers the free local install the
montage needs: when `montage status` reports `engine.state: missing`, run its
install command yourself (`engine.install_argv` or `engine.install`); it adds
whatever else the skill lacks on this machine too (see
[montage](montage.md#engine-check)).
Nothing else is authorized: no account changes, no publishing, no uploads of
files outside the project or library.

- Do not run `grant` and do not ask for spending approval. Queue each paid
  action with
  `creator_studio.py action enqueue <ws> <project> --type generate|vary|regenerate --target <T> --expected-revision N --idempotency-key K [--payload JSON]`.
  The idempotency key is required: one key per intended generation, e.g.
  `<project>:<type>:<target>:<attempt>`. Repeat a lost or uncertain call with
  the **same** key — it returns the existing action and never charges twice.
  While an action of the same type on the same target is `queued` or
  `running`, a different key is refused with that action's id; use a new key
  only for a new generation after the previous one finished.
  In autopilot it returns `status: queued, issued_by: autopilot` and writes an
  `autopilot-grant` history entry. That entry raises the revision by one: take
  the fresh revision for the next `--expected-revision`. Then `claim`, execute,
  collect and `finish` as in [Creator Studio](creator-studio.md).
- If **enqueue** returns `needs_chat`, re-read `project.mode`. If it is not
  `autopilot`, the `guided` rules apply from here on (grant and approval in
  chat). If it is `autopilot` and enqueue still returns `needs_chat`, stop with
  a report (see Allowed stops); never issue a grant on your own. This is
  different from a `needs_chat` you write with **finish**, which is a blocker
  handled under Allowed stops.
- Everything else still applies: stage preflight in the
  [completion loop](completion-loop.md), [reference binding](reference-bindings.md)
  and its validator, collection and read-back. A failed check is fixed and
  re-run by you, not turned into a question.
- A defect found in review authorizes a `vary` or `regenerate` in autopilot;
  record why in the operation record and the final report.

## Order after approval, stage by stage

**Before `scenario`:** run the **tool check** (below) and
`creator_studio.py library match <ws> --text "<idea>"`. Remember the matches;
references cannot be written yet (the engine accepts `reference add/attach/edit`
only from `image_plan` on).

Known limitation of `library match`: it compares word stems, so it cannot tell
a female name from the genitive of a male one (Russian «Александра» — a woman,
or «(у) Александра» — Alexander's). When the idea's heroine has a name whose
stem matches a library character, check gender and role against the scenario
before using that entry; never attach another person's face.

Guide rule used below: run the exact `guide_registry.py match` from
[writing guides](writing-guides.md), take the first entry in `matches`, else no
guide; write the decision into `--reason` (for example `autopilot: guide <id>`
or `autopilot: no matching guide`).

Model rule used below: use the model named in the idea when the verified route
exposes it and it fits; otherwise apply "Выбрать за меня" from
[model selection](model-selection.md), weighing the exact task, the number of
image references and whether video references are used
([video inputs](video-inputs.md)). Record the reason. Re-select for each new
task (image, scene motion, one-shot, audio).

1. **`scenario`.** Scenario guide → `script add-version` → `scenes set` (with
   durations for video) → `stage approve --comment "autopilot"`.
2. **`image_plan`.**
   - **References first.** For each remembered library match:
     `reference add <ws> <project> --from-library <library_id> --expected-revision N`
     (`source=upload`). A voice (returned with its character,
     `matched_via: "voice_of"`) is not a reference of its own: enable
     `voice_enabled` on the character reference, then
     `reference attach … --reference IMG_NN --from-library <voice_id>`. Every
     other needed reference: `reference add … --source generate`. Do not
     generate what the library already has.
   - `project set-gen-mode` (`one_shot` / `per_scene` from the approved brief).
   - Choose the image model (model rule), then the prompt guide for it.
   - `scene plan`: plan only frames that will really be used. Every planned
     frame is a required, paid `image_results` position. For `per_scene`, plan
     a first frame on a later scene only where `previous_last_frame` is truly
     likely (a new composition over an unchanged state); plan first/last frames
     where the chosen motion mode needs them.
   - `prompt add-version` for generated references, planned frames and scene
     images. Motion prompts may be drafted here; they are drafts and are
     rewritten at `motion`.
   - `stage approve`.
3. **`image_results`.** For every generated reference, planned frame and scene
   image (photo projects), references first: `action enqueue` → claim →
   execute → collect (`result add-version`) → finish. Review, pick with
   `decide approve --target <version> --comment "autopilot: <reason>"`,
   vary/regenerate on a clear defect. Then `stage approve`.
4. **`motion`.**
   - **`per_scene`**, for each scene in order:
     1. for scenes after the first, `scene continuity` with the strategy
        recommended in [continuity choice](continuity-choice.md). If it is not
        available now (for example `previous_last_frame` without a first frame
        planned on `image_plan`, or the model rejects video continuation),
        take the best available one (`previous_video` or `independent`), record
        the reason, and **do not** go back to an earlier stage. For
        `previous_video`, first copy the accepted previous clip to a new media
        file, register it as `video_reference` and add it scene-locally with
        `usage=continue`, as the preconditions there require;
     2. `scene video-mode` (`first`, `firstlast` or `references`) matching the
        accepted frames and the model schema;
     3. model rule for this scene's task, then guide rule (task `continue` for
        `previous_video`);
     4. `prompt add-version --target pos:scene:<scene>:video` with the exact
        `@IMG_NN` / `@VID_NN` / `@VOICE_NN` and frames this scene uses;
     5. enqueue → claim → execute → collect → finish → review →
        `decide approve`.
   - **`one_shot`**: one position, `pos:oneshot`. No `scene continuity` or
     `scene video-mode` is required for it (the runner checks those only for
     per-scene video). Model rule for the whole-video task, guide rule, then
     `prompt add-version --target pos:oneshot` covering all scenes with the
     tags it uses; accepted frames may be used as inputs when the model schema
     supports them. Then enqueue → … → `decide approve`.
   - `stage approve`.
5. **`audio`.** A layer is required only when its result group has an entry.
   If the brief needs no separate sound, create nothing and `stage approve`
   the empty stage. Otherwise, per layer: model rule, guide rule, prompt,
   enqueue → … → `decide approve`, then `stage approve`.
6. **`assembly`.** Photo: `assembly set` with the accepted image, review it,
   then the final report. Video/mixed: the [montage](montage.md).
   `montage status`; if `engine.state` is `missing`, run its install command
   yourself (`engine.install_argv`, or the line `engine.install` in the shell —
   [montage](montage.md#engine-check); free, local; no question) and check
   again. Then
   `montage draft`, titles only where the meaning needs them
   (`montage edit … title-add`), `montage render`. Review the MP4: duration,
   frame size, sound and the absence of network access are checked by the
   render; look at frames when a viewer is available, otherwise say the visual
   check was not performed. Fix a visible defect with `montage edit` and render
   again. Then `stage approve` and the final report.

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

Blockers are handled by when they happen:

- **Before the external call** (binding, validator failure, stale revision
  while preparing): fix the cause, re-read the state, then queue the action
  again. Nothing was spent yet.
- **After execution** (collection failed, conflict on `result add-version`,
  read-back mismatch): fix the cause and repeat **only the collection** of the
  existing provider result, as in the [completion loop](completion-loop.md).
  Never generate again: the result is already paid for.

A blocker that cannot be fixed this way becomes a stop.

Stop only when continuing is physically impossible:

- no route at all for the required modality after the tool check;
- the provider refused on payment or balance;
- an `outcome_unknown` that the provider's own history cannot resolve (never
  retry it blindly);
- a binding, collection or revision blocker that you could not fix;
- `action enqueue` returned `needs_chat` although `project.mode` is
  `autopilot`;
- the montage engine could not be installed: `engine.install` ran and
  `montage status` still reports `engine.state: missing` (for example Linux
  without Node.js 22). Report `engine.reason`, the installer's montage lines
  and the command;
- the montage refuses the project folder («… монтаж не трогаю»: links or a
  program such as `ffmpeg` inside `montage/`). Do not delete them yourself;
  report what the refusal names.

Then write a report, not a question: what is done (with dashboard link), what
blocked, which routes were checked, and the exact command or action that
resumes the work. Everything else — an unclear detail, several good models, a
mediocre variant — is decided by you.

## Final report

At the end, list the decisions you made: guides used or skipped, generation
method, frame plan, continuity strategies (and any fallback with its reason),
models and why, library items reused, uploads, regenerations and why, every
provider switch, the montage (engine installed or not, versions built, titles
added and why, the path of the final MP4), and an available skill update if
one was found. Keep technical, visual and self-approved checks separate.
