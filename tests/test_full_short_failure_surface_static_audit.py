from tools.diagnostics.audit_full_short_failure_surface_architecture import audit


def test_full_short_stop_loss_static_source_audit_is_exact() -> None:
    result = audit()

    assert result["status"] == "PASS", result
    assert result["failed_checks"] == []
    assert set(result["metrics"].values()) == {0}
