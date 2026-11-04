"""Small generated-clips formats, adapted from AIEditing 0.1.0's method.

Sources: AIEditing SKILL.md (workshop versus built format), phases/trial.md
(same source for each probe; preserve chosen parameters), catalog/steps.json
(cut, music and motion). This adapter executes those applicable ideas with
the existing HyperFrames renderer; it never runs the speech/YouTube workshop.
Personal formats live in the workspace, never in the distributed package.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

from . import MontageError

_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_NUMBERS = {"transition": (0, 1), "zoom": (1, 1.15), "music_volume": (0, 1)}


def _profile(identity, label, transition, zoom, music):
    return {"schema_version": 1, "kind": "generated-clips", "id": identity, "label": label,
            "method": "aiediting-format-adaptation", "method_version": "0.1.0",
            "engine": "hyperframes", "steps": ["ordered-trim", "audio-mix", "motion"],
            "params": {"transition": transition, "zoom": zoom, "music_volume": music}}


BUILTINS = {"basic": _profile("basic", "Базовый / Basic", 0, 1, .3),
            "dynamic": _profile("dynamic", "Динамичный / Dynamic", .12, 1.06, .35),
            "cinematic": _profile("cinematic", "Кинематографичный / Cinematic", .5, 1.03, .22)}


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != set(BUILTINS["basic"]):
        raise MontageError("формат должен быть профилем generated-clips, не мастерской AIEditing")
    if (profile["schema_version"] != 1 or profile["kind"] != "generated-clips"
            or profile["engine"] != "hyperframes" or profile["method"] != "aiediting-format-adaptation"
            or profile["method_version"] != "0.1.0" or not _ID.fullmatch(str(profile["id"]))
            or profile["steps"] != BUILTINS["basic"]["steps"]
            or not isinstance(profile["label"], str) or not 1 <= len(profile["label"]) <= 120):
        raise MontageError("неподдерживаемый формат generated-clips")
    params = profile["params"]
    if not isinstance(params, dict) or set(params) != set(_NUMBERS):
        raise MontageError("формату нужны transition, zoom и music_volume")
    for key, (low, high) in _NUMBERS.items():
        value = params[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise MontageError(f"параметр {key} вне поддерживаемого диапазона")
    return copy.deepcopy(profile)


def _directory(workspace):
    folder = Path(workspace).resolve() / ".montage-styles"
    if folder.is_symlink():
        raise MontageError("папка личных монтажных стилей не должна быть ссылкой")
    return folder


def catalog(workspace):
    entries = [{"ref": key, "source": "builtin", "profile": copy.deepcopy(value)}
               for key, value in BUILTINS.items()]
    folder = _directory(workspace)
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            if path.is_symlink():
                raise MontageError("личный монтажный стиль не должен быть ссылкой")
            try:
                profile = validate_profile(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as error:
                raise MontageError("личный монтажный стиль повреждён") from error
            if path.stem != profile["id"]:
                raise MontageError("имя файла личного стиля не совпадает с его id")
            entries.append({"ref": "user:" + profile["id"], "source": "user", "profile": profile})
    return entries


def choose(workspace, ref="basic", *, brief=""):
    if ref == "auto":
        text = brief.casefold()
        ref = ("cinematic" if any(word in text for word in ("cinematic", "cinema", "кинемат", "плавн", "slow"))
               else "dynamic" if any(word in text for word in ("dynamic", "энерг", "динами", "быстр")) else "basic")
    entry = next((item for item in catalog(workspace) if item["ref"] == ref), None)
    if entry is None:
        raise MontageError("нет выбранного монтажного формата; перечитайте montage styles")
    return entry


def save(workspace, identity, profile, *, label=None):
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise MontageError("id личного стиля: строчные латинские буквы, цифры, дефис")
    profile = validate_profile({**profile, "id": identity, "label": label or profile["label"]})
    folder = _directory(workspace)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (identity + ".json")
    # O_EXCL: saving a second revision must use a new name, never overwrite taste.
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as error:
        raise MontageError("личный стиль уже существует; выберите новое имя версии") from error
    return {"ref": "user:" + identity, "profile": validate_profile(json.loads(target.read_text(encoding="utf-8")))}
