# 方法說明：疫情新聞查證與我國快速風險評估

本文件說明本工具採用之各項架構、各架構如何對應到 `assessment.json` 欄位與確定性計算，
以及**每份參考文件在開發時是否實際取得原文**。評估者操作指引（給模型與分析員閱讀）另見
`src/epi_risk_agent/prompts/methodology.md`；本文件為設計依據與引用。

> 取得情形說明：初版開發時之網路僅允許直接連線 `who.int` 與 `cdc.gov.tw`。ECDC 2019 操作工具與 UKHSA HAIRS 流程其後已可連線，
> 本版之量表、演算法、風險矩陣與信心定義已依其原文校正（下表 F、H）；仍未取得原文者（G、I 之 PDF、J）以搜尋摘要確認要點，
> 並明示為改寫或本工具之調整。

## 1. 參考架構一覽

| # | 架構／文件 | 網址 | 取得情形 | 本工具用途 |
|---|---|---|---|---|
| A | 疾管署《疫情報導》：茲卡病毒感染症疫情現況與風險評估（2016；32(11)；DOI 10.6524/EB.20160607.32(11).001） | 使用者提供 PDF | 全文閱讀 | 風險評估表格式、表三「風險等級定義」、分層結果、表四建議、限制陳述 |
| B | 疾管署《疫情報導》：發熱伴血小板減少綜合症疫情與風險評估（2023；39(4)；DOI 10.6524/EB.202302_39(4).0001） | 使用者提供 PDF | 全文閱讀 | 疾病特有項目（境外移入感染動物、野外感染）、表一格式、綜合研判 |
| C | 疾管署《疫情報導》：國內外 COVID-19 疫情研析及風險評估（2020；36(15)；DOI 10.6524/EB.202008_36(15).0001） | 使用者提供 PDF | 全文閱讀 | 境外移入／社區流行／衝擊三面向、事件型監測於疫情偵測之角色 |
| D | WHO. Rapid Risk Assessment of Acute Public Health Events（2012；WHO/HSE/GAR/ARO/2012.1） | https://iris.who.int/server/api/core/bitstreams/53e9bf3f-55f6-412b-b90a-1ec37abd36e0/content（條目頁 https://iris.who.int/handle/10665/70810） | **已取得全文**（2026-11-19）：風險特徵化見 PDF 第 21–24 頁（印刷頁 19–22）；圖 3a 為 PDF 第 22 頁之圖片，以頁面影像判讀；表 6（含顏色圖例）、表 7、表 8、表 9 | 危害／暴露／情境評估之結構；並行之 WHO 圖 3a 風險矩陣（`who_rra`）、表 6 對應行動；信心（表 9） |
| D′ | ECDC. Operational guidance on rapid risk assessment methodology（2011 年 8 月；三篇《疫情報導》文章引用之版本） | https://www.ecdc.europa.eu/sites/default/files/media/en/publications/Publications/1108_TED_Risk_Assessment_Methodology_Guidance.pdf | **已取得全文**（2026-11-19）：矩陣為圖 2.3（PDF 第 25 頁，印刷頁 20）；機率樹圖 2.1a／2.1b、衝擊樹圖 2.2 | 僅作比較（見 4.7），**未實作** |
| E | WHO Rapid Risk Assessment Guidance v.2.1（2025-05-19） | https://www.who.int/publications/m/item/who-rapid-risk-assessment-guidance-v.2.1 | 出版品頁面已讀；PDF（cdn.who.int）未取得 | 同上；以明確風險問題、信心程度表述 |
| F | ECDC. Operational tool on rapid risk assessment methodology – ECDC 2019 | https://www.ecdc.europa.eu/sites/default/files/documents/operational-tool-rapid-risk-assessment-methodolgy-ecdc-2019.pdf | **已取得全文**（2026-11-19）：圖 2.1、2.2、3、4 為 PDF 第 15–17 頁之圖片（印刷頁碼 10–12），以頁面影像判讀；Box 2 為印刷頁碼第 7 頁文字；預防原則見第 6 頁 | 機率（圖 2.1／2.2）與衝擊（圖 3）演算法、風險排序矩陣（圖 4）、信心程度（Box 2）、不確定時之預防原則、先評估一般民眾再分族群、情境因素不計分 |
| G | Nauta M, et al. Towards more transparent risk assessment of communicable diseases – Redefining probability and impact. *Epidemiol Infect* 2025;153:e31（DOI 10.1017/S0950268825000147） | https://www.cambridge.org/core/journals/epidemiology-and-infection/article/towards-more-transparent-risk-assessment-of-communicable-diseases-redefining-probability-and-impact/401D53CACF89A13A3D24D766D7B668E4 | **未取得原文**；搜尋摘要確認主張：以數值區間表達機率、風險問題由風險管理者明確提出、不宜只以單一「低／高」概括 | 機率量表加上量化錨點；報告同時呈現機率、衝擊與等級，不只給單一標籤 |
| H | UKHSA. HAIRS risk assessment process；附錄 B（證據品質與信心）；演算法題目之可及文字版見已發表評估之附件 B、D（例：chikungunya） | https://www.gov.uk/government/publications/hairs-risk-assessment-process/hairs-risk-assessment-process ；https://www.gov.uk/government/publications/hairs-risk-assessment-process/appendix-b-assessing-the-quality-of-evidence-and-confidence-in-the-risk ；https://www.gov.uk/government/publications/hairs-risk-assessment-chikungunya-virus/qualitative-assessment-of-the-risk-that-chikungunya-virus-presents-to-the-uk-population | **已取得全文**（2026-11-19）；附錄 D 原 PDF 位於無法連線之主機，題目以上述評估之附件 B（機率 Q1–Q10）、D（衝擊 Q1–Q12）核對 | 人畜共通／新興病原之機率與衝擊演算法（交叉核對，分別報告、不併入矩陣）；信心定義（附錄 B） |
| I | International Health Regulations (2005), Annex 2 decision instrument | https://apps.who.int/gb/bd/pdf_files/IHR_2022-en.pdf（WHO 頁面所列連結） | **未取得原文**；四問題與「≥2 項為是」之門檻經多個搜尋結果一致確認 | 升級篩檢（`ihr_annex2`） |
| J | WHO 公共衛生情報／EIOS（事件型監測：訊號→分流→查證→事件） | https://www.who.int/initiatives/eios（相關課程文件位於 cdn.who.int） | **未取得原文**；搜尋摘要確認訊號、分流、查證之定義 | 新聞陳述擷取、分流、多來源查證、來源分級 |
| K | 疾管署國際旅遊疫情建議等級（三級定義與開放資料） | https://www.cdc.gov.tw/CountryEpidLevel/Index/NlUwZUNvckRWQ09CbDJkRVFjaExjUT09 | 全文已讀；開放資料已下載 | 邊境／旅遊情境證據、決策選項 |

