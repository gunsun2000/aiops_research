from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build or refresh config/ops_llm_benchmark.json metadata from saved "
            "experiment run records. Per-model metrics are updated only when the "
            "input records include a recognizable model field."
        )
    )
    parser.add_argument(
        "--base-config",
        default="config/ops_llm_benchmark.json",
        help="Existing benchmark JSON to use as the candidate/policy template.",
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSON or JSONL run file. Can be passed multiple times.",
    )
    parser.add_argument(
        "--output",
        default="config/ops_llm_benchmark.generated.json",
        help="Output benchmark JSON path.",
    )
    parser.add_argument(
        "--benchmark-run-id",
        default="",
        help="Optional stable benchmark run id. Defaults to a timestamped id.",
    )
    args = parser.parse_args()

    base_path = Path(args.base_config)
    data = json.loads(base_path.read_text(encoding="utf-8"))
    records = []
    for input_path in args.input:
        records.extend(_load_records(Path(input_path)))

    _update_metadata(data, args.input, args.benchmark_run_id)
    _update_candidates_when_model_records_exist(data, records)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output_path), "records": len(records)}, indent=2))
    return 0


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return [dict(item) for item in payload["records"]]
        return [payload]
    return []


def _update_metadata(
    data: dict[str, Any],
    inputs: list[str],
    benchmark_run_id: str,
) -> None:
    run_id = benchmark_run_id or datetime.now().strftime("ops-llm-runs-%Y%m%d-%H%M%S")
    data["metadata"] = {
        "data_source": "run_records",
        "benchmark_run_id": run_id,
        "generated_from": inputs,
        "is_synthetic": False,
        "last_updated": datetime.now().date().isoformat(),
        "notes": [
            "Generated from available experiment run records.",
            (
                "Candidate metrics are preserved from the base config when input "
                "records do not contain standardized per-model fields."
            ),
        ],
    }


def _update_candidates_when_model_records_exist(
    data: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        model = _extract_model(record)
        if model:
            by_model[model].append(record)
    if not by_model:
        return

    for candidate in data.get("candidates", []):
        model_records = by_model.get(str(candidate.get("model", "")))
        if not model_records:
            continue
        total = len(model_records)
        valid = sum(1 for record in model_records if _record_success(record))
        metric_success = sum(1 for record in model_records if _metric_success(record))
        candidate["correct_detection_runs"] = valid
        candidate["total_detection_runs"] = total
        candidate["metric_success_runs"] = metric_success
        candidate["total_metric_runs"] = total

        ttd_values = [
            float(value)
            for value in (_extract_number(record, "ttd_seconds") for record in model_records)
            if value is not None and value > 0
        ]
        if ttd_values:
            candidate["average_ttd_seconds"] = round(sum(ttd_values) / len(ttd_values), 6)


def _extract_model(record: dict[str, Any]) -> str:
    for key in ("model", "selected_model", "selected_llm", "runtime_model"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("model") or metadata.get("runtime_model")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _record_success(record: dict[str, Any]) -> bool:
    for key in ("correct", "success", "valid", "measurement_valid"):
        if key in record:
            return bool(record[key])
    result = record.get("result")
    if isinstance(result, dict) and "valid" in result:
        return bool(result["valid"])
    return False


def _metric_success(record: dict[str, Any]) -> bool:
    for key in ("metric_success", "metric_successful", "measurement_valid"):
        if key in record:
            return bool(record[key])
    return _record_success(record)


def _extract_number(record: dict[str, Any], key: str) -> float | None:
    value = record.get(key)
    if value is None and isinstance(record.get("metrics"), dict):
        value = record["metrics"].get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
