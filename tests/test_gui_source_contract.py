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


def test_gui_advanced_estimate_settings_are_visible_by_default() -> None:
    source = GUI_SOURCE.read_text(encoding="utf-8")

    assert 'QGroupBox("進階估測設定")' in source
    advanced_section = source.split('QGroupBox("進階估測設定")', 1)[1].split("def _build_profile_controls", 1)[0]
    assert "setCheckable(True)" not in advanced_section
    assert "setVisible(False)" not in advanced_section
    assert "self.compare_nc_path" not in source
    assert "estimate_nc_time_with_comparison" not in source
    assert "self.fail_on_regression" not in source
    assert "self.time_model" in source
    assert "self.strict_feed" in source
    assert "self.fail_on_sanity_error" in source


def test_gui_profile_is_optional_and_profile_params_are_editable() -> None:
    source = GUI_SOURCE.read_text(encoding="utf-8")

    assert "可不選；選擇後會載入參數到下方 UI" in source
    assert "Machine Profile 參數" in source
    assert "self._profile_from_ui()" in source
    assert "self._write_profile_tempfile(profile)" in source
    assert "default_cut_jerk_mm_s3" in source
    assert "arc_chord_tolerance_mm" in source
    assert "phase2_max_samples_per_block" in source
