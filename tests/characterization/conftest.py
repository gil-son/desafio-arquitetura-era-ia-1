"""Configuração da suíte de caracterização.

A suíte exercita as 4 features do helpdesk pela API HTTP, sempre pela BORDA
(o mesmo caminho que o avaliador usa), e fixa o corpo das respostas observado
na aplicação recebida (v1-coupled). As saídas do provider-fake são
determinísticas, então os valores fixados são estáveis.
"""

import json
import os
import pathlib

import httpx
import pytest

# Porta de entrada oficial do helpdesk (a borda nginx). Sobrescrevível por env.
HELPDESK_URL = os.environ.get("HELPDESK_URL", "http://localhost:8000")
# O provider simulado, usado só para garantir o modo normal antes da suíte.
PROVIDER_URL = os.environ.get("PROVIDER_URL", "http://localhost:8090")

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session", autouse=True)
def provider_normal_mode():
    """Garante que o provider-fake está em modo normal e sem falhas configuradas.

    A suíte de caracterização mede o comportamento de referência, não os modos
    de falha. O enunciado permite que os testes usem os endpoints /admin.
    """
    try:
        httpx.post(f"{PROVIDER_URL}/admin/reset", timeout=5)
    except httpx.HTTPError:
        pass  # Se o provider não estiver acessível, os próprios testes falham com mensagem clara.
    yield


@pytest.fixture(scope="session")
def client():
    # Timeout folgado: a F2/F3 na v1 são síncronas e lentas (saída longa / lotes).
    with httpx.Client(base_url=HELPDESK_URL, timeout=60) as c:
        yield c
