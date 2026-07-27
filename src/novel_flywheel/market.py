from __future__ import annotations

import hashlib
import html
import json
import math
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary


ZHIHU_SALT_URL = "https://www.zhihu.com/fiore/h5/vip-web"
ZHIHU_BILLBOARD_URL = (
    "https://api.zhihu.com/km-vip-zhihu-web/vip_tab/svip_story?modules=billboard"
)
MARKET_BOUNDARY = "结果仅反映当前抓取到的平台榜单样本，不代表全网市场。"
TITLE_NOISE = re.compile(
    r"(?i)(?:\.txt$|知乎|盐选|会员|全文|完整版|完结版|完结|修订版|精校版|"
    r"第\d+版|作者[:：].*$|[-—_]\s*作者.*$)"
)
WRAPPERS = str.maketrans("", "", "《》〈〉「」『』【】[]()（）")
TOKEN_STOPWORDS = {
    "我们", "你们", "他们", "自己", "一个", "这个", "那个", "什么", "怎么",
    "故事", "作品", "开始", "然后", "已经", "没有", "只有",
}

LENGTH_TYPES = {"long", "short", "anthology", "unknown"}
SPACE_LENGTH_TYPES = {
    "longspace": "long", "long": "long", "novel": "long",
    "shortspace": "short", "short": "short",
    "anthology": "anthology", "collection": "anthology",
}
KEYWORD_GROUPS = {
    "题材设定": ("重生", "穿越", "循环", "系统", "末世", "悬疑", "脑洞", "言情", "甜宠", "虐恋", "治愈"),
    "人物身份": ("皇后", "公主", "王爷", "总裁", "医生", "警察", "学霸", "替身", "暴君"),
    "人物关系": ("青梅竹马", "夫妻", "婆媳", "姐妹", "师徒", "母女", "父子", "婚姻"),
    "核心冲突": ("复仇", "背叛", "替嫁", "夺权", "误会", "退婚", "死亡", "囚禁"),
    "情绪体验": ("后悔", "暗恋", "恐惧", "绝望", "救赎", "遗憾"),
    "故事场景": ("校园", "皇宫", "医院", "婚礼", "密室", "职场", "古代", "现代"),
}
KEYWORD_ALIASES = {"重来": "重生", "复生": "重生", "甜文": "甜宠", "虐文": "虐恋"}


def normalize_work_title(value: str) -> str:
    cleaned = TITLE_NOISE.sub("", value.strip())
    cleaned = cleaned.translate(WRAPPERS)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"^[-—_·]+|[-—_·]+$", "", cleaned)
    return cleaned.strip()


def parse_metric(value: Any) -> int | float | str:
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|亿)?", text)
    if not match:
        return text
    number = float(match.group(1))
    if match.group(2) == "万":
        number *= 10_000
    elif match.group(2) == "亿":
        number *= 100_000_000
    return int(number) if number.is_integer() else number


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._json_script = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type") in {"application/json", "application/ld+json"}:
            self._json_script = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._json_script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_script:
            self.scripts.append("".join(self._parts))
            self._json_script = False


