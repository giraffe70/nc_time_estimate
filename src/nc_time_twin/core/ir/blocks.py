from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class BaseBlock:
    line_no: int
    raw: str
    start: Position | None = None
    end: Position | None = None
    length: float = 0.0
    estimated_time: float = 0.0
    warnings: list[str] = field(default_factory=list)
    prev: BaseBlock | None = field(default=None, repr=False, compare=False)
    next: BaseBlock | None = field(default=None, repr=False, compare=False)

    block_type: ClassVar[str] = "unknown"

    @property
    def display_type(self) -> str:
        return self.block_type

    def start_tuple(self) -> tuple[float, float, float] | None:
        return self.start.as_tuple() if self.start else None

    def end_tuple(self) -> tuple[float, float, float] | None:
        return self.end.as_tuple() if self.end else None


@dataclass
class RapidMoveBlock(BaseBlock):
    block_type: ClassVar[str] = "rapid"


@dataclass
class LinearMoveBlock(BaseBlock):
    feedrate: float | None = None
    feed_mode: str = "G94"
    spindle_speed: float | None = None
    unit: str = "mm"
    block_type: ClassVar[str] = "linear"


@dataclass
class ArcMoveBlock(BaseBlock):
    direction: str = "G02"
    plane: str = "G17"
    ijk: tuple[float | None, float | None, float | None] = (None, None, None)
    r: float | None = None
    feedrate: float | None = None
    feed_mode: str = "G94"
    spindle_speed: float | None = None
    unit: str = "mm"
    block_type: ClassVar[str] = "arc"


@dataclass
class DwellBlock(BaseBlock):
    dwell_time_sec: float = 0.0
    block_type: ClassVar[str] = "dwell"


@dataclass
class ToolChangeBlock(BaseBlock):
    tool_id: int | None = None
    block_type: ClassVar[str] = "tool_change"


@dataclass
class SpindleEventBlock(BaseBlock):
    event: str = "spindle_start"
    spindle_speed: float | None = None
    block_type: ClassVar[str] = "spindle_event"


@dataclass
class CoolantEventBlock(BaseBlock):
    event: str = "coolant_on"
    block_type: ClassVar[str] = "coolant_event"


@dataclass
class ProgramEndBlock(BaseBlock):
    block_type: ClassVar[str] = "program_end"


@dataclass
class UnknownBlock(BaseBlock):
    reason: str = "unknown"
    block_type: ClassVar[str] = "unknown"
