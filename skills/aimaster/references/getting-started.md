# Установка с нуля: AI Мастерская

Эта инструкция поможет создать постоянную папку для ваших проектов и первый
ролик. После того как workspace известен и первый проект создан, навык сразу
запускает локальную страницу проекта. Агент добавляет к адресу `?project=<project-id>` и открывает его
через возможность хоста; если её нет, он показывает точный адрес для ручного
открытия. Страница показывает ход работы и даёт копировать готовые запросы;
решения и действия остаются в чате. Telegram можно подключить позже. Если запуск
страницы технически недоступен, работа продолжается только в чате.

Примеры команд подготовлены для macOS и оболочки zsh. Нужен Python 3.11 или
новее. Для другой оболочки способ ввода пути может отличаться.

## 1. Проверь среду

Нужен Python 3.11 или новее. Дополнительные пакеты Python устанавливать не
нужно. Открой терминал в папке `skills/aimaster` и проверь версию и доступные
команды:

```zsh
cd "/путь/к/skills/aimaster"
python3 --version
python3 scripts/creator_studio.py --help
python3 scripts/creator_studio_bot.py --help
```

В новом окне терминала снова укажи папку проекта: введённые значения
не переносятся туда автоматически.

## 2. Подготовь папку для проектов

Выбери постоянную папку вне установленной копии `aimaster`. В ней будут лежать
проекты и медиа. При открытии нового окна терминала путь нужно ввести снова.
Не выбирай временную папку: после перезагрузки она может исчезнуть.

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

Если команда завершилась ошибкой, не переходи к следующим шагам: сначала исправь
путь или окружение и запусти этот блок снова.

Повторный запуск с тем же путём не создаст `first-video` заново. Для следующего
проекта нужны другое короткое имя, название и тип. Файл `state.json` вручную
не редактируй.

## 3. Выбери способ работы

Можно продолжить только в чате, открыть страницу проекта в браузере, подключить
Telegram или совместить эти варианты. Для страницы и Telegram используется та
же папка проектов.

## 4. Открой страницу проекта в браузере (если нужен ручной запуск)

Если агент не смог открыть страницу через возможность хоста, запусти из той же
папки:

```zsh
python3 scripts/creator_studio.py serve "$CREATOR_WORKSPACE" --port 0
```

К единственному напечатанному адресу добавь ID проекта и открой полный адрес:
`http://127.0.0.1:<номер-порта>/?project=first-video`. Для другого проекта
замени `first-video` на его ID. Страница работает, пока открыт этот процесс;
для остановки нажми `Ctrl-C`. Страница только показывает материалы и позволяет
копировать промпты. Вопросы, решения, правки и создание новых материалов идут
через работающего агента в чате.

## 5. Подключи Telegram (необязательно, только для владельца macOS)

Для подключения запусти локальный мастер:

```zsh
python3 scripts/creator_studio_telegram.py setup-ui
```

Он принимает токен скрыто и сохраняет его в macOS Keychain. Если Keychain
недоступен, используется файл с правами `0600` вне проекта. Токен не попадает в
чат, URL, argv или логи.

После сохранения токена окно покажет pairing-код. Затем запусти transport:

```zsh
python3 scripts/creator_studio_telegram.py run --workspace "$CREATOR_WORKSPACE"
```

Отправь боту команду `/start <код>`, показанную локальным мастером. Первый
личный запуск с правильным кодом привязывает текущий Telegram ID;
посторонние чаты игнорируются. При наличии `cloudflared` бот добавит кнопку
«AI Мастерская» с Mini App. Если туннель недоступен, текстовые команды и локальный
bridge остаются доступными, но Mini App с телефона не откроется. В этой версии
в Telegram поддерживаются текстовые сообщения и команды; медиа-вложения будут
добавлены отдельным этапом.

На macOS агент должен быть установлен и авторизован заранее. Windows в этом
выпуске не поддерживается.

Программа читает значения, переданные текущему процессу. Файл `.env` сам по
себе не загружается. Используй терминал или уже настроенное безопасное хранилище.
Имена переменных должны быть точно такими:

```text
TELEGRAM_STUDIO_BOT_TOKEN
TELEGRAM_STUDIO_OWNER_ID
```

`TELEGRAM_STUDIO_OWNER_ID` — числовой ID собственного аккаунта, не имя пользователя и
не ID бота.

### Безопасно узнать свой числовой ID

Если для этого бота уже настроена передача сообщений на другой адрес, способ
ниже не сработает. Используй нового отдельного бота или сначала сам реши, можно
ли менять его настройки; автоматически ничего не удаляется. Если сообщения
этого бота уже читает другая запущенная тобой программа, останови только её.
Способ ниже не печатает токен, адрес запроса или полный ответ Telegram.

1. Сгенерируй случайную фразу локально и запиши её только в текущем терминале:

```zsh
TELEGRAM_CHALLENGE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
printf 'Отправь эту фразу в личный чат с новым ботом: %s\n' "$TELEGRAM_CHALLENGE"
```

2. Сам отправь ровно эту фразу боту в личном диалоге. Затем, в том же
   терминале, введи токен скрыто и выполни проверку. Она принимает только одно
   личное сообщение от того же аккаунта с точным совпадением случайной фразы;
   первый попавшийся отправитель не принимается. Если совпадений нет, их несколько,
   пишет другой отправитель или возникает ошибка, проверка останавливается.

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

Проверь напечатанное число глазами. Следующий legacy-блок нужен только для
ручного режима `creator_studio_bot.py`; обычный macOS-путь выше использует
`creator_studio_telegram.py run` и pairing-код.

```zsh
read -r "TELEGRAM_STUDIO_OWNER_ID?Введите найденный числовой ID: "
export TELEGRAM_STUDIO_OWNER_ID
python3 scripts/creator_studio_bot.py --workspace "$CREATOR_WORKSPACE"
```

Если открываешь новое окно терминала, снова укажи папку проектов, токен бота
и свой числовой ID. Связь с Telegram работает только для указанного владельца,
запускается вручную и не заменяет работающего AI-агента.

## 6. Продолжай в чате

Напиши агенту идею ролика. Для видео сначала назови предполагаемую длительность
и выбери формат: один цельный ролик (`one-shot`) или отдельные сцены
(`per-scene`); затем агент уточнит аудиторию и ограничения, подготовит
сценарий, кадры и промпты, а затем поможет пройти следующие шаги. Вопросы и
ответы остаются в чате; страница в браузере показывает материалы проекта.

Сначала скажи агенту, какие сервисы или MCP уже подключены. Агент проверит их,
покажет доступные модели и поможет выбрать подходящую. После этого одно разрешённое
действие на создание или перегенерацию означает один запуск — повторно спрашивать
подтверждение того же действия не нужно. Дополнительный запуск требует нового
разрешения. Точные команды описаны в [справочнике для агента](creator-studio.md).
