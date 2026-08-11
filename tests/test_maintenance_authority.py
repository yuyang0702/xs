from __future__ import annotations

import hashlib

import pytest

from novel_flywheel.maintenance_authority import (
    MAINTENANCE_WINDOW_RECEIPT_VERSION,
    adapt_maintenance_window_payload,
    bisect_maintenance_window_contract,
    build_maintenance_reduction,
    build_maintenance_window_bundle,
    build_maintenance_window_contracts,
    canonical_sha256,
    receipt_to_maintenance_candidate,
    validate_maintenance_reduction,
    validate_maintenance_window_bundle,
    validate_maintenance_window_coverage,
)


def _payload(quote: str) -> dict:
    return {
        "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
        "facts": [{
            "key": "hero.choice", "value": quote, "evidence": quote,
        }],
        "state_deltas": [{
            "character": "hero", "field": "trust", "value": "earned",
            "evidence": quote,
        }],
        "state_transitions": [],
        "world_rules": [],
        "timeline": [],
    }


@pytest.mark.parametrize(
    "genre_text",
    [
        "侦探在钟楼前公开唯一证词。",
        "她在雨夜选择留下，并把戒指还给他。",
        "法师以名字封住裂隙，代价是失去记忆。",
        "工程师关闭反应堆，把航行日志交给舰长。",
        "父亲在早餐桌前承认自己伪造了收据。",
        "剑修收起本命剑，承认此战已经结束。",
    ],
)
def test_window_receipt_uses_exact_evidence_without_genre_rules(
    genre_text: str,
) -> None:
    manuscript = "序幕保持不变。\n\n" + genre_text + "\n\n结尾状态已经确认。"
    state_sha = canonical_sha256({"confirmed_facts": []})
    contract = build_maintenance_window_contracts(
        manuscript, entry_state_sha256=state_sha, target_characters=400,
    )[0]

    envelope = adapt_maintenance_window_payload(
        _payload(genre_text), contract=contract, manuscript=manuscript,
    )
    candidate = receipt_to_maintenance_candidate(envelope)

    assert candidate["facts"] == [{"key": "hero.choice", "value": genre_text}]
    assert candidate["state"] == {"hero": {"trust": "earned"}}
    evidence = envelope.receipt.facts[0].evidence
    assert manuscript[evidence.start:evidence.end] == genre_text
    assert evidence.sha256 == hashlib.sha256(genre_text.encode("utf-8")).hexdigest()
    assert envelope.adapter_audit


def test_window_coverage_and_recursive_bundle_are_hash_bound() -> None:
    manuscript = "\n\n".join(
        f"第{index}段发生一个不可省略的事件。" + "证据" * 90
        for index in range(1, 9)
    )
    state_sha = canonical_sha256({"confirmed_facts": []})
    contracts = build_maintenance_window_contracts(
        manuscript,
        entry_state_sha256=state_sha,
        target_characters=500,
        overlap_characters=80,
    )
    validate_maintenance_window_coverage(contracts, manuscript)
    parent = contracts[0]
    left, right = bisect_maintenance_window_contract(
        parent, manuscript, entry_state_sha256=state_sha,
    )
    left_quote = manuscript[left.start:left.end].split("证据", 1)[0] + "证据"
    right_text = manuscript[right.start:right.end]
    right_quote = right_text[: min(12, len(right_text))]
    left_envelope = adapt_maintenance_window_payload(
        _payload(left_quote), contract=left, manuscript=manuscript,
    )
    right_envelope = adapt_maintenance_window_payload(
        _payload(right_quote), contract=right, manuscript=manuscript,
    )
    bundle = build_maintenance_window_bundle(
        parent_contract=parent,
        source_state_sha256=state_sha,
        envelopes=[right_envelope, left_envelope],
        canon={"facts": [], "state": {}},
        confirmed_facts=[],
        manuscript=manuscript,
    )

    validated = validate_maintenance_window_bundle(
        bundle.model_dump(mode="json", by_alias=True),
        parent_contract=parent,
        manuscript=manuscript,
        source_state_sha256=state_sha,
    )
    assert [item.contract.start for item in validated.envelopes] == sorted(
        item.contract.start for item in validated.envelopes
    )
    tampered = bundle.model_dump(mode="json", by_alias=True)
    tampered["canon"]["facts"] = ["not-bound"]
    with pytest.raises(ValueError, match="bundle hash"):
        validate_maintenance_window_bundle(
            tampered,
            parent_contract=parent,
            manuscript=manuscript,
            source_state_sha256=state_sha,
        )


def test_reduction_rejects_coverage_and_authority_tampering() -> None:
    manuscript = "开端事实只出现一次。\n\n中段事实只出现一次。\n\n结局事实只出现一次。"
    state_sha = canonical_sha256({"confirmed_facts": []})
    contracts = build_maintenance_window_contracts(
        manuscript, entry_state_sha256=state_sha, target_characters=400,
    )
    envelope = adapt_maintenance_window_payload(
        _payload("中段事实只出现一次。"),
        contract=contracts[0], manuscript=manuscript,
    )
    reduction = build_maintenance_reduction(
        manuscript=manuscript,
        source_state_sha256=state_sha,
        envelopes=[envelope],
        canon={"facts": [{"key": "hero.choice", "value": "中段事实只出现一次。"}]},
        confirmed_facts=[{
            "key": "hero.choice", "value": "中段事实只出现一次。",
            "level": "confirmed", "source": "run",
        }],
    )
    payload = reduction.model_dump(mode="json", by_alias=True)
    assert validate_maintenance_reduction(
        payload, manuscript=manuscript, source_state_sha256=state_sha,
    ).canon == reduction.canon

    payload["coverage_spans"] = [[1, len(manuscript)]]
    unsigned = {key: value for key, value in payload.items() if key != "reduction_sha256"}
    payload["reduction_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(ValueError, match="coverage|span ledger"):
        validate_maintenance_reduction(
            payload, manuscript=manuscript, source_state_sha256=state_sha,
        )


def test_ambiguous_quote_cannot_be_silently_adapted() -> None:
    manuscript = "重复证据。重复证据。"
    state_sha = canonical_sha256({"confirmed_facts": []})
    contract = build_maintenance_window_contracts(
        manuscript, entry_state_sha256=state_sha, target_characters=400,
    )[0]
    with pytest.raises(ValueError, match="unique exact"):
        adapt_maintenance_window_payload(
            _payload("重复证据。"), contract=contract, manuscript=manuscript,
        )
