from __future__ import annotations

import re
from pathlib import Path

from novel_flywheel.api.errors import safe_http_exception
from novel_flywheel.failure_boundary import (
    project_safe_failure,
    safe_local_validation_message,
)


SECRET_SENTINEL = "api_key=SECRET-SENTINEL C:\\private\\route.log provider-body"


def test_safe_failure_projects_only_static_message_and_hash() -> None:
    exc = RuntimeError(SECRET_SENTINEL)
    failure = project_safe_failure(
        exc,
        boundary="wizard.interview",
        code="wizard.interview_failed",
        family="provider.request_failed",
        message="访谈模型暂时不可用，请稍后重试。",
        retryable=True,
        recovery_action="retry_interview",
    )

    serialized = failure.model_dump_json()
    assert SECRET_SENTINEL not in serialized
    assert "C:\\private" not in serialized
    assert "访谈模型暂时不可用" in serialized
    assert len(failure.failure_sha256) == 64
    assert failure.persistence_summary().endswith(
        f"incident={failure.failure_sha256[:16]}]"
    )


def test_safe_http_exception_uses_one_versioned_detail_contract() -> None:
    exc = ValueError(SECRET_SENTINEL)
    projected = safe_http_exception(
        exc,
        status_code=422,
        boundary="reference.import",
        code="reference.request_invalid",
        family="request.domain_validation",
        message="参考资料未通过校验，请检查输入后重试。",
    )

    assert projected.status_code == 422
    assert projected.detail["version"] == 1
    assert projected.detail["code"] == "reference.request_invalid"
    assert SECRET_SENTINEL not in str(projected.detail)


def test_local_validation_feedback_keeps_actionable_text_but_redacts_secrets() -> None:
    assert safe_local_validation_message(
        ValueError("query is not allowed")
    ) == "query is not allowed"
    redacted = safe_local_validation_message(ValueError(SECRET_SENTINEL))
    assert "SECRET-SENTINEL" not in redacted
    assert "C:\\private" not in redacted
    assert "<redacted>" in redacted
    assert "<path>" in redacted


def test_api_and_workflow_boundaries_do_not_project_raw_exception_text() -> None:
    root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    api_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "api").glob("*.py"))
    )
    workflow_source = (root / "workflows.py").read_text(encoding="utf-8")

    forbidden_api = (
        "detail=str(exc)",
        '"message": str(exc)',
        "describe_error(exc)",
    )
    for fragment in forbidden_api:
        assert fragment not in api_source
    assert re.search(r"(?<!raw_)error\s*=\s*str\(exc\)", workflow_source) is None
    assert '"error": describe_error(exc)' not in workflow_source
