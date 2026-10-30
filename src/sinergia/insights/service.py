"""Gera, confere e guarda o relatório; o médico do trabalho aprova ou devolve."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from sinergia.core.clock import Clock
from sinergia.core.errors import SessionStateError
from sinergia.core.rules import RuleCatalog
from sinergia.data.absences import AbsenceRepository
from sinergia.data.alerts import AlertRepository
from sinergia.data.audit import AuditLog
from sinergia.data.employees import EmployeeRepository
from sinergia.data.reports import Report, ReportRepository, ReportStatus, StoredReport
from sinergia.data.tasks import TaskRepository
from sinergia.insights.crew import CrewResult
from sinergia.insights.facts import Facts, build_facts, facts_text
from sinergia.insights.guard import check_report
from sinergia.insights.template import template_report

ACTOR = "crew_insights"


class ReportCrew(Protocol):
    """O que o serviço espera da crew (a real ou um dublê nos testes)."""

    def run(self, facts_text: str) -> CrewResult:
        """Roda a crew sobre o texto dos fatos."""
        ...


@dataclass(frozen=True)
class InsightsDeps:
    """Dependências da crew de insights."""

    rules: RuleCatalog
    employees: EmployeeRepository
    absences: AbsenceRepository
    alerts: AlertRepository
    tasks: TaskRepository
    reports: ReportRepository
    audit: AuditLog
    clock: Clock
    salt: str
    crew: ReportCrew | None


class InsightsService:
    """Relatório do período: crew quando possível, relatório padrão quando não."""

    def __init__(self, deps: InsightsDeps) -> None:
        self._deps = deps

    def run(self, reference: date | None = None) -> StoredReport:
        """Gera o rascunho do período que termina na data de referência."""
        facts = self.facts(reference or self._deps.clock().date())
        content, method, issues = self._write(facts)
        report = Report(
            period_start=facts.period_start,
            period_end=facts.period_end,
            method=method,
            content=content,
            facts=facts.model_dump(mode="json"),
            issues=issues,
            rules_version=self._deps.rules.version,
        )
        report_id = self._deps.reports.add(report, self._deps.clock())
        self._deps.audit.record(
            ACTOR,
            "relatorio_gerado",
            f"relatorio:{report_id}",
            ["I01"],
            {"metodo": method, "problemas": len(issues)},
        )
        return self._deps.reports.get(report_id)

    def facts(self, day: date) -> Facts:
        """Agregados do período (também usados pelo painel do SESMT)."""
        deps = self._deps
        employees = deps.employees.active()
        lookback = day - timedelta(days=7 * deps.rules.insights.trend_weeks)
        data = (
            employees,
            deps.absences.valid_overlapping(lookback, day),
            deps.alerts.list(),
            deps.tasks.find(),
        )
        return build_facts(day, deps.rules, data, deps.salt)

    def decide(
        self, report_id: int, approve: bool, by: str, note: str | None = None
    ) -> StoredReport:
        """Aprovação (ou devolução) pelo médico do trabalho."""
        report = self._deps.reports.get(report_id)
        if report.status is not ReportStatus.DRAFT:
            raise SessionStateError(f"O relatório {report_id} já foi {report.status.value}.")
        status = ReportStatus.APPROVED if approve else ReportStatus.RETURNED
        self._deps.reports.decide(report_id, status, by, self._deps.clock(), note)
        self._deps.audit.record(by, f"relatorio_{status.value}", f"relatorio:{report_id}", ["I01"])
        return self._deps.reports.get(report_id)

    def _write(self, facts: Facts) -> tuple[str, str, list[str]]:
        """Texto da crew se passar na conferência; senão, o relatório padrão e o motivo."""
        text = facts_text(facts)
        content, issues = self._from_crew(text, facts.hidden_groups)
        if content is not None:
            return content, "crew", []
        return template_report(facts), "modelo", [f"crew: {issue}" for issue in issues]

    def _from_crew(self, text: str, hidden_groups: list[str]) -> tuple[str | None, list[str]]:
        """O texto aprovado da crew, ou os problemas que o barraram."""
        if self._deps.crew is None:
            return None, ["não configurada (LLM ou extra 'insights' ausente)."]
        try:
            result = self._deps.crew.run(text)
        except Exception as exc:  # noqa: BLE001 — a crew nunca derruba o relatório
            return None, [f"indisponível ({type(exc).__name__})."]
        if not result.approved:
            return None, [f"o revisor de privacidade devolveu: {result.reason}"]
        employee_ids = [e.employee_id for e in self._deps.employees.active()]
        problems = check_report(
            result.content, text, (employee_ids, hidden_groups), self._deps.rules
        )
        return (None, problems) if problems else (result.content, [])
