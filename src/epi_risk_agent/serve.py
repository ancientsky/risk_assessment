"""Minimal local web UI (Python standard library only).

GET  /                 upload form
POST /api/jobs         multipart: file | text | url  (or an assessment .json to render only)
GET  /api/jobs/<id>    job status + progress log (JSON)
GET  /reports/<id>     rendered report

Binds to 127.0.0.1 by default. Intended for a single analyst's workstation;
it has no authentication - do not expose it on a shared network.
"""

from __future__ import annotations

import json
import threading
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .ingest import IngestedNews, ingest, ingest_bytes, ingest_text
from .render import render_html
from .schema import Assessment

MAX_UPLOAD = 30 * 1024 * 1024

PAGE = """<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>疫情風險評估 AI Agent</title>
<style>
:root{color-scheme:light;--bg:#f9f9f7;--card:#fff;--ink:#0b0b0b;--muted:#5d5c58;--line:#d9d8d1;--accent:#1c5cab}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0d;--card:#1a1a19;--ink:#f0efec;--muted:#b3b2aa;--line:#383835;--accent:#86b6ef}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif;line-height:1.6}
main{max-width:760px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}
label{display:block;font-weight:600;margin:10px 0 4px} textarea,input[type=url],input[type=file]{width:100%;box-sizing:border-box;font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
textarea{min-height:140px} button{font:inherit;padding:8px 18px;border-radius:8px;border:0;background:var(--accent);color:#fff;cursor:pointer;margin-top:12px}
.muted{color:var(--muted);font-size:.9rem} #log{white-space:pre-wrap;font-size:.9rem}
.warn{background:#fff6dc;color:#0b0b0b;border:1px solid #e7b84a;border-radius:8px;padding:8px 12px}
</style></head><body><main>
<h1>疫情風險評估 AI Agent</h1>
<p class="warn">產出內容為 AI 草稿，須經流行病學專業人員審閱。本介面僅供本機使用。</p>
<form class="card" id="f">
<label for="file">上傳新聞檔案（txt／md／html／pdf／圖片），或已完成之 assessment.json（僅產出報告）</label>
<input type="file" id="file" name="file">
<label for="text">或貼上新聞文字</label><textarea id="text" name="text"></textarea>
<label for="url">或輸入新聞網址</label><input type="url" id="url" name="url" placeholder="https://">
<button type="submit">開始評估</button>
<p class="muted">完整評估需設定 Claude API 憑證（ANTHROPIC_API_KEY 等），約需數分鐘。</p>
</form>
<section class="card" id="status" hidden><h2>進度</h2><div id="log" aria-live="polite"></div><p id="link"></p></section>
</main><script>
const f=document.getElementById('f');
f.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(f);
 const st=document.getElementById('status'),log=document.getElementById('log'),link=document.getElementById('link');
 st.hidden=false;log.textContent='送出中…';link.textContent='';
 const r=await fetch('/api/jobs',{method:'POST',body:fd});const j=await r.json();
 if(!r.ok){log.textContent='錯誤：'+(j.error||r.status);return;}
 const poll=async()=>{const s=await (await fetch('/api/jobs/'+j.id)).json();
  log.textContent=s.log.join('\\n');
  if(s.status==='done'){const a=document.createElement('a');a.href='/reports/'+j.id;a.textContent='開啟報告';link.replaceChildren(a);}
  else if(s.status==='error'){log.textContent+='\\n失敗：'+s.error;}
  else setTimeout(poll,2000);};
 poll();});
</script></body></html>"""


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "running"
        self.log: list[str] = []
        self.error: Optional[str] = None
        self.report: Optional[Path] = None


JOBS: dict[str, Job] = {}


def parse_multipart(content_type: str, body: bytes) -> dict[str, tuple[Optional[str], bytes]]:
    msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    out: dict[str, tuple[Optional[str], bytes]] = {}
    if not msg.is_multipart():
        return out
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            out[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return out


def _run_job(job: Job, workdir: Path, news: Optional[IngestedNews], assessment_json: Optional[bytes]) -> None:
    try:
        out = workdir / f"{job.id}.html"
        if assessment_json is not None:
            job.log.append("讀取評估 JSON 並產出報告")
            a = Assessment.model_validate(json.loads(assessment_json.decode("utf-8")))
        else:
            from .agent import RiskAgent

            agent = RiskAgent(progress=lambda stage, msg: job.log.append(f"[{stage}] {msg}"))
            result = agent.run(news)
            a = result.assessment
            (workdir / f"{job.id}.assessment.json").write_text(a.model_dump_json(indent=2), encoding="utf-8")
        out.write_text(render_html(a), encoding="utf-8")
        job.report = out
        job.status = "done"
        job.log.append("完成")
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"


def make_handler(workdir: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def log_message(self, fmt: str, *args) -> None:  # quieter console
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if self.path.startswith("/api/jobs/"):
                job = JOBS.get(self.path.rsplit("/", 1)[-1])
                if not job:
                    return self._json(404, {"error": "not found"})
                return self._json(200, {"id": job.id, "status": job.status, "log": job.log, "error": job.error})
            if self.path.startswith("/reports/"):
                job = JOBS.get(self.path.rsplit("/", 1)[-1])
                if not job or not job.report:
                    return self._send(404, "找不到報告".encode("utf-8"), "text/plain; charset=utf-8")
                return self._send(200, job.report.read_bytes(), "text/html; charset=utf-8")
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/jobs":
                return self._json(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_UPLOAD:
                return self._json(400, {"error": "請提供檔案、文字或網址（上限 30MB）"})
            fields = parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
            news: Optional[IngestedNews] = None
            assessment_json: Optional[bytes] = None
            fname, fdata = fields.get("file", (None, b""))
            text = fields.get("text", (None, b""))[1].decode("utf-8", "replace").strip()
            url = fields.get("url", (None, b""))[1].decode("utf-8", "replace").strip()
            try:
                if fname and fdata:
                    if fname.lower().endswith(".json"):
                        assessment_json = fdata
                    else:
                        news = ingest_bytes(fdata, fname, origin=fname)
                elif text:
                    news = ingest_text(text)
                elif url:
                    if not url.startswith(("http://", "https://")):
                        return self._json(400, {"error": "網址需以 http:// 或 https:// 開頭"})
                    news = ingest(url)
                else:
                    return self._json(400, {"error": "請提供檔案、文字或網址"})
            except Exception as e:  # noqa: BLE001
                return self._json(400, {"error": f"無法讀取輸入：{e}"})
            job = Job()
            JOBS[job.id] = job
            if news is not None:
                job.log.extend(f"[ingest] {w}" for w in news.warnings)
            threading.Thread(target=_run_job, args=(job, workdir, news, assessment_json), daemon=True).start()
            self._json(202, {"id": job.id})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, workdir: Path = Path("./runs")) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), make_handler(workdir))
    print(f"疫情風險評估介面：http://{host}:{port}/（Ctrl+C 結束）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
