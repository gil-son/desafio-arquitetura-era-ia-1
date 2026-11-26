# Plano de refatoração — da v1 acoplada à v2 atrás do gateway

Objetivo: tirar o provider, o modelo físico, o formato da API e a credencial de
dentro das features, invertendo a dependência para uma porta (abstração). O
comportamento externo não muda (a suíte de caracterização é o juiz); a prova de
que a estrutura melhorou é a métrica da Main Sequence (o juiz determinístico ao
lado do agente de IA, que não é confiável para avaliar o próprio trabalho).

## Ponto de partida (medição da v1-coupled)

Zona de dor na v1 (A < 0,5 ∧ I < 0,5 ∧ D ≥ 0,5): `llm` (I=0,20, A=0, D=0,80),
`config` (D=1,00), `schemas` (D=1,00). Nenhuma abstração em todo o pacote (A=0
em todos os 9 componentes). `llm` é o hotspot: é o componente concreto que fala
com o provider e é importado por todas as 4 features — exatamente o acoplamento
que o gateway resolve.

| componente | ca | ce | i | a | d |
|---|---|---|---|---|---|
| main | 0 | 5 | 1.00 | 0.00 | 0.00 |
| report | 1 | 4 | 0.80 | 0.00 | 0.20 |
| classification | 1 | 3 | 0.75 | 0.00 | 0.25 |
| extraction | 1 | 3 | 0.75 | 0.00 | 0.25 |
| suggestion | 1 | 3 | 0.75 | 0.00 | 0.25 |
| tickets | 1 | 1 | 0.50 | 0.00 | 0.50 |
| llm | 4 | 1 | 0.20 | 0.00 | 0.80 |
| schemas | 5 | 0 | 0.00 | 0.00 | 1.00 |
| config | 6 | 0 | 0.00 | 0.00 | 1.00 |

## Componentes-alvo e estratégia

| componente-alvo | problema na v1 | estratégia |
|---|---|---|
| `llm` (vira `adapters.gateway`) | concreto, acoplado aos 2 SDKs e aos 2 providers; importado por todas as features (Ca=4) na zona de dor | **inverter a dependência**: criar a porta `ports.LLMGateway` (Protocol). O código que fala com o gateway passa a ser um único adapter concreto que *implementa* a porta. Só o ponto de composição (`main.py`) o conhece. |
| `classification`, `suggestion`, `extraction`, `report` | dependem do concreto `llm` e de `config` (modelo físico) | passam a **depender da porta** (abstração), recebendo o gateway por injeção. Não importam mais o adapter nem o nome do modelo físico; cada feature conhece só o seu **nome lógico de capacidade**. |
| `config` | guarda nome de modelo físico e credenciais | perde os modelos físicos e as chaves dos providers; mantém só configuração estável (URL/chave do gateway, parâmetros do relatório). Fica **estável por natureza**. |
| `schemas` | tipos de valor do domínio (pydantic) | inalterado; é **estável por natureza** (tipo de valor que quase nunca muda). |
| `ports` (novo) | não existia abstração | nasce com o `Protocol` da capacidade de LLM — o ponto de inversão. A alto, estável. |

## Critério de pronto (baseado na métrica)

1. Existe abstração: `ports` com A = 1,0, próximo da Main Sequence (D ≈ 0).
2. O componente que chama o gateway (`adapters.gateway`) **não está na zona de dor** e tem Ca = 1 (só `main`). Nenhuma feature o importa.
3. As 4 features saem da leitura "concreto + instável + longe da sequência": passam a depender da porta; nenhuma fica na zona de dor.
4. Os únicos componentes que restarem na zona de dor são `config` e `schemas`, **declarados estáveis por natureza** no ADR da métrica (nunca o gateway-caller nem as features).
5. A suíte de caracterização passa sem alteração (comportamento externo idêntico).
6. `grep -rE "gpt-fake|claude-fake" app/` e `grep -rE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY" app/` não retornam nada.

