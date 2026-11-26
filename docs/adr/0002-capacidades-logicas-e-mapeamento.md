# 0002. Capacidades lógicas e mapeamento para modelos físicos

- Status: aceita
- Data: 2026-11-26
- Nível: software

## Contexto

Com o gateway no lugar (ADR 0001), falta definir o vocabulário que a aplicação
usa. Se a app conhecesse `gpt-fake-large`/`claude-fake-large`, o acoplamento ao
modelo físico apenas mudaria de lugar. O requisito 5 exige que nenhum nome físico
apareça em `app/`.

## Opções consideradas

1. A aplicação envia o nome físico do modelo ao gateway.
2. A aplicação envia um nome lógico por **feature** (capacidade), e o gateway
   resolve o físico.
3. Um único nome lógico genérico para tudo.

## Decisão

Uma **capacidade lógica por feature**: `classification`, `suggestion`, `topics`,
`extraction`. A aplicação só conhece esses quatro nomes (constante `CAPABILITY` em
cada módulo de feature). O mapeamento capacidade → modelo físico vive em
`gateway/config.yaml`. Um nome único genérico foi descartado porque impediria
roteamento e fallback distintos por feature (ex.: F4 sem modelo fraco — ADR 0004).

Mapeamento primário (os dois `large` são equivalentes):

| Capacidade | Feature | Modelo físico primário |
|---|---|---|
| `classification` | F1 | `openai/gpt-fake-large` |
| `suggestion` | F2 | `anthropic/claude-fake-large` |
| `topics` | F3 | `anthropic/claude-fake-large` |
| `extraction` | F4 | `openai/gpt-fake-large` |

Os destinos técnicos e fracos (`*-fallback`, `*-weak`) são alvos internos de
roteamento do gateway; a aplicação nunca os nomeia.

## Consequências

- `grep -rE "gpt-fake|claude-fake" app/` fica vazio.
- Trocar o físico de uma capacidade é mudança de uma linha no gateway (ADR 0001/
  README "Troca de modelo"), sem tocar na aplicação.
- O único componente que fala com o gateway é `adapters.gateway` (ADR 0007).

## Evidência

```
grep -rE "gpt-fake|claude-fake" app/   # (vazio)
```
`/admin/calls` mostra que cada capacidade lógica chega ao físico esperado (ver
tabela de capacidades no README).
