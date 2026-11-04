"""Typed drawings over generated clips, using the existing HTML/SVG renderer.

AIEditing's Focus/Cursor/Link supply the method (frame-based targeting,
time-bounded marks, optional stroke reveal). No React/Remotion runtime is
imported. Coordinates are pixels in the declared canvas, origin top-left.
Only this encoder emits SVG; clients submit data, never SVG/HTML/CSS.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from html.parser import HTMLParser

from . import MontageError
from .html_doc import element_attrs, element_span, fmt_number as fmt, insert_before_root_end
from .index_io import read_index, write_index

TYPES = ("rect", "ellipse", "arrow", "stroke")
LAYER = "overlays"
TRACK = 6
_FIELDS = {"type", "canvas", "geometry", "color", "stroke_width", "opacity", "draw_on", "scene_id"}
_REQUIRED = _FIELDS - {"draw_on", "scene_id"}
_ID = re.compile(r"o-(\d+)\Z")
_SCENE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TIMELINE_MARK = "/* AIMASTER_TYPED_OVERLAYS_V1 */"
_TIMELINE = """/* AIMASTER_TYPED_OVERLAYS_V1 */
    root.querySelectorAll('[data-am-layer="overlays"]').forEach(function (element) {
      var drawing = JSON.parse(element.getAttribute('data-am-overlay'));
      if (drawing.draw_on > 0) {
        var path = element.querySelector('svg path');
        tl.fromTo(path, { strokeDashoffset: 1 },
          { strokeDashoffset: 0, duration: drawing.draw_on, ease: 'none', immediateRender: true },
          parseFloat(element.getAttribute('data-start')) || 0);
      }
    });
    """


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise MontageError(f"некорректное значение рисунка: {label}")
    return round(float(value), 6)


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise MontageError(f"некорректные поля рисунка: {label}")


def canvas_of(text):
    root = element_attrs(text).get("root", {})
    try:
        return {"width": int(root["data-width"]), "height": int(root["data-height"])}
    except (KeyError, TypeError, ValueError) as error:
        raise MontageError("у композиции нет корректного холста") from error


def validate(overlay, *, canvas=None):
    if not isinstance(overlay, dict) or not _REQUIRED <= set(overlay) or set(overlay) - _FIELDS:
        raise MontageError("рисунок принимает только типизированные данные, не SVG/HTML")
    kind = overlay["type"]
    if kind not in TYPES:
        raise MontageError("тип рисунка: rect, ellipse, arrow или stroke")
    declared = overlay["canvas"]
    _object(declared, {"width", "height"}, "canvas")
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16384
           for value in declared.values()) or (canvas is not None and declared != canvas):
        raise MontageError("холст рисунка должен совпадать с текущим canvas")
    width, height = declared["width"], declared["height"]
    geometry = overlay["geometry"]
    if kind in {"rect", "ellipse"}:
        _object(geometry, {"x", "y", "width", "height"}, "geometry")
        x, y = _number(geometry["x"], 0, width, "x"), _number(geometry["y"], 0, height, "y")
        w, h = _number(geometry["width"], .001, width, "width"), _number(geometry["height"], .001, height, "height")
        if x + w > width or y + h > height:
            raise MontageError("выделение выходит за canvas")
        geometry = {"x": x, "y": y, "width": w, "height": h}
    elif kind == "arrow":
        _object(geometry, {"x1", "y1", "x2", "y2"}, "geometry")
        geometry = {key: _number(value, 0, width if key.startswith("x") else height, key)
                    for key, value in geometry.items()}
        if math.hypot(geometry["x2"] - geometry["x1"], geometry["y2"] - geometry["y1"]) < .001:
            raise MontageError("у стрелки должны различаться начало и конец")
    else:
        _object(geometry, {"points"}, "geometry")
        points = geometry["points"]
        if not isinstance(points, list) or not 2 <= len(points) <= 1024:
            raise MontageError("штрих должен содержать от 2 до 1024 точек")
        clean = []
        for point in points:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise MontageError("точка штриха — пара координат canvas")
            clean.append([_number(point[0], 0, width, "point.x"), _number(point[1], 0, height, "point.y")])
        if all(point == clean[0] for point in clean):
            raise MontageError("штрих должен содержать разные точки")
        geometry = {"points": clean}
    color = overlay["color"]
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise MontageError("цвет рисунка — #RRGGBB")
    scene = overlay.get("scene_id")
    if scene is not None and (not isinstance(scene, str) or not _SCENE.fullmatch(scene)):
        raise MontageError("некорректный scene_id рисунка")
    return {"type": kind, "canvas": dict(declared), "geometry": geometry, "color": color.upper(),
            "stroke_width": _number(overlay["stroke_width"], .5, 100, "stroke_width"),
            "opacity": _number(overlay["opacity"], 0, 1, "opacity"),
            "draw_on": _number(overlay.get("draw_on", 0), 0, 60, "draw_on"), "scene_id": scene}


def _path(overlay):
    kind, g = overlay["type"], overlay["geometry"]
    if kind in {"rect", "ellipse"}:
        x, y, w, h = (g[key] for key in ("x", "y", "width", "height"))
        if kind == "rect":
            return f"M{fmt(x)} {fmt(y)} H{fmt(x+w)} V{fmt(y+h)} H{fmt(x)} Z"
        return (f"M{fmt(x)} {fmt(y+h/2)} a{fmt(w/2)} {fmt(h/2)} 0 1 0 {fmt(w)} 0 "
                f"a{fmt(w/2)} {fmt(h/2)} 0 1 0 {fmt(-w)} 0")
    if kind == "stroke":
        return " ".join(("M" if index == 0 else "L") + fmt(x) + " " + fmt(y)
                        for index, (x, y) in enumerate(g["points"]))
    x1, y1, x2, y2 = (g[key] for key in ("x1", "y1", "x2", "y2"))
    length = math.hypot(x2-x1, y2-y1)
    ux, uy = (x2-x1) / length, (y2-y1) / length
    head = min(max(8, overlay["stroke_width"] * 3), length / 3)
    a = (x2 - ux*head - uy*head*.55, y2 - uy*head + ux*head*.55)
    b = (x2 - ux*head + uy*head*.55, y2 - uy*head - ux*head*.55)
    return (f"M{fmt(x1)} {fmt(y1)} L{fmt(x2)} {fmt(y2)} "
            f"M{fmt(a[0])} {fmt(a[1])} L{fmt(x2)} {fmt(y2)} L{fmt(b[0])} {fmt(b[1])}")


def fragment(identity, overlay, start, duration):
    payload = html.escape(json.dumps(overlay, ensure_ascii=False, sort_keys=True, separators=(",", ":")), quote=True)
    scene = f' data-am-scene="{html.escape(overlay["scene_id"], quote=True)}"' if overlay["scene_id"] else ""
    draw = overlay["draw_on"]
    dash = ' pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"' if draw else ""
    canvas = overlay["canvas"]
    return (f'<div id="{identity}" class="clip am-overlay" data-start="{fmt(start)}" '
            f'data-duration="{fmt(duration)}" data-track-index="{TRACK}" data-am-layer="{LAYER}"'
            f'{scene} data-am-overlay="{payload}" style="position:absolute;inset:0;z-index:6;pointer-events:none">'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
            f'viewBox="0 0 {canvas["width"]} {canvas["height"]}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path d="{_path(overlay)}" fill="none" stroke="{overlay["color"]}" '
            f'stroke-width="{fmt(overlay["stroke_width"])}" opacity="{fmt(overlay["opacity"])}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash}/></svg></div>')


def with_timeline(text, overlay):
    if not overlay["draw_on"] or _TIMELINE_MARK in text:
        return text
    marker = 'window.__timelines["main"] = tl;'
    if text.count(marker) != 1:
        raise MontageError("прорисовке нужен существующий таймлайн main черновика AIMaster")
    return text.replace(marker, _TIMELINE + marker, 1)


def add(ctx, request):
    text = read_index(ctx.paths.index)
    overlay = validate(request.overlay, canvas=canvas_of(text))
    root = element_attrs(text)["root"]
    total = float(root["data-duration"])
    start = _number(request.at, 0, total, "at")
    duration = _number(request.duration, .001, total, "duration")
    if start + duration > total + 1e-6:
        raise MontageError("рисунок должен находиться внутри длительности композиции")
    number = max((int(match.group(1)) for match in map(_ID.fullmatch, element_attrs(text)) if match), default=0) + 1
    identity = f"o-{number}"
    text = insert_before_root_end(text, fragment(identity, overlay, start, duration))
    write_index(ctx.paths.index, with_timeline(text, overlay))
    return {"ok": True, "new_clip": identity, "overlay": overlay}


def update(ctx, clip, request):
    if clip.overlay is None:
        raise MontageError("overlay-update применяется только к рисунку")
    text = read_index(ctx.paths.index)
    overlay = validate(request.overlay, canvas=canvas_of(text))
    begin, end = element_span(text, clip.id)
    text = text[:begin] + fragment(clip.id, overlay, clip.start, clip.duration) + text[end:]
    write_index(ctx.paths.index, with_timeline(text, overlay))
    return {"ok": True, "clip": clip.id, "overlay": overlay}


class _Visual(HTMLParser):
    """Ignore Studio IDs/track bookkeeping; keep actual SVG and presentation changes."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        clean = []
        for name, value in attrs:
            if name.startswith(("data-", "aria-")) or name in {"id", "xmlns"}:
                continue
            if name == "style":
                value = ";".join(sorted(part.strip().replace(": ", ":") for part in value.split(";") if part.strip()))
            clean.append((name, value))
        self.records.append((tag, sorted(clean)))
        self.in_style = tag == "style"

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.records.append(("css", " ".join(data.split())))


def read_overlay(text, identity, attrs):
    if attrs.get("data-am-layer") != LAYER:
        return None, None
    try:
        payload = validate(json.loads(attrs["data-am-overlay"]))
    except (KeyError, ValueError, TypeError) as error:
        raise MontageError("данные рисунка в композиции повреждены") from error
    begin, end = element_span(text, identity)
    parser = _Visual()
    parser.feed(text[begin:end])
    canonical = json.dumps(parser.records, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(canonical.encode()).hexdigest()[:16]
