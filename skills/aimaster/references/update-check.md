# One quiet update check per new chat

Run only when the skill is first invoked in a new conversation. This is an
ordinary short local tool call, not a background service, timer, browser tab,
new agent or global startup hook. Do not announce the check or add progress
messages about it. Do not run it because the host app launched without the
skill being invoked.

## Conversation guard

If this conversation already invoked aimaster, already checked, declined an
update, or is waiting for restart/resume, skip the check. Keep this fact in the
conversation's working context and continuation summary, never a global
“already checked” file that suppresses checks in another new chat. Set the
conversation marker before invoking the helper; failures are not retried in
this conversation. Compaction and resuming the same chat are not new chats.

## Quiet discovery

From the actual installed skill folder, invoke through the host's normal
terminal/tool capability:

```sh
python3 scripts/check_update.py
```

Use an absolute path when the host cwd is elsewhere; follow the skill symlink
to find its installed VERSION. The helper uses a bounded public GitHub request
and considers dated published releases, including this project's prereleases.
It neither updates files nor reads credentials.

- Empty stdout: continue the original task without any remark about versions
  or the check. This can mean no newer version or an unavailable check; do not
  claim “up to date.” If execution tools/network are unavailable, do the same.
- Update JSON: before the creative task, say briefly:
  “Вышла новая версия AI Мастерской — {latest}. Рекомендую обновить перед работой.
  Обновим?” Link the verified official release URL if useful.

Exception: for an `autopilot` project whose brief is already approved —
including approval given in this same request (for example an idea sent with
"делай" / "go") — do not ask; mention the new version only in the final report
([autopilot](autopilot.md)).

Wait for the choice. If declined, continue the original task on the installed
version without repeating the offer. Detecting an update is not permission to
install it. An explicit update request in this chat already supplies that choice.

## Approved update and restart

Use the repository README's safe update procedure: resolve the actual install
clone from the invoked skill; verify the official origin, `main` branch and
clean worktree; use a fast-forward update; preserve local modifications,
personal preferences, guides and projects. On every OS the bundled installer
does exactly this: `python3 scripts/install.py --update --json` (Windows:
`py -3 scripts/install.py --update --json`); read `update.status` and
`update.tag`. It also refreshes installed copies (Windows fallback without
links). Do not reset/stash/overwrite to
force an update. A copied standalone skill without a verified clone needs the
documented installation route; do not guess its repository or replace it blindly.

After updating, read back installed VERSION and the release tag/commit.
Only a confirmed newer installed version counts as success. On a failed or
blocked update, report the specific issue; do not announce success or require
restart as if the update had happened.

After success, say:

> Обновление установлено. Полностью закройте и снова откройте приложение, чтобы
> подгрузилась новая версия. Затем напишите здесь «Продолжай».

End this turn without starting/continuing creative work. Preserve the original
request and pending restart in the conversation for continuation. Do not close
or restart the host automatically. On the user's “Продолжай”, re-read the
updated installed SKILL.md and resume the original task; do not run another
update check in the same chat. Do not claim to have independently verified the
host restart. In a terminal host the equivalent is fully exiting and relaunching
that agent application, then resuming the conversation.
