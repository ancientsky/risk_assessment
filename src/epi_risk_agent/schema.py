"""Pydantic models for the assessment JSON.

This is the single contract between the evidence-gathering agent (API pipeline
or the Claude Code skill) and the deterministic scorer / renderer.

Design rule: the LLM fills in *judgments with citations* (probability and
impact scores per item, evidence bullets referencing source ids, proposed
levels). Everything that can be computed - matrix lookups, 5->3 level mapping,
overall level, IHR Annex 2 tally, confidence caps, consistency checks - is
computed by ``scoring.py`` and stored under ``audit`` (never trusted from the
LLM; ``scoring.audit()`` always recomputes it).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies (values are zh-TW because they are shown verbatim)
# ---------------------------------------------------------------------------

Level3 = Literal["低", "中", "高"]
"""Three-level scale used by the Taiwan CDC 疫情報導 articles."""

MatrixLevel = Literal["無", "極低", "低", "中", "高", "極高"]
"""Output of the ECDC (2019) Figure 4 risk-ranking matrix: None, Very low, Low, Moderate, High, Very high."""

Confidence = Literal["低", "中", "高"]
"""低／中／高 = ECDC Box 2 & HAIRS Appendix B: Unsatisfactory／Satisfactory／Good (不足／尚可／良好)."""

Verdict = Literal["已證實", "部分證實", "無法證實", "與官方資訊不符", "過時"]

Stance = Literal["支持", "反駁", "背景"]

SourceTier = Literal[1, 2, 3, 4]
"""1 = 官方衛生機關/國際組織, 2 = 同儕審查文獻, 3 = 主流媒體, 4 = 社群/未知."""

Retrieval = Literal["全文", "搜尋摘要", "未取得"]
"""How the content of a source was actually obtained in this run.

