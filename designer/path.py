# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Grammar-correct SVG path data parsing.

The SVG path mini-language has traps a number-regex cannot handle:
arc flags are single characters that may be fused with the following
coordinate (``a5 5 0 0110 10``), and decimals may omit the leading zero
and run together (``M.5.5``). This module implements the real grammar,
and on top of it: curve flattening to vertices, and correct fill area
(curves sampled, opposite-winding holes subtracted).

``parse_path`` raises ValueError on malformed data — callers treat that
as "not a path we can reason about" rather than guessing.
"""

from __future__ import annotations

import math
import re

# command -> parameter count
PARAM_COUNTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

_SEP = re.compile(r"[ \t\n\r,]*")
_CMD = re.compile(r"[ \t\n\r,]*([MmLlHhVvCcSsQqTtAaZz])")
_NUM = re.compile(r"[ \t\n\r,]*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_FLAG = re.compile(r"[ \t\n\r,]*([01])")


def parse_path(d: str) -> list[tuple[str, list[float]]]:
    """Parse path data into a list of (command, params).

    Implicit command repetition is expanded (``L 1 2 3 4`` becomes two
    L commands; coordinates after a moveto become linetos, per spec).
    Arc flags are parsed as single characters, so fused forms like
    ``0110 10`` decode correctly.
    """
    out: list[tuple[str, list[float]]] = []
    pos, n = 0, len(d)
    cmd: str | None = None
    while True:
        pos = _SEP.match(d, pos).end()
        if pos >= n:
            break
        m = _CMD.match(d, pos)
        if m:
            cmd = m.group(1)
            pos = m.end()
        else:
            if cmd is None:
                raise ValueError(f"path data must start with a command: {d[:30]!r}")
            if cmd.upper() == "Z":
                raise ValueError(f"unexpected data after Z at position {pos}")
            # implicit repeat; extra moveto pairs become linetos
            if cmd == "M":
                cmd = "L"
            elif cmd == "m":
                cmd = "l"
        count = PARAM_COUNTS[cmd.upper()]
        params: list[float] = []
        for i in range(count):
            if cmd.upper() == "A" and i in (3, 4):
                fm = _FLAG.match(d, pos)
                if not fm:
                    raise ValueError(f"invalid arc flag at position {pos} in {d[:60]!r}")
                params.append(float(fm.group(1)))
                pos = fm.end()
            else:
                nm = _NUM.match(d, pos)
                if not nm:
                    raise ValueError(f"expected number at position {pos} in {d[:60]!r}")
                params.append(float(nm.group(1)))
                pos = nm.end()
        out.append((cmd, params))
    if not out:
        raise ValueError("empty path data")
    return out


def serialize_path(cmds: list[tuple[str, list[float]]]) -> str:
    parts: list[str] = []
    for cmd, params in cmds:
        parts.append(cmd)
        for i, value in enumerate(params):
            if cmd.upper() == "A" and i in (3, 4):
                parts.append(str(int(value)))
            else:
                parts.append(f"{value:.2f}".rstrip("0").rstrip(".") or "0")
    return " ".join(parts)


# ------------------------------------------------------------ flattening


def _sample_cubic(p0, c1, c2, p1, k):
    pts = []
    for i in range(1, k + 1):
        t = i / k
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * p1[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * p1[1]
        pts.append((x, y))
    return pts


def _sample_quad(p0, c, p1, k):
    pts = []
    for i in range(1, k + 1):
        t = i / k
        mt = 1 - t
        x = mt**2 * p0[0] + 2 * mt * t * c[0] + t**2 * p1[0]
        y = mt**2 * p0[1] + 2 * mt * t * c[1] + t**2 * p1[1]
        pts.append((x, y))
    return pts


def _sample_arc(p0, rx, ry, rot_deg, large, sweep, p1, k):
    """Endpoint-parameterized elliptical arc -> sampled points (SVG
    implementation notes, F.6.5)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rot_deg)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2
    # scale radii up if the arc is impossible
    lam = x1p**2 / rx**2 + y1p**2 / ry**2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    coeff = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coeff = -coeff
    cxp = coeff * rx * y1p / ry
    cyp = -coeff * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        length = math.hypot(ux, uy) * math.hypot(vx, vy)
        ang = math.acos(max(-1.0, min(1.0, dot / length)))
        if ux * vy - uy * vx < 0:
            ang = -ang
        return ang

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    pts = []
    for i in range(1, k + 1):
        t = theta1 + dtheta * i / k
        x = cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi
        y = cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi
        pts.append((x, y))
    pts[-1] = p1
    return pts


