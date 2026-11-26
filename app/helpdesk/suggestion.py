from typing import Iterator

from .ports import LLMGateway
from .schemas import TicketInput

CAPABILITY = "suggestion"


def suggest_stream(ticket: TicketInput, gateway: LLMGateway) -> Iterator[str]:
    """Trechos da sugestão, conforme chegam do gateway (streaming).

    A moldura SSE (eventos data/end/error) é responsabilidade do ponto de
    composição (main); aqui mora só a capacidade e a tarefa.
    """
    return gateway.stream(CAPABILITY, "suggest", ticket.text)
