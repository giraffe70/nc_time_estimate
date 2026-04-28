from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from nc_time_twin.api import estimate_nc_time, estimate_nc_time_with_comparison
from nc_time_twin.core.feed_normalizer import normalize_feed_file
from nc_time_twin.core.machine.benchmark_generator import generate_benchmark_nc_code
from nc_time_twin.core.machine.calibration import calibrate_machine_profile_from_csv
from nc_time_twin.core.machine.profile import load_machine_profile
from nc_time_twin.core.report.auto_outputs import write_auto_outputs
from nc_time_twin.core.report.exporters import export_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nc-time-twin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate_parser = subparsers.add_parser("estimate", help="Estimate NC-Code machining time")
    estimate_parser.add_argument("--nc", required=True, help="Path to NC-Code file")
    estimate_parser.add_argument("--profile", required=True, help="Path to machine profile YAML")
    estimate_parser.add_argument("--out", help="Output report path")
    estimate_parser.add_argument(
        "--feed-unit",
        choices=["auto", "mm_per_min", "m_per_min", "inverse_time"],
        help="Override the profile feed_unit for this run",
    )
    estimate_parser.add_argument(
        "--time-model",
        choices=["profile", "constant_velocity", "trapezoid", "phase2"],
        default="profile",
        help="Override profile time_model.mode; default uses the profile value",
    )
    estimate_parser.add_argument("--compare-nc", help="Baseline/source NC-Code path for candidate comparison")
    estimate_parser.add_argument(
        "--max-regression-ratio",
        type=float,
        default=0.0,
        help="Allowed regression ratio before --fail-on-regression fails; default 0.0",
    )
    estimate_parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Return exit code 1 when --compare-nc has matching geometry and the candidate is slower",
    )
    estimate_parser.add_argument(
        "--strict-feed",
        action="store_true",
        help="Estimate G21/G94 feed as explicit mm/min and flag mixed feed scales more strictly",
    )
    estimate_parser.add_argument(
        "--fail-on-sanity-error",
        action="store_true",
        help="Return exit code 1 when feed sanity diagnostics contain critical issues",
    )
    estimate_parser.add_argument(
        "--format",
        choices=["json", "csv", "xlsx", "excel", "html"],
        help="Output format; inferred from --out when omitted",
    )
    estimate_parser.add_argument("--print-summary", action="store_true", help="Print summary JSON")

    normalize_parser = subparsers.add_parser("normalize-feed", help="Normalize G21/G94 feed words to mm/min")
    normalize_parser.add_argument("--nc", required=True, help="Path to NC-Code file")
    normalize_parser.add_argument("--profile", required=True, help="Path to machine profile YAML")
    normalize_parser.add_argument("--out", required=True, help="Output normalized NC-Code path")
    normalize_parser.add_argument(
        "--input-feed-unit",
        required=True,
        choices=["mm_per_min", "m_per_min"],
        help="Unit used by input G21/G94 F words before normalization",
    )
    normalize_parser.add_argument("--print-summary", action="store_true", help="Print normalization summary JSON")

    benchmark_parser = subparsers.add_parser("generate-benchmark", help="Generate Phase 2 benchmark NC-Code")
    benchmark_parser.add_argument("--profile", required=True, help="Path to machine profile YAML")
    benchmark_parser.add_argument("--out", required=True, help="Output NC-Code path")
    benchmark_parser.add_argument("--print-summary", action="store_true", help="Print generation summary JSON")

    calibrate_parser = subparsers.add_parser("calibrate-profile", help="Calibrate a Phase 2 profile from CSV data")
    calibrate_parser.add_argument("--dataset", required=True, help="CSV with case_id,nc_file,actual_total_time_sec")
    calibrate_parser.add_argument("--profile", required=True, help="Base machine profile YAML")
    calibrate_parser.add_argument("--out", required=True, help="Output calibrated profile YAML")
    calibrate_parser.add_argument(
        "--nc-base-dir",
        help="Base directory for relative nc_file values in the dataset; defaults to dataset directory",
    )
    calibrate_parser.add_argument("--print-summary", action="store_true", help="Print calibration summary JSON")

    args = parser.parse_args(argv)
    if args.command == "estimate":
        return _estimate(args)
    if args.command == "normalize-feed":
        return _normalize_feed(args)
    if args.command == "generate-benchmark":
        return _generate_benchmark(args)
    if args.command == "calibrate-profile":
        return _calibrate_profile(args)
    return 2


