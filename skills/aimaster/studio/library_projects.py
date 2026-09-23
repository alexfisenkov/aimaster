"""Library ⇄ projects: `library import --from-projects` and `--from-library`.

Spec 2026-09-23 §3. Import walks every project's references that carry a
registered file — scene-local image references included, scene-local
video references (`project_clip`) skipped — and adds each file once (sha256). A generated reference
(`source=generate`) contributes its selected result version, else its
approved one (`generated_asset_id`). Labels are shortened to
their name part («Артём — второй персонаж» → «Артём»); the most frequent
name becomes the entry label, the others its aliases. A character's
attached voice file becomes its own `kind=voice` entry with `voice_of`.

`materialize` is the other direction: a library file is copied into
`<workspace>/media/library/` (the asset index only serves files below
`media/`) and registered with the asset role its kind needs.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .assets import AssetError
from .authoring_support import open_assets, open_store
from .library import (KIND_FOLDERS, LibraryError, add_file, find_by_sha, get_entry, library_file,
                      library_root, locked_index, sha256_of)
from .library_match import name_part

_ROLE_TO_KIND = {"character": "character", "location": "location", "product": "product",
                 "style": "style", "object": "other", "other": "other", "video": "other"}
_TAG_LIKE = ("IMG_", "VID_", "VOICE_")


_NAME_KINDS = frozenset({"character", "voice"})


def _full_label(reference) -> str | None:
    label = reference.get("label")
    if not isinstance(label, str) or not label.strip() or label.strip().startswith(_TAG_LIKE):
        return None
    return label.strip()


def _candidate_name(kind, full) -> str:
    """A person is named by the part before « — »; anything else keeps its
    whole caption («AI Мастерская — dark boho riding look» is a look, not
    the brand)."""

    return name_part(full) if kind in _NAME_KINDS else full


def _has_cyrillic(text: str) -> bool:
    return any("а" <= char <= "я" or char == "ё" for char in text.casefold())


def _label_and_aliases(slot, current_label=None) -> tuple[str, list[str]]:
    """Most frequent name wins; a tie prefers a Cyrillic spelling, then the
    entry's current label (stable across imports), then first seen."""

    counts = slot["names"]
    order = {name: position for position, name in enumerate(counts)}
    names = sorted(counts, key=lambda name: (-counts[name], not _has_cyrillic(name),
                                             name != current_label, order[name]))
    names = names or [slot["path"].stem]
    aliases = [*names[1:], *slot["fulls"]]
    return names[0], [a for a in dict.fromkeys(aliases) if a != names[0]]


def _usable(result) -> bool:
    return (isinstance(result, dict) and result.get("asset_id")
            and result.get("decision") != "rejected"
            and result.get("hidden") is not True and result.get("retired") is not True)


def generated_asset_id(state, reference) -> tuple[str | None, str | None]:
    """File of a generated reference: the selected result version the
    reference links to, else its latest `decision: approved` version.
    Rejected, hidden and retired versions never count.
    Returns `(asset_id, None)` or `(None, "no_selected_result")`.
    """

    results = [r for r in state.get("image_results", []) or [] if isinstance(r, dict)]
    links = reference.get("links") if isinstance(reference.get("links"), dict) else {}
    selected = links.get("image_result_id")
    for result in results:
        if selected and result.get("version_id") == selected and _usable(result):
            return result["asset_id"], None
    own = f"result:ref:{reference.get('reference_id')}"
    approved = [r for r in results if r.get("result_id") == own
                and r.get("decision") == "approved" and _usable(r)]
    if approved:
        return approved[-1]["asset_id"], None
    return None, "no_selected_result"


