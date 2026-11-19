"""Decision trees from the primary sources, encoded as data.

* ECDC (2019) Operational tool on rapid risk assessment methodology,
  Figures 2.1, 2.2 (probability) and 3 (impact), Figure 4 (risk-ranking matrix).
  https://www.ecdc.europa.eu/sites/default/files/documents/operational-tool-rapid-risk-assessment-methodolgy-ecdc-2019.pdf
* UKHSA HAIRS risk assessment process: probability-of-infection and
  impact-on-human-health algorithms (accessible text reproduced in Annexes B/D
  of published HAIRS assessments, e.g. the chikungunya assessment).
  https://www.gov.uk/government/publications/hairs-risk-assessment-process/hairs-risk-assessment-process

Question texts are given in English (verbatim) and Traditional Chinese
(translation by this tool).

Uncertainty (answer 不確定, or the question left unanswered) is handled with the
precautionary rule: both branches are evaluated and the higher-risk outcome is
taken. ECDC: uncertainty is managed "by adopting a precautionary approach ...
and moving through the algorithm to a higher level of risk". HAIRS: "Following
precautionary principles, the algorithm should be continued until a decisive
answer is attained". Taking the maximum of both branches is this tool's
operationalisation of those statements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

Target = Union[str, int]  # question id ("Q3") or outcome value (int)


@dataclass(frozen=True)
class Node:
    en: str
    zh: str
    yes: Target
    no: Target
    yes_label: str = "是"
    note: Optional[str] = None


@dataclass(frozen=True)
class Tree:
    key: str
    title: str
    start: str
    nodes: dict[str, Node]
    labels: dict[int, str]  # outcome value -> zh label


# --- ECDC 2019 -------------------------------------------------------------

ECDC_P_LABELS = {0: "無", 1: "極低", 2: "低", 3: "中", 4: "高"}  # None, Very low, Low, Moderate, High
ECDC_I_LABELS = {1: "極低", 2: "低", 3: "中", 4: "高"}  # Very low, Low, Moderate, High

_ECDC_Q2_4 = {
    "Q3": Node("Is the population in the Member States highly susceptible?", "我國人口是否高度易感？", yes="Q4", no=2),
    "Q4": Node("Is the pathogen likely to be transmitted?", "病原是否可能傳播？", yes=4, no=3),
}

ECDC_21 = Tree(
    key="2.1", title="ECDC 圖 2.1：國內感染／傳播機率", start="Q1", labels=ECDC_P_LABELS,
    nodes={
        "Q1": Node("Are there routes of introduction into Member States?", "是否有傳入我國之途徑？", yes="Q2", no=0),
        "Q2": Node("Is human exposure likely in Member States?", "我國境內是否可能有人類暴露？", yes="Q3", no=1),
        **_ECDC_Q2_4,
    },
)

ECDC_22 = Tree(
    key="2.2", title="ECDC 圖 2.2：國人於境外感染之機率（本工具對應：境外移入）", start="Q2", labels=ECDC_P_LABELS,
    nodes={
        "Q2": Node("Is exposure likely?", "國人是否可能暴露？", yes="Q3", no=1),
        "Q3": Node("Is the exposed group/community highly susceptible?", "暴露之族群是否高度易感？", yes="Q4", no=2),
        "Q4": Node("Is the pathogen likely to be transmitted?", "病原是否可能傳播？", yes=4, no=3),
    },
)

ECDC_3 = Tree(
    key="3", title="ECDC 圖 3：衝擊（族群中疾病嚴重度）", start="Q5", labels=ECDC_I_LABELS,
    nodes={
        "Q5": Node("Is severe disease likely in this population/group?", "此族群是否可能發生重症？", yes="Q6", no=1),
        "Q6": Node("Will a significant number of people be affected?", "是否會有相當多人受影響？", yes="Q7", no=2),
        "Q7": Node("Are effective treatment and control measures available?", "是否有有效之治療與防治措施？", yes=3, no=4),
    },
)

ECDC_TREES = {"2.1": ECDC_21, "2.2": ECDC_22, "3": ECDC_3}

# --- UKHSA HAIRS -----------------------------------------------------------

HAIRS_P_LABELS = {1: "極低", 2: "低", 3: "中", 4: "高"}
HAIRS_I_LABELS = {1: "極低", 2: "低", 3: "中", 4: "高", 5: "極高"}

HAIRS_P = Tree(
    key="hairs-p", title="HAIRS：我國人口感染機率", start="Q1", labels=HAIRS_P_LABELS,
    nodes={
        "Q1": Node("Is this a recognised human disease?", "是否為已知之人類疾病？", yes="Q3", no="Q2"),
        "Q2": Node("Is this a zoonosis or is there a zoonotic potential?", "是否為人畜共通傳染病或具人畜共通潛勢？", yes="Q4", no=1),
        "Q3": Node("Is this disease endemic in humans within the UK?", "此疾病是否於我國人類中呈地方性流行？", yes="Q5", no="Q4",
                   note="note 2: This pathway considers reverse-zoonosis of a pathogen already in circulation in the human population."),
        "Q4": Node("Is this disease endemic in animals in the UK?", "此疾病是否於我國動物中呈地方性流行？", yes="Q8", no="Q5"),
        "Q5": Node("Are there routes of introduction into animals in the UK?", "是否有傳入我國動物之途徑？", yes="Q6", no=1),
        "Q6": Node("Are effective measures in place to mitigate against these?", "是否已有有效措施可減緩這些途徑？", yes=1, no="Q7"),
        "Q7": Node("Do environmental conditions in the UK support the natural vectors of disease?", "我國環境條件是否支持該疾病之自然病媒？", yes="Q8", no=1),
        "Q8": Node("Will there be human exposure?", "是否會有人類暴露？", yes="Q9", no=1),
        "Q9": Node("Are humans highly susceptible?", "人類是否高度易感？", yes="Q10", no=2,
                   note="note 3: Includes susceptibility to animal-derived variants."),
        "Q10": Node("Is the disease highly infectious in humans?", "此疾病於人類間是否具高度傳染力？", yes=4, no=3),
    },
)

HAIRS_I = Tree(
    key="hairs-i", title="HAIRS：對我國人群健康之衝擊", start="Q1", labels=HAIRS_I_LABELS,
    nodes={
        "Q1": Node("Is there human-to-human spread?", "是否有人傳人？", yes="Q4", no="Q2"),
        "Q2": Node("Is there zoonotic or vector-borne spread?", "是否有人畜共通或病媒傳播？", yes="Q3", no=1),
        "Q3": Node("For zoonoses or vector-borne disease, is the animal host or vector present in the UK?", "（人畜共通或病媒傳播者）動物宿主或病媒是否存在於我國？", yes="Q4", no=1),
        "Q4": Node("Is the human population susceptible?", "人群是否易感？", yes="Q5", no=1),
        "Q5": Node("Does it cause severe disease in humans?", "是否造成人類重症？", yes="Q8", no="Q6", yes_label="是（高風險族群）"),
        "Q6": Node("Is it highly infectious to humans?", "對人類是否具高度傳染力？", yes="Q9", no="Q7"),
        "Q7": Node("Are effective interventions available?", "是否有有效介入措施？", yes=1, no=2),
        "Q8": Node("Would a substantial number of people be affected?", "是否會有相當多人受影響？", yes="Q10", no="Q9",
                   note="note 4: 'Substantial' is not quantified in the algorithm but left open for discussion within the context of the risk being assessed."),
        "Q9": Node("Are effective interventions available?", "是否有有效介入措施？", yes=2, no=3),
        "Q10": Node("Is it highly infectious to humans?", "對人類是否具高度傳染力？", yes="Q12", no="Q11"),
        "Q11": Node("Are effective interventions available?", "是否有有效介入措施？", yes=3, no=4),
        "Q12": Node("Are effective interventions available?", "是否有有效介入措施？", yes=4, no=5),
    },
)

HAIRS_TREES = {"probability": HAIRS_P, "impact": HAIRS_I}


# --- evaluation ------------------------------------------------------------


@dataclass
class Step:
    q: str
    answer: str  # 是 / 否 / 不確定 / 未填
    taken: str  # 是 / 否 (branch actually followed)


@dataclass
class Result:
    tree: str
    value: int
    label: str
    steps: list[Step] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)  # questions resolved by the precautionary rule
    missing: list[str] = field(default_factory=list)  # questions on the path left unanswered

    def path_text(self, title: Optional[str] = None) -> str:
        parts = []
        for s in self.steps:
            if s.answer in ("是", "否"):
                parts.append(f"{s.q} {s.answer}")
            else:
                parts.append(f"{s.q} {s.answer}（預防原則取「{s.taken}」）")
        return f"{title + '：' if title else ''}{' → '.join(parts)} ⇒ {self.label}"


def evaluate(tree: Tree, answers: dict[str, str]) -> Result:
    """Walk ``tree`` with ``answers`` (question id -> 是/否/不確定).

    Unanswered or 不確定 questions evaluate both branches and take the higher
    outcome (precautionary rule)."""

    def walk(target: Target) -> tuple[int, list[Step], list[str], list[str]]:
        if isinstance(target, int):
            return target, [], [], []
        node = tree.nodes[target]
        ans = answers.get(target)
        if ans == "是":
            v, st, un, mi = walk(node.yes)
            return v, [Step(target, "是", "是")] + st, un, mi
        if ans == "否":
            v, st, un, mi = walk(node.no)
            return v, [Step(target, "否", "否")] + st, un, mi
        vy, sy, uy, my = walk(node.yes)
        vn, sn, un_, mn = walk(node.no)
        label = "不確定" if ans == "不確定" else "未填"
        if vy >= vn:  # ties resolved toward 是 (the branch that continues the assessment)
            return vy, [Step(target, label, "是")] + sy, ([target] if ans == "不確定" else []) + uy, ([] if ans == "不確定" else [target]) + my
        return vn, [Step(target, label, "否")] + sn, ([target] if ans == "不確定" else []) + un_, ([] if ans == "不確定" else [target]) + mn

    v, steps, unc, miss = walk(tree.start)
    return Result(tree=tree.key, value=v, label=tree.labels[v], steps=steps, uncertain=unc, missing=miss)
