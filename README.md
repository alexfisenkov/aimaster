# AI Мастерская / aimaster

`aimaster` — навык для AI-агента с локальным дашбордом «AI Мастерская».
Он ведёт фото- или видеопроект от идеи и сценария до материалов для монтажа.
Агент работает в вашем чате, а дашборд показывает сценарий, карточки, промпты
и результаты. Это не отдельная нейросеть.

Предварительный публичный выпуск. Новый путь установки из GitHub ещё не
проверялся на чистых машинах; установку и первый запуск пользователь проходит сам.

Репозиторий — публичная упаковка навыка. Личные проекты, медиа и собственная
база знаний должны жить в постоянной папке вне Git-клона. Сервис генерации,
провайдеры и их авторизация настраиваются отдельно. Telegram-controller —
необязательный контроллер, а не LLM и не ASR.

## Установка — выберите один путь

### Вариант 1. Попросить своего агента

Скопируйте prompt ниже целиком и отдайте его своему агенту. Подробные
инструкции, которые агент должен прочитать, находятся в
[INSTALL_WITH_AGENT.md](INSTALL_WITH_AGENT.md).

```text
Установи публичный навык aimaster из https://github.com/alexfisenkov/aimaster.
Сначала прочитай https://github.com/alexfisenkov/aimaster/blob/main/INSTALL_WITH_AGENT.md
и выполни только описанные там безопасные шаги. Определи мой целевой runtime
(Codex или Claude Code); спроси меня только если это неоднозначно. Проверь
наличие Git и Python 3.11+ и установи только недостающие бесплатные зависимости
через официальный пакетный менеджер моей ОС. Если отсутствует сам необходимый
менеджер пакетов, подготовь его установку из официального источника и выполни
её в рамках разрешений среды; для WSL сначала согласуй изменение системы.
Не переустанавливай уже найденное,
не отключай защиты, не угадывай пароль sudo и не печатай секреты. Если нужен
админский пароль, перезагрузка или вход в аккаунт, попроси меня выполнить только
этот шаг и продолжи после моего ответа.

Клонируй репозиторий в постоянный $HOME/.local/share/aimaster (или явно
согласованный мной путь), а в каталог навыков целевого runtime установи только
папку skills/aimaster через безопасную символическую ссылку; не клонируй
репозиторий внутрь папки навыка и не перезаписывай существующие targets.
Проверь origin уже существующего клона перед повторным использованием.

Не покупай ничего, не настраивай Telegram/MCP, не запускай генерацию и не
запрашивай логин AI-клиента автоматически. После установки остановись, сообщи
путь и дай мне первый пример запроса. Не запускай creative/media jobs.
```

После установки навык вызывается в Codex как `$aimaster`, а в Claude Code как
`/aimaster`. Это не обещание появления slash-команды в каждом другом агенте.
Если список навыков не обновился, откройте новый чат или перезапустите клиент.

Нужен локальный агент с доступом к файлам и терминалу. Обычный веб-чат без
таких инструментов не сможет установить ПО на ваш компьютер. Установка и
авторизация самого AI-клиента — отдельный предварительный шаг.

Первый запрос в чате Codex:

```text
$aimaster Хочу ролик о [идея]. Работай с уточнениями и открой дашборд.
```

В Claude Code замените `$aimaster` на `/aimaster`. Это текст для чата,
не команда терминала.

После установки прочитайте [getting-started.md](skills/aimaster/references/getting-started.md):
там описаны постоянный workspace вне клона, guided/autopilot, dashboard и
необязательный Telegram-трек. Проекты сохраняются локально; пользовательские
KB-файлы также держите вне публичного Git-репозитория.

### Вариант 2. Установить вручную в терминале

Нужны Git и Python 3.11+; runtime использует стандартную библиотеку Python,
Node/npm и `pip` для него не нужны. Команды ниже — для macOS/Linux POSIX.
Если шаг завершился ошибкой, остановитесь и устраните её до следующего шага.

macOS (если Homebrew уже есть — ставьте только отсутствующее):

```zsh
if ! command -v git >/dev/null 2>&1; then brew install git; fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then brew install python; fi
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else "Python 3.11+ required")'
```

