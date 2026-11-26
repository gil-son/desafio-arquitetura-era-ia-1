# STEP-BY-STEP — Desafio Arquitetura na Era da IA

Roteiro de execução para levar o helpdesk de "acoplado e síncrono" até "atrás de um AI Gateway, com modo de execução decidido por feature". Segue a ordem sugerida do enunciado (10 passos) e amarra cada tarefa ao critério de aceite que ela fecha.

> **Regra de ouro do desafio:** cada decisão precisa de **nome, nível, motivo e prova**. A prova quase sempre é `/admin/calls` do provider simulado ou uma medição pela borda (`localhost:8000`). Se um ADR afirma algo que você não consegue demonstrar por aí, o ADR ou o código estão errados.

---

## Mapa de fatos já levantados (leitura do código base)

Confirmado lendo `app/helpdesk/`, `edge/nginx.conf`, `provider-fake/README.md` e `provider-fake/app/tasks.py`:

| Fato | Onde | Consequência para a arquitetura |
|---|---|---|
| F1 classify e F4 extract → provider `openai`; F2 suggest e F3 topics → `anthropic` | `config.py`, `llm.py` | Provider/modelo físico estão espalhados e hard-coded. |
| Nome do modelo físico está no código (`CLASSIFICATION_MODEL = "gpt-fake-large"` etc.) | `config.py` | Dor "trocar modelo exige deploy". |
| Chaves dos providers chegam por `env_file: .env` no serviço `app` | `compose.yaml`, `config.py` | Precisam sair do `app` e viver só no gateway (req. 5). |
| Nenhuma chamada tem `timeout` nem política de `retry`; valem os padrões dos SDKs | `llm.py` | SDKs repetem `429`/`5xx` sozinhos e têm timeout longo → estouram os 30 s da borda. |
| Borda encerra com `504` após 30 s sem nenhum byte | `edge/nginx.conf` (`proxy_read_timeout 30s`) | F3 (5000 tickets, lotes de 150 sequenciais) nunca termina a tempo → precisa ser assíncrona. F2 precisa começar a emitir bytes cedo → streaming. |
| F3 processa em lotes de 150, um após o outro | `report.py` | ~34 chamadas sequenciais; não cabe em resposta síncrona. |
| **Diferença large↔mini**: só `extract` (F4) piora de verdade | `tasks.py` l.104-116 | mini pega o **primeiro número de 6 dígitos** (pode ser nota fiscal, não o pedido) e **nunca identifica o produto** (`product=null`). `classify` e `topics` são idênticos large/mini; `suggest` só muda no tamanho do texto. |
| F4 alimenta automação de troca/devolução **sem revisão humana** | `README.md` tabela de contrato | Campo errado = troca errada → para F4, resposta errada é pior que nenhuma. Base para "falhar explícito" no fallback fraco de F4. |
| Preço: `gpt-fake-mini` in/out 0,15/0,60; `claude-fake-mini` 0,80/4,00; large ≈ 2,50-3,00 / 10-15 por 1M | `provider-fake/README.md` | Precisa declarar preços no LiteLLM ou budget nunca estoura. |
| App não tem nenhuma classe abstrata; `schemas.py` tem só pydantic concreto | `app/helpdesk/*` | A (abstração) ≈ 0 em tudo; `llm.py`/`config.py` são importados por várias features (Ca alto) → zona de dor na v1. |

**Decisões de arquitetura já pré-fundamentadas** (a confirmar com medição/evidência, mas é para onde o desenho aponta):

- **F1 classify → síncrono.** Cliente esperando confirmação na tela; saída curta; cabe em < 3 s. Pergunta da árvore: "alguém está esperando agora?" sim; "cabe no orçamento de latência?" sim.
- **F2 suggest → streaming (SSE).** Atendente lê/edita conforme o texto chega; saída longa; primeiro trecho em < 1,5 s. "É consumível aos poucos?" sim.
- **F3 topics → assíncrono (202/Location/Retry-After → status → 303).** Ninguém esperando olhando; 5000 tickets não cabem em 30 s. "Alguém está esperando agora?" não.
- **F4 extract → síncrono.** Automação consome; saída curta; precisa de timeout explícito e resposta ≤ 15 s.
- **Fallback com modelo fraco (mini):**
  - F1 classify: mini == large → **aceitar mini** é seguro (mesma saída).
  - F2 suggest: mini só encurta o texto, sem perder sentido → **aceitar mini** (resposta pior-mas-útil é melhor que nenhuma para o atendente).
  - F3 topics: mini == large → **aceitar mini**.
  - F4 extract: mini erra pedido e zera produto, e alimenta automação sem revisão → **falhar explícito** (não cair para mini).
  - *(Isto é a hipótese; o ADR de fallback precisa trazer a evidência do `/admin/calls` + diff de saída que a sustenta.)*

