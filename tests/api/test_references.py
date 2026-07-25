from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import MemorySecretStore


def client_for(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    references = ReferenceLibrary(db, tmp_path / "references")
    return TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", reference_library=references,
    ))


def test_reference_api_imports_lists_analyzes_and_deletes(tmp_path) -> None:
    client = client_for(tmp_path)

    created = client.post("/api/references", json={
        "title": "伤口判断", "source_type": "paste",
        "text": "血是暗红色，静脉血。插得不深，没伤到大动脉。刀还不能拔。",
    })

    assert created.status_code == 201
    source = created.json()
    assert "storage_path" not in str(source)
    assert client.get("/api/references").json()[0]["id"] == source["id"]
    assert client.get(f"/api/references/{source['id']}").status_code == 200
    assert client.get(f"/api/references/{source['id']}/content").json()["text"].startswith("血是")

    analysis = client.post(f"/api/references/{source['id']}/analyze")
    assert analysis.status_code == 200
    assert analysis.json()["result"]["analyzer"] == "local-editorial"
    assert "model_id" not in str(analysis.json())

    assert client.delete(f"/api/references/{source['id']}").status_code == 204
    assert client.get(f"/api/references/{source['id']}").status_code == 404


def test_reference_api_validates_input_and_missing_sources(tmp_path) -> None:
    client = client_for(tmp_path)

    assert client.post("/api/references", json={
        "title": "", "source_type": "paste", "text": "正文",
    }).status_code == 422
    assert client.post("/api/references", json={
        "title": "标题", "source_type": "pdf", "text": "正文",
    }).status_code == 422
    assert client.get("/api/references/deadbeef").status_code == 404


def test_document_import_endpoint_accepts_extracted_text(tmp_path) -> None:
    client = client_for(tmp_path)
    response = client.post("/api/references/import", json={
        "title": "文档", "source_type": "docx", "text": "提取后的正文",
        "source_uri": "book.docx", "warnings": [],
    })
    assert response.status_code == 201
    assert response.json()["source_type"] == "docx"
