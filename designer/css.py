# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""A small CSS subset for SVG <style> blocks.

Real exports from Figma/Illustrator/SVGO routinely put fills, fonts and
strokes in a stylesheet with class selectors. Ignoring that block means
auditing a document whose colors and fonts you cannot see — so the
parser resolves the common cases (element, .class, #id, grouped
selectors) into presentation attributes and reports anything it had to
skip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Selector specificity ordering: id > class > element.
_SPECIFICITY = {"id": 3, "class": 2, "element": 1}

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_SIMPLE_SELECTOR_RE = re.compile(r"^(?:([a-zA-Z][\w-]*))?(?:\.([\w-]+))?(?:#([\w-]+))?$")


@dataclass
class Stylesheet:
    # (specificity, order, kind, key) -> declarations
    rules: list[tuple[int, int, str, str, dict[str, str]]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def declarations_for(
        self, tag: str, class_attr: str | None, id_attr: str | None
    ) -> dict[str, str]:
        """Merged declarations that apply to an element, in cascade
        order (later/more specific wins)."""
        classes = set((class_attr or "").split())
        matches = []
        for specificity, order, kind, key, decls in self.rules:
            if kind == "element" and key == tag:
                matches.append((specificity, order, decls))
            elif kind == "class" and key in classes:
                matches.append((specificity, order, decls))
            elif kind == "id" and key == id_attr:
                matches.append((specificity, order, decls))
        matches.sort(key=lambda m: (m[0], m[1]))
        merged: dict[str, str] = {}
        for _, _, decls in matches:
            merged.update(decls)
        return merged


def parse_stylesheet(css: str) -> Stylesheet:
    sheet = Stylesheet()
    css = _COMMENT_RE.sub("", css or "")
    order = 0
    for match in _RULE_RE.finditer(css):
        selector_text, body = match.group(1), match.group(2)
        declarations = _parse_declarations(body)
        if not declarations:
            continue
        for selector in selector_text.split(","):
            selector = selector.strip()
            if not selector:
                continue
            order += 1
            parsed = _parse_simple_selector(selector)
            if parsed is None:
                sheet.skipped.append(selector)
                continue
            kind, key = parsed
            sheet.rules.append((_SPECIFICITY[kind], order, kind, key, declarations))
    return sheet


def _parse_declarations(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name, value = name.strip().lower(), value.strip()
        if name and value:
            out[name] = value
    return out


def _parse_simple_selector(selector: str) -> tuple[str, str] | None:
    """Only single-component selectors are supported; descendant,
    pseudo, and attribute selectors are reported as skipped rather than
    silently mis-applied."""
    if selector == "*":
        return ("element", "*")
    m = _SIMPLE_SELECTOR_RE.match(selector)
    if not m:
        return None
    element, class_name, id_name = m.groups()
    if id_name and not element and not class_name:
        return ("id", id_name)
    if class_name and not element and not id_name:
        return ("class", class_name)
    if element and not class_name and not id_name:
        return ("element", element)
    return None  # compound selectors (e.g. text.brand) not supported
