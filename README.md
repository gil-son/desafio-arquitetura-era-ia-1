# Helpdesk com IA atrás de um AI Gateway

Helpdesk de uma loja online com IA em quatro pontos do atendimento, evoluído de
uma integração acoplada e síncrona para uma arquitetura atrás de um AI Gateway,
com o modo de execução decidido feature a feature e cada decisão registrada em ADR
e comprovada por evidência observável.

## Visão geral

A aplicação (Python 3.12 + FastAPI, em `app/`) não conhece provider, modelo
físico, formato de API nem credencial: ela pede uma **capacidade lógica**
(`classification`, `suggestion`, `topics`, `extraction`) a um **AI Gateway**
(LiteLLM Proxy, serviço `gateway`), por um endpoint OpenAI-compatível e com uma
virtual key do próprio gateway. O gateway mapeia cada capacidade para o modelo
físico, concentra credenciais, orçamento, limites e resiliência, e traduz o
formato para o provider upstream. Dentro de `app/`, o **único componente que fala
com o gateway é `app/helpdesk/adapters/gateway.py`** (`adapters.gateway`); as
features dependem da porta `helpdesk/ports.py`, não do adapter.

**Quando um provider cai**, o gateway tenta o primário (no máximo 2 vezes), depois
o equivalente `large` no outro provider; se os dois `large` estiverem fora, cada
feature se comporta conforme sua política de fallback: F1/F2/F3 aceitam o modelo
fraco (`mini`) e seguem respondendo; **F4 falha explicitamente**, porque alimenta
automação sem revisão humana e o `mini` erraria o número do pedido. Requisições
fora do orçamento ou do limite de requisições são recusadas no gateway, antes de
consumir token do provider. Os modos de execução garantem que nenhuma requisição
termine em `504` da borda: F1/F4 síncronas com timeout, F2 em streaming (SSE) e F3
assíncrona (Request-Reply).

## Diagnóstico da v1

As quatro dores do cenário, reproduzidas na aplicação recebida (tag `v1-coupled`),
pela borda `localhost:8000` e com os modos de falha do provider simulado.

### Dor 1 — o relatório do mês nunca chega (504 da borda)

```
time curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST localhost:8000/reports/topics \
  -H "Content-Type: application/json" -d '{"start":"2026-08-01","end":"2026-08-31"}'
```

Observado: **HTTP 504 em ~30,0s**. Acompanhando `/admin/calls` nos segundos
seguintes, a aplicação **continua chamando o provider** depois do cliente ter
recebido o 504 (cada lote de 150 leva ~9,8s; o mês são ~34 lotes sequenciais).
Causa: `app/helpdesk/report.py` (lotes síncronos, um após o outro) + resposta
síncrona, contra o `proxy_read_timeout 30s` de `edge/nginx.conf`. Ninguém cancela
a tarefa quando a borda desiste.

### Dor 2 — o atendente espera sem ver nada

```
time curl -s -o /dev/null -X POST localhost:8000/tickets/reply-suggestion \
  -H "Content-Type: application/json" -d '{"ticket_id":"TK-1","text":"Meu pedido não chegou"}'
```

Observado: **~15,9s** até qualquer byte; a resposta inteira chega de uma vez no
fim. Causa: `app/helpdesk/suggestion.py` chama o modelo de forma síncrona, sem
streaming; a saída é longa (~2400 chars a 40 tokens/s + 0,8s de TTFT).

### Dor 3 — um provider cai e parte do helpdesk para

```
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" \
  -d '{"provider":"openai","mode":"error_500"}'
curl -s -o /dev/null -w "F1 HTTP %{http_code}\n" -X POST localhost:8000/tickets/classification \
  -H "Content-Type: application/json" -d '{"ticket_id":"TK-1","text":"teste"}'
curl -s "localhost:8090/admin/calls?last=10"
```

Observado: **F1 → HTTP 500**; `/admin/calls` mostra **3 chamadas `classify`, todas
500** (o SDK repete sozinho — retries padrão). A F2 (anthropic) segue respondendo
`200`: "metade do helpdesk parou". Causa: `app/helpdesk/llm.py` sem timeout nem
política de retry (valem os padrões do SDK), provider/modelo fixos em `config.py`
e nenhum fallback.

### Dor 4 — trocar modelo exige mudar código e reconstruir

```
# editar CLASSIFICATION_MODEL em app/helpdesk/config.py (gpt-fake-large -> gpt-fake-mini)
docker compose up -d --build app
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id":"TK-1","text":"teste"}'
curl -s "localhost:8090/admin/calls?last=1"   # model: gpt-fake-mini
```

Observado: a troca só vale depois de **editar `config.py` e reconstruir o serviço
`app`**. Causa: o nome do modelo físico está hard-coded em `app/helpdesk/config.py`.
(Esta é a única alteração em `app/` feita no diagnóstico, desfeita antes da tag
`v1-coupled`.)

## Como rodar

Requer Docker + Docker Compose v2. Sobe tudo com um comando:

