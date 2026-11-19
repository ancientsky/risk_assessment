"""Every branch of the ECDC 2019 (Figures 2.1, 2.2, 3) and UKHSA HAIRS trees."""

import itertools

import pytest

from epi_risk_agent.algorithms import ECDC_21, ECDC_22, ECDC_3, HAIRS_I, HAIRS_P, evaluate

Y, N, U = "是", "否", "不確定"

# --- ECDC Figure 2.1: probability of infection/transmission (domestic) -------
FIG21 = [
    ({"Q1": N}, 0, "無"),
    ({"Q1": Y, "Q2": N}, 1, "極低"),
    ({"Q1": Y, "Q2": Y, "Q3": N}, 2, "低"),
    ({"Q1": Y, "Q2": Y, "Q3": Y, "Q4": N}, 3, "中"),
    ({"Q1": Y, "Q2": Y, "Q3": Y, "Q4": Y}, 4, "高"),
]

# --- ECDC Figure 2.2: our citizens abroad (no Q1) -----------------------------
FIG22 = [
    ({"Q2": N}, 1, "極低"),
    ({"Q2": Y, "Q3": N}, 2, "低"),
    ({"Q2": Y, "Q3": Y, "Q4": N}, 3, "中"),
    ({"Q2": Y, "Q3": Y, "Q4": Y}, 4, "高"),
]

# --- ECDC Figure 3: impact ----------------------------------------------------
FIG3 = [
    ({"Q5": N}, 1, "極低"),
    ({"Q5": Y, "Q6": N}, 2, "低"),
    ({"Q5": Y, "Q6": Y, "Q7": Y}, 3, "中"),  # effective treatment/control available -> Moderate
    ({"Q5": Y, "Q6": Y, "Q7": N}, 4, "高"),
]


@pytest.mark.parametrize("tree,answers,value,label",
                         [(ECDC_21, *c) for c in FIG21] + [(ECDC_22, *c) for c in FIG22] + [(ECDC_3, *c) for c in FIG3])
def test_ecdc_branches(tree, answers, value, label):
    r = evaluate(tree, answers)
    assert (r.value, r.label) == (value, label)
    assert [s.q for s in r.steps] == list(answers)
    assert not r.uncertain and not r.missing


def test_ecdc_22_has_no_q1():
    assert ECDC_22.start == "Q2" and "Q1" not in ECDC_22.nodes


# --- HAIRS probability (Q1-Q10) ------------------------------------------------
HAIRS_P_CASES = [
    ({"Q1": N, "Q2": N}, 1),
    ({"Q1": N, "Q2": Y, "Q4": Y, "Q8": N}, 1),
    ({"Q1": N, "Q2": Y, "Q4": N, "Q5": N}, 1),
    ({"Q1": N, "Q2": Y, "Q4": N, "Q5": Y, "Q6": Y}, 1),
    ({"Q1": N, "Q2": Y, "Q4": N, "Q5": Y, "Q6": N, "Q7": N}, 1),
    ({"Q1": N, "Q2": Y, "Q4": N, "Q5": Y, "Q6": N, "Q7": Y, "Q8": Y, "Q9": N}, 2),
    ({"Q1": Y, "Q3": Y, "Q5": Y, "Q6": N, "Q7": Y, "Q8": Y, "Q9": Y, "Q10": N}, 3),
    ({"Q1": Y, "Q3": N, "Q4": Y, "Q8": Y, "Q9": Y, "Q10": Y}, 4),
    ({"Q1": Y, "Q3": N, "Q4": Y, "Q8": Y, "Q9": N}, 2),
]


@pytest.mark.parametrize("answers,value", HAIRS_P_CASES)
def test_hairs_probability_branches(answers, value):
    r = evaluate(HAIRS_P, answers)
    assert r.value == value and r.label == HAIRS_P.labels[value]
    assert [s.q for s in r.steps] == list(answers)