---

## Passo 0 — Fork e preparação do repositório

- [ ] Fazer fork público de `https://github.com/devfullcycle/desafio-arquitetura-era-ia-1` e trabalhar na `main` do fork. (Este diretório já é o repositório base; confirme o `git remote` aponta para o seu fork antes de dar push.)
- [ ] `git remote -v` — ajustar `origin` para o fork se necessário.
- [ ] Decidir onde o enunciado antigo fica. O `README.md` vai ser **reescrito** por você (seções obrigatórias no fim deste roteiro). Guarde o enunciado se quiser (ele continua no repo base); o arquivo `info` é só uma cópia do enunciado — não precisa versionar.
- [ ] `git status` limpo antes de começar cada tag.

---

## Passo 1 — Reconhecimento

Objetivo: conhecer o terreno antes de tocar em nada.

- [ ] Subir o ambiente:
  ```bash
  cp .env.example .env
  docker compose up -d --build --wait
  curl -s localhost:8000/health
  ```
- [ ] Exercitar as 4 features pela borda:
  ```bash
  curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
    -d '{"ticket_id":"TK-1","text":"Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
  curl -s -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
    -d '{"ticket_id":"TK-1","text":"Meu pedido #481516 não chegou"}'
  curl -s -X POST localhost:8000/tickets/extraction -H "Content-Type: application/json" \
    -d '{"ticket_id":"TK-1","text":"Quero trocar o pedido #605065, veio um fone quebrado"}'
  curl -s -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
    -d '{"start":"2026-08-01","end":"2026-08-01"}'   # um dia só, para não travar ainda
  ```
- [ ] Chamar cada tarefa **direto no provider** nos dois tamanhos (large e mini) e comparar a saída — principalmente `extract`:
  ```bash
  for m in gpt-fake-large gpt-fake-mini; do
    curl -s localhost:8090/openai/v1/chat/completions \
      -H "Authorization: Bearer sk-fake-openai-0001" -H "Content-Type: application/json" \
      -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"TASK: extract\nNF 123456, quero trocar o pedido #605065, fone quebrado\"}]}"
    echo " <- $m"
  done
  ```
  Guarde esses diffs: são a **evidência do ADR de fallback**.
- [ ] Ler `provider-fake/README.md` inteiro (preços, latências, modos de falha, `/admin`).
- [ ] Confirmar os padrões dos SDKs (pista da fricção): `openai` e `anthropic` fazem retries automáticos em `429`/`5xx` e têm timeout longo — cada tentativa vira uma linha em `/admin/calls`.

Nada de alterar `app/` aqui (exceto o experimento temporário de troca de modelo do Passo 2).

---

## Passo 2 — Diagnóstico da v1 (reproduzir as 4 dores)

Objetivo: transformar cada dor em fato observável. Vai tudo para a seção **"Diagnóstico da v1"** do README (comando + resultado observado + trecho de `app/` que é a causa).

- [ ] **Dor 1 — relatório do mês nunca chega (504 na borda).**
  ```bash
  time curl -s -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
    -d '{"start":"2026-08-01","end":"2026-08-31"}'
  ```
  Esperado: `504` perto de 30 s. Causa: `report.py` (lotes sequenciais) + resposta síncrona + `edge/nginx.conf` 30 s.
  Mostrar também que a app **continua trabalhando depois do 504**:
  ```bash
  sleep 5 && curl -s "localhost:8090/admin/calls?last=20"   # chamadas topics ainda chegando
  ```
- [ ] **Dor 2 — atendente espera sem ver nada (F2 síncrona).**
  ```bash
  time curl -s -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
    -d '{"ticket_id":"TK-1","text":"Meu pedido não chegou"}'
  ```
  Esperado: resposta só no fim (saída longa, ~2400 chars a 40 tok/s ≈ vários segundos). Causa: `suggestion.py`/`llm.call_anthropic` sem streaming.
