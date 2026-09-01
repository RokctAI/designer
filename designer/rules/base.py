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

"""Rule interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from designer.report import Finding
from designer.svg import Document
from designer.tokens import DesignSystem


class Rule(ABC):
    """A single design-system constraint.

    ``run`` inspects the document and returns findings. When ``autofix``
    is True the rule mutates the document in place and marks the
    findings it resolved as fixed.
    """

    id: str = "rule"
    description: str = ""

    @abstractmethod
    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        ...