def _work_from_dict(item: dict[str, Any], ranking: str, category: str, rank: int) -> dict[str, Any] | None:
    title = item.get("title") or item.get("name")
    if not isinstance(title, str) or not normalize_work_title(title):
        return None
    raw_id = (
        item.get("id") or item.get("workId") or item.get("work_id")
        or item.get("columnId") or item.get("column_id")
        or item.get("contentId") or item.get("content_id") or item.get("business_id")
    )
    url = item.get("url") or item.get("link") or item.get("detailUrl") or item.get("detail_url")
    if not raw_id:
        raw_id = hashlib.sha256(f"{title}|{url or ''}".encode("utf-8")).hexdigest()[:20]
    metrics: dict[str, Any] = {}
    metric_aliases = {
        "likes": ("likes", "likeCount", "like_count", "voteCount", "vote_count", "likeText", "like_text"),
        "black_horse_index": ("blackHorseIndex", "black_horse_index", "index"),
    }
    for output_name, aliases in metric_aliases.items():
        for alias in aliases:
            if alias in item and item[alias] not in (None, ""):
                metrics[output_name] = parse_metric(item[alias])
                break
    subtitle = str(item.get("subtitle") or item.get("skuGrade") or item.get("sku_grade") or "")
    if "赞" in subtitle and "likes" not in metrics:
        metrics["likes"] = parse_metric(subtitle)
    if "黑马指数" in subtitle and "black_horse_index" not in metrics:
        metrics["black_horse_index"] = parse_metric(subtitle)
    tags = item.get("tags") or item.get("categories") or item.get("labels") or item.get("label_text") or []
    if isinstance(tags, str):
        tags = [part for part in re.split(r"[,，/、·\s]+", tags) if part]
    if isinstance(tags, list):
        tags = [
            str(tag.get("name") if isinstance(tag, dict) else tag).strip()
            for tag in tags
            if tag
        ]
    raw_space_type = str(item.get("space_type") or item.get("spaceType") or "").strip()
    length_type = SPACE_LENGTH_TYPES.get(raw_space_type.lower(), "unknown")
    if length_type == "unknown" and "长篇" in ranking:
        length_type = "long"
        length_source = "ranking"
        length_evidence = ranking
    else:
        length_source = "platform" if length_type != "unknown" else "unknown"
        length_evidence = raw_space_type or None
    return {
        "platform_work_id": str(raw_id),
        "title": html.unescape(title.strip()),
        "author": item.get("author") or item.get("authorName") or item.get("author_name"),
        "summary": item.get("summary") or item.get("description") or item.get("excerpt"),
        "cover_url": item.get("cover") or item.get("coverUrl") or item.get("cover_url")
                     or item.get("artwork") or item.get("image"),
        "detail_url": url,
        "ranking_name": ranking or "榜单",
        "category": category or (tags[0] if tags else "未分类"),
        "rank": int(item.get("rank") or rank),
        "tags": tags,
        "metrics": metrics,
        "length_type": length_type,
        "length_source": length_source,
        "length_evidence": length_evidence,
    }


def _extract_market_lists(node: Any, inherited_name: str = "", inherited_category: str = "") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            results.extend(_extract_market_lists(item, inherited_name, inherited_category))
        return results
    if not isinstance(node, dict):
        return results

    head = node.get("head") if isinstance(node.get("head"), dict) else {}
    ranking = str(
        node.get("rankingName") or node.get("ranking_name")
        or node.get("listName") or node.get("list_name")
        or head.get("title") or node.get("name") or inherited_name
    )
    category = str(
        node.get("categoryName") or node.get("category_name")
        or node.get("category") or inherited_category
    )
    works = (
        node.get("works") or node.get("items") or node.get("contents")
        or node.get("contentList") or node.get("content_list")
    )
    if isinstance(works, list):
        parsed = [
            _work_from_dict(item, ranking, category, index)
            for index, item in enumerate(works, 1)
            if isinstance(item, dict)
        ]
        results.extend(item for item in parsed if item)
    for key, value in node.items():
        if key in {"works", "items", "contents", "contentList", "content_list"}:
            continue
        results.extend(_extract_market_lists(value, ranking, category))
    return results


def parse_zhihu_market(page: str) -> list[dict[str, Any]]:
    collector = _ScriptCollector()
    collector.feed(page)
    found: list[dict[str, Any]] = []
    try:
        found.extend(_extract_market_lists(json.loads(page)))
    except json.JSONDecodeError:
        pass
    for script in collector.scripts:
        try:
            found.extend(_extract_market_lists(json.loads(script)))
        except (json.JSONDecodeError, RecursionError):
            continue
    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in found:
        key = (item["platform_work_id"], item["ranking_name"], item["rank"])
        unique[key] = item
    return list(unique.values())


def _default_fetcher(url: str) -> str:
    target_url = ZHIHU_BILLBOARD_URL if url == ZHIHU_SALT_URL else url
    response = httpx.get(
        target_url,
        timeout=25,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": ZHIHU_SALT_URL,
        },
    )
    response.raise_for_status()
    return response.text


