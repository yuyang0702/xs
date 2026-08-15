from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.canary.approval_closure import CHECK_NAMES, validate_c0b_approval_closure
from tools.canary.approval_store import ApprovalConsumptionStore
from tools.canary.c0b_packet import prepare_c0b_smoke_packet
from tools.canary.contracts import (
    build_canary_experiment_plan_v1, build_canary_plan_approval_v1,
)


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


@pytest.fixture()
def closure_packet(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    packet_path = tmp_path / "packet.json"
    ledger = tmp_path / "approval-ledger"
    ledger.mkdir()
    plan, approval, packet = prepare_c0b_smoke_packet(
        live_database_path=LIVE_DB, fixture_path=FIXTURE,
        plan_path=plan_path, approval_path=approval_path, packet_path=packet_path,
        cohort_id="c0b-p11-closure", run_namespace="c0b-p11-closure",
    )
    return {
        "root": tmp_path, "plan": plan, "approval": approval, "packet": packet,
        "plan_path": plan_path, "approval_path": approval_path,
        "packet_path": packet_path, "ledger": ledger,
    }


def validate(item, *, now=None):
    return validate_c0b_approval_closure(
        plan_path=item["plan_path"], approval_path=item["approval_path"],
        packet_path=item["packet_path"], workload_fixture_path=FIXTURE,
        live_database_path=LIVE_DB, live_project_root=LIVE_PROJECTS,
        canary_root=item["root"] / "future-canary-root",
        approval_ledger_root=item["ledger"],
        cli_approved_plan_sha256=item["plan"]["plan_sha256"], now=now,
    )


def replace_plan(item, mutate) -> None:
    payload = deepcopy(item["plan"])
    payload.pop("plan_sha256")
    mutate(payload)
    plan = build_canary_experiment_plan_v1(payload)
    approval_payload = deepcopy(item["approval"])
    approval_payload.pop("approval_sha256")
    approval_payload["approved_plan_sha256"] = plan["plan_sha256"]
    approval_payload["approved_launcher_sha256"] = plan["launcher_sha256"]
    approval = build_canary_plan_approval_v1(approval_payload)
    item["plan"], item["approval"] = plan, approval
    write_json(item["plan_path"], plan)
    write_json(item["approval_path"], approval)


def check(receipt, name):
    return next(item for item in receipt["ordered_checks"] if item["name"] == name)


def test_full_validate_only_closes_all_25_checks_with_zero_external_actions(closure_packet) -> None:
    receipt = validate(closure_packet)
    assert receipt["overall_status"] == "exact", receipt
    assert [item["name"] for item in receipt["ordered_checks"]] == list(CHECK_NAMES)
    assert len(receipt["ordered_checks"]) == 25
    assert set(receipt["external_action_counters"].values()) == {0}
    assert len(receipt["validation_receipt_sha256"]) == 64
    assert receipt["approval_state"] == "disabled_candidate"


@pytest.mark.parametrize(("field", "check_name"), [
    ("approved_build_fingerprint", "build_fingerprint"),
    ("approved_execution_config_fingerprint", "execution_config_fingerprint"),
    ("expected_runtime_execution_fingerprint", "runtime_execution_fingerprint"),
    ("provider_descriptor_definition_sha256", "provider_descriptor_manifest"),
    ("role_binding_manifest_definition_sha256", "role_route_binding_manifest"),
])
def test_runtime_and_route_mismatches_are_blocked(closure_packet, field, check_name) -> None:
    replace_plan(closure_packet, lambda plan: plan.__setitem__(field, "f" * 64))
    receipt = validate(closure_packet)
    assert receipt["overall_status"] == "blocked"
    assert check(receipt, check_name)["status"] == "blocked"


def test_pricing_manifest_mismatch_is_blocked(closure_packet) -> None:
    replace_plan(closure_packet, lambda plan: plan["budgets"].__setitem__("price_catalog_sha256", "e" * 64))
    receipt = validate(closure_packet)
    assert check(receipt, "pricing_evidence_manifest")["status"] == "blocked"


def test_happy_test_group_cannot_replace_approved_default_group(closure_packet, monkeypatch) -> None:
    from decimal import Decimal
    from tools.canary.monetary import PriceCatalogV1, PriceRuleV1
    import tools.canary.approval_closure as closure

    old = closure.production_price_catalog().definitions()
    changed = []
    for item in old:
        values = dict(item)
        if values["provider"] == "happy" and values["model"] == "qwen-max-thinking":
            values["relay_group"] = "test"
            values["input_rate_per_unit"] = "0.6"
            values["output_rate_per_unit"] = "2.4"
        changed.append(PriceRuleV1(
            provider=values["provider"], model=values["model"], relay_group=values["relay_group"],
            currency=values["currency"], unit_tokens=values["unit_tokens"],
            input_rate_per_unit=Decimal(values["input_rate_per_unit"]),
            cached_input_rate_per_unit=Decimal(values["cached_input_rate_per_unit"]),
            output_rate_per_unit=Decimal(values["output_rate_per_unit"]),
            reasoning_token_rule=values["reasoning_token_rule"], source_type=values["source_type"],
            evidence_sha256=values["evidence_sha256"], effective_evidence_date=values["effective_evidence_date"],
        ))
    catalog = PriceCatalogV1(changed)
    definitions = catalog.definitions()
    price_hash = domain_sha256("novel-flywheel-c0b-price-catalog-v1", definitions)
    replace_plan(closure_packet, lambda plan: plan["budgets"].__setitem__("price_catalog_sha256", price_hash))
    closure_packet["packet"]["price_catalog"] = definitions
    write_json(closure_packet["packet_path"], closure_packet["packet"])
    monkeypatch.setattr(closure, "production_price_catalog", lambda: catalog)
    receipt = validate(closure_packet)
    assert check(receipt, "pricing_evidence_manifest")["status"] == "exact"
    assert check(receipt, "happy_relay_group")["status"] == "blocked"


def test_approval_budget_definition_below_48_is_not_the_approved_smoke_contract(closure_packet) -> None:
    budget = deepcopy(closure_packet["approval"]["approved_budget"])
    budget["maximum_model_calls_per_run"] = 47
    budget["maximum_total_model_calls"] = 47
    body = {key: value for key, value in budget.items() if key != "definition_sha256"}
    budget["definition_sha256"] = domain_sha256("novel-flywheel-c0b-approved-budget-v1", body)
    payload = deepcopy(closure_packet["approval"])
    payload.pop("approval_sha256")
    payload["approved_budget"] = budget
    closure_packet["approval"] = build_canary_plan_approval_v1(payload)
    closure_packet["packet"]["approval_budget"] = budget
    write_json(closure_packet["approval_path"], closure_packet["approval"])
    write_json(closure_packet["packet_path"], closure_packet["packet"])
    receipt = validate(closure_packet)
    assert check(receipt, "call_budget_definition")["status"] == "blocked"


def test_stop_condition_mismatch_is_blocked(closure_packet) -> None:
    replace_plan(closure_packet, lambda plan: plan["stop_conditions"].append("unapproved_stop"))
    receipt = validate(closure_packet)
    assert check(receipt, "stop_condition_manifest")["status"] == "blocked"


def test_phase1b_true_returns_a_structured_blocked_receipt(closure_packet) -> None:
    raw = deepcopy(closure_packet["plan"])
    raw["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] = True
    body = deepcopy(raw)
    body.pop("plan_sha256")
    raw["plan_sha256"] = domain_sha256("novel-flywheel-canary-experiment-plan-v1", body)
    write_json(closure_packet["plan_path"], raw)
    receipt = validate(closure_packet)
    assert receipt["overall_status"] == "blocked"
    assert check(receipt, "phase1b_disabled")["reason_code"] == "phase1b_environment_flag_enabled"
    assert set(receipt["external_action_counters"].values()) == {0}


def test_expired_approval_returns_structured_blocked_receipt(closure_packet) -> None:
    past = datetime.now(timezone.utc) - timedelta(days=2)
    payload = deepcopy(closure_packet["approval"])
    payload.pop("approval_sha256")
    payload["execution_window"] = {
        "not_before": past.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "not_after": (past + timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload["approval_expiry"] = (past + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    closure_packet["approval"] = build_canary_plan_approval_v1(payload)
    write_json(closure_packet["approval_path"], closure_packet["approval"])
    receipt = validate(closure_packet)
    assert check(receipt, "approval_execution_window")["reason_code"] == "approval_expired"


def test_reserved_or_consumed_approval_is_blocked_without_consuming_it(closure_packet) -> None:
    store = ApprovalConsumptionStore(closure_packet["ledger"])
    store.reserve(closure_packet["approval"])
    receipt = validate(closure_packet)
    assert check(receipt, "approval_cohort_single_use")["status"] == "blocked"
    assert set(receipt["external_action_counters"].values()) == {0}


def test_launcher_validate_only_runs_full_closure_without_credential_or_network(
    closure_packet, monkeypatch, capsys,
) -> None:
    import keyring
    from tools.canary.launcher import main

    monkeypatch.setattr(
        keyring, "get_password",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during validate-only")
        ),
    )
    code = main([
        "--plan", str(closure_packet["plan_path"]),
        "--approval", str(closure_packet["approval_path"]),
        "--approved-plan-sha256", closure_packet["plan"]["plan_sha256"],
        "--validate-only", "--approval-packet", str(closure_packet["packet_path"]),
        "--workload-fixture", str(FIXTURE),
        "--canary-root", str(closure_packet["root"] / "future-canary-root"),
        "--approval-ledger-root", str(closure_packet["ledger"]),
        "--live-database", str(LIVE_DB),
        "--live-project-root", str(LIVE_PROJECTS),
    ])
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["overall_status"] == "exact"
    assert output["network_call_count"] == 0
    assert set(output["external_action_counters"].values()) == {0}
