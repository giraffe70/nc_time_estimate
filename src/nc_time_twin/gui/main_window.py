from __future__ import annotations

import sys
from pathlib import Path

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional GUI dependency
    raise SystemExit("PySide6 is required for the GUI. Install project requirements first.") from exc

from nc_time_twin.api import estimate_nc_time
from nc_time_twin.core.report.exporters import export_result
from nc_time_twin.core.report.result_model import EstimateResult


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NC-Code Machining Time Estimator")
        self.resize(1180, 760)
        self.result: EstimateResult | None = None

        self.nc_path = QLineEdit()
        self.profile_path = QLineEdit(str(Path("profiles/default_3axis.yaml").resolve()))
        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        self.warning_text = QPlainTextEdit()
        self.warning_text.setReadOnly(True)
        self.table = QTableWidget()
        self.export_format = QComboBox()
        self.export_format.addItems(["json", "csv", "xlsx", "html"])
        self.chart_container = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_container)

        tabs = QTabWidget()
        tabs.addTab(self._build_project_tab(), "Project")
        tabs.addTab(self._build_result_tab(), "Results")
        tabs.addTab(self._build_table_tab(), "Blocks")
        tabs.addTab(self._build_chart_tab(), "Charts")
        tabs.addTab(self.warning_text, "Warnings")
        self.setCentralWidget(tabs)

    def _build_project_tab(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.addWidget(QLabel("NC-Code"), 0, 0)
        layout.addWidget(self.nc_path, 0, 1)
        nc_button = QPushButton("Browse")
        nc_button.clicked.connect(self._browse_nc)
        layout.addWidget(nc_button, 0, 2)

        layout.addWidget(QLabel("Machine Profile"), 1, 0)
        layout.addWidget(self.profile_path, 1, 1)
        profile_button = QPushButton("Browse")
        profile_button.clicked.connect(self._browse_profile)
        layout.addWidget(profile_button, 1, 2)

        estimate_button = QPushButton("Estimate")
        estimate_button.clicked.connect(self._estimate)
        layout.addWidget(estimate_button, 2, 1)

        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Export"))
        export_row.addWidget(self.export_format)
        export_button = QPushButton("Save Report")
        export_button.clicked.connect(self._export)
        export_row.addWidget(export_button)
        layout.addLayout(export_row, 3, 1)
        layout.setColumnStretch(1, 1)
        return widget

    def _build_result_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.summary_text)
        return widget

    def _build_table_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.table)
        return widget

    def _build_chart_tab(self) -> QWidget:
        return self.chart_container

    def _browse_nc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select NC-Code", "", "NC files (*.nc *.tap *.gcode *.txt);;All files (*)")
        if path:
            self.nc_path.setText(path)

    def _browse_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Machine Profile", "", "YAML files (*.yaml *.yml);;All files (*)")
        if path:
            self.profile_path.setText(path)

    def _estimate(self) -> None:
        try:
            self.result = estimate_nc_time(self.nc_path.text(), self.profile_path.text())
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "Estimate failed", str(exc))
            return
        self._show_summary(self.result)
        self._show_table(self.result)
        self._show_warnings(self.result)
        self._show_charts(self.result)

    def _export(self) -> None:
        if self.result is None:
            QMessageBox.information(self, "No result", "Run an estimate first.")
            return
        fmt = self.export_format.currentText()
        path, _ = QFileDialog.getSaveFileName(self, "Save Report", f"result.{fmt}", f"{fmt.upper()} files (*.{fmt});;All files (*)")
        if not path:
            return
        try:
            export_result(self.result, path, fmt)
        except Exception as exc:  # pragma: no cover - GUI behavior
            QMessageBox.critical(self, "Export failed", str(exc))

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
        self.warning_text.setPlainText("\n".join(result.warning_list))

    def _show_charts(self, result: EstimateResult) -> None:
        self._clear_chart_layout()
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
        except Exception:
            self.chart_layout.addWidget(QLabel("Matplotlib Qt backend is unavailable."))
            return

        figure = Figure(figsize=(8, 6))
        canvas = FigureCanvas(figure)
        path_ax = figure.add_subplot(211)
        time_ax = figure.add_subplot(212)

        xs: list[float] = []
        ys: list[float] = []
        labels: list[str] = []
        times: list[float] = []
        for block in result.ir_program:
            if block.start is not None and block.end is not None:
                xs.extend([block.start.x, block.end.x, None])
                ys.extend([block.start.y, block.end.y, None])
            labels.append(str(block.line_no))
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
        figure.tight_layout()
        self.chart_layout.addWidget(canvas)

    def _clear_chart_layout(self) -> None:
        while self.chart_layout.count():
            item = self.chart_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
