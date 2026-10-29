"""Histórico sintético com padrões plantados, para validar e medir o Agente 3.

Cria ~100 colaboradores fictícios em 5 setores e 10 semanas de afastamentos de fundo,
e planta um caso para cada regra:

- A01: pico de afastamentos na Logística na última semana;
- A02: 3 pessoas da Câmara Fria com o mesmo grupo de CID em 30 dias (aparece no setor e
  no turno da manhã, que reúne a Câmara Fria);
- A03: 2 dos 5 operadores de empilhadeira (função crítica) ausentes na data;
- A04: um colaborador do Administrativo somando 13 dias pela mesma causa em 60 dias;
- A05: pico na Diretoria (3 pessoas), que deve ser suprimido por ser um grupo pequeno.

O resultado esperado acompanha os dados, para calcular precisão e cobertura dos alertas.
"""

import csv
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sinergia.core.domain import AbsenceStatus, CaseStatus, DocumentType
from sinergia.core.pseudonym import pseudonymize
from sinergia.data.absences import Absence, AbsenceRepository
from sinergia.data.alerts import Alert
from sinergia.data.employees import CSV_COLUMNS, Employee, EmployeeRepository
from sinergia.data.intakes import Intake, IntakeRepository

SECTORS = {
    # setor: (pessoas, turnos, função)
    "Logística": (40, ("manhã", "tarde", "noite"), "Auxiliar de logística"),
    "Loja": (30, ("manhã", "tarde"), "Operador de caixa"),
    "Câmara Fria": (12, ("manhã",), "Repositor de câmara fria"),
    "Administrativo": (15, ("comercial",), "Analista administrativo"),
    "Diretoria": (3, ("comercial",), "Diretor"),
}
FORKLIFT = "Operador de empilhadeira"
_ORIGIN = "historico_sintetico"


@dataclass
class History:
    """Dados sintéticos e o que o Agente 3 deveria encontrar neles."""

    employees: list[Employee]
    absences: list[tuple[str, date, int, str | None]] = field(default_factory=list)
    expected: list[dict[str, str]] = field(default_factory=list)
    expected_suppressed: list[str] = field(default_factory=list)


def build_history(reference: date, seed: int = 42) -> History:
    """Gera colaboradores, afastamentos de fundo e os padrões plantados."""
    rng = random.Random(seed)
    history = History(employees=_employees())
    _background(history, reference, rng)
    for plant in (
        _plant_spike,
        _plant_cid_cluster,
        _plant_coverage,
        _plant_same_cause,
        _plant_small_group,
    ):
        plant(history, reference)
    return history


def _employees() -> list[Employee]:
    """Cadastro fictício; os 5 primeiros da Logística operam empilhadeira (função crítica)."""
    people = []
    for sector, (size, shifts, role) in SECTORS.items():
        for index in range(size):
            forklift = sector == "Logística" and index < 5
            people.append(
                Employee(
                    employee_id=f"{sector[:3].upper()}{index + 1:03d}",
                    sector=sector,
                    role=FORKLIFT if forklift else role,
                    shift=shifts[index % len(shifts)],
                    critical_role=forklift,
                )
            )
    return people


def _background(history: History, reference: date, rng: random.Random) -> None:
    """Afastamentos curtos e sem CID nas 10 semanas anteriores à semana de referência."""
    by_sector = _by_sector(history)
    for week in range(1, 11):
        week_start = reference - timedelta(days=7 * week + 6)
        for sector, people in by_sector.items():
            if sector == "Diretoria":
                continue
            count = max(1, round(len(people) * 0.03) + rng.choice((-1, 0, 0, 1)))
            for person in rng.sample(people, count):
                history.absences.append(
                    (person, week_start + timedelta(days=rng.randint(0, 4)), 2, None)
                )


def _plant_spike(history: History, reference: date) -> None:
    """A01: 9 pessoas da Logística (2 delas operadoras de empilhadeira) com 3 dias."""
    people = [e.employee_id for e in history.employees if e.sector == "Logística"][3:12]
    for person in people:
        history.absences.append((person, reference - timedelta(days=2), 3, None))
    history.expected.append({"rule_id": "A01", "scope_type": "setor", "scope": "Logística"})


def _plant_cid_cluster(history: History, reference: date) -> None:
    """A02: 3 repositores da Câmara Fria com dorsalgia (M54) entre 15 e 25 dias atrás."""
    people = [e.employee_id for e in history.employees if e.sector == "Câmara Fria"][:3]
    for offset, person in zip((25, 20, 15), people, strict=True):
        history.absences.append((person, reference - timedelta(days=offset), 2, "M54.5"))
    history.expected += [
        {"rule_id": "A02", "scope_type": "setor", "scope": "Câmara Fria"},
        {"rule_id": "A02", "scope_type": "turno", "scope": "manhã"},
    ]