```
cp .env.example .env
docker compose up -d --build --wait
curl -s localhost:8000/health         # {"status":"ok"}
```

O `--wait` só retorna com todos os serviços saudáveis (inclui a criação das
virtual keys pelo `gateway-bootstrap`).

### Testes de caracterização / contrato

Rodam pela borda, contra o compose no ar:

```
python -m venv .venv
.venv/bin/pip install -r tests/characterization/requirements.txt
.venv/bin/python -m pytest tests/characterization -q
```

Na `main` a suíte valida o contrato novo (F2 streaming, F3 assíncrona). O registro
do comportamento antigo (tudo síncrono) está nas tags `v1-coupled` e `v2-decoupled`.

### Script de métrica (Main Sequence)

```
.venv/bin/pip install -r metrics/requirements.txt
.venv/bin/python metrics/measure.py app/helpdesk --name main
# gera metrics/results/main.csv (component,ca,ce,i,a,d) e main.png
```

Para medir uma tag, rode o script da sua branch sobre um checkout dela:

```
git worktree add ../v1 v1-coupled
.venv/bin/python metrics/measure.py ../v1/app/helpdesk --name v1-coupled
git worktree remove ../v1
```

## Métrica

Leitura dos três gráficos (`metrics/results/*.png`), pela régua fixa do requisito 3.

- **v1-coupled:** nenhuma abstração (A=0 em tudo). Na zona de dor: `llm` (I=0,20,
  D=0,80) — o hotspot concreto que fala com o provider e é importado pelas 4
  features — mais `config` e `schemas` (D=1,00).
- **v2-decoupled:** nasce a abstração `ports` (A=1,00, D=0,00, sobre a Main
  Sequence) e o `adapters.gateway` (I=0,67, **Ca=1 — só `main` o importa**). As
  features passam a depender da porta; `llm` desaparece. Sobram na zona de dor só
  `config` e `schemas`.
- **main:** igual à v2 mais `jobs` (I=0,75, fora da zona de dor), do modo
  assíncrono da F3.

**Exceções declaradas** (zona de dor por natureza, justificadas no ADR 0007):
`schemas` (tipos de valor do domínio) e `config` (constantes de configuração). O
componente que chama o gateway (`adapters.gateway`) e os componentes de feature
**não** estão na zona de dor e não são exceção.

## Tabela de capacidades

| Capacidade lógica | Feature | Modelo primário | Fallback técnico | Política com modelo fraco | Máx. tentativas por destino |
|---|---|---|---|---|---|
| `classification` | F1 | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | aceita `gpt-fake-mini` | 2 / 2 / 2 |
| `suggestion` | F2 | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | aceita `claude-fake-mini` | 2 / 2 / 2 |
| `topics` | F3 | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | aceita `claude-fake-mini` | 2 / 2 / 2 |
| `extraction` | F4 | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | **sem modelo fraco (falha)** | 2 / 2 / — |

Máx. tentativas por destino = primário / fallback técnico / modelo fraco
(`num_retries: 1` no gateway → 1 tentativa + 1 retry por destino). Configuração em
`gateway/config.yaml`.

## Tabela de fallback

O que cada feature faz quando **não há nenhum modelo `large` disponível** (os dois
`large` em falha):

| Feature | Resposta | Status |
|---|---|---|
| F1 classification | classifica com `gpt-fake-mini` (idêntico ao large) | `200` |
| F2 suggestion | sugere com `claude-fake-mini` (texto mais curto, mesmo sentido) | `200` (stream) |
| F3 topics | gera o relatório com `claude-fake-mini` (idêntico ao large) | `done` |
| F4 extraction | **não usa mini** (erraria o pedido); falha explícita | `500` |

Base da decisão (evidência medida do `mini` vs `large`) no ADR 0004.

## Fluxos

### F1 — Classificar ticket · SÍNCRONO
Resultado completo em até 3s.
```
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id":"TK-00042","text":"Meu pedido #481516 não chegou, urgente"}'
# {"ticket_id":"TK-00042","category":"delivery","priority":"high"}
```

### F2 — Sugerir resposta · STREAMING (SSE)
Primeiro trecho em até 1,5s; use `curl -N` para ver chegando peça a peça.
```
curl -N -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id":"TK-00042","text":"Meu pedido não chegou"}'
# data: {"chunk": "Olá!"}
# data: {"chunk": " Sin"}
# ...
# event: end
# data: {"ticket_id": "TK-00042"}
```
Erro no meio do stream (modo `midstream_error` do provider) chega como
`event: error` dentro do próprio stream.

### F3 — Relatório de temas · ASSÍNCRONO (Request-Reply)
```
# 1) pede o relatório -> 202 com Location e Retry-After
curl -i -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
  -d '{"start":"2026-08-01","end":"2026-08-31"}'
# HTTP/1.1 202 Accepted
# location: /reports/topics/status/<id>
# retry-after: 5

# 2) acompanha o status (200 enquanto roda; 303 quando pronto)
curl -i localhost:8000/reports/topics/status/<id>
# 200 {"state":"running"}  ...  depois:  303 See Other, location: /reports/topics/<id>

# 3) pega o resultado (total_tickets=5000 no mês inteiro)
curl -s localhost:8000/reports/topics/<id>
```