## 2. 流程

```
新聞輸入（txt/md/html/pdf/網址/圖片）
  → [J] 分流與陳述擷取 → 多來源查證（判定＋來源分級）→ 新聞可信度
  → [A–C] 證據蒐集：病原/傳播特性 → 國際疫情 → 我國現況
  → [A–F] 逐項評估：ECDC 演算法逐題作答（機率 0–4、衝擊 1–4 由程式推導）、等級定義、文章式判斷、分層、信心程度（附引用）
  → [H] 人畜共通／新興病原：HAIRS 機率與衝擊演算法（交叉核對）
  → 確定性計算：項目結果（機率類＝發生機率三級；衝擊列＝衝擊三級）、矩陣風險（機率×衝擊）、綜合研判；信心上限；一致性與引用檢核（scoring.py）
  → [I][H] 升級篩檢；情境、觸發指標、決策選項、建議事項
  → 單一自足 HTML 報告
```

核心原則：**判斷由人或模型做並附引用；合成由程式做**。程式從不覆寫判斷者的建議等級，而是把「建議」與「計算」並列，差異列為警告交由審閱者裁定。

## 3. 對應三篇《疫情報導》的元素

| 文章元素 | 出處 | schema 欄位 | 呈現 |
|---|---|---|---|
| 證據蒐集順序：病原/傳播 → 國際疫情 → 我國現況（監測、檢驗量能、病媒/宿主、法定傳染病分類）→ 評估 → 建議 | A、B、C 結果章節順序 | `pathogen`、`international`、`taiwan.*`、`risk_items`、`recommendations` | 報告第 4、5、7 節 |
| 評估項目：境外移入、國內社區流行（評估結果＝**發生機率**；A 表三標題即「感染機率風險評估表」，材料與方法稱「以低、中、高 3 級判定發生機率及衝擊風險」） | A 表三、B 表一、C 三(一)(二) | `risk_items[kind=機率]`；結果＝`audit.items[].computed_level`（機率之三級） | 風險評估表「評估結果」欄（標示「發生機率」），旁附「矩陣風險（機率×衝擊）」 |
| 疾病特有項目（境外移入感染動物、野外感染） | B 表一 | 額外 `risk_items[kind=機率]` | 同上 |
| 衝擊（嚴重度/致死率、易感族群、疫苗與治療、防治策略、醫療量能、民眾恐慌） | A 表三衝擊列、B 四(四)、C 三(三) | `risk_items[kind=衝擊]` | 同上 |
| 評估內容（條列實證） | A 表三、B 表一 | `evidence[]`（每條附 `source_ids`） | 「評估內容」欄，含引用編號；未引用者標「未引證」 |
| 風險等級定義（低／中／高各一句） | A 表三 | `level_definitions` | 「風險等級定義」欄 |
| 分層結果（季節/地區、族群） | A 表三（南高屏流行季＝中；孕婦/胎兒＝高） | `strata[]` | 「評估結果」欄；高於整體之分層另列於決策摘要 |
| 綜合研判（唯一合併機率與衝擊之處） | B 表一末列、C 三(四) | `overall` ＋ `audit.overall_*` | 表格末列與決策摘要 |
| 限制與「將視新增實證適時調整」 | A 七 | `limitations` | 第 8 節，固定加註 |
| 建議分類：監測通報／邊境檢疫／醫療整備／病媒或動物防治／風險溝通 | A 結論、B 討論 | `recommendations[].category`（另增「實驗室檢驗」「跨部會與國際合作」） | 第 7 節可篩選 |

