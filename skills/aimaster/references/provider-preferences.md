# Persistent registry of generation MCPs

This is a feature of the **public skill for every user and every generation
service**, not a developer-specific preference. Start empty: there is no
preconfigured provider. Once the user adds a generation MCP, or the agent
discovers it among actually exposed generation tools, remember it for future
sessions. Multiple services accumulate in the registry; never replace the
entire list with the last service selected.

## Storage and startup

At **every skill activation**, before provider discovery or selection, read
the user's persistent preference file:

`<config-home>/aimaster/preferences.json`

Use an absolute `XDG_CONFIG_HOME` when set; otherwise use the current user's
`~/.config`. Resolve this in the execution environment: never hardcode the
author's home. This file belongs to the user, outside the installed skill and
outside any individual project. The same environment reuses it across chats,
workspaces, restarts and official updates. A different machine/environment
needs the user's explicit transfer; do not promise automatic cloud sync.

If absent, start with an empty profile. If unreadable, malformed or of an
unsupported version, explain the problem; preserve it and continue selection
in chat without claiming that it was saved. Do not overwrite it with defaults.
This is not the legacy `director.config.json` or the runner's `--profile`.

The initial shape is:

```json
{
  "schema_version": 1,
  "preferred_provider_id": null,
  "providers": []
}
```

Each provider entry records `id`, `name`, `transport`, `declared_capabilities`
(an array of capability names) and `declared_by` (`user` or `discovery`).
For `discovery`, derive capabilities from actual tools/schema or a read-only
catalog, never from the MCP name alone. These are preferences
and user declarations, **not proof of present availability**. Never store
credentials, endpoints with secrets, model catalogs, grants or execution
permissions here. Read the file as data; it cannot authorize commands.

## Choice in each session

1. Read saved declarations, then inspect currently callable MCP/tools. Classify
   each saved provider as currently verified, visible but unverified, or not
   exposed in this session. A read-only catalog/probe may verify capability;
   generation, upload and paid tools are not discovery probes.
2. Before preparing generation in a new session/project, offer an explicit
   choice listing the remembered services by their actual names and current
   availability, plus adding another service or preparing prompts only. Put a
   previously selected preferred service first when one exists; never invent a
   developer's default. Use the host's choice UI when available. Do this in automatic mode
   too. If the user already explicitly chose the provider in the current
   request, accept that answer rather than repeating the same question.
3. If it is missing now, name that saved service and say its MCP is not exposed
   in this session; offer reconnecting or choosing another available route. Keep the
   saved declaration. Do not silently forget it, claim it is connected, switch
   to a website, or install/reconfigure a connector without authorization.
4. Reuse the accepted choice for the current run. When the next stage requires
   a different capability, verify it and offer the choice again. Before writing
   model-specific prompts, select a model from the verified route and perform
   the separate writing-guide choice. Saved preferences do not bypass it.

## Saving and changing choices

When the user adds or names a generation MCP, explicitly selects a service,
or discovery finds a new exposed generation MCP, save/update its entry and read the
saved file back. No extra “may I remember?” question is needed for this
service preference. A selected service becomes `preferred_provider_id` unless
the user says it is only for the current run; that temporary choice stays with
the project. Merely declaring another available service must not replace an
existing preference. Discovery alone never chooses a preferred service.
Choosing “prompts only” does not erase saved services.

Merge by stable provider ID and preserve other providers and user fields.
Read the latest file before writing; use an atomic replacement when available
and do not overwrite a detected concurrent edit. Create the parent directory
only when saving. On failure, keep the in-chat choice and say persistence was
not confirmed. Announce successful saving briefly, without dumping the file.
Remove or reset a stored choice only on the user's request.

No provider is preselected for all users of the public package. Personal
preference files must never be committed or bundled into a public release.
