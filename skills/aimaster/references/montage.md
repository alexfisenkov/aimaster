# Montage

The assembly of `video` and `mixed` projects is a montage on HyperFrames, an
open-source video engine pinned to one version (`studio/montage/engine.json`:
HyperFrames 0.8.75, GSAP 3.14.2). The working montage is
`<project>/montage/current/index.html`. Every build is a new version `vNNN`:
an immutable snapshot in `montage/versions/vNNN/` and an MP4 in
`<workspace>/media/<project-id>/montage/vNNN.mp4`, registered as the project's
`assembly`. Photo projects are not touched: their assembly stays the accepted
image (`assembly set`).

Run the commands as `python3 scripts/creator_studio.py montage …` (the
`python_cmd` of this machine instead of `python3`). Never run the `hyperframes`
CLI, `npx hyperframes` or `npm` yourself: the montage commands start the pinned
engine with its own HOME, telemetry off, the ffmpeg this skill found and
`--json` on every call. Without `--json` HyperFrames 0.8.75 checks for updates
of itself and of its skills on every run (the npm registry, GitHub,
`git ls-remote`), and no environment variable turns that off.

## When to start

After every scene video (or the one-shot video) is chosen, `motion` is approved
and `audio` is approved (an empty audio stage counts). The montage writes into
the `assembly` stage; once `assembly` is approved, every changing command is
refused. A build is local and free: it needs no `grant`, is not a paid action
and needs no confirmation. «Собрать ролик» — in chat or from the dashboard — is
`montage diff` → retell → `montage render` straight away, with no plan and no
confirmation step. The dashboard's current prompt («Собрать → чат» /
«Собрать заново → чат») still calls the build paid and asks to wait for a
confirmation: that text predates the montage; do not wait.

## Engine check

Start with `montage status WS P`. Its `engine`:

- `state: "installed"` — go on.
- `state: "missing"` — `reason` says what is absent (Node.js 22+, HyperFrames
  0.8.75, its render browser or GSAP 3.14.2 with its MotionPathPlugin);
  `install_argv` is the exact install command for this machine as a list of
  arguments and `install` is the same command as one line, for example
  `/usr/bin/python3 /…/skills/aimaster/scripts/install.py --install-deps`.
  Every command that needs the engine refuses with «Монтажный движок не готов:
  … Поставьте его командой: …» naming the same command.

Run it as `install_argv` when your tool starts a program with a list of
arguments (no shell). Otherwise run the line `install` in the shell: it works
as it is in bash or zsh (macOS, Linux) and in Git Bash (the shell of Claude
Code on Windows). On Windows the line has forward slashes and quotes only
around a path that needs them; in PowerShell a line that starts with a quote
needs the call operator in front: `& "C:/Program Files/Python312/python.exe"
"C:/…/install.py" --install-deps`.

The command installs whatever the skill lacks on this machine. HyperFrames
with GSAP, its render browser and the cache of HyperFrames skills go into the
skill's user data folder, not globally. ffmpeg, Node.js 22+ and the optional
helpers cloudflared and git come from winget (Windows) or Homebrew (macOS); on
Linux the report names the commands to run with `sudo` instead. It is free; the
engine is about 330 MB (npm packages about 130 MB, headless Chrome about
190 MB) and takes a few minutes.