- [ ] **Dor 3 — provider cai e parte do helpdesk para.**
  ```bash
  curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" \
    -d '{"provider":"openai","mode":"error_500"}'
  curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
    -d '{"ticket_id":"TK-1","text":"teste"}'      # F1/F4 quebram, F2/F3 seguem
  curl -s "localhost:8090/admin/calls?last=10"     # ver as tentativas repetidas do SDK
  curl -s -X POST localhost:8090/admin/reset
  ```
  Causa: sem fallback; provider fixo em `config.py`; retries do SDK multiplicam a carga.
- [ ] **Dor 4 — trocar modelo exige mudar código e rebuild.** (única exceção que pode tocar `app/`, e **tem que desfazer antes da tag**)
  - Alterar `CLASSIFICATION_MODEL` em `config.py`, `docker compose up -d --build app`, mostrar em `/admin/calls` que o modelo mudou.
  - `git checkout app/helpdesk/config.py` para desfazer. Causa: nome físico em `config.py`.
- [ ] Escrever a seção "Diagnóstico da v1" no README com os 4 blocos.
- [ ] `curl -s -X POST localhost:8090/admin/reset` e garantir `app/` idêntico ao base (`git diff --stat` vazio em `app/`).

---

## Passo 3 — Testes de caracterização + tag `v1-coupled`

Objetivo: rede de segurança que fixa o comportamento atual (Feathers). Critério: fixa **corpo** das respostas, não só status; ≥ 1 caso de erro de entrada por feature; roda com 1 comando.

- [ ] Escolher ferramenta de teste (pytest + httpx sugerido) e criar `tests/characterization/`.
- [ ] Para cada feature: 1+ caso de sucesso (fixando campos e valores exatos — a saída do provider é determinística) + 1 caso de erro de entrada (ex.: `text` vazio → 422; período invertido em F3 → 422).
  - F3: usar um período pequeno (ex.: 1 dia) para o teste não depender do fluxo lento; fixar `total_tickets` e `topics` observados.
- [ ] Documentar o comando único no README (ex.: `pytest tests/characterization -q`, rodando contra o compose no ar).
- [ ] Rodar, ficar verde. **Congelar:** nesse commit `app/` == base.
  ```bash
  git add tests/ README.md
  git commit -m "test: suíte de caracterização das 4 features (v1)"
  git tag v1-coupled
  ```
- [ ] Não dar push das tags ainda (pode esperar o fim), ou `git push && git push --tags` já.

> ⚠️ A suíte **tem que ser idêntica** entre `v1-coupled` e `v2-decoupled` (`git diff v1-coupled v2-decoupled -- tests/characterization/` vazio). Só na `main` ela muda para o contrato novo.

---

## Passo 4 — Script de métrica + medir a v1

Objetivo: `metrics/` com script que recebe o caminho de `app/helpdesk/` e gera CSV + gráfico A×I com a Main Sequence. **Régua fixa** (req. 3) — não invente.

Régua (implementar exatamente):
- Componente = cada `.py` de `app/helpdesk/` (inclui subpastas), id por caminho com pontos (`adapters.gateway`), **exceto `__init__.py`**.
- Dependência = import (relativo ou absoluto) que resolve para **outro componente** do próprio `app/helpdesk`. Libs externas e stdlib **não contam**.
- Ca = quantos componentes importam este; Ce = quantos este importa.
- I = Ce / (Ce + Ca), ou 0 se ambos 0.
- A = (classes que herdam de `typing.Protocol` ou `abc.ABC`) / (total de classes do módulo), ou 0 se não há classes.
- D = |A + I − 1|. Tudo arredondado a 2 casas.

- [ ] Implementar com `ast` (parsear imports e classes). Cuidado: resolver imports relativos (`from . import x`, `from ..ports import Y`) e absolutos (`from helpdesk import config`) para o nome-de-componente.
- [ ] Gerar `metrics/results/<name>.csv` com cabeçalho **exato** `component,ca,ce,i,a,d`.
- [ ] Gerar gráfico A×I (matplotlib) com a linha Main Sequence (A + I = 1) e a zona de dor marcada.
- [ ] **Validar à mão** 2-3 módulos da v1 (dica final do enunciado: se bater diferente da conta manual, o bug é do script).
- [ ] Medir a v1 sobre um checkout da tag (o script nasce depois da tag):
  ```bash
  git worktree add ../v1 v1-coupled
  python metrics/measure.py ../v1/app/helpdesk --name v1-coupled
  git worktree remove ../v1
  ```
