from epi_risk_agent.ingest import ingest, ingest_bytes, ingest_text


def test_text_and_markdown(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("# 標題\n\n卡達通報 2 例 MERS。", encoding="utf-8")
    n = ingest(str(p))
    assert n.kind == "text" and n.title == "標題" and "MERS" in n.text
    blocks = n.as_content_blocks()
    assert blocks[-1]["type"] == "text" and "<news>" in blocks[-1]["text"]


def test_html_strips_scripts():
    html = b"<html><head><title>T</title><script>evil()</script></head><body><nav>menu</nav><article><p>Body text</p></article></body></html>"
    n = ingest_bytes(html, "a.html")
    assert n.kind == "html" and n.title == "T"
    assert "Body text" in n.text and "evil" not in n.text and "menu" not in n.text


def test_image_becomes_native_block():
    n = ingest_bytes(b"\x89PNG\r\n\x1a\nfake", "a.png")
    assert n.kind == "image"
    assert n.blocks[0]["type"] == "image" and n.blocks[0]["source"]["media_type"] == "image/png"


def test_pdf_attached_natively_even_if_text_fails():
    n = ingest_bytes(b"%PDF-1.4 not really a pdf", "a.pdf")
    assert n.kind == "pdf"
    assert n.blocks and n.blocks[0]["type"] == "document"
    assert n.warnings


def test_pdf_text_extraction():
    from io import BytesIO

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    n = ingest_bytes(buf.getvalue(), "blank.pdf")
    assert n.kind == "pdf" and n.blocks[0]["source"]["media_type"] == "application/pdf"


def test_pasted_text():
    n = ingest_text("新聞內容")
    assert n.text == "新聞內容" and n.origin == "使用者貼上之文字"
