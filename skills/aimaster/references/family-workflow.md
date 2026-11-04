# One project, one canonical state

The public CLI is `python3 <skill>/scripts/creator_studio.py`; substitute installed `python_cmd`. `WS` is a persistent folder outside the installed package and `ID` is the project ID. Always use the revision returned by a read or previous successful write. A stale revision is a conflict: reload, inspect, decide again. Do not rewrite history.

## Intake and brief

Create the project immediately and open its exact dashboard URL. In guided mode ask only material questions. Use native choice UI where the host provides it; otherwise a numbered prompt works in chat and on mobile. Store answers with `question`/`project` commands. The user chooses whether supplied image/video/audio is a source, reference, existing shot, edit target or transform input. Keep original bytes and provenance. For video ask duration and one-shot/per-scene; set generation mode during `image_plan`. For a later scene, ask whether to continue prior video, use its last frame or start independently when relevant. Video continuation requires a supported endpoint/schema field; never send it as ordinary generation based only on brand name.

Fully automatic mode presents a short brief including service, guide rule, key references, duration and montage/materials choice for approval. The one-time warning covers spending without a media cap. After approval the agent resolves ordinary stage decisions itself. Missing auth/route or contradictory source remains a visible blocker. Existing `autopilot` is an internal state name; user-facing wording is «полностью автоматически»/“fully automatic”.

## Route, guides and media

Read current provider tools/catalog first, then select service *and model* for the intended operation. Record a paid route with `creator_studio_operator.py route-set`; its binding is to exact prompt/reference basis. `guide_registry.py --workspace WS list --include-builtin` lists metadata; `match --include-builtin` uses the **specific task** as well as stage, kind, modality, provider, model family, model and version. Scenario-family tasks include `ugc-script` and `expert-script`; `task=scenario` returning empty is inconclusive. If no exact candidate exists, record `source=none` with null ref/hash. `project set-guide-choice WS ID --file choice.json --expected-revision N` validates scope and SHA. User guides live in `WS/instructions`, never installed `guides/`.

Before external generation use [reference binding](reference-bindings.md): discover actual operation-scoped fields and native mention tokens, map each selected canonical reference, validate, retain submitted arguments. Route and reference basis must still match when clicked. Scene-local reference may be an uploaded or generated copy/direct input. Supplied upload is not a request to regenerate. Canonical IDs and provider bindings are different namespaces. A media result is incomplete until downloaded to WS, registered to the right position, read back and reviewed.

`library list|match|add|edit|attach|import` works across characters, products, locations, visual styles, voice and other. `match` returns candidates and ambiguity, never picks a namesake automatically. `reference add|attach --from-library ID` keeps the identity link; project assets remain if library metadata later disappears. Library notes/tags and personal media remain outside package updates and export unless specifically selected.

## Stages and handoff

Video: `scenario → image_plan → image_results → motion → audio → assembly`; photo skips motion/audio. Do not generate future-stage media early. Review each result; approve a selected version and stage through the public decision/approval CLI. At assembly use the recorded choice:

- `materials`: `assembly materials WS ID --expected-revision N` prepares an immutable selected-assets packet, then `stage approve`. Verify manifest and file hashes after relocation. No invented MP4 is needed.
- `montage`: `montage handoff WS ID --style basic`, then `montage build WS ID --expected-revision N --style basic`. Keep base version available. Optional `build --improve --style cinematic|dynamic`, desk edits, overlay drawing, render, save-style and `montage export` follow user preference. `montage verify-export PATH/manifest.json` checks a moved package. Read [montage](montage.md) for exact commands and engine needs.

Show what was checked: bytes/container, visual frames, audio streams versus human listening, selected version, relocation and delivery. A queued action, HTTP 202, source clip or draft is not a completed output. Uncertain paid result requires provider read-back and reconciliation without repeat POST.
