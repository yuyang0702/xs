import io
import zipfile

import httpx
import pytest

from novel_flywheel.reference_extractors import extract_docx, extract_pdf, fetch_public_url


def test_extracts_docx_paragraphs_with_stdlib() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>',
        )
    assert extract_docx(stream.getvalue()) == "第一段\n\n第二段"


def test_rejects_private_url_before_request() -> None:
    with pytest.raises(ValueError, match="public"):
        fetch_public_url("http://127.0.0.1/private")


def test_extracts_public_html_and_ignores_scripts(monkeypatch) -> None:
    monkeypatch.setattr("novel_flywheel.reference_extractors._is_public_host", lambda _host: True)
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        text="<html><title>标题</title><script>bad()</script><p>第一段。</p><p>第二段。</p></html>",
    ))
    result = fetch_public_url("https://example.com/story", transport=transport)
    assert result["title"] == "标题"
    assert result["text"] == "第一段。\n\n第二段。"


def test_pdf_rejects_pages_without_extractable_text() -> None:
    with pytest.raises(ValueError, match="PDF"):
        extract_pdf(b"not a pdf")