- [ ] Versionar `metrics/results/v1-coupled.csv` + gráfico (commit na `main`/branch de trabalho, não na tag).

---

## Passo 5 — Plano de refatoração + gateway no ar + piloto

Objetivo: `docs/refactoring-plan.md` + subir o LiteLLM + piloto medido em 1 componente.

### 5a. Subir o gateway (LiteLLM) — estrutura
- [ ] Criar `gateway/config.yaml` com `model_list` (nomes **lógicos** → modelos físicos), declarando **preços** de cada modelo (senão budget nunca estoura).
- [ ] Virtual keys + budget + rate limit precisam de **Postgres** → adicionar serviço `db` (postgres) ao compose. **Isso exige um ADR** justificando o serviço a partir do req. 5 (governança).
- [ ] Criar as virtual keys **sem passo manual** (script de bootstrap que roda no `up`, ou config declarativa do LiteLLM). O avaliador sobe tudo com 1 comando.
- [ ] Nomes lógicos sugeridos (capacidades, não modelos): `classify`, `suggest`, `topics`, `extract` — ou por qualidade (`classification-primary` etc.). A app só conhece esses nomes.
- [ ] `grep -rE "gpt-fake|claude-fake" app/` tem que ficar vazio ao final.

### 5b. Escrever o plano
- [ ] Componentes-alvo: `llm.py` (vira porta + adapter do gateway), `config.py` (tira modelo físico), features (deixam de importar `llm`/provider direto).
- [ ] Estratégia por componente: introduzir **porta** (`Protocol`/`ABC`) para o gateway (↑A), inverter dependência (features dependem da porta, não do adapter concreto), só o `main.py` (composição) conhece o adapter concreto.
- [ ] Critério de pronto **baseado na métrica**: nenhum componente de feature na zona de dor; o componente que chama o gateway isolado; A das portas > 0; D baixo.

### 5c. Piloto
- [ ] Refatorar **1 componente só** (ex.: criar `ports.py` com `Protocol` do gateway + `adapters/gateway.py`, e migrar F1 classify para usá-lo via injeção).
- [ ] Rodar a suíte de caracterização (tem que continuar verde) + medir antes/depois e registrar no plano.
- [ ] Registrar **pelo menos uma revisão** do plano (o que a medição/piloto mostrou que mudou o plano original).

---

## Passo 6 — Escalar a refatoração com agente + medir + tag `v2-decoupled`

- [ ] Fazer o handoff para um agente de IA (pode ser este Claude Code). Registrar no plano: o que entregou ao agente, e como testes + métrica foram usados para **aceitar/rejeitar** cada entrega.
- [ ] Refatorar as 4 features para chamar o modelo **só pela porta do gateway**, por nome lógico, com a **chave virtual do gateway** (sem `FAKE_*` no `app`).
- [ ] Trocar o `compose.yaml`: serviço `app` **não** recebe mais as chaves dos providers; recebe só a URL do gateway + a virtual key.
- [ ] Manter comportamento externo idêntico: mesmas rotas, mesmos modos (ainda tudo síncrono nesta tag), **manter `large` atrás de cada capacidade** (mini mudaria a saída fixada pela suíte).
- [ ] Suíte de caracterização verde, **sem alteração** vs v1.
- [ ] Verificações de gateway (mínimo da v2):
  ```bash
  grep -rE "gpt-fake|claude-fake" app/            # vazio
  grep -rE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY|sk-fake-openai|sk-ant-fake" app/   # vazio
  docker compose exec app env | grep -i fake      # vazio
  docker compose config                           # serviço app sem as chaves dos providers
  ```
- [ ] Medir e versionar `metrics/results/v2-decoupled.csv` + gráfico (sobre checkout da tag, mesmo truque do worktree).
- [ ] Commit + `git tag v2-decoupled`.

---

## Passo 7 — Governança + resiliência no gateway

Objetivo: fechar o req. 5 completo e os critérios de gateway.

- [ ] **Troca de modelo por config:** documentar e provar que editar só `gateway/config.yaml` + `docker compose restart gateway` muda o modelo físico (próxima chamada em `/admin/calls` com o novo modelo, **sem** reiniciar `app`).
- [ ] **Governança:** ≥ 1 chave com **budget** e ≥ 1 com **rate limit**. Provar recusa:
  ```bash
  # estourar rate limit → gateway recusa ANTES de chegar no provider
  curl -s "localhost:8090/admin/calls?last=5"   # contagem não aumenta com as recusadas
  ```
