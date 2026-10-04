import hashlib
import json
from pathlib import Path

import httpx
import pytest

from novel_flywheel.generated_artifacts import (
    ArtifactConversionError,
    GeneratedArtifactGateway,
)
from novel_flywheel.provider_response_capture import (
    ReviewDiagnosticCaptureScopeError,
    ReviewDiagnosticCaptureObserverV1,
    ShortAutoRecoveryCaptureObserverV1,
)
from novel_flywheel.providers.http import HttpProvider
from novel_flywheel.production_incidents import classify_production_failure


PROVIDER_ID = "1e915fbe-7b79-4a20-8eaa-ab78bdf5b1ea"
MODEL_ID = "d058f66c-e536-4738-8c34-3f2f3b49dee0"


def _observer(tmp_path: Path) -> ReviewDiagnosticCaptureObserverV1:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
        context={"run_id": "06741882a6114b86a91730076d9626b3", "api_key": "secret"},
    )
    observer.bind_stage_context(
        stage_id="segment-05-receipt-window-01",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="a" * 64,
        contract_runtime_input_required=True,
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id=MODEL_ID, route_fingerprint="route-v1",
    )
    return observer


def _bind_request(observer: ReviewDiagnosticCaptureObserverV1) -> bytes:
    payload = {
        "model": "doubao-seed-character-260628",
        "input": [{"role": "user", "content": "review candidate"}],
        "max_output_tokens": 1084,
        "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
        "stream": True,
        "headers": {"Authorization": "must-not-persist"},
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    observer.bind_model_request(protocol="openai-responses", request=payload)
    observer.before_http_dispatch(
        method="POST", url="https://ark.cn-beijing.volces.com/api/v3/responses",
        payload=payload, request_bytes=raw,
    )
    observer.before_http_post()
    observer.before_network_request()
    return raw


def test_capture_records_wire_adapter_and_validator_events_without_secrets(
    tmp_path: Path,
) -> None:
    observer = _observer(tmp_path)
    _bind_request(observer)
    raw = json.dumps({
        "output": [
            {"type": "reasoning", "text": "hidden thought"},
            {"type": "output_text", "text": "{\"missing\":true}"},
        ],
        "finish_reason": "stop",
    }, ensure_ascii=False).encode()
    observer.capture_provider_protocol_input(
        data=raw, status_code=200, content_type="application/json",
        encoding="utf-8", transport_complete=True,
    )
    observer.capture_contract_runtime_input(
        '{"missing":true}', adapter_id="openai-responses", adapter_version=1,
        finish_reason="stop", transport_complete=True,
    )
    observer.capture_review_diagnostic(
        event="validator-failure", normalized_payload={"missing": True},
        instance_path="/required_field", schema_path="#/required",
        findings=[{"code": "required_fields_missing"}],
    )

    root = tmp_path / "capture"
    saved = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.json"))
    assert "must-not-persist" not in saved
    assert "hidden thought" not in saved
    assert "missing_fields" not in saved or "required_fields_missing" in saved
    assert (root / "10-request.json").is_file()
    assert (root / "20-provider-response.json").is_file()
    assert (root / "30-adapter-output.json").is_file()
    assert list((root / "events").glob("*.json"))
    response_record = json.loads((root / "20-provider-response.json").read_text())
    assert response_record["raw_length"] == len(raw)
    assert response_record["structured"]["output"][0]["hidden_content_redacted"] is True


def test_short_auto_recovery_capture_keeps_each_dispatch_independent(
    tmp_path: Path,
) -> None:
    class BaseObserver:
        def bind_route(self, **_kwargs):
            return None
        def bind_stage_context(self, **_kwargs):
            return None
        def bind_model_request(self, **_kwargs):
            return None
        def before_http_dispatch(self, **_kwargs):
            return None
        def before_http_post(self):
            return None
        def before_network_request(self):
            return None
        def capture_provider_protocol_input(self, **_kwargs):
            return None
        def capture_contract_runtime_input(self, _text=None, **_kwargs):
            return None
        def after_http_response(self, **_kwargs):
            return None
        def after_http_failure(self, **_kwargs):
            return None

    class Registry:
        @staticmethod
        def inspect_public_route(_provider_id, _model_id):
            return type("Public", (), {
                "destination": "https://ark.cn-beijing.volces.com/api/v3/responses",
            })()

    observer = ShortAutoRecoveryCaptureObserverV1(
        base_observer=BaseObserver(), registry=Registry(),
        store_root=tmp_path / "auto",
        context={"run_id": "run", "authorization_revision": "short-auto-receipt-correction-v1"},
    )
    route = {
        "role": "review", "lane": "primary", "provider_id": PROVIDER_ID,
        "model_id": MODEL_ID, "route_fingerprint": "route-v1",
    }
    payload = {"model": "doubao-seed-character-260628", "messages": [{"role": "user", "content": "immutable candidate"}], "max_tokens": 32}
    for attempt in (1, 2):
        payload = {
            **payload,
            "messages": [{
                "role": "user",
                "content": (
                    "immutable candidate"
                    if attempt == 1 else
                    "immutable candidate\nFEEDBACK=/viewpoint_valid"
                ),
            }],
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        observer.bind_stage_context(
            stage_id="segment-05", contract_name="draft_segment_semantic_receipt",
            contract_version=1, contract_schema_sha256="b" * 64,
            contract_runtime_input_required=True,
            contract_attempt_index=attempt, contract_route="primary",
            contract_route_attempt=attempt,
        )
        observer.bind_route(**route)
        observer.bind_model_request(protocol="openai-chat", request=payload)
        observer.before_http_dispatch(
            method="POST", url="https://ark.cn-beijing.volces.com/api/v3/responses",
            payload=payload, request_bytes=raw,
        )
        observer.before_http_post(); observer.before_network_request()
        observer.capture_provider_protocol_input(
            data=json.dumps({"output": [{"text": f"response-{attempt}"}]}).encode(),
            status_code=200, content_type="application/json", encoding="utf-8",
            transport_complete=True,
        )
        observer.capture_contract_runtime_input(
            f"response-{attempt}", adapter_id="openai-chat", adapter_version=1,
            finish_reason="completed", transport_complete=True,
        )
        observer.after_http_response(status_code=200)
    assert (tmp_path / "auto" / "attempt-01" / "10-request.json").is_file()
    assert (tmp_path / "auto" / "attempt-02" / "10-request.json").is_file()
    first = (tmp_path / "auto" / "attempt-01" / "30-adapter-output.json").read_text()
    second = (tmp_path / "auto" / "attempt-02" / "30-adapter-output.json").read_text()
    assert "response-1" in first and "response-2" in second
    second_request = (tmp_path / "auto" / "attempt-02" / "10-request.json").read_text()
    assert "FEEDBACK=/viewpoint_valid" in second_request


def test_short_auto_recovery_capture_works_without_full_short_base_observer(
    tmp_path: Path,
) -> None:
    class Registry:
        @staticmethod
        def inspect_public_route(_provider_id, _model_id):
            return type("Public", (), {
                "destination": "https://ark.cn-beijing.volces.com/api/v3/responses",
            })()

    observer = ShortAutoRecoveryCaptureObserverV1(
        base_observer=None,
        registry=Registry(),
        store_root=tmp_path / "auto",
        context={"run_id": "run", "authorization_revision": "short-auto-receipt-correction-v3"},
    )
    assert observer.exact_full_short_execution is False
    assert observer.sealed_route_for_next_logical_stage is None
    assert observer.capacity_admission_context is None
    with pytest.raises(AttributeError):
        _ = observer.unregistered_observer_attribute
    payload = {"model": "current-model", "messages": [{"role": "user", "content": "candidate"}]}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    observer.bind_stage_context(
        stage_id="segment-05", contract_name="draft_segment_semantic_receipt",
        contract_version=1, contract_schema_sha256="c" * 64,
        contract_runtime_input_required=True, contract_attempt_index=1,
        contract_route="primary", contract_route_attempt=1,
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id=MODEL_ID, route_fingerprint="route-v2",
    )
    observer.bind_model_request(protocol="openai-chat", request=payload)
    observer.before_http_dispatch(
        method="POST", url="https://ark.cn-beijing.volces.com/api/v3/responses",
        payload=payload, request_bytes=raw,
    )
    observer.before_http_post(); observer.before_network_request()
    observer.capture_provider_protocol_input(
        data=b'{"output":[{"text":"{}"}]}', status_code=200,
        content_type="application/json", encoding="utf-8", transport_complete=True,
    )
    observer.capture_contract_runtime_input(
        "{}", adapter_id="openai-chat", adapter_version=1,
        finish_reason="completed", transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    assert (tmp_path / "auto" / "attempt-01" / "10-request.json").is_file()
    assert (tmp_path / "auto" / "attempt-01" / "20-provider-response.json").is_file()
    assert (tmp_path / "auto" / "attempt-01" / "30-adapter-output.json").is_file()


def test_short_auto_recovery_capture_advances_ordinal_across_wrapper_recreation(
    tmp_path: Path,
) -> None:
    class Registry:
        @staticmethod
        def inspect_public_route(_provider_id, _model_id):
            return type("Public", (), {
                "destination": "https://ark.cn-beijing.volces.com/api/v3/responses",
            })()

    route = {
        "role": "review", "lane": "primary", "provider_id": PROVIDER_ID,
        "model_id": MODEL_ID, "route_fingerprint": "route-v1",
    }
    payload = {"model": "current-model", "messages": [{"role": "user", "content": "candidate"}]}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    def dispatch(observer):
        observer.bind_stage_context(
            stage_id="segment-05", contract_name="draft_segment_semantic_receipt",
            contract_version=1, contract_schema_sha256="c" * 64,
            contract_runtime_input_required=True, contract_attempt_index=1,
            contract_route="primary", contract_route_attempt=1,
        )
        observer.bind_route(**route)
        observer.bind_model_request(protocol="openai-chat", request=payload)
        observer.before_http_dispatch(
            method="POST", url="https://ark.cn-beijing.volces.com/api/v3/responses",
            payload=payload, request_bytes=raw,
        )
        observer.after_http_failure(failure_kind="transport_interrupted")

    first = ShortAutoRecoveryCaptureObserverV1(
        base_observer=None, registry=Registry(), store_root=tmp_path / "auto",
        context={"run_id": "run", "authorization_revision": "v3"},
    )
    dispatch(first)
    second = ShortAutoRecoveryCaptureObserverV1(
        base_observer=None, registry=Registry(), store_root=tmp_path / "auto",
        context={"run_id": "run", "authorization_revision": "v3"},
    )
    dispatch(second)
    assert (tmp_path / "auto" / "attempt-01" / "10-request.json").is_file()
    assert (tmp_path / "auto" / "attempt-02" / "10-request.json").is_file()


def test_http_provider_forwards_adapter_text_to_capture_observer(
    tmp_path: Path,
) -> None:
    observer = _observer(tmp_path)
    _bind_request(observer)
    observer.capture_provider_protocol_input(
        data=b'{"output":[{"type":"output_text","text":"{}"}]}',
        status_code=200, content_type="application/json", encoding="utf-8",
        transport_complete=True,
    )
    provider = HttpProvider(
        "https://ark.cn-beijing.volces.com/api/v3", "secret",
        attempt_observer=observer,
    )
    provider.capture_contract_runtime_input(
        "{}", adapter_id="openai-responses", adapter_version=1,
        finish_reason="completed", transport_complete=True,
    )
    assert (tmp_path / "capture" / "30-adapter-output.json").is_file()


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ({"field": None}, "null"),
        ({"field": []}, "empty"),
        ({"field": 7}, "type"),
    ],
)
def test_synthetic_invalid_fixtures_follow_formal_conversion_boundary(
    tmp_path: Path, fixture: dict, expected: str,
) -> None:
    observer = _observer(tmp_path)
    _bind_request(observer)
    text = json.dumps(fixture, ensure_ascii=False)
    observer.capture_provider_protocol_input(
        data=text.encode(), status_code=200, content_type="application/json",
        encoding="utf-8", transport_complete=True,
    )
    observer.capture_contract_runtime_input(
        text, adapter_id="openai-responses", adapter_version=1,
        finish_reason="stop", transport_complete=True,
    )
    gateway = GeneratedArtifactGateway()
    try:
        gateway.convert_object(
            text, contract_name="draft_atomic_semantic_receipt",
        )
    except ArtifactConversionError as exc:
        observer.capture_review_diagnostic(
            event="conversion-failure", error_type=type(exc).__name__,
            error_message=str(exc), fixture_class=expected,
        )
    else:
        observer.capture_review_diagnostic(
            event="validator-failure", fixture_class=expected,
            normalized_payload=fixture,
        )
    assert list((tmp_path / "capture" / "events").glob("*.json"))


def test_capture_is_single_dispatch_and_route_bound(tmp_path: Path) -> None:
    observer = _observer(tmp_path)
    raw = _bind_request(observer)
    with pytest.raises(ReviewDiagnosticCaptureScopeError, match="SECOND_DISPATCH"):
        observer.before_http_dispatch(
            method="POST", url="https://ark.cn-beijing.volces.com/api/v3/responses",
            payload={"model": "doubao-seed-character-260628"}, request_bytes=raw,
        )
    with pytest.raises(ReviewDiagnosticCaptureScopeError, match="ROUTE_MISMATCH"):
        observer.bind_route(
            role="review", lane="primary", provider_id=PROVIDER_ID,
            model_id="wrong-model", route_fingerprint="route-v1",
        )


def test_candidate_bytes_are_not_touched_by_capture(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.md"
    candidate.write_text("潮汐证词\n", encoding="utf-8")
    before = hashlib.sha256(candidate.read_bytes()).hexdigest()
    observer = _observer(tmp_path)
    _bind_request(observer)
    observer.capture_provider_protocol_input(
        data=b"{\"incomplete\":true", status_code=200,
        content_type="application/json", encoding="utf-8", transport_complete=False,
    )
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == before


def test_non_target_contract_is_rejected_before_route_or_provider_dispatch(
    tmp_path: Path,
) -> None:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
    )
    with pytest.raises(
        ReviewDiagnosticCaptureScopeError,
        match="NON_TARGET_CONTRACT",
    ):
        observer.bind_stage_context(
            stage_id="planning-01",
            contract_name="planning_event_realizations",
            contract_version=1,
            contract_schema_sha256="b" * 64,
        )
    assert not (tmp_path / "capture" / "01-route.json").exists()
    assert not (tmp_path / "capture" / "10-request.json").exists()


def test_preflight_route_is_deferred_until_formal_review_context(
    tmp_path: Path,
) -> None:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id=MODEL_ID, route_fingerprint="route-v1",
    )
    assert observer.bound_route is None
    observer.bind_stage_context(
        stage_id="segment-05-receipt-window-01",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="a" * 64,
        contract_runtime_input_required=True,
    )
    assert observer.bound_route is not None
    assert observer.bound_route["route_fingerprint"] == "route-v1"


