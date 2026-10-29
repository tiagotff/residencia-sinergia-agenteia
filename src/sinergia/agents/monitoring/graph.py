"""Subgrafo LangGraph do Agente 3, no ciclo Percepção → Decisão → Ação.

    detect (percepção + decisão: base pseudonimizada → regras A01–A05)
      → publish (ação: grava alertas novos com explicação e auditoria) → FIM

Roda de dois jeitos: no grafo do caso, depois de um afastamento válido, e sozinho,
pela CLI ou pela API, no ciclo agendado sobre a base inteira.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sinergia.agents.monitoring.detectors import detect
from sinergia.agents.monitoring.snapshot import build_snapshot
from sinergia.agents.monitoring.writer import AlertWriter
from sinergia.core.clock import Clock
from sinergia.core.rules import RuleCatalog
from sinergia.core.state import CaseState
from sinergia.data.absences import AbsenceRepository
from sinergia.data.alerts import Alert, AlertRepository
from sinergia.data.audit import AuditLog
from sinergia.data.employees import EmployeeRepository

ACTOR = "agente_3_monitoramento"


@dataclass(frozen=True)
class MonitoringDeps:
    """Dependências injetadas no Agente 3."""

    rules: RuleCatalog
    employees: EmployeeRepository
    absences: AbsenceRepository
    alerts: AlertRepository
    audit: AuditLog
    writer: AlertWriter
    clock: Clock
    salt: str


class MonitoringNodes:
    """Nós do subgrafo."""

    def __init__(self, deps: MonitoringDeps) -> None:
        self._deps = deps

    def detect(self, state: CaseState) -> dict[str, Any]:
        """Monta a visão pseudonimizada da base e aplica as regras."""
        reference = _reference_date(state, self._deps.clock)
        employees = self._deps.employees.active()
        absences = self._deps.absences.valid_overlapping(
            reference - timedelta(days=_lookback_days(self._deps.rules)), reference
        )
        snapshot = build_snapshot(reference, employees, absences, self._deps.salt)
        found = detect(snapshot, self._deps.rules.monitoring, self._deps.rules.processing)
        return {
            "monitoring_date": reference.isoformat(),
            "detection": {
                "alerts": [alert.model_dump(mode="json") for alert in found.alerts],
                "suppressed": sorted(found.suppressed),
                "employees": len(employees),
            },
        }

    def publish(self, state: CaseState) -> dict[str, Any]:
        """Grava os alertas novos com a explicação; repetidos são ignorados."""
        detection = state["detection"]
        alerts = [Alert.model_validate(item) for item in detection["alerts"]]
        created = [alert for alert in alerts if self._store(alert)]
        self._audit(state["monitoring_date"], created, detection)
        summary = {
            "reference_date": state["monitoring_date"],
            "created": [alert.fingerprint for alert in created],
            "already_known": len(alerts) - len(created),
            "suppressed": detection["suppressed"],
            "employees": detection["employees"],
        }
        return {"monitoring": summary, "detection": {}}

    def _store(self, alert: Alert) -> bool:
        """Grava um alerta com a explicação redigida."""
        explained = alert.model_copy(update={"explanation": self._deps.writer.explain(alert)})
        return self._deps.alerts.add(explained, self._deps.rules.version, self._deps.clock())

    def _audit(self, reference: str, created: list[Alert], detection: dict[str, Any]) -> None:
        """Registra a execução, sem dados de saúde nos detalhes."""
        rules = sorted(
            {alert.rule_id for alert in created} | ({"A05"} if detection["suppressed"] else set())
        )
        self._deps.audit.record(
            ACTOR,
            "monitoramento",
            f"monitoramento:{reference}",
            rules,
            {"alertas_novos": len(created), "grupos_suprimidos": len(detection["suppressed"])},
        )


def _reference_date(state: CaseState, clock: Clock) -> date:
    """Data informada na execução, ou hoje."""
    given = state.get("monitoring_date")
    return date.fromisoformat(given) if given else clock().date()


def _lookback_days(rules: RuleCatalog) -> int:
    """Quanto histórico o agente precisa ler para todas as regras."""
    monitoring = rules.monitoring
    return max(
        7 * (monitoring.baseline_weeks + 1),
        monitoring.cid_window_days,
        rules.processing.same_cause_window_days,
    )


def build_monitoring_graph(deps: MonitoringDeps) -> CompiledStateGraph:
    """Monta e compila o subgrafo do Agente 3."""
    nodes = MonitoringNodes(deps)
    graph = StateGraph(CaseState)
    graph.add_node("detect", nodes.detect)
    graph.add_node("publish", nodes.publish)
    graph.add_edge(START, "detect")
    graph.add_edge("detect", "publish")
    graph.add_edge("publish", END)
    return graph.compile()
