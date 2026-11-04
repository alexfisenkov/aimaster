# Install AIMaster with a local agent

This procedure is for an agent with terminal access on macOS, Linux or native Windows. The user has authorized installation, but OS admin prompts, provider OAuth and account login still require their normal interaction. Do not put tokens in chat, argv or logs. Do not perform a paid generation during installation. Preserve unrelated MCP configuration and installed skills. Python 3.11+ is required; no Python packages are required by AIMaster.

## 1. Obtain the skill

If Node/npx is present, use the documented skills CLI from the official repository:

```sh
npx skills add https://github.com/alexfisenkov/aimaster/tree/main/skills/aimaster --skill aimaster -g -a codex -a claude-code
```

Read the result and locate the actual installed folder containing `SKILL.md`, `VERSION`, `scripts/`, `studio/`, `references/` and `guides/`. Do not assume the folder's parent is a Git clone. The CLI was exercised with a synthetic home; still inspect the target user's result. If Node is missing and can be installed with the OS manager, do so if authorized. For a no-npx route, clone the official repository into a persistent nonconflicting directory, then run `python3 skills/aimaster/scripts/install.py --install-deps --json` from that clone. On Windows use `py -3` if that is the available Python 3.11+ command. Do not clone over an existing directory or force-replace a conflicting skill.

Install missing free Python/Git/Node/ffmpeg prerequisites through the OS's official manager where the user and OS allow it. `family_setup.py setup --install-deps` attempts supported free prerequisites, but cannot bypass missing package managers, admin prompts or host login. Report a partial result and exact next step in those cases. `install.py --print-python-cmd` can report the appropriate Python command without writing.

## 2. Set up the family

From the **actual installed skill folder**, run with the command above's Python (`python3` or `py -3`):

```sh
python3 <skill>/scripts/family_setup.py catalog --json
python3 <skill>/scripts/family_setup.py setup --install-deps --json
python3 <skill>/scripts/family_setup.py status --json
```

Default setup covers SYNTX, Higgsfield, Magnific and fal plus AIEditing. The official local SYNTX source is [alexfisenkov/syntx-mcp](https://github.com/alexfisenkov/syntx-mcp). Hosted MCP endpoints are [Higgsfield](https://mcp.higgsfield.ai/mcp), [Magnific](https://mcp.magnific.com) and [fal](https://mcp.fal.ai/mcp-relay); those are connector destinations, not downloadable GitHub packages. AIEditing is the [workshop](https://github.com/alexfisenkov/AIEditing), not a universal rendering program. The setup merges known host entries after backups and read-back; a name conflict remains visible. `--agent codex|claude|all` narrows host registration if needed. `--syntx-upload-destination hidden|uploaded` is an explicit choice for that provider's upload behavior; neither grants access to arbitrary local roots. Do not set a broad SYNTX image root automatically.

The host/user performs OAuth or provider login. Classify each connection separately as installed, configured, authenticated and available. After login or client restart, inspect tools and make a read-only probe in a **new session**; record discovery only from actual evidence. A `status` receipt by itself is not proof of usable paid models. Do not guess credits, account entitlement, models or server rollback.

## 3. Optional project and updates

Choose a persistent workspace outside the installed package. Run `creator_studio.py workspace init WS` and `family_setup.py register-workspace --workspace WS --json`; registration lets the updater check compatibility and active jobs. Ask once whether the user wants automatic updates. If yes, run `family_update.py policy --enabled on --json`; otherwise leave it off. `family_update.py session-start --session-id HOST_SESSION_ID --json` checks once per new session and switches only while idle. Updated local AIMaster/SYNTX/AIEditing packages have backup and rollback receipts. Hosted servers only get fresh connection checks. `family_update.py rollback --component aimaster|syntx|aiediting --json` may return `compatibility_blocked` for newer data; never strip data or overwrite the live workspace. A separate verified `snapshot-workspace`/`restore-workspace --use-rollback` path exists for old-compatible data copies.

Finish with actual installed paths, Python command, setup/status receipts, any login/restart/admin action still needed, and a first `$aimaster` (Codex) or `/aimaster` (Claude Code) prompt. Do not claim a live generation, Windows/Linux Telegram acceptance, or provider OAuth from a synthetic check.
