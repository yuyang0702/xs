import hashlib
import json

import pytest

from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash


SOURCE = "原始最佳稿"
CANDIDATE = "候选稿第一段。\n\n候选稿第二段。\n"
SOURCE_HASH = hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()
CANDIDATE_HASH = hashlib.sha256(CANDIDATE.encode("utf-8")).hexdigest()


def test_repair_artifact_hash_uses_canonical_json_and_exact_text() -> None:
    assert repair_artifact_hash({"b": 2, "a": "候选"}) == (
        "f14bfa8dedde8a75b04cf6a9b10b0b5ea8297edf50b96e5b4602ec4a3d852cdd"
    )
    assert repair_artifact_hash({"a": "候选", "b": 2}) == (
        "f14bfa8dedde8a75b04cf6a9b10b0b5ea8297edf50b96e5b4602ec4a3d852cdd"
    )
    assert repair_artifact_hash("候选稿\n") == (
        "1ed162a6c264b5093f90b0a9cf61b88ac42962c2da3c84967cf827f36b63c01b"
    )


def _write_complete_state(store: RepairRunStore, *, report: bool = True) -> None:
    contract = {"manuscript_hash": SOURCE_HASH, "说明": "只修改指定位置"}
    groups = {"groups": [
        {"group_id": "group-1", "说明": "修复开头"},
        {"group_id": "group-2", "说明": "核对结尾"},
    ]}
    store.write_contract(contract)
    store.write_groups(groups)
    store.write_candidate(CANDIDATE)
    store.write_checkpoint({
        "source_hash": SOURCE_HASH,
        "contract_hash": repair_artifact_hash(contract),
        "groups_hash": repair_artifact_hash(groups),
        "candidate_hash": CANDIDATE_HASH,
        "completed_groups": ["group-1"],
        "stage": "applying",
    })
    if report:
        store.write_report({"status": "waiting_confirmation", "说明": "等待确认"})


