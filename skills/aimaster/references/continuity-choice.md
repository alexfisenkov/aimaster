# Continuity choice between per-scene clips

Use this gate for every scene after the first when `gen_mode=per_scene`, before
writing/finalizing its motion prompt or selecting the model for generation.
Record the accepted answer through the project question lifecycle with a stable
ID such as `continuity-<scene-id>`. If the user already stated the strategy in
their current request, accept it without asking the same question again.

## Offer three distinct strategies

1. **Continue from the accepted previous video.** Recommended when characters,
   wardrobe, props, location, light and time remain substantially continuous.
   The previous clip becomes a scene-local video reference with
   `usage=continue` for the next scene.
2. **Use the previous final frame as the next start frame.** Useful for a new
   camera composition or a provider that handles image keyframes better than
   source-video continuation. This preserves one visual boundary, not the full
   motion history. This option is immediately available only when the next
   scene's first frame was planned on `image_plan`. If it was not, explain that
   the canonical route requires returning to an earlier stage and re-approving
   later stages; do not promise a frame write that the current `motion` stage
   cannot perform.
3. **Generate an independent clip with shared references.** Use for an intended
   cut, location/time/wardrobe discontinuity, or when the model cannot accept
   the required continuation input.

Briefly recommend one based on the scene transition, but let the user choose
in `guided`. In `autopilot`, take the recommended strategy without asking and
record it with `scene continuity`.
Offer “use this preference for subsequent unchanged scenes” to reduce repeated
questions; even then revalidate every previous result and model schema before
each operation, and ask again when continuity conditions change.

After the answer, record it through the question lifecycle and persist the
same value through `scene continuity` as `previous_video`,
`previous_last_frame` or `independent`. Read the scene back. The runner rejects
`generate`, `vary` and `regenerate` for every later `per_scene` scene until the
choice and its required input are present.

## Preconditions for video continuation

- The previous scene must have an exact active **accepted** video result. Do not
  continue from `ready`, rejected, hidden, retired, stale or ambiguous versions
  without an explicit user choice.
- Verify the local file/container and keep the original result untouched. Asset
  roles are immutable: copy the verified clip to a distinct media path,
  register the copy as `video_reference`, then add/reuse a reference scoped only
  to the next scene with `source=upload`, `usage=continue`.
- The canonical choice records the immediately previous scene ID and its exact
  accepted result version. A `previous_video` reference must be local to the
  target scene and carry that same source-result provenance. A
  `previous_last_frame` first-frame result carries the same provenance. If the
  previous active version changes, the runner blocks the stale choice.
- Verify the selected provider/model's live schema accepts video references or
  extension for this duration/aspect/resolution and other required inputs.
  Source-video continuation, motion control and last-frame continuation are
  separate capabilities. Do not combine video references and keyframes when the
  schema marks them mutually exclusive.
- Run the exact writing-guide match for `modality=video` and task `continue`
  (or the provider's more precise task) after model selection. A guide registered
  only for image generation or generic motion is not automatically applicable.

Update the next scene's prompt with the canonical `@VID_NN` and the exact last
state to preserve: people, wardrobe, props, pose, environment, light and camera
direction. Provider-native mapping still follows reference binding.

After collection, inspect the seam between clips as well as the new clip:
identity, wardrobe/prop state, spatial direction, lighting, timing, frame jump
and audio discontinuity. Preserve each clip separately; concatenation/assembly
is a later operation.
