"""Fixtures do Agente 4: relógio ajustável, aplicação sem OCR e envio de atestados."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from sinergia.agents.reception.service import ReceptionInput
from sinergia.bootstrap import Container, Overrides, build_container
from sinergia.core.settings import Settings
from sinergia.synthetic.history import build_history, load_history
from tests.conftest import NOW, YESTERDAY


class Clock:
    """Relógio que o teste pode adiantar."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, days: int) -> None:
        self.now += timedelta(days=days)


class _NoOcr:
    """Os PDFs sintéticos têm camada de texto: o OCR não é usado."""

    def read(self, image: bytes) -> object:  # pragma: no cover - não deve ser chamado
        raise AssertionError("OCR não deveria ser usado")


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW)


@pytest.fixture
def app(settings: Settings, clock: Clock) -> Container:
    """Aplicação com relógio ajustável."""
    return build_container(settings, Overrides(clock=clock, ocr=_NoOcr()))


@pytest.fixture
def cycle(app: Container) -> str:
    """Histórico sintético carregado e um ciclo de monitoramento rodado; devolve a sessão."""
    load_history(
        (app.intakes, app.absences, app.employees),
        build_history(NOW.date()),
        NOW,
        app.rules.version,
    )
    return app.monitoring.run(NOW.date())["session_id"]


@pytest.fixture
def submit(app: Container, samples: Path) -> Callable[..., str]:
    """Envia um PDF sintético e devolve o protocolo."""

    def _submit(sample: str, employee_id: str = "9001", start: date = YESTERDAY) -> str:
        data = ReceptionInput(
            file_name=f"{sample}.pdf",
            content=(samples / f"{sample}.pdf").read_bytes(),
            employee_id=employee_id,
            absence_start=start,
        )
        return app.reception.start(data).protocol or ""

    return _submit
