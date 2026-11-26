"""Adapter concreto do AI Gateway (LiteLLM), compatível com o formato OpenAI.

É o ÚNICO componente da aplicação que fala com o gateway. Conhece a base URL e a
virtual key do gateway (nunca as chaves dos providers nem o modelo físico). O
LiteLLM traduz o formato OpenAI para o provider upstream de cada capacidade, então
um único cliente atende as quatro capacidades.

Os retries do SDK são DESLIGADOS (max_retries=0): a política de retry é do
gateway. Se o SDK também repetisse, as tentativas se multiplicariam (visível em
/admin/calls).
"""

from typing import Iterator

from openai import OpenAI

from .. import config
from ..ports import LLMGateway


class GatewayClient:
    """Implementa `ports.LLMGateway` sobre o endpoint OpenAI-compatível do gateway."""

    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            timeout=timeout,
        )

    def _messages(self, task: str, content: str) -> list[dict]:
        return [{"role": "user", "content": f"TASK: {task}\n{content}"}]

    def complete(self, capability: str, task: str, content: str) -> str:
        response = self._client.chat.completions.create(
            model=capability,
            messages=self._messages(task, content),
            max_tokens=config.MAX_OUTPUT_TOKENS,
        )
        return response.choices[0].message.content

    def stream(self, capability: str, task: str, content: str) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=capability,
            messages=self._messages(task, content),
            max_tokens=config.MAX_OUTPUT_TOKENS,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


def build_gateway() -> LLMGateway:
    """Fábrica usada pelo ponto de composição: devolve a abstração, não o concreto."""
    return GatewayClient(
        base_url=f"{config.GATEWAY_BASE_URL}/v1",
        api_key=config.GATEWAY_API_KEY,
        timeout=config.GATEWAY_TIMEOUT,
    )
