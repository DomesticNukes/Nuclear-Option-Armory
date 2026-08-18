"""
Minimal, pure-stdlib SVG parser — just enough to pull real vector shapes (paths + circles) out of a
plain, non-nested, non-`<use>`, single-`<g transform="matrix(...)">` SVG icon like the ones used for
the Controller Mapper's diagrams, and flatten them into Tkinter-Canvas-ready point lists. Not a
general SVG renderer (no gradients, clipping, nested transforms, `<use>`, CSS, viewBox scaling beyond
the one group transform) — only what real, simple icon SVGs from sites like Flaticon/thenounproject
actually use in practice, keeping this dependency-free per the project's pure-stdlib approach.

Bezier curves (C/S/Q/T) are flattened into straight-line segments by sampling a fixed number of
points per curve — Tkinter Canvas has no native bezier primitive, only straight polygons/lines (or
`create_line(..., smooth=True)`, which spline-fits through points rather than rendering the real
curve, so this project always flattens explicitly instead for a faithful shape).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

_SVG_NS = "{http://www.w3.org/2000/svg}"
_CURVE_STEPS = 14   # points per bezier segment when flattening — smooth enough at typical UI sizes

_TOKEN_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")


@dataclass
class Shape:
    kind: str            # "polygon" or "oval"
    points: list = field(default_factory=list)   # for "polygon": [(x,y), ...]; for "oval": [(cx,cy,r)]
    fill: Optional[str] = None
    stroke: Optional[str] = None


def _tokenize(d: str) -> list:
    tokens = []
    for cmd_match, num_match in _TOKEN_RE.findall(d):
        if cmd_match:
            tokens.append(cmd_match)
        elif num_match:
            tokens.append(float(num_match))
    return tokens


def _cubic_bezier(p0, p1, p2, p3, steps=_CURVE_STEPS):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _quad_bezier(p0, p1, p2, steps=_CURVE_STEPS):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
        y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
        pts.append((x, y))
    return pts


def _elliptical_arc(p0, rx, ry, x_rot_deg, large_arc, sweep, p1, steps=_CURVE_STEPS):
    """Standard SVG endpoint-to-center arc parameterization (spec appendix F.6.5), sampled into
    straight-line points. Real icon SVGs draw full circles as four 90-degree arcs (start==end never
    happens per-segment, but four of them close a circle) — a straight-line "approximation" of THAT
    is a diamond, not a circle, so this path matters for visual correctness, not just polish."""
    import math
    x0, y0 = p0
    x1, y1 = p1
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [p1]
    phi = math.radians(x_rot_deg)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx2, dy2 = (x0 - x1) / 2, (y0 - y1) / 2
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    rx, ry = abs(rx), abs(ry)
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale

    sign = -1 if large_arc == sweep else 1
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = sign * math.sqrt(max(num / den, 0)) if den else 0
    cxp = co * (rx * y1p / ry)
    cyp = co * -(ry * x1p / rx)

    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x1) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y1) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        length = math.sqrt((ux ** 2 + uy ** 2) * (vx ** 2 + vy ** 2))
        a = math.acos(max(-1, min(1, dot / length))) if length else 0
        return a if ux * vy - uy * vx >= 0 else -a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    pts = []
    for i in range(1, steps + 1):
        t = theta1 + dtheta * i / steps
        x = cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi
        y = cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi
        pts.append((x, y))
    return pts


def parse_path_d(d: str) -> list:
    """Returns a list of subpaths, each a flat list of (x, y) points — straight lines and flattened
    curves/arcs only (Z closes back to the subpath's start point). Elliptical arcs ("A") are flattened
    via the real endpoint-to-center parameterization (see _elliptical_arc) — a straight-line
    approximation was tried first and rejected: real icon SVGs often draw a full circle as four
    90-degree arcs, and a straight-line "approximation" of that draws a diamond, not a circle,
    confirmed as a real, visible bug on this project's own button-circle SVGs, not just theoretical."""
    tokens = _tokenize(d)
    subpaths = []
    current = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_control = None
    i = 0
    cmd = None
    while i < len(tokens):
        tok = tokens[i]
        if isinstance(tok, str):
            cmd = tok
            i += 1
        if cmd is None:
            break

        upper = cmd.upper()
        relative = cmd.islower()

        def nxt():
            nonlocal i
            v = tokens[i]
            i += 1
            return v

        if upper == "M":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            if current:
                subpaths.append(current)
            current = [(x, y)]
            cur = (x, y)
            start = cur
            cmd = "l" if relative else "L"   # subsequent pairs after M are implicit lineto
            last_control = None
        elif upper == "L":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            current.append((x, y))
            cur = (x, y)
            last_control = None
        elif upper == "H":
            x = nxt()
            x = cur[0] + x if relative else x
            cur = (x, cur[1])
            current.append(cur)
            last_control = None
        elif upper == "V":
            y = nxt()
            y = cur[1] + y if relative else y
            cur = (cur[0], y)
            current.append(cur)
            last_control = None
        elif upper == "C":
            x1, y1, x2, y2, x, y = nxt(), nxt(), nxt(), nxt(), nxt(), nxt()
            if relative:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            current.extend(_cubic_bezier(cur, (x1, y1), (x2, y2), (x, y)))
            cur = (x, y)
            last_control = (x2, y2)
        elif upper == "S":
            x2, y2, x, y = nxt(), nxt(), nxt(), nxt()
            if relative:
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            if last_control:
                x1, y1 = 2 * cur[0] - last_control[0], 2 * cur[1] - last_control[1]
            else:
                x1, y1 = cur
            current.extend(_cubic_bezier(cur, (x1, y1), (x2, y2), (x, y)))
            cur = (x, y)
            last_control = (x2, y2)
        elif upper == "Q":
            x1, y1, x, y = nxt(), nxt(), nxt(), nxt()
            if relative:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x, y = cur[0] + x, cur[1] + y
            current.extend(_quad_bezier(cur, (x1, y1), (x, y)))
            cur = (x, y)
            last_control = (x1, y1)
        elif upper == "T":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            if last_control:
                x1, y1 = 2 * cur[0] - last_control[0], 2 * cur[1] - last_control[1]
            else:
                x1, y1 = cur
            current.extend(_quad_bezier(cur, (x1, y1), (x, y)))
            cur = (x, y)
            last_control = (x1, y1)
        elif upper == "A":
            rx, ry, x_rot, large_arc, sweep = nxt(), nxt(), nxt(), nxt(), nxt()
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            current.extend(_elliptical_arc(cur, rx, ry, x_rot, bool(large_arc), bool(sweep), (x, y)))
            cur = (x, y)
            last_control = None
        elif upper == "Z":
            current.append(start)
            cur = start
            last_control = None
        else:
            i += 1   # unknown command — skip its token defensively rather than looping forever

    if current:
        subpaths.append(current)
    return subpaths


def _apply_matrix(points: list, matrix) -> list:
    a, b, c, d, e, f = matrix
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in points]


