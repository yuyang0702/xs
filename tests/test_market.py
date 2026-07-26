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

ZHIHU_API_JSON = """
{"data":[{"module_type":"billboard","module_title":"榜单","module_data":{"data":{
  "button_text":"全部","data":[
    {"head":{"title":"推荐榜","type":"recommend","filters":[{"key":"0","name":"全部"},{"key":"1","name":"言情"}]},
     "content_list":[
       {"business_id":"1654593780966428672","title":"河清海晏","artwork":"https://pic.example/a.jpg",
        "subtitle":"66.3 万赞","url":"https://www.zhihu.com/market/paid_column/1/section/2",
        "label_text":"言情 · 警察","description":"她在暴雨里等一个答案。"}
     ]},
    {"head":{"title":"热度榜","type":"hot","filters":[{"key":"12","name":"脑洞"}]},
     "content_list":[
       {"business_id":"2050600604976803918","title":"不提分就出不去的房间",
        "subtitle":"86.2 黑马指数","label_text":"脑洞 · 学霸","description":"第一天重新开始。"}
     ]}
  ]}}}]}
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


def test_parse_zhihu_market_accepts_the_live_billboard_api_shape() -> None:
    works = parse_zhihu_market(ZHIHU_API_JSON)

    assert len(works) == 2
    assert works[0]["platform_work_id"] == "1654593780966428672"
    assert works[0]["ranking_name"] == "推荐榜"
    assert works[0]["category"] == "言情"
    assert works[0]["metrics"]["likes"] == 663000
    assert works[0]["tags"] == ["言情", "警察"]
    assert works[1]["metrics"]["black_horse_index"] == 86.2


def test_live_shape_preserves_platform_length_type() -> None:
    page = ZHIHU_API_JSON.replace(
        '"business_id":"1654593780966428672"',
        '"business_id":"1654593780966428672","space_type":"LongSpace"',
    )

    works = parse_zhihu_market(page)

    assert works[0]["length_type"] == "long"
    assert works[0]["length_source"] == "platform"


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


def test_keywords_count_distinct_works_and_expose_evidence_by_text_area(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    works = [
        {"id": "1", "title": "重生后复仇", "summary": "她回到婚礼现场复仇", "tags": ["言情"],
         "rank": 1, "ranking_name": "推荐榜"},
        {"id": "2", "title": "重来一次", "summary": "重生之后，她决定复仇", "tags": ["言情"],
         "rank": 8, "ranking_name": "热度榜"},
        {"id": "2", "title": "重来一次", "summary": "重生之后，她决定复仇", "tags": ["言情"],
         "rank": 2, "ranking_name": "推荐榜"},
        {"id": "3", "title": "孤城", "summary": "只有一个人", "tags": ["悬疑"],
         "rank": 3, "ranking_name": "推荐榜"},
    ]

    result = market._keywords(works)

    combined = {item["word"]: item for item in result["combined"]}
    assert combined["重生"]["work_count"] == 2
    assert combined["重生"]["category"] == "题材设定"
    assert combined["重生"]["score"] > 0
    assert {work["id"] for work in combined["重生"]["works"]} == {"1", "2"}
    assert "复仇" not in {item["word"] for item in result["title"]}
    assert "复仇" in {item["word"] for item in result["summary"]}
    assert "孤城" not in combined


def test_keyword_evidence_separates_daily_and_period_best_rank(tmp_path) -> None:
    now = {"value": datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc)}
    page = ZHIHU_HTML.replace("那年暗室逢月明", "重生月明").replace("铜臭", "重生铜臭")
    pages = iter([
        page.replace('"rank":1', '"rank":4', 1),
        page.replace('"rank":1', '"rank":2', 1),
        page.replace('"rank":1', '"rank":3', 1),
    ])
    db = Database(tmp_path / "app.db")
    db.migrate()
    market = MarketService(
        db, ReferenceLibrary(db, tmp_path / "references"),
        fetcher=lambda _url: next(pages), clock=lambda: now["value"],
    )
    market.refresh()
    now["value"] = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    market.refresh()
    now["value"] = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
    market.refresh()

    result = market.dashboard(days=30)
    keyword = next(item for item in result["keywords"]["combined"] if item["word"] == "重生")
    work = next(item for item in keyword["works"] if item["id"] == "zhihu:zh-1")

    assert work["daily_best"] == {"date": "2026-07-27", "rank": 3, "ranking_name": "推荐榜"}
    assert work["period_best"] == {"date": "2026-07-26", "rank": 2, "ranking_name": "推荐榜"}


def test_market_keywords_do_not_start_ltp_for_fixed_vocabulary(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    market.nlp_analyzer = lambda _text: (_ for _ in ()).throw(
        AssertionError("fixed market vocabulary must not start LTP")
    )

    result = market._keywords([
        {"id": "1", "title": "重生复仇", "summary": "她决定复仇", "tags": [],
         "rank": 1, "ranking_name": "推荐榜"},
        {"id": "2", "title": "重生归来", "summary": "再次复仇", "tags": [],
         "rank": 2, "ranking_name": "推荐榜"},
    ])

    assert {item["word"] for item in result["combined"]} >= {"重生", "复仇"}


def test_length_filter_and_user_override_have_priority(tmp_path) -> None:
    page = ZHIHU_API_JSON.replace(
        '"business_id":"1654593780966428672"',
        '"business_id":"1654593780966428672","space_type":"LongSpace"',
    )
    market = service(tmp_path, [page])
    market.refresh()

    assert {item["id"] for item in market.list_works(length_type="long")} == {
        "zhihu:1654593780966428672",
    }

    changed = market.set_length_type("zhihu:1654593780966428672", "short")
    assert changed["length_type"] == "short"
    assert changed["length_source"] == "user"
    assert changed["length_override"] == "short"

    reset = market.set_length_type("zhihu:1654593780966428672", None)
    assert reset["length_type"] == "long"
    assert reset["length_source"] == "platform"


def test_long_ranking_signal_survives_same_work_in_other_rankings(tmp_path) -> None:
    page = """
    <script type="application/json">{"lists":[
      {"name":"长篇榜","category":"悬疑","works":[{"id":"same","title":"长夜","rank":1}]},
      {"name":"推荐榜","category":"悬疑","works":[{"id":"same","title":"长夜","rank":2}]}
    ]}</script>
    """
    market = service(tmp_path, [page])

    market.refresh()

    assert market.work_detail("zhihu:same")["length_type"] == "long"


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


def test_confirmed_txt_can_supply_length_when_platform_has_no_signal(tmp_path) -> None:
    market = service(tmp_path, [ZHIHU_HTML])
    market.refresh("zhihu-salt")
    text = "\n".join(f"第{i}章\n" + ("正文" * 6000) for i in range(1, 11))
    reference = market.references.import_text(title="铜臭", text=text, source_type="txt")

    market.confirm_link(reference["id"], "zhihu:zh-2")

    work = market.work_detail("zhihu:zh-2")
    assert work["length_type"] == "long"
    assert work["length_source"] == "txt"
    assert "10" in work["length_evidence"]
    market.set_length_type("zhihu:zh-2", "short")
    reset = market.set_length_type("zhihu:zh-2", None)
    assert reset["length_type"] == "long"
    assert reset["length_source"] == "txt"
