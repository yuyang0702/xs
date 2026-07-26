from datetime import datetime, timezone

import pytest

from novel_flywheel.db import Database
from novel_flywheel.market import MarketService, normalize_work_title, parse_zhihu_market
from novel_flywheel.reference_library import ReferenceLibrary


ZHIHU_HTML = """
<html><body>
<script id="market-data" type="application/json">
{"lists":[
  {"name":"推荐榜","category":"脑洞","works":[
    {"id":"zh-1","title":"那年暗室逢月明","rank":1,"likes":"25.9 万赞",
     "summary":"我穿得奇奇怪怪，别人穿越风光潇洒。","cover":"https://pic.example/1.jpg",
     "url":"https://www.zhihu.com/market/paid_column/1","tags":["脑洞","言情"]},
    {"id":"zh-2","title":"铜臭","rank":2,"likes":"2.2 万赞","summary":"膝下只有我。","tags":["脑洞"]}
  ]},
  {"name":"今日必读","category":"悬疑","works":[
    {"id":"zh-3","title":"世界代码","rank":1,"likes":"731 赞","summary":"世界出现了错误。","tags":["悬疑","科幻"]}
  ]}
]}
</script>
</body></html>
"""


def service(tmp_path, pages: list[str]) -> MarketService:
    db = Database(tmp_path / "app.db")
    db.migrate()
    iterator = iter(pages)
    return MarketService(
        db,
        ReferenceLibrary(db, tmp_path / "references"),
        fetcher=lambda _url: next(iterator),
        clock=lambda: datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
    )


def test_parse_zhihu_market_extracts_visible_market_fields() -> None:
    works = parse_zhihu_market(ZHIHU_HTML)

    assert len(works) == 3
    assert works[0]["platform_work_id"] == "zh-1"
    assert works[0]["ranking_name"] == "推荐榜"
    assert works[0]["category"] == "脑洞"
    assert works[0]["rank"] == 1
    assert works[0]["metrics"]["likes"] == 259000
    assert works[0]["tags"] == ["脑洞", "言情"]


def test_refresh_keeps_one_work_and_multiple_snapshot_entries(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML, ZHIHU_HTML.replace('"rank":1', '"rank":2', 1)])

    market.refresh("zhihu-salt")
    second = market.refresh("zhihu-salt")

    assert second["status"] == "success"
    assert len(market.list_works(platform="zhihu")) == 3
    history = market.work_detail("zhihu:zh-1")["history"]
    assert [item["rank"] for item in history] == [2, 1]


def test_empty_refresh_fails_without_replacing_last_snapshot(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML, "<html><body>会员</body></html>"])
    market.refresh("zhihu-salt")

    with pytest.raises(ValueError, match="没有识别到榜单作品"):
        market.refresh("zhihu-salt")

    dashboard = market.dashboard(platform="zhihu", days=30)
    assert dashboard["summary"]["work_count"] == 3
    assert dashboard["refresh"]["status"] == "failed"


def test_dashboard_requires_two_snapshots_before_claiming_trend(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    market.refresh("zhihu-salt")

    dashboard = market.dashboard(platform="zhihu", days=30)

    assert dashboard["summary"]["snapshot_count"] == 1
    assert dashboard["trend_ready"] is False
    assert dashboard["categories"][0]["trend"] == "数据不足"
    assert "不代表全网市场" in dashboard["boundary"]


def test_title_normalization_and_reference_matching(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    market.refresh("zhihu-salt")
    reference = market.references.import_text(
        title="《那年暗室逢月明》（知乎盐选完结版）",
        text="我穿得奇奇怪怪，别人穿越风光潇洒。后续正文。",
        source_type="txt",
        source_uri="《那年暗室逢月明》（知乎盐选完结版）.txt",
    )

    result = market.match_reference(reference["id"])

    assert normalize_work_title("知乎_《那年暗室逢月明》（完结）.txt") == "那年暗室逢月明"
    assert result["status"] == "high"
    assert result["candidates"][0]["work_id"] == "zhihu:zh-1"
    assert "标题完全一致" in result["candidates"][0]["reasons"]
    assert "正文开头与榜单简介相似" in result["candidates"][0]["reasons"]


def test_confirmed_link_updates_market_context_without_changing_reference(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    market.refresh("zhihu-salt")
    reference = market.references.import_text(
        title="铜臭", text="膝下只有我。正文没有变化。", source_type="txt",
    )

    linked = market.confirm_link(reference["id"], "zhihu:zh-2")
    source = market.references.get(reference["id"])

    assert linked["status"] == "confirmed"
    assert source["title"] == "铜臭"
    assert market.references.read_text(reference["id"]) == "膝下只有我。正文没有变化。"
    assert market.reference_context(reference["id"])["current"]["rank"] == 2

    market.unlink_reference(reference["id"])
    assert market.reference_context(reference["id"]) is None