def _json_row(row: Any, *fields: str) -> dict[str, Any]:
    result = dict(row)
    for field in fields:
        result[field.removesuffix("_json")] = json.loads(result.pop(field) or "{}")
    return result


class MarketService:
    def __init__(
        self,
        db: Database,
        references: ReferenceLibrary,
        *,
        fetcher: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        nlp_analyzer: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.db = db
        self.references = references
        self.fetcher = fetcher or _default_fetcher
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.nlp_analyzer = nlp_analyzer
        self._ensure_default_source()

    def _ensure_default_source(self) -> None:
        now = self.clock().isoformat()
        with self.db.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO market_sources
                (id,platform,name,url,enabled,config_json,refresh_status,created_at,updated_at)
                VALUES ('zhihu-salt','zhihu','知乎盐选榜单',?,1,'{}','never',?,?)""",
                (ZHIHU_SALT_URL, now, now),
            )

    def refresh(self, source_id: str = "zhihu-salt") -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or not source["enabled"]:
            raise ValueError("市场数据源不存在或已停用")
        attempted_at = self.clock().isoformat()
        try:
            page = self.fetcher(source["url"])
            parsed = parse_zhihu_market(page) if source["platform"] == "zhihu" else []
            if not parsed:
                raise ValueError("没有识别到榜单作品，页面可能为空或结构已变化")
            snapshot_id = uuid.uuid4().hex
            with self.db.connect() as connection:
                connection.execute(
                    "INSERT INTO market_snapshots VALUES (?,?,?,?,?,?)",
                    (snapshot_id, source_id, attempted_at, "success", len(parsed), "{}"),
                )
                for item in parsed:
                    work_id = f"{source['platform']}:{item['platform_work_id']}"
                    connection.execute(
                        """INSERT INTO market_works
                        (id,platform,platform_work_id,title,normalized_title,author,summary,cover_url,
                         detail_url,original_category,unified_category,tags_json,latest_metrics_json,
                         length_type,platform_length_type,length_source,length_evidence,
                         first_seen_at,last_seen_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                          title=excluded.title, normalized_title=excluded.normalized_title,
                          author=COALESCE(excluded.author,market_works.author),
                          summary=COALESCE(excluded.summary,market_works.summary),
                          cover_url=COALESCE(excluded.cover_url,market_works.cover_url),
                          detail_url=COALESCE(excluded.detail_url,market_works.detail_url),
                          original_category=excluded.original_category,
                          unified_category=COALESCE(market_works.unified_category,excluded.unified_category),
                          tags_json=excluded.tags_json,latest_metrics_json=excluded.latest_metrics_json,
                          length_type=CASE WHEN market_works.length_override IS NULL
                            AND excluded.length_type!='unknown'
                            THEN excluded.length_type ELSE market_works.length_type END,
                          platform_length_type=COALESCE(
                            excluded.platform_length_type,market_works.platform_length_type),
                          length_source=CASE WHEN market_works.length_override IS NULL
                            AND excluded.length_type!='unknown'
                            THEN excluded.length_source ELSE market_works.length_source END,
                          length_evidence=CASE WHEN market_works.length_override IS NULL
                            AND excluded.length_type!='unknown'
                            THEN excluded.length_evidence ELSE market_works.length_evidence END,
                          last_seen_at=excluded.last_seen_at""",
                        (
                            work_id, source["platform"], item["platform_work_id"], item["title"],
                            normalize_work_title(item["title"]), item["author"], item["summary"],
                            item["cover_url"], item["detail_url"], item["category"], item["category"],
                            json.dumps(item["tags"], ensure_ascii=False),
                            json.dumps(item["metrics"], ensure_ascii=False),
                            item["length_type"],
                            item["length_type"] if item["length_source"] == "platform" else None,
                            item["length_source"], item["length_evidence"],
                            attempted_at, attempted_at,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO market_entries VALUES (?,?,?,?,?,?,?,?)",
                        (
                            uuid.uuid4().hex, snapshot_id, work_id, item["ranking_name"],
                            item["category"], item["rank"],
                            json.dumps(item["metrics"], ensure_ascii=False), attempted_at,
                        ),
                    )
                connection.execute(
                    """UPDATE market_sources SET refresh_status='success',refresh_error=NULL,
                    last_success_at=?,last_attempt_at=?,updated_at=? WHERE id=?""",
                    (attempted_at, attempted_at, attempted_at, source_id),
                )
            return {
                "status": "success", "source_id": source_id, "snapshot_id": snapshot_id,
                "work_count": len(parsed), "captured_at": attempted_at,
            }
        except Exception as exc:
            with self.db.connect() as connection:
                connection.execute(
                    """UPDATE market_sources SET refresh_status='failed',refresh_error=?,
                    last_attempt_at=?,updated_at=? WHERE id=?""",
                    (str(exc), attempted_at, attempted_at, source_id),
                )
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"榜单更新失败：{exc}") from exc

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM market_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return None
        result = _json_row(row, "config_json")
        result["enabled"] = bool(result["enabled"])
        return result

    def list_sources(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM market_sources ORDER BY platform,name").fetchall()
        return [_json_row(row, "config_json") for row in rows]

    def list_works(
        self,
        *,
        platform: str | None = None,
        ranking: str | None = None,
        category: str | None = None,
        length_type: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions, values = [], []
        if platform:
            conditions.append("work.platform=?")
            values.append(platform)
        if ranking:
            conditions.append("entry.ranking_name=?")
            values.append(ranking)
        if category:
            conditions.append("COALESCE(entry.category,work.original_category)=?")
            values.append(category)
        if length_type:
            conditions.append("work.length_type=?")
            values.append(length_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            WITH latest AS (
              SELECT source_id,MAX(rowid) snapshot_rowid FROM market_snapshots
              WHERE status='success' GROUP BY source_id
            )
            SELECT work.*,entry.ranking_name,entry.category,entry.rank,
                   entry.metrics_json AS entry_metrics_json,snapshot.captured_at,
                   link.reference_id
            FROM market_entries entry
            JOIN market_snapshots snapshot ON snapshot.id=entry.snapshot_id
            JOIN latest ON latest.source_id=snapshot.source_id AND latest.snapshot_rowid=snapshot.rowid
            JOIN market_works work ON work.id=entry.work_id
            LEFT JOIN reference_market_links link ON link.work_id=work.id
            {where}
            ORDER BY entry.ranking_name,entry.rank,work.title
        """
        with self.db.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        results = []
        for row in rows:
            item = _json_row(row, "tags_json", "latest_metrics_json", "entry_metrics_json")
            item["metrics"] = item.pop("entry_metrics")
            item.pop("latest_metrics", None)
            results.append(item)
        return results

    def work_detail(self, work_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM market_works WHERE id=?", (work_id,)).fetchone()
            history = connection.execute(
                """SELECT entry.ranking_name,entry.category,entry.rank,entry.metrics_json,
                snapshot.captured_at FROM market_entries entry
                JOIN market_snapshots snapshot ON snapshot.id=entry.snapshot_id
                WHERE entry.work_id=? ORDER BY snapshot.captured_at DESC,entry.rowid DESC""",
                (work_id,),
            ).fetchall()
        if not row:
            raise LookupError("市场作品不存在")
        result = _json_row(row, "tags_json", "latest_metrics_json")
        result["history"] = [
            {**_json_row(item, "metrics_json")} for item in history
        ]
        return result

    def dashboard(
        self,
        *,
        platform: str | None = None,
        days: int = 30,
        ranking: str | None = None,
        category: str | None = None,
        length_type: str | None = None,
    ) -> dict[str, Any]:
        works = self.list_works(
            platform=platform, ranking=ranking, category=category, length_type=length_type,
        )
        cutoff = (self.clock() - timedelta(days=max(1, min(days, 365)))).isoformat()
        with self.db.connect() as connection:
            snapshots = connection.execute(
                """SELECT snapshot.* FROM market_snapshots snapshot
                JOIN market_sources source ON source.id=snapshot.source_id
                WHERE snapshot.status='success' AND snapshot.captured_at>=?
                AND (? IS NULL OR source.platform=?)
                ORDER BY snapshot.captured_at""",
                (cutoff, platform, platform),
            ).fetchall()
            source = connection.execute(
                """SELECT * FROM market_sources
                WHERE (? IS NULL OR platform=?) ORDER BY last_attempt_at DESC LIMIT 1""",
                (platform, platform),
            ).fetchone()
            link_count = connection.execute(
                """SELECT COUNT(*) FROM reference_market_links link
                JOIN market_works work ON work.id=link.work_id
                WHERE (? IS NULL OR work.platform=?) AND link.status='confirmed'""",
                (platform, platform),
            ).fetchone()[0]
        unique_works = list({item["id"]: item for item in works}.values())
        counts = Counter(
            (item["category"] or item["original_category"] or "未分类") for item in unique_works
        )
        top_counts = Counter(
            (item["category"] or item["original_category"] or "未分类")
            for item in unique_works if item["rank"] and item["rank"] <= 5
        )
        metric_sums: dict[str, list[float]] = defaultdict(list)
        for item in unique_works:
            cat = item["category"] or item["original_category"] or "未分类"
            numeric = [float(value) for value in item["metrics"].values() if isinstance(value, (int, float))]
            if numeric:
                metric_sums[cat].append(max(numeric))
        total = len(unique_works) or 1
        max_count = max(counts.values(), default=1)
        categories = []
        for name, count in counts.most_common():
            average = sum(metric_sums[name]) / len(metric_sums[name]) if metric_sums[name] else 0
            heat = round(100 * (0.55 * count / max_count + 0.45 * top_counts[name] / max(count, 1)))
            categories.append({
                "name": name, "count": count, "share": round(count * 100 / total, 1),
                "top_five": top_counts[name], "average_metric": round(average, 1),
                "heat": heat, "competition": "高" if count >= max(3, max_count * .7) else "中" if count >= 2 else "低",
                "trend": "数据不足",
            })
        snapshot_count = len(snapshots)
        trend_ready = snapshot_count >= 2
        trend_series = self._trend_series([dict(item) for item in snapshots], platform, ranking)
        if trend_ready and trend_series:
            first, last = trend_series[0]["categories"], trend_series[-1]["categories"]
            for item in categories:
                change = last.get(item["name"], 0) - first.get(item["name"], 0)
                item["trend"] = "上升" if change > 0 else "下降" if change < 0 else "稳定"
        keywords = self._keywords(works, self._rank_history(cutoff, platform, ranking))
        refresh = dict(source) if source else {"refresh_status": "never", "refresh_error": None}
        refresh = {
            "status": refresh.get("refresh_status", "never"),
            "error": refresh.get("refresh_error"),
            "last_success_at": refresh.get("last_success_at"),
            "last_attempt_at": refresh.get("last_attempt_at"),
        }
        return {
            "summary": {
                "work_count": len(unique_works),
                "entry_count": len(works),
                "snapshot_count": snapshot_count,
                "linked_count": int(link_count),
                "hot_category": categories[0]["name"] if categories else None,
                "rising_category": next((item["name"] for item in categories if item["trend"] == "上升"), None),
            },
            "categories": categories,
            "trend_ready": trend_ready,
            "trend_series": trend_series,
            "rankings": self._ranking_distribution(works),
            "keywords": keywords,
            "works": works,
            "refresh": refresh,
            "boundary": MARKET_BOUNDARY,
        }

    def _trend_series(
        self, snapshots: list[dict[str, Any]], platform: str | None, ranking: str | None,
    ) -> list[dict[str, Any]]:
        points = []
        with self.db.connect() as connection:
            for snapshot in snapshots:
                rows = connection.execute(
                    """SELECT entry.category,COUNT(*) count FROM market_entries entry
                    JOIN market_works work ON work.id=entry.work_id
                    WHERE entry.snapshot_id=? AND (? IS NULL OR work.platform=?)
                    AND (? IS NULL OR entry.ranking_name=?)
                    GROUP BY entry.category""",
                    (snapshot["id"], platform, platform, ranking, ranking),
                ).fetchall()
                points.append({
                    "captured_at": snapshot["captured_at"],
                    "categories": {row["category"] or "未分类": row["count"] for row in rows},
                })
        return points

    @staticmethod
    def _ranking_distribution(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
        table: dict[str, Counter[str]] = defaultdict(Counter)
        for item in works:
            table[item["ranking_name"]][item["category"] or "未分类"] += 1
        return [{"name": name, "categories": dict(values)} for name, values in sorted(table.items())]

    def _rank_history(
        self, cutoff: str, platform: str | None, ranking: str | None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT work.id,entry.rank,entry.ranking_name,snapshot.captured_at
                FROM market_entries entry
                JOIN market_snapshots snapshot ON snapshot.id=entry.snapshot_id
                JOIN market_works work ON work.id=entry.work_id
                WHERE snapshot.status='success' AND snapshot.captured_at>=?
                AND (? IS NULL OR work.platform=?)
                AND (? IS NULL OR entry.ranking_name=?)""",
                (cutoff, platform, platform, ranking, ranking),
            ).fetchall()
        by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
        local_tz = ZoneInfo("Asia/Shanghai")
        for row in rows:
            captured = datetime.fromisoformat(row["captured_at"])
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            by_work[row["id"]].append({
                "date": captured.astimezone(local_tz).date().isoformat(),
                "rank": row["rank"], "ranking_name": row["ranking_name"],
            })
        result = {}
        for work_id, entries in by_work.items():
            days: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for entry in entries:
                days[entry["date"]].append(entry)
            latest_day = max(days)
            best = lambda values: min(values, key=lambda item: (
                item["rank"] if item["rank"] is not None else 999,
                item["ranking_name"], item["date"],
            ))
            result[work_id] = {
                "daily_best": best(days[latest_day]),
                "period_best": best(entries),
            }
        return result

    def _keywords(
        self, works: list[dict[str, Any]],
        rank_history: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        rank_history = rank_history or {}
        unique: dict[str, dict[str, Any]] = {}
        for item in works:
            current = unique.setdefault(item["id"], {**item, "_rankings": set()})
            current["_rankings"].add(item.get("ranking_name") or "")
            if (item.get("rank") or 999) < (current.get("rank") or 999):
                current["rank"] = item["rank"]
        category_for = {
            word: category for category, words in KEYWORD_GROUPS.items() for word in words
        }

        def terms(text: str, tags: list[str] | None = None) -> set[str]:
            normalized = text or ""
            found = {
                word for word in category_for if word in normalized
            }
            for alias, canonical in KEYWORD_ALIASES.items():
                if alias in normalized:
                    found.add(canonical)
            for tag in tags or []:
                canonical = KEYWORD_ALIASES.get(tag, tag)
                if canonical in category_for:
                    found.add(canonical)
            return found

        areas: dict[str, dict[str, set[str]]] = {
            "title": {}, "summary": {}, "combined": {},
        }
        for work_id, item in unique.items():
            title_terms = terms(item.get("title") or "")
            summary_terms = terms(item.get("summary") or "")
            areas["title"][work_id] = title_terms
            areas["summary"][work_id] = summary_terms
            areas["combined"][work_id] = (
                title_terms | summary_terms | terms("", item.get("tags") or [])
            )

        def summarize(area: str) -> list[dict[str, Any]]:
            result = []
            total = max(1, len(unique))
            all_rankings = {
                name for item in unique.values() for name in item["_rankings"] if name
            }
            vocabulary = sorted(set().union(*areas[area].values()) if areas[area] else set())
            for word in vocabulary:
                matched = [
                    item for work_id, item in unique.items() if word in areas[area][work_id]
                ]
                if len(matched) < 2:
                    continue
                top_five = sum(1 for item in matched if (item.get("rank") or 999) <= 5)
                rankings = {
                    name for item in matched for name in item["_rankings"] if name
                }
                coverage = len(matched) / total
                score = round(
                    55 * coverage
                    + 20 * top_five / len(matched)
                    + 15 * len(rankings) / max(1, len(all_rankings)),
                    1,
                )
                result.append({
                    "word": word,
                    "category": category_for[word],
                    "work_count": len(matched),
                    "share": round(coverage * 100, 1),
                    "top_five_count": top_five,
                    "ranking_count": len(rankings),
                    "trend": "数据不足",
                    "score": score,
                    "works": [{
                        "id": item["id"], "title": item["title"],
                        "ranking_names": sorted(item["_rankings"]),
                        "rank": item.get("rank"),
                        "excerpt": (
                            item.get("title") if area == "title"
                            else (item.get("summary") or item.get("title") or "")[:100]
                        ), **rank_history.get(item["id"], {}),
                    } for item in matched],
                })
            return sorted(result, key=lambda item: (-item["score"], -item["work_count"], item["word"]))[:30]

        return {area: summarize(area) for area in ("combined", "title", "summary")}

    def set_length_type(self, work_id: str, length_type: str | None) -> dict[str, Any]:
        if length_type is not None and length_type not in LENGTH_TYPES - {"unknown"}:
            raise ValueError("篇幅类型必须是 long、short 或 anthology")
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM market_works WHERE id=?", (work_id,),
            ).fetchone()
            if not row:
                raise LookupError("市场作品不存在")
            if length_type is not None:
                effective, source, evidence = length_type, "user", "用户手动确认"
            else:
                platform_type = row["platform_length_type"]
                history = connection.execute(
                    "SELECT ranking_name FROM market_entries WHERE work_id=?", (work_id,),
                ).fetchall()
                if platform_type in LENGTH_TYPES - {"unknown"}:
                    effective, source, evidence = platform_type, "platform", platform_type
                elif any("长篇" in item["ranking_name"] for item in history):
                    effective, source, evidence = "long", "ranking", "长篇榜"
                else:
                    link = connection.execute(
                        """SELECT reference_id FROM reference_market_links
                        WHERE work_id=? AND status='confirmed' LIMIT 1""",
                        (work_id,),
                    ).fetchone()
                    inferred = self._infer_reference_length(link["reference_id"]) if link else None
                    if inferred:
                        effective, source, evidence = inferred
                    else:
                        effective, source, evidence = "unknown", "unknown", None
            connection.execute(
                """UPDATE market_works SET length_type=?,length_source=?,
                length_evidence=?,length_override=? WHERE id=?""",
                (effective, source, evidence, length_type, work_id),
            )
        return self.work_detail(work_id)

    def _infer_reference_length(
        self, reference_id: str,
    ) -> tuple[str, str, str] | None:
        reference = self.references.get(reference_id)
        if reference.get("source_type") not in {"txt", "paste"}:
            return None
        text = self.references.read_text(reference_id)
        anthology_count = len(re.findall(
            r"(?m)^\s*(?:第[一二三四五六七八九十百千0-9]+篇|短篇[一二三四五六七八九十0-9]+)",
            text,
        ))
        chapter_count = len(re.findall(
            r"(?mi)^\s*(?:第[一二三四五六七八九十百千0-9]+[章节卷回]|chapter\s+\d+)",
            text,
        ))
        character_count = len(re.sub(r"\s+", "", text))
        if anthology_count >= 3:
            return "anthology", "txt", f"TXT 检出 {anthology_count} 个独立篇目标题"
        if chapter_count >= 3 or character_count >= 50_000:
            return "long", "txt", f"TXT 共 {character_count} 字符，检出 {chapter_count} 个章节标题"
        return "short", "txt", f"TXT 共 {character_count} 字符，未检出连续长篇章节结构"

    def match_reference(self, reference_id: str) -> dict[str, Any]:
        source = self.references.get(reference_id)
        text = self.references.read_text(reference_id)
        target = normalize_work_title(source.get("source_uri") or source["title"])
        works = self.list_works()
        candidates = []
        exact_count = len({
            work["id"] for work in works if work["normalized_title"] == target
        })
        seen: set[str] = set()
        for work in works:
            if work["id"] in seen:
                continue
            seen.add(work["id"])
            title_score = SequenceMatcher(None, target, work["normalized_title"]).ratio()
            summary_score = _text_similarity(text[:1000], work.get("summary") or "")
            exact = target == work["normalized_title"]
            if not exact and title_score < .58 and summary_score < .38:
                continue
            reasons = []
            if exact:
                reasons.append("标题完全一致")
            elif title_score >= .78:
                reasons.append("标题高度相似")
            if exact_count == 1 and exact:
                reasons.append("只有一个同名候选")
            if summary_score >= .45:
                reasons.append("正文开头与榜单简介相似")
            confidence = min(1.0, .72 * title_score + .28 * summary_score)
            candidates.append({
                "work_id": work["id"], "title": work["title"], "platform": work["platform"],
                "ranking_name": work["ranking_name"], "category": work["category"],
                "confidence": round(confidence, 3), "reasons": reasons,
            })
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        high = bool(candidates and "标题完全一致" in candidates[0]["reasons"]
                    and "只有一个同名候选" in candidates[0]["reasons"])
        return {
            "reference_id": reference_id,
            "normalized_title": target,
            "status": "high" if high else "confirm" if candidates else "none",
            "candidates": candidates[:5],
        }

    def auto_associate_reference(self, reference_id: str) -> dict[str, Any]:
        match = self.match_reference(reference_id)
        candidate = match["candidates"][0] if match["candidates"] else None
        required = {"标题完全一致", "只有一个同名候选", "正文开头与榜单简介相似"}
        if candidate and required.issubset(candidate["reasons"]):
            confirmed = self.confirm_link(reference_id, candidate["work_id"])
            return {**confirmed, "automatic": True, "match": match}
        return {
            "reference_id": reference_id,
            "status": "needs_confirmation" if candidate else "no_match",
            "automatic": False,
            "match": match,
        }

    def confirm_link(self, reference_id: str, work_id: str) -> dict[str, Any]:
        reference = self.references.get(reference_id)
        work = self.work_detail(work_id)
        now = self.clock().isoformat()
        with self.db.connect() as connection:
            connection.execute(
                """INSERT INTO reference_market_links
                (reference_id,work_id,status,confirmed_at,updated_at) VALUES (?,?,'confirmed',?,?)
                ON CONFLICT(reference_id) DO UPDATE SET work_id=excluded.work_id,
                status='confirmed',confirmed_at=excluded.confirmed_at,updated_at=excluded.updated_at""",
                (reference_id, work_id, now, now),
            )
            if (
                reference.get("source_type") in {"txt", "paste"}
                and work["length_type"] == "unknown"
                and work.get("length_override") is None
            ):
                inferred, _, evidence = self._infer_reference_length(reference_id)
                connection.execute(
                    """UPDATE market_works SET length_type=?,length_source='txt',
                    length_evidence=? WHERE id=? AND length_override IS NULL""",
                    (inferred, evidence, work_id),
                )
        return {"reference_id": reference_id, "work_id": work_id, "status": "confirmed", "confirmed_at": now}

    def unlink_reference(self, reference_id: str) -> bool:
        with self.db.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM reference_market_links WHERE reference_id=?", (reference_id,),
            )
        return cursor.rowcount > 0

    def reference_context(self, reference_id: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            link = connection.execute(
                """SELECT link.*,work.title,work.platform,work.original_category,
                work.unified_category,work.tags_json FROM reference_market_links link
                JOIN market_works work ON work.id=link.work_id WHERE link.reference_id=?""",
                (reference_id,),
            ).fetchone()
        if not link:
            return None
        item = _json_row(link, "tags_json")
        detail = self.work_detail(item["work_id"])
        item["current"] = detail["history"][0] if detail["history"] else None
        item["history"] = detail["history"]
        return item


def _text_similarity(left: str, right: str) -> float:
    def grams(text: str) -> set[str]:
        normalized = re.sub(r"\s+", "", text)
        return {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}

    a, b = grams(left), grams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))
