"""Execução assíncrona do relatório de temas (F3).

A F3 lê 5.000 tickets em lotes sequenciais — não cabe no orçamento de latência da
borda (30s). O padrão Asynchronous Request-Reply libera a conexão: o POST aceita
o pedido (202) e um worker em background produz o relatório; o cliente acompanha
por uma URL de status.

Estado em memória (o enunciado não cobra sobreviver a reinício). Um relatório que
não termina com sucesso vira `failed` com motivo — nunca fica preso em `running`.
"""

import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from . import report
from .ports import LLMGateway
from .schemas import PeriodInput, TopicsReport


@dataclass
class Job:
    state: str = "pending"  # pending | running | done | failed
    reason: Optional[str] = None
    result: Optional[TopicsReport] = None


class ReportJobs:
    """Store em memória + worker em thread para o relatório de temas."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, period: PeriodInput, gateway: LLMGateway) -> str:
        job_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._jobs[job_id] = Job()
        thread = threading.Thread(target=self._run, args=(job_id, period, gateway), daemon=True)
        thread.start()
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job_id: str, period: PeriodInput, gateway: LLMGateway) -> None:
        self._update(job_id, state="running")
        try:
            result = report.topics(period, gateway)
            self._update(job_id, state="done", result=result)
        except Exception as exc:  # falha de provider, timeout, etc.
            self._update(job_id, state="failed", reason=str(exc)[:200])

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                for key, value in changes.items():
                    setattr(job, key, value)