## 4. 機率、衝擊與矩陣（依 ECDC 2019；`algorithms.py`、`scoring.py`）

### 4.1 量表與演算法（F）
- 機率：0 無、1 極低、2 低、3 中、4 高（None／Very low／Low／Moderate／High）。
- 衝擊：1 極低、2 低、3 中、4 高（Very low／Low／Moderate／High）。
- 分數**由程式依演算法推導**：評估者在 `ecdc` 中逐題答「是／否／不確定」。
  - 圖 2.1 國內感染／傳播機率：Q1 是否有傳入途徑？否⇒無；Q2 是否可能有人類暴露？否⇒極低；Q3 人口是否高度易感？否⇒低；Q4 病原是否可能傳播？否⇒中、是⇒高。
  - 圖 2.2 國人境外感染機率：同上但無 Q1（原文註：此演算法不需傳入途徑）。
  - 圖 3 衝擊：Q5 此族群是否可能重症？否⇒極低；Q6 是否會有相當多人受影響？否⇒低；Q7 是否有有效治療與防治措施？是⇒中、否⇒高。
- **本工具之調整**：「境外移入風險」對應圖 2.2（國人於境外感染後移入），國內社區流行、院內感染、野外感染等國內傳播類項目對應圖 2.1；ECDC 原文為歐盟觀點，本工具以我國取代「Member States」。
- **不確定**：ECDC 原文：不確定性「以預防原則與比例原則處理，並在演算法中往較高風險層級移動」（第 6 頁）。本工具之實作：答「不確定」或路徑上未作答之題目，同時計算「是」「否」兩分支，取較高者，並在報告列出該題與所取分支；未作答另發警告。
- 評估者另填之 `probability`／`impact` 若與推導值不同，發出警告並並列，計算採推導值；未填 `ecdc` 時採所填分數並提示。
- ECDC 要求先評估一般民眾、再對高風險族群或不同地區分別評估：以 `strata`（可各附 `ecdc`／`ecdc_impact`）或另立項目表達。公眾關注、媒體與政治壓力等情境因素依原文另行說明、不計分。

### 4.2 風險矩陣（版本 `ecdc-2019-fig4`，即 ECDC 圖 4）

