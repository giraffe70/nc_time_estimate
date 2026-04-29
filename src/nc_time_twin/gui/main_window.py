from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QScrollArea,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional GUI dependency
    raise SystemExit("PySide6 is required for the GUI. Install project requirements first.") from exc

import yaml

from nc_time_twin.api import estimate_nc_time
from nc_time_twin.core.feed_normalizer import normalize_feed_file
from nc_time_twin.core.machine.benchmark_generator import generate_benchmark_nc_code
from nc_time_twin.core.machine.calibration import calibrate_machine_profile_from_csv
from nc_time_twin.core.machine.profile import MachineProfile, load_machine_profile
from nc_time_twin.core.report.auto_outputs import manual_export_path_in_dir, write_auto_log
from nc_time_twin.core.report.exporters import export_result
from nc_time_twin.core.report.result_model import EstimateResult


ALWAYS_VISIBLE_PROFILE_KEYS = {
    "machine_name",
    "controller_name",
    "kinematic_type",
    "units",
}
CONSTANT_VELOCITY_FIELDS = {
    "feed_unit",
    "max_cut_feed_mm_min",
    "default_cut_feed_mm_min",
    "axes.X.rapid_velocity_mm_min",
    "axes.Y.rapid_velocity_mm_min",
    "axes.Z.rapid_velocity_mm_min",
    "arc_tolerance_mm",
    "controller.dwell_p_unit",
    "controller.dwell_x_unit",
    "event_time.tool_change_sec",
    "event_time.spindle_start_sec",
    "event_time.spindle_stop_sec",
    "event_time.coolant_on_sec",
    "event_time.coolant_off_sec",
    "event_time.optional_stop_sec",
    "cycle.peck_clearance_mm",
    "reference_return.mode",
    "reference_return.fixed_time_sec",
    "reference_return.position.X",
    "reference_return.position.Y",
    "reference_return.position.Z",
}
TRAPEZOID_FIELDS = CONSTANT_VELOCITY_FIELDS | {"default_cut_acc_mm_s2"}
PHASE2_FIELDS = TRAPEZOID_FIELDS | {
    "rapid_feed_mm_min",
    "default_cut_jerk_mm_s3",
    "arc_chord_tolerance_mm",
    "axes.X.max_velocity_mm_min",
    "axes.X.max_acc_mm_s2",
    "axes.X.max_jerk_mm_s3",
    "axes.Y.max_velocity_mm_min",
    "axes.Y.max_acc_mm_s2",
    "axes.Y.max_jerk_mm_s3",
    "axes.Z.max_velocity_mm_min",
    "axes.Z.max_acc_mm_s2",
    "axes.Z.max_jerk_mm_s3",
    "controller.interpolation_period_ms",
    "controller.lookahead_blocks",
    "controller.junction_tolerance_mm",
    "controller.same_direction_angle_threshold_deg",
    "controller.reverse_angle_threshold_deg",
    "controller.lookahead_max_iterations",
    "controller.velocity_tolerance_mm_s",
    "controller.phase2_max_samples_per_block",
}
TIME_MODEL_PROFILE_KEYS = {
    "constant_velocity": CONSTANT_VELOCITY_FIELDS,
    "trapezoid": TRAPEZOID_FIELDS,
    "phase2": PHASE2_FIELDS,
}
TIME_MODEL_DESCRIPTIONS = {
    "constant_velocity": "Constant Velocity：固定速度估算。需設定 Feed、Rapid、Event、Dwell、Cycle 與 Reference Return 參數。",
    "trapezoid": "Trapezoid：含切削加減速。除固定速度參數外，需設定「切削加速度」，用來估算起步加速與結尾減速。",
    "phase2": "精準動態估算（含加減速與轉角降速）。用更接近真實機台的方式估算，會考慮各軸速度能力、加減速平順度、轉角降速、連續短線段與圓弧路徑。",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NC-Time-Twin")
        self.resize(1180, 820)
        self.result: EstimateResult | None = None
        self.log_path: Path | None = None

        self.project_root = Path(__file__).resolve().parents[3]
        self.default_profile = str((self.project_root / "profiles/default_3axis.yaml").resolve())
        self.default_output_dir = str((self.project_root / "output").resolve())
        self.nc_path = QLineEdit()
        self.profile_path = QLineEdit()
        self.profile_path.setPlaceholderText("可不選；選擇後會載入參數到下方 UI")
        self.status_label = QLabel("就緒")
        self.project_summary = QPlainTextEdit()
        self.project_summary.setReadOnly(True)
        self.project_summary.setMinimumHeight(150)

        self.time_model = QComboBox()
        self.time_model.addItem("快速估算（固定速度）", "constant_velocity")
        self.time_model.addItem("標準估算（含加減速）", "trapezoid")
        self.time_model.addItem("精準估算（機台動態）", "phase2")
        self.time_model.currentIndexChanged.connect(self._apply_time_model_visibility)
        self.time_model_parameter_hint = QLabel()
        self.time_model_parameter_hint.setWordWrap(True)
        self.strict_feed = QCheckBox("嚴格檢查 G21/G94 進給")
        self.fail_on_sanity_error = QCheckBox("顯示 Feed sanity 失敗警示")

        self.export_dir = QLineEdit(self.default_output_dir)
        self.export_checks = {
            "json": QCheckBox("JSON"),
            "csv": QCheckBox("CSV"),
            "xlsx": QCheckBox("Excel"),
            "html": QCheckBox("HTML"),
        }

        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(150)
        self.warning_text = QPlainTextEdit()
        self.warning_text.setReadOnly(True)
        self.warning_text.setMinimumHeight(120)
        self.table = QTableWidget()
        self.chart_container = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_container)

        self.profile_inputs: dict[str, object] = {}
        self.axis_inputs: dict[str, dict[str, QDoubleSpinBox]] = {}
        self.profile_row_widgets: dict[str, list[QWidget]] = {}
        self._build_tool_controls()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_project_tab(), "估測")
        self.tabs.addTab(self._build_tools_tab(), "Tools")
        self.tabs.addTab(self._build_table_tab(), "Blocks")
        self.tabs.addTab(self._build_chart_tab(), "Charts")
        self.setCentralWidget(self.tabs)

    def _build_project_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QGridLayout()
        form.addWidget(QLabel("NC-Code"), 0, 0)
        form.addWidget(self.nc_path, 0, 1)
        nc_button = QPushButton("瀏覽")
        nc_button.clicked.connect(self._browse_nc)
        form.addWidget(nc_button, 0, 2)

        form.addWidget(QLabel("Machine Profile"), 1, 0)
        form.addWidget(self.profile_path, 1, 1)
        profile_button = QPushButton("瀏覽")
        profile_button.clicked.connect(self._browse_profile)
        form.addWidget(profile_button, 1, 2)
        load_profile_button = QPushButton("載入參數")
        load_profile_button.clicked.connect(self._load_profile_from_path)
        form.addWidget(load_profile_button, 1, 3)

        form.addWidget(QLabel("Time Model"), 2, 0)
        form.addWidget(self.time_model, 2, 1)
        form.addWidget(self.time_model_parameter_hint, 3, 1, 1, 3)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)

        self._build_profile_controls()
        layout.addWidget(self._build_profile_group())
        layout.addWidget(self._build_advanced_group())

        action_row = QHBoxLayout()
        estimate_button = QPushButton("Estimate")
        estimate_button.clicked.connect(self._estimate)
        action_row.addWidget(estimate_button)
        action_row.addWidget(self.status_label)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        layout.addWidget(QLabel("估測摘要"))
        layout.addWidget(self.project_summary)
        layout.addWidget(QLabel("完整 Results"))
        layout.addWidget(self.summary_text)
        layout.addWidget(QLabel("Warnings"))
        layout.addWidget(self.warning_text)
        layout.addWidget(self._build_export_group())
        layout.addStretch(1)
        scroll.setWidget(widget)
        return scroll

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("進階估測設定")
        self.advanced_group = group

        container = QWidget()
        form = QGridLayout(container)
        form.addWidget(self.strict_feed, 0, 1)
        form.addWidget(self.fail_on_sanity_error, 1, 1)
        form.setColumnStretch(1, 1)

        layout = QVBoxLayout(group)
        layout.addWidget(container)
        return group

    def _build_profile_controls(self) -> None:
        if self.profile_inputs:
            return
        self.profile_inputs = {
            "machine_name": QLineEdit(),
            "controller_name": QLineEdit(),
            "kinematic_type": QLineEdit("3_axis"),
            "units": self._combo(["mm", "inch"]),
            "feed_unit": self._combo(["auto", "mm_per_min", "m_per_min", "inverse_time"]),
            "rapid_feed_mm_min": self._double(1, 1_000_000, 0),
            "max_cut_feed_mm_min": self._double(1, 1_000_000, 0),
            "default_cut_feed_mm_min": self._double(1, 1_000_000, 0),
            "default_cut_acc_mm_s2": self._double(0.001, 1_000_000, 3),
            "default_cut_jerk_mm_s3": self._double(0.001, 100_000_000, 3),
            "arc_tolerance_mm": self._double(0, 1000, 6),
            "arc_chord_tolerance_mm": self._double(0.000001, 1000, 6),
            "controller.interpolation_period_ms": self._double(0.001, 100_000, 3),
            "controller.lookahead_blocks": self._int(0, 1_000_000),
            "controller.junction_tolerance_mm": self._double(0, 1000, 6),
            "controller.same_direction_angle_threshold_deg": self._double(0, 180, 3),
            "controller.reverse_angle_threshold_deg": self._double(0, 180, 3),
            "controller.lookahead_max_iterations": self._int(1, 1_000_000),
            "controller.velocity_tolerance_mm_s": self._double(0.000001, 1000, 6),
            "controller.phase2_max_samples_per_block": self._int(10, 10_000_000),
            "controller.dwell_p_unit": self._combo(["ms", "sec"]),
            "controller.dwell_x_unit": self._combo(["sec", "ms"]),
            "event_time.tool_change_sec": self._double(0, 100_000, 3),
            "event_time.spindle_start_sec": self._double(0, 100_000, 3),
            "event_time.spindle_stop_sec": self._double(0, 100_000, 3),
            "event_time.coolant_on_sec": self._double(0, 100_000, 3),
            "event_time.coolant_off_sec": self._double(0, 100_000, 3),
            "event_time.optional_stop_sec": self._double(0, 100_000, 3),
            "cycle.peck_clearance_mm": self._double(0, 100_000, 3),
            "reference_return.mode": self._combo(["unestimated", "fixed", "rapid"]),
            "reference_return.fixed_time_sec": self._double(0, 100_000, 3),
            "reference_return.position.X": self._double(-1_000_000, 1_000_000, 3),
            "reference_return.position.Y": self._double(-1_000_000, 1_000_000, 3),
            "reference_return.position.Z": self._double(-1_000_000, 1_000_000, 3),
        }
        for axis in ("X", "Y", "Z"):
            self.axis_inputs[axis] = {
                "rapid_velocity_mm_min": self._double(0.001, 1_000_000, 3),
                "max_velocity_mm_min": self._double(0.001, 1_000_000, 3),
                "max_acc_mm_s2": self._double(0.001, 1_000_000, 3),
                "max_jerk_mm_s3": self._double(0.001, 100_000_000, 3),
            }
        self._apply_profile_to_ui(load_machine_profile(self.default_profile))

    def _build_profile_group(self) -> QGroupBox:
        group = QGroupBox("Machine Profile 參數（可直接修改；上傳 Profile 只是載入這些欄位）")
        group.setCheckable(True)
        group.setChecked(False)
        container = QWidget()
        form = QGridLayout(container)

        rows = [
            ("machine_name", "Machine Name"),
            ("controller_name", "Controller Name"),
            ("kinematic_type", "Kinematic Type"),
            ("units", "Units"),
            ("feed_unit", "Feed Unit"),
            ("rapid_feed_mm_min", "Rapid Feed mm/min"),
            ("max_cut_feed_mm_min", "Max Cut Feed mm/min"),
            ("default_cut_feed_mm_min", "Default Cut Feed mm/min"),
            ("default_cut_acc_mm_s2", "Default Cut Acc mm/s^2"),
            ("default_cut_jerk_mm_s3", "Default Cut Jerk mm/s^3"),
            ("arc_tolerance_mm", "Arc Tolerance mm"),
            ("arc_chord_tolerance_mm", "Arc Chord Tolerance mm"),
        ]
        for row, (key, label) in enumerate(rows):
            label_widget = QLabel(label)
            form.addWidget(label_widget, row, 0)
            form.addWidget(self.profile_inputs[key], row, 1)
            self._track_profile_row(key, label_widget, self.profile_inputs[key])

        start_row = len(rows)
        for axis_index, axis in enumerate(("X", "Y", "Z")):
            col = axis_index * 2
            form.addWidget(QLabel(f"{axis} Axis"), start_row, col)
            for offset, key in enumerate(
                ("rapid_velocity_mm_min", "max_velocity_mm_min", "max_acc_mm_s2", "max_jerk_mm_s3"),
                start=1,
            ):
                label_widget = QLabel(key)
                form.addWidget(label_widget, start_row + offset, col)
                form.addWidget(self.axis_inputs[axis][key], start_row + offset, col + 1)
                self._track_profile_row(f"axes.{axis}.{key}", label_widget, self.axis_inputs[axis][key])

        controller_row = start_row + 6
        controller_rows = [
            ("controller.interpolation_period_ms", "Interpolation Period ms"),
            ("controller.lookahead_blocks", "Lookahead Blocks"),
            ("controller.junction_tolerance_mm", "Junction Tolerance mm"),
            ("controller.same_direction_angle_threshold_deg", "Same Direction Angle deg"),
            ("controller.reverse_angle_threshold_deg", "Reverse Angle deg"),
            ("controller.lookahead_max_iterations", "Lookahead Max Iterations"),
            ("controller.velocity_tolerance_mm_s", "Velocity Tolerance mm/s"),
            ("controller.phase2_max_samples_per_block", "Phase2 Max Samples/Block"),
            ("controller.dwell_p_unit", "Dwell P Unit"),
            ("controller.dwell_x_unit", "Dwell X Unit"),
        ]
        for offset, (key, label) in enumerate(controller_rows):
            label_widget = QLabel(label)
            form.addWidget(label_widget, controller_row + offset, 0)
            form.addWidget(self.profile_inputs[key], controller_row + offset, 1)
            self._track_profile_row(key, label_widget, self.profile_inputs[key])

        event_rows = [
            ("event_time.tool_change_sec", "Tool Change sec"),
            ("event_time.spindle_start_sec", "Spindle Start sec"),
            ("event_time.spindle_stop_sec", "Spindle Stop sec"),
            ("event_time.coolant_on_sec", "Coolant On sec"),
            ("event_time.coolant_off_sec", "Coolant Off sec"),
            ("event_time.optional_stop_sec", "Optional Stop sec"),
            ("cycle.peck_clearance_mm", "G83 Peck Clearance mm"),
            ("reference_return.mode", "Reference Return Mode"),
            ("reference_return.fixed_time_sec", "Reference Fixed sec"),
            ("reference_return.position.X", "Reference X"),
            ("reference_return.position.Y", "Reference Y"),
            ("reference_return.position.Z", "Reference Z"),
        ]
        for offset, (key, label) in enumerate(event_rows):
            label_widget = QLabel(label)
            form.addWidget(label_widget, controller_row + offset, 2)
            form.addWidget(self.profile_inputs[key], controller_row + offset, 3)
            self._track_profile_row(key, label_widget, self.profile_inputs[key])

        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        layout = QVBoxLayout(group)
        layout.addWidget(container)
        container.setVisible(False)
        group.toggled.connect(container.setVisible)
        self._apply_time_model_visibility()
        return group

    def _track_profile_row(self, key: str, label: QWidget, widget: QWidget) -> None:
        self.profile_row_widgets[key] = [label, widget]

    def _combo(self, values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        return combo

    def _double(self, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(1.0)
        return spin

    def _int(self, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        return spin

    def _build_export_group(self) -> QGroupBox:
        group = QGroupBox("報表輸出")
        layout = QGridLayout(group)
        note = QLabel("Estimate 只會自動產生 log；Report 只有按下「輸出報表」後才會寫入選定資料夾。")
        layout.addWidget(note, 0, 0, 1, 3)
        layout.addWidget(QLabel("輸出資料夾"), 1, 0)
        layout.addWidget(self.export_dir, 1, 1)
        browse_button = QPushButton("選擇資料夾")
        browse_button.clicked.connect(self._browse_export_dir)
        layout.addWidget(browse_button, 1, 2)

        format_row = QHBoxLayout()
        for checkbox in self.export_checks.values():
            format_row.addWidget(checkbox)
        format_row.addStretch(1)
        layout.addLayout(format_row, 2, 1)

        export_button = QPushButton("輸出報表")
        export_button.clicked.connect(self._export_reports)
        layout.addWidget(export_button, 3, 1)
        layout.setColumnStretch(1, 1)
        return group

    def _build_table_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.table)
        return widget

    def _build_chart_tab(self) -> QWidget:
        return self.chart_container

    def _build_tool_controls(self) -> None:
        self.normalize_nc_path = QLineEdit()
        self.normalize_profile_path = QLineEdit(self.default_profile)
        self.normalize_out_path = QLineEdit(str((self.project_root / "output/normalized.nc").resolve()))
        self.normalize_input_unit = QComboBox()
        self.normalize_input_unit.addItems(["m_per_min", "mm_per_min"])
        self.normalize_summary = QPlainTextEdit()
        self.normalize_summary.setReadOnly(True)

        self.benchmark_profile_path = QLineEdit(self.default_profile)
        self.benchmark_out_path = QLineEdit(str((self.project_root / "output/phase2_benchmark.nc").resolve()))
        self.benchmark_summary = QPlainTextEdit()
        self.benchmark_summary.setReadOnly(True)

        self.calibration_dataset_path = QLineEdit()
        self.calibration_profile_path = QLineEdit(str((self.project_root / "profiles/default_phase2_3axis.yaml").resolve()))
        self.calibration_out_path = QLineEdit(str((self.project_root / "profiles/calibrated_phase2.yaml").resolve()))
        self.calibration_nc_base_dir = QLineEdit()
        self.calibration_summary = QPlainTextEdit()
        self.calibration_summary.setReadOnly(True)

    def _build_tools_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        tool_tabs = QTabWidget()
        tool_tabs.addTab(self._build_normalize_tab(), "Feed 正規化")
        tool_tabs.addTab(self._build_benchmark_tab(), "Benchmark")
        tool_tabs.addTab(self._build_calibration_tab(), "Profile 校正")
        layout.addWidget(tool_tabs)
        return widget

    def _build_normalize_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QGridLayout()
        self._add_path_row(form, 0, "NC-Code", self.normalize_nc_path, self._browse_normalize_nc)
        self._add_path_row(form, 1, "Machine Profile", self.normalize_profile_path, self._browse_normalize_profile)
        self._add_save_path_row(form, 2, "輸出 NC", self.normalize_out_path, self._browse_normalize_out)
        form.addWidget(QLabel("輸入 Feed 單位"), 3, 0)
        form.addWidget(self.normalize_input_unit, 3, 1)
        layout.addLayout(form)
        run_button = QPushButton("執行 Feed 正規化")
        run_button.clicked.connect(self._run_normalize_feed)
        layout.addWidget(run_button)
        layout.addWidget(self.normalize_summary)
        return widget

    def _build_benchmark_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QGridLayout()
        self._add_path_row(form, 0, "Machine Profile", self.benchmark_profile_path, self._browse_benchmark_profile)
        self._add_save_path_row(form, 1, "輸出 NC", self.benchmark_out_path, self._browse_benchmark_out)
        layout.addLayout(form)
        run_button = QPushButton("產生 Benchmark")
        run_button.clicked.connect(self._run_generate_benchmark)
        layout.addWidget(run_button)
        layout.addWidget(self.benchmark_summary)
        return widget

    def _build_calibration_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QGridLayout()
        self._add_path_row(form, 0, "Dataset CSV", self.calibration_dataset_path, self._browse_calibration_dataset)
        self._add_path_row(form, 1, "Base Profile", self.calibration_profile_path, self._browse_calibration_profile)
        self._add_save_path_row(form, 2, "輸出 Profile", self.calibration_out_path, self._browse_calibration_out)
        self._add_directory_row(form, 3, "NC Base Dir", self.calibration_nc_base_dir, self._browse_calibration_nc_base)
        layout.addLayout(form)
        run_button = QPushButton("執行 Profile 校正")
        run_button.clicked.connect(self._run_calibrate_profile)
        layout.addWidget(run_button)
        layout.addWidget(self.calibration_summary)
        return widget

    def _add_path_row(self, layout: QGridLayout, row: int, label: str, field: QLineEdit, callback) -> None:
        layout.addWidget(QLabel(label), row, 0)
        layout.addWidget(field, row, 1)
        button = QPushButton("瀏覽")
        button.clicked.connect(callback)
        layout.addWidget(button, row, 2)
        layout.setColumnStretch(1, 1)

    def _add_save_path_row(self, layout: QGridLayout, row: int, label: str, field: QLineEdit, callback) -> None:
        self._add_path_row(layout, row, label, field, callback)

    def _add_directory_row(self, layout: QGridLayout, row: int, label: str, field: QLineEdit, callback) -> None:
        self._add_path_row(layout, row, label, field, callback)

    def _browse_nc(self) -> None:
        self._browse_file_into(self.nc_path, "選擇 NC-Code", "NC files (*.nc *.tap *.gcode *.txt);;All files (*)")

    def _browse_profile(self) -> None:
        self._browse_file_into(self.profile_path, "選擇 Machine Profile", "YAML files (*.yaml *.yml);;All files (*)")
        if self.profile_path.text().strip():
            self._load_profile_from_path()

    def _load_profile_from_path(self) -> None:
        path = self.profile_path.text().strip()
        if not path:
            QMessageBox.information(self, "未選擇 Profile", "Machine Profile 可不選；目前會使用下方 UI 參數。")
            return
        try:
            self._apply_profile_to_ui(load_machine_profile(path))
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "載入 Profile 失敗", str(exc))

    def _apply_profile_to_ui(self, profile: MachineProfile) -> None:
        self._set_value("machine_name", profile.machine_name)
        self._set_value("controller_name", profile.controller_name)
        self._set_value("kinematic_type", profile.kinematic_type)
        self._set_value("units", profile.units)
        self._set_value("feed_unit", profile.feed_unit)
        self._set_value("rapid_feed_mm_min", profile.rapid_feed_mm_min)
        self._set_value("max_cut_feed_mm_min", profile.max_cut_feed_mm_min)
        self._set_value("default_cut_feed_mm_min", profile.default_cut_feed_mm_min)
        self._set_value("default_cut_acc_mm_s2", profile.default_cut_acc_mm_s2)
        self._set_value("default_cut_jerk_mm_s3", profile.default_cut_jerk_mm_s3)
        self._set_value("arc_tolerance_mm", profile.arc_tolerance_mm)
        self._set_value("arc_chord_tolerance_mm", profile.arc_chord_tolerance_mm)
        self._set_value("controller.interpolation_period_ms", profile.controller.interpolation_period_ms)
        self._set_value("controller.lookahead_blocks", profile.controller.lookahead_blocks)
        self._set_value("controller.junction_tolerance_mm", profile.controller.junction_tolerance_mm)
        self._set_value("controller.same_direction_angle_threshold_deg", profile.controller.same_direction_angle_threshold_deg)
        self._set_value("controller.reverse_angle_threshold_deg", profile.controller.reverse_angle_threshold_deg)
        self._set_value("controller.lookahead_max_iterations", profile.controller.lookahead_max_iterations)
        self._set_value("controller.velocity_tolerance_mm_s", profile.controller.velocity_tolerance_mm_s)
        self._set_value("controller.phase2_max_samples_per_block", profile.controller.phase2_max_samples_per_block)
        self._set_value("controller.dwell_p_unit", profile.controller.dwell_p_unit)
        self._set_value("controller.dwell_x_unit", profile.controller.dwell_x_unit)
        self._set_value("event_time.tool_change_sec", profile.event_time.tool_change_sec)
        self._set_value("event_time.spindle_start_sec", profile.event_time.spindle_start_sec)
        self._set_value("event_time.spindle_stop_sec", profile.event_time.spindle_stop_sec)
        self._set_value("event_time.coolant_on_sec", profile.event_time.coolant_on_sec)
        self._set_value("event_time.coolant_off_sec", profile.event_time.coolant_off_sec)
        self._set_value("event_time.optional_stop_sec", profile.event_time.optional_stop_sec)
        self._set_value("cycle.peck_clearance_mm", profile.cycle.peck_clearance_mm)
        self._set_value("reference_return.mode", profile.reference_return.mode)
        self._set_value("reference_return.fixed_time_sec", profile.reference_return.fixed_time_sec)
        self._set_value("reference_return.position.X", profile.reference_return.axis_position("X"))
        self._set_value("reference_return.position.Y", profile.reference_return.axis_position("Y"))
        self._set_value("reference_return.position.Z", profile.reference_return.axis_position("Z"))
        self._set_combo_data(self.time_model, profile.time_model.mode)
        for axis in ("X", "Y", "Z"):
            axis_profile = profile.axis(axis)
            self.axis_inputs[axis]["rapid_velocity_mm_min"].setValue(axis_profile.rapid_velocity_mm_min)
            self.axis_inputs[axis]["max_velocity_mm_min"].setValue(axis_profile.max_velocity_mm_min)
            self.axis_inputs[axis]["max_acc_mm_s2"].setValue(axis_profile.max_acc_mm_s2)
            self.axis_inputs[axis]["max_jerk_mm_s3"].setValue(axis_profile.max_jerk_mm_s3)
        self._apply_time_model_visibility()

    def _apply_time_model_visibility(self, *_args: object) -> None:
        mode = str(self.time_model.currentData() or "constant_velocity")
        visible_keys = ALWAYS_VISIBLE_PROFILE_KEYS | TIME_MODEL_PROFILE_KEYS.get(mode, CONSTANT_VELOCITY_FIELDS)
        for key, widgets in self.profile_row_widgets.items():
            visible = key in visible_keys
            for widget in widgets:
                widget.setVisible(visible)
        fields = ", ".join(sorted(TIME_MODEL_PROFILE_KEYS.get(mode, CONSTANT_VELOCITY_FIELDS)))
        description = TIME_MODEL_DESCRIPTIONS.get(mode, TIME_MODEL_DESCRIPTIONS["constant_velocity"])
        self.time_model_parameter_hint.setText(f"{description}")

    def _set_value(self, key: str, value: object) -> None:
        widget = self.profile_inputs[key]
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif isinstance(widget, QComboBox):
            self._set_combo_text(widget, str(value))
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value))

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_combo_data(self, combo: QComboBox, value: str | None) -> None:
        if value is None:
            combo.setCurrentIndex(0)
            return
        for index in range(combo.count()):
            if combo.itemData(index) == value or combo.itemText(index) == value:
                combo.setCurrentIndex(index)
                return

    def _profile_from_ui(self) -> MachineProfile:
        time_model = self.time_model.currentData()
        data = {
            "machine_name": self._text("machine_name"),
            "controller_name": self._text("controller_name"),
            "kinematic_type": self._text("kinematic_type"),
            "units": self._combo_value("units"),
            "feed_unit": self._combo_value("feed_unit"),
            "axes": {
                axis: {
                    key: widget.value()
                    for key, widget in self.axis_inputs[axis].items()
                }
                for axis in ("X", "Y", "Z")
            },
            "rapid_feed_mm_min": self._number("rapid_feed_mm_min"),
            "max_cut_feed_mm_min": self._number("max_cut_feed_mm_min"),
            "default_cut_feed_mm_min": self._number("default_cut_feed_mm_min"),
            "default_cut_acc_mm_s2": self._number("default_cut_acc_mm_s2"),
            "default_cut_jerk_mm_s3": self._number("default_cut_jerk_mm_s3"),
            "arc_tolerance_mm": self._number("arc_tolerance_mm"),
            "arc_chord_tolerance_mm": self._number("arc_chord_tolerance_mm"),
            "controller": {
                "interpolation_period_ms": self._number("controller.interpolation_period_ms"),
                "lookahead_blocks": self._int_value("controller.lookahead_blocks"),
                "junction_tolerance_mm": self._number("controller.junction_tolerance_mm"),
                "same_direction_angle_threshold_deg": self._number("controller.same_direction_angle_threshold_deg"),
                "reverse_angle_threshold_deg": self._number("controller.reverse_angle_threshold_deg"),
                "lookahead_max_iterations": self._int_value("controller.lookahead_max_iterations"),
                "velocity_tolerance_mm_s": self._number("controller.velocity_tolerance_mm_s"),
                "phase2_max_samples_per_block": self._int_value("controller.phase2_max_samples_per_block"),
                "dwell_p_unit": self._combo_value("controller.dwell_p_unit"),
                "dwell_x_unit": self._combo_value("controller.dwell_x_unit"),
            },
            "event_time": {
                "tool_change_sec": self._number("event_time.tool_change_sec"),
                "spindle_start_sec": self._number("event_time.spindle_start_sec"),
                "spindle_stop_sec": self._number("event_time.spindle_stop_sec"),
                "coolant_on_sec": self._number("event_time.coolant_on_sec"),
                "coolant_off_sec": self._number("event_time.coolant_off_sec"),
                "optional_stop_sec": self._number("event_time.optional_stop_sec"),
            },
            "cycle": {"peck_clearance_mm": self._number("cycle.peck_clearance_mm")},
            "time_model": {"mode": time_model},
            "reference_return": {
                "mode": self._combo_value("reference_return.mode"),
                "fixed_time_sec": self._number("reference_return.fixed_time_sec"),
                "position": {
                    "X": self._number("reference_return.position.X"),
                    "Y": self._number("reference_return.position.Y"),
                    "Z": self._number("reference_return.position.Z"),
                },
            },
        }
        return MachineProfile.model_validate(data)

    def _write_profile_tempfile(self, profile: MachineProfile) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", encoding="utf-8", delete=False)
        with handle:
            yaml.safe_dump(profile.model_dump(mode="json"), handle, allow_unicode=True, sort_keys=False)
        return Path(handle.name)

    def _text(self, key: str) -> str:
        widget = self.profile_inputs[key]
        return widget.text() if isinstance(widget, QLineEdit) else ""

    def _combo_value(self, key: str) -> str:
        widget = self.profile_inputs[key]
        return widget.currentText() if isinstance(widget, QComboBox) else ""

    def _number(self, key: str) -> float:
        widget = self.profile_inputs[key]
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QSpinBox):
            return float(widget.value())
        raise TypeError(f"{key} is not numeric")

    def _int_value(self, key: str) -> int:
        widget = self.profile_inputs[key]
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return int(widget.value())
        raise TypeError(f"{key} is not integer")

    def _browse_export_dir(self) -> None:
        self._browse_dir_into(self.export_dir, "選擇報表輸出資料夾")

    def _browse_normalize_nc(self) -> None:
        self._browse_file_into(self.normalize_nc_path, "選擇 NC-Code", "NC files (*.nc *.tap *.gcode *.txt);;All files (*)")

    def _browse_normalize_profile(self) -> None:
        self._browse_file_into(self.normalize_profile_path, "選擇 Machine Profile", "YAML files (*.yaml *.yml);;All files (*)")

    def _browse_normalize_out(self) -> None:
        self._browse_save_into(self.normalize_out_path, "選擇輸出 NC", "NC files (*.nc);;All files (*)")

    def _browse_benchmark_profile(self) -> None:
        self._browse_file_into(self.benchmark_profile_path, "選擇 Machine Profile", "YAML files (*.yaml *.yml);;All files (*)")

    def _browse_benchmark_out(self) -> None:
        self._browse_save_into(self.benchmark_out_path, "選擇 Benchmark 輸出 NC", "NC files (*.nc);;All files (*)")

    def _browse_calibration_dataset(self) -> None:
        self._browse_file_into(self.calibration_dataset_path, "選擇 Dataset CSV", "CSV files (*.csv);;All files (*)")

    def _browse_calibration_profile(self) -> None:
        self._browse_file_into(self.calibration_profile_path, "選擇 Base Profile", "YAML files (*.yaml *.yml);;All files (*)")

    def _browse_calibration_out(self) -> None:
        self._browse_save_into(self.calibration_out_path, "選擇輸出 Profile", "YAML files (*.yaml *.yml);;All files (*)")

    def _browse_calibration_nc_base(self) -> None:
        self._browse_dir_into(self.calibration_nc_base_dir, "選擇 NC Base Dir")

    def _browse_file_into(self, field: QLineEdit, title: str, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if path:
            field.setText(path)

    def _browse_save_into(self, field: QLineEdit, title: str, file_filter: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, title, field.text(), file_filter)
        if path:
            field.setText(path)

    def _browse_dir_into(self, field: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, field.text() or self.default_output_dir)
        if path:
            field.setText(path)

    def _estimate(self) -> None:
        self.status_label.setText("估測中...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        temp_profile_path: Path | None = None
        try:
            profile = self._profile_from_ui()
            temp_profile_path = self._write_profile_tempfile(profile)
            strict_feed = self.strict_feed.isChecked()
            self.result = estimate_nc_time(
                self.nc_path.text(),
                temp_profile_path,
                time_model=None,
                strict_feed=strict_feed,
            )
            self.log_path = write_auto_log(self.result, self.nc_path.text(), base_dir=self.project_root)
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "估測失敗", str(exc))
            self.status_label.setText("估測失敗")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            if temp_profile_path is not None:
                try:
                    temp_profile_path.unlink()
                except FileNotFoundError:
                    pass

        self._show_project_summary(self.result)
        self._show_summary(self.result)
        self._show_table(self.result)
        self._show_warnings(self.result)
        self._show_charts(self.result)
        self.status_label.setText(f"完成：{self.result.total_time_text}")
        self.statusBar().showMessage(f"Log 已產生：{self.log_path}")

    def _export_reports(self) -> None:
        if self.result is None:
            QMessageBox.information(self, "尚無結果", "請先執行估測。")
            return
        formats = [fmt for fmt, checkbox in self.export_checks.items() if checkbox.isChecked()]
        if not formats:
            QMessageBox.information(self, "未選擇格式", "請至少選擇一種報表格式。")
            return
        output_dir = Path(self.export_dir.text() or self.default_output_dir)
        timestamp = datetime.now()
        written: list[Path] = []
        try:
            for fmt in formats:
                path = manual_export_path_in_dir(self.nc_path.text(), fmt, output_dir, now=timestamp)
                export_result(self.result, path, fmt)
                written.append(path)
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "輸出失敗", str(exc))
            return
        self.statusBar().showMessage("已輸出報表：" + " | ".join(str(path) for path in written))

    def _run_normalize_feed(self) -> None:
        try:
            summary = normalize_feed_file(
                self.normalize_nc_path.text(),
                self.normalize_profile_path.text(),
                self.normalize_out_path.text(),
                input_feed_unit=self.normalize_input_unit.currentText(),
            )
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "Feed 正規化失敗", str(exc))
            return
        data = summary.to_dict()
        self.normalize_summary.setPlainText(
            "\n".join(
                [
                    f"輸入檔案：{data['input_path']}",
                    f"輸出檔案：{data['output_path']}",
                    f"輸入 Feed 單位：{data['input_feed_unit']}",
                    f"輸出 Feed 單位：{data['output_feed_unit']}",
                    f"改寫 Feed 數：{data['rewritten_feed_count']}",
                    f"上限裁切數：{data['capped_feed_count']}",
                    f"略過 Feed 數：{data['skipped_feed_count']}",
                    f"變更行號：{data['changed_lines']}",
                ]
            )
        )

    def _run_generate_benchmark(self) -> None:
        try:
            profile = load_machine_profile(self.benchmark_profile_path.text())
            nc_code = generate_benchmark_nc_code(profile)
            out_path = Path(self.benchmark_out_path.text())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(nc_code, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "Benchmark 產生失敗", str(exc))
            return
        self.benchmark_summary.setPlainText(
            "\n".join(
                [
                    f"輸出檔案：{out_path}",
                    f"Machine：{profile.machine_name}",
                    f"行數：{len(nc_code.splitlines())}",
                ]
            )
        )

    def _run_calibrate_profile(self) -> None:
        try:
            nc_base_dir = self.calibration_nc_base_dir.text().strip() or None
            calibrated_profile, summary = calibrate_machine_profile_from_csv(
                self.calibration_dataset_path.text(),
                self.calibration_profile_path.text(),
                nc_base_dir=nc_base_dir,
            )
            out_path = Path(self.calibration_out_path.text())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml

            with out_path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(calibrated_profile.model_dump(mode="json"), fh, allow_unicode=True, sort_keys=False)
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "Profile 校正失敗", str(exc))
            return
        self.calibration_summary.setPlainText(
            "\n".join(
                [
                    f"輸出 Profile：{out_path}",
                    f"案例數：{summary['case_count']}",
                    f"校正前 MAPE：{summary['before_mape']:.3f}%",
                    f"校正後 MAPE：{summary['after_mape']:.3f}%",
                    f"最佳參數：{summary['best_params']}",
                ]
            )
        )

    def _show_project_summary(self, result: EstimateResult) -> None:
        critical_count = result.feed_sanity_summary.get("feed_sanity_critical_count", 0)
        sanity_warning = "是" if self.fail_on_sanity_error.isChecked() and critical_count else "否"
        lines = [
            f"總時間：{result.total_time_text}（{result.total_time_sec:.3f} 秒）",
            f"快速移動時間：{result.rapid_time_sec:.3f} 秒",
            f"切削時間：{result.cutting_time_sec:.3f} 秒",
            f"圓弧時間：{result.arc_time_sec:.3f} 秒",
            f"輔助時間：{result.auxiliary_time_sec:.3f} 秒",
            f"總路徑長度：{result.total_length_mm:.3f} mm",
            f"警告數：{len(result.warning_list)}",
            f"Feed 單位：{result.summary_dict().get('feed_unit_effective', '無')}",
            f"Feed sanity 嚴重問題數：{critical_count}",
            f"Feed sanity 失敗警示：{sanity_warning}",
        ]
        if self.log_path is not None:
            lines.append(f"Log：{self.log_path}")
        self.project_summary.setPlainText("\n".join(lines))

    def _show_summary(self, result: EstimateResult) -> None:
        lines = [f"{key}: {value}" for key, value in result.summary_dict().items()]
        self.summary_text.setPlainText("\n".join(lines))

    def _show_table(self, result: EstimateResult) -> None:
        rows = result.block_table
        headers = list(rows[0].keys()) if rows else []
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for col_index, header in enumerate(headers):
                item = QTableWidgetItem(str(row.get(header, "")))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, col_index, item)
        self.table.resizeColumnsToContents()

    def _show_warnings(self, result: EstimateResult) -> None:
        warnings = list(result.warning_list)
        if self.fail_on_sanity_error.isChecked() and result.feed_sanity_summary.get("feed_sanity_critical_count", 0):
            warnings.append("Feed sanity 失敗警示：偵測到嚴重 Feed 問題。")
        self.warning_text.setPlainText("\n".join(warnings))

    def _show_charts(self, result: EstimateResult) -> None:
        self._clear_chart_layout()
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
        except Exception:
            self.chart_layout.addWidget(QLabel("Matplotlib Qt backend is unavailable."))
            return

        has_phase2 = bool(result.phase2_dynamic_samples)
        figure = Figure(figsize=(8, 7 if has_phase2 else 6))
        canvas = FigureCanvas(figure)
        if has_phase2:
            path_ax = figure.add_subplot(311)
            time_ax = figure.add_subplot(312)
            velocity_ax = figure.add_subplot(313)
        else:
            path_ax = figure.add_subplot(211)
            time_ax = figure.add_subplot(212)

        xs: list[float | None] = []
        ys: list[float | None] = []
        times: list[float] = []
        for block in result.ir_program:
            if block.start is not None and block.end is not None:
                xs.extend([block.start.x, block.end.x, None])
                ys.extend([block.start.y, block.end.y, None])
            times.append(block.estimated_time)

        path_ax.plot(xs, ys, linewidth=1.0)
        path_ax.set_title("XY Toolpath")
        path_ax.set_aspect("equal", adjustable="datalim")
        path_ax.grid(True, linewidth=0.3)

        time_ax.bar(range(len(times)), times)
        time_ax.set_title("Block Time")
        time_ax.set_xlabel("Block index")
        time_ax.set_ylabel("sec")
        time_ax.grid(True, axis="y", linewidth=0.3)
        if has_phase2:
            velocity_ax.plot(
                [sample["time_sec"] for sample in result.phase2_dynamic_samples],
                [sample["velocity_mm_s"] for sample in result.phase2_dynamic_samples],
                linewidth=0.8,
            )
            velocity_ax.set_title("Phase 2 Velocity")
            velocity_ax.set_xlabel("sec")
            velocity_ax.set_ylabel("mm/s")
            velocity_ax.grid(True, linewidth=0.3)
        figure.tight_layout()
        self.chart_layout.addWidget(canvas)

    def _clear_chart_layout(self) -> None:
        while self.chart_layout.count():
            item = self.chart_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _yes_no(self, value: object) -> str:
        if value is True:
            return "是"
        if value is False:
            return "否"
        return "無"


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
