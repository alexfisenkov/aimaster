"""Materialize an exact decoded last frame from the selected previous video."""
from __future__ import annotations

import json
import subprocess
import uuid
from decimal import Decimal, InvalidOperation

from . import decision_stages, domain
from .authoring_support import AuthoringError, mutate, safe_id
from .platform_compat import find_program
from .domain_positions import current_member, position_specs


def extract_last_frame(store, assets, project_id, expected_revision, *, scene_id):
    """Extract under the project revision lock; preserve prior results and media.

    ffprobe identifies the timestamp of the final decoded video frame; ffmpeg
    selects that exact decode-order frame. Neither operation contacts a provider.
    """
    safe_id(scene_id, "scene_id")
    created = None
    asset_id = None
    try:
        def change(state):
            nonlocal created, asset_id
            if domain.derive_view_stage(state)["current_stage"] != "motion":
                raise AuthoringError("last-frame continuity is available at motion stage")
            if state.get("gen_mode", "per_scene") != "per_scene":
                raise AuthoringError("continuity requires per_scene mode")
            scene = domain._video_scene(state, scene_id)
            previous, source, source_id = domain._continuity_source(state, scene)
            source_asset = source["asset_id"]
            path, mime = assets.resolve(source_asset)
            if mime not in {"video/mp4", "video/webm"}:
                raise AuthoringError("previous result must be a video")
            ffprobe, ffmpeg = find_program("ffprobe"), find_program("ffmpeg")
            if not ffprobe or not ffmpeg:
                raise AuthoringError("last-frame extraction requires ffmpeg and ffprobe")
            try:
                probe = subprocess.run(
                    [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
                     "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)],
                    check=True, capture_output=True, timeout=300,
                )
                frames = json.loads(probe.stdout).get("frames", [])
                if not frames or len(frames) > 1000000:
                    raise AuthoringError("video has no usable frames or exceeds the frame limit")
                timestamp = frames[-1].get("best_effort_timestamp_time")
                if not isinstance(timestamp, str) or not Decimal(timestamp).is_finite() or Decimal(timestamp) < 0:
                    raise AuthoringError("last video frame has no verified timestamp")
                created = assets.allowed_roots[0] / ("continuity-" + uuid.uuid4().hex + ".png")
                subprocess.run(
                    [ffmpeg, "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{len(frames)-1})",
                     "-fps_mode", "passthrough", "-frames:v", "1", "-n", str(created)],
                    check=True, capture_output=True, timeout=300,
                )
            except (OSError, subprocess.SubprocessError, ValueError, InvalidOperation, json.JSONDecodeError) as error:
                raise AuthoringError("cannot extract the last video frame; check ffmpeg/ffprobe and the source") from error
            # The registered asset's digest must still match after decoding.
            assets.resolve(source_asset)
            registered = assets.register(created.relative_to(assets.root), "result")
            asset_id = registered["asset_id"]
            spec = next(s for s in position_specs(state, include_inactive=True)
                        if s.get("scene_id") == scene_id and s.get("kind") == "first_frame")
            current = current_member(state, spec, "result")
            if current:
                version = domain.append_result_version(state, current, asset_id, list_key="image_results", link_key="first_frame_result_id")
                result = next(r for r in state["image_results"] if r.get("version_id") == version["version_id"])
            else:
                if any(r.get("result_id") == spec["result_group_id"] for r in state.get("image_results", [])):
                    raise AuthoringError("first-frame result history exists without a selected version")
                result = domain.start_result_version(spec["result_group_id"], asset_id, scene_id=scene_id)
                state.setdefault("image_results", []).append(result)
            result.update(decision="approved", continuity_source_result_id=source_id,
                          continuity_source_asset_id=source_asset, continuity_timestamp=timestamp)
            scene.setdefault("links", {})["first_frame_result_id"] = result["version_id"]
            scene["need_first"] = True
            scene["video_mode"] = "firstlast" if scene.get("need_last") else "first"
            scene.update(continuity_strategy="previous_last_frame", continuity_previous_scene_id=previous["scene_id"],
                         continuity_source_result_id=source_id, continuity_source_asset_id=source_asset,
                         continuity_first_frame_result_id=result["version_id"])
            domain.append_history(state, "you", "continuity-set", "motion", scene_id=scene_id, strategy="previous_last_frame")
            decision_stages.apply_project_status(state)
            return {"asset_id": asset_id, "version_id": result["version_id"], "source_result_id": source_id,
                    "source_asset_id": source_asset, "timestamp": timestamp}

        result, new_state = mutate(store, project_id, expected_revision, change)
        return {"project_id": project_id, "scene_id": scene_id, "strategy": "previous_last_frame",
                "revision": new_state["revision"], **result}
    except Exception:
        if asset_id:
            assets.forget(asset_id)
        if created:
            created.unlink(missing_ok=True)
        raise
