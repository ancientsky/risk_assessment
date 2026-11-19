# 階段四：產出結構化評估 JSON

根據前面的新聞、查證筆記與證據筆記，依方法撰寫完整之評估 JSON（符合所附 schema）。

規則：
- `sources` 只能使用「來源登錄表」中列出的代碼與網址；不得新增網址。若某事實的來源不在登錄表內，請刪除該事實或列入限制。
- 每則 `evidence`、`facts`、`stats` 等都要引用來源代碼；推論請標 `is_inference=true`。
- 依方法給予每項機率／衝擊分數與建議等級；不要為了與矩陣一致而調整分數。
- `generated_at`、`data_cutoff` 用提供之時間；`reassessment_date` 一般為 2–4 週後。
- `generator.mode` 填 "api"。
- 全部文字使用臺灣繁體中文。
