"""Percepção do Agente 4: transforma pendências e alertas em demandas com prazo.

Do caso vêm R10 e R11 (decididas pelo Agente 2) e as regras próprias do agente:
R12 (exame de retorno, NR-7 item 7.5.9) e R13 (indício de origem ocupacional, CAT até o
1º dia útil seguinte — Lei 8.213/1991, art. 22). Dos alertas do Agente 3 vêm A01–A04.
"""

from datetime import date, timedelta

from sinergia.agents.escalation.models import Demand
from sinergia.core.rules import RuleCatalog
from sinergia.data.absences import Absence
from sinergia.data.alerts import StoredAlert

_GROUP_SCOPES = {"setor", "turno", "funcao"}


def case_demands(
    absence: Absence, escalations: list[dict], rules: RuleCatalog, today: date
) -> list[Demand]:
    """Demandas de um afastamento válido."""
    demands = [_legal(absence, item["rule_id"], rules, today) for item in escalations]
    if (absence.days or 0) >= rules.escalation.return_exam_min_days:
        demands.append(_return_exam(absence))
    if _occupational(absence.cid, rules.escalation.occupational_cid_prefixes):
        demands.append(_occupational_origin(absence, rules, today))
    return demands


def _base(absence: Absence, rule_id: str) -> dict:
    """Campos comuns às demandas de um caso (identificação individual)."""
    return {
        "key": f"{rule_id}|{absence.protocol}",
        "rule_id": rule_id,
        "subject": absence.employee_id or "sem matrícula",
        "source_ref": absence.protocol,
        "max_detail": "individual",
        "facts": {
            "dias": absence.days,
            "inicio": _br(absence.start_date),
            "fim": _br(absence.last_day),
        },
        "health_detail": absence.cid[:3] if absence.cid else None,
    }


def _legal(absence: Absence, rule_id: str, rules: RuleCatalog, today: date) -> Demand:
    """R10: prazo é o 16º dia; R11: prazo padrão a partir de hoje."""
    if rule_id == "R10" and absence.start_date:
        deadline = absence.start_date + timedelta(days=rules.processing.inss_threshold_days)
    else:
        deadline = _default_deadline(rule_id, rules, today)
    return Demand(**_base(absence, rule_id), deadline=deadline)


def _return_exam(absence: Absence) -> Demand:
    """R12: o exame precisa acontecer antes do dia de volta."""
    back = absence.last_day + timedelta(days=1) if absence.last_day else None
    demand = Demand(**_base(absence, "R12"), deadline=back)
    demand.facts["retorno"] = _br(back)
    return demand


def _occupational_origin(absence: Absence, rules: RuleCatalog, today: date) -> Demand:
    """R13: indício individual de origem ocupacional, pelo grupo de CID."""
    return Demand(**_base(absence, "R13"), deadline=_default_deadline("R13", rules, today))


def _occupational(cid: str | None, prefixes: list[str]) -> bool:
    """CID começa com um dos prefixos configurados (lesões, exposição ocupacional)."""
    return bool(cid) and any(cid.upper().startswith(prefix) for prefix in prefixes)


def alert_demands(alerts: list[StoredAlert], rules: RuleCatalog, today: date) -> list[Demand]:
    """Uma demanda por alerta novo do Agente 3."""
    return [_from_alert(alert, rules, today) for alert in alerts]


def _from_alert(alert: StoredAlert, rules: RuleCatalog, today: date) -> Demand:
    """Alerta vira demanda agregada (grupo) ou pseudonimizada (A04)."""
    group = alert.scope_type in _GROUP_SCOPES
    return Demand(
        key=f"alerta|{alert.id}",
        rule_id=alert.rule_id,
        subject=f"{alert.scope_type} {alert.scope}" if group else alert.scope,
        source_ref=f"alerta #{alert.id}",
        deadline=_default_deadline(alert.rule_id, rules, today),
        max_detail="agregado" if group else "pseudonimizado",
        facts={"explicacao": alert.explanation, "tamanho_grupo": alert.group_size},
        health_detail=alert.details.get("grupo_cid"),
    )


def _default_deadline(rule_id: str, rules: RuleCatalog, today: date) -> date | None:
    """Prazo padrão do tipo de demanda, contado de hoje."""
    days = rules.escalation.demands[rule_id].default_deadline_days
    return today + timedelta(days=days) if days is not None else None


def _br(value: date | None) -> str:
    """Data em DD/MM/AAAA (ou traço)."""
    return f"{value:%d/%m/%Y}" if value else "—"
