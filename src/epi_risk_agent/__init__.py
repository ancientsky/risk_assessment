"""Epidemic rapid risk assessment agent for Taiwan public-health officials.

Pipeline: ingest news -> extract claims -> verify on the web -> gather Taiwan
context -> structured assessment JSON (LLM judgments with citations) ->
deterministic scoring/validation -> self-contained HTML report.
"""

__version__ = "0.1.0"
METHODOLOGY_VERSION = "2026.11-v2-ecdc"
