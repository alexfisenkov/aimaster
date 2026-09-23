# User-supplied asset intake

A file the user supplies is existing material. It is never permission or a
request to generate the same material again. Apply this rule to images, video,
voice, audio and documents in every project and content type.

When no file is attached, do not assume upload. For an “add material to this
scene” request, offer upload or generation. If the user already wrote which one
they want, accept that choice without repeating it. A generated scene-local
reference is planned at `image_plan` with its exact `scene_id`; its external
generation waits for `image_results` under the completion-loop stage gate.

## Classify before writing

Use the current question and user message to identify the intended target. If
the target is ambiguous, ask one short question before changing state
(`guided`). In `autopilot` after brief approval, attach it to the most likely
target, record why, and mention it in the final report.

| Supplied material | Canonical destination |
|---|---|
| Character, product, location or style image | Existing matching reference, or a new reference with `source=upload` |
| Video reference | Existing/new `kind=video`, `source=upload`, with explicit `usage` |
| Character voice sample | That character's enabled voice reference |
| Generated image/video/audio output | Exact versioned result position through the completion loop—not a reference |
| Audio intended for atmosphere/fx/music/voice layer | Exact audio result layer |
| Scenario or prompt instruction document | Writing-guide gate/catalogue |

Prefer the existing planned placeholder when the user identifies it (“второй
персонаж — Артём”) or the role/name/scene makes the match unambiguous. Update
that reference instead of creating a duplicate. Preserve its `reference_id`,
scene memberships and history.

## Attach means uploaded

For an image/video reference:

1. Copy the source into workspace media without overwriting prior files.
2. Register it with the matching asset role.
3. Attach it to the selected reference using the current revision. Direct
   attachment atomically sets the reference to `source=upload`; a caller that
   creates a reference with `asset_id` is normalized to `source=upload` too.
4. Read back the reference and derived positions. Confirm `asset_id` is the
   registered file, `source=upload`, and no `pos:ref:<id>` generation position
   remains active. An old generated prompt/result may remain as provenance but
   does not authorize or require another generation.

Never generate a replacement merely because the placeholder was originally
`source=generate`. Generation is allowed only when the user explicitly asks
for a generated alternative, transformation or new variant after the supplied
file has been acknowledged.

Voice/audio uses its own role and attachment flow; do not convert it into an
image-generation request. Provider-native upload/binding for a later external
generation is separate from this Studio intake and follows reference binding.

If registration or attachment fails, keep the original reference unchanged,
report the blocker and do not fall back to generation.