Если Homebrew нет, установите его по [официальной странице Homebrew](https://brew.sh/)
и [официальной инструкции установки](https://docs.brew.sh/Installation),
прочитав команды перед выполнением. Не используйте непроверенный `curl | sh`.
Выполните напечатанные Homebrew «Next steps» для PATH и повторите проверку
Python. Если после установки виден старый Python, не заменяйте системный:
исправьте PATH по инструкции Homebrew.

Ubuntu/Debian:

```sh
command -v git >/dev/null || { sudo apt update && sudo apt install -y git; }
command -v python3 >/dev/null || { sudo apt update && sudo apt install -y python3; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else "Python 3.11+ required; stop and upgrade Python through official OS documentation")'
```

Проверка версии, используемая runtime:

```sh
python3 -c 'import sys; print(sys.version); raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
```

Если Linux предлагает Python младше 3.11, остановитесь и выполните официальный
путь обновления вашей ОС; поддерживаемой установку не называйте.

На Windows используйте [официальный WSL](https://learn.microsoft.com/en-us/windows/wsl/install):
`wsl --install` выполняется в PowerShell администратора; возможны перезапуск
и создание Linux-пользователя. Затем продолжайте внутри WSL с Linux-агентом.
Нативный Windows для этого runtime не поддерживается (`fcntl`). Переносимость
на WSL здесь не проверена; Windows-клиент не обязан видеть навыки внутри WSL.

Клонирование и ссылки (выберите один или оба runtime; не заменяйте существующие
ссылки/папки):

```sh
(
set -eu
AIMASTER_REPO_URL='https://github.com/alexfisenkov/aimaster.git'
AIMASTER_REPO_DIR="${HOME}/.local/share/aimaster"
mkdir -p "$(dirname "$AIMASTER_REPO_DIR")"
if [ -e "$AIMASTER_REPO_DIR" ] || [ -L "$AIMASTER_REPO_DIR" ]; then
  test -d "$AIMASTER_REPO_DIR/.git"
  test "$(git -C "$AIMASTER_REPO_DIR" remote get-url origin)" = "$AIMASTER_REPO_URL"
else
  git clone "$AIMASTER_REPO_URL" "$AIMASTER_REPO_DIR"
fi
test -f "$AIMASTER_REPO_DIR/skills/aimaster/SKILL.md"
)
```

```sh
# Codex
(
set -eu
AIMASTER_REPO_DIR="${HOME}/.local/share/aimaster"
AIMASTER_TARGET="${HOME}/.agents/skills/aimaster"
test "$(git -C "$AIMASTER_REPO_DIR" remote get-url origin)" = 'https://github.com/alexfisenkov/aimaster.git'
test -f "$AIMASTER_REPO_DIR/skills/aimaster/SKILL.md"
mkdir -p "$(dirname "$AIMASTER_TARGET")"
if [ -e "$AIMASTER_TARGET" ] || [ -L "$AIMASTER_TARGET" ]; then
  echo "Уже существует: $AIMASTER_TARGET. Ничего не заменено." >&2; exit 1
fi
ln -s "$AIMASTER_REPO_DIR/skills/aimaster" "$AIMASTER_TARGET"
)
```

```sh
# Claude Code
(
set -eu
AIMASTER_REPO_DIR="${HOME}/.local/share/aimaster"
AIMASTER_TARGET="${HOME}/.claude/skills/aimaster"
test "$(git -C "$AIMASTER_REPO_DIR" remote get-url origin)" = 'https://github.com/alexfisenkov/aimaster.git'
test -f "$AIMASTER_REPO_DIR/skills/aimaster/SKILL.md"
mkdir -p "$(dirname "$AIMASTER_TARGET")"
if [ -e "$AIMASTER_TARGET" ] || [ -L "$AIMASTER_TARGET" ]; then
  echo "Уже существует: $AIMASTER_TARGET. Ничего не заменено." >&2; exit 1
fi
ln -s "$AIMASTER_REPO_DIR/skills/aimaster" "$AIMASTER_TARGET"
)
```

Официальные документы о навыках: [OpenAI/Codex](https://learn.chatgpt.com/docs/build-skills)
и [Claude Code](https://code.claude.com/docs/en/skills). Другие агенты могут
поддерживать Agent Skills в своих официальных каталогах или принимать прямой
путь к `SKILL.md`; универсальная установка для любого агента не обещается.

## Обновление и удаление

Обновление выполняйте только в клоне и только с сохранением локальных изменений:
`git -C "$HOME/.local/share/aimaster" pull --ff-only`. При конфликте остановитесь.
Удаляйте только проверенную ссылку (`unlink` после проверки, что это symlink и
она указывает на этот клон); сам клон и workspace с проектами не удаляйте.

Лицензия для этой публичной упаковки пока не выбрана владельцем.

Авторский канал: [AI Мастерская](https://t.me/masterskaya_video).
