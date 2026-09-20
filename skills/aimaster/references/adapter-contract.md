# Adapter contract

Every capability follows: `probe`, `prepare`, `execute`, `collect`, `validate`, `provenance`.

- `probe`: availability, version, authentication without secret values, and known cost/limit.
- `prepare`: a reviewable prompt/job package and intended outputs.
- `execute`: only after fresh approval for an external or paid action.
- `collect`: bind results to `shot_id` and revision without guessing success.
- `validate`: technical evidence and visual evidence as separate fields.
- `provenance`: adapter/model, settings, source, time, and artifact path/URI.

Canonical capability IDs are `transcription`, `knowledge`, `image_generation`, `image_to_video`, `visual_inspection`, `file_delivery`, `montage`, `telegram_transport`, `design_social_context`, and `agent_handoff`. Brand-specific implementations stay outside this public core.

If unavailable, record the probe result and choose: verified local implementation, already connected adapter, manual job package, or one explicit blocker. `outcome_unknown` is not failure or success and forbids automatic retry.
