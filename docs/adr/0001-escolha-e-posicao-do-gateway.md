# 0001. Pôr um AI Gateway self-hosted (LiteLLM) na frente dos providers

- Status: aceita
- Data: 2026-11-26
- Nível: solução

## Contexto

Na v1 cada feature chamava o SDK do provider direto do código: provider, modelo
físico, formato de API e credencial estavam espalhados por `llm.py`/`config.py` e
importados por todas as features. A métrica confirmou o acoplamento: `llm`
(I=0,20, A=0, D=0,80) na zona de dor, importado por 4 features. Trocar modelo
exigia deploy; não havia timeout, retry controlado nem fallback; as chaves dos
providers viviam no ambiente do serviço `app`.

## Opções consideradas

1. Biblioteca de abstração só no código (um wrapper interno), sem processo separado.
2. Gateway SaaS (hospedado por terceiros).
3. Gateway self-hosted como serviço no compose (LiteLLM Proxy).

## Decisão

Gateway self-hosted **LiteLLM Proxy** como serviço `gateway` no compose, único
ponto que conhece provider, modelo físico, formato e credencial. A aplicação
passa a pedir uma **capacidade lógica** por um endpoint OpenAI-compatível, com uma
virtual key do próprio gateway. SaaS foi descartado porque o avaliador precisa
subir tudo localmente, sem serviço externo. Um wrapper só em código não tiraria
credencial, custo, limites e resiliência de dentro da aplicação — o ponto da
inversão de dependência aplicada à IA.

Posição: o gateway fica **entre a aplicação e os providers**. Governança,
resiliência e tradução de formato moram nele; a aplicação só fala OpenAI-compat.

## Consequências

- Melhora: trocar modelo vira configuração (ADR 0002); credenciais e governança
  num lugar só (ADR 0005); resiliência uniforme por capacidade (ADR 0004).
- Custo: mais uma peça a operar, que precisa de banco para virtual keys/orçamentos
  (ADR 0006).
- A aplicação não usa mais o SDK `anthropic`; o LiteLLM traduz o formato OpenAI
  para o provider upstream de cada capacidade.

## Evidência

`docker compose config` mostra o serviço `gateway`. Uma chamada por nome lógico
aparece em `/admin/calls` com o modelo físico correto:

```
curl -s localhost:4000/v1/chat/completions -H "Authorization: Bearer sk-helpdesk-app-0001" \
  -H "Content-Type: application/json" \
  -d '{"model":"classification","messages":[{"role":"user","content":"TASK: classify\nMeu pedido não chegou"}]}'
# /admin/calls => provider: openai, model: gpt-fake-large, task: classify, status: 200
```
