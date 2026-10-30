"""Fatos do período, calculados em Python: a única entrada da crew de insights.

Só entram agregados de grupos com pelo menos N pessoas (A05). Não entram matrículas,
pseudônimos, nomes, CID nem alertas individuais (A04): o relatório trata de grupos.
"""

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel

from sinergia.agents.monitoring.detectors import weekly_rate
from sinergia.agents.monitoring.snapshot import build_snapshot, grouped
from sinergia.core.rules import RuleCatalog
from sinergia.data.absences import Absence
from sinergia.data.alerts import StoredAlert
from sinergia.data.employees import Employee
from sinergia.data.tasks import StoredTask, TaskStatus

_GROUP_RULES = {"A01", "A02", "A03"}
SCOPES = {"setor": "setor", "turno": "turno", "funcao": "função"}
DESTINATIONS = {
    "rh_dp": "RH/DP",
    "sesmt": "SESMT",
    "medico_trabalho": "médico do trabalho",
    "gestor": "gestor",
    "coordenacao_rh": "coordenação do RH",
    "coordenacao_sesmt": "coordenação do SESMT",
}
_ALERT_TEXT = {
    "A01": "pico de afastamentos acima da linha de base",
    "A02": "concentração de afastamentos de um mesmo grupo de diagnóstico",
    "A03": "cobertura abaixo do mínimo em função crítica",
}


class Facts(BaseModel):
    """O que o relatório pode afirmar."""

    period_start: date
    period_end: date
    employees: int
    sectors: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    tasks: dict[str, Any]
    suppressed_groups: int
    hidden_groups: list[str] = []  # só para a conferência; nunca vai para a crew


def build_facts(
    reference: date,
    rules: RuleCatalog,
    data: tuple[list[Employee], list[Absence], list[StoredAlert], list[StoredTask]],
    salt: str,
) -> Facts:
    """Calcula os agregados do período que termina na data de referência."""
    employees, absences, alerts, tasks = data
    start = reference - timedelta(days=rules.insights.period_days - 1)
    snapshot = build_snapshot(reference, employees, absences, salt)
    sectors, hidden = grouped(snapshot.members, "sector", rules.monitoring.min_group_size)
    return Facts(
        period_start=start,
        period_end=reference,
        employees=len(employees),
        sectors=[
            _sector(snapshot, name, members, rules) for name, members in sorted(sectors.items())
        ],
        alerts=[_alert(a) for a in alerts if a.rule_id in _GROUP_RULES and _within(a, start)],
        tasks=_tasks(tasks, reference),
        suppressed_groups=len(hidden),
        hidden_groups=sorted(hidden),
    )


def _sector(snapshot, name: str, members: list, rules: RuleCatalog) -> dict[str, Any]:  # noqa: ANN001
    """Taxa da última semana, média das anteriores e a série semanal do setor."""
    weeks = rules.insights.trend_weeks
    series = [round(weekly_rate(snapshot, members, offset) * 100, 1) for offset in range(weeks)]
    previous = series[1:] or [0.0]
    mean = round(sum(previous) / len(previous), 1)
    return {
        "setor": name,
        "pessoas": len(members),
        "taxa_semana_pct": series[0],
        "media_anterior_pct": mean,
        "variacao_pp": round(series[0] - mean, 1),
        "serie_pct": list(reversed(series)),
    }


def _within(alert: StoredAlert, start: date) -> bool:
    """O alerta toca o período do relatório."""
    return alert.period_end >= start


def _alert(alert: StoredAlert) -> dict[str, Any]:
    """Alerta de grupo, sem o grupo de CID nem a explicação livre."""
    return {
        "regra": alert.rule_id,
        "grupo": f"{SCOPES.get(alert.scope_type, alert.scope_type)} {alert.scope}",
        "descricao": _ALERT_TEXT[alert.rule_id],
        "pessoas_no_grupo": alert.group_size,
        "situacao": alert.status,
    }


def _tasks(tasks: list[StoredTask], today: date) -> dict[str, Any]:
    """Encaminhamentos por situação e por destino, e quantos estão vencidos."""
    by_status: dict[str, int] = {}
    open_by_destination: dict[str, int] = {}
    for task in tasks:
        by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
        if task.status is TaskStatus.OPEN:
            label = DESTINATIONS.get(task.destination, task.destination)
            open_by_destination[label] = open_by_destination.get(label, 0) + 1
    overdue = sum(
        1 for t in tasks if t.status is TaskStatus.OPEN and t.due_date and t.due_date < today
    )
    return {
        "por_situacao": by_status,
        "abertas_por_destino": open_by_destination,
        "vencidas": overdue,
    }


def facts_text(facts: Facts) -> str:
    """Os fatos em texto, como a crew recebe (os números aparecem exatamente assim)."""
    lines = [
        f"Período: {facts.period_start:%d/%m/%Y} a {facts.period_end:%d/%m/%Y}.",
        f"Colaboradores ativos: {facts.employees}. Grupos pequenos fora do relatório: "
        f"{facts.suppressed_groups}.",
        "Setores (taxa de afastamento da semana, média das semanas anteriores, variação):",
        *(_sector_line(sector) for sector in facts.sectors),
        "Alertas do período:",
        *([_alert_line(alert) for alert in facts.alerts] or ["- nenhum"]),
        f"Encaminhamentos: {_counts(facts.tasks['por_situacao'])}; "
        f"vencidos: {facts.tasks['vencidas']}.",
        f"Abertos por destino: {_counts(facts.tasks['abertas_por_destino'])}.",
    ]
    return "\n".join(lines)


def _sector_line(s: dict[str, Any]) -> str:
    """Uma linha por setor."""
    return (
        f"- {s['setor']} ({s['pessoas']} pessoas): {_pct(s['taxa_semana_pct'])}, média "
        f"{_pct(s['media_anterior_pct'])}, variação {_pp(s['variacao_pp'])}"
    )


def _alert_line(a: dict[str, Any]) -> str:
    """Uma linha por alerta."""
    return f"- {a['regra']} em {a['grupo']} ({a['pessoas_no_grupo']} pessoas): {a['descricao']}"


def _pct(value: float) -> str:
    """12.5 → '12,5%'."""
    return f"{value:.1f}%".replace(".", ",")


def _pp(value: float) -> str:
    """Variação em pontos percentuais, com sinal."""
    return f"{value:+.1f} p.p.".replace(".", ",", 1)


def _counts(values: dict[str, int]) -> str:
    """{'aberto': 3} → 'aberto 3'."""
    return ", ".join(f"{name} {count}" for name, count in sorted(values.items())) or "nenhum"
