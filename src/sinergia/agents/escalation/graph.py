"""Subgrafo LangGraph do Agente 4 (baseado em utilidade).

    collect (percepção: pendências do caso, R12/R13 e alertas novos)
      → decide (função de utilidade: destino, urgência e detalhe; grava as propostas)
      ─┬─ sem demanda → FIM
       └─ await_confirmation (interrupt: uma pessoa confirma, cancela ou redireciona)
            → dispatch (ação: abre as tarefas com prazo e registra na auditoria) → FIM

Nenhum encaminhamento vale sem confirmação humana. O prazo das tarefas abertas é
acompanhado pelo ``EscalationService.sweep``, que reescala o que vencer sem resposta.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from sinergia.agents.escalation.demands import alert_demands, case_demands
from sinergia.agents.escalation.models import Demand, EscalationDecision, Proposal
from sinergia.agents.escalation.summary import compose
from sinergia.agents.escalation.utility import allowed, propose
from sinergia.core.clock import Clock
from sinergia.core.domain import AbsenceStatus
from sinergia.core.rules import EscalationRules, RuleCatalog
from sinergia.core.state import CaseState
from sinergia.data.absences import AbsenceRepository
from sinergia.data.alerts import AlertRepository
from sinergia.data.audit import AuditLog
from sinergia.data.tasks import StoredTask, Task, TaskRepository, TaskStatus

ACTOR = "agente_4_escalonamento"


@dataclass(frozen=True)
class EscalationDeps:
    """Dependências injetadas no Agente 4."""

    rules: RuleCatalog
    absences: AbsenceRepository
    alerts: AlertRepository
    tasks: TaskRepository
    audit: AuditLog
    clock: Clock


class EscalationNodes:
    """Nós do subgrafo."""

    def __init__(self, deps: EscalationDeps) -> None:
        self._deps = deps

    def collect(self, state: CaseState) -> dict[str, Any]:
        """Reúne as demandas ainda não encaminhadas."""
        today = self._deps.clock().date()
        demands = self._case(state, today) + self._alerts(state, today)
        fresh = [d for d in demands if not self._deps.tasks.known_demand(d.key)]
        return {"escalation": {"demands": [d.model_dump(mode="json") for d in fresh]}}

    def decide(self, state: CaseState) -> dict[str, Any]:
        """Pontua as alternativas e grava as escolhidas como propostas."""
        today = self._deps.clock().date()
        ids: list[int] = []
        for demand in _demands(state):
            proposals = propose(demand, self._deps.rules.escalation, today)
            ids += self._propose(state, demand, proposals)
        return {"escalation": {**state["escalation"], "task_ids": ids}}

    def route(self, state: CaseState) -> Literal["await_confirmation", "__end__"]:
        """Sem proposta, nada a confirmar."""
        return "await_confirmation" if state["escalation"].get("task_ids") else END

    def await_confirmation(self, state: CaseState) -> dict[str, Any]:
        """Pausa até uma pessoa confirmar os encaminhamentos."""
        tasks = [self._deps.tasks.get(task_id) for task_id in state["escalation"]["task_ids"]]
        decision = interrupt(confirmation_payload(state["session_id"], tasks))
        decided = EscalationDecision.model_validate(decision).model_dump(mode="json")
        return {"escalation": {**state["escalation"], "decision": decided}}

    def dispatch(self, state: CaseState) -> dict[str, Any]:
        """Abre, cancela ou redireciona cada tarefa conforme a decisão."""
        decision = EscalationDecision.model_validate(state["escalation"]["decision"])
        demands = {demand.key: demand for demand in _demands(state)}
        for task_id in state["escalation"]["task_ids"]:
            task = self._deps.tasks.get(task_id)
            self._settle(task, demands[task.demand_key], decision, _reference(state))
        return {"escalation": {**state["escalation"], "dispatched": True}}

    def _case(self, state: CaseState, today: date) -> list[Demand]:
        """Demandas do afastamento válido do caso, se houver."""
        if state.get("processing_status") != AbsenceStatus.VALID.value:
            return []
        absence = self._deps.absences.get(state["protocol"])
        return case_demands(absence, state.get("escalations", []), self._deps.rules, today)

    def _alerts(self, state: CaseState, today: date) -> list[Demand]:
        """Demandas dos alertas criados pelo monitoramento nesta execução."""
        created = (state.get("monitoring") or {}).get("created", [])
        alerts = self._deps.alerts.by_fingerprints(created)
        return alert_demands(alerts, self._deps.rules, today)

    def _propose(self, state: CaseState, demand: Demand, proposals: list[Proposal]) -> list[int]:
        """Grava as propostas da demanda e registra a decisão na auditoria."""
        ids = [self._store(state, demand, proposal) for proposal in proposals]
        self._deps.audit.record(
            ACTOR,
            "encaminhamento_proposto",
            _reference(state),
            [demand.rule_id],
            {"destinos": [p.destination for p in proposals], "demanda": demand.source_ref},
        )
        return [task_id for task_id in ids if task_id is not None]

    def _store(self, state: CaseState, demand: Demand, proposal: Proposal) -> int | None:
        """Grava uma proposta como tarefa ainda não confirmada."""
        rules = self._deps.rules
        task = Task(
            demand_key=demand.key,
            session_id=state["session_id"],
            origin="caso" if state.get("protocol") else "ciclo",
            rule_id=demand.rule_id,
            title=rules.escalation.demands[demand.rule_id].title,
            subject=demand.subject,
            summary=compose(demand, proposal.destination, rules.escalation),
            primary_choice=proposal.primary,
            deadline=demand.deadline,
            rules_version=rules.version,
            **proposal.model_dump(include={"destination", "urgency", "detail", "utility"}),
            breakdown=proposal.breakdown,
        )
        return self._deps.tasks.add(task, self._deps.clock())

    def _settle(
        self, task: StoredTask, demand: Demand, decision: EscalationDecision, reference: str
    ) -> None:
        """Aplica a decisão humana a uma tarefa: cancela, ou abre (talvez redirecionada)."""
        now = self._deps.clock()
        signed = {"decided_by": decision.reviewer, "note": decision.note}
        if task.id in decision.cancel:
            self._deps.tasks.update(task.id, now, status=TaskStatus.CANCELLED, **signed)
            self._record(decision.reviewer, "encaminhamento_cancelado", reference, task)
            return
        changes = _redirect(task, demand, decision, self._deps.rules.escalation)
        due = due_date(now.date(), task.urgency, task.deadline, self._deps.rules.escalation)
        self._deps.tasks.update(
            task.id, now, status=TaskStatus.OPEN, due_date=due, **signed, **changes
        )
        self._record(decision.reviewer, "encaminhamento_confirmado", reference, task, changes)

    def _record(
        self, actor: str, action: str, reference: str, task: StoredTask, changes: dict | None = None
    ) -> None:
        """Auditoria do encaminhamento, sem dado de saúde."""
        destination = (changes or {}).get("destination", task.destination)
        details = {"tarefa": task.id, "destino": destination, "urgencia": task.urgency}
        self._deps.audit.record(actor, action, reference, [task.rule_id], details)


def _demands(state: CaseState) -> list[Demand]:
    """Demandas guardadas no estado."""
    return [Demand.model_validate(item) for item in state["escalation"].get("demands", [])]


def _reference(state: CaseState) -> str:
    """Protocolo do caso, ou a sessão do ciclo de monitoramento."""
    return state.get("protocol") or state["session_id"]


def _redirect(
    task: StoredTask, demand: Demand, decision: EscalationDecision, rules: EscalationRules
) -> dict[str, Any]:
    """Novo destino escolhido pela pessoa, com o texto refeito para ele."""
    destination = decision.redirect.get(task.id)
    if destination is None or destination == task.destination:
        return {}
    return {"destination": destination, "summary": compose(demand, destination, rules)}


def check_decision(
    decision: EscalationDecision, tasks: list[StoredTask], rules: EscalationRules
) -> None:
    """Recusa ids de outra sessão e redirecionamentos proibidos, antes de retomar."""
    by_id = {task.id: task for task in tasks}
    unknown = (set(decision.cancel) | set(decision.redirect)) - set(by_id)
    if unknown:
        raise ValueError(f"Encaminhamentos que não são desta confirmação: {sorted(unknown)}")
    for task_id, destination in decision.redirect.items():
        if destination not in rules.chain:
            raise ValueError(f"Destino desconhecido: {destination}")
        stub = Demand(
            key="", rule_id=by_id[task_id].rule_id, subject="", source_ref="", max_detail="agregado"
        )
        if not allowed(stub, destination, rules):
            raise ValueError("O gestor não recebe encaminhamentos com dado de saúde.")


def due_date(today: date, urgency: str, deadline: date | None, rules: EscalationRules) -> date:
    """Prazo da área: hoje + SLA da urgência, sem passar do prazo legal ainda possível."""
    due = today + timedelta(days=rules.urgencies[urgency].sla_days)
    if deadline is None:
        return due
    return min(due, deadline) if deadline >= today else today


def confirmation_payload(session_id: str, tasks: list[StoredTask]) -> dict[str, Any]:
    """O que a pessoa vê para confirmar (o texto já respeita o que cada destino pode ver)."""
    fields = {
        "id",
        "rule_id",
        "title",
        "destination",
        "urgency",
        "detail",
        "subject",
        "summary",
        "utility",
        "breakdown",
        "primary_choice",
        "deadline",
    }
    return {
        "kind": "escalation",
        "session_id": session_id,
        "tasks": [task.model_dump(mode="json", include=fields) for task in tasks],
    }


def build_escalation_graph(deps: EscalationDeps) -> CompiledStateGraph:
    """Monta e compila o subgrafo do Agente 4."""
    nodes = EscalationNodes(deps)
    graph = StateGraph(CaseState)
    graph.add_node("collect", nodes.collect)
    graph.add_node("decide", nodes.decide)
    graph.add_node("await_confirmation", nodes.await_confirmation)
    graph.add_node("dispatch", nodes.dispatch)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "decide")
    graph.add_conditional_edges("decide", nodes.route)
    graph.add_edge("await_confirmation", "dispatch")
    graph.add_edge("dispatch", END)
    return graph.compile()
