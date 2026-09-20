# Установка с нуля: AI Мастерская

Эта процедура нужна для нового или пустого workspace. Оба трека независимы:
дашборд и Telegram можно настроить оба, любой один или ни один. Chat-only —
полностью рабочий вариант.

Примеры команд проверены в macOS zsh; runtime требует POSIX и Python 3.11+.
Для другой оболочки адаптируй ввод переменных и синтаксис проверки пути.

## 1. Проверь среду

Нужен Python 3.11+ и POSIX-система (macOS проверена); используются только
модули стандартной библиотеки, установка пакетов не нужна. Из папки самого
skill проверь версию и команды:

```zsh
cd "/путь/к/skills/aimaster"
python3 --version
python3 scripts/creator_studio.py --help
python3 scripts/creator_studio_bot.py --help
```

При новом терминале снова задай рабочую переменную: shell-переменные сами не
переносятся между терминалами. Не используй `HOME` или общие переменные.

## 2. Подготовь общий workspace

Выбери постоянную абсолютную папку владельца. Она нужна всем трекам и
chat-only; запуск `serve` не обязателен. В новом терминале повторно введи этот
путь. Не используй `mktemp` для обычной работы: он предназначен только для
тестового harness.

```zsh
read -r "CREATOR_WORKSPACE?Введите постоянный абсолютный путь workspace: "
python3 - "$CREATOR_WORKSPACE" <<'PY'
import subprocess
import sys
from pathlib import Path

raw = sys.argv[1]
if not raw:
    raise SystemExit("Workspace path is empty; refusing to continue")
candidate = Path(raw)
if not candidate.is_absolute():
    raise SystemExit("Workspace path must be absolute; refusing to continue")
try:
    canonical = candidate.resolve(strict=False)
except OSError:
    raise SystemExit("Workspace path cannot be resolved; refusing to continue")
if canonical == Path("/"):
    raise SystemExit("Workspace path resolves to /; refusing to continue")
if candidate.exists() and not candidate.is_dir():
    raise SystemExit("Workspace path exists but is not a directory")

projects = canonical / "projects"
media = canonical / "media"
projects.mkdir(parents=True, exist_ok=True)
media.mkdir(parents=True, exist_ok=True)
state = projects / "first-video" / "state.json"
if state.is_file():
    print("first-video already exists; leaving it unchanged")
else:
    subprocess.run(
        [
            sys.executable,
            "scripts/creator_studio.py",
            "project",
            "create",
            str(canonical),
            "first-video",
            "--title",
            "Первый ролик",
            "--type",
            "video",
            "--mode",
            "guided",
        ],
        check=True,
    )
PY
```

Если setup завершился ошибкой, не переходи к следующим шагам: сначала исправь
путь или окружение и запусти этот блок снова.

Повторный запуск выбирает тот же существующий путь и не повторяет создание
`first-video`. Для другого проекта выбери новый `id` и конкретные title/type/mode;
не редактируй `state.json` вручную.

## 3. Выбери необязательные треки

Выбери дашборд, Telegram, оба или ни одного. Они независимы: chat-only не
требует ни локального сервера, ни Telegram, а Telegram получает тот же
`CREATOR_WORKSPACE` независимо от запуска dashboard.

## 4. Запусти дашборд (необязательно)

Если нужен браузерный интерфейс, запусти loopback-сервер из этой же папки:

```zsh
python3 scripts/creator_studio.py serve "$CREATOR_WORKSPACE" --port 0
```

Открой единственный напечатанный адрес `http://127.0.0.1:<port>` в браузере.
Сервер работает до `Ctrl-C`. Дашборд ставить ПО, логиниться, вызывать LLM или
провайдеров не умеет и сам агента не будит. Можно сразу пропустить этот трек и
продолжить в чате.

## 5. Подключи Telegram-controller (необязательно, только для владельца)

Этот трек не нужен для chat-only или dashboard-only работы. Владелец сам
создаёт отдельного бота через официальный @BotFather и получает токен. Токен
не отправляй в чат, не вставляй в пример и не сохраняй в историю команд.

Runtime читает только окружение процесса: `.env` может быть местом хранения,
но сам по себе не загружается. Используй shell или уже имеющийся у тебя
secret manager/loader. Имена переменных — только эти:

```text
TELEGRAM_STUDIO_BOT_TOKEN
TELEGRAM_STUDIO_OWNER_ID
```