| 衝擊＼機率 | 無 None | 極低 Very low | 低 Low | 中 Moderate | 高 High |
|---|---|---|---|---|---|
| **極低 Very low** | 無 | 極低 | 低 | 低 | 中 |
| **低 Low** | 無 | 低 | 低 | 中 | 中 |
| **中 Moderate** | 無 | 低 | 中 | 中 | 高 |
| **高 High** | 無 | 中 | 中 | 高 | 極高 |

測試 `test_matrix_equals_ecdc_figure4` 逐格（20 格）比對。

### 4.3 項目結果、矩陣風險與綜合研判（保留兩種尺度）
- 以下三級對應為**本工具之調整**（ECDC 無此步驟），用以對應疾管署文章之低／中／高：
- **機率類項目之評估結果**＝發生機率對應三級：0–2（無／極低／低）低、3 中、4 高（`PROBABILITY_TO_LEVEL3`）。這與三篇文章一致：境外移入、社區流行、野外感染等列只判定發生機率，衝擊另列一列。分層（`strata`）同理。
- **衝擊項目之評估結果**＝衝擊分數對應三級：1–2 低、3 中、4 高。
- **矩陣風險**（另列、標示「矩陣風險（機率×衝擊）」）：每一機率類項目及其分層以機率 × 衝擊（未填 `impact` 時沿用衝擊項目分數，多個衝擊項目取最大）查 4.2 矩陣（ECDC 圖 4），得六級（無～極高）；對應三級為無／極低／低→低、中→中、高／極高→高。矩陣圖上的項目位置即矩陣風險。
- **綜合研判**＝各機率類項目矩陣風險之最大者，再對應三級（並記錄由哪一項決定）。這是唯一合併機率與衝擊之處。
- 任何分層之矩陣風險高於綜合研判時，檢核產生提示，並在決策摘要中列出。
- 評估者之文章式判斷（`proposed_level`，依各項目之風險等級定義）與演算法推導結果不同時，兩者並列並發出警告；例如 MERS 衝擊：ECDC 圖 3「可能重症、但受影響人數不多」⇒ 低，文章式判斷因致死率高、無疫苗與特效藥評為高。

迴歸測試（`tests/test_scoring.py::test_article_*`）以低＝2、中＝3、高＝4 編碼三篇文章之表格，並檢查項目層級與綜合結果：
- COVID-19（2020）：境外移入 高、社區流行 中、衝擊 高 → 綜合 高（圖 4：高×高＝極高→高）✔
- SFTS（2023）：人類病例移入 低、感染動物移入 中、社區流行 低、野外感染 中、衝擊 中 → 綜合 中（圖 4：中×中＝中）✔
- 茲卡（2016）：境外移入 高；社區流行分層 非流行季 低／南高屏流行季 中／中北部流行季 低；衝擊分層 孕婦胎兒 高／一般民眾 低 ✔（文章未給單一綜合等級）

若改以矩陣風險作為各項目結果，SFTS「人類病例移入」（機率低、衝擊中 → 圖 4 為中）與 COVID-19「社區流行」（機率中、衝擊高 → 圖 4 為高）都會與文章不符，故項目結果採機率、矩陣風險僅並列參考。

### 4.4 信心程度（F 之 Box 2、H 之附錄 B）與上限
信心三級之定義採原文：
- 高＝良好（Good）：證據品質大多良好——多個可靠來源、已查證、專家意見一致、有類似事件之經驗。
- 中＝尚可（Satisfactory）：證據品質大多尚可——證據品質適當（含僅見於灰色文獻但一致之結果）、可靠來源、以類比推論、專家間意見一致或兩位可信專家之意見。
- 低＝不足（Unsatisfactory）：證據品質大多不足——證據少且品質差、專家間不確定或意見衝突、無類似事件之經驗。

判斷者先給「高／中／低」與理由，程式再依來源情形設上限（**上限規則為本工具自訂**）：
- 評估內容全未引證 → 低；
- 引用來源僅單一發布者（不含新聞本身）→ 中；
- 無第 1、2 級來源（僅媒體或未知）→ 低；
- 全部來源僅取得搜尋摘要或未取得全文 → 中；
- 超過 30% 評估內容未引證 → 中。
整體信心 = 各項目有效信心之最小值；若有關鍵陳述未通過查證規則，再設上限「中」。

