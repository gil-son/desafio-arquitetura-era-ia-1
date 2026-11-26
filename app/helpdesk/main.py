import json

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse

from . import classification, extraction, jobs, suggestion
from .adapters.gateway import build_gateway
from .schemas import Classification, OrderData, PeriodInput, TicketInput, TopicsReport

app = FastAPI(title="Helpdesk")

# Ponto de composição: o único lugar que conhece o adapter concreto do gateway.
gateway = build_gateway()
report_jobs = jobs.ReportJobs()


def _sse(event: str | None, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {payload}\n\n"


@app.get("/health")
def health():
    return {"status": "ok"}


# --- F1 Classificar ticket — SÍNCRONO ---------------------------------------
# "Alguém está esperando agora?" sim. Saída curta, cabe no orçamento (< 3s).
@app.post("/tickets/classification")
def classify_ticket(ticket: TicketInput) -> Classification:
    return classification.classify(ticket, gateway)


# --- F4 Extrair dados do pedido — SÍNCRONO ----------------------------------
# Consumido por automação; saída curta; timeout explícito (responde ou erra <15s).
@app.post("/tickets/extraction")
def extract_order_data(ticket: TicketInput) -> OrderData:
    return extraction.extract(ticket, gateway)


# --- F2 Sugerir resposta — STREAMING (SSE) ----------------------------------
# "É consumível aos poucos?" sim. Atendente lê/edita enquanto o texto chega.
@app.post("/tickets/reply-suggestion")
def suggest_reply(ticket: TicketInput):
    def event_stream():
        try:
            for chunk in suggestion.suggest_stream(ticket, gateway):
                yield _sse(None, {"chunk": chunk})
        except Exception:
            # O status 200 já foi enviado: o erro vai como evento no próprio stream.
            yield _sse("error", {"ticket_id": ticket.ticket_id, "message": "A geração foi interrompida"})
            return
        yield _sse("end", {"ticket_id": ticket.ticket_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Impede o buffer do nginx/borda: os trechos precisam sair peça por peça.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# --- F3 Relatório de temas — ASSÍNCRONO (Request-Reply) ----------------------
# "Alguém está esperando agora?" não. 5.000 tickets não cabem no orçamento da borda.
@app.post("/reports/topics", status_code=202)
def topics_report(period: PeriodInput, response: Response):
    if period.start > period.end:
        raise HTTPException(status_code=422, detail="A data inicial é posterior à data final")
    job_id = report_jobs.submit(period, gateway)
    response.headers["Location"] = f"/reports/topics/status/{job_id}"
    response.headers["Retry-After"] = "5"
    return {"job_id": job_id, "state": "pending"}


@app.get("/reports/topics/status/{job_id}")
def topics_status(job_id: str):
    job = report_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    if job.state == "done":
        return Response(status_code=303, headers={"Location": f"/reports/topics/{job_id}"})
    body: dict = {"state": job.state}
    if job.state == "failed":
        body["reason"] = job.reason
    return JSONResponse(status_code=200, content=body)


@app.get("/reports/topics/{job_id}")
def topics_result(job_id: str) -> TopicsReport:
    job = report_jobs.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Resultado não disponível")
    return job.result
