import json
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from novel_flywheel.db import Database


class InterviewSuggestion(BaseModel):
    field_id: str = Field(min_length=1)
    value: Any
    reason: str = ""


class InterviewModelOutput(BaseModel):
    message: str = Field(min_length=1)
    suggestions: list[InterviewSuggestion] = Field(default_factory=list)


class WizardInterviewService:
    SYSTEM = """你是小说开书访谈编辑。你的工作是帮助作者澄清当前建书向导中的设定。
每轮只推进一个最重要的问题；必要时先用通俗语言解释专业术语，再给2到3个可选方向。
不得改变 policy=locked 的答案，不得发明表单外的字段，不得请求文件或工具。
只输出 JSON：{"message":"给作者的回复和下一问","suggestions":[{"field_id":"字段ID","value":"建议值","reason":"理由"}]}。
只有作者已经明确表达或高度确认的内容才放入 suggestions；尚待选择的方向只写在 message 中。"""

    def __init__(self, db: Database, gateway) -> None:
        self.db = db
        self.gateway = gateway

    def history(self, wizard_id: str) -> list[dict]:
        self._wizard(wizard_id)
        return self.db.list_interview_messages(wizard_id)

    async def turn(self, wizard_id: str, user_message: str | None = None) -> dict:
        wizard = self._editable_wizard(wizard_id)
        message = (user_message or "").strip()
        if len(message) > 4000:
            raise ValueError("Interview message is too long")
        if message:
            self.db.save_interview_message(uuid.uuid4().hex, wizard_id, "user", message, [])
        elif self.db.list_interview_messages(wizard_id):
            raise ValueError("Interview message is required")

        try:
            result = await self.gateway.complete(
                "planning", self.SYSTEM, self._context(wizard_id, wizard), max_output_tokens=1200,
            )
        except LookupError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            output = self._parse_output(result.text)
        except ValueError:
            repaired = await self.gateway.complete(
                "planning",
                "把给定的模型回复整理为指定 JSON，不增加新剧情。只输出 "
                '{"message":"回复","suggestions":[{"field_id":"字段ID","value":"值","reason":"理由"}]}。',
                json.dumps({
                    "allowed_field_ids": list(self._field_map(wizard)),
                    "model_response": result.text[:12000],
                }, ensure_ascii=False),
                max_output_tokens=1200,
            )
            output = self._parse_output(repaired.text)
        suggestions = self._valid_suggestions(wizard, output.suggestions)
        message_id = uuid.uuid4().hex
        self.db.save_interview_message(
            message_id, wizard_id, "assistant", output.message,
            [item.model_dump() for item in suggestions],
        )
        return self.db.get_interview_message(message_id)

    def apply(self, wizard_id: str, message_id: str, field_ids: list[str]) -> dict:
        wizard = self._editable_wizard(wizard_id)
        message = self.db.get_interview_message(message_id)
        if message is None or message["wizard_id"] != wizard_id or message["role"] != "assistant":
            raise LookupError("Interview message not found")
        selected = set(field_ids)
        fields = self._field_map(wizard)
        answers = dict(wizard["answers"])
        applied = []
        for suggestion in message["suggestions"]:
            field_id = suggestion["field_id"]
            if (field_id not in selected or field_id not in fields
                    or answers.get(field_id, {}).get("policy") == "locked"):
                continue
            answers[field_id] = {"value": suggestion["value"], "policy": "suggestible"}
            applied.append(field_id)
        if applied:
            self.db.save_wizard(
                wizard_id, wizard["status"], wizard["mode"], wizard["schema"], answers,
                wizard.get("project_id"),
            )
        self.db.update_interview_message_status(message_id, "applied" if applied else "dismissed")
        return {"wizard": self.db.get_wizard(wizard_id), "applied_fields": applied}

    def _wizard(self, wizard_id: str) -> dict:
        wizard = self.db.get_wizard(wizard_id)
        if wizard is None:
            raise LookupError("Wizard not found")
        return wizard

    def _editable_wizard(self, wizard_id: str) -> dict:
        wizard = self._wizard(wizard_id)
        if wizard["status"] == "completed":
            raise ValueError("Completed wizard cannot be interviewed")
        return wizard

    def _context(self, wizard_id: str, wizard: dict) -> str:
        fields = [{"id": field["id"], "label": field["label"], "required": field.get("required", False)}
                  for step in wizard["schema"]["steps"] for field in step["fields"]]
        history = [{"role": item["role"], "content": item["content"]}
                   for item in self.db.list_interview_messages(wizard_id)[-20:]]
        return json.dumps({
            "mode": wizard["mode"], "fields": fields,
            "answers": wizard["answers"], "conversation": history,
        }, ensure_ascii=False)

    @staticmethod
    def _parse_output(text: str) -> InterviewModelOutput:
        candidate = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate,
                              flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        decoder = json.JSONDecoder()
        errors = []
        for start in [0, *(match.start() for match in re.finditer(r"\{", candidate))]:
            try:
                value, _ = decoder.raw_decode(candidate, start)
                return InterviewModelOutput.model_validate(value)
            except (json.JSONDecodeError, ValidationError) as exc:
                errors.append(exc)
        raise ValueError("Planning model did not return valid JSON") from errors[-1]

    def _valid_suggestions(self, wizard: dict,
                           suggestions: list[InterviewSuggestion]) -> list[InterviewSuggestion]:
        fields = self._field_map(wizard)
        seen = set()
        valid = []
        for item in suggestions:
            if (item.field_id not in fields or item.field_id in seen
                    or item.value in (None, "")
                    or wizard["answers"].get(item.field_id, {}).get("policy") == "locked"):
                continue
            seen.add(item.field_id)
            valid.append(item)
        return valid

    @staticmethod
    def _field_map(wizard: dict) -> dict[str, dict]:
        return {field["id"]: field for step in wizard["schema"]["steps"] for field in step["fields"]}