def _estimate(args: argparse.Namespace) -> int:
    time_model = None if args.time_model == "profile" else args.time_model
    if args.compare_nc:
        result = estimate_nc_time_with_comparison(
            args.nc,
            args.compare_nc,
            args.profile,
            feed_unit=args.feed_unit,
            time_model=time_model,
            strict_feed=args.strict_feed,
            max_regression_ratio=args.max_regression_ratio,
        )
    else:
        result = estimate_nc_time(
            args.nc,
            args.profile,
            feed_unit=args.feed_unit,
            time_model=time_model,
            strict_feed=args.strict_feed,
        )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_result(result, out_path, args.format)
        print(f"Wrote report: {out_path.resolve()}", file=sys.stderr)
        print(f"Total time: {result.total_time_text} ({result.total_time_sec:.3f} sec)", file=sys.stderr)
    auto_paths = write_auto_outputs(result, args.nc)
    print(f"Wrote auto report: {auto_paths.report_path.resolve()}", file=sys.stderr)
    print(f"Wrote log: {auto_paths.log_path.resolve()}", file=sys.stderr)
    if args.print_summary or not args.out:
        json.dump(result.summary_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    if args.fail_on_regression and result.comparison.get("is_regression"):
        _print_regression(result)
        return 1
    if args.fail_on_sanity_error and result.feed_sanity_summary.get("feed_sanity_critical_count", 0):
        _print_sanity_failure(result)
        return 1
    return 0


def _normalize_feed(args: argparse.Namespace) -> int:
    summary = normalize_feed_file(
        args.nc,
        args.profile,
        args.out,
        input_feed_unit=args.input_feed_unit,
    )
    print(f"Wrote normalized NC-Code: {Path(args.out).resolve()}", file=sys.stderr)
    if args.print_summary:
        json.dump(summary.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


def _generate_benchmark(args: argparse.Namespace) -> int:
    profile = load_machine_profile(args.profile)
    nc_code = generate_benchmark_nc_code(profile)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(nc_code, encoding="utf-8")
    print(f"Wrote benchmark NC-Code: {out_path.resolve()}", file=sys.stderr)
    if args.print_summary:
        json.dump(
            {
                "output_path": str(out_path),
                "machine_name": profile.machine_name,
                "line_count": len(nc_code.splitlines()),
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
    return 0


def _calibrate_profile(args: argparse.Namespace) -> int:
    calibrated_profile, summary = calibrate_machine_profile_from_csv(
        args.dataset,
        args.profile,
        nc_base_dir=args.nc_base_dir,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(calibrated_profile.model_dump(mode="json"), fh, allow_unicode=True, sort_keys=False)
    print(f"Wrote calibrated profile: {out_path.resolve()}", file=sys.stderr)
    if args.print_summary:
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


def _print_regression(result) -> None:
    comparison = result.comparison
    print(
        "Regression: candidate NC-Code is slower than baseline with matching geometry "
        f"({comparison['total_time_delta_sec']:.3f} sec).",
        file=sys.stderr,
    )
    for row in comparison.get("top_time_regression_blocks", [])[:5]:
        if row.get("delta_time_sec", 0.0) <= 0:
            continue
        print(
            "  line "
            f"{row.get('candidate_line_no')}: +{row.get('delta_time_sec'):.3f} sec, "
            f"F{row.get('candidate_feedrate')} -> {row.get('candidate_effective_feed_mm_min')} mm/min",
            file=sys.stderr,
        )


def _print_sanity_failure(result) -> None:
    critical_count = result.feed_sanity_summary.get("feed_sanity_critical_count", 0)
    print(f"Feed sanity failure: {critical_count} critical issue(s).", file=sys.stderr)
    for issue in result.feed_sanity_issues[:5]:
        if issue.get("severity") != "critical":
            continue
        location = f"line {issue.get('line_no')}" if issue.get("line_no") is not None else "program"
        print(f"  {location}: {issue.get('code')} - {issue.get('message')}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
