# 疫情風險評估 AI Agent（epi-risk-agent）

協助疾病管制與公共衛生人員處理「疫情相關新聞」的 AI 工具：上傳一則新聞（文字、PDF、網址或圖片），
Agent 會：

1. **擷取可查證陳述**，並以多來源交叉比對進行**新聞查證**（已證實／部分證實／無法證實／與官方資訊不符／過時）；
2. 依序蒐集**病原特性、國際疫情、我國現況**之證據；
3. 依疾管署《疫情報導》風險評估文章格式，並以 ECDC 2019 快速風險評估操作工具之演算法與風險矩陣，進行**我國快速風險評估**；
4. 產出**單一檔案、可離線開啟、可列印**之互動式 HTML 報告，包含建議事項與**長官下一步決策建議**。

> **注意：**本工具產出之內容為 **AI 草稿**，須經流行病學專業人員審閱後方可使用。

## 方法摘要

- **判斷與計算分離**：模型（或分析員）負責蒐集證據，逐題回答 **ECDC 2019 操作工具**之機率演算法（圖 2.1 國內感染／傳播、圖 2.2 國人境外感染＝境外移入）與衝擊演算法（圖 3），並給出文章式建議等級與信心程度，**每則評估內容與每題作答都須引用來源**；
  程式由作答推導機率（無／極低／低／中／高）與衝擊（極低／低／中／高），以 **ECDC 圖 4 風險排序矩陣**得「矩陣風險」（無～極高），並計算各項目結果（如原文章：境外移入、社區流行等列為**發生機率**之低／中／高，衝擊另列一列）、綜合研判（取最高矩陣風險）、IHR 附件二計數與信心上限。證據不足時答「不確定」，依 ECDC 預防原則取較高風險分支。
  三級對應（無／極低／低→低）與圖 2.2↔境外移入之對應為本工具之調整，見方法文件。
  建議與計算不一致時，報告**並列呈現**並提出警告，不會靜默覆寫。
- **評估表格式**沿用疾管署《疫情報導》（茲卡 2016、SFTS 2023、COVID-19 2020）：評估項目／評估內容／風險等級定義／評估結果，含分層結果（如季節、地區、族群）。
- **新聞查證**採事件型監測（EBS／EIOS）之分流與查證概念，來源分 4 級（官方衛生機關/國際組織 > 同儕審查文獻 > 主流媒體 > 社群/未知），並記錄每個來源之實際取得方式（全文／搜尋摘要／未取得）。
- **升級篩檢與交叉核對**：IHR（2005）附件二四問題；人畜共通／新興病原另以 UKHSA HAIRS 之機率與衝擊演算法交叉核對（分別報告，不併入矩陣）。
- **信心程度**：低／中／高依 ECDC Box 2 與 HAIRS 附錄 B 定義為不足／尚可／良好；依來源情形自動設上限之規則為本工具自訂。
- **決策支援**：最佳／最可能／最壞情境、升降級觸發指標、決策選項比較（優缺點、主責單位、時程）、再評估日期。

完整方法、各架構對應方式與引用見 [`docs/methodology.md`](docs/methodology.md)（含各參考文件是否實際取得原文之說明）。

## 網路需求

完整流程需能連線至：

- Claude API：`api.anthropic.com`（API 路徑；查證與證據蒐集使用 Anthropic 伺服器端之 web_search／web_fetch，由 Anthropic 端代為連線）
- Claude Code 技能路徑則由執行環境直接連線，建議允許：`www.cdc.gov.tw`、`nidss.cdc.gov.tw`、`www.who.int`、`cdn.who.int`、`iris.who.int`、`apps.who.int`、`www.ecdc.europa.eu`、`www.cdc.gov`、`www.gov.uk`、`assets.publishing.service.gov.uk`、`pubmed.ncbi.nlm.nih.gov`、`pmc.ncbi.nlm.nih.gov`、`doi.org`、`promedmail.org`，以及新聞來源網站
- 輸入為網址時，`epi-risk assess` 會由本機下載該網址

**開發環境說明**：本專案初版開發時之執行環境僅能連線 `who.int` 與 `cdc.gov.tw`；ECDC 2019 操作工具與 UKHSA HAIRS 流程其後已可連線，量表、演算法、矩陣與信心定義已依原文校正。IHR 附件二原文 PDF、Nauta 等（2025）仍未取得原文，僅依搜尋結果摘要整理（見 `docs/methodology.md` 第 1 節），**正式採用前請以原文核對**。

## 安裝

需要 Python 3.10 以上。

```bash
python -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -e ".[dev]"
```

`epi-risk serve` 只用到 Python 標準函式庫，無須額外套件。

## 使用方式

### 路徑一：Claude API 完整流程（需 API 憑證）

```bash
export ANTHROPIC_API_KEY=...        # 或以 `ant auth login` 設定之憑證
epi-risk assess news.pdf -o report.html
epi-risk assess https://example.org/news/123 -o report.html --effort high
```

- 預設模型 `claude-opus-5-5`，可用 `--model` 或環境變數 `EPI_RISK_MODEL` 調整；推理強度 `--effort`（預設 high，亦可設 `EPI_RISK_EFFORT`）。
- 使用 Anthropic 伺服器端 `web_search`／`web_fetch` 工具查證與蒐集證據；可用 `--allowed-domains who.int,cdc.gov.tw` 限縮網域。
- 預設啟用伺服器端拒答備援（`fallbacks: "default"`）；不需要時加 `--no-fallbacks`。
- 產出：`report.html`、`report.assessment.json`（評估 JSON）、`report.runlog.json`（各階段 token 用量與停止原因）。
- **來源可追溯**：報告中所有網址都由程式從 API 實際回傳之搜尋／擷取結果登錄，模型無法自行加入未取得的網址。