def test_deferred_wrong_route_is_rejected_when_context_binds(
    tmp_path: Path,
) -> None:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id="wrong-model", route_fingerprint="route-v1",
    )
    with pytest.raises(ReviewDiagnosticCaptureScopeError, match="ROUTE_MISMATCH"):
        observer.bind_stage_context(
            stage_id="segment-05-receipt-window-01",
            contract_name="draft_segment_semantic_receipt",
            contract_version=1,
            contract_schema_sha256="a" * 64,
            contract_runtime_input_required=True,
        )


def test_preflight_fallback_lookup_does_not_replace_primary_binding(
    tmp_path: Path,
) -> None:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id=MODEL_ID, route_fingerprint="route-primary",
    )
    observer.bind_route(
        role="review", lane="configured_fallback", provider_id="other-provider",
        model_id="other-model", route_fingerprint="route-fallback",
    )
    observer.bind_stage_context(
        stage_id="segment-05-receipt-window-01",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="a" * 64,
        contract_runtime_input_required=True,
    )
    assert observer.bound_route["lane"] == "primary"


def test_scope_error_has_local_boundary_and_is_not_provider_protocol_failure(
    tmp_path: Path,
):
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com",
    )
    with pytest.raises(ReviewDiagnosticCaptureScopeError) as caught:
        observer.before_http_dispatch(
            method="POST",
            url="https://ark.cn-beijing.volces.com/api/v3/responses",
            payload={"model": "doubao-seed-character-260628"},
            request_bytes=b'{"model":"doubao-seed-character-260628"}',
        )
    failure = caught.value.reliability_failure
    assert failure.boundary == "review_diagnostic_capture.observer_scope"
    assert failure.failure_class.value == "unknown"
    incident = classify_production_failure(
        str(caught.value), workflow="short", stage="segment-05",
        failure=failure,
    )
    assert incident["incident_family"] != "parser.generated_artifact_shape"
    assert incident["failure_boundary"] == "review_diagnostic_capture.observer_scope"


