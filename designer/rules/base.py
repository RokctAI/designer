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
