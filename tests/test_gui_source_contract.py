from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCE = ROOT / "src" / "nc_time_twin" / "gui" / "main_window.py"


def test_gui_estimate_does_not_auto_export_report() -> None:
    source = GUI_SOURCE.read_text(encoding="utf-8")

    assert "write_auto_log" in source
    assert "write_auto_outputs" not in source
    assert "export_result(self.result" in source
    assert "export_button.clicked.connect(self._export_reports)" in source


def test_gui_results_and_warnings_are_project_content_not_tabs() -> None:
    source = GUI_SOURCE.read_text(encoding="utf-8")

    assert 'self.tabs.addTab(self._build_result_tab(), "Results")' not in source
    assert 'self.tabs.addTab(self.warning_text, "Warnings")' not in source
    assert 'layout.addWidget(QLabel("完整 Results"))' in source
    assert 'layout.addWidget(QLabel("Warnings"))' in source


def test_gui_advanced_cli_settings_are_visible_by_default() -> None:
    source = GUI_SOURCE.read_text(encoding="utf-8")

    assert 'QGroupBox("進階估測設定")' in source
    assert "group.setCheckable(True)" not in source
    assert "container.setVisible(False)" not in source
    assert "self.compare_nc_path" in source
    assert "self.feed_unit" in source
    assert "self.time_model" in source
    assert "self.strict_feed" in source