- `autopilot`: run the install command yourself, without asking, then
  `montage status` again. Still `missing` — an allowed stop: report
  `engine.reason`, the installer's montage lines and the command
  ([autopilot](autopilot.md#allowed-stops)).
- `guided`: offer it once: «Для монтажа нужен бесплатный движок HyperFrames —
  около 330 МБ, ставится один раз. Установить?». On «да» run it, check
  `montage status`, continue.

## Commands

```bash
creator_studio.py montage draft WS P --expected-revision N [--refresh | --rebuild]
creator_studio.py montage status WS P
creator_studio.py montage diff WS P [--against vNNN]
creator_studio.py montage edit WS P OP [--clip ID] [--at S] [--seconds S] [--duration S] \
  [--value V] [--fade-in S] [--fade-out S] [--text T] --expected-revision N [--expected-model-hash H]
creator_studio.py montage render WS P --expected-revision N [--by agent|owner|autopilot] [--summary "…"]
creator_studio.py montage restore WS P vNNN --expected-revision N
creator_studio.py montage gsap WS P [--plugin NAME]...
creator_studio.py montage open WS P
creator_studio.py montage close WS P
```

Every command prints one JSON object; `--json` is accepted and changes
nothing. A refusal is exit code 3 and one line on stderr,
`creator_studio.py: error: <text>`, in Russian and without absolute paths,
except the engine folder and the install command in «Монтажный движок не
готов»: tell the person what it means in plain words (see Refusals).
`draft`, `edit`, `render` and `restore` need `--expected-revision N` — the
`revision` of the last reply or of `montage status`. `draft` (new and
`--rebuild`), `render` and `restore` return the next revision; `edit` and
`draft --refresh` do not change it. Every reply also carries `project_id`.

| Command | What it does | Reply |
|---|---|---|
| `montage draft` | first draft from the chosen scene videos and sound layers; no titles; copies the HyperFrames skills into the workspace | `revision`, `canvas`, `duration`, `clips`, `current`, `backup`, `skills` |
| `montage draft … --refresh` | replaces the sources of clips whose scene or layer now has another chosen result; other edits stay | `revision`, `refreshed`, `not_refreshed`, `skills` |
| `montage draft … --rebuild` | builds the draft again from the project; the previous `index.html` (with titles and desk edits) goes to `montage/.undo/`, named in `backup` | `revision`, `canvas`, `duration`, `clips`, `current`, `backup`, `skills` |
| `montage status` | engine, skills, versions, current version, layers, stale clips, desk, paths | see below |
| `montage diff` | Russian list of changes since the current version (or `--against vNNN`) | `base`, `changes`, `model_hash`, `unrendered_changes` |
| `montage edit` | one edit, below | `revision`, `op`, `clip`, `model_hash_before`, `model_hash`, `duration`, `receipt` |
| `montage render` | reference check → lint → MP4 (its log checked for network access) → ffprobe → new version → `assembly` | `version`, `asset_id`, `path`, `duration`, `changes`, `warnings` (lint warnings), `revision` |
| `montage restore` | makes an earlier version current again (the replaced `index.html` goes to `.undo/`) | `current_version`, `backup`, `revision` |
| `montage gsap` | copies pinned GSAP and plugins from the engine into `current/assets/` | `version`, `files`, `copied`, `script_tags`, `missing_tags`, `rules` |
| `montage open` | starts the montage desk (HyperFrames Studio) | `state`, `url`, `port`, `pid`, `started_at` |
| `montage close` | stops it | `state` |

`montage render` without `--by` records `autopilot` in an autopilot project and
`agent` otherwise; pass `--by owner` when the build is the person's own
(their desk edits, their «собери»). `--summary` is the version's caption on the
dashboard; without it the caption is made from the changes.

### Reading `montage status`

- `engine`: `state` (`installed` | `missing`), `version`, `wanted`, `reason`,
  `install` and `install_argv` (both `null` when installed).
- `skills`: HyperFrames skills in this workspace — `status` (`found`,
  `missing`, `conflict`, `failed`, `skipped_home`), `version`, `message`.
- `exists` (is there a draft), `current_version`, `versions` (`id`,
  `asset_id`, `created_at`, `by`, `based_on`, `summary`), `canvas`.
- `layers`: once the engine has read the draft, all six, in this order —
  `video` «Видео», `titles` «Титры», `voice` «Голос», `music` «Музыка», `fx`
  «Шумы», `atmos` «Атмосфера»; each has `layer`, `label` and `clips`, each
  clip `id`, `kind`, `start`, `duration`, `media_start`, `volume`,
  `scene_id`, `asset_id`, `text`.
- `model_hash` and `unrendered_changes` (`true` — the montage changed after the
  current version was built); `duration`.
- `stale_clips` (see Keeping the draft current); `desk`; `paths.current`
  (the composition folder) and `paths.output` (the MP4 of the current version).
- `model_error` / `stale_error`: the engine could not read the montage, or the
  project could not be compared with it; the rest of the reply is still valid
  (the screen needs versions and paths in any case).

Without the engine, `model_hash`, `duration` and `unrendered_changes` are
`null` and `layers` is empty; versions and paths are still shown.

## Edit operations

- `move --clip ID --at S` — new start; moving past the end makes the video longer.
- `trim-start --clip ID --seconds S` — cut S seconds off the start; the source
  is cut too (`media_start` moves), exactly as the mouse does in Studio; a
  negative value gives seconds back.
- `trim-end --clip ID --duration S` — new length.
- `split --clip ID --at S` — cut in two at S seconds of the video; the second
  piece is `<ID>-2` (`receipt.new_clip`).
- `delete --clip ID`.
- `volume --clip ID --value V` — 0…3.98, 1 = as recorded; only clips with sound.
- `fade --clip ID [--fade-in S] [--fade-out S]` — soft sound edges, 0 removes
  one; only clips with sound.
- `title-add --text T --at S --duration S` — a title on the «Титры» layer;
  the new id is in `receipt.new_clip`.
- `title-text --clip ID --text T` — new text of a title.
- `undo` — takes back your own last edit (repeat for earlier ones); the reply
  has `op`, `ok` and `restored`. Refused when the montage changed after it, for
  example in the desk, or when there is nothing to take back.

Clip ids come from `status.layers`: videos `v-1`, `v-2`… in scenario order,
titles `t-1`, `t-2`… as they are added, sound `a-voice`, `a-music`, `a-fx`,
`a-atmos`, split pieces `<id>-2`. Times are seconds of the finished video.

## What the draft contains

- One video clip per scene, in scenario order, inside its scene's window and
  never longer than its source; the chosen and accepted result of each
  position (not the newest file). One-shot: one clip for the whole video.
- Sound layers voice / music / fx / atmos from 0 s, volumes 1.0 / 0.3 / 0.8 /
  0.5; music and atmosphere fade out over 1 s. Scene videos play at 0.3 under
  sound layers and at 1.0 without them; a video without sound stays muted.
- Transitions: the next clip fades in over 0.4 s (CSS `@keyframes`); the
  sound of the clips on both sides of a cut fades over 0.4 s.
- The frame size of the first video (even sides), otherwise 1080×1920.
- Media hard-linked (or copied) into `current/assets/`, named by asset id.
- Local GSAP 3.14.2 from the engine (`assets/gsap.min.js`,
  `assets/MotionPathPlugin.min.js`) and one paused timeline
  `window.__timelines["main"]` as long as the root's `data-duration`. It is
  there for the desk: without a timeline, Studio 0.8.75 plays the preview
  after an edit by seeking and without sound. The root never carries
  `data-no-timeline`.
- Root markers `data-am-scenes`, `data-am-gen-mode`, `data-am-layers` and clip
  markers `data-am-*`: the project structure at draft time, used to find stale
  clips. Keep them.
- The bundled font «AM Inter» (Inter, OFL-1.1, in `current/assets/fonts/`,
  local `@font-face`); no titles; no external URLs. A build works without the
  network and looks the same with and without it.

## Titles and captions

Only through `montage edit title-add` / `title-text`; the draft has none:
a scene's text describes the shot, it is not a line to show.

- `guided` — when the person asks for them.
- `autopilot` — where the meaning needs them: a name, a place, a date, a line
  the voice does not say. Short, one idea per title, not over faces;
  otherwise leave the picture clean. Never copy scene texts into titles as
  they are.

Titles are white bold text on a dark band in the lower part of the frame
(`.am-title`).

## Font

All text is set in «AM Inter»: `.am-title` and the page body already use it.
In any CSS you write, the family is `font-family: "AM Inter", sans-serif` —
never another family, never a bare `sans-serif`, never a font link or
`@import`. HyperFrames downloads any family that is not declared locally from
Google Fonts or substitutes a system font; a render whose log shows either is
refused and leaves no version.

## GSAP and animations

Prefer CSS `@keyframes` on the clip element: the runtime seeks CSS animations
frame by frame. When an effect needs GSAP (animations from the HyperFrames
skills):

1. `montage gsap WS P [--plugin SplitText]` copies the plugin from the
   installed engine into `current/assets/`. Put every tag from `missing_tags`
   into `<head>` after `assets/gsap.min.js`. A plugin name is the file name in
   `gsap/dist`.
2. Add the animations into the existing timeline script of the draft (the
   inline `<script>` after the root that registers
   `window.__timelines["main"]`). Never register a second `main` and never add
   a second inline GSAP script: Studio reloads the preview after an edit only
   with one.
3. The timeline stays paused (`gsap.timeline({ paused: true })`) and not
   shorter than the video; never add `data-no-timeline` to the root.
4. Never a CDN link: the build check refuses external scripts; local ones are
   fine.

The reply's `rules` repeat these points in Russian.

## HyperFrames skills

The ten core HyperFrames skills of the pinned version live in the workspace,
not in your global skills: `<workspace>/.claude/skills/<name>/` for Claude Code
and `<workspace>/.agents/skills/<name>/` for Codex (`hyperframes`,
`hyperframes-animation`, `hyperframes-audio`, `hyperframes-cli`,
`hyperframes-core`, `hyperframes-creative`, `hyperframes-keyframes`,
`hyperframes-registry`, `hyperframes-studio`, `media-use`). `workspace init`
and `montage draft` copy them from the cache next to the engine and mark them
(`.aimaster-install.json`); a folder with the same name that aimaster did not
put there is left alone (`conflict`). They are visible when the agent works in
the workspace folder.

Use them only for what the draft does not do: animated titles, intros,
effects. This skill leads the montage: never start a new HyperFrames project,
never run `hyperframes init` or a HyperFrames skill installer, never install
workflow skills (`figma`, `slideshow`, …), never reference files outside
`montage/current/`. Their advice to load GSAP or fonts from a CDN is
overridden by Font and GSAP above.

## Guided flow: what the person sees

1. `montage status` (engine), `montage draft`, `montage render`. Say: «Черновой
   монтаж готов — версия v1, 0:15. Он на экране «Сборка». Поправить можно
   словами здесь или мышью на монтажном столе». The dashboard's «Сборка»
   shows the current version as the final video; `paths.output` is the file.
2. Wait. Words in chat → `montage edit` (one command per edit; name what
   changed). Mouse → `montage open`; open `url` in a new tab through the host
   capability, or give the link: «Монтажный стол открыт: <url>. Правки
   сохраняются сами; интерфейс стола на английском. Когда закончите —
   напишите «собери»».
3. On «собери» / «Собрать ролик» or the dashboard prompt: `montage diff`,
   retell the changes, `montage render` straight away (`--by owner` for the
   person's desk edits) — free and local, no plan and no confirmation — then
   show the new version: «Готова версия v2: …».
4. «Сделай текущей v1», «верни прошлую» → `montage restore`. Versions are never
   deleted; an open desk picks up the restored montage by itself.
5. Approval stays the person's: `stage approve` only on their word. When the
   desk is no longer needed, `montage close`.

## Autopilot flow

`montage status` → install the engine if it is missing (Engine check) →
`montage draft` → titles only where the meaning needs them → `montage render`
→ review: duration, frame size, sound and the absence of network access are
checked by the render itself; look at frames when a viewer is available,
otherwise say the visual check was not performed → a visible defect: fix with
`montage edit`, render again → `stage approve` → final report (versions built,
titles added and why, whether the engine was installed). No questions.

## Retelling a diff

`montage diff` returns ready Russian lines, for example «клип сцены 1 «Сад»:
начало обрезано на 0,5 с» or «добавлен титр «…» с 0:00.5». Retell them
briefly, grouped by scene, in plain words; never paste ids or file names.
Empty `changes` means nothing changed since the current version: say so and do
not build a duplicate. If the person edited in the desk, say that you took
their edits as they are.

## Montage desk

`montage open` starts HyperFrames Studio on 127.0.0.1 for this project only
and returns `url`; a second `open` returns the same desk. Edits save to
`current/index.html` by themselves and Studio picks up edits made by
commands. Before your own edits while the desk may be open, read
`montage status` and pass its `model_hash` as `--expected-model-hash`: a
concurrent mouse edit then refuses your edit instead of being overwritten.
`montage close` stops Studio and its browser; nothing stops the desk on its
own yet. `montage status` → `desk.state` shows `open` or `closed` (with a
`note` when a recorded desk no longer answers). `open`, `close` and `status`
add `forgotten` when the recorded process turned out not to be this desk: it
is left alone and only the record is dropped.

## Keeping the draft current

After the person chooses another scene video or sound, `status.stale_clips`
lists the clips (`clip`, `layer`, `scene_id`, `asset_id`, `current_asset_id`,
`reason`, `cause`, `audio_change` — the last one is filled only in the
`refreshed` / `not_refreshed` lists of `--refresh`):

- `reason: null` — `montage draft --refresh` replaces the source; the other
  edits stay;
- `reason: "нет принятого"` — the scene or layer has no accepted result now:
  the person has to choose one first;
- `reason: "нужен --rebuild"` (`cause`: `scene_added`, `scene_removed`,
  `gen_mode`, `layer_added`) — `montage draft --rebuild`. It drops titles and
  desk edits (the old `index.html` stays in `montage/.undo/`): in `guided` say
  so and rebuild on their word; in `autopilot` rebuild and add the titles again.

## Refusals and what to tell the person

| Refusal (start of the text) | What it means, what to do |
|---|---|
| «Монтажный движок не готов: …» | Engine check above |
| «видео сцены … не принято» / «общее видео (one_shot) не принято» | choose the videos first; the montage takes only accepted results |
| «черновик уже есть: …» | use `--refresh` or `--rebuild` |
| «черновика ещё нет: сначала montage draft» | make the draft |
| «проект изменился — обновите номер ревизии: сейчас N» | repeat with that revision |
| «монтаж изменился с тех пор, как вы его читали …» | the desk changed it: read `montage status`, repeat the edit |
| «монтаж поменяли во время сборки …» / «монтаж поменяли, пока сборка готовила его …» | a desk edit landed during the build: no version, build again |
| «Монтаж нельзя собрать: …» / «Проверка монтажа (lint) нашла ошибки: …» | name the clip and the error, fix it with an edit, build again |
| «Сборка обращалась в сеть или к чужому шрифту: …» | a foreign font or a CDN script: Font and GSAP rules, then build again |
| «Собранный ролик не прошёл проверку: …» / «Сборка не удалась: …» | no version; `montage/.logs/render-vNNN.log` has the engine log |
| «Ролик больше 2 ГБ — такой файл студия не примет; сократите монтаж» | shorten the video (fewer or shorter clips), build again: «Ролик вышел больше 2 ГБ — укорочу монтаж и соберу снова» |
| «отменять нечего» | there is no edit of yours to take back |
| «после этой правки монтаж меняли …» / «нет отметки о состоянии после последней правки …» / «отметка о последней правке повреждена …» | `undo` would erase someone else's changes (the desk): make the opposite edit instead: «Отменить не могу — после моей правки монтаж меняли на столе. Поправлю обратной правкой» |
| «нет версии vNNN» | that version does not exist: list `versions` from `montage status` and name the real ones |
| «в папке монтажа есть ссылки на другие места: …; монтаж не трогаю» / «в папке монтажа лежит montage/current/ffmpeg …» | the montage folder holds links or a program someone put there; nothing is touched until it is gone. Never delete it yourself: «В папке монтажа проекта лежат посторонние ссылки (или программа ffmpeg) — пока они там, монтаж не работает. Уберите их, и я продолжу» |
| «папка montage проекта — ссылка на другое место; монтаж не трогаю» | the whole `montage` folder is a link: «Папка монтажа этого проекта — ссылка на другое место, поэтому монтаж её не трогает. Замените ссылку обычной папкой (или уберите её), и я соберу черновик заново» |
| «у фото-проекта монтажа нет …» | photo: `assembly set` |
| «--summary: дашборд не показывает текст с …» | the caption has a service word: rephrase it |
| «Монтажный стол не запустился за 30 с: …» / «монтажный стол этого проекта сейчас открывают или закрывают …» | try `montage open` again in a minute; `montage/.logs/desk.log` has the details |
| «этап «assembly» уже одобрен — montage его не меняет» | the assembly is accepted and the montage no longer changes: say «Сборка уже принята — монтаж этого ролика больше не меняется» |

## Rules

- The reference check and `lint` run before every build; a failure leaves no
  version and keeps the current one.
- A render whose log shows network access or a substituted font is refused
  and leaves no version.
- Never edit or delete anything in `montage/versions/` or a version's MP4.
- Keep all media inside `montage/current/` (`assets/`); no links, no absolute
  paths, no `../`.
- A version larger than 2 GB is refused.

## Known limitations

- Studio's interface is English only.
- Studio's page sends usage analytics to its developers (PostHog) unless the
  key `hyperframes-studio:telemetryDisabled` is set to `1` in the page's local
  storage before it first loads; a desk opened from chat does not set it. The
  engine's own telemetry is off.
- The engine is kept offline by `--json` on every call, not by a setting:
  with it, render, lint, timeline edits and the desk make no outbound request
  and start no `git` (checked through a logging proxy). The desk page in the
  browser is outside that (Studio's analytics above).
- The engine is pinned: a newer HyperFrames is used only after a skill
  release. After a skill update that pins another version, `montage status`
  says `missing` («стоит HyperFrames …, нужен …») and `engine.install` brings
  the engine to the pin.
- The desk is not stopped by idleness or when the dashboard stops: close it
  with `montage close`.
- The studio reads a version's MP4 whole to check it: large videos register
  slowly.