- [ ] **Resiliência (toda capacidade):**
  - timeout explícito;
  - retry **limitado** com backoff para falhas transitórias;
  - **fallback técnico** para o destino equivalente no **outro** provider (openai↔anthropic, mesmo tier large).
  - Declarar no README o **nº máximo de tentativas por destino** (primário, fallback técnico, modelo fraco).
- [ ] ⚠️ **Retries não podem se multiplicar.** Desligar os retries do SDK no `app` (`max_retries=0`) OU não usar SDK para falar com o gateway — senão SDK×gateway multiplicam (visível em `/admin/calls`). O provider primário não pode receber mais tentativas do que o README declara.
- [ ] **Fallback com modelo fraco (mini):** configurar por feature conforme a tabela pré-fundamentada acima. F4 **falha explícito** (não cai para mini).
- [ ] Testar cada modo de falha e conferir em `/admin/calls`:
  ```bash
  # primário em error_500 → sucesso via outro provider, tentativas ≤ declarado
  curl -s -X POST localhost:8090/admin/failures -d '{"provider":"openai","model":"gpt-fake-large","mode":"error_500"}' -H "Content-Type: application/json"
  # os dois large em error_500 → cada feature se comporta como a tabela de fallback diz
  curl -s -X POST localhost:8090/admin/reset
  ```

---

## Passo 8 — Modo de execução por feature (`main`) + medir

Objetivo: implementar os modos decididos e cumprir os requisitos de experiência (medidos pela borda).

- [ ] **F1 classify — síncrono** com timeout explícito. Resultado completo ≤ 3 s. Sem pendurar quando provider trava: sucesso (fallback) ou erro explícito ≤ 15 s.
- [ ] **F2 suggest — streaming SSE.** `Content-Type: text/event-stream`; primeiro trecho ≤ 1,5 s (e antes da metade do tempo total); eventos `data:` por trecho, `event: end` no fim.
  - ⚠️ **Nada pode bufferizar**: desligar compressão/buffer no FastAPI (`StreamingResponse`), no gateway e conferir que `edge` não acumula. Testar com `curl -N`.
  - `midstream_error` do provider → emitir `event: error` com `{"ticket_id","message"}` dentro do stream (status 200 já foi).
- [ ] **F3 topics — assíncrono.** `POST` responde `202` + `Location` + `Retry-After` ≤ 1 s. Worker processa os 5000 tickets em background. `GET` status → `200` `{state: pending|running|failed}` enquanto roda, `303` + `Location` para o resultado quando `done`. Falha visível (`failed` + motivo) ≤ 60 s; nunca preso em `running`.
  - Precisa de **worker/fila** (ou background task) + store de estado. Se adicionar serviço (fila/worker/redis) → **ADR** justificando. Background task do FastAPI + store em memória pode bastar (reinício não é cobrado), mas decida e registre.
  - Com os dois providers em `error_500` → o job chega a `failed` com motivo ≤ 60 s.
- [ ] **F4 extract — síncrono** com timeout; fallback técnico large↔large; **sem** fallback para mini (falha explícita se só mini disponível).
- [ ] **Nenhuma requisição pode dar `504` da borda**, inclusive nos cenários de falha.
- [ ] Atualizar/complementar a suíte de testes na `main` para o **contrato novo** (streaming/async). A suíte de caracterização das tags continua sendo o registro do comportamento antigo.
- [ ] Medir e versionar `metrics/results/main.csv` + gráfico.
  - ⚠️ Critério: na `main` **nenhum componente na zona de dor** (A<0,5 ∧ I<0,5 ∧ D≥0,5), exceto declarados no ADR da métrica como estáveis por natureza (e o componente do gateway e os de feature **não** podem ser exceção).
  - ⚠️ O código que chama o gateway fica num **único componente** de `app/`, nenhuma feature o importa; só o ponto de composição (`main.py`) depende dele.

---

## Passo 9 — ADRs + README