### 4.5 並行評估：WHO 2012 風險矩陣（D）
WHO 手冊以「危害評估、暴露評估、情境評估」為基礎進行風險特徵化（risk characterization），在無量化模型時由團隊專家意見判定，並以風險矩陣輔助（第 19 頁）。WHO 明言：「When applying the matrix, the definitions of likelihood and consequence can be refined to fit with the national or sub-national context in each country.」**WHO 無題目樹**：本工具中可能性與後果為評估者依表 7、表 8 之判斷（`who_rra`），報告中明示。

圖 3a（PDF 第 22 頁；版本 `who-2012-fig3a`；顏色依表 6 之顏色圖例：綠＝Low risk、黃＝Moderate risk、橙＝High risk、紅＝Very high risk——表 6 本身即附色塊，故此對應出自原文，非推論）：

| 可能性＼後果 | Minimal 極輕微 | Minor 輕微 | Moderate 中度 | Major 重大 | Severe 嚴重 |
|---|---|---|---|---|---|
| **Almost certain 幾乎確定** | 低 | 中 | 高 | 極高 | 極高 |
| **Highly likely 很可能** | 低 | 中 | 高 | 極高 | 極高 |
| **Likely 可能** | 低 | 中 | 高 | 高 | 極高 |
| **Unlikely 不太可能** | 低 | 低 | 中 | 高 | 高 |
| **Very unlikely 極不可能** | 低 | 低 | 中 | 高 | 高 |

測試 `test_who_matrix_equals_figure_3a` 逐格（25 格）比對。三級對應（極高→高）為本工具之規則。

表 6「How to read Figures 3a and 3b」：
- Low risk：Managed according to standard response protocols, routine control programmes and regulation (e.g. monitoring through routine surveillance systems)
- Moderate risk：Roles and responsibility for the response must be specified. Specific monitoring or control measures required (e.g. enhanced surveillance, additional vaccination campaigns)
- High risk：Senior management attention needed: there may be a need to establish command and control structures; a range of additional control measures will be required some of which may have significant consequences
- Very high risk：Immediate response required even if the event is reported out of normal working hours. Immediate senior management attention needed (e.g. the command and control structure should be established within hours); the implementation of control measures with serious consequences is highly likely

表 7「Estimates of likelihood definitions」：
- Almost certain：Is expected to occur in most circumstances (e.g. probability of 95% or more)
- Highly likely：Will probably occur in most circumstances (e.g. a probability of between 70% and 94%)
- Likely：Will occur some of the time (e.g. a probability of between 30% and 69%)
- Unlikely：Could occur some of the time (e.g. a probability of between 5% and 29%)
- Very unlikely：Could occur under exceptional circumstances (e.g. a probability of less than 5%)

表 8「Estimates of consequences definitions」（各級四項：族群影響／活動與服務干擾／額外防治措施／成本）：
- Minimal：Limited impact on the affected population；Little disruption to normal activities and services；Routine responses are adequate and there is no need to implement additional control measures；Few extra costs for authorities and stakeholders
- Minor：Minor impact for a small population or at-risk group；Limited disruption to normal activities and services；A small number of additional control measures will be needed that require minimal resources；Some increase in costs for authorities and stakeholders
- Moderate：Moderate impact as a large population or at-risk group is affected；Moderate disruption to normal activities and services；Some additional control measures will be needed and some of these require moderate resources to implement；Moderate increase in costs for authorities and stakeholders
- Major：Major impact for a small population or at-risk group；Major disruption to normal activities and services；A large number of additional control measures will be needed and some of these require significant resources to implement；Significant increase in costs for authorities and stakeholders
- Severe：Severe impact for a large population or at-risk group；Severe disruption to normal activities and services；A large number of additional control measures will be needed and most of these require significant resources to implement；Serious increase in costs for authorities and stakeholders

表 9「Level of confidence in two risk assessments」以兩例說明信心：例 A（醫院醫師之詳細臨床描述、監測資料、快速應變團隊流行病學調查、同儕審查文獻等）屬中至高信心；例 B（僅見未經其他來源證實之報紙報導）屬極低或低信心。信心可用「very low 至 very high」之描述量表表達（第 23 頁）。本工具之信心三級仍以 ECDC Box 2／HAIRS 附錄 B 定義，WHO 表 9 之例與其一致。

