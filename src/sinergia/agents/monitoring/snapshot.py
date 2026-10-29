"""Percepção do Agente 3: a base vista por pseudônimos, numa data de referência."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sinergia.core.pseudonym import pseudonymize
from sinergia.data.absences import Absence
from sinergia.data.employees import Employee

OTHERS_GROUP = "Demais grupos (agregado)"


@dataclass(frozen=True)
class Member:
    """Colaborador ativo, identificado só pelo pseudônimo."""

    person: str
    sector: str
    role: str
    shift: str
    critical_role: bool


@dataclass(frozen=True)
class Episode:
    """Afastamento válido, sem matrícula e com o CID reduzido à categoria (3 caracteres)."""

    person: str
    start: date
    end: date
    days: int
    cid_group: str | None

    def overlap(self, first: date, last: date) -> int:
        """Dias do afastamento dentro do período [first, last]."""
        return max(0, (min(self.end, last) - max(self.start, first)).days + 1)


@dataclass(frozen=True)
class Snapshot:
    """Tudo o que o agente compara numa execução."""

    reference_date: date
    members: list[Member]
    episodes: list[Episode]

    def window(self, days: int, offset: int = 0) -> tuple[date, date]:
        """Janela de ``days`` dias terminando ``offset`` janelas antes da referência."""
        last = self.reference_date - timedelta(days=days * offset)
        return last - timedelta(days=days - 1), last

    @property
    def first_record(self) -> date | None:
        """Data do afastamento mais antigo visível (limite da linha de base)."""
        return min((episode.start for episode in self.episodes), default=None)


def build_snapshot(
    reference_date: date, employees: list[Employee], absences: list[Absence], salt: str
) -> Snapshot:
    """Troca matrículas por pseudônimos e descarta o que o agente não precisa."""
    members = [
        Member(pseudonymize(e.employee_id, salt), e.sector, e.role, e.shift, e.critical_role)
        for e in employees
    ]
    episodes = [_episode(absence, salt) for absence in absences if absence.employee_id]
    return Snapshot(reference_date, members, [e for e in episodes if e is not None])


def _episode(absence: Absence, salt: str) -> Episode | None:
    """Converte um afastamento válido em episódio pseudonimizado."""
    if absence.start_date is None:
        return None
    end = absence.last_day or absence.start_date
    days = absence.days or (end - absence.start_date).days + 1
    cid_group = absence.cid[:3] if absence.cid else None
    return Episode(
        pseudonymize(absence.employee_id or "", salt), absence.start_date, end, days, cid_group
    )


def grouped(members: list[Member], attribute: str, min_size: int) -> tuple[dict, list[str]]:
    """A05: agrupa por atributo; grupos pequenos vão para um agregado ou são suprimidos."""
    groups: dict[str, list[Member]] = defaultdict(list)
    for member in members:
        groups[getattr(member, attribute)].append(member)
    small = [name for name, people in groups.items() if len(people) < min_size]
    kept = {name: people for name, people in groups.items() if name not in small}
    pooled = [member for name in small for member in groups[name]]
    if len(pooled) >= min_size:
        kept[OTHERS_GROUP] = pooled
        return kept, []
    return kept, small
