"""Percepção do Agente 3: pseudônimos, episódios e agrupamento com a A05."""

from datetime import date, datetime

from sinergia.agents.monitoring.snapshot import OTHERS_GROUP, Member, build_snapshot, grouped
from sinergia.core.domain import AbsenceStatus
from sinergia.core.pseudonym import pseudonymize
from sinergia.data.absences import Absence
from sinergia.data.employees import Employee


def _members(sizes: dict[str, int]) -> list[Member]:
    return [
        Member(f"P-{sector}{i}", sector, "função", "manhã", False)
        for sector, size in sizes.items()
        for i in range(size)
    ]


def test_pseudonym_is_stable_and_depends_on_salt() -> None:
    first = pseudonymize("1001", "sal-a")
    assert first == pseudonymize("1001", "sal-a")
    assert first != pseudonymize("1001", "sal-b")
    assert first.startswith("P-") and len(first) == 12 and "1001" not in first


def test_snapshot_has_no_employee_ids_and_keeps_only_cid_category() -> None:
    employee = Employee(employee_id="1001", sector="Loja", role="Caixa", shift="manhã")
    absence = Absence(
        protocol="SNG-1",
        session_id="s",
        employee_id="1001",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
        days=3,
        cid="M54.5",
        status=AbsenceStatus.VALID,
        extraction_method="regex",
        rules_version="t",
        updated_at=datetime(2026, 10, 1),
    )
    snapshot = build_snapshot(date(2026, 10, 28), [employee], [absence], "sal")
    [episode] = snapshot.episodes
    assert episode.person == snapshot.members[0].person != "1001"
    assert episode.cid_group == "M54"
    assert episode.overlap(date(2026, 10, 2), date(2026, 10, 10)) == 2


def test_small_groups_are_pooled_when_together_they_are_big_enough() -> None:
    groups, suppressed = grouped(_members({"A": 10, "B": 3, "C": 2}), "sector", 5)
    assert sorted(groups) == ["A", OTHERS_GROUP]
    assert len(groups[OTHERS_GROUP]) == 5
    assert suppressed == []


def test_small_groups_are_suppressed_when_pool_is_still_small() -> None:
    groups, suppressed = grouped(_members({"A": 10, "B": 3}), "sector", 5)
    assert sorted(groups) == ["A"]
    assert suppressed == ["B"]
