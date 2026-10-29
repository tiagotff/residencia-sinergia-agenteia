"""Fixtures do Agente 3: aplicação sem OCR e histórico sintético carregado."""

import pytest

from sinergia.bootstrap import Container, Overrides, build_container
from sinergia.core.clock import fixed_clock
from sinergia.core.settings import Settings
from sinergia.synthetic.history import History, build_history, load_history
from tests.conftest import NOW


class _NoOcr:
    """O monitoramento nunca lê imagens."""

    def read(self, image: bytes) -> object:  # pragma: no cover - não deve ser chamado
        raise AssertionError("OCR não deveria ser usado no monitoramento")


@pytest.fixture
def app(settings: Settings) -> Container:
    """Aplicação com relógio fixo e sem carregar o modelo de OCR."""
    return build_container(settings, Overrides(clock=fixed_clock(NOW), ocr=_NoOcr()))


@pytest.fixture
def history() -> History:
    """Histórico sintético com os padrões plantados de A01 a A05."""
    return build_history(NOW.date())


@pytest.fixture
def loaded(app: Container, history: History) -> Container:
    """Aplicação com o histórico sintético gravado."""
    load_history((app.intakes, app.absences, app.employees), history, NOW, app.rules.version)
    return app
