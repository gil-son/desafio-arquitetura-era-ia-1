import os

# A aplicação só conhece a base URL e a virtual key do GATEWAY. Nenhum nome de
# modelo físico e nenhuma chave de provider vivem aqui: isso é do gateway.
GATEWAY_BASE_URL = os.environ["GATEWAY_BASE_URL"]
GATEWAY_API_KEY = os.environ["HELPDESK_GATEWAY_KEY"]
# Timeout de rede do adapter. Folgado o bastante para não cortar a F2 síncrona
# da v2 (saída longa, ~16s, igual à v1). Os orçamentos de latência por feature
# (requisito 6) são impostos pelos modos de execução/gateway na main, não aqui.
GATEWAY_TIMEOUT = 60.0

MAX_OUTPUT_TOKENS = 2000

TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