def test_repair_store_writes_exact_named_artifacts_atomically(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")

    _write_complete_state(store)

    assert {path.name for path in (tmp_path / "run" / "outputs").iterdir()} == {
        "repair-contract.json",
        "patch-groups.json",
        "repair-checkpoint.json",
        "candidate.md",
        "repair-report.json",
    }


def test_json_keeps_chinese_and_candidate_is_written_exactly(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")

    store.write_contract({"manuscript_hash": SOURCE_HASH, "说明": "保留中文"})
    store.write_candidate("正文末尾不补换行")

    contract_text = (store.output / "repair-contract.json").read_text(encoding="utf-8")
    assert '"说明": "保留中文"' in contract_text
    assert "\\u4fdd\\u7559" not in contract_text
    assert (store.output / "candidate.md").read_text(encoding="utf-8") == "正文末尾不补换行"


def test_resume_returns_checkpoint_fields_and_read_only_artifacts(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)

    state = store.load_resume_state(SOURCE_HASH)

    assert state["stage"] == "applying"
    assert state["completed_groups"] == ["group-1"]
    assert state["contract"]["说明"] == "只修改指定位置"
    assert state["groups"]["groups"][1]["group_id"] == "group-2"
    assert state["candidate"] == CANDIDATE
    assert state["report"]["status"] == "waiting_confirmation"


def test_resume_allows_report_to_be_absent_after_early_interruption(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store, report=False)

    state = store.load_resume_state(SOURCE_HASH)

    assert "report" not in state


def test_write_checkpoint_allows_incomplete_stage_state(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")

    store.write_checkpoint({"stage": "contract_written"})

    assert json.loads((store.output / "repair-checkpoint.json").read_text(encoding="utf-8")) == {
        "stage": "contract_written",
    }


def test_resume_rejects_changed_protected_best_hash_before_missing_artifacts(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    store.write_checkpoint({
        "source_hash": SOURCE_HASH,
        "candidate_hash": "c" * 64,
        "completed_groups": [],
    })

    with pytest.raises(ValueError, match="最佳稿已经变化"):
        store.load_resume_state("b" * 64)


@pytest.mark.parametrize("checkpoint", [
    {"candidate_hash": CANDIDATE_HASH, "completed_groups": []},
    {"source_hash": "短哈希", "candidate_hash": CANDIDATE_HASH, "completed_groups": []},
    {"source_hash": "G" * 64, "candidate_hash": CANDIDATE_HASH, "completed_groups": []},
])
def test_resume_rejects_missing_or_invalid_source_hash(tmp_path, checkpoint) -> None:
    store = RepairRunStore(tmp_path / "run")
    store.write_checkpoint(checkpoint)

    with pytest.raises(ValueError, match="原稿校验信息无效"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("candidate_hash", [None, "短哈希", "Z" * 64])
def test_resume_rejects_missing_or_invalid_candidate_hash(tmp_path, candidate_hash) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    checkpoint = json.loads(
        (store.output / "repair-checkpoint.json").read_text(encoding="utf-8"),
    )
    if candidate_hash is not None:
        checkpoint["candidate_hash"] = candidate_hash
    else:
        checkpoint.pop("candidate_hash")
    store.write_checkpoint(checkpoint)

    with pytest.raises(ValueError, match="候选稿校验信息无效"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("contract_hash", None, "合同校验信息无效"),
    ("contract_hash", "短哈希", "合同校验信息无效"),
    ("contract_hash", "G" * 64, "合同校验信息无效"),
    ("groups_hash", None, "分组校验信息无效"),
    ("groups_hash", "短哈希", "分组校验信息无效"),
    ("groups_hash", "G" * 64, "分组校验信息无效"),
])
def test_resume_rejects_missing_or_invalid_contract_and_groups_hash(
    tmp_path, field, value, message,
) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    checkpoint = json.loads(
        (store.output / "repair-checkpoint.json").read_text(encoding="utf-8"),
    )
    if value is None:
        checkpoint.pop(field)
    else:
        checkpoint[field] = value
    store.write_checkpoint(checkpoint)

    with pytest.raises(ValueError, match=message):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize(("artifact", "message"), [
    ("contract", "修复合同与检查点不一致"),
    ("groups", "修复分组与检查点不一致"),
])
def test_resume_rejects_contract_or_groups_changed_after_checkpoint(
    tmp_path, artifact, message,
) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    if artifact == "contract":
        store.write_contract({"manuscript_hash": SOURCE_HASH, "说明": "合同被静默改写"})
    else:
        store.write_groups({"groups": [
            {"group_id": "group-1", "说明": "分组内容被静默改写"},
            {"group_id": "group-2", "说明": "核对结尾"},
        ]})

    with pytest.raises(ValueError, match=message):
        store.load_resume_state(SOURCE_HASH)


def test_resume_rejects_invalid_requested_source_hash(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)

    with pytest.raises(ValueError, match="当前最佳稿校验信息无效"):
        store.load_resume_state("invalid")


def test_resume_rejects_contract_checkpoint_hash_mismatch(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    store.write_contract({"manuscript_hash": "d" * 64})

    with pytest.raises(ValueError, match="修复合同与最佳稿不一致"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("manuscript_hash", [None, "短哈希", "Q" * 64])
def test_resume_rejects_missing_or_invalid_contract_hash(tmp_path, manuscript_hash) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    contract = {"说明": "合同仍在编写"}
    if manuscript_hash is not None:
        contract["manuscript_hash"] = manuscript_hash
    store.write_contract(contract)

    with pytest.raises(ValueError, match="修复合同缺少有效的原稿校验信息"):
        store.load_resume_state(SOURCE_HASH)


def test_resume_rejects_candidate_hash_mismatch(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    store.write_candidate("被意外改动的候选稿")

    with pytest.raises(ValueError, match="候选稿与修复记录不一致"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("groups_value", [None, {}, {"groups": "group-1"}])
def test_resume_rejects_missing_or_invalid_groups_collection(tmp_path, groups_value) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    store.write_groups(groups_value or {})

    with pytest.raises(ValueError, match="修复分组记录无效"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("groups", [
    [{"group_id": "group-1"}, {"group_id": "group-1"}],
    [{"group_id": ""}],
    [{"group_id": "   "}],
    [{"group_id": 7}],
    [{}],
])
def test_resume_rejects_duplicate_or_invalid_group_ids(tmp_path, groups) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    store.write_groups({"groups": groups})

    with pytest.raises(ValueError, match="修复分组记录无效"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("completed_groups", [
    ["group-1", "group-1"],
    ["unknown-group"],
    "group-1",
    [7],
])
def test_resume_rejects_duplicate_unknown_or_invalid_completed_groups(
    tmp_path, completed_groups,
) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    checkpoint = json.loads(
        (store.output / "repair-checkpoint.json").read_text(encoding="utf-8"),
    )
    checkpoint["completed_groups"] = completed_groups
    store.write_checkpoint(checkpoint)

    with pytest.raises(ValueError, match="修复进度记录无效"):
        store.load_resume_state(SOURCE_HASH)


@pytest.mark.parametrize("missing_name", [
    "repair-contract.json",
    "patch-groups.json",
    "repair-checkpoint.json",
    "candidate.md",
])
def test_resume_reports_missing_required_artifact_without_leaking_path(
    tmp_path, missing_name,
) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    (store.output / missing_name).unlink()

    with pytest.raises(ValueError) as raised:
        store.load_resume_state(SOURCE_HASH)

    assert "修复记录不完整" in str(raised.value)
    assert missing_name not in str(raised.value)
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.parametrize("name", [
    "repair-contract.json",
    "patch-groups.json",
    "repair-checkpoint.json",
    "repair-report.json",
])
@pytest.mark.parametrize("content", ['{"未完成":', "[]"])
def test_resume_reports_damaged_or_non_object_json_in_chinese(
    tmp_path, name, content,
) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    (store.output / name).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError) as raised:
        store.load_resume_state(SOURCE_HASH)

    message = str(raised.value)
    assert "修复记录已损坏" in message
    assert name not in message
    assert "JSONDecodeError" not in message
    assert "line " not in message


def test_interruption_after_new_candidate_before_checkpoint_is_not_resumable(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    _write_complete_state(store)
    store.write_candidate("这是已经写入、但尚未提交检查点的新候选稿")

    with pytest.raises(ValueError, match="候选稿与修复记录不一致"):
        store.load_resume_state(SOURCE_HASH)


def test_store_never_changes_authoritative_project_files(tmp_path) -> None:
    run_path = tmp_path / "project" / "runs" / "run-1"
    best = tmp_path / "project" / "manuscript" / "best-candidate.md"
    formal = tmp_path / "project" / "manuscript" / "formal.md"
    story_state = tmp_path / "project" / "memory" / "story-state.json"
    for path, content in (
        (best, "原最佳稿"),
        (formal, "原正式稿"),
        (story_state, '{"revision": 9}'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    before = {path: path.read_bytes() for path in (best, formal, story_state)}
    store = RepairRunStore(run_path)

    _write_complete_state(store)
    store.load_resume_state(SOURCE_HASH)

    assert {path: path.read_bytes() for path in before} == before