### ADRs (`docs/adr/`, um arquivo por decisão, cada um com linha `Nível:`)
Mínimo exigido (req. 7) — pelo menos 1 em cada nível (corporativa / solução / software):
- [ ] Escolha e **posição** do gateway *(solução)*.
- [ ] Capacidades lógicas e mapeamento → modelos físicos *(solução/software)*.
- [ ] **Modo de execução** — ADR único, 1 seção por feature, com a pergunta da árvore de decisão que sustentou cada uma *(solução)*.
- [ ] **Política de fallback** (técnico + modelo fraco) — 1 seção por feature, **com a evidência do provider simulado** (o diff de saída do `extract` mini vs large é a prova de F4) *(solução/produto)*.
- [ ] Governança de chaves, orçamentos e limites *(corporativa — ex.: teto de gasto mensal, quais providers a empresa aceita)*.
- [ ] Leitura da métrica + exceções "estáveis por natureza" declaradas *(software)*.
- [ ] ADR para **cada serviço extra** no compose (db do LiteLLM, worker/fila da F3) justificado a partir de um requisito.

> Teste de cada ADR: consigo provar por `/admin/calls` ou pela borda? Se não, conserto o ADR ou o código.

### README (reescrever; seções obrigatórias)
- [ ] Visão geral (1-2 parágrafos, incl. como o sistema se comporta quando um provider cai).
- [ ] Diagnóstico da v1 (4 dores: comando + resultado + causa no código).
- [ ] Como rodar (subida, testes de caracterização, script de métrica — comandos exatos).
- [ ] Métrica (leitura dos 3 gráficos + exceções declaradas).
- [ ] Tabela de capacidades (capacidade lógica, feature, modelo primário, fallback técnico, política de modelo fraco, nº máx. de tentativas por destino).
- [ ] Tabela de fallback (por feature: o que acontece sem `large` — qual resposta, qual status).
- [ ] Fluxos (por feature: modo escolhido + como consumir + `curl` exato).
- [ ] Troca de modelo (qual arquivo, o que alterar, qual comando).
- [ ] Roteiro de governança (comandos que mostram recusa por orçamento e por limite).
- [ ] Mapa de decisões (tabela: ADR, nível, resumo).

---

## Passo 10 — Verificação final do zero + publicação

- [ ] Clone limpo do fork, subir **só pelo README**:
  ```bash
  cp .env.example .env && docker compose up -d --build --wait
  curl -s localhost:8000/health   # 200, sem passo manual
  ```
- [ ] Percorrer **todos os critérios de aceite** item a item (seção Critérios de Aceite do enunciado), com o provider simulado provocando: derruba 1 provider, derruba os 2 large, troca modelo, estoura orçamento.
- [ ] Conferir invariantes:
  ```bash
  git diff v1-coupled v2-decoupled -- tests/characterization/   # vazio
  grep -rE "gpt-fake|claude-fake" app/                          # vazio
  grep -rE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY|sk-fake-openai|sk-ant-fake" app/  # vazio
  git diff --stat <base> -- provider-fake/ edge/ data/          # vazio (não alterados)
  ```
- [ ] Rodar o script da `main` sobre checkout da `v1-coupled` e conferir que **reproduz** o CSV versionado da tag.
- [ ] `git push origin main && git push --tags`.
- [ ] Entregar o link do fork público.

---

## Checklist de armadilhas (não pule)

1. **Retries multiplicados** (SDK + gateway). Desligue no app. `/admin/calls` denuncia na hora.
2. **Borda 30 s** manda em tudo. Timeouts seus precisam ser menores. F3 tem que ser assíncrona; F2 tem que emitir bytes cedo.
3. **Streaming bufferizado** = reprovado. Teste com `curl -N` pela borda; se vier em bloco, procure o buffer na sua cadeia (FastAPI, gateway, nginx).
4. **LiteLLM não sabe preço dos modelos fake** → sem declarar preço, budget nunca estoura.
5. **Virtual keys sem passo manual** → bootstrap automático; o avaliador sobe com 1 comando.
6. **Não desenhe o código para enganar a fórmula.** A métrica aponta onde olhar; o ADR explica por que a estrutura ficou melhor. Imports artificiais são denunciáveis.
7. **Suíte idêntica entre as duas tags.** Só muda na `main`.
8. **`app/` idêntico ao base na `v1-coupled`.** Desfaça o experimento da dor 4.
9. **F4 extract é a feature onde mini erra de verdade.** O ADR de fallback precisa dessa evidência; a decisão natural é falhar explícito.
10. **Cada serviço extra no compose precisa de ADR.** db do LiteLLM, worker da F3, etc.