## Piloto (um único componente antes de escalar)

Componente escolhido: **F1 `classification`** — é a feature mais simples (saída
curta, sem streaming nem lotes), então isola a mudança estrutural do resto.

Passos do piloto:
1. Criar `ports.py` com `LLMGateway` (Protocol) expondo `complete(capability, task, content) -> str`.
2. Criar `adapters/gateway.py` com `GatewayClient` (implementa a porta, fala com o LiteLLM por nome lógico, usando a virtual key do gateway).
3. Migrar `classification.classify` para receber a porta por injeção e usar a capacidade lógica `"classification"`, deixando de importar `llm` e `config`.
4. Ligar no `main.py` (composição): instanciar `GatewayClient` e injetar na rota da F1.
5. Rodar a suíte de caracterização (F1 tem que continuar idêntica) e **medir antes/depois**.

### Medição do piloto

Piloto executado em `classification` (criados `ports` e `adapters.gateway`; F2–F4
ainda em `llm`). Medição do working tree:

| componente | antes (i/a/d) | depois (i/a/d) | leitura |
|---|---|---|---|
| classification | 0.75 / 0.00 / 0.25 | 0.67 / 0.00 / 0.33 | deixou de importar `llm`/`config`; passou a depender da porta `ports` |
| ports (novo) | — | 0.00 / 1.00 / 0.00 | abstração nova, **sobre a Main Sequence** (D=0) |
| adapters.gateway (novo) | — | 0.67 / 0.00 / 0.33 | gateway-caller isolado, **Ca=1 (só `main`)**, fora da zona de dor |
| llm | 0.20 / 0.00 / 0.80 | 0.25 / 0.00 / 0.75 | perdeu 1 dependente (Ca 4→3); some quando todas migrarem |

Validação de comportamento do piloto: a capacidade lógica `classification`,
chamada pelo gateway, devolve `{"category":"delivery","priority":"high"}` para o
ticket de referência — idêntico ao golden fixado pela suíte de caracterização.

## Revisão do plano

**Revisão 1 — o adapter depende da porta explicitamente.** No plano original o
adapter implementaria `LLMGateway` só por *structural typing* (sem importar
`ports`). A conta da métrica mostrou que, assim, `adapters.gateway` teria
Ce=1 (só `config`) → I=0,50, parado exatamente na borda da zona de dor (frágil a
qualquer releitura do critério). Revisão: a fábrica `build_gateway() -> LLMGateway`
usa a porta como tipo de retorno, então o adapter importa e depende de `ports`
(Ce=2 → I=0,67), saindo com folga da zona de dor e tornando explícita a
dependência da abstração. Não foi um import artificial: o retorno tipado pela
abstração é a própria intenção do ponto de composição.

## Handoff para o agente de IA

A refatoração foi conduzida com um agente de IA (Claude) a partir deste pacote de
handoff:

- **Entregue ao agente:** este plano (componentes-alvo, estratégia, critério de
  pronto), a suíte de caracterização **verde** na `v1-coupled`, o script de
  métrica com a régua fixa, e os números-alvo (nenhuma feature nem o
  gateway-caller na zona de dor; abstração presente com A>0).
- **Métrica e testes como juízes:** cada entrega do agente só foi aceita se
  (1) a suíte de caracterização passasse sem alteração **e** (2) a medição não
  deixasse nenhuma feature nem `adapters.gateway` na zona de dor. Caso contrário,
  a entrega era rejeitada e devolvida citando o número que violou o critério.
  Exemplo real de rejeição/ajuste: a borda de I=0,50 do adapter (ver Revisão 1),
  corrigida antes de escalar.
- **Resultado:** ver `metrics/results/v2-decoupled.csv` e o gráfico; a leitura
  final e as exceções declaradas estão no ADR da métrica (`docs/adr/0008-...`).
