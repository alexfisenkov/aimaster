# Точка передачи AI Мастерской

Обновлено: 2026-09-22, выпуск `2026.09.22.2`.

## Где мы

- Репозиторий: `https://github.com/alexfisenkov/aimaster`, локальный checkout
  `/Users/AlexFisenkov/Documents/aimaster-public`, ветка `main`.
- Последний выпуск — `2026.09.22.2` (тег и страница выпуска на том же коммите).
  Что в него вошло и что проверено — `RELEASES.md`.
- Все три пункта «Незавершённого» из передачи Codex от 2026-09-21 закрыты:
  локальный E2E транспорта (`scripts/test_telegram_e2e.py`), проверки
  Mini App (`scripts/test_mini_app.py` + браузерный проход), выпуск.

## Что осталось владельцу

1. Ручная проверка в настоящем Telegram: бот отвечает на `/start`, кнопка
   проекта выбирает проект, кнопка «AI Мастерская» открывает Mini App
   с дашбордом, а не с «Не удалось загрузить проект». Юнит-тесты и локальный
   E2E этого не доказывают.
2. Ручная проверка дашборда на компьютере на своём проекте после обновления
   установленной копии.

## Известное и не сделанное

- Telegram Web (браузерная версия) открывает Mini App в iframe; дашборд
  отдаёт `X-Frame-Options: DENY` и `frame-ancestors 'none'`, поэтому там
  Mini App не откроется. Решение по политике безопасности всего дашборда,
  не мелкая правка.
- При ответе 403 экран Mini App пишет «Проверьте соединение», хотя дело
  не в связи. Кнопка «Повторить» есть; текст не уточнялся.
- Windows по-прежнему вне выпуска.

## Ограничения для любого агента

- Не трогать Telegram-токены, Keychain, пользовательские проекты, медиа
  и реальные платные генерации.
- Не считать unit-тесты доказательством работы Telegram WebView.
- Не переписывать историю: без `reset`, `checkout`, `stash`.
- Перед выпуском — набор проверок из «Правила для владельца» в `RELEASES.md`.

## Стартовая проверка

```bash
cd /Users/AlexFisenkov/Documents/aimaster-public
git status --short --branch
git log -3 --oneline --decorate
python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
```
