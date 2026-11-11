"""Evaluation-only document contracts. Offsets use Unicode code points."""
from dataclasses import dataclass, field


@dataclass
class Unit:
    key: str
    role: str
    text: str
    scripts: list[tuple[int, int, str]] = field(default_factory=list)
    math: list[tuple[int, int]] = field(default_factory=list)
    section: tuple[str, ...] = ()


@dataclass
class Document:
    format: str
    units: list[Unit]
    authors: dict[str, str]
    affiliations: dict[str, str]
    edges: set[tuple[str, str]]
    unsupported: list[dict]
    tree: object
    warnings: list[str] = field(default_factory=list)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def prf(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn)}
