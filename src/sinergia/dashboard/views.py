"""Dados de cada perfil do painel, sem Streamlit (testáveis).

Cada perfil vê só o que precisa: o gestor nunca vê saúde; o colaborador vê só o próprio
caso; o RH vê prazos e filas; o SESMT vê alertas e o relatório; a auditoria vê a trilha.
O perfil é escolhido na tela por enquanto: o controle de acesso entra com a autenticação.
"""

from datetime import date, timedelta
from typing import Any

from sinergia.bootstrap import Container
from sinergia.core.errors import NotFoundError
from sinergia.data.alerts import StoredAlert
from sinergia.data.tasks import StoredTask, TaskStatus
from sinergia.insights.facts import DESTINATIONS, SCOPES

PROFILES = ("Colaborador", "RH/DP", "Gestor", "SESMT / médico do trabalho", "Auditoria")
HR = ("rh_dp", "coordenacao_rh")
HEALTH = ("sesmt", "medico_trabalho", "coordenacao_sesmt")


def employee_case(container: Container, protocol: str) -> dict[str, Any] | None:
    """O próprio caso: situação, pendências e encaminhamentos (sem CID nem texto clínico)."""
    try:
        intake = container.intakes.get(protocol.strip())
    except NotFoundError:
        return None
    return {
        "protocolo": intake.protocol,
        "recebido_em": f"{intake.received_at:%d/%m/%Y %H:%M}",
        "entrada": intake.status.value,
        "afastamento": _absence(container, intake.protocol),
        "pendencias": [p.kind for p in container.intakes.pendencies_for(intake.protocol)],
        "encaminhamentos": [
            {"assunto": t.title, "area": _label(t.destination), "situacao": t.status.value}
            for t in container.tasks.for_session(intake.session_id)
            if t.rule_id.startswith("R")
        ],
    }


def _absence(container: Container, protocol: str) -> dict[str, Any] | None:
    """Situação do afastamento, sem CID."""
    try:
        absence = container.absences.get(protocol)
    except NotFoundError:
        return None
    return {
        "situacao": absence.status.value,
        "inicio": _br(absence.start_date),
        "fim": _br(absence.last_day),
        "dias": absence.days,
    }


def hr_overview(container: Container, today: date) -> dict[str, Any]:
    """Volume, automação, fila de revisão e prazos do RH/DP."""
    counts = container.absences.status_counts()
    total = sum(sum(by.values()) for by in counts.values())
    automatic = counts.get("valido", {}).get("automatico", 0)
    return {
        "recebidos": container.intakes.count(),
        "afastamentos": total,
        "automatico_pct": round(100 * automatic / total, 1) if total else 0.0,
        "fila_revisao": len(container.review.pending()),
        "tarefas": tasks_table(container, HR, today),
    }


def manager_view(container: Container, today: date, sector: str | None = None) -> dict[str, Any]:
    """Quem está ausente e até quando, e a cobertura de funções críticas (sem saúde)."""
    staff = {e.employee_id: e for e in container.employees.active()}
    absent = []
    for absence in container.absences.valid_overlapping(today, today):
        person = staff.get(absence.employee_id or "")
        if person and (sector is None or person.sector == sector):
            absent.append(
                {
                    "matricula": person.employee_id,
                    "setor": person.sector,
                    "funcao": person.role,
                    "turno": person.shift,
                    "ausente_ate": _br(absence.last_day),
                }
            )
    return {
        "setores": sorted({e.sector for e in staff.values()}),
        "ausentes": sorted(absent, key=lambda row: (row["setor"], row["matricula"])),
        "cobertura": coverage(staff.values(), {row["matricula"] for row in absent}, sector),
        "tarefas": tasks_table(container, ("gestor",), today),
    }


def coverage(staff: Any, absent: set[str], sector: str | None) -> list[dict[str, Any]]:
    """Disponibilidade das funções críticas."""
    roles: dict[str, list[str]] = {}
    for person in staff:
        if person.critical_role and (sector is None or person.sector == sector):
            roles.setdefault(person.role, []).append(person.employee_id)
    return [
        {
            "funcao": role,
            "equipe": len(ids),
            "disponiveis": len(ids) - len(absent & set(ids)),
            "disponivel_pct": round(100 * (len(ids) - len(absent & set(ids))) / len(ids), 1),
        }
        for role, ids in sorted(roles.items())
    ]


def sesmt_view(container: Container, today: date) -> dict[str, Any]:
    """Alertas completos, tendência semanal por setor, tarefas da saúde e relatórios."""
    facts = container.insights.facts(today)
    weeks = len(facts.sectors[0]["serie_pct"]) if facts.sectors else 0
    labels = [(today - timedelta(days=7 * (weeks - 1 - i))).isoformat() for i in range(weeks)]
    trend = {s["setor"]: s["serie_pct"] for s in facts.sectors}
    return {
        "alertas": [_alert_row(a) for a in container.alerts.list()],
        "tendencia": {"semanas": labels, "series": trend},
        "tarefas": tasks_table(container, HEALTH, today),
        "relatorios": container.reports.recent(),
    }


def _alert_row(alert: StoredAlert) -> dict[str, Any]:
    """Alerta completo para a saúde (inclui o grupo de CID), com nomes legíveis."""
    return {
        "id": alert.id,
        "regra": alert.rule_id,
        "grupo": f"{SCOPES.get(alert.scope_type, alert.scope_type)} {alert.scope}",
        "periodo": f"{_br(alert.period_start)} a {_br(alert.period_end)}",
        "pessoas_no_grupo": alert.group_size,
        "grupo_cid": alert.details.get("grupo_cid", ""),
        "situacao": alert.status,
        "explicacao": alert.explanation,
    }


def audit_trail(container: Container, limit: int = 200, actor: str | None = None) -> list[dict]:
    """Trilha de auditoria, mais recente primeiro."""
    return [entry.model_dump(mode="json") for entry in container.audit.recent(limit, actor)]


def tasks_table(container: Container, destinations: tuple[str, ...], today: date) -> list[dict]:
    """Tarefas abertas dos destinos, com o texto já escrito para eles."""
    open_tasks = container.tasks.find(TaskStatus.OPEN)
    return [_task_row(t, today) for t in open_tasks if t.destination in destinations]


def _task_row(task: StoredTask, today: date) -> dict[str, Any]:
    """Uma linha de tarefa."""
    return {
        "id": task.id,
        "regra": task.rule_id,
        "assunto": task.title,
        "area": _label(task.destination),
        "urgencia": task.urgency,
        "prazo": _br(task.due_date),
        "vencida": bool(task.due_date and task.due_date < today),
        "resumo": task.summary,
    }


def _label(destination: str) -> str:
    """Nome da área para a tela."""
    return DESTINATIONS.get(destination, destination)


def _br(value: date | None) -> str:
    """Data em DD/MM/AAAA (ou traço)."""
    return f"{value:%d/%m/%Y}" if value else "—"
