"""Fusionオブジェクトを含まない処理結果。"""
from dataclasses import dataclass
from .geometry import Part


@dataclass(frozen=True)
class ExtractionResult:
    parts: list[Part]
    warnings: list[str]
    hidden_count: int


@dataclass(frozen=True)
class AnalysisResult:
    parts: list[Part]
    warnings: list[str]
    size: tuple[float, float]
    hidden_count: int
