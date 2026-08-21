from datetime import datetime, timezone
from pathlib import Path

from tools.canary.approval_profiles import (
    SHORT_COMPLETION_PROFILE_ID,
    approval_profile,
)
from tools.canary.c0b_packet import prepare_c0b_smoke_packet
from tools.canary.hash_manifest import (
    GENERIC_CANARY_IMPORT_SCOPE_ID,
    validate_import_closure,
)
from tools.canary.network_sentinel import FailClosedNetworkSentinel


ROOT = Path(__file__).parents[2]


def test_fresh_short_base_validate_only_import_closure_is_exact(
    tmp_path: Path, monkeypatch,
) -> None:
    import keyring

    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during validate-only")
        ),
    )
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    sentinel = FailClosedNetworkSentinel()
    with sentinel:
        plan, _approval, _packet = prepare_c0b_smoke_packet(
            live_database_path=ROOT / "data" / "app.db",
            fixture_path=(
                ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
            ),
            plan_path=tmp_path / "base-plan.json",
            approval_path=tmp_path / "base-approval.json",
            packet_path=tmp_path / "base-packet.json",
            cohort_id="sc-ic1-import-closure-test",
            run_namespace="sc-ic1-import-closure-test",
            now=datetime(2026, 8, 21, tzinfo=timezone.utc),
            feature_flags=profile.required_flags(),
        )
        manifest = validate_import_closure(
            ROOT / "tools" / "canary",
            approved_third_party=(
                plan["approved_dependency_manifest"]["third_party"]
            ),
        )

    assert sentinel.network_call_count == 0
    assert manifest["launcher_sha256"] == plan["launcher_sha256"]
    assert manifest["import_scope_id"] == GENERIC_CANARY_IMPORT_SCOPE_ID
    assert manifest["approved_third_party"] == []
    assert "provider_reasoning_capability_probe_real.py" in (
        manifest["excluded_probe_entrypoints"]
    )