def _plant_coverage(history: History, reference: date) -> None:
    """A03: o pico da Logística já deixa 2 dos 5 operadores de empilhadeira ausentes."""
    history.expected.append({"rule_id": "A03", "scope_type": "funcao", "scope": FORKLIFT})


def _plant_same_cause(history: History, reference: date) -> None:
    """A04: 6 + 7 dias pela mesma causa (M75) em 60 dias, sem chegar aos 15 da R11."""
    person = "ADM001"
    history.absences += [
        (person, reference - timedelta(days=40), 6, "M75.1"),
        (person, reference - timedelta(days=12), 7, "M75.1"),
    ]
    history.expected.append({"rule_id": "A04", "scope_type": "colaborador", "scope": person})


def _plant_small_group(history: History, reference: date) -> None:
    """A05: 2 dos 3 diretores afastados na última semana; o grupo é pequeno demais."""
    for person in ("DIR001", "DIR002"):
        history.absences.append((person, reference - timedelta(days=4), 5, None))
    history.expected_suppressed.append("setor:Diretoria")


def _by_sector(history: History) -> dict[str, list[str]]:
    """Matrículas por setor."""
    groups: dict[str, list[str]] = {}
    for employee in history.employees:
        groups.setdefault(employee.sector, []).append(employee.employee_id)
    return groups


def as_records(
    history: History, received_at: datetime, rules_version: str
) -> list[tuple[Intake, Absence]]:
    """Converte o histórico em linhas de entrada e afastamentos válidos."""
    return [
        _record(f"HIST-{number:04d}", item, received_at, rules_version)
        for number, item in enumerate(history.absences, start=1)
    ]


def _record(
    protocol: str, item: tuple, received_at: datetime, rules_version: str
) -> tuple[Intake, Absence]:
    """Uma entrada recebida e o afastamento válido correspondente."""
    person, start, days, cid = item
    common = {
        "protocol": protocol,
        "session_id": _ORIGIN,
        "employee_id": person,
        "document_type": DocumentType.MEDICAL_CERTIFICATE,
        "rules_version": rules_version,
    }
    intake = Intake(
        **common,
        channel=_ORIGIN,
        absence_start=start,
        received_at=received_at,
        status=CaseStatus.RECEIVED,
        attempts=1,
    )
    return intake, _absence(common, start, days, cid, received_at)


def _absence(common: dict, start: date, days: int, cid: str | None, at: datetime) -> Absence:
    """Afastamento válido do histórico."""
    return Absence(
        **common,
        start_date=start,
        end_date=start + timedelta(days=days - 1),
        days=days,
        cid=cid,
        status=AbsenceStatus.VALID,
        extraction_method=_ORIGIN,
        updated_at=at,
    )


def expected_keys(history: History, salt: str) -> set[tuple[str, str, str]]:
    """Alertas esperados como (regra, tipo de grupo, grupo); A04 vem por pseudônimo."""
    keys = set()
    for item in history.expected:
        scope = item["scope"]
        if item["scope_type"] == "colaborador":
            scope = pseudonymize(scope, salt)
        keys.add((item["rule_id"], item["scope_type"], scope))
    return keys


def evaluate(
    found: list[Alert], suppressed: list[str], history: History, salt: str
) -> dict[str, Any]:
    """Precisão e cobertura dos alertas frente aos padrões plantados (e a A05)."""
    expected = expected_keys(history, salt)
    got = {(alert.rule_id, alert.scope_type, alert.scope) for alert in found}
    hits = expected & got
    return {
        "esperados": len(expected),
        "encontrados": len(got),
        "acertos": len(hits),
        "precisao": round(len(hits) / len(got), 3) if got else 0.0,
        "cobertura": round(len(hits) / len(expected), 3) if expected else 0.0,
        "faltando": sorted("|".join(key) for key in expected - got),
        "inesperados": sorted("|".join(key) for key in got - expected),
        "supressao_ok": set(history.expected_suppressed) <= set(suppressed),
    }


def write_employees_csv(history: History, path: Path) -> Path:
    """Grava o cadastro fictício no formato aceito por ``sinergia employees import``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for e in history.employees:
            writer.writerow(
                [e.employee_id, e.sector, e.role, e.shift, "sim" if e.critical_role else "não"]
            )
    return path


def load_history(
    repos: tuple[IntakeRepository, AbsenceRepository, EmployeeRepository],
    history: History,
    at: datetime,
    rules_version: str,
) -> int:
    """Grava cadastro e afastamentos; devolve quantos afastamentos novos entraram."""
    intakes, absences, employees = repos
    for employee in history.employees:
        employees.upsert(employee, at)
    added = 0
    for intake, absence in as_records(history, at, rules_version):
        if intakes.exists(intake.protocol):
            continue
        intakes.add(intake)
        absences.save(absence)
        added += 1
    return added