# --- HAIRS impact (Q1-Q12) ------------------------------------------------------
HAIRS_I_CASES = [
    ({"Q1": N, "Q2": N}, 1),
    ({"Q1": N, "Q2": Y, "Q3": N}, 1),
    ({"Q1": N, "Q2": Y, "Q3": Y, "Q4": N}, 1),
    ({"Q1": Y, "Q4": N}, 1),
    ({"Q1": Y, "Q4": Y, "Q5": N, "Q6": N, "Q7": Y}, 1),
    ({"Q1": Y, "Q4": Y, "Q5": N, "Q6": N, "Q7": N}, 2),
    ({"Q1": Y, "Q4": Y, "Q5": N, "Q6": Y, "Q9": Y}, 2),
    ({"Q1": Y, "Q4": Y, "Q5": N, "Q6": Y, "Q9": N}, 3),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": N, "Q9": Y}, 2),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": N, "Q9": N}, 3),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": Y, "Q10": N, "Q11": Y}, 3),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": Y, "Q10": N, "Q11": N}, 4),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": Y, "Q10": Y, "Q12": Y}, 4),
    ({"Q1": Y, "Q4": Y, "Q5": Y, "Q8": Y, "Q10": Y, "Q12": N}, 5),
]


@pytest.mark.parametrize("answers,value", HAIRS_I_CASES)
def test_hairs_impact_branches(answers, value):
    r = evaluate(HAIRS_I, answers)
    assert r.value == value and r.label == HAIRS_I.labels[value]
    assert [s.q for s in r.steps] == list(answers)


def test_every_hairs_node_and_edge_is_covered():
    for tree, cases in ((HAIRS_P, HAIRS_P_CASES), (HAIRS_I, HAIRS_I_CASES)):
        edges = {(q, a) for answers, _ in cases for q, a in answers.items()}
        for q in tree.nodes:
            assert (q, Y) in edges and (q, N) in edges, f"{tree.key} {q} branch not covered"


def test_every_ecdc_edge_is_covered():
    for tree, cases in ((ECDC_21, FIG21), (ECDC_22, FIG22), (ECDC_3, FIG3)):
        edges = {(q, a) for answers, *_ in cases for q, a in answers.items()}
        for q in tree.nodes:
            assert (q, Y) in edges and (q, N) in edges


# --- precautionary handling of uncertainty --------------------------------------

def test_uncertain_takes_higher_branch_ecdc():
    r = evaluate(ECDC_21, {"Q1": Y, "Q2": Y, "Q3": U, "Q4": N})
    assert r.value == 3 and r.uncertain == ["Q3"] and not r.missing
    assert "Q3 不確定（預防原則取「是」）" in r.path_text()
    # Q7 uncertain: "available" (是) -> Moderate, "not available" (否) -> High; take High
    r = evaluate(ECDC_3, {"Q5": Y, "Q6": Y, "Q7": U})
    assert r.value == 4 and r.steps[-1].taken == "否"


def test_missing_answers_are_listed_and_precautionary():
    r = evaluate(ECDC_22, {})
    assert r.value == 4 and r.missing == ["Q2", "Q3", "Q4"]


@pytest.mark.parametrize("tree", [ECDC_21, ECDC_22, ECDC_3, HAIRS_P, HAIRS_I])
def test_uncertain_never_lower_than_any_definite_answer(tree):
    qs = list(tree.nodes)
    for q in qs:
        others = {x: Y for x in qs if x != q}
        for base in (Y, N):
            others_n = {x: base for x in qs if x != q}
            for ctx in (others, others_n):
                u = evaluate(tree, {**ctx, q: U}).value
                assert u >= evaluate(tree, {**ctx, q: Y}).value
                assert u >= evaluate(tree, {**ctx, q: N}).value


def test_all_answer_combinations_terminate_ecdc():
    for tree in (ECDC_21, ECDC_22, ECDC_3):
        qs = list(tree.nodes)
        for combo in itertools.product((Y, N, U), repeat=len(qs)):
            r = evaluate(tree, dict(zip(qs, combo)))
            assert r.value in tree.labels
