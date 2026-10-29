"""Montagem das dependências da aplicação a partir das configurações."""

import sqlite3
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph

from sinergia.agents.processing.crm import CrmVerifier, build_crm_verifier
from sinergia.agents.processing.extraction import build_field_extractor
from sinergia.agents.processing.graph import ProcessingDeps, build_processing_graph
from sinergia.agents.processing.ocr import EasyOcrEngine, OcrEngine
from sinergia.agents.processing.review import ReviewService
from sinergia.agents.processing.text_reader import DocumentTextReader
from sinergia.agents.reception.graph import ReceptionDeps, build_reception_graph
from sinergia.agents.reception.inspection import FileInspector
from sinergia.agents.reception.messages import build_composer
from sinergia.agents.reception.service import ReceptionService
from sinergia.core.clock import Clock, system_clock
from sinergia.core.llm import build_chat_model
from sinergia.core.rules import RuleCatalog, load_rules
from sinergia.core.settings import Settings
from sinergia.data.absences import AbsenceRepository
from sinergia.data.audit import AuditLog
from sinergia.data.database import Database
from sinergia.data.file_store import FileStore
from sinergia.data.intakes import IntakeRepository
from sinergia.data.vacations import VacationRepository
from sinergia.graph import build_case_graph


@dataclass(frozen=True)
class Container:
    """Objetos de longa duração compartilhados pela API e pela CLI."""

    settings: Settings
    rules: RuleCatalog
    clock: Clock
    database: Database
    files: FileStore
    intakes: IntakeRepository
    absences: AbsenceRepository
    vacations: VacationRepository
    audit: AuditLog
    reception: ReceptionService
    review: ReviewService


@dataclass(frozen=True)
class Overrides:
    """Substituições usadas em testes (relógio, LLM, OCR, CRM, checkpoint)."""

    clock: Clock | None = None
    chat_model: BaseChatModel | None = None
    ocr: OcrEngine | None = None
    crm: CrmVerifier | None = None
    checkpointer: BaseCheckpointSaver | None = None


@dataclass(frozen=True)
class _Shared:
    """Peças comuns aos agentes."""

    rules: RuleCatalog
    clock: Clock
    files: FileStore
    intakes: IntakeRepository
    absences: AbsenceRepository
    vacations: VacationRepository
    audit: AuditLog


def build_container(settings: Settings, overrides: Overrides | None = None) -> Container:
    """Cria banco, repositórios, agentes e o grafo do caso."""
    extra = overrides or Overrides()
    shared, database = _shared(settings, extra)
    model = extra.chat_model if extra.chat_model is not None else build_chat_model(settings)
    reception = build_reception_graph(_reception_deps(shared, model))
    processing = build_processing_graph(_processing_deps(settings, shared, model, extra))
    case = build_case_graph(
        reception, processing, extra.checkpointer or sqlite_checkpointer(settings)
    )
    return _assemble(settings, shared, database, case)


def _assemble(
    settings: Settings, shared: _Shared, database: Database, case: CompiledStateGraph
) -> Container:
    """Junta as peças e os serviços que usam o grafo do caso."""
    return Container(
        settings=settings,
        rules=shared.rules,
        clock=shared.clock,
        database=database,
        files=shared.files,
        intakes=shared.intakes,
        absences=shared.absences,
        vacations=shared.vacations,
        audit=shared.audit,
        reception=ReceptionService(case, shared.files),
        review=ReviewService(case, shared.absences),
    )


def _shared(settings: Settings, extra: Overrides) -> tuple[_Shared, Database]:
    """Regras, relógio, banco e repositórios."""
    rules = load_rules(settings.rules_path)
    clock = extra.clock or system_clock(settings.timezone)
    database = Database(settings.database_path)
    database.initialize()
    shared = _Shared(
        rules=rules,
        clock=clock,
        files=FileStore(settings.files_dir),
        intakes=IntakeRepository(database),
        absences=AbsenceRepository(database),
        vacations=VacationRepository(database),
        audit=AuditLog(database, clock, rules.version),
    )
    return shared, database


def _reception_deps(shared: _Shared, model: BaseChatModel | None) -> ReceptionDeps:
    """Dependências do Agente 1."""
    return ReceptionDeps(
        rules=shared.rules,
        inspector=FileInspector(shared.rules.reception),
        files=shared.files,
        intakes=shared.intakes,
        audit=shared.audit,
        composer=build_composer(shared.rules.reception, model),
        clock=shared.clock,
    )


def _processing_deps(
    settings: Settings, shared: _Shared, model: BaseChatModel | None, extra: Overrides
) -> ProcessingDeps:
    """Dependências do Agente 2."""
    return ProcessingDeps(
        rules=shared.rules,
        reader=DocumentTextReader(extra.ocr or EasyOcrEngine(settings.ocr_models_dir)),
        extractor=build_field_extractor(model),
        crm=extra.crm or build_crm_verifier(settings),
        intakes=shared.intakes,
        absences=shared.absences,
        vacations=shared.vacations,
        audit=shared.audit,
        clock=shared.clock,
    )


def sqlite_checkpointer(settings: Settings) -> SqliteSaver:
    """Checkpointer em SQLite: casos pausados sobrevivem a reinícios."""
    settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.checkpoint_path, check_same_thread=False)
    return SqliteSaver(conn)
