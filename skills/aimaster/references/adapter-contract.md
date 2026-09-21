# Adapter contract

Every capability follows: `discover`, `probe`, `prepare`, `execute`, `collect`, `validate`, `provenance`.

- `discover`: first load [saved provider preferences](provider-preferences.md), then inspect the MCP/tools/routes exposed in the current chat. Offer the preferred saved provider first; a missing tool does not delete the saved declaration. Persist explicit user choices with read-back. Do not browse a provider site merely to discover a route.
- `probe`: confirm current-session availability, relevant capability, authentication without secret values, and observable cost/limit. Present only models exposed by that verified route.
- `prepare`: a reviewable prompt/job package and intended outputs. Before every
  external generation, complete [reference binding](reference-bindings.md).
- `execute`: only after fresh approval for an external or paid action.
- `collect`: follow the mandatory [completion loop](completion-loop.md): save
  confirmed output locally, bind it to the exact Studio `pos:*` target (or
  legacy `shot_id`) and revision, read back the dashboard state, then finish.
- `validate`: technical evidence and visual evidence as separate fields.
- `provenance`: adapter/model, settings, source, time, and artifact path/URI.

Canonical capability IDs are `transcription`, `knowledge`, `image_generation`, `image_to_video`, `visual_inspection`, `file_delivery`, `montage`, `telegram_transport`, `design_social_context`, and `agent_handoff`. Brand-specific implementations stay outside this public core.

If unavailable, record the probe result and choose: verified local implementation, already connected adapter, manual job package, or one explicit blocker. `outcome_unknown` is not failure or success and forbids automatic retry.

Before prompt preparation for each newly selected model and relevant task, use
the [writing-guide gate](writing-guides.md). A guide the user selects is the
creative specification for that prompt task, but never authorizes provider
execution. Reusable opt-in guides live in the workspace catalogue; an existing
`instructions/model-prompt-instructions.md` is discovery-only until its exact
scope is classified and registered.
Only a deterministic registry match for modality, task and model/version can be
offered automatically; conversation reuse is not a match.

Reference binding is a provider-neutral safety contract, not a universal prompt
syntax: route, model and mode determine whether an observed native inline tag,
structured file field/order, or hybrid form is used. Unknown mapping blocks
preparation and execution; it never permits a paid probe or invented tag.

Select the model through [model selection](model-selection.md). Provider or
catalog defaults are candidates, not a sufficient shortlist or compatibility
decision.
