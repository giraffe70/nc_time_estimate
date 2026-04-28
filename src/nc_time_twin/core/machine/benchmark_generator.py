from __future__ import annotations

import math

from nc_time_twin.core.machine.profile import MachineProfile


def generate_benchmark_nc_code(machine_profile: MachineProfile) -> str:
    max_feed = min(6000, int(machine_profile.max_cut_feed_mm_min))
    feeds = [feed for feed in (500, 1000, 2000, 4000, 6000) if feed <= max_feed]
    if not feeds:
        feeds = [int(machine_profile.default_cut_feed_mm_min)]

    lines: list[str] = [
        "%",
        f"(NC-Time-Twin Phase 2 benchmark for {machine_profile.machine_name})",
        "G21 G90 G17",
        "G00 X0 Y0 Z50",
        "S3000 M03",
    ]

    for feed in feeds:
        lines.append(f"G01 X100 Y0 Z50 F{feed}")
        lines.append(f"G01 X0 Y0 Z50 F{feed}")

    lines.append("G01 X0 Y0 Z20 F3000")
    for index in range(100):
        lines.append(f"G01 X{index * 0.5:.3f} Y{math.sin(index) * 0.5:.3f} Z20 F3000")

    lines.extend(
        [
            "G01 X0 Y0 Z20 F3000",
            "G01 X50 Y0 Z20 F3000",
            "G01 X50 Y50 Z20 F3000",
            "G01 X0 Y50 Z20 F3000",
            "G02 X50 Y0 I25 J0 F2000",
            "G03 X0 Y0 I-25 J0 F2000",
            "G00 X0 Y0 Z50",
            "G00 X100 Y100 Z50",
            "G00 X0 Y0 Z50",
            "M05",
            "T2 M06",
            "S5000 M03",
            "G04 P1000",
            "M30",
            "%",
        ]
    )
    return "\n".join(lines) + "\n"
