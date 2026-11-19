"""Turn the user's news input (text / markdown / HTML / PDF / URL / image) into
an ``IngestedNews`` object: extracted text plus, where useful, a native content
block (PDF ``document`` or ``image``) that can be passed straight to Claude.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_TEXT_CHARS = 200_000


@dataclass
class IngestedNews:
    kind: str  # text | html | pdf | url | image
    origin: str  # file path or URL
    text: str = ""
    title: Optional[str] = None
    media_type: Optional[str] = None
    blocks: list[dict] = field(default_factory=list)  # Claude content blocks (document / image)
    warnings: list[str] = field(default_factory=list)

    def as_content_blocks(self) -> list[dict]:
        """Content blocks for a Claude user message (native blocks first, then text)."""
        out = list(self.blocks)
        header = f"【使用者提供之新聞】來源：{self.origin}" + (f"\n標題：{self.title}" if self.title else "")
        body = self.text if self.text else "（文字擷取為空，請直接閱讀上方附件）"
        out.append({"type": "text", "text": f"{header}\n\n<news>\n{body}\n</news>"})
        return out


def html_to_text(html: str) -> tuple[str, Optional[str]]:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else None
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body or soup
        text = main.get_text("\n", strip=True)
    except ImportError:  # pragma: no cover - bs4 is a declared dependency
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = m.group(1).strip() if m else None
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text, title


def pdf_to_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _pdf_block(data: bytes) -> dict:
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                           "data": base64.standard_b64encode(data).decode("ascii")}}


def _image_block(data: bytes, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode("ascii")}}


def _truncate(n: IngestedNews) -> IngestedNews:
    if len(n.text) > MAX_TEXT_CHARS:
        n.warnings.append(f"文字超過 {MAX_TEXT_CHARS} 字元，僅保留前段；請確認重要內容未被截斷")
        n.text = n.text[:MAX_TEXT_CHARS]
    return n


def ingest_bytes(data: bytes, name: str, content_type: Optional[str] = None, origin: Optional[str] = None,
                 attach_native: bool = True) -> IngestedNews:
    origin = origin or name
    suffix = Path(name).suffix.lower()
    ctype = (content_type or mimetypes.guess_type(name)[0] or "").split(";")[0].strip().lower()
    if suffix == ".pdf" or ctype == "application/pdf":
        n = IngestedNews(kind="pdf", origin=origin, media_type="application/pdf")
        try:
            n.text = pdf_to_text(data)
        except Exception as e:  # noqa: BLE001 - report and continue with native block
            n.warnings.append(f"PDF 文字擷取失敗：{e}")
        if attach_native:
            n.blocks.append(_pdf_block(data))
        if not n.text:
            n.warnings.append("PDF 無可擷取文字（可能為掃描檔），將以 PDF 原檔交由模型判讀")
        return _truncate(n)
    if suffix in IMAGE_TYPES or ctype.startswith("image/"):
        mt = IMAGE_TYPES.get(suffix, ctype or "image/png")
        n = IngestedNews(kind="image", origin=origin, media_type=mt)
        n.blocks.append(_image_block(data, mt))
        n.warnings.append("圖片不進行本地 OCR；文字由模型直接判讀圖片")
        return n
    text = data.decode("utf-8", errors="replace")
    if suffix in (".html", ".htm") or ctype in ("text/html", "application/xhtml+xml") or re.match(r"\s*<(!doctype|html)", text, re.I):
        body, title = html_to_text(text)
        return _truncate(IngestedNews(kind="html", origin=origin, text=body, title=title, media_type="text/html"))
    title = None
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first.startswith("#"):
        title = first.lstrip("#").strip()
    return _truncate(IngestedNews(kind="text", origin=origin, text=text.strip(), title=title, media_type="text/plain"))


def fetch_url(url: str, timeout: float = 30.0) -> tuple[bytes, Optional[str]]:
    import httpx

    headers = {"User-Agent": "epi-risk-agent/0.1 (public-health rapid risk assessment)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content, r.headers.get("content-type")


def ingest(source: str, attach_native: bool = True) -> IngestedNews:
    """Ingest a local path or an http(s) URL."""
    if re.match(r"^https?://", source, re.I):
        data, ctype = fetch_url(source)
        name = source.split("?")[0].rstrip("/").split("/")[-1] or "index.html"
        n = ingest_bytes(data, name, ctype, origin=source, attach_native=attach_native)
        if n.kind in ("text", "html"):
            n.kind = "url"
        return n
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(source)
    return ingest_bytes(p.read_bytes(), p.name, origin=str(p), attach_native=attach_native)


def ingest_text(text: str, origin: str = "使用者貼上之文字") -> IngestedNews:
    return ingest_bytes(text.encode("utf-8"), "pasted.txt", "text/plain", origin=origin)
