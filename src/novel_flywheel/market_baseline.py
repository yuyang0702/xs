from __future__ import annotations

import json
import re
from collections import defaultdict
from statistics import median
from typing import Any

from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary


class MarketBaselineService:
    def __init__(self, db: Database, references: ReferenceLibrary) -> None:
        self.db = db
        self.references = references

    @staticmethod
    def confidence_level(sample_count: int) -> str:
        if sample_count >= 10:
            return "advisory"
        if sample_count >= 5:
            return "preliminary"
        return "insufficient"

    def list_cohorts(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT work.platform,entry.ranking_name,
                COALESCE(work.unified_category,entry.category,work.original_category,'unknown') category,
                COALESCE(work.length_type,'unknown') length_type,
                COUNT(DISTINCT work.id) sample_count,
                MIN(substr(snapshot.captured_at,1,10)) start_date,
                MAX(substr(snapshot.captured_at,1,10)) end_date
                FROM reference_market_links link
                JOIN market_works work ON work.id=link.work_id
                JOIN market_entries entry ON entry.work_id=work.id
                JOIN market_snapshots snapshot ON snapshot.id=entry.snapshot_id
                WHERE link.status='confirmed' AND snapshot.status='success'
                GROUP BY work.platform,entry.ranking_name,category,length_type
                ORDER BY sample_count DESC,work.platform,entry.ranking_name,category,length_type"""
            ).fetchall()
        return [self._cohort_row(row) for row in rows]

    def build_baseline(self, key: dict[str, str]) -> dict[str, Any]:
        required = {"platform", "ranking_name", "category", "length_type"}
        if set(key) != required or not all(str(key[name]).strip() for name in required):
            raise ValueError("市场基线范围不完整")
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT work.id work_id,link.reference_id,
                MIN(substr(snapshot.captured_at,1,10)) start_date,
                MAX(substr(snapshot.captured_at,1,10)) end_date
                FROM reference_market_links link
                JOIN market_works work ON work.id=link.work_id
                JOIN market_entries entry ON entry.work_id=work.id
                JOIN market_snapshots snapshot ON snapshot.id=entry.snapshot_id
                WHERE link.status='confirmed' AND snapshot.status='success'
                AND work.platform=? AND entry.ranking_name=?
                AND COALESCE(work.unified_category,entry.category,work.original_category,'unknown')=?
                AND COALESCE(work.length_type,'unknown')=?
                GROUP BY work.id,link.reference_id
                ORDER BY work.id""",
                (key["platform"], key["ranking_name"], key["category"], key["length_type"]),
            ).fetchall()
            references = [row["reference_id"] for row in rows]
            mechanisms = []
            if references:
                placeholders = ",".join("?" for _ in references)
                mechanisms = connection.execute(
                    f"SELECT source_id,data_json FROM learning_nodes WHERE node_type='mechanism' "
                    f"AND status!='rejected' AND source_id IN ({placeholders})",
                    references,
                ).fetchall()
        sample_count = len(rows)
        by_name: dict[str, dict[str, Any]] = defaultdict(lambda: {"sources": set(), "positions": []})
        for row in mechanisms:
            data = json.loads(row["data_json"])
            name = str(data.get("name") or "").strip()
            if not name:
                continue
            by_name[name]["sources"].add(row["source_id"])
            by_name[name]["positions"].extend(
                float(value) for value in data.get("positions", [])
                if isinstance(value, (int, float)) and 0 <= float(value) <= 100
            )
        mechanism_summary = []
        for name, data in by_name.items():
            positions = sorted(data["positions"])
            work_count = len(data["sources"])
            mechanism_summary.append({
                "name": name,
                "work_count": work_count,
                "prevalence_percent": round(work_count / max(1, sample_count) * 100, 1),
                "position_median": round(median(positions), 1) if positions else None,
                "position_range": {"start": positions[0], "end": positions[-1]} if positions else None,
            })
        mechanism_summary.sort(key=lambda item: (-item["work_count"], item["name"]))
        opening = self._opening_summary(references)
        dates = [value for row in rows for value in (row["start_date"], row["end_date"]) if value]
        return {
            "key": dict(key),
            "sample_count": sample_count,
            "confidence_level": self.confidence_level(sample_count),
            "date_range": {"start": min(dates), "end": max(dates)} if dates else None,
            "mechanisms": mechanism_summary,
            "opening": opening,
            "boundary": "仅描述已确认关联的当前本地榜单样本，不代表爆款原因或全网市场。",
        }

    def _opening_summary(self, reference_ids: list[str]) -> dict[str, Any]:
        question_count = anomaly_count = 0
        for source_id in reference_ids:
            opening = self.references.read_text(source_id)[:500]
            question_count += bool(re.search(r"[？?]|为什么|怎么会|究竟", opening))
            anomaly_count += bool(re.search(r"突然|竟然?|却|失踪|死亡|异常|不见了|消失", opening))
        count = len(reference_ids)
        return {
            "question_percent": round(question_count / max(1, count) * 100, 1),
            "anomaly_percent": round(anomaly_count / max(1, count) * 100, 1),
        }

    def _cohort_row(self, row) -> dict[str, Any]:
        key = {
            "platform": row["platform"], "ranking_name": row["ranking_name"],
            "category": row["category"], "length_type": row["length_type"],
        }
        count = int(row["sample_count"])
        return {
            "key": key, "sample_count": count,
            "confidence_level": self.confidence_level(count),
            "date_range": {"start": row["start_date"], "end": row["end_date"]},
        }
