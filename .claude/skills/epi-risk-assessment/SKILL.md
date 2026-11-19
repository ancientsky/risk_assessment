---
name: epi-risk-assessment
description: 對使用者提供的疫情新聞（文字、PDF、網址或圖片）進行查證與臺灣快速風險評估，產出 assessment.json 與互動式 HTML 報告（含建議事項與長官決策建議）。適用於「評估這則疫情新聞」「這則新聞對臺灣風險多高」「幫我做快速風險評估報告」等請求。不需 ANTHROPIC_API_KEY，以 Claude Code 內建 WebSearch／WebFetch 執行。
---

# 疫情新聞查證與快速風險評估（Claude Code 技能）

本技能讓你在 Claude Code 內扮演 `epi_risk_agent` 的 API 管線：你負責蒐集證據並做逐項判斷（附引用），
程式負責確定性計算（ECDC 演算法推導、ECDC 圖 4 矩陣、WHO 2012 圖 3a 矩陣、三級對應、綜合研判與綜合評估、HAIRS 交叉核對、IHR 計數、信心上限、一致性檢核）並產出報告。

## 開始前必讀

1. 讀取方法指引（與 API 管線共用，唯一版本）：`src/epi_risk_agent/prompts/methodology.md`
2. 讀取欄位說明：`.claude/skills/epi-risk-assessment/references/schema-guide.md`
3. 參考完整範例：`examples/mers-qatar-2026/assessment.json`（及其 `news.md`）
4. 確認工具可用：`epi-risk --help`（若未安裝：`pip install -e .`）

## 流程

建立工作資料夾 `examples/<事件代稱>/`（或使用者指定位置），依序：

### 步驟 1：讀入新聞與分流
- 檔案：用 Read 讀取（PDF 用 `pages` 參數；圖片直接讀）。網址：用 WebFetch。
- 將新聞**摘要與來源網址**存為 `news.md`（不要整篇複製受著作權保護之原文；可短引）。
- 擷取 3–10 則可查證陳述，標「關鍵／次要」；決定分流（進行完整評估／持續監測／不需處理）。

### 步驟 2：多來源查證（WebSearch → WebFetch）
- 每則陳述至少嘗試 1 個官方第一手來源（WHO DON、事件所在國衛生部、ECDC、疾管署）。
- 能讀全文就用 WebFetch 讀全文；WebFetch 摘要可能改寫原文，**引文要逐字**時，若主機可連線，用 `curl` 下載原頁後以文字比對確認。
- 每個來源記錄：網址、發布者、發布日期、取用日期、等級（1–4）、取得方式（全文／搜尋摘要／未取得）。

### 步驟 3：蒐集我國情境
依方法第 2 節順序：病原特性 → 國際疫情 → 我國現況。疾管署常用頁面：
- 疾病介紹與專區（cdc.gov.tw「傳染病介紹」）
- 旅遊疫情建議開放資料：`https://www.cdc.gov.tw/CountryEpidLevel/ExportJSON`（全部歷史紀錄；各國現行等級取最新一筆）
- 國際重要疫情列表、新聞稿、致醫界通函、傳染病防治工作手冊、感染管制指引

### 步驟 4：撰寫 assessment.json
- 依 schema 撰寫（`generator.mode` 填 `"claude-code-skill"`，`model` 填你目前的模型 ID）。
- 每則評估內容引用來源代碼；推論標 `is_inference: true`；查不到的資料寫入 `limitations`，不得補造。
- 機率與衝擊**逐題回答 ECDC 2019 演算法**（`ecdc`：境外移入用圖 2.2，國內傳播類用圖 2.1，衝擊用圖 3；高風險族群以 `strata` 或另立項目分別作答），程式推導分數（機率 0–4、衝擊 1–4）並查 ECDC 圖 4 矩陣。證據不足時答「不確定」，程式依預防原則取較高風險分支。
- 機率類項目之 `proposed_level` 是依本項目風險等級定義所作之**文章式判斷**，只代表發生機率（如原文章），衝擊另列；它與 ECDC 推導結果不同時，報告並列，**不要為了一致而改動作答或判斷**。
- 人畜共通／新興病原：另填頂層 `hairs`（UKHSA HAIRS 機率 Q1–Q10、衝擊 Q1–Q12），作為交叉核對，不併入矩陣。
- 另填頂層 `who_rra`（WHO 2012 矩陣之並行評估：風險問題、依表 7／表 8 判斷之可能性與後果、必要時之族群）。程式產出「綜合評估」比較表（綜合等級＝ECDC 2019），若各架構結果不同，須於 `overall.synthesis_note` 說明差異與審閱者應權衡之處。

### 步驟 5：驗證與產出
```bash
epi-risk validate examples/<事件代稱>/assessment.json
epi-risk render   examples/<事件代稱>/assessment.json -o examples/<事件代稱>/report.html
```
- `validate` 有「錯誤」時必須修正（例如引用不存在的來源、「已證實」缺獨立來源）。
- 「警告」逐一檢視：屬實際資料缺口者（如未引證之資料缺口說明）可保留並於限制中說明。

### 步驟 6：回報
向使用者說明：整體風險（計算結果與你的建議是否一致）、信心程度、新聞可信度、建議決策、
主要資料缺口，以及**哪些來源只取得搜尋摘要或無法連線**（列出主機名稱）。

## 網路受限時
若 WebFetch／curl 對某主機失敗（例如 DNS 無法解析或代理拒絕），**不要改用記憶中的內容**：
- 改找可連線的官方替代來源；
- 僅能取得搜尋結果摘要者，`retrieval` 填「搜尋摘要」並在 `note` 說明；
- 在 `limitations` 與回報中列出無法連線之主機。

## 實務提示
- `www.cdc.gov` 會拒絕偽裝成瀏覽器的 User-Agent（回 403 Access Denied），請用 curl 預設 User-Agent。其頁面上的表格數字多由資料檔載入（例如麻疹：`/wcms/vizdata/measles/measles_hosp.json`），頁面文字抓不到時改讀資料檔。
- 疾管署網站之 `/File/Get/...` 附件連結以 curl 下載可能回傳網頁而非檔案；取不到時來源標示為僅讀得清單頁，並列入限制。