### 路徑二：Claude Code 技能（不需 API 金鑰）

在本專案資料夾開啟 Claude Code，直接說：

> 請用 epi-risk-assessment 技能評估這則新聞：<貼上文字、檔案路徑或網址>

技能定義於 `.claude/skills/epi-risk-assessment/SKILL.md`，與 API 管線共用同一份方法指引
（`src/epi_risk_agent/prompts/methodology.md`）。Claude 會以 WebSearch／WebFetch 查證、撰寫
`assessment.json`，再執行：

```bash
epi-risk validate examples/<事件>/assessment.json
epi-risk render   examples/<事件>/assessment.json -o examples/<事件>/report.html
```

### 其他指令

```bash
epi-risk validate assessment.json            # 檢核：錯誤→結束碼 1；不符 schema→2
epi-risk validate assessment.json --write-audit audited.json
epi-risk render assessment.json -o report.html
epi-risk serve --port 8765                   # 本機網頁介面：上傳檔案／貼上文字或網址 → 進度 → 報告
```

`serve` 亦可直接上傳已完成之 `assessment.json` 只產出報告（不需 API）；單次上傳上限 20 MB。介面預設僅綁定 127.0.0.1，未設驗證機制，請勿開放於共用網路。

## 報告內容（依序）

1. 決策摘要（整體風險等級、信心程度、重點發現、建議決策、再評估日期）
2. 長官下一步決策建議（選項比較、建議方案、主責單位、時程、觸發指標）
3. 新聞查證（各陳述之判定、證據與來源連結、整體可信度）
4. 疫情概況（數字磚、事件時序、各國病例圖、病原特性、我國現況）
5. 風險評估表（文章格式，含各項目之 ECDC 演算法路徑）＋ 互動式 ECDC 圖 4 矩陣（衝擊 4 列 × 機率 5 欄）＋「試算」功能；人畜共通／新興事件另附 HAIRS 交叉核對
6. 情境分析、IHR 附件二篩檢
7. 建議事項（可依類別／優先順序／時程篩選）
8. 限制與不確定性（含自動檢核結果）、方法說明、參考資料、免責聲明與資料截止時間

報告為單一 HTML 檔，不載入任何外部資源，支援淺色／深色主題、手機寬度與 A4 列印；等級以文字＋符號＋顏色表示，不單靠顏色。

## 範例

`examples/mers-qatar-2026/`：2026 年 11 月 WHO 公布之卡達 MERS 散發病例新聞之實際評估。

- `news.md`：新聞摘要與來源網址（非全文）
- `assessment.json`：評估 JSON（所有來源皆於製作時實際取得，取得方式逐一標註）
- `data/tcdc_travel_alert_mers_extract.json`：自疾管署旅遊疫情建議開放資料擷取之 MERS 紀錄
- `report.html`：產出之報告

該範例以 Claude Code 技能路徑製作；製作環境的網路僅能直接連線 who.int 與 cdc.gov.tw，
ECDC 月報與新聞原文僅取得搜尋摘要，已於報告「限制」中說明。

`examples/us-measles-pregnancy-2026/`：美國孕婦麻疹病例新聞之評估（非人畜共通，無 HAIRS 交叉核對）。
校正為 ECDC 圖 4 後，綜合研判由「中」改為「低」，原因記載於該報告之限制。

## 專案結構

```
src/epi_risk_agent/
  schema.py      評估 JSON 之 pydantic 模型（agent 與報告之唯一介面）
  scoring.py     確定性計算與檢核規則（矩陣、三級對應、信心上限、查證規則…）
  ingest.py      txt/md/html/pdf/網址/圖片 → 文字與 Claude 內容區塊
  agent.py       Claude API 管線（擷取 → 查證 → 證據蒐集 → 結構化評估 → 修正重試）
  render.py      評估 JSON → 自足 HTML；templates/ 內為 HTML/CSS/JS
  cli.py         epi-risk 指令；serve.py 本機網頁介面
  prompts/       方法指引與各階段提示詞（與 Claude Code 技能共用）
.claude/skills/epi-risk-assessment/   Claude Code 技能
docs/methodology.md                   方法與引用
examples/                             實例
tests/                                pytest
```

## 測試

```bash
pytest
```

API 管線以模擬（mock）客戶端測試，涵蓋請求參數、`pause_turn` 續行、來源登錄、結構化輸出被拒時之退回、JSON 修正重試與拒答處理；
**測試不會呼叫真實 API**。

## 限制

- 風險分數仍為判斷者（模型或分析員）之主觀判斷；本工具使其透明、可稽核、可重現，但不保證正確。
- 綜合研判採「各機率類項目取最高」之保守規則；風險矩陣為 ECDC 2019 圖 4，但三級對應、圖 2.2↔境外移入之對應、不確定時兩分支取高之實作為本工具之調整，詳見方法文件。
- ECDC 演算法為是非題，對連續性證據較粗略（例：「相當多人受影響」未量化）；文章式判斷與演算法結果不一致時，報告並列由審閱者裁定。
- IHR 附件二原文 PDF、Nauta 等（2025）於開發環境無法取得原文，僅依搜尋摘要確認要點；正式採用前應以原文核對。
- 網路查證品質取決於可取得之來源；查不到的資訊會標示「無法證實」或列入限制，不會補造。
- 主責單位為建議，需依實際組織分工調整。
- API 完整流程尚未以真實 API 金鑰端對端執行過（開發環境無金鑰），僅以模擬客戶端測試。
