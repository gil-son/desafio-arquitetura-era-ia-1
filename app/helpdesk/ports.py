"""Portas (abstrações) da aplicação.

A porta `LLMGateway` é o ponto de inversão de dependência: as features pedem uma
CAPACIDADE lógica (ex.: "classification") sem conhecer provider, modelo físico,
formato de API nem credencial. Quem implementa isso é um adapter concreto
(`adapters.gateway`), conhecido apenas pelo ponto de composição (`main`).
"""

from typing import Iterator, Protocol


class LLMGateway(Protocol):
    """Capacidade de inferência exposta pelo AI Gateway."""

    def complete(self, capability: str, task: str, content: str) -> str:
        """Resposta completa (síncrona) para uma capacidade lógica."""
        ...

    def stream(self, capability: str, task: str, content: str) -> Iterator[str]:
        """Resposta em trechos (streaming) para uma capacidade lógica."""
        ...
