# Установка aimaster силами агента

Этот файл предназначен для агента пользователя (Claude Code, Codex или другого
агента с доступом к терминалу). Установка одна для macOS, Linux и Windows:
скачать репозиторий и запустить установщик `install.py`. Он сам подключает
навык к Claude Code (`~/.claude/skills/aimaster`) и к Codex и другим агентам
(`~/.agents/skills/aimaster`), проверяет программы и делает самопроверку.
WSL для Windows не нужен.

**Главное правило для агента:** не просите пользователя выбирать версии,
способы установки или агента. Ставьте то, что указано ниже, и берите команду
Python из вывода установщика — поле `python_cmd` (`python3`, `py -3` или
`python`). Во всех командах навыка, где в документации написано `python3`,
используйте именно её.

## Разрешённые границы

Разрешено проверить и при отсутствии поставить Git и Python 3.11+ через
официальный менеджер пакетов ОС (winget, Homebrew, apt), а также запустить
`install.py --install-deps`: он ставит бесплатные ffmpeg, cloudflared и Git.
На Windows установщик передаёт winget флаги `--accept-package-agreements
--accept-source-agreements`, то есть соглашается с условиями этих пакетов;
если пользователь против, запустите без `--install-deps` — установщик только
напечатает команды. Node, npm, pip и сторонние Python-пакеты не нужны.

Не отключайте защиты, не угадывайте пароль sudo и не печатайте токены, пароли,
cookies или `.env`. Если нужен пароль администратора, перезагрузка или
интерактивный вход, остановитесь и попросите пользователя выполнить только
этот шаг.

Запрещены покупки, настройка Telegram/MCP, платные генерации, автоматический
логин AI-клиента, публикация и запуск creative/media jobs. После установки
остановитесь: сообщите проверенные пути и предложите первый запрос.

Во время установки не изменяйте код в `studio/` и `scripts/`. Соблюдайте
[авторские условия](LICENSE): бесплатно использовать пакет для работы и клиентов
можно, но распространять изменённую сборку или выдавать её за свой продукт без
согласия владельца нельзя. Пользовательские проекты, медиа, база, настройки и
свои инструкции хранятся вне клона. Если установка нашла ошибку проекта,
предложите пользователю создать обращение в
https://github.com/alexfisenkov/aimaster/issues. Ничего не публикуйте без его
согласия и не включайте в обращение личные данные, секреты и содержимое проектов.

## Процедура (все ОС)

Точный адрес репозитория: `https://github.com/alexfisenkov/aimaster.git`.
Постоянная папка клона: macOS и Linux — `~/.local/share/aimaster`,
Windows — `%LOCALAPPDATA%\aimaster`. Другой путь — только по просьбе
пользователя. Не клонируйте репозиторий внутрь каталога навыков.

1. **Python 3.11+.** Проверьте командой из раздела вашей ОС. Если Python нет
   или он старше — поставьте указанной командой, затем откройте новый терминал.
2. **Файлы.** Если папка клона уже есть, не клонируйте поверх: убедитесь, что
   это Git-репозиторий с точным `origin`, иначе остановитесь и попросите путь.
   Если папки нет — `git clone`. Без Git (и без возможности его поставить) —
   скачайте архив с GitHub (см. раздел Windows).
3. **Установщик.** Запустите `install.py --install-deps --json` из клона
   (команды ниже). Он печатает JSON с полями:
   - `ok` — всё ли получилось; `targets` — куда подключён навык и каким способом
     (`symlink`, `junction` или `copy`);
   - `deps` — какие программы есть, чего нет и какой командой поставить;
   - `self_check` — самопроверка (импорт, `--help`, `detect_tools.py`,
     `workspace init` во временной папке, которая затем удаляется);
   - `python_cmd` — команда Python для этой машины.
4. **Если `ok: false`.** Прочитайте `message` у пунктов со статусом `conflict`
   или с `ok: false`. Установщик никогда не перезаписывает чужую папку на месте
   навыка — покажите её пользователю и спросите, что с ней делать. Свою старую
   ссылку или копию aimaster он заменяет только с `--force`.

Коды выхода: `0` — готово, `1` — есть конфликт или ошибка самопроверки,
`2` — Python старше 3.11 (в выводе точная команда установки), `3` — не найден
клон.

### macOS

```zsh
python3 -c 'import sys; print(sys.version); raise SystemExit(0 if sys.version_info >= (3,11) else 1)' \
  || brew install python@3.12
command -v git >/dev/null || brew install git
git clone https://github.com/alexfisenkov/aimaster.git "$HOME/.local/share/aimaster"
python3 "$HOME/.local/share/aimaster/skills/aimaster/scripts/install.py" --install-deps --json
```