def path_subpaths(d: str, curve_samples: int = 8) -> list[list[tuple[float, float]]]:
    """Flatten path data to vertex lists, one per subpath. Curves and
    arcs are sampled; relative commands, H/V, and S/T reflection are
    fully handled. Raises ValueError on malformed data."""
    cmds = parse_path(d)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    cx = cy = 0.0  # current point
    sx = sy = 0.0  # subpath start
    prev_cmd = ""
    prev_ctrl: tuple[float, float] | None = None

    def close_current():
        nonlocal current
        if len(current) >= 2:
            subpaths.append(current)
        current = []

    for cmd, p in cmds:
        absolute = cmd.isupper()
        u = cmd.upper()
        ox, oy = (0.0, 0.0) if absolute else (cx, cy)
        if u == "M":
            close_current()
            cx, cy = ox + p[0], oy + p[1]
            sx, sy = cx, cy
            current = [(cx, cy)]
            prev_ctrl = None
        elif u == "L":
            cx, cy = ox + p[0], oy + p[1]
            current.append((cx, cy))
            prev_ctrl = None
        elif u == "H":
            cx = (p[0] if absolute else cx + p[0])
            current.append((cx, cy))
            prev_ctrl = None
        elif u == "V":
            cy = (p[0] if absolute else cy + p[0])
            current.append((cx, cy))
            prev_ctrl = None
        elif u == "C":
            c1 = (ox + p[0], oy + p[1])
            c2 = (ox + p[2], oy + p[3])
            end = (ox + p[4], oy + p[5])
            current.extend(_sample_cubic((cx, cy), c1, c2, end, curve_samples))
            prev_ctrl = c2
            cx, cy = end
        elif u == "S":
            if prev_cmd.upper() in ("C", "S") and prev_ctrl is not None:
                c1 = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1])
            else:
                c1 = (cx, cy)
            c2 = (ox + p[0], oy + p[1])
            end = (ox + p[2], oy + p[3])
            current.extend(_sample_cubic((cx, cy), c1, c2, end, curve_samples))
            prev_ctrl = c2
            cx, cy = end
        elif u == "Q":
            c = (ox + p[0], oy + p[1])
            end = (ox + p[2], oy + p[3])
            current.extend(_sample_quad((cx, cy), c, end, curve_samples))
            prev_ctrl = c
            cx, cy = end
        elif u == "T":
            if prev_cmd.upper() in ("Q", "T") and prev_ctrl is not None:
                c = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1])
            else:
                c = (cx, cy)
            end = (ox + p[0], oy + p[1])
            current.extend(_sample_quad((cx, cy), c, end, curve_samples))
            prev_ctrl = c
            cx, cy = end
        elif u == "A":
            end = (ox + p[5], oy + p[6])
            current.extend(
                _sample_arc((cx, cy), p[0], p[1], p[2], int(p[3]), int(p[4]), end, curve_samples * 2)
            )
            cx, cy = end
            prev_ctrl = None
        elif u == "Z":
            if current:
                cx, cy = sx, sy
                if current[-1] != (sx, sy):
                    current.append((sx, sy))
            prev_ctrl = None
        prev_cmd = cmd
    close_current()
    return subpaths


def _signed_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def path_area(d: str, curve_samples: int = 8) -> float:
    """Fill area of a path: curves sampled to vertices, subpath signed
    areas summed so opposite-winding holes subtract (matching how this
    engine emits holes)."""
    total = 0.0
    for sub in path_subpaths(d, curve_samples):
        total += _signed_area(sub)
    return abs(total)


def path_bounds(d: str) -> tuple[float, float, float, float] | None:
    """(min_x, min_y, max_x, max_y) of the flattened path, or None."""
    xs: list[float] = []
    ys: list[float] = []
    for sub in path_subpaths(d, curve_samples=4):
        xs.extend(p[0] for p in sub)
        ys.extend(p[1] for p in sub)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)