@pytest.mark.asyncio
async def test_target_review_scope_reaches_transport_and_captures_response(
    tmp_path: Path,
) -> None:
    observer = _observer(tmp_path)
    payload = {
        "model": "doubao-seed-character-260628",
        "input": [{"role": "user", "content": "review candidate"}],
        "max_output_tokens": 1084,
        "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
        "stream": True,
    }

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "ark.cn-beijing.volces.com"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"output": [{"type": "output_text", "text": '{"ok":true}'}]},
            request=request,
        )

    observer.bind_model_request(protocol="openai-responses", request=payload)
    provider = HttpProvider(
        "https://ark.cn-beijing.volces.com/api/v3",
        "secret",
        attempt_observer=observer,
        injected_http_transport=httpx.MockTransport(transport),
    )
    result = await provider.post("responses", payload=payload, headers={})
    assert result["output"][0]["type"] == "output_text"
    assert observer.dispatch_count == 1
    assert observer.response_count == 1
    assert (tmp_path / "capture" / "10-request.json").is_file()
    assert (tmp_path / "capture" / "20-provider-response.json").is_file()

@pytest.mark.parametrize("fallback_lane", ["fallback", "configured_fallback"])
def test_pre_dispatch_primary_failure_allows_configured_fallback_capture(
    tmp_path: Path, fallback_lane: str,
) -> None:
    observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "capture",
        provider_id=PROVIDER_ID,
        model_id=MODEL_ID,
        hostname="ark.cn-beijing.volces.com,api.deepseek.com",
    )
    observer.bind_stage_context(
        stage_id="segment-05-receipt-window-01",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="a" * 64,
        contract_runtime_input_required=True,
    )
    observer.bind_route(
        role="review", lane="primary", provider_id=PROVIDER_ID,
        model_id=MODEL_ID, route_fingerprint="route-primary",
    )
    observer.bind_stage_context(
        stage_id="segment-05-receipt-window-01-fallback",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="a" * 64,
        contract_route="configured_fallback",
    )
    observer.bind_route(
        role="review", lane=fallback_lane, provider_id="fallback-provider",
        model_id="fallback-model", route_fingerprint="route-fallback",
    )
    payload = {"model": "fallback-model", "input": []}
    observer.before_http_dispatch(
        method="POST",
        url="https://api.deepseek.com/anthropic/messages",
        payload=payload,
        request_bytes=b'{"model":"fallback-model","input":[]}',
    )
    assert observer.bound_route["lane"] == fallback_lane
    assert observer.dispatch_count == 1
    assert (tmp_path / "capture" / "10-request.json").is_file()

