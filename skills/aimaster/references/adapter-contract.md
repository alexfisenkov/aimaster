# Adapter contract

Every capability follows: `discover`, `probe`, `prepare`, `execute`, `collect`, `validate`, `provenance`.

- `discover`: inspect the MCP/tools/routes already connected in the current chat. Do not browse a provider site merely to discover a route.
- `probe`: confirm current-session availability, relevant capability, authentication without secret values, and observable cost/limit. Present only models exposed by that verified route.
- `prepare`: a reviewable prompt/job package and intended outputs.
- `execute`: only after fresh approval for an external or paid action.
- `collect`: bind results to `shot_id` and revision without guessing success.
- `validate`: technical evidence and visual evidence as separate fields.
- `provenance`: adapter/model, settings, source, time, and artifact path/URI.

Canonical capability IDs are `transcription`, `knowledge`, `image_generation`, `image_to_video`, `visual_inspection`, `file_delivery`, `montage`, `telegram_transport`, `design_social_context`, and `agent_handoff`. Brand-specific implementations stay outside this public core.

If unavailable, record the probe result and choose: verified local implementation, already connected adapter, manual job package, or one explicit blocker. `outcome_unknown` is not failure or success and forbids automatic retry.

Before prompt preparation for each newly selected model and relevant task, use
the [writing-guide gate](writing-guides.md). A guide the user selects is the
creative specification for that prompt task, but never authorizes provider
execution. Reusable opt-in guides live in the workspace catalogue; an existing
`instructions/model-prompt-instructions.md` remains a supported general guide.
