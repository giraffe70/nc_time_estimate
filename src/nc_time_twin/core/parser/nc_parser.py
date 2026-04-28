from __future__ import annotations

from pathlib import Path

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    CoolantEventBlock,
    DwellBlock,
    LinearMoveBlock,
    OptionalStopBlock,
    Position,
    ProgramEndBlock,
    RapidMoveBlock,
    ReferenceReturnBlock,
    SmoothingEventBlock,
    SpindleEventBlock,
    ToolChangeBlock,
    UnknownBlock,
)
from nc_time_twin.core.ir.program import IRProgram
from nc_time_twin.core.machine.profile import MachineProfile
from nc_time_twin.core.parser.macro import (
    expand_macro_variables,
    is_macro_assignment,
    update_macro_table,
)
from nc_time_twin.core.parser.modal_state import (
    ModalState,
    convert_length,
    resolve_target_position,
    unit_factor,
    update_modal_state,
)
from nc_time_twin.core.parser.preprocess import preprocess_nc_lines
from nc_time_twin.core.parser.tokenizer import TokenizedLine, tokenize


def parse_nc_file(path: str | Path, machine_profile: MachineProfile) -> IRProgram:
    raw_lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    return parse_nc_lines(raw_lines, machine_profile)


def parse_nc_lines(raw_lines: list[str], machine_profile: MachineProfile) -> IRProgram:
    state = ModalState()
    macro_table: dict[str, float] = {}
    blocks: list[BaseBlock] = []

    for clean_line in preprocess_nc_lines(raw_lines):
        if is_macro_assignment(clean_line.clean):
            update_macro_table(clean_line.clean, macro_table)
            continue

        expanded, macro_warnings = expand_macro_variables(clean_line.clean, macro_table)
        tokens = tokenize(expanded)
        prev_state = state.clone()
        modal_warnings = update_modal_state(state, tokens)
        line_blocks = build_ir_blocks(
            line_no=clean_line.line_no,
            raw=clean_line.raw,
            tokens=tokens,
            prev_state=prev_state,
            state=state,
            machine_profile=machine_profile,
        )
        warnings = [*macro_warnings, *tokens.warnings, *modal_warnings]
        if warnings and line_blocks:
            line_blocks[0].warnings.extend(warnings)
        elif warnings:
            line_blocks.append(
                UnknownBlock(
                    line_no=clean_line.line_no,
                    raw=clean_line.raw,
                    reason="; ".join(warnings),
                    warnings=warnings,
                )
            )
        blocks.extend(line_blocks)

    program = IRProgram(blocks)
    return program


def build_ir_blocks(
    line_no: int,
    raw: str,
    tokens: TokenizedLine,
    prev_state: ModalState,
    state: ModalState,
    machine_profile: MachineProfile,
) -> list[BaseBlock]:
    blocks: list[BaseBlock] = []

    blocks.extend(_build_m_code_blocks(line_no, raw, tokens, state))
    if tokens.contains_g(5):
        blocks.append(SmoothingEventBlock(line_no=line_no, raw=raw, code="G5"))

    if tokens.contains_g(4):
        blocks.append(
            DwellBlock(
                line_no=line_no,
                raw=raw,
                dwell_time_sec=parse_dwell_time(tokens, machine_profile),
            )
        )
        return blocks

    if tokens.contains_g(28) or tokens.contains_g(30):
        code = "G28" if tokens.contains_g(28) else "G30"
        blocks.append(
            ReferenceReturnBlock(
                line_no=line_no,
                raw=raw,
                start=prev_state.current_position,
                code=code,
                axes=_reference_return_axes(tokens),
            )
        )
        _apply_reference_return_position(state, prev_state.current_position, tokens, machine_profile)
        return blocks

    if state.canned_cycle and _should_expand_cycle(tokens):
        blocks.extend(_expand_canned_cycle(line_no, raw, tokens, prev_state, state, machine_profile))
        return blocks

    if tokens.has_any_axis():
        if state.motion is None:
            blocks.append(
                UnknownBlock(
                    line_no=line_no,
                    raw=raw,
                    reason="axis words without active motion",
                    warnings=["Axis words found without active G00/G01/G02/G03 motion"],
                )
            )
            return blocks
        resolve_state = state.clone()
        resolve_state.current_position = prev_state.current_position
        start = prev_state.current_position
        end = resolve_target_position(tokens, resolve_state)

        if state.motion == "G00":
            block: BaseBlock = RapidMoveBlock(line_no=line_no, raw=raw, start=start, end=end)
        elif state.motion == "G01":
            block = LinearMoveBlock(
                line_no=line_no,
                raw=raw,
                start=start,
                end=end,
                feedrate=state.feedrate,
                feed_mode=state.feed_mode,
                spindle_speed=state.spindle_speed,
                unit=state.unit,
            )
        elif state.motion in {"G02", "G03"}:
            factor = unit_factor(state.unit)
            block = ArcMoveBlock(
                line_no=line_no,
                raw=raw,
                start=start,
                end=end,
                direction=state.motion,
                plane=state.plane,
                ijk=(
                    _scale_optional(tokens.get_float("I"), factor),
                    _scale_optional(tokens.get_float("J"), factor),
                    _scale_optional(tokens.get_float("K"), factor),
                ),
                r=_scale_optional(tokens.get_float("R"), factor),
                feedrate=state.feedrate,
                feed_mode=state.feed_mode,
                spindle_speed=state.spindle_speed,
                unit=state.unit,
            )
        else:
            block = UnknownBlock(
                line_no=line_no,
                raw=raw,
                reason=f"unsupported active motion {state.motion}",
                warnings=[f"Unsupported active motion: {state.motion}"],
            )
        blocks.append(block)
        state.current_position = end

    return blocks


