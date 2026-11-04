# AIMaster

AIMaster turns a text or voice idea into a project with a script, shot plan, selected images and video, and a portable collection of materials. A final MP4 is optional. The local dashboard opens the exact project and can submit actions through an explicitly running Codex or Claude controller. You can work in chat, in the dashboard, or through the optional Telegram Mini App. Projects, personal guides and library stay in your own workspace outside the installed skill.

Python 3.11+ is required. The package uses Python's standard library and supports macOS, Linux and native Windows. Host login and provider accounts are separate. Generations can use SYNTX, Higgsfield, Magnific or fal when those routes are actually available; each selected service and model is checked live before use. [Русская инструкция](README.ru.md).

## Install

Give your local coding agent this prompt:

```text
Install AIMaster from https://github.com/alexfisenkov/aimaster. Read INSTALL_WITH_AGENT.md first. Install free prerequisites through the official OS package manager where permitted, install the skill for my agent, then run its family_setup.py setup --install-deps --json from the actual installed skill folder. Show me any OS/admin/login/OAuth step that only I can complete. Do not invent successful authentication, perform a paid generation, overwrite unrelated MCP entries, or put secrets in chat. Read back the installed paths and setup status. Ask me whether to turn on automatic updates once.
```

If Node/npx is available, the standalone skill-folder command is:

```sh
npx skills add https://github.com/alexfisenkov/aimaster/tree/main/skills/aimaster --skill aimaster -g -a codex -a claude-code
```

Find the installed `<skill>` directory from the command's output, then run `python3 <skill>/scripts/family_setup.py setup --install-deps --json` (use `py -3` on Windows if that is the Python command). This setup can be partial when an OS package manager, host login or provider OAuth needs you. A Git clone plus `skills/aimaster/scripts/install.py --install-deps --json` remains a supported fallback; [agent procedure](INSTALL_WITH_AGENT.md) gives the exact steps. Installation of a connector does not prove account access or a usable model. The setup includes all four provider connectors and the AIEditing workshop; it preserves unrelated MCP settings.

In Codex start with `$aimaster Make a short video about …`; in Claude Code use `/aimaster`. Choose guided or fully automatic. For a video, choose whether you want a finished montage or just a portable set of selected materials. The agent creates the project, opens the exact dashboard URL, and records choices there. Full automatic mode asks for a short brief approval, shows a spending warning once, then proceeds without routine follow-up prompts or a media limit. Guided paid buttons authorize one displayed action. Supplied media is kept as input and is not regenerated unless you request that.

## Updates and recovery

Automatic updates are an explicit one-time opt-in. On a new idle session, AIMaster checks local AIMaster, SYNTX and AIEditing versions; hosted providers are checked for availability. Working packages and host configuration have backup/rollback receipts. A rollback can be blocked if older code cannot read newer project data; in that case keep current data and restore an older compatible snapshot to a separate folder. Personal projects, guides, library and editing styles are outside installed packages. Hosted provider servers cannot be rolled back by AIMaster. See [architecture](docs/architecture.md) and [release notes](RELEASES.md).

The local and synthetic acceptance harness does not prove account login, credits, native operation on every OS or final publication. Check those in the target environment before relying on them.

Монтажный стол opens an editable local composition when montage is selected.
The managed opener disables «анонимной статистики Studio» in that browser
session; opening its raw URL directly may retain the Studio default. The
separate local engine runs with telemetry disabled.
