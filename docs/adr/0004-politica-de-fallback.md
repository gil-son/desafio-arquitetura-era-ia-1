# 0004. Política de fallback (técnico e com modelo fraco), por feature

- Status: aceita
- Data: 2026-11-26
- Nível: solução

## Contexto

Providers caem. O fallback técnico (ir para o equivalente `large` no outro
provider) é barato e invisível: os dois `large` dão a mesma saída. Já o fallback
para modelo fraco (`mini`) é decisão de **produto**, não só de infra: a pergunta
não é "o gateway consegue?", é "uma resposta pior é melhor que nenhuma, para quem
consome esta feature?". Antes de decidir, medimos o que o `mini` devolve em cada
tarefa, direto no provider.

## Evidência medida (mini vs large, no provider simulado)

- **classify**: idêntico large/mini (o gerador não ramifica por tamanho).
- **topics**: idêntico large/mini.
- **suggest**: mini gera texto mais curto, mesma estrutura e sentido.
- **extract**: **diverge de forma crítica.** Com o texto
  `"Nota fiscal 998877. Quero trocar o pedido #605065, veio um fone de ouvido bluetooth"`:
  - large → `{"order_number":"#605065","product":"fone de ouvido bluetooth"}`
  - mini  → `{"order_number":"#998877","product":null}` (pegou a **nota fiscal** como
    pedido e não achou o produto)

## Decisão

Fallback **técnico** para toda capacidade: primário → equivalente `large` no outro
provider. Fallback com **modelo fraco** decidido feature a feature:

| Feature | Sem nenhum `large` disponível | Por quê |
|---|---|---|
| F1 classification | **aceita `mini`** (gpt-fake-mini) | classify é idêntico large/mini: zero perda. |
| F2 suggestion | **aceita `mini`** (claude-fake-mini) | texto mais curto, mesmo sentido; para o atendente, uma sugestão encurtada é melhor que tela vazia. |
| F3 topics | **aceita `mini`** (claude-fake-mini) | topics é idêntico large/mini: zero perda. |
| F4 extraction | **falha explícita** (sem destino fraco) | o mini erra o número do pedido e zera o produto, e a F4 alimenta automação sem revisão humana: um campo errado gera uma troca errada (frete, estoque, cliente). Uma resposta errada é pior que nenhuma. |

Número máximo de tentativas por destino: **primário 2** (1 + 1 retry), **fallback
técnico 2**, **modelo fraco 2** (`num_retries: 1` no gateway). F4 não tem destino
fraco: esgotados os dois `large`, responde erro.

## Consequências

- F4 troca disponibilidade por correção de propósito: prefere falhar a entregar um
  pedido errado para a automação.
- As três outras features ganham disponibilidade sob degradação, sem mudar o que
  entregam de forma perceptível.

## Evidência (`/admin/calls`)

- Primário F1 em `error_500` → 2 tentativas no primário, depois sucesso no
  `anthropic/claude-fake-large`.
- Os dois `large` em `error_500` → F1/F2/F3 respondem via `*-mini`; F4 responde
  `500` (sem chamada a mini).
