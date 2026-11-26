# 0006. Serviços extras do compose: Postgres (db) e bootstrap de chaves

- Status: aceita
- Data: 2026-11-26
- Nível: software

## Contexto

O requisito 5 exige virtual keys com orçamento e limite de requisições. O LiteLLM
guarda chaves virtuais, spend e limites num banco relacional: sem banco, não há
budget nem rate limit persistido. Além disso, as chaves precisam existir **sem
passo manual** (o avaliador sobe tudo com um comando). Cada serviço além de `app`
e `gateway` precisa de justificativa a partir de um requisito.

## Opções consideradas

1. LiteLLM sem banco: só roteamento, sem virtual keys/budget/rate limit.
2. LiteLLM com Postgres, e criação manual das chaves após subir.
3. LiteLLM com Postgres + um serviço de bootstrap que cria as chaves no `up`.

## Decisão

Dois serviços extras, cada um amarrado ao requisito 5 (governança — ADR 0005):

- **`db` (postgres:16-alpine):** backing store das virtual keys, do spend e dos
  limites do LiteLLM. Sem ele, o requisito de budget/rate limit não se sustenta.
- **`gateway-bootstrap`:** container efêmero (roda uma vez e sai) que, com a master
  key, cria as três virtual keys com valores fixos vindos do `.env`
  (app, budget, rate limit). É **idempotente**: se a chave já existe, segue. Assim
  não há passo manual e o `docker compose up --wait` entrega tudo pronto.

A opção sem banco foi descartada por não entregar governança. A criação manual foi
descartada por exigir passo humano, quebrando o "sobe com um comando".

## Consequências

- Duas peças a mais no compose, ambas de infraestrutura do gateway, não da app.
- O `app` depende de `gateway` (saudável) e de `gateway-bootstrap`
  (`service_completed_successfully`), garantindo que a virtual key exista antes da
  primeira chamada.
- O estado do gateway (chaves/spend) vive no Postgres; não é persistido entre
  recriações do volume, o que é suficiente para o desafio.

## Evidência

```
docker compose config   # serviços: provider-fake, edge, db, gateway, gateway-bootstrap, app
docker compose up gateway-bootstrap   # => [bootstrap] key criada: helpdesk-app / budget / rpm
```