### F4 — Extrair dados do pedido · SÍNCRONO
Resultado completo em ~1s; timeout explícito (responde ou erra em até 15s).
```
curl -s -X POST localhost:8000/tickets/extraction -H "Content-Type: application/json" \
  -d '{"ticket_id":"TK-00042","text":"Quero trocar o pedido #605065, veio um fone de ouvido bluetooth"}'
# {"ticket_id":"TK-00042","order_number":"#605065","product":"fone de ouvido bluetooth"}
```

## Troca de modelo

Trocar o modelo físico por trás de uma capacidade é mudança de **configuração do
gateway**, sem reconstruir nem reiniciar o `app`:

1. Edite `gateway/config.yaml`, no bloco `model_name:` da capacidade (ex.:
   `classification`), a linha `model:` (ex.: `openai/gpt-fake-large` →
   `openai/gpt-fake-mini`).
2. Reinicie **só** o gateway: `docker compose restart gateway`.
3. A próxima chamada aparece em `/admin/calls` com o novo modelo; o serviço `app`
   não foi reiniciado.

## Roteiro de governança

Pela porta do gateway (`localhost:4000`). As chaves são criadas pelo bootstrap.

### Recusa por orçamento (budget)
A chave `sk-helpdesk-budget-0001` tem orçamento de US$ 0,001.
```
for n in $(seq 1 12); do
  curl -s -o /dev/null -w "req $n -> %{http_code}\n" localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer sk-helpdesk-budget-0001" -H "Content-Type: application/json" \
    -d '{"model":"classification","messages":[{"role":"user","content":"TASK: classify\nMeu pedido não chegou, urgente"}]}'
  sleep 3
done
# após ~5 chamadas: HTTP 429 (budget_exceeded)
```

### Recusa por limite de requisições (rate limit)
A chave `sk-helpdesk-rpm-0001` tem `rpm=2`.
```
curl -s "localhost:8090/admin/calls?last=5000" | python3 -c "import sys,json;print('antes:',len(json.load(sys.stdin)))"
for n in 1 2 3 4 5; do
  curl -s -o /dev/null -w "req $n -> %{http_code}\n" localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer sk-helpdesk-rpm-0001" -H "Content-Type: application/json" \
    -d '{"model":"classification","messages":[{"role":"user","content":"TASK: classify\nteste"}]}'
done
curl -s "localhost:8090/admin/calls?last=5000" | python3 -c "import sys,json;print('depois:',len(json.load(sys.stdin)))"
# req 1,2 -> 200 ; req 3,4,5 -> 429 ; o nº de chamadas em /admin/calls sobe só 2 (recusadas não chegam ao provider)
```

## Mapa de decisões

| ADR | Nível | Resumo |
|---|---|---|
| [0001](docs/adr/0001-escolha-e-posicao-do-gateway.md) | solução | Pôr um AI Gateway self-hosted (LiteLLM) entre a aplicação e os providers |
| [0002](docs/adr/0002-capacidades-logicas-e-mapeamento.md) | software | Uma capacidade lógica por feature; mapeamento para o modelo físico no gateway |
| [0003](docs/adr/0003-modo-de-execucao-por-feature.md) | solução | Modo de execução de cada feature (F1 sync, F2 streaming, F3 async, F4 sync) |
| [0004](docs/adr/0004-politica-de-fallback.md) | solução | Fallback técnico para toda capacidade; modelo fraco por feature (F4 falha) |
| [0005](docs/adr/0005-governanca-chaves-orcamentos-limites.md) | corporativa | Governança de chaves, orçamento e limites; providers aceitos |
| [0006](docs/adr/0006-servicos-extras-db-e-bootstrap.md) | software | Serviços extras `db` (Postgres) e `gateway-bootstrap`, justificados pela governança |
| [0007](docs/adr/0007-leitura-da-metrica.md) | software | Leitura da métrica e exceções declaradas (`config`, `schemas`) |
| [0008](docs/adr/0008-execucao-assincrona-f3.md) | software | F3 assíncrona com worker em thread e estado em memória (sem fila) |

## Estrutura

- `app/` — a aplicação do helpdesk (refatorada): `helpdesk/ports.py` (porta),
  `helpdesk/adapters/gateway.py` (único a falar com o gateway), features,
  `helpdesk/jobs.py` (async da F3), `helpdesk/main.py` (composição).
- `gateway/` — `config.yaml` (capacidades, fallback, timeouts, preços) e
  `bootstrap/` (criação das virtual keys sem passo manual).
- `tests/characterization/` — a suíte pela borda.
- `metrics/` — o script da Main Sequence e os resultados das três versões.
- `docs/adr/` e `docs/refactoring-plan.md` — as decisões e o plano/piloto/handoff.
- `provider-fake/`, `edge/`, `data/` — não alterados.
