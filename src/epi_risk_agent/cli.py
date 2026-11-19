"""Command line interface: ``epi-risk assess|render|validate|serve``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .render import load_assessment, render_html
from .scoring import apply_audit


def _print_issues(a) -> int:
    au = a.audit
    sev_label = {"error": "錯誤", "warning": "警告", "info": "提示"}
    for i in sorted(au.issues, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x.severity]):
        loc = f" [{i.path}]" if i.path else ""
        print(f"  {sev_label[i.severity]}｜{i.code}｜{i.message}{loc}")
    n_err = sum(1 for i in au.issues if i.severity == "error")
    n_warn = sum(1 for i in au.issues if i.severity == "warning")
    print(f"整體風險（計算）：{au.overall_computed_level}（矩陣 {au.overall_matrix_level}；評估者建議 {au.overall_proposed_level}）"
          f"；信心：{au.overall_confidence}；新聞可信度：{au.credibility_computed}")
    print(f"檢核結果：錯誤 {n_err}、警告 {n_warn}、提示 {len(au.issues) - n_err - n_warn}")
    return n_err


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        a = apply_audit(load_assessment(args.assessment))
    except ValidationError as e:
        print("JSON 不符合 schema：", file=sys.stderr)
        print(e, file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as e:
        print(f"無法讀取：{e}", file=sys.stderr)
        return 2
    n_err = _print_issues(a)
    if args.write_audit:
        Path(args.write_audit).write_text(a.model_dump_json(indent=2), encoding="utf-8")
        print(f"已寫出含 audit 之 JSON：{args.write_audit}")
    return 1 if n_err else 0


def cmd_render(args: argparse.Namespace) -> int:
    try:
        a = load_assessment(args.assessment)
    except ValidationError as e:
        print("JSON 不符合 schema，無法產出報告：", file=sys.stderr)
        print(e, file=sys.stderr)
        return 2
    Path(args.output).write_text(render_html(a), encoding="utf-8")
    n_err = _print_issues(apply_audit(a))
    print(f"已產出報告：{args.output}")
    return 1 if (n_err and args.strict) else 0


def cmd_assess(args: argparse.Namespace) -> int:
    from .agent import AgentConfig, AgentError, RiskAgent
    from .ingest import ingest

    def progress(stage: str, msg: str) -> None:
        print(f"[{stage}] {msg}", file=sys.stderr, flush=True)

    cfg = AgentConfig()
    if args.model:
        cfg.model = args.model
    if args.effort:
        cfg.effort = args.effort
    if args.no_fallbacks:
        cfg.use_fallbacks = False
    if args.no_structured_output:
        cfg.structured_output = False
    if args.allowed_domains:
        cfg.allowed_domains = [d.strip() for d in args.allowed_domains.split(",") if d.strip()]
    news = ingest(args.source)
    for w in news.warnings:
        progress("ingest", w)
    try:
        result = RiskAgent(config=cfg, progress=progress).run(news)
    except AgentError as e:
        print(f"評估失敗：{e}", file=sys.stderr)
        return 3
    out = Path(args.output)
    json_path = Path(args.json) if args.json else out.with_suffix(".assessment.json")
    json_path.write_text(result.assessment.model_dump_json(indent=2), encoding="utf-8")
    out.write_text(render_html(result.assessment), encoding="utf-8")
    log_path = out.with_suffix(".runlog.json")
    log_path.write_text(json.dumps(result.log, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _print_issues(result.assessment)
    print(f"已產出：{out}（評估 JSON：{json_path}；執行紀錄：{log_path}）")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .serve import serve

    serve(host=args.host, port=args.port, workdir=Path(args.workdir))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epi-risk", description="疫情風險評估 AI Agent：新聞查證、快速風險評估與互動式報告")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("assess", help="完整流程：輸入新聞（檔案或網址）→ 查證 → 評估 → HTML 報告（需 Claude API 憑證）")
    a.add_argument("source", help="新聞檔案（txt/md/html/pdf/png/jpg）或 http(s) 網址")
    a.add_argument("-o", "--output", default="report.html")
    a.add_argument("-j", "--json", help="評估 JSON 輸出路徑（預設與報告同名 .assessment.json）")
    a.add_argument("--model", help="模型（預設環境變數 EPI_RISK_MODEL 或 claude-opus-5-5）")
    a.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="推理強度（預設 high）")
    a.add_argument("--allowed-domains", help="限制網路搜尋網域，逗號分隔")
    a.add_argument("--no-fallbacks", action="store_true", help="停用伺服器端拒答備援模型")
    a.add_argument("--no-structured-output", action="store_true", help="不使用結構化輸出（改以提示詞要求 JSON）")
    a.set_defaults(func=cmd_assess)

    r = sub.add_parser("render", help="評估 JSON → 單一自足 HTML 報告")
    r.add_argument("assessment")
    r.add_argument("-o", "--output", default="report.html")
    r.add_argument("--strict", action="store_true", help="檢核有錯誤時回傳非零結束碼")
    r.set_defaults(func=cmd_render)

    v = sub.add_parser("validate", help="驗證評估 JSON 並列出檢核結果（有錯誤時結束碼 1，schema 不符為 2）")
    v.add_argument("assessment")
    v.add_argument("--write-audit", help="將重新計算之 audit 寫入此路徑")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("serve", help="啟動本機網頁介面（上傳檔案／貼上文字或網址）")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--workdir", default="./runs")
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
