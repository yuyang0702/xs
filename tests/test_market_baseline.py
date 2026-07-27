import json
import uuid

from novel_flywheel.db import Database
from novel_flywheel.market_baseline import MarketBaselineService
from novel_flywheel.reference_library import ReferenceLibrary


def setup_cohort(tmp_path, count: int, *, ranking: str = "推荐榜", category: str = "悬疑",
                 length_type: str = "short"):
    db = Database(tmp_path / "app.db")
    db.migrate()
    references = ReferenceLibrary(db, tmp_path / "references")
    with db.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO market_sources "
            "(id,platform,name,url,enabled,config_json,refresh_status,created_at,updated_at) "
            "VALUES ('source','zhihu','测试榜','https://example.com',1,'{}','success',datetime('now'),datetime('now'))"
        )
    for index in range(count):
        source = references.import_text(
            title=f"作品{index}", source_type="paste",
            text=f"为什么朋友会消失？他决定追查。最终真相揭晓，朋友回来了。{index}",
            platform="知乎", content_type="popular_sample",
        )
        work_id = f"zhihu:work-{index}"
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO market_works "
                "(id,platform,platform_work_id,title,normalized_title,tags_json,latest_metrics_json,"
                "original_category,unified_category,length_type,length_source,first_seen_at,last_seen_at) "
                "VALUES (?,?,?,?,?,'[]','{}',?,?,?,?,datetime('now'),datetime('now'))",
                (work_id, "zhihu", f"work-{index}", f"作品{index}", f"作品{index}",
                 category, category, length_type, "platform"),
            )
            for day in range(2):
                snapshot_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO market_snapshots VALUES (?,?,?,?,?,?)",
                    (snapshot_id, "source", f"2026-07-{20 + day}T08:00:00+00:00", "success", 1, "{}"),
                )
                connection.execute(
                    "INSERT INTO market_entries VALUES (?,?,?,?,?,?,?,datetime('now'))",
                    (uuid.uuid4().hex, snapshot_id, work_id, ranking, category, index + 1, "{}"),
                )
            connection.execute(
                "INSERT INTO reference_market_links VALUES (?,?,'confirmed',datetime('now'),datetime('now'))",
                (source["id"], work_id),
            )
            node_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO learning_nodes VALUES (?, 'mechanism', ?, NULL, 'confirmed', ?, NULL, NULL, datetime('now'), datetime('now'))",
                (node_id, source["id"], json.dumps({
                    "name": "延迟回答核心读者问题", "positions": [8.0, 82.0],
                    "confidence": 0.8,
                }, ensure_ascii=False)),
            )
    return MarketBaselineService(db, references)


def test_cohort_counts_each_work_once_across_snapshots(tmp_path) -> None:
    service = setup_cohort(tmp_path, 5)

    cohort = service.list_cohorts()[0]
    baseline = service.build_baseline(cohort["key"])

    assert cohort["sample_count"] == 5
    assert baseline["sample_count"] == 5
    assert baseline["confidence_level"] == "preliminary"
    assert baseline["date_range"] == {"start": "2026-07-20", "end": "2026-07-21"}
    assert baseline["mechanisms"][0]["work_count"] == 5
    assert baseline["mechanisms"][0]["prevalence_percent"] == 100.0


def test_cohort_thresholds_and_dimensions_remain_isolated(tmp_path) -> None:
    preliminary = setup_cohort(tmp_path / "five", 5).list_cohorts()[0]
    advisory = setup_cohort(tmp_path / "ten", 10).list_cohorts()[0]
    insufficient = setup_cohort(tmp_path / "four", 4).list_cohorts()[0]

    assert insufficient["confidence_level"] == "insufficient"
    assert preliminary["confidence_level"] == "preliminary"
    assert advisory["confidence_level"] == "advisory"
    assert preliminary["key"] == {
        "platform": "zhihu", "ranking_name": "推荐榜",
        "category": "悬疑", "length_type": "short",
    }


def test_baseline_explains_sample_weights_and_keeps_raw_counts(tmp_path) -> None:
    service = setup_cohort(tmp_path, 5)
    baseline = service.build_baseline(service.list_cohorts()[0]["key"])

    assert baseline["sample_count"] == 5
    assert len(baseline["samples"]) == 5
    assert all(0 < sample["weight"] <= 1 for sample in baseline["samples"])
    assert all(sample["weight_reasons"] for sample in baseline["samples"])
    assert baseline["mechanisms"][0]["weighted_prevalence_percent"] == 100.0