註：WHO 手冊正文（第 19 頁）稱可能性見「Table 6」、後果見「Table 7」，但實際編號為表 7、表 8（表 6 為讀圖說明）；本文件以實際表號引用。

### 4.6 綜合評估（`scoring.synthesize`）
使用單位決定以 ECDC 2019 為主要方法、WHO 2012 並行、HAIRS 交叉核對，最後產出單一綜合評估：
- **比較表**：每一架構一列（ECDC 2019 一般民眾＋矩陣風險高於整體之分層；WHO 2012 一般民眾＋族群；HAIRS 機率與衝擊分列、明示無合併等級；疫情報導式判斷＝`overall.proposed_level`），欄位為原生結果、三級對應、取得方式（演算法推導或評估者判斷）、主要決定因素。
- **綜合等級**＝ECDC 2019 之綜合研判（使用單位之決定）。
- **一致性**（一般民眾層級之 ECDC、WHO、文章式判斷）：全相同＝一致；最高與最低相差一級＝部分一致；相差兩級（低對高）＝不一致；並列出何者不同、較高或較低。
- **審慎上限**＝上述一般民眾層級三者之最高三級（本工具之規則）。族群結果與 HAIRS 分項不納入上限，但若高於綜合等級，列為「注意事項」。
- 有任何差異或注意事項時，`overall.synthesis_note`（評估者說明差異原因與應權衡之處）為必填，未填則警告；報告於比較表下方呈現。
- 決策摘要之綜合等級徽章維持 ECDC 結果，下方以一行列出「ECDC｜WHO｜HAIRS｜文章式判斷｜審慎上限」。

### 4.7 三個矩陣之比較（皆讀過原文）

| | WHO 2012 圖 3a | ECDC 2011 圖 2.3 | ECDC 2019 圖 4（本工具主要方法） |
|---|---|---|---|
| 機率／可能性 | 5 級：Very unlikely～Almost certain（表 7 附機率區間） | 4 級：Very low、Low、Moderate、High（無「None」） | 5 級：None、Very low、Low、Moderate、High |
| 衝擊／後果 | 5 級：Minimal～Severe（表 8 四面向） | 5 級：Very low～Very high | 4 級：Very low～High |
| 如何得分 | 評估者判斷（無題目樹） | 題目樹（機率圖 2.1a：暴露、易感、高度傳染力；圖 2.1b 另問傳入其他會員國之途徑；衝擊圖 2.2：重症、相當多人、高度傳染力、有效治療與防治） | 題目樹（圖 2.1／2.2：傳入途徑、暴露、易感、傳播；圖 3：重症、相當多人、有效治療與防治） |
| 輸出 | Low、Moderate、High、Very high | Very low～Very high risk | None～Very high risk |
| 特性 | 偏重後果：極不可能 × 中度後果即為中；極不可能 × 重大後果即為高 | 高 × 高＝High；Very high 僅見於極高衝擊 × 高機率 | 高 × 高＝Very high；極低機率 × 高衝擊＝中 |

三篇《疫情報導》文章引用的是 WHO 2012 手冊與 ECDC 2011 操作指引；本工具則以 ECDC 2019 版計算（使用單位之決定），WHO 2012 並行呈現，ECDC 2011 僅作比較、未實作。

## 5. 新聞查證（J）

- 判定：已證實／部分證實／無法證實／與官方資訊不符／過時。
- 來源分級：1 官方衛生機關／國際組織 ＞ 2 同儕審查文獻 ＞ 3 主流媒體（ProMED 歸此級）＞ 4 社群／未知。
- 取得方式：全文／搜尋摘要／未取得（每個來源必填，反映**本次**實際取得情形）。
- 確定性規則（`scoring.audit_claim`）：
  - 「已證實」「部分證實」需 ≥1 個「支持」來源：具網址、非新聞本身、發布者與新聞不同、且非「未取得」。否則列為**錯誤**並建議改為「無法證實」。
  - 「已證實」僅由第 3、4 級來源支持 → 警告。
  - 「與官方資訊不符」需 ≥1 個第 1 級「反駁」來源。
  - 「過時」需 ≥1 個具網址之來源。
