"""Testes de contrato das 4 features — versão da branch `main`.

F1 e F4 continuam síncronas (corpo fixado, como na caracterização). F2 e F3
mudaram de MODO de execução (requisito 6): F2 é streaming (SSE) e F3 é assíncrona
(Request-Reply). Aqui os testes validam o NOVO contrato, mantendo a saída de
negócio idêntica à fixada nos golden (o texto da sugestão e o relatório de 1 dia).

O registro do comportamento ANTIGO (tudo síncrono) vive nas tags v1-coupled e
v2-decoupled; ver o histórico git.
"""

import json
import time

from conftest import load_fixture


# --------------------------------------------------------------------------- #
# F1 — Classificar ticket  (SÍNCRONO, inalterado)
# --------------------------------------------------------------------------- #
def test_f1_classification_success(client):
    r = client.post(
        "/tickets/classification",
        json={
            "ticket_id": "TK-00042",
            "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}


def test_f1_classification_input_error(client):
    r = client.post("/tickets/classification", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F2 — Sugerir resposta  (STREAMING SSE)
# --------------------------------------------------------------------------- #
def _collect_sse(client, payload):
    """Consome o stream SSE e devolve (content_type, chunks, eventos)."""
    chunks: list[str] = []
    events: list[tuple[str, dict]] = []
    with client.stream("POST", "/tickets/reply-suggestion", json=payload) as r:
        content_type = r.headers.get("content-type", "")
        current_event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                if current_event:
                    events.append((current_event, data))
                    current_event = None
                else:
                    chunks.append(data["chunk"])
    return content_type, chunks, events


def test_f2_reply_suggestion_streaming(client):
    content_type, chunks, events = _collect_sse(
        client, {"ticket_id": "TK-00042", "text": "Meu pedido não chegou"}
    )
    assert "text/event-stream" in content_type
    assert chunks, "esperava trechos de texto no stream"
    # A sugestão montada é idêntica ao golden fixado (comportamento de negócio preservado).
    assert "".join(chunks) == load_fixture("f2_suggestion.json")["suggestion"]
    # Termina com evento end carregando o ticket_id.
    assert events[-1][0] == "end"
    assert events[-1][1] == {"ticket_id": "TK-00042"}


def test_f2_reply_suggestion_input_error(client):
    # Validação de entrada acontece antes de abrir o stream -> 422.
    r = client.post("/tickets/reply-suggestion", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F3 — Relatório de temas  (ASSÍNCRONO Request-Reply)
# --------------------------------------------------------------------------- #
def test_f3_topics_report_async(client):
    # POST aceita o pedido: 202 + Location + Retry-After.
    r = client.post("/reports/topics", json={"start": "2026-08-01", "end": "2026-08-01"})
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "Retry-After" in r.headers
    status_url = r.headers["Location"]

    # Acompanha o status até o 303 (done).
    result_url = None
    for _ in range(60):
        s = client.get(status_url)
        if s.status_code == 303:
            result_url = s.headers["Location"]
            break
        assert s.status_code == 200
        assert s.json()["state"] in {"pending", "running"}
        time.sleep(1)
    assert result_url, "o relatório não ficou pronto a tempo"

    # Resultado idêntico ao golden de 1 dia (comportamento de negócio preservado).
    result = client.get(result_url)
    assert result.status_code == 200
    assert result.json() == load_fixture("f3_topics.json")


def test_f3_topics_report_input_error(client):
    # start posterior a end -> 422 já no POST (antes de aceitar a tarefa).
    r = client.post("/reports/topics", json={"start": "2026-08-31", "end": "2026-08-01"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F4 — Extrair dados do pedido  (SÍNCRONO, inalterado)
# --------------------------------------------------------------------------- #
def test_f4_extraction_success(client):
    r = client.post(
        "/tickets/extraction",
        json={
            "ticket_id": "TK-00042",
            "text": "Nota fiscal 998877. Quero trocar o pedido #605065, "
            "veio um fone de ouvido bluetooth com defeito",
        },
    )
    assert r.status_code == 200
    assert r.json() == {
        "ticket_id": "TK-00042",
        "order_number": "#605065",
        "product": "fone de ouvido bluetooth",
    }


def test_f4_extraction_no_order(client):
    r = client.post(
        "/tickets/extraction",
        json={"ticket_id": "TK-00099", "text": "Só queria saber o horário de atendimento"},
    )
    assert r.status_code == 200
    assert r.json() == {"ticket_id": "TK-00099", "order_number": None, "product": None}


def test_f4_extraction_input_error(client):
    r = client.post("/tickets/extraction", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422
