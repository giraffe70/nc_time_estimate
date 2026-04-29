from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yaml

from nc_time_twin.api import estimate_nc_time, estimate_nc_time_with_comparison
from nc_time_twin.core.feed_normalizer import normalize_feed_file
from nc_time_twin.core.machine.benchmark_generator import generate_benchmark_nc_code
from nc_time_twin.core.machine.calibration import calibrate_machine_profile_from_csv
from nc_time_twin.core.machine.profile import MachineProfile, load_machine_profile
from nc_time_twin.core.report.exporters import export_result
from nc_time_twin.core.report.result_model import EstimateResult


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = PROJECT_ROOT / "profiles" / "default_3axis.yaml"
WEB_REPORT_ROOT = PROJECT_ROOT / "output" / "web_reports"
STATIC_DIR = Path(__file__).resolve().parent / "static"
REPORT_FORMATS = {"xlsx", "html"}
DEFAULT_REGRESSION_RATIO = 0.0002

app = FastAPI(title="NC-Time-Twin Web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "default_profile_exists": DEFAULT_PROFILE.exists()}


@app.post("/api/profile/parse")
async def parse_profile(profile: UploadFile | None = File(None)) -> dict[str, object]:
    if profile is not None and profile.filename:
        data = yaml.safe_load((await profile.read()).decode("utf-8-sig")) or {}
        parsed = MachineProfile.model_validate(data)
    else:
        parsed = load_machine_profile(DEFAULT_PROFILE)
    return {"profile": parsed.model_dump(mode="json")}


@app.post("/api/estimate")
async def estimate_nc_file(
    nc_file: UploadFile = File(...),
    profile: UploadFile | None = File(None),
    profile_data: str = Form(""),
    time_model: str = Form("profile"),
    feed_unit: str = Form(""),
    strict_feed: bool = Form(False),
) -> dict[str, object]:
    run_id = uuid4().hex
    run_dir = WEB_REPORT_ROOT / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=False)

    nc_path = input_dir / _safe_filename(nc_file.filename, "program.nc")
    await _save_upload(nc_file, nc_path)
    profile_path = await _resolve_profile(profile, profile_data, input_dir)
    result = estimate_nc_time(
        nc_path,
        profile_path,
        feed_unit=feed_unit or None,
        time_model=None if time_model in {"", "profile"} else time_model,
        strict_feed=strict_feed,
    )
    report_paths = _write_reports(result, run_dir, basename="estimate")
    return _estimate_response_payload(result, run_id, report_paths)


@app.post("/api/compare")
async def compare_nc_files(
    original_nc: UploadFile = File(...),
    optimized_nc: UploadFile = File(...),
    profile: UploadFile | None = File(None),
    profile_data: str = Form(""),
    time_model: str = Form("profile"),
    feed_unit: str = Form(""),
    strict_feed: bool = Form(False),
    max_regression_ratio: float = Form(DEFAULT_REGRESSION_RATIO),
) -> dict[str, object]:
    run_id = uuid4().hex
    run_dir = WEB_REPORT_ROOT / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=False)

    original_path = input_dir / _safe_filename(original_nc.filename, "original.nc")
    optimized_path = input_dir / _safe_filename(optimized_nc.filename, "optimized.nc")
    await _save_upload(original_nc, original_path)
    await _save_upload(optimized_nc, optimized_path)

    profile_path = await _resolve_profile(profile, profile_data, input_dir)

    normalized_time_model = None if time_model in {"", "profile"} else time_model
    normalized_feed_unit = feed_unit or None
    result = estimate_nc_time_with_comparison(
        optimized_path,
        original_path,
        profile_path,
        feed_unit=normalized_feed_unit,
        time_model=normalized_time_model,
        strict_feed=strict_feed,
        max_regression_ratio=max_regression_ratio,
    )
    report_paths = _write_reports(result, run_dir, basename="comparison")
    return _comparison_response_payload(result, run_id, report_paths)


