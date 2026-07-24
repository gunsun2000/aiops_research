import csv
import json
from pathlib import Path

from aiops_k8s_agents.research_event_store import (
    EVENT_STREAMS,
    InMemoryResearchEventStore,
    JsonlResearchEventStore,
)


def test_jsonl_event_store_writes_traceable_research_artifacts(tmp_path):
    store = JsonlResearchEventStore(
        root_dir=tmp_path,
        experiment_id="experiment-1",
        experiment_config={"policy_version": "mutual-v1"},
    )
    store.append(
        "peer_reviews",
        {
            "run_id": "run-1",
            "review_id": "review-1",
            "verdict": "approve",
        },
    )
    paths = store.finalize(
        {
            "run_id": "run-1",
            "policy_version": "mutual-v1",
            "valid": True,
            "final_status": "recovered",
            "selected_action": {"kind": "scale_out", "replicas": 2},
            "peer_reviews": [{"verdict": "approve"}],
            "negotiation": {"round_count": 1, "consensus": "approved"},
            "post_execution_reviews": [{"approved": True}],
            "human_review_required": False,
        }
    )

    peer_review_path = Path(paths["peer_reviews"])
    assert peer_review_path.exists()
    assert Path(paths["final_report_json"]).exists()
    assert Path(paths["final_report_md"]).exists()
    assert Path(paths["statistics_csv"]).exists()
    assert set(EVENT_STREAMS).issubset(paths)
    assert all(Path(paths[stream]).exists() for stream in EVENT_STREAMS)
    assert json.loads(peer_review_path.read_text(encoding="utf-8").splitlines()[0])[
        "review_id"
    ] == "review-1"

    with Path(paths["statistics_csv"]).open(
        encoding="utf-8", newline=""
    ) as stream:
        row = next(csv.DictReader(stream))
    assert row["consensus"] == "approved"
    assert row["selected_action"] == "scale_out"


def test_in_memory_event_store_retains_stream_order_and_final_report():
    store = InMemoryResearchEventStore()
    store.append("initial_decisions", {"decision_id": "decision-1"})
    store.append("initial_decisions", {"decision_id": "decision-2"})

    paths = store.finalize({"run_id": "run-1", "valid": False})

    assert [
        event["decision_id"] for event in store.events["initial_decisions"]
    ] == ["decision-1", "decision-2"]
    assert store.final_report["run_id"] == "run-1"
    assert paths == {}