`TELEGRAM_STUDIO_OWNER_ID` — числовой ID собственного аккаунта, не username и
не ID бота.

### Безопасно узнать owner id

Если уже активен webhook, этот `getUpdates`-путь недоступен: выбери нового
отдельного бота или сам реши, как менять настройки; ничего автоматически не
удаляется. Если ранее запущен другой твой poller, останови только этот свой
процесс перед probe, не глобальные процессы. Ниже — user-run способ с
официальным `getUpdates`. Он намеренно не печатает токен, URL или полный
payload. Выполняй его локально; в рамках этой документации сеть не запускается.

1. Сгенерируй случайную фразу локально и запиши её только в текущую shell:

```zsh
TELEGRAM_CHALLENGE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
printf 'Отправь эту фразу в личный чат с новым ботом: %s\n' "$TELEGRAM_CHALLENGE"
```

2. Сам отправь ровно эту фразу боту в личном диалоге. Затем, в том же
   терминале, введи токен скрыто и выполни локальный helper. Он принимает
   только ровно один update, где `message.chat.type == "private"`,
   `sender_id == chat_id` и текст точно совпадает с challenge; первый
   попавшийся отправитель не принимается. При нуле, нескольких совпадениях,
   чужом sender или ошибке helper останавливается.

```zsh
read -s "TELEGRAM_STUDIO_BOT_TOKEN?Введите токен: "; printf '\n'
export TELEGRAM_STUDIO_BOT_TOKEN
python3 - "$TELEGRAM_CHALLENGE" <<'PY'
import json, os, sys
from urllib import request

challenge = sys.argv[1]
token = os.environ.get("TELEGRAM_STUDIO_BOT_TOKEN")
if not isinstance(token, str) or not token.strip():
    raise SystemExit("TELEGRAM_STUDIO_BOT_TOKEN is missing or empty")
url = "https://api.telegram.org/bot" + token + "/getUpdates"
try:
    with request.urlopen(request.Request(url), timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
except Exception:
    raise SystemExit("getUpdates failed; no response or token was printed")
if not isinstance(body, dict) or body.get("ok") is not True:
    raise SystemExit("getUpdates rejected the request")
updates = body.get("result")
if not isinstance(updates, list):
    raise SystemExit("getUpdates result is not a list")
matches = []
for update in updates:
    message = update.get("message") if isinstance(update, dict) else None
    chat = message.get("chat") if isinstance(message, dict) else None
    sender = message.get("from") if isinstance(message, dict) else None
    text = message.get("text") if isinstance(message, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    sender_id = sender.get("id") if isinstance(sender, dict) else None
    valid_id = lambda value: type(value) is int and value > 0
    if (isinstance(chat, dict) and chat.get("type") == "private"
            and valid_id(chat_id) and valid_id(sender_id)
            and sender_id == chat_id
            and text == challenge):
        matches.append(chat_id)
if len(matches) != 1:
    raise SystemExit("expected exactly one matching private message")
print(matches[0])
PY
```

Проверь напечатанное число глазами, затем экспортируй owner id. Не подставляй
его в документацию или логи:

```zsh
read -r "TELEGRAM_STUDIO_OWNER_ID?Введите найденный числовой ID: "
export TELEGRAM_STUDIO_OWNER_ID
python3 scripts/creator_studio_bot.py --workspace "$CREATOR_WORKSPACE"
```

Если запускаешь controller в новом терминале, заново задай
`CREATOR_WORKSPACE`, `TELEGRAM_STUDIO_BOT_TOKEN` и
`TELEGRAM_STUDIO_OWNER_ID` там. Controller делает только явно запущенный
owner-only мост к Studio; это не LLM, не ASR и не голосовой чат, не выполняет
автозапуск и не заменяет активного агента.

## 6. Продолжай в чате

Продолжай в чате: агент задаёт необходимые вопросы, принимает решения и
approval там (или через явно запущенный Telegram-controller). Дашборд не
показывает текст вопросов и варианты ответов. Для video текущий путь имеет
шесть стадий, для photo — четыре; точные позиции см. в [Creator
Studio](creator-studio.md). Для одного платного dashboard-run verified route +
scoped grant + explicit click разрешают только этот один run; повтор,
variation или regeneration требуют нового согласования, второго approval для
того же действия нет. Установка не создаёт LLM/ASR и не обещает появление
голосового AI.