- 新聞可信度（程式計算）：關鍵陳述之有效判定（未通過規則者以建議判定計）取平均分數（已證實 1、部分證實 0.6、過時 0.4、無法證實 0.25、不符 0）；≥0.8 高、≥0.5 中、其餘低；任一關鍵陳述與官方不符 → 低；新聞來源屬第 4 級者上限為中。

## 6. 升級篩檢

- **IHR 附件二（I）**：四問題（嚴重影響、不尋常或非預期、國際傳播顯著風險、旅行或貿易限制顯著風險）。程式計算「是」之數目，≥2 即達門檻；天花、野生型小兒麻痺、新亞型人類流感、SARS 一律通報。我國非 WHO 會員，本工具以「事件發生國之角度」套用，作為我國研判升級之參考，並於報告中說明角度。
- **人畜共通／新興病原（H）**：UKHSA HAIRS 之兩個演算法——機率（Q1–Q10：已知人類疾病？人畜共通潛勢？人類中地方性流行？動物中地方性流行？傳入動物之途徑？有效減緩措施？環境支持病媒？人類暴露？高度易感？高度傳染力？）與衝擊（Q1–Q12：人傳人？人畜共通或病媒傳播？宿主或病媒存在？人群易感？重症（高風險族群）？高度傳染力？相當多人受影響？有效介入？），結果分別為極低～高、極低～極高。依 HAIRS「分別報告機率與衝擊」之作法，本工具將其作為 ECDC 結果之交叉核對，**不併入矩陣**；不確定時依 HAIRS 預防原則（"the algorithm should be continued until a decisive answer is attained"）取較高風險分支（同 4.1 之實作）。原文之 UK 以我國取代。事件類型為「人畜共通」或「新興或不明病原」而未填 `hairs` 時，檢核提示。

## 7. 決策支援

- **情境**：最佳／最可能／最壞，各有假設、隱含等級與意涵。
- **觸發指標**：可觀察、具門檻、指明監測來源與目前狀態；至少一項升級、一項降級（缺少時警告）。
- **長官決策建議**：決策問題、2–4 個選項（優點、缺點、主責單位、時程 24 小時／1 週／1 個月、所需資源）、恰一項建議方案（無建議方案為錯誤）。
- **再評估日期**：須晚於產出日。

## 8. 報告呈現原則

- 單一 HTML 檔，CSS／JS／圖示全部內嵌，無任何外部請求（測試 `test_no_external_resources`）；可離線、可列印為 A4。
- 六級風險（無／極低／低／中／高／極高）以「文字＋圖形符號（橫槓／空心圓／實心圓／三角／菱形／方塊）＋顏色」編碼，矩陣高／極高格另加 45°／135° 斜線；不單靠顏色。矩陣版面同 ECDC 圖 4（列＝衝擊、欄＝機率）。
- 淺色／深色主題以 CSS 變數定義，並支援使用者切換；手機寬度（390px）下表格改為卡片式，無水平捲動。
- 互動：矩陣點選顯示項目證據（可鍵盤操作）、情境試算（明確標示「試算」，不影響正式結果，且與 Python 使用同一矩陣資料）、建議事項篩選、圖表懸停提示與表格檢視。

## 9. 已知限制

- G（Nauta 等 2025）、I（IHR 附件二原文 PDF）、J（WHO EIOS 課程文件）仍未取得原文；WHO 2012 可能性與後果無題目樹，屬評估者判斷；IHR 四問題依多個搜尋結果一致之內容。
- 本工具之調整（非原文）：圖 2.2↔境外移入、圖 2.1↔國內傳播類項目之對應；六級矩陣與機率／衝擊分數對應三級之規則；不確定時「兩分支取高」之實作；信心上限規則；HAIRS 以我國取代 UK。
- ECDC 演算法之是非題對連續性證據較粗略（例：Q6「相當多人受影響」未量化，HAIRS 附註 4 亦指出「substantial」未量化），作答需判斷並附理由。
- 機率與衝擊分數仍為主觀判斷；本工具使其**透明、可稽核、可重現**，但不保證判斷正確。
- 綜合研判採「最大值」規則，屬保守設計；若使用單位偏好其他合成方式（例如加權），需修改 `scoring.audit` 並更新測試。
