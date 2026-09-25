"""Раскладка монтажа в папке проекта и путь к MP4 версии в media/.

<проект>/montage/current — рабочий монтаж (его правят Studio и агент),
versions/vNNN — неизменяемые снимки, скрытые .undo/.cache/.logs/.desk.json —
служебное. MP4 версии лежит в <workspace>/media/<проект>/montage/vNNN.mp4:
только внутри media/ его принимает AssetIndex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VERSION_ID = re.compile(r"v(\d{3,})")


def version_name(number: int) -> str:
    return f"v{number:03d}"


def version_number(version_id: str) -> int:
    match = VERSION_ID.fullmatch(version_id or "")
    if not match:
        raise ValueError(f"не версия монтажа: {version_id!r}")
    return int(match.group(1))


@dataclass(frozen=True)
class MontagePaths:
    root: Path

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def index(self) -> Path:
        return self.current / "index.html"

    @property
    def assets(self) -> Path:
        return self.current / "assets"

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def undo(self) -> Path:
        return self.root / ".undo"

    @property
    def cache(self) -> Path:
        return self.root / ".cache"

    @property
    def logs(self) -> Path:
        return self.root / ".logs"

    @property
    def desk_file(self) -> Path:
        return self.root / ".desk.json"

    def version_dir(self, version_id: str) -> Path:
        version_number(version_id)
        return self.versions / version_id


def montage_paths(project_dir: Path) -> MontagePaths:
    return MontagePaths(Path(project_dir) / "montage")


def render_output(media_root: Path, project_id: str, version_id: str) -> Path:
    version_number(version_id)
    return Path(media_root) / project_id / "montage" / f"{version_id}.mp4"