@pytest.mark.parametrize("fallback_lane", ["fallback", "configured_fallback"])
@pytest.mark.parametrize("with_base_observer", [False, True])
def test_short_auto_recovery_capture_allows_pre_dispatch_fallback_child(
    tmp_path: Path, fallback_lane: str, with_base_observer: bool,
) -> None:
    class Registry:
        @staticmethod
        def inspect_public_route(_provider_id, _model_id):
            return type("Public", (), {
                "destination": "https://api.deepseek.com/anthropic",
            })()

    base_observer = ReviewDiagnosticCaptureObserverV1(
        store_root=tmp_path / "direct",
        provider_id=PROVIDER_ID, model_id=MODEL_ID,
        hostname="lingsuan.org,api.deepseek.com",
    ) if with_base_observer else None
    observer = ShortAutoRecoveryCaptureObserverV1(
        base_observer=base_observer,
        registry=Registry(),
        store_root=tmp_path / "auto",
        context={"run_id": "run", "authorization_revision": "v1"},
    )
    primary = {
        "role": "review", "lane": "primary",
        "provider_id": PROVIDER_ID, "model_id": MODEL_ID,
        "route_fingerprint": "route-primary",
    }
    fallback = {
        "role": "review", "lane": fallback_lane,
        "provider_id": "fallback-provider", "model_id": "fallback-model",
        "route_fingerprint": "route-fallback",
    }
    observer.bind_stage_context(
        stage_id="segment-05",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="b" * 64,
        contract_runtime_input_required=True,
        contract_attempt_index=1,
        contract_route="primary",
        contract_route_attempt=1,
    )
    observer.bind_route(**primary)
    observer.bind_stage_context(
        stage_id="segment-05-fallback",
        contract_name="draft_segment_semantic_receipt",
        contract_version=1,
        contract_schema_sha256="b" * 64,
        contract_runtime_input_required=True,
        contract_attempt_index=1,
        contract_route="configured_fallback",
        contract_route_attempt=1,
    )
    observer.bind_route(**fallback)
    assert (tmp_path / "auto" / "attempt-01").is_dir()
    assert (tmp_path / "auto" / "attempt-02").is_dir()
    assert not (tmp_path / "auto" / "attempt-02" / "10-request.json").exists()
