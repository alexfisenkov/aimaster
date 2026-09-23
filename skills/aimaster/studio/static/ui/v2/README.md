# Оболочка дашборда v2 — волна 1

Контракт: `docs/superpowers/specs/2026-09-22-dashboard-redesign-design.md`.
Волна 1 — ядро и экран «Кадры». Волна 2 — просмотрщик и остальные четыре
экрана: Сценарий, Видео, Звук, Сборка. Ничего из v1 не удалено.

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
  `pathState(project)`, `primaryAction(project)` → `{label, stage, enabled, remaining[], items[]}`,
  `projectFinished(snapshot)`, `projectStatus(snapshot)` → `{text, tone: "warn"|"ok", count}|null`
  (пилюля шапки), `screenHeading(project, screen)` → `{kicker, title, hint}`.
- `unresolved.js` — `unresolvedEntries(project, stage)` → `{label, target: {kind, id}|null,
  tab, slot}[]` (каждый пункт открывает просмотрщик); `unresolvedItems` — те же пункты строками.
- `responsive.js` — `isPhone()` (`(max-width: 759px)`), `onViewportChange(cb)` → отписка.
- `scenario-model.js` — `scriptVersions(project)` → `{versions, activeIndex}`,
  `storyboardRows(project)`, `activeBlockText(scene)`.
- `video-model.js` — `clipStatus(project, scene)` и `continuationLine(project,
  scene)` → `{text, warn}`: откуда берётся движение сцены.
- `audio-model.js` — `AUDIO_LAYERS` (голос, музыка, эффекты, атмосфера —
  человеческий порядок, не серверный) и `audioTiles(project)`.
- `screen-prompts.js` — тексты для чата, нужные только экранам:
  `changeGenMode`, `editScenario`, `reopenScenario`, `assembleFinal`.
- `chat-prompts.js` — `addReference(kind, project, revision, {sceneId})`,
  `moreVariants({project, revision, sceneId, referenceId, slot, layer,
  promptVersion, selectedVariant})`,
  `uploadFrame({project, revision, sceneId, slot, layer, referenceId})`,
  `editPrompt({project, revision, sceneId, referenceId, promptVersion, what})`,
  `toggleSceneReference({project, revision, sceneId, reference, include})`,
  плюс `projectRef`/`sceneRef`. Каждая возвращает `{title, prompt, attachmentHint?}`.

С DOM:

- `dom.js` — `el`, `chatButton`, `thumb`, `clock`, `openViewer`, плюс
  возврат фокуса после перерисовки: `cardFocusNote()`, `restoreCardFocus
  (zone, note)`, `dropCardFocusNote()`. Листок `studio:card-focus-pending`
  вычёркивается только когда фокус поставлен: зоны две (доска и оверлей),
  и спросивший первым иначе забрал бы чужой.
- `path-nav.js` — `renderPath(project, {current})`, `requestScreen(screen, trigger)`:
  степпер в шапке; будущие шаги — `span` с причиной в `title`.
- `sheet.js` — `openSheet({title, items: [{label, hint?, tone?, onSelect}], returnFocus})`
  → `close()`: нижняя шторка с ловушкой фокуса, `Esc` ловит на `window` раньше просмотрщика.
- `toast.js` — `showToast(text)`: 2,6 с снизу по центру; при открытом `<dialog>` живёт в нём.
- `reference-shelf.js` — `SHELF_GROUPS`, `shelfGroups(project)`, `renderShelf(project, revision)`.
- `scene-zones.js` — `inFrameZone`/`localZone`/`videoReferenceZone`/`framesZone`
  `(project, revision, scene)`.
- `scene-zones-video.js` — `clipZone`/`continuationZone` `(project, scene)`:
  правые зоны той же строки сцены на экране «Видео».
- `scene-row.js` — `renderSceneRow(project, revision, scene, position, {mode})`,
  `scenePromptLine(project, scene, kind)`, `framePromptKind(project, scene)`,
  `scenesInOrder(project)`. `mode` — `"frames"` (четыре зоны) или `"video"`
  (три). Промпт в строке берётся по месту, а не по экрану: на «Видео» —
  `motion`, на «Кадрах» — запланированный кадр (`first`/`last`) или
  изображение фотопроекта; кадров не запланировано — строки нет вовсе.
- `video-thumb.js` — `videoThumb(assetUrl, label)`: миниатюра клипа
  `<video preload="metadata">`; `<img>` на mp4 отдаёт битую плитку.
- `more-menu.js` — `moreMenu(items)`: «···» из `<details>`, всё редкое с экрана.
- `screen-frames.js` — `renderFramesScreen(root, {state, readOnly, screen})`.
- `screen-scenario.js` · `screen-video.js` · `screen-audio.js` ·
  `screen-assembly.js` — `render*Screen(root, {state, screen})`, внизу каждого
  `renderFooter(snapshot, {screen})`.
- `footer.js` — `renderFooter(snapshot, {screen})`: одна главная кнопка
  (direct через `card-forms.buildSimpleButton`), чипсы «Осталось решить»
  (на телефоне — плашка со шторкой), на пройденном экране — «Вернуться к
  шагу …». Экран кладёт подвал в свою область, `shell.js` переносит его в
  липкую полосу на всю ширину.
  У сценария свой тип действия `approve-scenario`, у остальных пяти стадий —
  общий `approve` с именем стадии; сервер различает их по `target_id`
  (`decision_stages.MILESTONE_TARGETS` вычитает `scenario`). На пройденном
  экране кнопки нет вовсе.