@app.post("/api/tools/normalize-feed")
async def normalize_feed(
    nc_file: UploadFile = File(...),
    profile: UploadFile | None = File(None),
    profile_data: str = Form(""),
    input_feed_unit: str = Form("m_per_min"),
) -> dict[str, object]:
    run_id = uuid4().hex
    run_dir = WEB_REPORT_ROOT / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=False)

    nc_path = input_dir / _safe_filename(nc_file.filename, "program.nc")
    await _save_upload(nc_file, nc_path)
    profile_path = await _resolve_profile(profile, profile_data, input_dir)
    output_path = run_dir / f"{nc_path.stem}.normalized.nc"
    summary = normalize_feed_file(nc_path, profile_path, output_path, input_feed_unit=input_feed_unit)
    return {
        "run_id": run_id,
        "summary": summary.to_dict(),
        "download_url": _artifact_url(run_id, output_path.name),
    }


@app.post("/api/tools/generate-benchmark")
async def generate_benchmark(
    profile: UploadFile | None = File(None),
    profile_data: str = Form(""),
) -> dict[str, object]:
    run_id = uuid4().hex
    run_dir = WEB_REPORT_ROOT / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=False)

    profile_path = await _resolve_profile(profile, profile_data, input_dir)
    machine_profile = load_machine_profile(profile_path)
    nc_code = generate_benchmark_nc_code(machine_profile)
    output_path = run_dir / "phase2_benchmark.nc"
    output_path.write_text(nc_code, encoding="utf-8")
    return {
        "run_id": run_id,
        "summary": {
            "output_path": str(output_path),
            "machine_name": machine_profile.machine_name,
            "line_count": len(nc_code.splitlines()),
        },
        "download_url": _artifact_url(run_id, output_path.name),
    }


