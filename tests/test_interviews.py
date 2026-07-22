from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.interviews import WizardInterviewService


SCHEMA = {"steps": [{"title": "故事核心", "fields": [
    {"id": "genre", "label": "题材", "type": "text", "required": True, "lockable": True},
    {"id": "protagonist.arc", "label": "人物弧光终点", "type": "textarea", "required": False, "lockable": True},
]}]}


class FakeGateway:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({"role": role, "system": system, "user": user})
        return SimpleNamespace(text=self.text, receipt={"model_name": "planner"})


class SequenceGateway(FakeGateway):
    def __init__(self, texts):
        super().__init__(texts[0])
        self.texts = iter(texts)

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({"role": role, "system": system, "user": user})
        return SimpleNamespace(text=next(self.texts), receipt={"model_name": "planner"})


class ReasoningBudgetGateway(FakeGateway):
    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({
            "role": role, "system": system, "user": user,
            "max_output_tokens": max_output_tokens,
        })
        text = self.text if (max_output_tokens or 0) >= 4096 else ""
        return SimpleNamespace(text=text, receipt={"model_name": "reasoning-planner"})


def make_service(tmp_path, output, *, locked=False):
    db = Database(tmp_path / "app.db")
    db.migrate()
    answers = {"genre": {"value": "悬疑", "policy": "locked" if locked else "suggestible"}}
    db.save_wizard("wizard", "draft", "long", SCHEMA, answers)
    gateway = FakeGateway(output)
    return db, gateway, WizardInterviewService(db, gateway)


@pytest.mark.asyncio
async def test_interview_turn_persists_history_and_filters_unknown_fields(tmp_path) -> None:
    db, gateway, service = make_service(tmp_path, '''```json
{"message":"主角最终愿意付出什么代价？","suggestions":[
  {"field_id":"protagonist.arc","value":"从逃避责任到主动承担代价","reason":"与成长线一致"},
  {"field_id":"filesystem_path","value":"../x","reason":"无效字段"}
]}
```''')

    result = await service.turn("wizard", "主角一开始很胆小")

    assert result["role"] == "assistant"
    assert [item["role"] for item in service.history("wizard")] == ["user", "assistant"]
    assert [item["field_id"] for item in result["suggestions"]] == ["protagonist.arc"]
    assert gateway.calls[0]["role"] == "planning"
    assert "主角一开始很胆小" in gateway.calls[0]["user"]


@pytest.mark.asyncio
async def test_interview_never_proposes_or_overwrites_locked_answer(tmp_path) -> None:
    db, _, service = make_service(tmp_path, '''{
      "message":"继续讨论人物变化。",
      "suggestions":[{"field_id":"genre","value":"科幻","reason":"模型建议"}]
    }''', locked=True)

    assistant = await service.turn("wizard", "换成科幻吧")
    applied = service.apply("wizard", assistant["id"], ["genre"])

    assert assistant["suggestions"] == []
    assert applied["applied_fields"] == []
    assert db.get_wizard("wizard")["answers"]["genre"] == {"value": "悬疑", "policy": "locked"}


@pytest.mark.asyncio
async def test_interview_applies_only_selected_suggestions_as_suggestible(tmp_path) -> None:
    db, _, service = make_service(tmp_path, '''{
      "message":"我整理了两个方向。",
      "suggestions":[
        {"field_id":"genre","value":"社会派悬疑","reason":"题材更明确"},
        {"field_id":"protagonist.arc","value":"学会信任他人","reason":"回应内在缺陷"}
      ]
    }''')
    assistant = await service.turn("wizard", "帮我整理")

    result = service.apply("wizard", assistant["id"], ["protagonist.arc"])

    assert result["applied_fields"] == ["protagonist.arc"]
    answers = db.get_wizard("wizard")["answers"]
    assert answers["genre"]["value"] == "悬疑"
    assert answers["protagonist.arc"] == {"value": "学会信任他人", "policy": "suggestible"}
    assert db.get_interview_message(assistant["id"])["suggestion_status"] == "applied"


@pytest.mark.asyncio
async def test_interview_rejects_invalid_model_output(tmp_path) -> None:
    _, _, service = make_service(tmp_path, "not json")

    with pytest.raises(ValueError, match="valid JSON"):
        await service.turn("wizard", "继续")


def test_interview_extracts_json_surrounded_by_model_commentary() -> None:
    output = WizardInterviewService._parse_output(
        '下面是整理结果：\n{"message":"继续说说主角。","suggestions":[]}\n以上。'
    )

    assert output.message == "继续说说主角。"


@pytest.mark.asyncio
async def test_interview_repairs_non_json_model_response_once(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", SCHEMA, {})
    gateway = SequenceGateway([
        "我建议先明确主角的内在缺陷。",
        '{"message":"主角最害怕承认什么？","suggestions":[]}',
    ])
    service = WizardInterviewService(db, gateway)

    result = await service.turn("wizard", "我暂时只有一个模糊想法")

    assert result["content"] == "主角最害怕承认什么？"
    assert len(gateway.calls) == 2
    assert "整理为指定 JSON" in gateway.calls[1]["system"]


@pytest.mark.asyncio
async def test_interview_allows_reasoning_model_enough_output_budget(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", SCHEMA, {})
    gateway = ReasoningBudgetGateway(
        '{"message":"请继续描述女主的性格。","suggestions":[]}'
    )
    service = WizardInterviewService(db, gateway)

    result = await service.turn("wizard", "我选择第二种")

    assert result["content"] == "请继续描述女主的性格。"
    assert gateway.calls[0]["max_output_tokens"] >= 4096