def load_svg_shapes(svg_path: str) -> list:
    """Every real <path>/<circle> shape in the SVG, flattened to Canvas-ready points and with the
    file's own group transform already applied — callers never need to know the SVG's own coordinate
    system. Only supports a single top-level `matrix(...)` transform on one wrapping `<g>` (or no
    transform at all), which is all real single-icon SVGs of the kind this app uses actually have."""
    tree = ET.parse(svg_path)
    root = tree.getroot()

    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    group = root.find(f"{_SVG_NS}g")
    search_root = root
    if group is not None:
        transform = group.get("transform", "")
        m = re.search(r"matrix\(([^)]+)\)", transform)
        if m:
            parts = [float(p) for p in re.split(r"[,\s]+", m.group(1).strip()) if p]
            if len(parts) == 6:
                matrix = tuple(parts)
        search_root = group

    shapes = []
    for el in search_root.iter():
        tag = el.tag.replace(_SVG_NS, "")
        fill = el.get("fill")
        stroke = el.get("stroke")
        if tag == "path":
            d = el.get("d", "")
            for subpath in parse_path_d(d):
                shapes.append(Shape(kind="polygon", points=_apply_matrix(subpath, matrix),
                                     fill=fill, stroke=stroke))
        elif tag == "circle":
            cx, cy, r = float(el.get("cx", 0)), float(el.get("cy", 0)), float(el.get("r", 0))
            transformed = _apply_matrix([(cx, cy)], matrix)[0]
            scale = (matrix[0] ** 2 + matrix[1] ** 2) ** 0.5   # uniform-scale assumption
            shapes.append(Shape(kind="oval", points=[(transformed[0], transformed[1], r * scale)],
                                 fill=fill, stroke=stroke))
    return shapes


def bounding_box(shapes: list):
    xs, ys = [], []
    for s in shapes:
        if s.kind == "polygon":
            for x, y in s.points:
                xs.append(x); ys.append(y)
        else:
            cx, cy, r = s.points[0]
            xs.extend([cx - r, cx + r]); ys.extend([cy - r, cy + r])
    return min(xs), min(ys), max(xs), max(ys)
