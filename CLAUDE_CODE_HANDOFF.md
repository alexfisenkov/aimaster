# Передача AI Мастерской в Claude Code

Дата передачи: 2026-09-21

## Точка остановки

- Репозиторий: `https://github.com/alexfisenkov/aimaster`
- Локальный checkout: `/Users/AlexFisenkov/Documents/aimaster-public`
- Ветка: `main`
- HEAD: `0df65d27253d561eadc4acef9a139d00d6487bf4`
- Рабочее дерево чистое.
- Локальная `main` опережает `origin/main` на один коммит: callback-фикс ещё не опубликован.
- Последний опубликованный выпуск: `2026.09.21.7`.
- Установленный у пользователя клон в `/Users/AlexFisenkov/.local/share/aimaster` был обновлён до `.7`; callback-фикс туда ещё не устанавливался.

## Что уже сделано

- macOS Telegram transport, owner pairing, локальный Codex bridge и Mini App gateway.
- Keychain timeout: зависший вызов macOS Keychain прекращается через 5 секунд, затем используется защищённый fallback-файл `0600`.
- Telegram navigation menu, выбор проектов, разделы сценария/промптов/результатов/чата.
- Callback-фикс в `0df65d2`: `project:<id>` теперь выбирает проект; старые и неизвестные callback не останавливают polling loop.
- Добавлены regression-тесты для callback round-trip, меню, project actions и malformed/legacy callbacks.

## Проверено

- `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'` — 56 тестов, OK.
- До callback-фикса опубликованный `.7` прошёл `compileall`, `node --check`, `git diff --check` и `quick_validate.py`.
- Реальная Telegram UI-проверка выполнялась в `/Applications/Telegram.app`: бот отвечал, проекты и кнопка AI Мастерская отображались. Нажатие Mini App после последней локальной правки не подтверждено в Telegram WebView.

## Незавершённое

1. Завершить local E2E без платных генераций:
   - transport стартует;
   - callback `project:<id>` выбирает проект;
   - malformed callback не роняет polling;
   - следующий update после ошибки обрабатывается;
   - Mini App gateway остаётся живым.
2. Проверить Mini App bootstrap/auth:
   - valid `Telegram.WebApp.initData` пропускает `/api/projects`;
   - отсутствующий или невалидный `initData` даёт полноэкранную диагностику, не белый экран;
   - 403, network failure и недоступный Telegram SDK дают видимый retry/error state;
   - неавторизованный `/api` возвращает 403.
3. Если проверки зелёные, подготовить следующий выпуск (`2026.09.21.8` или следующий согласованный суффикс): обновить оба `VERSION`, `README.md`, `RELEASES.md`, затем отдельно согласовать push/tag/release.
4. Обновить установленный клон только после публикации и затем полностью перезапустить Codex/transport.

## Ограничения

- Не трогать Telegram-токены, Keychain, пользовательские проекты, медиа и реальные платные генерации.
- Не считать unit-тесты доказательством работы Telegram WebView.
- Не пушить и не создавать GitHub release до прохождения local E2E и Mini App checks.
- Windows пока вне этого выпуска.

## Стартовая проверка

```bash
cd /Users/AlexFisenkov/Documents/aimaster-public
git status --short --branch
git log -3 --oneline --decorate
python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
```

Сначала прочитай `AGENTS.md`, этот файл и `RELEASES.md`. Не переписывай историю и не делай `reset`, `checkout` или `stash`.
