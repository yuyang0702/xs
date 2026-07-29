import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database, WIZARD_MUTATION_LOCK
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


class DisconnectOnceGateway(FakeGateway):
    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({"role": role, "system": system, "user": user})
        if len(self.calls) == 1:
            raise ConnectionError("client disconnected")
        return SimpleNamespace(text=self.text, receipt={"model_name": "planner"})


class PausedGateway(FakeGateway):
    def __init__(self, texts, pause_call=1):
        super().__init__(texts[0])
        self.texts = texts
        self.pause_call = pause_call
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({"role": role, "system": system, "user": user})
        if len(self.calls) == self.pause_call:
            self.started.set()
            await self.release.wait()
        return SimpleNamespace(
            text=self.texts[len(self.calls) - 1],
            receipt={"model_name": "planner"},
        )


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


@pytest.mark.asyncio
async def test_interview_retry_does_not_duplicate_orphaned_user_message(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", SCHEMA, {})
    gateway = DisconnectOnceGateway('{"message":"Continue.","suggestions":[]}')
    service = WizardInterviewService(db, gateway)

    with pytest.raises(ConnectionError):
        await service.turn("wizard", "A long outline")
    result = await service.turn("wizard", "A long outline")

    assert result["content"] == "Continue."
    assert [item["role"] for item in service.history("wizard")] == ["user", "assistant"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_outputs", "pause_call"),
    [
        (['{"message":"继续。","suggestions":[]}'], 1),
        (["not json", '{"message":"继续。","suggestions":[]}'], 2),
    ],
)
async def test_interview_turn_does_not_save_model_reply_after_wizard_is_deleted(
    tmp_path, model_outputs, pause_call,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", SCHEMA, {})
    gateway = PausedGateway(model_outputs, pause_call)
    service = WizardInterviewService(db, gateway)

    turn = asyncio.create_task(service.turn("wizard", "先说说主角"))
    await asyncio.wait_for(gateway.started.wait(), timeout=5)
    assert await asyncio.wait_for(asyncio.to_thread(db.delete_wizard, "wizard"), timeout=5)
    gateway.release.set()

    with pytest.raises(LookupError, match="Wizard not found"):
        await turn
    assert db.get_wizard("wizard") is None
    assert db.list_interview_messages("wizard") == []


def test_interview_apply_waits_for_delete_and_does_not_restore_wizard(
    tmp_path, monkeypatch,
) -> None:
    db, _, service = make_service(
        tmp_path,
        '{"message":"继续。","suggestions":[]}',
    )
    db.save_interview_message(
        "assistant", "wizard", "assistant", "可以改成社会派悬疑。", [
            {"field_id": "genre", "value": "社会派悬疑", "reason": "方向更明确"},
        ],
    )
    delete_paused = Event()
    release_delete = Event()
    apply_attempted = Event()
    apply_finished = Event()
    original_delete = db.delete_wizard

    def paused_delete(wizard_id):
        with WIZARD_MUTATION_LOCK:
            delete_paused.set()
            assert release_delete.wait(5)
            return original_delete(wizard_id)

    def apply():
        apply_attempted.set()
        try:
            return service.apply("wizard", "assistant", ["genre"])
        finally:
            apply_finished.set()

    monkeypatch.setattr(db, "delete_wizard", paused_delete)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleted = executor.submit(db.delete_wizard, "wizard")
        assert delete_paused.wait(5)
        applied = executor.submit(apply)
        assert apply_attempted.wait(5)
        assert not apply_finished.wait(0.1)
        release_delete.set()
        assert deleted.result(timeout=5) is True
        with pytest.raises(LookupError, match="Wizard not found"):
            applied.result(timeout=5)

    assert apply_finished.is_set()
    assert db.get_wizard("wizard") is None
    assert db.get_interview_message("assistant") is None
