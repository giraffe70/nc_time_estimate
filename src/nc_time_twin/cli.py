from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from nc_time_twin.api import estimate_nc_time
from nc_time_twin.core.report.exporters import export_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nc-time-twin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate_parser = subparsers.add_parser("estimate", help="Estimate NC-Code machining time")
    estimate_parser.add_argument("--nc", required=True, help="Path to NC-Code file")
    estimate_parser.add_argument("--profile", required=True, help="Path to machine profile YAML")
    estimate_parser.add_argument("--out", help="Output report path")
    estimate_parser.add_argument(
        "--format",
        choices=["json", "csv", "xlsx", "excel", "html"],
        help="Output format; inferred from --out when omitted",
    )
    estimate_parser.add_argument("--print-summary", action="store_true", help="Print summary JSON")

    args = parser.parse_args(argv)
    if args.command == "estimate":
        return _estimate(args)
    return 2


def _estimate(args: argparse.Namespace) -> int:
    result = estimate_nc_time(args.nc, args.profile)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_result(result, out_path, args.format)
    if args.print_summary or not args.out:
        json.dump(result.summary_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
