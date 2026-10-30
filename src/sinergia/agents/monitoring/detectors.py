"""Regras de alerta do Agente 3 (A01–A05). Todas comparam números e dizem quais.

A01 e A02 tratam de saúde coletiva e passam pela A05 (grupos pequenos agregados ou
suprimidos). A03 trata só de ausência (cobertura), informação que o gestor já tem.
A04 é individual, mas por pseudônimo, e vira pendência administrativa preventiva.
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sinergia.agents.monitoring.snapshot import Member, Snapshot, grouped
from sinergia.core.rules import MonitoringRules, ProcessingRules
from sinergia.data.alerts import Alert

_WEEK = 7


@dataclass
class Detection:
    """Resultado de uma execução: alertas e grupos suprimidos pela A05."""

    alerts: list[Alert] = field(default_factory=list)
    suppressed: set[str] = field(default_factory=set)


def detect(snapshot: Snapshot, rules: MonitoringRules, processing: ProcessingRules) -> Detection:
    """Aplica A01–A04 (com A05 onde há dado de saúde coletiva)."""
    result = Detection()
    sectors, hidden_sectors = grouped(snapshot.members, "sector", rules.min_group_size)
    shifts, hidden_shifts = grouped(snapshot.members, "shift", rules.min_group_size)
    result.suppressed |= {f"setor:{name}" for name in hidden_sectors}
    result.suppressed |= {f"turno:{name}" for name in hidden_shifts}
    result.alerts += sector_spikes(snapshot, sectors, rules)
    result.alerts += cid_clusters(snapshot, {"setor": sectors, "turno": shifts}, rules)
    result.alerts += coverage_gaps(snapshot, rules)
    result.alerts += same_cause_approach(snapshot, rules, processing)
    return result


def sector_spikes(
    snapshot: Snapshot, sectors: dict[str, list[Member]], rules: MonitoringRules
) -> list[Alert]:
    """A01: taxa dos últimos 7 dias acima da linha de base do próprio setor."""
    alerts = []
    for sector, members in sorted(sectors.items()):
        history = _baseline(snapshot, members, rules)
        if len(history) < rules.min_baseline_weeks:
            continue
        current = weekly_rate(snapshot, members, 0)
        mean, spread = statistics.mean(history), statistics.pstdev(history)
        threshold = mean + max(rules.spike_std_factor * spread, rules.min_rate_increase)
        if current > threshold:
            alerts.append(
                _spike_alert(snapshot, sector, members, current, mean, threshold, len(history))
            )
    return alerts


def _baseline(snapshot: Snapshot, members: list[Member], rules: MonitoringRules) -> list[float]:
    """Taxas das semanas anteriores que já têm dados registrados."""
    first = snapshot.first_record
    if first is None:
        return []
    offsets = range(1, rules.baseline_weeks + 1)
    return [
        weekly_rate(snapshot, members, offset)
        for offset in offsets
        if snapshot.window(_WEEK, offset)[1] >= first
    ]


def weekly_rate(snapshot: Snapshot, members: list[Member], offset: int) -> float:
    """Dias de afastamento ÷ (pessoas × 7) na janela semanal."""
    first, last = snapshot.window(_WEEK, offset)
    people = {member.person for member in members}
    days = sum(e.overlap(first, last) for e in snapshot.episodes if e.person in people)
    return days / (len(people) * _WEEK)


def _spike_alert(
    snapshot: Snapshot,
    sector: str,
    members: list[Member],
    current: float,
    mean: float,
    threshold: float,
    weeks: int,
) -> Alert:
    """Monta o alerta A01 com a evidência da comparação."""
    first, last = snapshot.window(_WEEK)
    return Alert(
        rule_id="A01",
        scope_type="setor",
        scope=sector,
        period_start=first,
        period_end=last,
        metric="taxa_afastamento",
        value=round(current, 4),
        reference=round(mean, 4),
        threshold=round(threshold, 4),
        group_size=len(members),
        details={"semanas_na_linha_de_base": weeks},
    )


def cid_clusters(
    snapshot: Snapshot, groups: dict[str, dict[str, list[Member]]], rules: MonitoringRules
) -> list[Alert]:
    """A02: pessoas distintas com o mesmo grupo de CID no setor ou turno, na janela."""
    first, last = snapshot.window(rules.cid_window_days)
    cases = [e for e in snapshot.episodes if e.cid_group and e.overlap(first, last)]
    alerts = []
    for scope_type, by_name in groups.items():
        for name, members in sorted(by_name.items()):
            people = {member.person for member in members}
            alerts += _clusters_in(
                cases, people, scope_type, name, len(members), rules, (first, last)
            )
    return alerts


def _clusters_in(
    cases: list,
    people: set[str],
    scope_type: str,
    name: str,
    size: int,
    rules: MonitoringRules,
    period: tuple,
) -> list[Alert]:
    """Grupos de CID que atingem o mínimo de pessoas dentro de um grupo."""
    by_cid: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        if case.person in people:
            by_cid[case.cid_group].add(case.person)
    common = {"scope_type": scope_type, "scope": name, "group_size": size}
    return [
        _sensitive_alert(
            "A02",
            period,
            "pessoas_mesmo_grupo_cid",
            len(persons),
            rules.cid_min_cases,
            common,
            {"grupo_cid": cid},
        )
        for cid, persons in sorted(by_cid.items())
        if len(persons) >= rules.cid_min_cases
    ]


def _sensitive_alert(
    rule_id: str,
    period: tuple,
    metric: str,
    value: float,
    threshold: float,
    common: dict,
    details: dict,
) -> Alert:
    """Alerta com dado de saúde (grupo de CID): marcado como sensível."""
    return Alert(
        rule_id=rule_id,
        period_start=period[0],
        period_end=period[1],
        metric=metric,
        value=value,
        threshold=threshold,
        sensitive=True,
        details=details,
        **common,
    )


def coverage_gaps(snapshot: Snapshot, rules: MonitoringRules) -> list[Alert]:
    """A03: funções críticas com cobertura disponível abaixo do mínimo na data."""
    day = snapshot.reference_date
    absent = {e.person for e in snapshot.episodes if e.start <= day <= e.end}
    roles: dict[str, list[Member]] = defaultdict(list)
    for member in snapshot.members:
        if member.critical_role:
            roles[member.role].append(member)
    alerts = []
    for role, members in sorted(roles.items()):
        missing = sum(member.person in absent for member in members)
        available = (len(members) - missing) / len(members)
        if available < rules.min_critical_coverage:
            alerts.append(_coverage_alert(day, role, len(members), missing, available, rules))
    return alerts


def _coverage_alert(
    day: date, role: str, size: int, missing: int, available: float, rules: MonitoringRules
) -> Alert:
    """Monta o alerta A03 (só ausência, sem dado de saúde)."""
    return Alert(
        rule_id="A03",
        scope_type="funcao",
        scope=role,
        period_start=day,
        period_end=day,
        metric="cobertura_disponivel",
        value=round(available, 4),
        threshold=rules.min_critical_coverage,
        group_size=size,
        details={"ausentes": missing},
    )


def same_cause_approach(
    snapshot: Snapshot, rules: MonitoringRules, processing: ProcessingRules
) -> list[Alert]:
    """A04: mesma causa somando dias perto do limite da R11, antes de ele ser atingido."""
    period = (
        snapshot.reference_date - timedelta(days=processing.same_cause_window_days - 1),
        snapshot.reference_date,
    )
    totals = _same_cause_totals(snapshot, period)
    limit = processing.inss_threshold_days
    return [
        _sensitive_alert(
            "A04",
            period,
            "dias_mesma_causa",
            total,
            rules.same_cause_alert_days,
            {"scope_type": "colaborador", "scope": person, "group_size": 1},
            {"grupo_cid": cid, "limite_legal": limit},
        )
        for (person, cid), total in sorted(totals.items())
        if rules.same_cause_alert_days <= total <= limit
    ]


def _same_cause_totals(snapshot: Snapshot, period: tuple) -> dict[tuple[str, str], int]:
    """Dias por (pseudônimo, grupo de CID) com início no período."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for episode in snapshot.episodes:
        if episode.cid_group and period[0] <= episode.start <= period[1]:
            totals[(episode.person, episode.cid_group)] += episode.days
    return totals
