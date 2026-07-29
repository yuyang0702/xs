import hashlib
import json
import re
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def repair_artifact_hash(value: dict[str, Any] | str) -> str:
    if isinstance(value, dict):
        text = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
    elif isinstance(value, str):
        text = value
    else:
        raise TypeError("Repair artifact must be a JSON object or text")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RepairRunStore:
    CONTRACT = "repair-contract.json"
    GROUPS = "patch-groups.json"
    CHECKPOINT = "repair-checkpoint.json"
    CANDIDATE = "candidate.md"
    REPORT = "repair-report.json"

    def __init__(self, run_path: Path) -> None:
        self.output = run_path / "outputs"
        self.output.mkdir(parents=True, exist_ok=True)

    def write_contract(self, value: dict[str, Any]) -> None:
        self._write_json(self.CONTRACT, value)

    def write_groups(self, value: dict[str, Any]) -> None:
        self._write_json(self.GROUPS, value)

    def write_checkpoint(self, value: dict[str, Any]) -> None:
        self._write_json(self.CHECKPOINT, value)

    def write_candidate(self, text: str) -> None:
        atomic_write(self.output / self.CANDIDATE, text)

    def write_report(self, value: dict[str, Any]) -> None:
        self._write_json(self.REPORT, value)

    def load_resume_state(self, source_hash: str) -> dict[str, Any]:
        if not self._valid_hash(source_hash):
            raise ValueError("当前最佳稿校验信息无效，请重新确认需要处理的问题")

        checkpoint = self._read_json(self.CHECKPOINT)
        checkpoint_source_hash = checkpoint.get("source_hash")
        if not self._valid_hash(checkpoint_source_hash):
            raise ValueError("修复记录中的原稿校验信息无效，请重新开始本次返修")
        if checkpoint_source_hash != source_hash:
            raise ValueError("最佳稿已经变化，请重新确认需要处理的问题")

        contract_artifact_hash = checkpoint.get("contract_hash")
        if not self._valid_hash(contract_artifact_hash):
            raise ValueError("修复记录中的合同校验信息无效，请重新开始本次返修")

        groups_artifact_hash = checkpoint.get("groups_hash")
        if not self._valid_hash(groups_artifact_hash):
            raise ValueError("修复记录中的分组校验信息无效，请重新开始本次返修")

        candidate_hash = checkpoint.get("candidate_hash")
        if not self._valid_hash(candidate_hash):
            raise ValueError("修复记录中的候选稿校验信息无效，请重新开始本次返修")

        contract = self._read_json(self.CONTRACT)
        groups = self._read_json(self.GROUPS)
        candidate = self._read_candidate()

        contract_hash = contract.get("manuscript_hash")
        if not self._valid_hash(contract_hash):
            raise ValueError("修复合同缺少有效的原稿校验信息，请重新开始本次返修")
        if contract_hash != checkpoint_source_hash:
            raise ValueError("修复合同与最佳稿不一致，请重新开始本次返修")

        actual_candidate_hash = repair_artifact_hash(candidate)
        if actual_candidate_hash != candidate_hash:
            raise ValueError("候选稿与修复记录不一致，请重新开始本次返修")

        group_ids = self._validate_groups(groups)
        self._validate_completed_groups(checkpoint.get("completed_groups"), group_ids)
        if repair_artifact_hash(contract) != contract_artifact_hash:
            raise ValueError("修复合同与检查点不一致，请重新开始本次返修")
        if repair_artifact_hash(groups) != groups_artifact_hash:
            raise ValueError("修复分组与检查点不一致，请重新开始本次返修")

        state = dict(checkpoint)
        state.update({
            "contract": contract,
            "groups": groups,
            "candidate": candidate,
        })
        report = self._read_json(self.REPORT, required=False)
        if report is not None:
            state["report"] = report
        return state

    def _write_json(self, name: str, value: dict[str, Any]) -> None:
        atomic_write(
            self.output / name,
            json.dumps(value, ensure_ascii=False, indent=2),
        )

    def _read_json(self, name: str, *, required: bool = True) -> dict[str, Any] | None:
        try:
            text = (self.output / name).read_text(encoding="utf-8")
        except FileNotFoundError:
            if not required:
                return None
            raise ValueError("修复记录不完整，请重新开始本次返修") from None
        except (OSError, UnicodeError):
            raise ValueError("修复记录已损坏，请重新开始本次返修") from None
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("修复记录已损坏，请重新开始本次返修") from None
        if not isinstance(value, dict):
            raise ValueError("修复记录已损坏，请重新开始本次返修")
        return value

    def _read_candidate(self) -> str:
        try:
            return (self.output / self.CANDIDATE).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ValueError("修复记录不完整，请重新开始本次返修") from None
        except (OSError, UnicodeError):
            raise ValueError("修复记录已损坏，请重新开始本次返修") from None

    @staticmethod
    def _valid_hash(value: object) -> bool:
        return isinstance(value, str) and bool(_SHA256.fullmatch(value))

    @staticmethod
    def _validate_groups(groups: dict[str, Any]) -> set[str]:
        values = groups.get("groups")
        if not isinstance(values, list):
            raise ValueError("修复分组记录无效，请重新开始本次返修")
        group_ids: list[str] = []
        for item in values:
            group_id = item.get("group_id") if isinstance(item, dict) else None
            if not isinstance(group_id, str) or not group_id.strip() or group_id != group_id.strip():
                raise ValueError("修复分组记录无效，请重新开始本次返修")
            group_ids.append(group_id)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("修复分组记录无效，请重新开始本次返修")
        return set(group_ids)

    @staticmethod
    def _validate_completed_groups(completed: object, group_ids: set[str]) -> None:
        if not isinstance(completed, list):
            raise ValueError("修复进度记录无效，请重新开始本次返修")
        if any(not isinstance(group_id, str) or not group_id for group_id in completed):
            raise ValueError("修复进度记录无效，请重新开始本次返修")
        if len(completed) != len(set(completed)) or not set(completed).issubset(group_ids):
            raise ValueError("修复进度记录无效，请重新开始本次返修")
