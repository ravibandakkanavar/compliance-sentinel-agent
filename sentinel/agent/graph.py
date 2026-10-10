"""Assembles the audit graph."""

from __future__ import annotations

from functools import partial

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from sentinel.agent import nodes
from sentinel.agent.nodes import AuditState, Deps


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver | None = None):
    """Return the compiled graph.

    load_new_rules ─┬─► extract_obligations ─► scan_codebase ─► evaluate_findings ─► verify ─┐
                    ├─► scan_codebase (full re-audit, no new rules)                          │
                    └─► compile_report ◄─────────────────────────────────────────────────────┘
    """
    graph = StateGraph(AuditState)
    for name in (
        "load_new_rules",
        "extract_obligations",
        "scan_codebase",
        "evaluate_findings",
        "verify",
        "compile_report",
    ):
        graph.add_node(name, partial(getattr(nodes, name), deps=deps))

    graph.add_edge(START, "load_new_rules")
    graph.add_conditional_edges(
        "load_new_rules",
        nodes.route_after_load,
        ["extract_obligations", "scan_codebase", "compile_report"],
    )
    graph.add_edge("extract_obligations", "scan_codebase")
    graph.add_edge("scan_codebase", "evaluate_findings")
    graph.add_edge("evaluate_findings", "verify")
    graph.add_edge("verify", "compile_report")
    graph.add_edge("compile_report", END)
    return graph.compile(checkpointer=checkpointer)
