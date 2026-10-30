"""Fixtures da crew de insights: base sintética com ciclo confirmado e crews de mentira."""

from dataclasses import dataclass, field

import pytest

from sinergia.agents.escalation.models import EscalationDecision
from sinergia.bootstrap import Container, Overrides, build_container
from sinergia.core.settings import Settings
from sinergia.insights.crew import CrewResult
from sinergia.synthetic.history import build_history, load_history
from tests.conftest import NOW


class _NoOcr:
    def read(self, image: bytes) -> object:  # pragma: no cover - não deve ser chamado
        raise AssertionError("OCR não deveria ser usado")


@dataclass
class FakeCrew:
    """Devolve sempre a mesma resposta e guarda o texto de fatos recebido."""

    result: CrewResult | Exception
    received: list[str] = field(default_factory=list)

    def run(self, facts_text: str) -> CrewResult:
        self.received.append(facts_text)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def populate(app: Container) -> None:
    """Histórico sintético, ciclo de monitoramento e encaminhamentos confirmados."""
    load_history(
        (app.intakes, app.absences, app.employees),
        build_history(NOW.date()),
        NOW,
        app.rules.version,
    )
    session = app.monitoring.run(NOW.date())["session_id"]
    app.escalation.decide(session, EscalationDecision(reviewer="Ana (SESMT)"))


@pytest.fixture
def make_app(settings: Settings):
    """Monta a aplicação com a crew pedida (None = sem crew) e a base carregada."""

    def _make(crew: FakeCrew | None = None) -> Container:
        app = build_container(settings, Overrides(clock=lambda: NOW, ocr=_NoOcr(), crew=crew))
        populate(app)
        return app

    return _make