全文: the page/PDF itself was fetched and read; 搜尋摘要: only a search-engine
result / snippet was seen; 未取得: cited from another document, not retrieved.
"""

ItemKind = Literal["機率", "衝擊"]

RecCategory = Literal["監測通報", "邊境檢疫", "醫療整備", "實驗室檢驗", "病媒或動物防治", "風險溝通", "跨部會與國際合作"]

Priority = Literal["高", "中", "低"]

Timeframe = Literal["24小時", "1週", "1個月"]

IhrAnswer = Literal["是", "否", "不確定"]

EcdcAlgorithm = Literal["2.1", "2.2", "3"]
"""ECDC 2019 Figure 2.1 (domestic infection/transmission), 2.2 (our citizens infected abroad), 3 (impact)."""

SCORE_LABELS_P = {0: "無", 1: "極低", 2: "低", 3: "中", 4: "高"}  # ECDC probability: None..High
SCORE_LABELS_I = {1: "極低", 2: "低", 3: "中", 4: "高"}  # ECDC impact: Very low..High


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class Source(StrictModel):
    id: str = Field(description="來源代碼，如 S1；報告中以此引用")
    url: Optional[str] = Field(default=None, description="實際取得之網址；未取得者可為 null")
    title: str
    publisher: str = Field(description="發布機構或媒體")
    published_date: Optional[str] = Field(default=None, description="發布日期 YYYY-MM-DD（未知為 null）")
    accessed_date: Optional[str] = Field(default=None, description="取用日期 YYYY-MM-DD")
    tier: SourceTier = Field(description="1 官方衛生機關/國際組織；2 同儕審查文獻；3 主流媒體；4 社群/未知")
    retrieval: Retrieval = Field(description="本次實際取得方式：全文／搜尋摘要／未取得")
    is_news_item: bool = Field(default=False, description="是否為被查證之新聞本身")
    note: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url 必須以 http:// 或 https:// 開頭")
        return v


class EvidenceBullet(StrictModel):
    text: str = Field(description="評估內容（一句話，含數字與日期）")
    source_ids: list[str] = Field(default_factory=list, description="引用來源代碼；空白將被標記為『未引證』")
    is_inference: bool = Field(default=False, description="是否為評估者推論（非來源直接陳述）")


# ---------------------------------------------------------------------------
# Event + claims (event-based surveillance: triage -> verification)
# ---------------------------------------------------------------------------


class EventMeta(StrictModel):
    title: str = Field(description="事件標題（zh-TW）")
    hazard: str = Field(description="危害/病原（如：中東呼吸症候群冠狀病毒 MERS-CoV）")
    event_location: str
    event_type: list[Literal["人畜共通", "病媒傳播", "呼吸道", "腸道/食媒", "血液/性接觸", "新興或不明病原", "其他"]] = Field(default_factory=list)
    news_source_id: str = Field(description="新聞本身在 sources 中的代碼")
    news_summary: str = Field(description="新聞摘要（非全文）")
    taiwan_relevance: str = Field(description="與臺灣相關性（一句話）")
    triage_decision: Literal["進行完整評估", "持續監測", "不需處理"] = "進行完整評估"
    triage_reason: str = ""


class ClaimEvidence(StrictModel):
    source_id: str
    stance: Stance
    quote_or_summary: str = Field(description="來源原文短引或摘要（短引 < 125 字元）")


class Claim(StrictModel):
    id: str = Field(description="如 C1")
    text: str = Field(description="新聞中可查證之陳述（zh-TW）")
    importance: Literal["關鍵", "次要"] = "關鍵"
    verdict: Verdict
    verdict_reason: str
    evidence: list[ClaimEvidence] = Field(default_factory=list)


class NewsCredibility(StrictModel):
    proposed_level: Level3 = Field(description="評估者（LLM）建議之新聞可信度")
    reason: str


# ---------------------------------------------------------------------------
# Situation
# ---------------------------------------------------------------------------


class Fact(StrictModel):
    label: str
    value: str
    source_ids: list[str] = Field(default_factory=list)


class StatTile(StrictModel):
    label: str
    value: str
    as_of: Optional[str] = None
    note: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)


class TimelineEvent(StrictModel):
    date: str = Field(description="YYYY-MM-DD")
    label: str
    source_ids: list[str] = Field(default_factory=list)


class SeriesPoint(StrictModel):
    date: str
    value: float
    series: str = "病例數"


class CountryCount(StrictModel):
    country: str
    cases: Optional[float] = None
    deaths: Optional[float] = None
    period: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)


class PathogenProfile(StrictModel):
    summary: str
    facts: list[Fact] = Field(default_factory=list, description="病原、宿主、傳播途徑、潛伏期、可傳染期、致死率、治療、疫苗等")


class InternationalSituation(StrictModel):
    summary: list[EvidenceBullet] = Field(default_factory=list)
    stats: list[StatTile] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    time_series: list[SeriesPoint] = Field(default_factory=list)
    country_counts: list[CountryCount] = Field(default_factory=list)
    external_assessments: list[EvidenceBullet] = Field(default_factory=list, description="WHO/ECDC 等既有風險評估結論")


class TaiwanContext(StrictModel):
    notifiable_category: Optional[str] = Field(default=None, description="法定傳染病分類與通報時限")
    surveillance: list[EvidenceBullet] = Field(default_factory=list)
    laboratory: list[EvidenceBullet] = Field(default_factory=list)
    vectors_hosts: list[EvidenceBullet] = Field(default_factory=list)
    border_travel: list[EvidenceBullet] = Field(default_factory=list)
    healthcare: list[EvidenceBullet] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk items (the 評估項目 table)
# ---------------------------------------------------------------------------


class LevelDefinitions(StrictModel):
    """風險等級定義 (as in 茲卡表三), disease-specific."""

    低: str
    中: str
    高: str


class AlgAnswer(StrictModel):
    q: str = Field(description="問題代碼，如 Q2（ECDC 為 Q1–Q7；HAIRS 機率 Q1–Q10、衝擊 Q1–Q12）")
    answer: IhrAnswer = Field(description="是／否／不確定（不確定依預防原則取較高風險分支）")
    rationale: str = Field(description="一句話理由")
    source_ids: list[str] = Field(default_factory=list)


class EcdcPath(StrictModel):
    """Answers along an ECDC 2019 algorithm path; the level is derived by code."""

    algorithm: EcdcAlgorithm = Field(description="2.1 國內感染/傳播機率；2.2 國人境外感染機率（境外移入）；3 衝擊")
    answers: list[AlgAnswer]

    @field_validator("answers")
    @classmethod
    def _unique_q(cls, v: list[AlgAnswer]) -> list[AlgAnswer]:
        qs = [a.q for a in v]
        if len(qs) != len(set(qs)):
            raise ValueError("同一問題重複作答")
        return v


def _check_alg(path: Optional[EcdcPath], allowed: tuple[str, ...], where: str) -> None:
    if path is None:
        return
    if path.algorithm not in allowed:
        raise ValueError(f"{where}：此處 ECDC 演算法須為 {'/'.join(allowed)}，收到 {path.algorithm}")
    valid = {"2.1": {"Q1", "Q2", "Q3", "Q4"}, "2.2": {"Q2", "Q3", "Q4"}, "3": {"Q5", "Q6", "Q7"}}[path.algorithm]
    bad = [a.q for a in path.answers if a.q not in valid]
    if bad:
        raise ValueError(f"{where}：ECDC 圖 {path.algorithm} 無此問題 {bad}")


class Stratum(StrictModel):
    name: str = Field(description="分層名稱，如：南高屏登革熱流行季、孕婦/胎兒")
    probability: Optional[int] = Field(default=None, ge=0, le=4, description="ECDC 機率 0 無、1 極低、2 低、3 中、4 高")
    impact: Optional[int] = Field(default=None, ge=1, le=4, description="ECDC 衝擊 1 極低、2 低、3 中、4 高")
    ecdc: Optional[EcdcPath] = Field(default=None, description="此分層之 ECDC 機率（2.1/2.2）或衝擊（3）演算法路徑")
    ecdc_impact: Optional[EcdcPath] = Field(default=None, description="機率類項目之分層若有不同衝擊：ECDC 圖 3 路徑")
    proposed_level: Level3 = Field(description="此分層之評估結果（機率類項目為發生機率；衝擊項目為衝擊）")
    note: Optional[str] = None


class RiskItem(StrictModel):
    id: str = Field(description="如 R1")
    name: str = Field(description="評估項目，如：境外移入風險、國內社區流行風險、衝擊")
    kind: ItemKind = Field(description="機率類項目（有機率與衝擊）或衝擊項目（只有衝擊分數）")
    question: str = Field(description="此項目回答的風險問題（WHO/ECDC：明確的風險問題）")
    evidence: list[EvidenceBullet]
    level_definitions: LevelDefinitions
    probability: Optional[int] = Field(default=None, ge=0, le=4, description="評估者所填機率 0–4（ECDC：無/極低/低/中/高）；衝擊項目為 null")
    probability_rationale: Optional[str] = None
    impact: Optional[int] = Field(
        default=None, ge=1, le=4, description="評估者所填衝擊 1–4（ECDC：極低/低/中/高）；機率類項目若為 null，計算時沿用衝擊項目"
    )
    impact_rationale: Optional[str] = None
    ecdc: Optional[EcdcPath] = Field(default=None, description="ECDC 演算法路徑：機率類項目用 2.1 或 2.2，衝擊項目用 3；由程式推導分數")
    ecdc_impact: Optional[EcdcPath] = Field(default=None, description="機率類項目之衝擊另計時：ECDC 圖 3 路徑（取代沿用之衝擊）")
    proposed_level: Level3 = Field(description="評估者依本項目之風險等級定義所作文章式判斷：機率類項目為『發生機率』之低/中/高（不含衝擊），衝擊項目為衝擊之低/中/高")
    strata: list[Stratum] = Field(default_factory=list)
    confidence: Confidence = Field(description="低＝不足、中＝尚可、高＝良好（ECDC Box 2／HAIRS 附錄 B）")
    confidence_reason: str

    @model_validator(mode="after")
    def _kind_scores(self) -> "RiskItem":
        if self.kind == "機率" and self.probability is None:
            raise ValueError(f"{self.id}: 機率類項目必須提供 probability")
        if self.kind == "衝擊" and self.impact is None:
            raise ValueError(f"{self.id}: 衝擊項目必須提供 impact")
        prob_algs = ("2.1", "2.2") if self.kind == "機率" else ("3",)
        _check_alg(self.ecdc, prob_algs, f"{self.id}.ecdc")
        if self.kind == "衝擊" and self.ecdc_impact is not None:
            raise ValueError(f"{self.id}: 衝擊項目請用 ecdc（圖 3），不用 ecdc_impact")
        _check_alg(self.ecdc_impact, ("3",), f"{self.id}.ecdc_impact")
        for k, st in enumerate(self.strata):
            _check_alg(st.ecdc, prob_algs, f"{self.id}.strata[{k}].ecdc")
            _check_alg(st.ecdc_impact, ("3",), f"{self.id}.strata[{k}].ecdc_impact")
        return self


class HairsBlock(StrictModel):
    """UKHSA HAIRS emerging-infection algorithms (probability Q1–Q10, impact Q1–Q12).

    Cross-check only: reported beside the ECDC result, never combined into the matrix."""

    perspective: str = Field(default="以我國人口為評估對象（原文之 UK 換為我國）", description="評估對象說明")
    probability: list[AlgAnswer] = Field(default_factory=list)
    impact: list[AlgAnswer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_q(self) -> "HairsBlock":
        for name, lst, n in (("probability", self.probability, 10), ("impact", self.impact, 12)):
            qs = [a.q for a in lst]
            if len(qs) != len(set(qs)):
                raise ValueError(f"hairs.{name}：同一問題重複作答")
            bad = [q for q in qs if q not in {f"Q{i}" for i in range(1, n + 1)}]
            if bad:
                raise ValueError(f"hairs.{name}：無此問題 {bad}")
        return self


class WhoGroup(StrictModel):
    name: str = Field(description="族群或地區，如：孕婦、未滿 1 歲嬰兒及免疫不全者")
    likelihood: int = Field(ge=1, le=5, description="WHO 表 7：1 極不可能、2 不太可能、3 可能、4 很可能、5 幾乎確定")
    consequences: int = Field(ge=1, le=5, description="WHO 表 8：1 極輕微、2 輕微、3 中度、4 重大、5 嚴重")
    rationale: str
    source_ids: list[str] = Field(default_factory=list)


class WhoRra(StrictModel):
    """WHO (2012) Rapid Risk Assessment of Acute Public Health Events, Figure 3a.

    No question tree: likelihood and consequences are assessor judgments against
    WHO Tables 7 and 8."""

    risk_question: str
    likelihood: int = Field(ge=1, le=5, description="WHO 表 7：1 極不可能（<5%）、2 不太可能（5–29%）、3 可能（30–69%）、4 很可能（70–94%）、5 幾乎確定（≥95%）")
    likelihood_rationale: str
    consequences: int = Field(ge=1, le=5, description="WHO 表 8：1 極輕微、2 輕微、3 中度、4 重大、5 嚴重")
    consequences_rationale: str
    source_ids: list[str] = Field(default_factory=list)
    groups: list[WhoGroup] = Field(default_factory=list)

    @field_validator("groups")
    @classmethod
    def _unique_groups(cls, v: list[WhoGroup]) -> list[WhoGroup]:
        names = [g.name for g in v]
        if len(names) != len(set(names)):
            raise ValueError("who_rra.groups 名稱重複")
        return v


class OverallJudgment(StrictModel):
    proposed_level: Level3 = Field(description="疫情報導式（文章式）綜合判斷")
    summary: str = Field(description="綜合研判文字")
    key_findings: list[str] = Field(description="3–5 項重點發現")
    synthesis_note: Optional[str] = Field(default=None, description="各架構結果不一致時，評估者說明差異原因與審閱者應權衡之處（必填條件見方法）")


# ---------------------------------------------------------------------------
# IHR Annex 2, scenarios, triggers, recommendations, decision options
# ---------------------------------------------------------------------------


class IhrQuestion(StrictModel):
    key: Literal["serious_impact", "unusual_unexpected", "international_spread", "travel_trade_restriction"]
    answer: IhrAnswer
    rationale: str
    source_ids: list[str] = Field(default_factory=list)


class IhrScreen(StrictModel):
    perspective: str = Field(description="判定角度，如：以事件發生國（卡達）為準之篩檢；供我國研判升級參考")
    always_notifiable_disease: bool = Field(default=False, description="是否屬 IHR 附件二必通報疾病（天花、野生型小兒麻痺、新亞型人流感、SARS）")
    questions: list[IhrQuestion]

    @field_validator("questions")
    @classmethod
    def _four(cls, v: list[IhrQuestion]) -> list[IhrQuestion]:
        keys = [q.key for q in v]
        if sorted(keys) != sorted(["serious_impact", "unusual_unexpected", "international_spread", "travel_trade_restriction"]):
            raise ValueError("IHR 附件二篩檢需恰好包含四個問題各一次")
        return v


class Scenario(StrictModel):
    kind: Literal["最佳", "最可能", "最壞"]
    description: str
    assumptions: list[str] = Field(default_factory=list)
    implied_level: Level3
    implications: str


class Trigger(StrictModel):
    indicator: str = Field(description="可觀察之指標")
    direction: Literal["升級", "降級"]
    threshold: str
    monitoring_source: str
    current_status: str


class Recommendation(StrictModel):
    id: str
    category: RecCategory
    text: str
    priority: Priority
    timeframe: Timeframe
    owner: str = Field(description="建議主責單位")
    rationale: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)


class DecisionOption(StrictModel):
    id: str = Field(description="如 D1")
    title: str
    description: str
    pros: list[str]
    cons: list[str]
    recommended: bool = False
    owner: str
    timeframe: Timeframe
    resources: Optional[str] = None


class DecisionSupport(StrictModel):
    question: str = Field(description="長官需決定的問題")
    options: list[DecisionOption]
    recommendation_reason: str
    triggers: list[Trigger] = Field(default_factory=list)


class Generator(StrictModel):
    mode: Literal["api", "claude-code-skill", "manual"]
    model: Optional[str] = None
    tool_version: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Computed audit (written by scoring.audit; never trusted from input)
# ---------------------------------------------------------------------------


class Issue(StrictModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    path: Optional[str] = None


class PathAudit(StrictModel):
    algorithm: str
    value: int
    label: str
    path_text: str
    uncertain: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ItemAudit(StrictModel):
    item_id: str
    probability: Optional[int] = Field(description="計算採用之機率（有 ECDC 路徑時為推導值）")
    impact: Optional[int] = Field(description="計算採用之衝擊（有 ECDC 路徑時為推導值）")
    stated_probability: Optional[int] = None
    stated_impact: Optional[int] = None
    ecdc_probability: Optional[PathAudit] = None
    ecdc_impact: Optional[PathAudit] = None
    impact_inherited: bool = False
    matrix_level: Optional[MatrixLevel] = Field(description="矩陣風險（ECDC 圖 4：機率×衝擊），六級")
    matrix_level3: Optional[Level3] = Field(default=None, description="矩陣風險對應三級")
    computed_level: Level3 = Field(description="評估結果：機率類項目＝發生機率之三級；衝擊項目＝衝擊之三級")
    proposed_level: Level3
    agrees: bool
    stated_confidence: Confidence
    effective_confidence: Confidence
    confidence_caps: list[str] = Field(default_factory=list)
    uncited_bullets: int = 0
    strata_computed: list[dict] = Field(default_factory=list)


class WhoResult(StrictModel):
    name: str
    likelihood: int
    likelihood_label: str
    consequences: int
    consequences_label: str
    level: Literal["低", "中", "高", "極高"]
    level3: Level3
    action: str


class SynthesisRow(StrictModel):
    framework: str
    scope: str = Field(description="一般民眾／族群名稱")
    native: str
    level3: Optional[Level3] = Field(description="三級對應；HAIRS 無合併等級時為 null")
    method: str
    driver: str
    is_population: bool = True


class Synthesis(StrictModel):
    rows: list[SynthesisRow]
    integrated_level: Level3 = Field(description="綜合等級＝ECDC 2019 結果（主要方法）")
    consistency: Literal["一致", "部分一致", "不一致"]
    differences: list[str] = Field(default_factory=list)
    cautious_cap: Level3 = Field(description="審慎上限：ECDC、WHO、文章式判斷之最高三級（含一般民眾與高風險族群；不含 HAIRS）")
    cautions: list[str] = Field(default_factory=list, description="高於綜合等級之族群結果或 HAIRS 分項")
    note_required: bool
    compact: str


class ClaimAudit(StrictModel):
    claim_id: str
    stated_verdict: Verdict
    passes_rules: bool
    suggested_verdict: Optional[Verdict] = None
    independent_sources: int = 0
    best_tier: Optional[int] = None
    reasons: list[str] = Field(default_factory=list)


class Audit(StrictModel):
    matrix_version: str
    items: list[ItemAudit]
    overall_probability: Optional[int]
    overall_probability_from: Optional[str]
    overall_impact: Optional[int]
    overall_matrix_level: Optional[MatrixLevel]
    overall_computed_level: Level3
    overall_proposed_level: Level3
    overall_agrees: bool
    overall_confidence: Confidence
    overall_confidence_caps: list[str] = Field(default_factory=list)
    claims: list[ClaimAudit]
    credibility_computed: Level3
    credibility_proposed: Level3
    credibility_reason: str
    ihr_yes_count: int
    ihr_unknown_count: int
    ihr_meets_threshold: bool
    ihr_note: str
    hairs_probability: Optional[PathAudit] = None
    hairs_impact: Optional[PathAudit] = None
    who: Optional[WhoResult] = None
    who_groups: list[WhoResult] = Field(default_factory=list)
    synthesis: Optional[Synthesis] = None
    issues: list[Issue]


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


class Assessment(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_title: str
    generated_at: str = Field(description="ISO 8601 含時區")
    data_cutoff: str = Field(description="資料截止時間 ISO 8601")
    reassessment_date: str = Field(description="建議再評估日期 YYYY-MM-DD")
    generator: Generator
    event: EventMeta
    sources: list[Source]
    claims: list[Claim]
    news_credibility: NewsCredibility
    pathogen: PathogenProfile
    international: InternationalSituation
    taiwan: TaiwanContext
    risk_items: list[RiskItem]
    overall: OverallJudgment
    ihr_annex2: IhrScreen
    scenarios: list[Scenario]
    recommendations: list[Recommendation]
    decision: DecisionSupport
    limitations: list[str]
    hairs: Optional[HairsBlock] = Field(default=None, description="人畜共通／新興病原：UKHSA HAIRS 演算法作答（交叉核對用）")
    who_rra: Optional[WhoRra] = Field(default=None, description="WHO 2012 風險矩陣（圖 3a）之並行評估：可能性與後果為評估者依表 7、表 8 之判斷")
    audit: Optional[Audit] = Field(default=None, description="由 scoring.audit() 計算；輸入值會被忽略並重算")

    @model_validator(mode="after")
    def _unique_ids(self) -> "Assessment":
        for name, ids in (
            ("sources", [s.id for s in self.sources]),
            ("claims", [c.id for c in self.claims]),
            ("risk_items", [r.id for r in self.risk_items]),
            ("recommendations", [r.id for r in self.recommendations]),
            ("decision.options", [o.id for o in self.decision.options]),
        ):
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                raise ValueError(f"{name} 有重複代碼：{sorted(dupes)}")
        if not any(r.kind == "衝擊" for r in self.risk_items):
            raise ValueError("risk_items 必須至少包含一個『衝擊』項目")
        if not any(r.kind == "機率" for r in self.risk_items):
            raise ValueError("risk_items 必須至少包含一個『機率』類項目（如境外移入風險）")
        return self




def llm_output_schema() -> dict:
    """JSON schema for the LLM-facing part (without the computed ``audit``)."""
    schema = Assessment.model_json_schema()
    schema.get("properties", {}).pop("audit", None)
    return schema