Если после `brew install python@3.12` команда `python3` всё ещё старая,
запустите установщик через `python3.12` — он сам выберет и напечатает
правильный `python_cmd`.

Если Homebrew нет, откройте [brew.sh](https://brew.sh/) и
[Installation](https://docs.brew.sh/Installation), прочитайте официальный
установщик и выполните его, если разрешения среды позволяют. Пароль
администратора оставьте человеку. Не исполняйте непроверенный `curl | sh` и не
удаляйте системный Python.

### Linux (Ubuntu/Debian)

```sh
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' \
  || { sudo apt update && sudo apt install -y python3.12; }
command -v git >/dev/null || { sudo apt update && sudo apt install -y git; }
git clone https://github.com/alexfisenkov/aimaster.git "$HOME/.local/share/aimaster"
python3 "$HOME/.local/share/aimaster/skills/aimaster/scripts/install.py" --json
```

На Linux установщик сам ничего не ставит (нужен sudo): он печатает команды
`apt` для недостающих программ. Если `python3` остался старым, а `python3.12`
поставился, запускайте установщик через `python3.12`. Если в репозиториях ОС нет Python 3.11+,
остановитесь и объясните, что нужен официальный путь обновления ОС.

### Windows (PowerShell, без WSL)

Проверка Python (новый терминал после любой установки):

```powershell
py -3 --version
```

Если команды `py` нет или версия ниже 3.11:

```powershell
winget install -e --id Python.Python.3.12
```

Затем закройте и снова откройте PowerShell — иначе новый Python не найдётся.

Git и установка навыка:

```powershell
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { winget install -e --id Git.Git }
Set-Location $env:LOCALAPPDATA
git clone https://github.com/alexfisenkov/aimaster.git aimaster
py -3 aimaster\skills\aimaster\scripts\install.py --install-deps --json
```

Если Git только что поставлен, откройте новый PowerShell перед `git clone`.

Без Git — скачать архив с GitHub:

```powershell
$zip = Join-Path $env:TEMP 'aimaster.zip'
$tmp = Join-Path $env:TEMP 'aimaster-unpacked'
Invoke-WebRequest 'https://github.com/alexfisenkov/aimaster/archive/refs/heads/main.zip' -OutFile $zip
Expand-Archive $zip -DestinationPath $tmp -Force
Move-Item (Join-Path $tmp 'aimaster-main') (Join-Path $env:LOCALAPPDATA 'aimaster')
py -3 "$env:LOCALAPPDATA\aimaster\skills\aimaster\scripts\install.py" --install-deps --json
```

`Move-Item` не перезаписывает существующую папку: если `aimaster` уже есть,
остановитесь и спросите пользователя. Установка из архива не обновляется
через Git — для обновлений лучше поставить Git.

На Windows навык подключается через directory junction — прав администратора
не нужно. Если junction и символическая ссылка недоступны, установщик ставит
копию и пишет об этом; такую копию обновляют повторным запуском
`install.py --update`.

WSL — необязательная альтернатива для тех, кто уже работает в Linux-среде:
тогда агент, навык и Python ставятся внутри WSL по разделу Linux.

## Обновление

Обновляйте только чистый клон с точным `origin` на ветке `main`:

```sh
python3 ~/.local/share/aimaster/skills/aimaster/scripts/install.py --update --json
```

```powershell
py -3 "$env:LOCALAPPDATA\aimaster\skills\aimaster\scripts\install.py" --update --json
```

Установщик сам проверит `origin`, ветку и отсутствие локальных изменений,
выполнит `git pull --ff-only` и `git fetch --tags`, покажет метку выпуска в
`update.tag` и перепишет установленные копии. При локальных изменениях он
остановится (`update.status: blocked`) и ничего не сбросит. Никогда не
применяйте reset, stash, force или checkout для обхода локальных изменений.
Если метки выпуска нет, не объявляйте обновление завершённым.

## Завершение

После установки перечитайте пути из `targets` и убедитесь, что там есть
`SKILL.md`. Не называйте обнаружение навыка в интерфейсе агента
подтверждённым, пока оно не наблюдалось в новом чате. Сообщите пользователю
только нечувствительные сведения: путь клона, пути навыка, способ подключения,
`python_cmd`, каких необязательных программ нет. Затем предложите, например:

> Помоги сделать короткий ролик о [идея]. Сначала уточни аудиторию и ограничения.

Для следующего шага направьте пользователя к
`skills/aimaster/references/getting-started.md`. Не создавайте папку проектов,
проекты, медиа, Telegram credentials и настройки сервисов автоматически:
раскладку рабочей папки навык создаёт сам командой `workspace init` при первой
активации в выбранной пользователем папке. Если список навыков клиента не
обновился, предложите новый чат или перезапуск приложения.
