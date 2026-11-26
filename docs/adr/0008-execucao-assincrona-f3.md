# 0008. Execução assíncrona da F3 com estado em memória (sem fila)

- Status: aceita
- Data: 2026-11-26
- Nível: software

## Contexto

A F3 é assíncrona (ADR 0003): o `202` libera a conexão e um worker produz o
relatório dos 5.000 tickets em background. Falta decidir **onde** roda o worker e
**onde** mora o estado do job. O enunciado não cobra sobreviver a reinício da
aplicação com tarefas em andamento, e manda que cada serviço extra do compose
tenha ADR que o justifique.

## Opções consideradas

1. Fila + worker dedicado (ex.: Redis + processo worker).
2. Banco externo para o estado dos jobs.
3. Worker em thread dentro do próprio `app` + estado em memória.

## Decisão

Worker em **thread** dentro do serviço `app` (`helpdesk/jobs.py`, classe
`ReportJobs`) e **estado do job em memória**. O `POST` cria o job, dispara a thread
e devolve `202`; a thread roda `report.topics` e guarda `done`+resultado ou
`failed`+motivo. A URL de status lê esse estado.

Fila/worker dedicado e banco de jobs foram descartados: adicionariam serviços ao
compose cujo único ganho — sobreviver a reinício — está **fora de escopo**. Seria
peça a mais para operar sem requisito que a sustente. Se a persistência passasse a
ser exigida, a porta para evoluir é trocar o store em memória por um externo, sem
mudar o contrato HTTP.

## Consequências

- Nenhum serviço novo no compose por causa da F3 (só `app`).
- Um relatório em andamento é perdido se o `app` reiniciar — aceito por estar fora
  de escopo.
- `jobs` depende de `report`, `ports` e `schemas` (I=0,75): fica fora da zona de
  dor (ADR 0007).
- A falha é tratada no worker: esgotados os destinos no gateway, a exceção vira
  `failed` com motivo; o job nunca fica preso em `running`.

## Evidência (pela borda)

```
POST /reports/topics {"start":"2026-08-01","end":"2026-08-31"} => 202 + Location + Retry-After
GET  <status> => 200 {"state":"running"} ... => 303 => resultado com total_tickets=5000
# dois providers em error_500 => <status> chega a {"state":"failed","reason":...} em ~9s (< 60s)
```
