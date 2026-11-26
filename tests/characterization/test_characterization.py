"""Testes de caracterização das 4 features (Feathers).

Fixam o COMPORTAMENTO OBSERVADO da aplicação recebida (v1-coupled): corpo das
respostas (campos e valores), não só o status HTTP. São a rede de segurança da
refatoração: devem passar iguais na v1-coupled e na v2-decoupled.

Cada feature tem pelo menos um caso de sucesso e um caso de erro de entrada.
"""

from conftest import load_fixture


# --------------------------------------------------------------------------- #
# F1 — Classificar ticket  (POST /tickets/classification)
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
    assert r.json() == {
        "ticket_id": "TK-00042",
        "category": "delivery",
        "priority": "high",
    }


def test_f1_classification_input_error(client):
    # text vazio viola min_length=1 (pydantic) -> 422
    r = client.post("/tickets/classification", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F2 — Sugerir resposta  (POST /tickets/reply-suggestion)
# --------------------------------------------------------------------------- #
def test_f2_reply_suggestion_success(client):
    r = client.post(
        "/tickets/reply-suggestion",
        json={"ticket_id": "TK-00042", "text": "Meu pedido não chegou"},
    )
    assert r.status_code == 200
    # Saída longa e determinística; comparada por igualdade com o golden capturado.
    assert r.json() == load_fixture("f2_suggestion.json")


def test_f2_reply_suggestion_input_error(client):
    r = client.post("/tickets/reply-suggestion", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F3 — Relatório de temas  (POST /reports/topics)
# --------------------------------------------------------------------------- #
def test_f3_topics_report_success(client):
    # Período de 1 dia: na v1 a feature é síncrona e o mês inteiro estoura a borda.
    r = client.post(
        "/reports/topics", json={"start": "2026-08-01", "end": "2026-08-01"}
    )
    assert r.status_code == 200
    assert r.json() == load_fixture("f3_topics.json")


def test_f3_topics_report_input_error(client):
    # start posterior a end -> 422 (report.py levanta HTTPException)
    r = client.post(
        "/reports/topics", json={"start": "2026-08-31", "end": "2026-08-01"}
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# F4 — Extrair dados do pedido  (POST /tickets/extraction)
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
    # Com o modelo large: pedido correto (#605065, não a nota fiscal) e produto identificado.
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
    assert r.json() == {
        "ticket_id": "TK-00099",
        "order_number": None,
        "product": None,
    }


def test_f4_extraction_input_error(client):
    r = client.post("/tickets/extraction", json={"ticket_id": "X", "text": ""})
    assert r.status_code == 422
