# Reference binding for external generations

Complete this procedure **before every external generation** (including vary
and regenerate), after route/model/mode are verified and before any paid call.
It is a binding check, not authorization: uploading is an external action and
requires authorization; execution still needs its scoped approval.
First pass the target-stage preflight in [the completion loop](completion-loop.md).

## Canonical and native forms

Keep canonical Studio references stable: `@IMG_NN`, `@VOICE_NN` and `@VID_NN` identify the
creative asset/version in the canonical prompt/state. They are not a promise of
provider syntax. Bind every media input that the operation uses, including
character/location/product/style references, first/last frames and voice or
other audio references, plus source videos and their selected usage—even when
the canonical prose has no corresponding tag. For video operations follow
[video inputs](video-inputs.md); source-video extension, motion transfer and
last-frame continuation require different verified request shapes.
For this one operation, determine the selected route + model + mode's actual
UI/MCP schema and record each intended input as:

`canonical reference -> asset ID + exact version -> observed native tag or
structured field/slot and order -> role`.

The native form may be an inline tag, an ordered structured attachment field,
or a hybrid. Never invent tag syntax, assume a universal `@img1`, or put fake
tags into a structured provider's prompt. In a rich mention UI, insert the real
chip and verify it rendered as a chip rather than plain text. A visible upload
thumbnail does not prove prompt binding.

For example, only after read-back a route may map `@IMG_01` to `@img1` and
`@IMG_02` to the non-sequential `@img3`; the final text must then identify what
each actual mention means (for example, character `@img1`, background `@img3`).
If a live Magnific form exposes `@char1`, `@char2`, `@img1`, `@img2`, those
exact observed tags—not the words “first character”, “cafe” or “product
reference”—must appear in that operation's native prompt with their roles.
This example does not reserve those names: the next upload/order/model may
produce different tags.

## Procedure

1. Select only inputs actually intended for the target; resolve their current
   assets and versions and verify their creative role/input function. Do not
   use a vague request such as “character reference”: name the exact canonical
   reference or frame/audio input and its role.
2. Perform the authorized upload/attachment and read back the actual native
   tag, field, slot and order from the selected route. Record the mapping above
   for this operation only. A different model, mode, reordering, removal or
   replacement invalidates it and requires a new binding.
3. If the canonical prompt has only generic prose (for example, “character
   reference”), repair a per-operation working copy before compilation with
   explicit named reference-role/position wording; exact replacement alone
   cannot bind an absent token. Keep the **stored** canonical prompt unchanged.
   Construct the outgoing prompt from that working copy by deterministic,
   exact-token replacement only (so `@IMG_01` cannot alter `@IMG_010`), never
   a global prose or substring replacement. For structured routes, resolve
   mentions to the schema's
   verified role/position semantics and send files only in their observed
   fields/order: no internal unresolved tag belongs in the outgoing prompt.
4. Build an operation manifest from the fresh Studio/claimed-job context,
   not from memory or only from the files that happen to be visible in the
   provider. Record the operation ID, current Studio revision, provider,
   route, model, observation time, canonical `reference_id` and exact
   `asset_id` for every expected input. Use
   `transport=inline` for native tags/chips, `structured` for schema fields and
   `hybrid` only when the verified route requires both. For inline/hybrid
   inputs, the final prompt must contain every exact observed native token at
   least once; prose names do not count. For structured/hybrid inputs, record
   the exact field/slot. Native inline tokens and structured slots must be
   one-to-one within the operation. Set `binding_source` to the observed
   surface: `plain_text`, `rich_ui`, `structured_schema` or `hybrid`. With
   `rich_ui`, `chip_verified=true` is mandatory for every inline/hybrid input
   and may be recorded only after the final UI actually shows the mention
   chip.
5. Save the exact outgoing prompt as `prompt.txt` and the machine record as
   `binding.json`, then run before the external call:

```bash
python3 scripts/validate_reference_bindings.py \
  WS/projects/<id>/.generation/<operation-id>/binding.json \
  WS/projects/<id>/.generation/<operation-id>/prompt.txt \
  --context WS/projects/<id>/.generation/<operation-id>/claimed-job.json
```

   For a claimed job, save the exact JSON returned by `claim` as
   `claimed-job.json`; `--context` is mandatory and the validator compares the
   complete canonical tag/reference ID/asset ID set and state revision. Include
   accepted frame inputs as canonical `FRAME_FIRST`/`FRAME_LAST` with
   `reference_id` `frame:<scene-id>:first|last`. For a direct-chat operation
   without a job, omit `--context` only after rebuilding the same complete set
   through the reference's read-only state door and recording `action_id: none`
   in `binding.md`.

   A minimal inline record is:

```json
{
  "schema_version": 1,
  "operation_id": "action-or-direct-chat-id",
  "provider": "observed provider",
  "route": "observed route",
  "model": "observed model",
  "binding_source": "rich_ui",
  "observed_at": "2026-09-21T00:00:00Z",
  "state_revision": 7,
  "references": [
    {
      "canonical": "@IMG_01",
      "reference_id": "IMG_01",
      "asset_id": "asset-id-from-current-context",
      "native": "@char1",
      "role": "main character",
      "transport": "inline",
      "chip_verified": true
    }
  ]
}
```

   A structured entry uses `"slot": "video_reference[0]"` instead of
   `native`; a hybrid entry contains both. Omit `chip_verified` when the
   source is plain text or structured. The validator must return `status=valid`.
   It fails on a missing exact native tag, an unresolved canonical tag, a
   duplicate native tag/slot, incomplete operation provenance or an unverified
   rich-UI chip. `@img10` does not satisfy `@img1`. This local check proves the
   recorded manifest and prompt agree; it cannot by itself prove a provider
   issued the tag or accepted the payload. Live schema/UI read-back in steps
   2 and 6 remains mandatory.
6. Audit the final outgoing prompt **and** attachment list, including all
   references when there are many: every included asset has the intended role
   and mapping; no excluded or unbound asset remains. Save the human-readable
   operation record at
   `WS/projects/<id>/.generation/<operation-id>/binding.md`, outside
   public/dashboard sanitized state. For a claimed job use its exact `action_id`
   as `<operation-id>`; for direct chat create a fresh unique ID and record
   `action_id: none` (there is no job to `finish`). Record project ID, action
   type, target position/version, observed state revision, source prompt version,
   any source result version, selected route/model/mode, and the full media
   mapping and the validator result. Do not confuse this record ID with authoring `--operation-id`
   receipts. Strip secrets, signed URLs and provider
   credentials. The canonical prompt remains in Studio state. If the prompt
   was edited after a native tag/chip was inserted, re-read and verify that no
   stale tag, chip, slot or attachment remains before execution. This
   deterministic audit and substitution are part of the already authorized
   run, not a second approval request.

If the route cannot expose a native binding, an upload/attachment did not read
back, a role is unclear, the machine preflight fails, or the final payload cannot be audited, stop at
`prepare`: a claimed job finishes `needs_chat`; a direct-chat operation stops
and explains the blocker. Make no paid call. A live mapping does not override
the selected writing guide or other creative constraints.
