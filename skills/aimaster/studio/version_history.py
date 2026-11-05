"""Read all canonical version identities for authoring response and verification."""
from .decision_cards import PROMPT_COLLECTIONS, RESULT_COLLECTIONS


def version_ids(state):
    items = list((state.get("script") or {}).get("versions", []))
    for scene in state.get("scenes", []):
        items.extend((scene.get("script_block") or {}).get("versions", []))
    for collection in (*PROMPT_COLLECTIONS, *RESULT_COLLECTIONS):
        items.extend(state.get(collection, []))
    return {item.get("version_id") for item in items if isinstance(item, dict) and item.get("version_id")}