def _build_m_code_blocks(
    line_no: int,
    raw: str,
    tokens: TokenizedLine,
    state: ModalState,
) -> list[BaseBlock]:
    blocks: list[BaseBlock] = []
    for m_code in tokens.m_codes():
        if m_code == 1:
            blocks.append(OptionalStopBlock(line_no=line_no, raw=raw))
        elif m_code == 6:
            blocks.append(ToolChangeBlock(line_no=line_no, raw=raw, tool_id=state.current_tool))
        elif m_code in {3, 4}:
            blocks.append(
                SpindleEventBlock(
                    line_no=line_no,
                    raw=raw,
                    event="spindle_start",
                    spindle_speed=state.spindle_speed,
                )
            )
        elif m_code == 5:
            blocks.append(SpindleEventBlock(line_no=line_no, raw=raw, event="spindle_stop"))
        elif m_code == 8:
            blocks.append(CoolantEventBlock(line_no=line_no, raw=raw, event="coolant_on"))
        elif m_code == 9:
            blocks.append(CoolantEventBlock(line_no=line_no, raw=raw, event="coolant_off"))
        elif m_code == 30:
            blocks.append(ProgramEndBlock(line_no=line_no, raw=raw))
    return blocks


def _reference_return_axes(tokens: TokenizedLine) -> tuple[str, ...]:
    axes = tuple(letter for letter in ("X", "Y", "Z") if tokens.get_float(letter) is not None)
    return axes or ("X", "Y", "Z")


def _apply_reference_return_position(
    state: ModalState,
    start: Position,
    tokens: TokenizedLine,
    machine_profile: MachineProfile,
) -> None:
    axes = _reference_return_axes(tokens)
    reference = machine_profile.reference_return
    state.current_position = Position(
        x=reference.axis_position("X") if "X" in axes else start.x,
        y=reference.axis_position("Y") if "Y" in axes else start.y,
        z=reference.axis_position("Z") if "Z" in axes else start.z,
    )


def _should_expand_cycle(tokens: TokenizedLine) -> bool:
    return tokens.has_any_axis() or any(code in {81, 82, 83} for code in tokens.g_codes())


def _expand_canned_cycle(
    line_no: int,
    raw: str,
    tokens: TokenizedLine,
    prev_state: ModalState,
    state: ModalState,
    machine_profile: MachineProfile,
) -> list[BaseBlock]:
    warnings: list[str] = []
    current = prev_state.current_position
    factor = unit_factor(state.unit)

    target_xy = _resolve_cycle_xy(tokens, state, current, factor)
    z_depth = _cycle_coordinate("Z", tokens, state, current.z, factor, warnings)
    r_plane = _cycle_coordinate("R", tokens, state, current.z, factor, warnings)

    if z_depth is None or r_plane is None:
        return [
            UnknownBlock(
                line_no=line_no,
                raw=raw,
                reason="invalid canned cycle",
                warnings=warnings or ["Canned cycle requires Z and R values"],
            )
        ]

    p_xy = Position(target_xy.x, target_xy.y, current.z)
    p_r = Position(target_xy.x, target_xy.y, r_plane)
    p_z = Position(target_xy.x, target_xy.y, z_depth)

    blocks: list[BaseBlock] = [
        RapidMoveBlock(line_no=line_no, raw=raw, start=current, end=p_xy),
        RapidMoveBlock(line_no=line_no, raw=raw, start=p_xy, end=p_r),
    ]

    if state.canned_cycle == "G83":
        q_depth = _cycle_distance("Q", tokens, state, factor, warnings)
        if q_depth is None or q_depth <= 0:
            blocks.append(
                UnknownBlock(
                    line_no=line_no,
                    raw=raw,
                    reason="invalid G83 cycle",
                    warnings=warnings or ["G83 requires positive Q peck depth"],
                )
            )
            return blocks
        blocks.extend(
            _expand_g83_pecks(
                line_no=line_no,
                raw=raw,
                start=p_r,
                final_z=z_depth,
                q_depth=q_depth,
                state=state,
                machine_profile=machine_profile,
            )
        )
    else:
        blocks.append(
            LinearMoveBlock(
                line_no=line_no,
                raw=raw,
                start=p_r,
                end=p_z,
                feedrate=state.feedrate,
                feed_mode=state.feed_mode,
                spindle_speed=state.spindle_speed,
                unit=state.unit,
            )
        )
        if state.canned_cycle == "G82":
            dwell = _parse_cycle_dwell(tokens, state, machine_profile)
            blocks.append(DwellBlock(line_no=line_no, raw=raw, start=p_z, end=p_z, dwell_time_sec=dwell))
        blocks.append(RapidMoveBlock(line_no=line_no, raw=raw, start=p_z, end=p_r))

    if warnings:
        blocks[0].warnings.extend(warnings)
    state.current_position = p_r
    return blocks


