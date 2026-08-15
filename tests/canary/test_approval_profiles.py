from tools.canary.approval_profiles import (
    approval_profile_registry_v1,
)


def test_profile_registry_contains_only_the_two_approved_profiles() -> None:
    registry = approval_profile_registry_v1()
    assert tuple(registry) == ("c0b_smoke_1", "pa_strict_tool_obs_1")
    assert registry["c0b_smoke_1"].approval_scope == (
        "C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1"
    )
    assert registry["pa_strict_tool_obs_1"].approval_scope == (
        "PA_STRICT_TOOL_OBS_1_SINGLE_REAL_PROVIDER_OBSERVATION"
    )
