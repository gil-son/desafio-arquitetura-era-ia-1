#!/usr/bin/env python3
"""Cria as virtual keys do gateway sem passo manual.

Roda uma vez, depois que o gateway fica saudável (depends_on no compose), usando
a master key. É idempotente: se a chave já existe, segue em frente.

Cria três chaves com valores fixos (vindos do .env), para que o serviço app e o
roteiro de governança possam referenciá-las sem descobrir nada em runtime:

  - HELPDESK_GATEWAY_KEY    : chave da aplicação, orçamento alto, todas as capacidades
  - GATEWAY_BUDGET_KEY      : orçamento baixo (US$ 0,01), para demonstrar recusa por budget
  - GATEWAY_RATELIMIT_KEY   : limite de 2 req/min, para demonstrar recusa por rate limit
"""

import json
import os
import time
import urllib.error
import urllib.request

GATEWAY = os.environ.get("GATEWAY_BASE_URL", "http://gateway:4000")
MASTER = os.environ["LITELLM_MASTER_KEY"]
MODELS = ["classification", "suggestion", "topics", "extraction"]

KEYS = [
    {"key": os.environ["HELPDESK_GATEWAY_KEY"], "max_budget": 1000.0, "key_alias": "helpdesk-app"},
    {"key": os.environ["GATEWAY_BUDGET_KEY"], "max_budget": 0.01, "key_alias": "helpdesk-budget-demo"},
    {"key": os.environ["GATEWAY_RATELIMIT_KEY"], "rpm_limit": 2, "key_alias": "helpdesk-rpm-demo"},
]


def post(path: str, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{GATEWAY}{path}",
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_ready() -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{GATEWAY}/health/liveliness", timeout=5):
                return
        except urllib.error.URLError:
            time.sleep(2)
    raise SystemExit("gateway não respondeu a tempo")


def ensure_key(spec: dict) -> None:
    payload = {"models": MODELS, "duration": None, **spec}
    status, body = post("/key/generate", payload)
    alias = spec.get("key_alias", "?")
    if status == 200:
        print(f"[bootstrap] key criada: {alias}")
        return
    # Já existe (valor de key duplicado) ou erro tolerável: não falhar o compose.
    lowered = body.lower()
    if "already exists" in lowered or "duplicate" in lowered or status in (400, 409):
        print(f"[bootstrap] key já existia: {alias} (status {status})")
        return
    raise SystemExit(f"[bootstrap] falha ao criar {alias}: {status} {body}")


def main() -> None:
    wait_ready()
    for spec in KEYS:
        ensure_key(spec)
    print("[bootstrap] concluído")


if __name__ == "__main__":
    main()
