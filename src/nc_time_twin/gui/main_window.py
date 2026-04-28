from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

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
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional GUI dependency
    raise SystemExit("PySide6 is required for the GUI. Install project requirements first.") from exc

from nc_time_twin.api import estimate_nc_time, estimate_nc_time_with_comparison
from nc_time_twin.core.feed_normalizer import normalize_feed_file
from nc_time_twin.core.machine.benchmark_generator import generate_benchmark_nc_code
from nc_time_twin.core.machine.calibration import calibrate_machine_profile_from_csv
from nc_time_twin.core.machine.profile import load_machine_profile
from nc_time_twin.core.report.auto_outputs import manual_export_path_in_dir, write_auto_log
from nc_time_twin.core.report.exporters import export_result
from nc_time_twin.core.report.result_model import EstimateResult


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NC-Time-Twin")
        self.resize(1180, 820)
        self.result: EstimateResult | None = None
        self.log_path: Path | None = None

        self.default_profile = str(Path("profiles/default_3axis.yaml").resolve())
        self.default_output_dir = str(Path("output").resolve())

        self.nc_path = QLineEdit()
        self.profile_path = QLineEdit(self.default_profile)
        self.status_label = QLabel("就緒")
        self.project_summary = QPlainTextEdit()
        self.project_summary.setReadOnly(True)
        self.project_summary.setMinimumHeight(150)

        self.compare_nc_path = QLineEdit()
        self.feed_unit = QComboBox()
        self.feed_unit.addItem("使用 Profile 設定", None)
        self.feed_unit.addItem("auto", "auto")
        self.feed_unit.addItem("mm_per_min", "mm_per_min")
        self.feed_unit.addItem("m_per_min", "m_per_min")
        self.feed_unit.addItem("inverse_time", "inverse_time")
        self.time_model = QComboBox()
        self.time_model.addItem("使用 Profile 設定", None)
        for mode in ("constant_velocity", "trapezoid", "phase2"):
            self.time_model.addItem(mode, mode)
        self.strict_feed = QCheckBox("嚴格檢查 G21/G94 進給")
        self.fail_on_regression = QCheckBox("顯示回歸失敗警示")
        self.fail_on_sanity_error = QCheckBox("顯示 Feed sanity 失敗警示")
        self.max_regression_ratio = QDoubleSpinBox()
        self.max_regression_ratio.setRange(0.0, 10.0)
        self.max_regression_ratio.setSingleStep(0.01)
        self.max_regression_ratio.setDecimals(4)

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
        form.setColumnStretch(1, 1)
        layout.addLayout(form)

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
        form.addWidget(QLabel("比較 NC-Code"), 0, 0)
        form.addWidget(self.compare_nc_path, 0, 1)
        compare_button = QPushButton("瀏覽")
        compare_button.clicked.connect(self._browse_compare_nc)
        form.addWidget(compare_button, 0, 2)
        form.addWidget(QLabel("Feed Unit"), 1, 0)
        form.addWidget(self.feed_unit, 1, 1)
        form.addWidget(QLabel("Time Model"), 2, 0)
        form.addWidget(self.time_model, 2, 1)
        form.addWidget(QLabel("Max Regression Ratio"), 3, 0)
        form.addWidget(self.max_regression_ratio, 3, 1)
        form.addWidget(self.strict_feed, 4, 1)
        form.addWidget(self.fail_on_regression, 5, 1)
        form.addWidget(self.fail_on_sanity_error, 6, 1)
        form.setColumnStretch(1, 1)

        layout = QVBoxLayout(group)
        layout.addWidget(container)
        return group

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
        self.normalize_out_path = QLineEdit(str(Path("output/normalized.nc").resolve()))
        self.normalize_input_unit = QComboBox()
        self.normalize_input_unit.addItems(["m_per_min", "mm_per_min"])
        self.normalize_summary = QPlainTextEdit()
        self.normalize_summary.setReadOnly(True)

        self.benchmark_profile_path = QLineEdit(self.default_profile)
        self.benchmark_out_path = QLineEdit(str(Path("output/phase2_benchmark.nc").resolve()))
        self.benchmark_summary = QPlainTextEdit()
        self.benchmark_summary.setReadOnly(True)

        self.calibration_dataset_path = QLineEdit()
        self.calibration_profile_path = QLineEdit(str(Path("profiles/default_phase2_3axis.yaml").resolve()))
        self.calibration_out_path = QLineEdit(str(Path("profiles/calibrated_phase2.yaml").resolve()))
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

    def _browse_compare_nc(self) -> None:
        self._browse_file_into(self.compare_nc_path, "選擇比較 NC-Code", "NC files (*.nc *.tap *.gcode *.txt);;All files (*)")

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
        try:
            feed_unit = self.feed_unit.currentData()
            time_model = self.time_model.currentData()
            strict_feed = self.strict_feed.isChecked()
            compare_nc = self.compare_nc_path.text().strip()
            if compare_nc:
                self.result = estimate_nc_time_with_comparison(
                    self.nc_path.text(),
                    compare_nc,
                    self.profile_path.text(),
                    feed_unit=feed_unit,
                    time_model=time_model,
                    strict_feed=strict_feed,
                    max_regression_ratio=self.max_regression_ratio.value(),
                )
            else:
                self.result = estimate_nc_time(
                    self.nc_path.text(),
                    self.profile_path.text(),
                    feed_unit=feed_unit,
                    time_model=time_model,
                    strict_feed=strict_feed,
                )
            self.log_path = write_auto_log(self.result, self.nc_path.text())
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "估測失敗", str(exc))
            self.status_label.setText("估測失敗")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

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
        comparison = result.comparison or {}
        critical_count = result.feed_sanity_summary.get("feed_sanity_critical_count", 0)
        regression_warning = (
            "是" if self.fail_on_regression.isChecked() and comparison.get("is_regression") else "否"
        )
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
            f"是否回歸：{self._yes_no(comparison.get('is_regression'))}",
            f"Feed sanity 嚴重問題數：{critical_count}",
            f"回歸失敗警示：{regression_warning}",
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
        if self.fail_on_regression.isChecked() and result.comparison.get("is_regression"):
            warnings.append("回歸失敗警示：候選 NC-Code 比基準 NC-Code 慢。")
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
