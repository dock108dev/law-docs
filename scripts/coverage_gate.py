"""Enforce separate line and branch thresholds across all three Python components."""

import json, sys
from pathlib import Path

report = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json").read_text())
groups = {"shared": [], "crash": [], "plea": []}
for path, record in report["files"].items():
    group = (
        "crash"
        if "engines/crash_report/" in path
        else "plea"
        if "engines/plea_reports/" in path
        else "shared"
    )
    groups[group].append(record["summary"])
failed = []
for group, records in groups.items():
    assert records, f"{group} missing from coverage report"
    values = {
        key: sum(r[key] for r in records)
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    line = 100 * values["covered_lines"] / values["num_statements"]
    branch = 100 * values["covered_branches"] / max(1, values["num_branches"])
    print(f"{group}: {line:.1f}% lines, {branch:.1f}% branches")
    if min(line, branch) < 80:
        failed.append(group)
if failed:
    raise SystemExit("Coverage below 80%: " + ", ".join(failed))
