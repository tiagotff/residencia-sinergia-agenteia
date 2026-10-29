"""Fixtures compartilhadas: configurações isoladas, relógio fixo e amostras sintéticas."""

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sinergia.agents.processing.ocr import EasyOcrEngine
from sinergia.agents.reception.service import ReceptionInput
from sinergia.bootstrap import Container, Overrides, build_container
from sinergia.core.clock import fixed_clock
from sinergia.core.rules import RuleCatalog, load_rules
from sinergia.core.settings import Settings
from sinergia.synthetic.documents import generate_samples

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 28, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
YESTERDAY = date(2026, 10, 27)


@pytest.fixture(scope="session")
def samples(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Pasta com o conjunto de documentos sintéticos."""
    folder = tmp_path_factory.mktemp("samples")
    generate_samples(folder)
    return folder


@pytest.fixture(scope="session")
def ocr() -> EasyOcrEngine:
    """Motor de OCR compartilhado: o modelo é baixado uma vez para data/ocr_models."""
    return EasyOcrEngine(ROOT / "data" / "ocr_models")


@pytest.fixture
def rules() -> RuleCatalog:
    """Catálogo de regras real do repositório."""
    return load_rules(ROOT / "config" / "rules.yaml")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Configurações isoladas por teste, sem LLM e com o registro fictício de CRMs."""
    return Settings(
        _env_file=None,
        llm_provider="none",
        crm_verifier="local",
        crm_registry_path=ROOT / "config" / "crm_registry.yaml",
        data_dir=tmp_path / "data",
        rules_path=ROOT / "config" / "rules.yaml",
    )


@pytest.fixture
def container(settings: Settings, ocr: EasyOcrEngine) -> Container:
    """Aplicação montada com relógio fixo."""
    return build_container(settings, Overrides(clock=fixed_clock(NOW), ocr=ocr))


@pytest.fixture
def make_input(samples: Path) -> Callable[..., ReceptionInput]:
    """Monta uma entrada de recepção a partir do nome de uma amostra."""

    def _make(sample: str | None = None, **fields: object) -> ReceptionInput:
        file_fields = {}
        if sample is not None:
            file_fields = {"file_name": sample, "content": (samples / sample).read_bytes()}
        return ReceptionInput(**file_fields, **fields)

    return _make
