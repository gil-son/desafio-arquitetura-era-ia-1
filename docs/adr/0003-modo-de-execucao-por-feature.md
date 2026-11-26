# 0003. Modo de execução de cada feature

- Status: aceita
- Data: 2026-11-26
- Nível: solução

## Contexto

Uma chamada a LLM demora segundos, custa por token, chega aos poucos e prende
conexões. A borda encerra em `504` após 30s sem bytes. A pergunta não é "qual
modo adotar", é "qual para cada caso de uso". A árvore de decisão: "alguém está
esperando agora?", "cabe no orçamento de latência?", "é consumível aos poucos?".

## Opções consideradas

Para cada feature: síncrono, streaming (SSE) ou assíncrono (Request-Reply).

## Decisão

### F1 — Classificar ticket → SÍNCRONO
Características do contrato: roda na abertura do ticket, com o cliente esperando a
confirmação na tela; saída curta de valores fixos. "Alguém está esperando agora?"
sim. "Cabe no orçamento de latência?" sim (saída curta, < 3s). Não é consumível
aos poucos (é um objeto pequeno). → síncrono, com timeout explícito.

### F2 — Sugerir resposta → STREAMING (SSE)
Características: o atendente olha a tela e começa a ler/editar assim que o texto
aparece; saída longa. "Alguém está esperando agora?" sim, mas "é consumível aos
poucos?" sim. Síncrono deixaria o atendente ~16s olhando para o nada (dor 2). →
streaming: o primeiro trecho chega em ~1s e o texto continua. `Content-Type:
text/event-stream`; erro no meio vai como `event: error` no próprio stream.

### F3 — Relatório de temas → ASSÍNCRONO (Request-Reply)
Características: quem pede é um painel interno que não expõe callback; ninguém fica
esperando; 5.000 tickets em lotes sequenciais não cabem nos 30s da borda. "Alguém
está esperando agora?" não. → assíncrono: `202 Accepted` + `Location` +
`Retry-After`; a URL de status responde `200` (pending/running/failed) e `303`
para o resultado quando pronto. Streaming não serviria: mudaria a espera
percebida mas manteria a conexão presa pelos minutos de processamento.

### F4 — Extrair dados do pedido → SÍNCRONO
Características: alimenta automação de troca/devolução sem revisão humana; saída
curta. Quem consome é uma automação, que faz uma chamada e espera a resposta
estruturada. "Consumível aos poucos?" não (precisa do objeto inteiro para agir).
→ síncrono, com timeout explícito e sem fallback para modelo fraco (ADR 0004).

## Consequências

- F2 exige que nada na cadeia (FastAPI, gateway, borda) acumule o stream; a
  resposta manda `X-Accel-Buffering: no` para a borda não bufferizar.
- F3 ganha capacidade e paga com estado distribuído e mais peças a operar (store
  de jobs + worker em background — ADR 0008).
- Os testes na `main` passam a validar o novo contrato (streaming/assíncrono).

## Evidência (pela borda, `localhost:8000`)

- F1: `curl -w "%{time_total}"` → resultado completo em ~2,4s (< 3s).
- F2: `curl -N` → primeiro trecho de texto em ~1,0s (< 1,5s), chegando peça a peça.
- F3: `POST` → `202` em ~0,01s com `Location`/`Retry-After`; status `running`;
  `303` para o resultado; `total_tickets` = 5000 no mês inteiro.
- F4: `curl -w "%{time_total}"` → resultado completo em ~1s.
