# Stage and generation completion loop

Provider success is an intermediate event. A generated file is not complete
for aimaster until it is collected, validated and visible in Creator Studio.
Apply this loop to images, references, video, audio, variations, regeneration,
post-processing and final assembly.

## Before any external generation

Read the current canonical state and resolve the exact target position. Its
declared stage must equal `view_stage.current_stage`; the current prompt/result
owner and revision must also match the prepared operation. A grant, a prepared
prompt or a visible future position does not bypass this gate.

If the target belongs to a future stage, do **not** call the provider. Complete
the current stage's prompts and writing-guide choices, show the plan, and obtain
the normal stage decision first. A generated reference prompt is prepared at
`image_plan`, but its external image generation and result collection occur at
`image_results`. Motion prompts may be prepared at `image_plan`; motion media is
generated only at `motion`.

If a provider result already exists because this rule was violated, preserve it
without rerunning: copy it into workspace media, register the asset, and update
the operation's existing private `binding.md`. If none exists, create
`WS/projects/<id>/.generation/recovery-<fresh-id>/binding.md` with
`action_id: none` and `status: pending_collection`. Record project, target,
asset, external ID, prompt/model/bindings, source revision and required stage;
write `unavailable` for facts that cannot be verified—never reconstruct or
invent them. This is a durable **manual recovery record**, not a runtime
queue or proof that the result is already in Studio. Do not auto-approve stages
to force insertion. Resolve the current stage with the user; once the target
stage is reached, read that record, revalidate target/prompt/references and
append the same asset through the normal result command. Mark the record
collected only after snapshot read-back. A claimed job stops `needs_chat` until
collection can complete.

User-supplied source material follows [asset intake](asset-intake.md), not this
generated-output collection path. Do not turn an uploaded reference into a
generation task.

## After every successful external output

1. Collect the confirmed provider output using its supported result/read-back
   route. Download or copy the confirmed artifact into `<workspace>/media/`
   with a distinct filename. Preserve every previous variant; never overwrite
   the source or another version.
2. Validate the actual container/file and, when tools allow, visually inspect
   it against the exact prompt, references and storyboard. Record the provider
   result ID, selected model/settings, native prompt/bindings and QA evidence in
   the private operation record. A remote preview link alone is not collection.
   For video, inspect the complete duration or representative checkpoints that
   cover every scripted event—not only the first frame—and check identity,
   anatomy, transitions, continuity, location, text/logos and requested timing.
   For audio/mixes, listen to the used interval and verify synchronization,
   clipping, duration and fade/cut boundaries. Report exactly what was viewed
   or heard; technical stream metadata is not visual/audio QA.
3. Register the local artifact with the correct asset role and append it to the
   exact current Studio position/result group using the verified revision.
   This canonical collection is part of the already authorized generation,
   not another paid run and not a reason to ask for duplicate permission.
4. Read the snapshot back. Confirm that the expected result/version is visible
   in the dashboard, then finish the claimed job. Do not report the generation
   as done or `succeeded` before this read-back. If provider execution succeeded
   but collection cannot be completed, preserve the external evidence and stop
   with an explicit `needs_chat`/collection blocker; never generate again.
5. Show the result and offer the decisions supported for that material:
   accept/reject, another variation, regenerate with stated changes, hide,
   retire/restore, or continue. Do not auto-accept a creative result.

Post-processing creates another version. For example, a video with added music
is a new assembly/result while the original video and music stay preserved and
visible. When the user prefers an earlier version, record that decision and use
that exact version downstream instead of merely saying it is preferred.
Words such as “этот нравится больше” identify a preference but do not
automatically approve/retire versions. Offer to record the preferred version as
accepted and state what will happen to the others.

Before a paid audio generation, show provider/model, exact prompt, source and
generated duration, cost preview, which interval will be used in the project,
and the intended beat/cue map. Obtain the scoped permission only after that
preflight. A generic style description plus price is insufficient.

## Before leaving a stage

Read the canonical state and explicitly check:

- every required position has a prompt and accepted result where required;
- intended references are attached and bound; no missing proposed reference,
  frame, variation or correction was silently skipped;
- unresolved questions, `needs_chat`, `outcome_unknown`, stale prompts and
  uncollected remote outputs are listed;
- the user has seen the current materials and has the relevant decision paths.

If something optional could materially improve the result, offer it once with
its effect and cost boundary. If required work is missing, do not offer stage
approval as though the stage were complete. If all required material is ready,
offer approval and state what the next stage will add.
Every result-turn ends with the concrete next decision or stage action. Do not
leave a ready result at `draft` while merely listing that buttons exist.

## Before declaring the project complete

Audit all stages and variants. Ensure the selected image/video/audio versions
are reflected in canonical state and the final assembly points to the intended
files. Offer final assembly when it has not been produced; after assembly,
offer review, export/delivery or an editor handoff with ordering, durations,
script, prompts and comments. “Provider job finished,” “file exists locally,”
and “link sent to the user” are not project completion by themselves.