def _collect(workspace):
    store, assets = open_store(workspace), open_assets(workspace)
    found, skipped = {}, []
    # Read each project folder on its own (not `store.list_projects()`,
    # which refuses the whole workspace over one broken `state.json`):
    # critic finding 7 -- a broken project is reported, never fatal.
    for folder in store._project_paths():
        try:
            state = store._read(folder)
            project_id = state["project"]["id"]
            if not isinstance(project_id, str) or not isinstance(state.get("references", []), list):
                raise TypeError("unexpected project shape")
        except Exception as error:  # noqa: BLE001 - one broken project must not stop the import
            skipped.append({"project_id": folder.name, "reference_id": None,
                            "reason": "project_unreadable", "error": type(error).__name__})
            continue
        for reference in state.get("references", []) or []:
            ref_id = reference.get("reference_id")
            where = {"project_id": project_id, "reference_id": ref_id}
            # `local` is a binding inside one project, not a property of the
            # subject: a scene-local image reference is imported like any
            # other. A scene-local video is a clip of that very film
            # (continuation, edit) and stays in its project.
            if reference.get("role") == "video" and reference.get("local", "scene_id" in reference):
                skipped.append({**where, "reason": "project_clip"})
                continue
            kind = _ROLE_TO_KIND.get(reference.get("role"))
            asset_id = reference.get("asset_id")
            if kind is not None and asset_id is None and reference.get("source") == "generate":
                asset_id, reason = generated_asset_id(state, reference)
                if asset_id is None:
                    skipped.append({**where, "reason": reason})
                    continue
            if kind is None or asset_id is None:
                skipped.append({**where, "reason": "no_file"})
                continue
            jobs = [(kind, asset_id)]
            voice = reference.get("voice") or {}
            if kind == "character" and isinstance(voice, dict) and voice.get("asset_id"):
                jobs.append(("voice", voice["asset_id"]))
            owner_digest = None
            for job_kind, asset_id in jobs:
                try:
                    path, _ = assets.resolve(asset_id)
                    digest = sha256_of(path)
                except (AssetError, ValueError, OSError):
                    skipped.append({**where, "reason": "asset_missing"})
                    break
                slot = found.setdefault(digest, {"kind": job_kind, "path": path, "names": Counter(),
                                                 "fulls": [], "source": where,
                                                 "owner_digest": owner_digest})
                owner_digest = digest
                full = _full_label(reference)
                if full:
                    slot["names"][_candidate_name(slot["kind"], full)] += 1
                    slot["fulls"].append(full)
    return found, skipped


def import_from_projects(workspace) -> dict:
    library = library_root(workspace, create=True)
    found, skipped = _collect(workspace)
    created, reused, relabeled = [], [], []
    character_ids = {}
    with locked_index(library) as index:
        for digest, slot in sorted(found.items(), key=lambda item: item[1]["kind"] == "voice"):
            before = find_by_sha(index, digest)
            label, aliases = _label_and_aliases(slot, before["label"] if before else None)
            voice_of = character_ids.get(slot["owner_digest"]) if slot["kind"] == "voice" else None
            before = None if before is None else (before["label"], list(before["aliases"]))
            try:
                entry, is_new, _ = add_file(index, library, kind=slot["kind"], label=label,
                                            aliases=aliases, source_file=slot["path"],
                                            voice_of=voice_of, source=slot["source"],
                                            strict_kind=False)
            except (LibraryError, OSError) as error:
                # Critic finding 7: one bad file never stops the others.
                skipped.append({**slot["source"], "reason": "add_failed",
                                "error": type(error).__name__})
                continue
            (created if is_new else reused).append(entry["library_id"])
            if not is_new and "source" in entry and entry["kind"] == slot["kind"]:
                # Derived by an earlier import: bring its caption up to the
                # current naming rule. Entries from `library add` (no
                # `source`) are the user's own wording and stay untouched.
                # Critic finding 6: merge, never drop, aliases someone added
                # by hand; only the previous automatic label is let go.
                kept = [a for a in entry["aliases"]
                        if a not in aliases and a != label and a != (before or ("",))[0]]
                entry["label"], entry["aliases"] = label, [*aliases, *kept]
                if before != (entry["label"], entry["aliases"]):
                    relabeled.append(entry["library_id"])
            if entry["kind"] == "character":
                character_ids[digest] = entry["library_id"]
        total = len(index["entries"])
    return {"created": created, "already_in_library": reused, "relabeled": relabeled,
            "skipped": skipped, "entries": total}


def _asset_role(kind: str, media: str) -> str:
    if media == "video":
        return "video_reference"
    if media == "audio":
        return "voice"
    return kind if kind in {"character", "location", "product", "style", "other"} else "other"


def materialize(workspace, library_id) -> dict:
    """Copy a library file into `media/library/` and register it as an asset."""

    library, entry = get_entry(workspace, library_id)
    item = entry["files"][0]
    source = library_file(library, item["path"])
    if sha256_of(source) != item["sha256"]:
        raise LibraryError("library file changed since it was added")
    media_dir = Path(workspace).resolve(strict=True) / "media" / "library" / KIND_FOLDERS[entry["kind"]]
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / f"{item['sha256'][:12]}-{source.name}"
    if not target.exists():
        descriptor, temporary = tempfile.mkstemp(dir=media_dir, prefix=".copy.", suffix=".tmp")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    role = _asset_role(entry["kind"], item["media"])
    relative = target.relative_to(Path(workspace).resolve(strict=True)).as_posix()
    registered = open_assets(workspace).register(relative, role)
    return {"entry": entry, "asset": registered, "media": item["media"]}