def _expand_g83_pecks(
    line_no: int,
    raw: str,
    start: Position,
    final_z: float,
    q_depth: float,
    state: ModalState,
    machine_profile: MachineProfile,
) -> list[BaseBlock]:
    blocks: list[BaseBlock] = []
    direction = -1.0 if final_z < start.z else 1.0
    current_z = start.z
    target_x, target_y = start.x, start.y

    def remaining() -> bool:
        return (final_z - current_z) * direction > 1e-9

    while remaining():
        next_z = current_z + direction * q_depth
        if (final_z - next_z) * direction < 0:
            next_z = final_z

        p_cut_start = Position(target_x, target_y, current_z)
        p_cut_end = Position(target_x, target_y, next_z)
        blocks.append(
            LinearMoveBlock(
                line_no=line_no,
                raw=raw,
                start=p_cut_start,
                end=p_cut_end,
                feedrate=state.feedrate,
                feed_mode=state.feed_mode,
                spindle_speed=state.spindle_speed,
                unit=state.unit,
            )
        )
        p_retract = Position(target_x, target_y, start.z)
        blocks.append(RapidMoveBlock(line_no=line_no, raw=raw, start=p_cut_end, end=p_retract))

        current_z = next_z
        if remaining():
            approach_z = current_z - direction * machine_profile.cycle.peck_clearance_mm
            if (approach_z - start.z) * direction < 0:
                approach_z = start.z
            p_approach = Position(target_x, target_y, approach_z)
            blocks.append(RapidMoveBlock(line_no=line_no, raw=raw, start=p_retract, end=p_approach))
            current_z = approach_z
    return blocks


def parse_dwell_time(tokens: TokenizedLine, machine_profile: MachineProfile) -> float:
    if tokens.get_float("P") is not None:
        return _convert_dwell_value(tokens.get_float("P") or 0.0, machine_profile.controller.dwell_p_unit)
    if tokens.get_float("X") is not None:
        return _convert_dwell_value(tokens.get_float("X") or 0.0, machine_profile.controller.dwell_x_unit)
    return 0.0


def _parse_cycle_dwell(tokens: TokenizedLine, state: ModalState, machine_profile: MachineProfile) -> float:
    value = tokens.get_float("P")
    if value is None:
        value = state.cycle_params.get("P")
    if value is None:
        return 0.0
    return _convert_dwell_value(value, machine_profile.controller.dwell_p_unit)


def _convert_dwell_value(value: float, unit: str) -> float:
    return value / 1000.0 if unit == "ms" else value


def _resolve_cycle_xy(tokens: TokenizedLine, state: ModalState, current: Position, factor: float) -> Position:
    input_x = tokens.get_float("X")
    input_y = tokens.get_float("Y")
    if state.distance_mode == "G90":
        return Position(
            x=input_x * factor if input_x is not None else current.x,
            y=input_y * factor if input_y is not None else current.y,
            z=current.z,
        )
    return Position(
        x=current.x + (input_x * factor if input_x is not None else 0.0),
        y=current.y + (input_y * factor if input_y is not None else 0.0),
        z=current.z,
    )


def _cycle_coordinate(
    letter: str,
    tokens: TokenizedLine,
    state: ModalState,
    reference: float,
    factor: float,
    warnings: list[str],
) -> float | None:
    value = tokens.get_float(letter)
    if value is None:
        value = state.cycle_params.get(letter)
    if value is None:
        warnings.append(f"Canned cycle requires {letter} value")
        return None
    if state.distance_mode == "G91":
        return reference + value * factor
    return value * factor


def _cycle_distance(
    letter: str,
    tokens: TokenizedLine,
    state: ModalState,
    factor: float,
    warnings: list[str],
) -> float | None:
    value = tokens.get_float(letter)
    if value is None:
        value = state.cycle_params.get(letter)
    if value is None:
        warnings.append(f"Canned cycle requires {letter} value")
        return None
    return abs(value * factor)


def _scale_optional(value: float | None, factor: float) -> float | None:
    return value * factor if value is not None else None
