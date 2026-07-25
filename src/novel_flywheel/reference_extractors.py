import io
import ipaddress
import socket
import zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from pypdf import PdfReader


MAX_BYTES = 10 * 1024 * 1024


def extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError("DOCX document is invalid") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("DOCX document has no extractable text")
    return "\n\n".join(paragraphs)


def extract_pdf(data: bytes) -> str:
    try:
        pages = [page.extract_text().strip() for page in PdfReader(io.BytesIO(data)).pages]
    except Exception as exc:
        raise ValueError("PDF document is invalid or has no extractable text") from exc
    text = "\n\n".join(page for page in pages if page)
    if not text:
        raise ValueError("PDF document has no extractable text; scanned PDF OCR is not supported")
    return text


class _ArticleParser(HTMLParser):
    BLOCKS = {"p", "article", "section", "h1", "h2", "h3", "h4", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.current: list[str] = []
        self.blocks: list[str] = []
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "form"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCKS and self.current:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKS:
            self._flush()
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "form"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        value = " ".join(data.split())
        if self.in_title and value:
            self.title.append(value)
        elif value:
            self.current.append(value)

    def _flush(self) -> None:
        value = "".join(self.current).strip()
        if value:
            self.blocks.append(value)
        self.current.clear()

    def result(self) -> dict:
        self._flush()
        return {"title": "".join(self.title).strip(), "text": "\n\n".join(self.blocks)}


def _is_public_host(host: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if not address.is_global:
            return False
    return bool(addresses)


def fetch_public_url(url: str, *, transport=None) -> dict:
    current = url
    with httpx.Client(timeout=20, transport=transport, follow_redirects=False) as client:
        for _ in range(5):
            parsed = urlparse(current)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or not _is_public_host(parsed.hostname):
                raise ValueError("URL must resolve to a public HTTP/HTTPS destination")
            with client.stream("GET", current, headers={"User-Agent": "NovelFlywheel/1.0"}) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("URL redirect has no destination")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(value in content_type for value in ("text/html", "text/plain")):
                    raise ValueError("URL content type is not supported")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("URL response exceeds 10 MB")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                body = b"".join(chunks).decode(encoding, errors="replace")
                if "text/plain" in content_type:
                    return {"title": parsed.path.rsplit("/", 1)[-1] or parsed.hostname, "text": body.strip(), "url": current}
                parser = _ArticleParser()
                parser.feed(body)
                result = parser.result()
                if not result["text"]:
                    raise ValueError("Web page has no extractable article text")
                return {**result, "url": current}
    raise ValueError("URL exceeded the redirect limit")
