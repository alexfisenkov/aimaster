# Оболочка дашборда v2 — волна 1

Контракт: `docs/superpowers/specs/2026-09-22-dashboard-redesign-design.md`.
Здесь сделаны ядро и экран «Кадры»; просмотрщик и экраны Сценарий / Видео /
Звук / Сборка — волна 2. Ничего из v1 не удалено.

## Вход

`static/app.js` — развилка: по умолчанию `ui/v2/boot.js` → `bootV2()`;
старая оболочка целиком лежит в `static/app-v1.js` и открывается якорем
**`#ui=v1`**. `?ui=v1` тоже распознаётся, но сервер пускает на `/` ровно
один параметр запроса — только `project` (`studio/http_app.py`, `_path`), —
и на `?project=…&ui=v1` отвечает 400. Якорь серверу не уходит и работает.

## Модули

Чистые (без DOM, их и покрывают тесты):

- `variants.js` — `orderByParent(records, idField="version_id")`,
  `resultGroups(records)`, `promptGroups(records)` → `Map<groupId, versions[]>`,
  `selectedResultVersion(project, {sceneId, slot, referenceId, layer})`,
  `variantState(version)` → `selected|new|rejected|hidden|retired`,
  `versionsMadeBy(promptVersionId, results)`.
- `counts.js` — `variantCounts(project, target)` → `{versions, total, selected,
  index, groupId, position}`; `variantStatus(counts, {source, hasAsset})` → одна
  из четырёх формулировок спецификации.
- `screen-map.js` — `SCREENS`, `SCREEN_LABELS`, `SCREEN_HINTS`,
  `screensFor(type)`, `screenForStage(stage)`, `stagesForScreen(screen)`,
  `pathState(project)`, `primaryAction(project)` → `{label, stage, enabled, remaining[]}`.
- `unresolved.js` — `unresolvedItems(project, stage)` → строки «осталось решить».
- `chat-prompts.js` — `addReference(kind, project, revision, {sceneId})`,
  `moreVariants({project, revision, sceneId, referenceId, slot, promptVersion,
  selectedVariant})`, `uploadFrame({project, revision, sceneId, slot})`,
  `editPrompt({project, revision, sceneId, referenceId, promptVersion, what})`,
  `toggleSceneReference({project, revision, sceneId, reference, include})`,
  плюс `projectRef`/`sceneRef`. Каждая возвращает `{title, prompt, attachmentHint?}`.

С DOM:

- `dom.js` — `el`, `chatButton`, `thumb`, `clock`, `openViewer`.
- `path-nav.js` — `renderPath(project, {current})`, `requestScreen(screen, trigger)`.
- `reference-shelf.js` — `SHELF_GROUPS`, `shelfGroups(project)`, `renderShelf(project, revision)`.
- `scene-zones.js` — `inFrameZone`/`localZone`/`videoReferenceZone`/`framesZone`
  `(project, revision, scene)`.
- `scene-row.js` — `renderSceneRow(project, revision, scene, position)`,
  `scenePromptLine(project, scene, kind)`, `scenesInOrder(project)`.
- `screen-frames.js` — `renderFramesScreen(root, {state, readOnly, screen})`.
- `footer.js` — `renderFooter(snapshot, {screen})`: одна главная кнопка
  (direct `approve` стадии через `card-forms.buildSimpleButton`) и строка
  «Осталось решить». На пройденном экране кнопки нет вовсе.
- `shell.js` — `renderShellV2(root, state)`, `setViewedScreen`, `currentScreen`.
- `boot.js` — `bootV2()`: стор, контроллер и fetch те же, что у v1.

## События

- `studio:screen-viewed` · `{screen, trigger}` — путь просит показать экран;
  слушает `boot.js`.
- `studio:open-viewer` · `{version: 2, target: {kind: "scene"|"reference"|"layer"|
  "assembly", id}, tab: "frames"|"video"|"history", slot, trigger}` — просьба
  открыть просмотрщик. Сейчас её **никто не обрабатывает**: слушатель v1
  (`ui/viewer.js`) пропускает всё, у чего `detail.kind` не `image|video|audio`,
  а v2-событие такого поля не имеет — клик просто ничего не открывает.

## Что делать волне 2

1. Написать `viewer.js` и подписать его в `bootV2()` на `studio:open-viewer`
   с проверкой `detail.version === 2`; слушатель v1 не трогать.
2. Заменить временные рендереры v1 в `SCREEN_RENDERERS` (`shell.js`) на свои
   `screen-scenario.js`, `screen-video.js`, `screen-audio.js`, `screen-assembly.js`
   с сигнатурой `(root, {state, readOnly, screen})` и вызовом
   `renderFooter(snapshot, {screen})` внизу.
3. Брать готовые тексты для чата из `chat-prompts.js`, а счёт вариантов —
   из `counts.js`; заново не считать.

## Тесты

```
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
```

`snapshot.fixture.mjs` — срез живого проекта владельца (revision 62): менять
его руками не надо, а `projectWith({...})` даёт копию с правками для теста.