- `viewer.js` — `attachViewerV2(getSnapshot)`, `repaintViewer()`, `closeViewer()`:
  тёмный оверлей на весь экран, вкладки, ловушка фокуса, `Esc`/✕, `←`/`→`,
  свайп и блокировка прокрутки страницы.
- `viewer-canvas.js` — чистые `filmstrip(counts)`, `slotOptions(project, scene)`,
  `canvasCaption({index, total, mark, promptLabel})`, `ownFileStrip(assetUrl,
  caption)`, `promptOfVariant(version, promptVersions)`; с DOM —
  `renderCanvas`, `renderSlotSwitch`.
- `viewer-prompt.js` — чистые `promptPlace(project, target, {tab, slot})`,
  `promptVersions(project, place)`, `splitTags(text)`, `promptMeta(version,
  index)`; с DOM — `renderPromptPanel`. Теги промпта собираются из
  `textContent`: разметку из текста страница не исполняет.
- `viewer-zones.js` — `renderViewerZones(project, revision, scene)`: те же
  зоны из `scene-zones.js`, тёмный вид задаёт `styles/v2/viewer.css`.
- `decide.js` — чистые `resultTargetId(version)`, `directActionsFor({allowedActions,
  currentStage, collection, version})`, `directActionRequest(actionType, version,
  revision, {comment})` и ряд «две кнопки и «···»» `renderDecideRow(context)`.
  Шесть прямых действий идут через `ui/actions.js`; `vary`/`regenerate` не
  показываются никогда. Решение предлагается только на стадии, которой
  принадлежит коллекция результата (`studio/decision_cards.STAGE_COLLECTIONS`).
- `shell.js` — `renderShellV2(root, state)`, `setViewedScreen`, `currentScreen`,
  `metaLine`. Рисует шапку (мета, название, пилюля, «💬 Агент», степпер) и
  **заголовок экрана** (kicker, H1, подсказка) — экраны свои заголовки не
  рисуют; справа от заголовка пустой `[data-hook="v2-screen-aside"]` для
  управления экрана. Стили каркаса — `styles/v2/shell.css`.
- `rail-drawer.js` — `createRailDrawer()`: на десктопе панель стоит в сетке
  и сворачивается «‹» (выбор в `localStorage`), на телефоне выдвигается
  поверх с затемнением, `Esc` и ловушкой Tab. `body[data-rail]` —
  `docked|collapsed|open|closed`. Список внутри рисует `ui/rail.js`.
- `boot.js` — `bootV2()`: стор, контроллер и fetch те же, что у v1, плюс
  `ensureStylesheet(href)` — `index.html` принадлежит оболочке, поэтому
  `styles/v2/viewer.css` подключается отсюда тегом `<link>`. Здесь же
  адресная строка (`?project=` через `history.pushState`, `popstate`) и
  память о последнем проекте в `localStorage`: голый `/` открывает его,
  а если такого проекта уже нет — экран выбора с открытой панелью.

## События

- `studio:screen-viewed` · `{screen, trigger}` — путь просит показать экран;
  слушает `boot.js`.
- `studio:open-viewer` · `{version: 2, target: {kind: "scene"|"reference"|"layer"|
  "assembly", id}, tab: "frames"|"video"|"audio"|"history", slot, trigger}` —
  просьба открыть просмотрщик; слушает `viewer.js` (только `version: 2`).
  Слушатель v1 (`ui/viewer.js`) пропускает всё, у чего `detail.kind` не
  `image|video|audio`, а у v2-события такого поля нет — оба висят рядом и
  не спорят за одно событие. Набор вкладок зависит от `target.kind`:
  сцена — «Кадры · Видео · История», референс — «Картинка · История»,
  слой звука — «Звук · История», сборка — «Ролик · История».

## Что делать волне 2

1. ~~Написать `viewer.js` и подписать его в `bootV2()` на `studio:open-viewer`~~
   — сделано, слушатель v1 не тронут. Вкладка «Звук» и одобренная сборка
   проверены живьём на синтетических `zz-audio-check` и `zz-assembly-check`
   в копии workspace. Живьём не проверен только переключатель слотов
   «первый / последний кадр»: сцен с кадрами нет ни в одном проекте —
   он покрыт тестами (`viewer-canvas.test.mjs`), но не глазами.
2. ~~Заменить временные рендереры v1 в `SCREEN_RENDERERS` (`shell.js`)~~ —
   сделано: все пять экранов свои, `step-*.js` из v2 больше не вызываются.
   Сами файлы v1 не удалены: они живут в `static/app-v1.js` до приёмки.
3. Брать готовые тексты для чата из `chat-prompts.js`, а счёт вариантов —
   из `counts.js`; заново не считать.

## Что осталось известным долгом

- У сборки нет группы вариантов: `assembly` — один объект `{status,
  asset_id, summary}`. Просмотрщик показывает его одной плиткой
  «Финальный ролик» (`soloStrip`), а принимается финал только кнопкой
  подвала: своей коллекции результатов у `assembly` на сервере нет
  (`decision_cards.STAGE_COLLECTIONS`). Скачивания пока нет — оно
  отдельной работой.
- Пока решение в полёте, просмотрщик не перерисовывается вовсе: ни
  листание, ни вкладки, ни фоновый опрос. Это цена того, что ряд кнопок
  гасит `submitAction`, а не сам просмотрщик; если когда-нибудь
  понадобится живая доска под открытым решением, гасить придётся здесь.

## Тесты

```
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
```

`snapshot.fixture.mjs` — срез живого проекта владельца (revision 62): менять
его руками не надо, а `projectWith({...})` даёт копию с правками для теста.
