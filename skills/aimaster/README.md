# Aimaster

A portable agent skill for turning a text or voice idea into a reviewed video
production package. It keeps one canonical project state, preserves history,
and never treats an unavailable external tool as a completed action.

## Package contents

- `SKILL.md` routes the workflow and approval gates.
- `references/creator-studio.md` is the current workflow and command reference.
- `scripts/creator_studio.py` and `studio/` create and mutate Studio state.
- `references/phases/`, `references/state-and-cli.md`, and
  `scripts/state_cli.py` remain only for explicitly continued legacy projects.
- `scripts/validate_config.py` validates knowledge and adapter declarations.
- `config.example.json` is a portable configuration example.
- `scripts/creator_studio_bot.py` is an optional owner-only Telegram controller;
  importing or using the core does not start it.

## Install and remove

Place this entire folder in the skills directory documented by your agent
runtime, without renaming files inside it. To remove the skill, delete only the
copy or link you installed. Video project folders are separate and must not be
removed with the skill.

## Start a new project locally

From this package directory:

```bash
AIMASTER_WORKSPACE="$HOME/Documents/AI-Master-Projects"
mkdir -p "$AIMASTER_WORKSPACE/projects" "$AIMASTER_WORKSPACE/media"
python3 scripts/creator_studio.py project create "$AIMASTER_WORKSPACE" first-video \
  --title "First video" --type video --mode guided
```

The browser is optional. Start it only when the user wants the dashboard:

```bash
python3 scripts/creator_studio.py serve "$AIMASTER_WORKSPACE" --port 0
```

Read [the Studio reference](references/creator-studio.md) for stages, positions,
chat commands and grants. This package is self-contained: Studio operation does
not depend on the repository demo, a personal profile, ffmpeg, or an external
validator.

The Studio core and CLI use local files and loopback HTTP. The optional bot
entrypoint makes limited Telegram Bot API requests only when a user explicitly
launches it with owner-only environment configuration. It is a controller, not
an LLM or speech recognizer, and cannot wake an inactive creative agent.

For an existing legacy `state_cli.py` project, keep using its old phase and
state references. Never mix the legacy and Studio layouts in one project or
migrate one implicitly into the other.
