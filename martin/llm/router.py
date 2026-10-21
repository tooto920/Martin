"""Automatické routování mezi lokálním a cloudovým modelem."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from martin.llm.client import OllamaClient


class TaskComplexity(str, Enum):
    """Odhad složitosti úlohy."""

    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


@dataclass(slots=True)
class RoutingDecision:
    """Rozhodnutí, který model a úroveň oprávnění se použije."""

    model: str
    provider: str  # local | cloud
    complexity: TaskComplexity
    reason: str
    requires_vision: bool = False
    requires_tools: bool = False
    allow_cloud: bool = True


# Slova signalizující složitou úlohu.
_COMPLEX_MARKERS = (
    "analyz", "porovnej", "porovn", "navrhni", "architekt", "plán", "plan",
    "vysvětli podrobně", "krok za krokem", "optimaliz", "lad", "debug",
    "refaktor", "přepiš", "implementuj", "napiš kód", "co je chyba",
)

_VISION_MARKERS = (
    "obrazov", "screen", "screenshot", "sním", "co je tady", "co je tohle",
    "tahle chyba", "tuhle chyba", "okno", "co vidíš", "co tu je",
)

_TOOL_MARKERS = (
    "spusť", "spust", "otevři", "otevri", "nastav", "zavři", "vyhledej",
    "najdi", "spusť program", "launch", "přepni", "přepni na",
)

_CODE_BLOCK = re.compile(r"```")


class ModelRouter:
    """Rozhoduje mezi lokálním a cloudovým modelem.

    Pravidla:
      * Local Only režim -> vždy lokální model, jinak chyba.
      * Obraz -> musí jít o model s vizí.
      * Složitá úloha + povolený cloud -> cloud model.
      * Jindy -> lokální model.
    """

    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    def estimate_complexity(self, text: str) -> TaskComplexity:
        """Odhadne složitost požadavku podle délky a klíčových slov."""
        lowered = text.lower()
        length = len(text)
        has_code = bool(_CODE_BLOCK.search(text))
        markers = sum(1 for m in _COMPLEX_MARKERS if m in lowered)
        if markers >= 2 or (markers >= 1 and length > 200) or length > 900:
            return TaskComplexity.COMPLEX
        if markers >= 1 or length > 320 or has_code:
            return TaskComplexity.SIMPLE
        return TaskComplexity.TRIVIAL

    def requires_vision(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in _VISION_MARKERS)

    def requires_tools(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in _TOOL_MARKERS)

    def route(
        self,
        text: str,
        local_model: str,
        cloud_model: str,
        local_only: bool = False,
        allow_cloud: bool = True,
    ) -> RoutingDecision:
        """Rozhodne, kterým modelem odpovědět."""
        complexity = self.estimate_complexity(text)
        needs_vision = self.requires_vision(text)
        needs_tools = self.requires_tools(text)

        if local_only:
            if needs_vision and not self._client.has_vision(local_model):
                raise ValueError(
                    "Zadaný lokální model nemá podporu zpracování obrazu."
                )
            return RoutingDecision(
                model=local_model,
                provider="local",
                complexity=complexity,
                reason="Režim Local Only - pouze lokální model.",
                requires_vision=needs_vision,
                requires_tools=needs_tools,
                allow_cloud=False,
            )

        if needs_vision:
            if self._client.has_vision(local_model):
                return RoutingDecision(
                    model=local_model,
                    provider="local",
                    complexity=complexity,
                    reason="Vizuální úloha - lokální model s podporou obrazu.",
                    requires_vision=True,
                    requires_tools=needs_tools,
                )
            if allow_cloud:
                return RoutingDecision(
                    model=cloud_model,
                    provider="cloud",
                    complexity=complexity,
                    reason="Lokální model neumí obraz - použit cloudový model.",
                    requires_vision=True,
                    requires_tools=needs_tools,
                )
            raise ValueError(
                "Vizuální úloha vyžaduje model s podporou obrazu a cloud je vypnutý."
            )

        if complexity is TaskComplexity.COMPLEX and allow_cloud:
            return RoutingDecision(
                model=cloud_model,
                provider="cloud",
                complexity=complexity,
                reason="Složitá úloha - použit cloudový model.",
                requires_tools=needs_tools,
            )

        return RoutingDecision(
            model=local_model,
            provider="local",
            complexity=complexity,
            reason="Úloha je zvládnutelná lokálně.",
            requires_tools=needs_tools,
        )