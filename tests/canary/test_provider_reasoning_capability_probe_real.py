from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canary import provider_reasoning_capability_probe_real as probe


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = (
    REPO_ROOT
    / "docs/superpowers/reports/r1-ptr7-reasoning-probe-mat"
    / probe.COHORT_ID
)
LIVE_DB = REPO_ROOT / "data/app.db"
LIVE_PROJECTS = REPO_ROOT / "data/projects"


def _clean_git(_repo_root: Path, *, require_clean: bool):
    del require_clean
    return {
        "branch": probe.EXPECTED_BRANCH,
        "head": "a" * 40,
        "worktree": "clean",
    }


def test_packet_and_synthetic_request_match_final_authorization() -> None:
    packet = probe.verify_fresh_packet_exact(REPO_ROOT, PACKET_ROOT)
    request = probe._synthetic_request()
    assert packet["candidate"]["candidate_sha256"] == probe.CANDIDATE_SHA256
    assert packet["definition"]["definition_sha256"] == probe.DEFINITION_SHA256
    assert packet["fixture"]["fixture_sha256"] == probe.FIXTURE_SHA256
    assert request["receipt"]["fixture_sha256"] == probe.FIXTURE_SHA256
    assert request["receipt"]["raw_prompt_omitted"] is True
    assert request["receipt"]["raw_story_omitted"] is True
    assert len(request["user"]) > 1000
    assert "story" not in request["user"].casefold()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"parameter_disposition": "rejected"}, "UNSUPPORTED"),
        ({
            "parameter_disposition": "accepted", "finish_reason": "max_tokens",
            "thinking_block_count": 1, "visible_characters": 0,
            "tool_block_count": 0, "reasoning_tokens_if_reported": None,
            "final_artifact_exact": False, "token_separation_reported": False,
        }, "IGNORED"),
        ({
            "parameter_disposition": "accepted", "finish_reason": "end_turn",
            "thinking_block_count": 1, "visible_characters": 40,
            "tool_block_count": 0, "reasoning_tokens_if_reported": 7000,
            "final_artifact_exact": True, "token_separation_reported": True,
        }, "SUPPORTED"),
        ({
            "parameter_disposition": "accepted", "finish_reason": "end_turn",
            "thinking_block_count": 1, "visible_characters": 40,
            "tool_block_count": 0, "reasoning_tokens_if_reported": None,
            "final_artifact_exact": True, "token_separation_reported": False,
        }, "UNKNOWN"),
    ],
)
def test_fail_closed_classification(state: dict, expected: str) -> None:
    assert probe._classification(state)[0] == expected


def test_stream_observer_counts_without_retaining_content() -> None:
    state = probe._new_observation()
    state.update({"block_types": {}, "text_parts": []})
    probe._consume_event({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "thinking", "thinking": "private"},
    }, state)
    probe._consume_event({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "thinking_delta", "thinking": " work"},
    }, state)
    probe._consume_event({
        "type": "content_block_start", "index": 1,
        "content_block": {"type": "text", "text": "{"},
    }, state)
    probe._consume_event({
        "type": "content_block_delta", "index": 1,
        "delta": {"type": "text_delta", "text": "}"},
    }, state)
    probe._consume_event({
        "type": "message_delta", "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 123, "reasoning_tokens": 100,
                  "final_output_tokens": 23},
    }, state)
    assert state["thinking_block_count"] == 1
    assert state["reasoning_characters_if_observable"] == 12
    assert state["visible_characters"] == 2
    assert state["finish_reason"] == "end_turn"
    assert state["reasoning_tokens_if_reported"] == 100


def test_materialize_and_signed_validate_are_offline_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_git_preflight", _clean_git)
    output = tmp_path / "real-observation-v1"
    result = probe.materialize_signed_authorization(
        repo_root=REPO_ROOT, packet_root=PACKET_ROOT, output_root=output,
        live_database=LIVE_DB, live_projects=LIVE_PROJECTS,
    )
    assert result["receipt"]["overall_status"] == "exact"
    assert result["receipt"]["external_action_counters"] == probe.ZERO_COUNTERS
    assert result["signed_approval"]["schema"] == (
        "ProviderReasoningCapabilityProbeSignedApprovalV1"
    )
    assert not (output / "approval-ledger/reserved-v1.json").exists()
    assert not (output / "approval-ledger/consumed-v1.json").exists()
    validated = probe.validate_signed_authorization(
        repo_root=REPO_ROOT, packet_root=PACKET_ROOT, output_root=output,
        live_database=LIVE_DB, live_projects=LIVE_PROJECTS,
        require_clean=False,
    )
    assert validated == result["receipt"]


def test_one_fake_execution_consumes_ledger_and_cannot_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_git_preflight", _clean_git)
    output = tmp_path / "real-observation-v1"
    probe.materialize_signed_authorization(
        repo_root=REPO_ROOT, packet_root=PACKET_ROOT, output_root=output,
        live_database=LIVE_DB, live_projects=LIVE_PROJECTS,
    )

    async def fake_call(*, live_database, request, counters):
        del live_database, request
        for key in counters:
            counters[key] += 1
        return {
            "observation": {
                "parameter_disposition": "accepted", "http_status_class": "2xx",
                "finish_reason": "end_turn", "input_tokens": 100,
                "output_tokens": 200, "reasoning_tokens_if_reported": None,
                "final_output_tokens_if_reported": None,
                "token_separation_reported": False, "thinking_block_count": 1,
                "final_text_block_count": 1, "tool_block_count": 0,
                "visible_characters": 30, "reasoning_characters_if_observable": 40,
                "unknown_block_count": 0, "block_type_sequence_sha256": "b" * 64,
                "final_artifact_exact": True, "final_artifact_sha256": "c" * 64,
            },
            "cost_currency": "USD", "actual_cost_microunits": 10,
            "maximum_cost_microunits": probe.MAX_USD_MICROUNITS,
        }

    monkeypatch.setattr(probe, "_one_provider_request", fake_call)
    result = probe.execute_real_probe_once(
        repo_root=REPO_ROOT, packet_root=PACKET_ROOT, output_root=output,
        live_database=LIVE_DB, live_projects=LIVE_PROJECTS,
    )
    assert result["execution"]["classification"] == "UNKNOWN"
    assert result["execution"]["real_provider_probe"] == "EXECUTED_ONCE"
    assert result["execution"]["external_action_counters"] == {
        key: 1 for key in probe.ZERO_COUNTERS
    }
    assert (output / "approval-ledger/reserved-v1.json").is_file()
    assert (output / "approval-ledger/consumed-v1.json").is_file()
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private" not in serialized
    with pytest.raises(probe.ProviderReasoningProbeRealError) as exc:
        probe.execute_real_probe_once(
            repo_root=REPO_ROOT, packet_root=PACKET_ROOT, output_root=output,
            live_database=LIVE_DB, live_projects=LIVE_PROJECTS,
        )
    assert exc.value.reason_code == "operational_ledger_not_unused"


def test_no_hidden_retry_in_real_request_source() -> None:
    source = Path(probe.__file__).read_text(encoding="utf-8")
    section = source.split("async def _one_provider_request", 1)[1].split(
        "def execute_real_probe_once", 1,
    )[0]
    assert "adapter.client.stream(" in section
    assert "post_stream(" not in section
    assert "for attempt" not in section
    assert "thinking\": {\"type\": \"enabled\", \"budget_tokens\"" in section
