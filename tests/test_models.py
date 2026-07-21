import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse
from novel_flywheel.models import ModelGateway
from novel_flywheel.providers.registry import ResolvedModel


class FakeAdapter:
    async def complete(self, request):
        assert request.model == "actual-model"
        return ModelResponse(text="result", input_tokens=10, output_tokens=20, raw_request_id="req-1")


class FakeRegistry:
    def resolve(self, provider_id, model_id):
        assert (provider_id, model_id) == ("provider", "model")
        return ResolvedModel(provider_id, model_id, "actual-model", FakeAdapter())


@pytest.mark.asyncio
async def test_gateway_routes_role_and_returns_redacted_receipt(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("draft", "provider", "model", None, None)
    result = await ModelGateway(db, FakeRegistry()).complete("draft", "system rules", "write")
    assert result.text == "result"
    assert result.receipt == {
        "role": "draft", "provider_id": "provider", "model_id": "model",
        "model_name": "actual-model", "input_tokens": 10, "output_tokens": 20,
        "request_id": "req-1",
    }


@pytest.mark.asyncio
async def test_gateway_rejects_unbound_role_before_model_call(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    with pytest.raises(LookupError, match="review"):
        await ModelGateway(db, FakeRegistry()).complete("review", "rules", "review")