@app.post("/api/tools/calibrate-profile")
async def calibrate_profile(
    dataset_csv: UploadFile = File(...),
    base_profile: UploadFile | None = File(None),
    nc_zip: UploadFile | None = File(None),
    nc_base_dir: str = Form(""),
) -> dict[str, object]:
    run_id = uuid4().hex
    run_dir = WEB_REPORT_ROOT / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=False)

    dataset_path = input_dir / _safe_filename(dataset_csv.filename, "calibration.csv")
    await _save_upload(dataset_csv, dataset_path)
    profile_path = await _resolve_profile(base_profile, "", input_dir, fallback_name="base_profile.yaml")
    resolved_nc_base_dir: str | Path | None = nc_base_dir.strip() or None
    if nc_zip is not None and nc_zip.filename:
        zip_path = input_dir / _safe_filename(nc_zip.filename, "nc_files.zip")
        await _save_upload(nc_zip, zip_path)
        extract_dir = run_dir / "nc_files"
        _extract_zip_safely(zip_path, extract_dir)
        resolved_nc_base_dir = extract_dir

    calibrated_profile, summary = calibrate_machine_profile_from_csv(
        dataset_path,
        profile_path,
        nc_base_dir=resolved_nc_base_dir,
    )
    output_path = run_dir / "calibrated_profile.yaml"
    output_path.write_text(
        yaml.safe_dump(calibrated_profile.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {
        "run_id": run_id,
        "summary": summary,
        "download_url": _artifact_url(run_id, output_path.name),
    }


@app.get("/api/reports/{run_id}.{fmt}")
def download_report(run_id: str, fmt: str) -> FileResponse:
    if not _valid_run_id(run_id):
        raise HTTPException(status_code=404, detail="Report not found")
    fmt = fmt.lower()
    if fmt not in REPORT_FORMATS:
        raise HTTPException(status_code=404, detail="Report format not found")
    path = _find_report_path(run_id, fmt)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, filename=f"{path.stem}_{run_id}.{fmt}", media_type=_media_type(fmt))


@app.get("/api/artifacts/{run_id}/{filename}")
def download_artifact(run_id: str, filename: str) -> FileResponse:
    if not _valid_run_id(run_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    safe_name = _safe_filename(filename, "")
    if safe_name != filename:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = WEB_REPORT_ROOT / run_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, filename=filename)


def _write_reports(result: EstimateResult, run_dir: Path, *, basename: str) -> dict[str, str]:
    report_paths: dict[str, str] = {}
    for fmt in sorted(REPORT_FORMATS):
        path = run_dir / f"{basename}.{fmt}"
        export_result(result, path, fmt)
        report_paths[fmt] = f"/api/reports/{run_dir.name}.{fmt}"
    return report_paths


def _estimate_response_payload(result: EstimateResult, run_id: str, report_paths: dict[str, str]) -> dict[str, object]:
    data = result.to_dict()
    return {
        "run_id": run_id,
        "summary": result.summary_dict(),
        "full_results": data,
        "warnings": result.warning_list,
        "blocks": result.block_table,
        "charts": result.chart_data(),
        "download_urls": report_paths,
    }


def _comparison_response_payload(result: EstimateResult, run_id: str, report_paths: dict[str, str]) -> dict[str, object]:
    comparison = result.comparison
    segment_rows = sorted(
        comparison.get("segment_differences", []),
        key=lambda row: float(row.get("delta_time_sec") or 0.0),
        reverse=True,
    )
    return {
        "run_id": run_id,
        "summary": {
            "original_total_time_sec": comparison.get("source_total_time_sec"),
            "optimized_total_time_sec": comparison.get("candidate_total_time_sec"),
            "original_total_time_text": comparison.get("source_total_time_text"),
            "optimized_total_time_text": comparison.get("candidate_total_time_text"),
            "total_time_delta_sec": comparison.get("total_time_delta_sec"),
            "cutting_time_delta_sec": comparison.get("cutting_time_delta_sec"),
            "regression_ratio": comparison.get("regression_ratio"),
            "is_regression": comparison.get("is_regression"),
            "geometry_match": comparison.get("geometry_match"),
            "warning_count": len(result.warning_list),
            "feed_sanity_issue_count": result.feed_sanity_summary.get("feed_sanity_issue_count", 0),
            "feed_sanity_critical_count": result.feed_sanity_summary.get("feed_sanity_critical_count", 0),
        },
        "warnings": result.warning_list,
        "full_results": result.to_dict(),
        "optimized_blocks": result.block_table,
        "charts": result.chart_data(),
        "feed_sanity": {
            "summary": result.feed_sanity_summary,
            "issues": result.feed_sanity_issues,
            "recommendation": result.normalized_feed_recommendation,
        },
        "comparison": {
            "source_label": comparison.get("source_label"),
            "candidate_label": comparison.get("candidate_label"),
            "feed_band_deltas": comparison.get("feed_band_deltas", []),
            "top_time_regression_blocks": comparison.get("top_time_regression_blocks", []),
            "segment_differences": segment_rows,
        },
        "download_urls": report_paths,
    }


async def _resolve_profile(
    profile: UploadFile | None,
    profile_data: str,
    input_dir: Path,
    *,
    fallback_name: str = "profile.yaml",
) -> Path:
    if profile_data.strip():
        try:
            parsed = MachineProfile.model_validate(json.loads(profile_data))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid profile data: {exc}") from exc
        path = input_dir / fallback_name
        path.write_text(
            yaml.safe_dump(parsed.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path
    if profile is not None and profile.filename:
        path = input_dir / _safe_filename(profile.filename, fallback_name)
        await _save_upload(profile, path)
        return path
    if not DEFAULT_PROFILE.exists():
        raise HTTPException(status_code=400, detail=f"Profile not found: {DEFAULT_PROFILE}")
    return DEFAULT_PROFILE


async def _save_upload(upload: UploadFile, path: Path) -> None:
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"Empty upload: {upload.filename or path.name}")
    path.write_bytes(content)


def _extract_zip_safely(zip_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (extract_dir / member.filename).resolve()
            if extract_dir.resolve() not in target.parents and target != extract_dir.resolve():
                raise HTTPException(status_code=400, detail="Unsafe zip path")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def _find_report_path(run_id: str, fmt: str) -> Path:
    run_dir = WEB_REPORT_ROOT / run_id
    for basename in ("comparison", "estimate", "result"):
        path = run_dir / f"{basename}.{fmt}"
        if path.exists():
            return path
    return run_dir / f"comparison.{fmt}"


def _artifact_url(run_id: str, filename: str) -> str:
    return f"/api/artifacts/{run_id}/{filename}"


def _safe_filename(filename: str | None, fallback: str) -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def _valid_run_id(run_id: str) -> bool:
    return len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)


def _media_type(fmt: str) -> str:
    if fmt == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt == "html":
        return "text/html; charset=utf-8"
    if fmt == "json":
        return "application/json"
    return "text/csv; charset=utf-8"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nc-time-twin-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run("nc_time_twin.web.server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
