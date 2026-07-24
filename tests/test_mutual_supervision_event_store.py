import csv
import json
from pathlib import Path

from aiops_k8s_agents.research_event_store import (
    EVENT_STREAMS,
    InMemoryResearchEventStore,
    JsonlResearchEventStore,
)
from aiops_k8s_agents.research_protocol import (
    ResearchProtocolProfile,
    load_research_protocol,
)


def test_jsonl_event_store_writes_traceable_research_artifacts(tmp_path):
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    protocol_snapshot = profile.to_canonical_dict()
    protocol_identity = {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "config_hash": profile.config_hash,
    }
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
            "protocol_profile": protocol_identity,
            "protocol_profile_snapshot": protocol_snapshot,
            "active_agents": ["AIServiceHASupportAgent"],
            "agent_runtimes": {
                "AIServiceHASupportAgent": "deterministic",
            },
            "agent_contributions": {
                "AIServiceHASupportAgent": {
                    "decisions": 1,
                    "approvals": 1,
                    "revisions": 0,
                    "vetoes": 0,
                    "post_reviews": 1,
                    "reward": 0.9,
                }
            },
            "valid": True,
            "final_status": "recovered",
            "selected_action": {"kind": "scale_out", "replicas": 2},
            "peer_reviews": [{"verdict": "approve"}],
            "negotiation": {
                "round_count": 1,
                "consensus": "approved",
                "strategy": "role_based_veto",
            },
            "post_execution_reviews": [{"approved": True}],
            "human_review_required": False,
            "metadata": {
                "protocol_profile": protocol_identity,
                "protocol_profile_snapshot": protocol_snapshot,
            },
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
    assert row["consensus_strategy"] == "role_based_veto"
    assert row["protocol_profile_id"] == "four-agent-role-veto-v1"
    assert row["protocol_profile_version"] == "1.0.0"
    assert row["protocol_config_hash"] == profile.config_hash
    assert row["active_agents"] == "AIServiceHASupportAgent"
    assert row["agent_runtimes"] == "AIServiceHASupportAgent=deterministic"
    assert row["selected_action"] == "scale_out"
    markdown = Path(paths["final_report_md"]).read_text(encoding="utf-8")
    assert "four-agent-role-veto-v1" in markdown
    assert "AIServiceHASupportAgent=deterministic" in markdown
    assert "role_based_veto" in markdown
    experiment_config = json.loads(
        Path(paths["experiment_config"]).read_text(encoding="utf-8")
    )
    assert experiment_config["protocol_profile"] == protocol_identity
    assert (
        experiment_config["protocol_profile_snapshot"]
        == protocol_snapshot
    )
    final_report = json.loads(
        Path(paths["final_report_json"]).read_text(encoding="utf-8")
    )
    assert final_report["protocol_profile"] == protocol_identity
    assert (
        ResearchProtocolProfile.from_dict(
            final_report["protocol_profile_snapshot"]
        )
        == profile
    )
    assert experiment_config["active_agents"] == ["AIServiceHASupportAgent"]


def test_profile_and_contribution_streams_are_available():
    assert "protocol_profiles" in EVENT_STREAMS
    assert "agent_contributions" in EVENT_STREAMS


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
