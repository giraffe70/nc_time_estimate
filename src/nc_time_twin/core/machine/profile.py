from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class AxisProfile(BaseModel):
    rapid_velocity_mm_min: float = Field(default=12000.0, gt=0)
    max_velocity_mm_min: float = Field(default=12000.0, gt=0)
    max_acc_mm_s2: float = Field(default=1000.0, gt=0)
    max_jerk_mm_s3: float = Field(default=10000.0, gt=0)


class ControllerProfile(BaseModel):
    interpolation_period_ms: float = Field(default=2.0, gt=0)
    lookahead_blocks: int = Field(default=100, ge=0)
    junction_tolerance_mm: float = Field(default=0.01, ge=0)
    same_direction_angle_threshold_deg: float = Field(default=1.0, ge=0)
    reverse_angle_threshold_deg: float = Field(default=1.0, ge=0)
    lookahead_max_iterations: int = Field(default=8, ge=1)
    velocity_tolerance_mm_s: float = Field(default=1e-4, gt=0)
    phase2_max_samples_per_block: int = Field(default=1000, ge=10)
    dwell_p_unit: str = "ms"
    dwell_x_unit: str = "sec"

    @field_validator("dwell_p_unit", "dwell_x_unit")
    @classmethod
    def validate_dwell_unit(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"ms", "sec"}:
            raise ValueError("dwell unit must be 'ms' or 'sec'")
        return normalized


class EventTimeProfile(BaseModel):
    tool_change_sec: float = Field(default=8.0, ge=0)
    spindle_start_sec: float = Field(default=2.0, ge=0)
    spindle_stop_sec: float = Field(default=1.0, ge=0)
    coolant_on_sec: float = Field(default=0.5, ge=0)
    coolant_off_sec: float = Field(default=0.5, ge=0)
    optional_stop_sec: float = Field(default=0.0, ge=0)


class CycleProfile(BaseModel):
    peck_clearance_mm: float = Field(default=1.0, ge=0)


class TimeModelProfile(BaseModel):
    mode: str = "constant_velocity"

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"constant_velocity", "trapezoid", "phase2"}:
            raise ValueError("time model mode must be 'constant_velocity', 'trapezoid', or 'phase2'")
        return normalized


class ReferenceReturnProfile(BaseModel):
    mode: str = "unestimated"
    fixed_time_sec: float = Field(default=0.0, ge=0)
    position: dict[str, float] = Field(default_factory=lambda: {"X": 0.0, "Y": 0.0, "Z": 0.0})

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"unestimated", "fixed", "rapid"}:
            raise ValueError("reference return mode must be 'unestimated', 'fixed', or 'rapid'")
        return normalized

    @field_validator("position")
    @classmethod
    def normalize_position(cls, position: dict[str, float]) -> dict[str, float]:
        normalized = {axis.upper(): value for axis, value in position.items()}
        for axis in ("X", "Y", "Z"):
            normalized.setdefault(axis, 0.0)
        return normalized

    def axis_position(self, name: str) -> float:
        return self.position[name.upper()]


class MachineProfile(BaseModel):
    machine_name: str = "Default 3-Axis CNC"
    controller_name: str = "generic"
    kinematic_type: str = "3_axis"
    units: str = "mm"
    feed_unit: str = "mm_per_min"
    axes: dict[str, AxisProfile]
    rapid_feed_mm_min: float = Field(default=12000.0, gt=0)
    max_cut_feed_mm_min: float = Field(default=10000.0, gt=0)
    default_cut_feed_mm_min: float = Field(default=1000.0, gt=0)
    default_cut_acc_mm_s2: float = Field(default=800.0, gt=0)
    default_cut_jerk_mm_s3: float = Field(default=10000.0, gt=0)
    arc_tolerance_mm: float = Field(default=0.01, ge=0)
    arc_chord_tolerance_mm: float = Field(default=0.02, gt=0)
    controller: ControllerProfile = Field(default_factory=ControllerProfile)
    event_time: EventTimeProfile = Field(default_factory=EventTimeProfile)
    cycle: CycleProfile = Field(default_factory=CycleProfile)
    time_model: TimeModelProfile = Field(default_factory=TimeModelProfile)
    reference_return: ReferenceReturnProfile = Field(default_factory=ReferenceReturnProfile)

    @field_validator("units")
    @classmethod
    def validate_units(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"mm", "inch"}:
            raise ValueError("units must be 'mm' or 'inch'")
        return normalized

    @field_validator("feed_unit")
    @classmethod
    def validate_feed_unit(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"mm_per_min", "m_per_min", "inverse_time", "auto"}:
            raise ValueError("feed_unit must be 'mm_per_min', 'm_per_min', 'inverse_time', or 'auto'")
        return normalized

    @field_validator("kinematic_type")
    @classmethod
    def validate_kinematic_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized != "3_axis":
            raise ValueError("phase 2 MVP supports only kinematic_type '3_axis'")
        return normalized

    @field_validator("axes")
    @classmethod
    def normalize_axes(cls, axes: dict[str, AxisProfile]) -> dict[str, AxisProfile]:
        normalized = {name.upper(): profile for name, profile in axes.items()}
        for axis in ("X", "Y", "Z"):
            if axis not in normalized:
                raise ValueError(f"missing axis profile: {axis}")
        return normalized

    def axis(self, name: str) -> AxisProfile:
        return self.axes[name.upper()]


def load_machine_profile(path: str | Path) -> MachineProfile:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return MachineProfile.model_validate(data)
