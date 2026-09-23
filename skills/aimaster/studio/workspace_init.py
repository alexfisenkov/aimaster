"""`workspace init <ws>`: create the working-folder layout, idempotently.

Spec 2026-09-23 §5. Creates only what is missing and never overwrites an
existing file: `projects/`, `media/`, `instructions/`, `library/` with its
kind folders and an empty `index.json`, the private `.studio/`, and a
Russian `README.md` explaining the layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from .library import INDEX_NAME, KIND_FOLDERS, LIBRARY_DIR_NAME, SCHEMA_VERSION, write_index_atomic
from .workspace import PRIVATE_DIR_NAME

README_TEXT = """# Рабочая папка AI Мастерской

Здесь живёт всё, что создаёт навык aimaster. Папки появились сами при первом
запуске; руками их создавать и переименовывать не нужно.

- `projects/` — проекты роликов: у каждого своя папка с `state.json`.
- `media/` — файлы, которые проекты используют: референсы, кадры, видео, звук.
- `instructions/` — ваши гайды по промптам для нейросетей (`guides.json` — их список).
- `library/` — библиотека рабочей папки: персонажи, голоса, локации, товары
  и стили, которые подхватываются в новых проектах сами.
  - `characters/` — персонажи;
  - `voices/` — голоса персонажей;
  - `locations/` — места;
  - `products/` — товары и предметы;
  - `styles/` — стили;
  - `other/` — всё остальное;
  - `index.json` — список записей библиотеки (ведёт агент, руками не править).
- `.studio/` — служебные базы студии (очередь действий, вопросы, реестр файлов).
  Скрытая папка: не удаляйте и не отправляйте её никому.

Чтобы добавить персонажа или голос в библиотеку, отправьте файл агенту и
скажите, кто это. Уже загруженные в проекты персонажи агент может перенести
в библиотеку сам.
"""


def _ensure_dir(path: Path, root: Path, created: list, *, mode=0o755) -> None:
    if path.is_symlink():
        raise ValueError(f"{path.relative_to(root)} must be a real directory, not a symlink")
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"{path.relative_to(root)} exists and is not a directory")
        return
    path.mkdir(mode=mode)
    created.append(path.relative_to(root).as_posix() + "/")


def init_workspace(workspace) -> dict:
    root = Path(workspace).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    created: list[str] = []
    for name in ("projects", "media", "instructions", LIBRARY_DIR_NAME):
        _ensure_dir(root / name, root, created)
    _ensure_dir(root / PRIVATE_DIR_NAME, root, created, mode=0o700)
    library = root / LIBRARY_DIR_NAME
    for folder in KIND_FOLDERS.values():
        _ensure_dir(library / folder, root, created)
    index = library / INDEX_NAME
    if not index.exists():
        write_index_atomic(library, {"schema_version": SCHEMA_VERSION, "revision": 0, "entries": []})
        created.append(f"{LIBRARY_DIR_NAME}/{INDEX_NAME}")
    else:
        json.loads(index.read_text(encoding="utf-8"))  # an unreadable index is reported, not replaced
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")
        created.append("README.md")
    return {"workspace": str(root), "created": created, "already_initialized": not created}
