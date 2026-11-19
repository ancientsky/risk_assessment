# assessment.json 欄位說明

正式定義見 `src/epi_risk_agent/schema.py`（pydantic）。可用下列指令輸出 JSON Schema：

```bash
python -c "import json; from epi_risk_agent.schema import llm_output_schema; print(json.dumps(llm_output_schema(), ensure_ascii=False, indent=1))"
```

`audit` 欄位由程式重算，輸入值一律忽略，**不要填寫**。

## 頂層

| 欄位 | 說明 |
|---|---|
| `report_title` | 報告標題 |
| `generated_at` / `data_cutoff` | ISO 8601，含時區（例：`2026-11-19T11:40:00+08:00`） |
| `reassessment_date` | `YYYY-MM-DD`，須晚於產出日 |
| `generator` | `mode`（api／claude-code-skill／manual）、`model`、`notes` |
| `event` | 事件、危害、地點、類型、`news_source_id`、新聞摘要、與臺灣相關性、分流 |
| `sources[]` | 來源登錄（見下） |
| `claims[]` | 新聞陳述與查證 |
| `news_credibility` | 建議可信度與理由 |
| `pathogen` | 病原摘要與 `facts[]`（label/value/source_ids） |
| `international` | `summary[]`、`stats[]`（數字磚）、`timeline[]`、`time_series[]`、`country_counts[]`、`external_assessments[]` |
| `taiwan` | `notifiable_category` 與 `surveillance／laboratory／vectors_hosts／border_travel／healthcare` 各為評估內容清單 |
| `risk_items[]` | 評估項目（見下） |
| `overall` | 建議等級、綜合研判文字、3–5 項重點發現 |
| `ihr_annex2` | 角度說明、是否一律通報疾病、四問題 |
| `scenarios[]` | 最佳／最可能／最壞 |
| `recommendations[]` | 建議事項 |
| `decision` | 決策問題、選項（恰 1 項 `recommended: true`）、建議理由、觸發指標 |
| `limitations[]` | 限制與不確定性 |

## sources[]

```json
{"id": "S2", "url": "https://www.who.int/...", "title": "...", "publisher": "World Health Organization",
 "published_date": "2026-11-13", "accessed_date": "2026-11-19", "tier": 1, "retrieval": "全文",
 "is_news_item": false, "note": null}
```
- `tier`：1 官方衛生機關／國際組織、2 同儕審查文獻、3 主流媒體、4 社群／未知。
- `retrieval`：全文／搜尋摘要／未取得——依**本次實際**取得情形填寫。
- 被查證之新聞本身：`is_news_item: true`，並以 `event.news_source_id` 指向它。

## claims[]

```json
{"id": "C1", "text": "…", "importance": "關鍵", "verdict": "已證實", "verdict_reason": "…",
 "evidence": [{"source_id": "S2", "stance": "支持", "quote_or_summary": "\"原文短引\""}]}
```
- `verdict`：已證實／部分證實／無法證實／與官方資訊不符／過時。
- `stance`：支持／反駁／背景。規則：「已證實」「部分證實」需 ≥1 個具網址、非新聞本身、且發布者不同之「支持」來源；「與官方資訊不符」需第 1 級「反駁」來源。

## risk_items[]

```json
{"id": "R1", "name": "境外移入風險", "kind": "機率", "question": "未來 3 個月內…？",
 "evidence": [{"text": "…", "source_ids": ["S2"], "is_inference": false}],
 "level_definitions": {"低": "…", "中": "…", "高": "…"},
 "probability": 1, "probability_rationale": "…", "impact": null,
 "proposed_level": "低",
 "strata": [{"name": "高暴露職業族群", "probability": 2, "proposed_level": "低"}],
 "confidence": "中", "confidence_reason": "…", "hairs_questions": []}
```
- `kind`：「機率」（需 `probability`；`impact` 留 null 時沿用衝擊項目）或「衝擊」（需 `impact`）。
- `proposed_level`：機率類項目＝**發生機率**之低／中／高（1–2 低、3 中、4–5 高，與原文章一致，不含衝擊）；衝擊項目＝衝擊之低／中／高。
- 程式另計算「矩陣風險（機率×衝擊）」與報告並列；綜合研判＝各機率類項目最高之矩陣風險。
- 分層 `strata[].proposed_level` 同理：機率類項目之分層代表分層機率，衝擊項目之分層代表分層衝擊。
- 至少一個機率類與一個衝擊項目。
- `hairs_questions`：人畜共通／新興病原時填寫（question／answer 是‧否‧不確定／rationale／source_ids）。

## 其他列舉值
- 建議類別：監測通報、邊境檢疫、醫療整備、實驗室檢驗、病媒或動物防治、風險溝通、跨部會與國際合作
- 優先：高／中／低；時程：24小時／1週／1個月
- IHR 問題 key：`serious_impact`、`unusual_unexpected`、`international_spread`、`travel_trade_restriction`
