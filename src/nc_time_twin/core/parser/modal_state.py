from __future__ import annotations

from dataclasses import dataclass, field
import copy

from nc_time_twin.core.ir.blocks import Position
from nc_time_twin.core.parser.tokenizer import TokenizedLine


SUPPORTED_G = {0, 1, 2, 3, 4, 17, 18, 19, 20, 21, 80, 81, 82, 83, 90, 91, 93, 94, 95}
SUPPORTED_M = {3, 4, 5, 6, 8, 9, 30}


@dataclass
class ModalState:
    motion: str | None = None
    plane: str = "G17"
    distance_mode: str = "G90"
    unit: str = "mm"
    feed_mode: str = "G94"
    feedrate: float | None = None
    spindle_speed: float | None = None
    current_position: Position = field(default_factory=Position)
    current_tool: int | None = None
    coolant_on: bool = False
    spindle_on: bool = False
    canned_cycle: str | None = None
    cycle_params: dict[str, float] = field(default_factory=dict)

    def clone(self) -> ModalState:
        return copy.deepcopy(self)


def update_modal_state(state: ModalState, tokens: TokenizedLine) -> list[str]:
    warnings: list[str] = []
    for g in tokens.g_codes():
        if g not in SUPPORTED_G:
            warnings.append(f"Unsupported G-code: G{g}")
            continue
        if g == 0:
            state.motion = "G00"
            state.canned_cycle = None
        elif g == 1:
            state.motion = "G01"
            state.canned_cycle = None
        elif g == 2:
            state.motion = "G02"
            state.canned_cycle = None
        elif g == 3:
            state.motion = "G03"
            state.canned_cycle = None
        elif g in {81, 82, 83}:
            state.canned_cycle = f"G{g:02d}"
        elif g == 80:
            state.canned_cycle = None
        elif g == 17:
            state.plane = "G17"
        elif g == 18:
            state.plane = "G18"
        elif g == 19:
            state.plane = "G19"
        elif g == 20:
            state.unit = "inch"
        elif g == 21:
            state.unit = "mm"
        elif g == 90:
            state.distance_mode = "G90"
        elif g == 91:
            state.distance_mode = "G91"
        elif g == 93:
            state.feed_mode = "G93"
        elif g == 94:
            state.feed_mode = "G94"
        elif g == 95:
            state.feed_mode = "G95"

    if tokens.get_float("F") is not None:
        state.feedrate = tokens.get_float("F")
    if tokens.get_float("S") is not None:
        state.spindle_speed = tokens.get_float("S")
    if tokens.get_float("T") is not None:
        state.current_tool = int(tokens.get_float("T") or 0)

    for letter in ("Z", "R", "Q", "P"):
        value = tokens.get_float(letter)
        if value is not None:
            state.cycle_params[letter] = value

    for m in tokens.m_codes():
        if m not in SUPPORTED_M:
            warnings.append(f"Unsupported M-code: M{m}")
            continue
        if m in {3, 4}:
            state.spindle_on = True
        elif m == 5:
            state.spindle_on = False
        elif m == 8:
            state.coolant_on = True
        elif m == 9:
            state.coolant_on = False

    return warnings


def unit_factor(unit: str) -> float:
    return 25.4 if unit == "inch" else 1.0


def convert_length(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return value * unit_factor(unit)


def resolve_target_position(tokens: TokenizedLine, state: ModalState) -> Position:
    factor = unit_factor(state.unit)
    current = state.current_position
    input_x = tokens.get_float("X")
    input_y = tokens.get_float("Y")
    input_z = tokens.get_float("Z")

    if state.distance_mode == "G90":
        return Position(
            x=input_x * factor if input_x is not None else current.x,
            y=input_y * factor if input_y is not None else current.y,
            z=input_z * factor if input_z is not None else current.z,
        )
    return Position(
        x=current.x + (input_x * factor if input_x is not None else 0.0),
        y=current.y + (input_y * factor if input_y is not None else 0.0),
        z=current.z + (input_z * factor if input_z is not None else 0.0),
    )
