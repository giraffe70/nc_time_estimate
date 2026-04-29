from __future__ import annotations

import json
import zipfile

from fastapi.testclient import TestClient

from nc_time_twin.web import server


def test_web_profile_parse_and_estimate(tmp_path, profile_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_REPORT_ROOT", tmp_path / "web_reports")
    client = TestClient(server.app)

    profile_response = client.post("/api/profile/parse")
    assert profile_response.status_code == 200
    profile = profile_response.json()["profile"]
    assert profile["machine_name"]

    estimate_response = client.post(
        "/api/estimate",
        files={
            "nc_file": ("program.nc", b"G21 G90\nG01 X100 F1000\n", "text/plain"),
        },
        data={
            "profile_data": json.dumps(profile),
            "time_model": "profile",
        },
    )

    assert estimate_response.status_code == 200
    data = estimate_response.json()
    assert data["summary"]["total_time_sec"] > 0
    assert data["blocks"][0]["line_no"] == 2
    assert data["charts"]["block_times"]
    assert data["download_urls"]["xlsx"].endswith(".xlsx")
    assert client.get(data["download_urls"]["json"]).status_code == 200


def test_web_compare_uploads_and_downloads_reports(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_REPORT_ROOT", tmp_path / "web_reports")
    client = TestClient(server.app)

    response = client.post(
        "/api/compare",
        files={
            "original_nc": ("original.nc", b"G21 G90\nG01 X100 F6000\n", "text/plain"),
            "optimized_nc": ("optimized.nc", b"G21 G90\nG01 X100 F100\n", "text/plain"),
        },
        data={"time_model": "profile", "max_regression_ratio": "0.0"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_time_delta_sec"] > 0
    assert data["comparison"]["segment_differences"][0]["line_no"] == 2
    assert data["download_urls"]["xlsx"].endswith(".xlsx")

    for fmt, url in data["download_urls"].items():
        report = client.get(url)
        assert report.status_code == 200
        assert report.content
        if fmt == "json":
            assert report.json()["comparison"]["segment_differences"]


def test_web_compare_accepts_uploaded_profile(tmp_path, profile_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_REPORT_ROOT", tmp_path / "web_reports")
    client = TestClient(server.app)

    response = client.post(
        "/api/compare",
        files={
            "original_nc": ("original.nc", b"G21 G90\nG01 X100 F6000\n", "text/plain"),
            "optimized_nc": ("optimized.nc", b"G21 G90\nG01 X100 F100\n", "text/plain"),
            "profile": ("profile.yaml", profile_path.read_bytes(), "application/x-yaml"),
        },
        data={"time_model": "profile", "max_regression_ratio": "0.0"},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["original_total_time_sec"] is not None


def test_web_tools_normalize_and_benchmark(tmp_path, profile_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_REPORT_ROOT", tmp_path / "web_reports")
    client = TestClient(server.app)

    normalize_response = client.post(
        "/api/tools/normalize-feed",
        files={
            "nc_file": ("program.nc", b"G21 G90 G94\nG01 X100 F6\n", "text/plain"),
            "profile": ("profile.yaml", profile_path.read_bytes(), "application/x-yaml"),
        },
        data={"input_feed_unit": "m_per_min"},
    )

    assert normalize_response.status_code == 200
    normalize_data = normalize_response.json()
    assert normalize_data["summary"]["rewritten_feed_count"] == 1
    normalized = client.get(normalize_data["download_url"])
    assert normalized.status_code == 200
    assert b"F6000" in normalized.content

    benchmark_response = client.post(
        "/api/tools/generate-benchmark",
        files={"profile": ("profile.yaml", profile_path.read_bytes(), "application/x-yaml")},
    )
    assert benchmark_response.status_code == 200
    benchmark_data = benchmark_response.json()
    assert benchmark_data["summary"]["line_count"] > 10
    assert client.get(benchmark_data["download_url"]).status_code == 200


def test_web_tool_calibrate_profile_with_nc_zip(tmp_path, profile_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_REPORT_ROOT", tmp_path / "web_reports")
    client = TestClient(server.app)

    zip_path = tmp_path / "nc_files.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("case.nc", "G21 G90\nG01 X100 F1000\n")
    dataset = "case_id,nc_file,actual_total_time_sec\ncase_001,case.nc,6.0\n".encode("utf-8")

    response = client.post(
        "/api/tools/calibrate-profile",
        files={
            "dataset_csv": ("calibration.csv", dataset, "text/csv"),
            "base_profile": ("profile.yaml", profile_path.read_bytes(), "application/x-yaml"),
            "nc_zip": ("nc_files.zip", zip_path.read_bytes(), "application/zip"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["case_count"] == 1
    assert client.get(data["download_url"]).status_code == 200


def test_web_ui_contains_gui_feature_tabs() -> None:
    html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (server.STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for label in ("Estimate", "Compare", "Blocks", "Charts", "XYZ Toolpath"):
        assert label in html
    for removed_label in ("Tools", "Feed 正規化", "Benchmark", "Profile 校正"):
        assert removed_label not in html
    for marker in ("estimate-stop-button", "<summary>Axes</summary>", "<summary>Controller / Events</summary>"):
        assert marker in html
    for endpoint in ("/api/estimate", "/api/profile/parse"):
        assert endpoint in js
    assert "/api/tools/" not in js
    assert "AbortController" in js
