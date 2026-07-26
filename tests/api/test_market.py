from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.market import MarketService
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import MemorySecretStore


HTML = """
<script id="market-data" type="application/json">
{"lists":[{"name":"热度榜","category":"脑洞","works":[
{"id":"one","title":"循环故事","rank":1,"likes":"1.2 万赞","summary":"第一天重新开始。","tags":["脑洞"]}
]}]}
</script>
"""


def client_for(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    db.migrate()
    references = ReferenceLibrary(db, tmp_path / "references")
    market = MarketService(db, references, fetcher=lambda _url: HTML)
    return TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", reference_library=references,
        market_service=market,
    ))


def test_market_api_refresh_dashboard_and_reference_link(tmp_path) -> None:
    client = client_for(tmp_path)
    assert client.get("/api/market/dashboard").json()["summary"]["work_count"] == 0

    refreshed = client.post("/api/market/refresh", json={"source_id": "zhihu-salt"})
    assert refreshed.status_code == 200
    assert refreshed.json()["work_count"] == 1

    reference = client.post("/api/references", json={
        "title": "循环故事", "source_type": "txt", "text": "第一天重新开始。正文。",
    }).json()
    match = client.get(f"/api/market/references/{reference['id']}/match")
    assert match.status_code == 200
    assert match.json()["status"] == "high"

    linked = client.put(f"/api/market/references/{reference['id']}/link", json={
        "work_id": "zhihu:one",
    })
    assert linked.status_code == 200
    enriched = client.get(f"/api/references/{reference['id']}").json()
    assert enriched["market_context"]["current"]["ranking_name"] == "热度榜"

    assert client.delete(f"/api/market/references/{reference['id']}/link").status_code == 204


def test_market_api_reports_refresh_failure_and_keeps_dashboard_available(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    references = ReferenceLibrary(db, tmp_path / "references")
    market = MarketService(db, references, fetcher=lambda _url: "<html>空页面</html>")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", reference_library=references,
        market_service=market,
    ))

    response = client.post("/api/market/refresh", json={"source_id": "zhihu-salt"})
    assert response.status_code == 422
    assert client.get("/api/market/dashboard").json()["refresh"]["status"] == "failed"


def test_market_api_updates_and_filters_length_type(tmp_path) -> None:
    client = client_for(tmp_path)
    client.post("/api/market/refresh", json={"source_id": "zhihu-salt"})

    changed = client.put("/api/market/works/zhihu:one/length", json={"length_type": "short"})
    assert changed.status_code == 200
    assert changed.json()["length_source"] == "user"
    assert len(client.get("/api/market/works?length_type=short").json()) == 1
    assert client.get("/api/market/dashboard?length_type=long").json()["works"] == []

    reset = client.put("/api/market/works/zhihu:one/length", json={"length_type": None})
    assert reset.status_code == 200
    assert reset.json()["length_type"] == "unknown"
