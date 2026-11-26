# 0007. Leitura da métrica de acoplamento e exceções declaradas

- Status: aceita
- Data: 2026-11-26
- Nível: software

## Contexto

A refatoração precisa de um critério de pronto observável, não de opinião. A Main
Sequence (módulo 02) transforma a estrutura em medida: cada componente vira um
ponto A × I, e a zona de dor (A < 0,5 ∧ I < 0,5 ∧ D ≥ 0,5) aponta onde olhar. A
régua (requisito 3) é fixa; o script em `metrics/` a aplica igual nas três
versões. Foi validado à mão nos 9 componentes da v1.

## Leitura das três medições

- **v1-coupled:** `llm` (I=0,20, D=0,80), `config` e `schemas` (D=1,00) na zona de
  dor; A=0 em todo o pacote (nenhuma abstração). `llm` é o hotspot: concreto, fala
  com o provider, importado por 4 features.
- **v2-decoupled:** nasce `ports` (A=1,00, D=0,00, sobre a Main Sequence) e
  `adapters.gateway` (I=0,67, Ca=1 — só `main`). As features passam a depender da
  porta (abstração). `llm` desaparece. Sobram na zona de dor só `config` e
  `schemas`.
- **main:** igual à v2 mais o componente `jobs` (I=0,75, fora da zona de dor), do
  modo assíncrono da F3 (ADR 0008). A zona de dor segue com `config` e `schemas`.

## Decisão

Declarar **`config` e `schemas` como estáveis por natureza**, exceções à zona de
dor:

- `schemas`: tipos de valor do domínio (pydantic). São contratos de dados que
  quase nunca mudam; é esperado e saudável que muitos dependam deles (Ca alto) e
  que não tenham abstração. Concreto e estável por natureza.
- `config`: constantes de configuração (URL e virtual key do gateway, parâmetros
  do relatório). Também é um ponto estável e concreto por natureza.

Não são exceção, e não estão na zona de dor na `main`: `adapters.gateway` (o
componente que chama o gateway) nem nenhuma feature — como o requisito exige.

Não desenhamos o código em função da fórmula (nada de import artificial para tirar
módulo da zona): a abstração `ports` existe porque inverte a dependência de LLM de
verdade; a melhora na métrica é consequência, não objetivo.

## Consequências

- O critério de pronto da refatoração (ADR do plano) é verificável: rodar o script
  e conferir que só as exceções declaradas estão na zona de dor.
- Qualquer regressão futura que jogue uma feature ou o gateway-caller para a zona
  de dor aparece na medição.

## Evidência

```
python metrics/measure.py app/helpdesk --name main
# zona de dor: apenas config e schemas
```
Rodar o script sobre um checkout da `v1-coupled` reproduz `metrics/results/v1-coupled.csv`.
