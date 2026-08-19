from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def write_partition_report(
    report: Mapping[str, Any], artifact_root: str | Path
) -> Path:
    plan_id = str(report["plan"]["plan_id"])
    output_directory = Path(artifact_root).expanduser().resolve() / plan_id
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / "report.json"
    temporary_path = output_directory / "report.json.tmp"
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return output_path
