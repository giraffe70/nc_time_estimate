from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nc_time_twin.core.ir.blocks import BaseBlock


class IRProgram(list[BaseBlock]):
    """List-like IR container with prev/next links for later look-ahead."""

    def __init__(self, blocks: Iterable[BaseBlock] = ()):
        super().__init__(blocks)
        self.metadata: dict[str, Any] = {}
        self.link_neighbors()

    def link_neighbors(self) -> None:
        for index, block in enumerate(self):
            block.prev = self[index - 1] if index > 0 else None
            block.next = self[index + 1] if index + 1 < len(self) else None
