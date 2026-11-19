import json

from epi_risk_agent.cli import main
from epi_risk_agent.serve import parse_multipart


def test_validate_ok(capsys, data, tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert main(["validate", str(p)]) == 0
    out = capsys.readouterr().out
    assert "整體風險（計算）：低" in out


def test_validate_errors_and_schema(tmp_path, data):
    data["claims"][0]["evidence"] = []
    p = tmp_path / "a.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert main(["validate", str(p)]) == 1
    p.write_text("{}", encoding="utf-8")
    assert main(["validate", str(p)]) == 2


def test_render_writes_html(tmp_path, data):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "r.html"
    assert main(["render", str(p), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_multipart_parser():
    body = (b"--XX\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n\xe6\x96\xb0\xe8\x81\x9e\r\n"
            b"--XX\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.json\"\r\nContent-Type: application/json\r\n\r\n{}\r\n--XX--\r\n")
    f = parse_multipart("multipart/form-data; boundary=XX", body)
    assert f["text"][1].decode() == "新聞"
    assert f["file"] == ("a.json", b"{}")
