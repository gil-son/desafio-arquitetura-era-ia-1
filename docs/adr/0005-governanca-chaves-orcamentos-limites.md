# 0005. Governança de chaves, orçamentos e limites de IA

- Status: aceita
- Data: 2026-11-26
- Nível: corporativa

## Contexto

Três meses depois de colocar IA em produção, "a conta chegou". Gasto com IA é
custo recorrente de empresa, e um pico (um loop, um relatório pedido em excesso,
uma integração nova) não pode virar uma fatura-surpresa nem derrubar o orçamento
de outras áreas. Isso é decisão de nível corporativo: qual o teto de gasto, quais
providers a empresa aceita, e quem pode gastar quanto — não uma escolha de
implementação de uma feature.

## Opções consideradas

1. Sem governança: cada serviço usa a chave do provider livremente.
2. Governança no código de cada serviço (cada um conta seu próprio gasto).
3. Governança centralizada no gateway: chaves virtuais com orçamento e limite.

## Decisão

Política corporativa, materializada no gateway (ADR 0001):

- **Providers aceitos:** apenas OpenAI e Anthropic (os dois do contrato), atrás do
  gateway. Nenhum outro destino é configurável sem alterar `gateway/config.yaml`.
- **Chaves virtuais por consumidor:** a aplicação usa uma virtual key do gateway
  (`HELPDESK_GATEWAY_KEY`), nunca as chaves dos providers. As chaves são criadas
  sem passo manual no bootstrap (ADR 0006).
- **Teto de gasto (budget):** existe uma chave com orçamento (`GATEWAY_BUDGET_KEY`,
  US$ 0,001 para demonstração; na vida real, o teto mensal de IA). Estourado o
  orçamento, o gateway recusa **antes** de chegar ao provider.
- **Limite de requisições (rate limit):** existe uma chave com `rpm` limitado
  (`GATEWAY_RATELIMIT_KEY`, 2 req/min). Acima do limite, o gateway recusa antes do
  provider.

Governança no código de cada serviço foi descartada: multiplicaria a contagem,
divergiria entre serviços e não impediria o pico de forma central.

## Consequências

- Uma requisição fora do orçamento ou do limite é barrada no gateway e **não
  consome token** do provider.
- Virtual keys/orçamentos exigem um banco (Postgres) — ADR 0006.
- O teto de demonstração (US$ 0,001) é propositalmente baixo para o roteiro; o
  valor de produção é uma decisão de negócio, trocável sem mexer na aplicação.

## Evidência (roteiro de governança no README)

```
# budget: após ~5 chamadas, a próxima é recusada
=> HTTP 429 {"error":{"type":"budget_exceeded",...}}
# rate limit: 3ª requisição no mesmo minuto é recusada
=> HTTP 429 ; o nº de chamadas em /admin/calls NÃO aumenta com as recusadas
```
