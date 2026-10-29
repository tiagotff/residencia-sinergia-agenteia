"""Montagem das dependências da aplicação a partir das configurações."""

import sqlite3
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from sinergia.agents.reception.graph import ReceptionDeps, build_reception_graph
from sinergia.agents.reception.inspection import FileInspector
from sinergia.agents.reception.messages import build_composer
from sinergia.agents.reception.service import ReceptionService
from sinergia.core.clock import Clock, system_clock
from sinergia.core.llm import build_chat_model
from sinergia.core.rules import RuleCatalog, load_rules
from sinergia.core.settings import Settings
from sinergia.data.audit import AuditLog
from sinergia.data.database import Database
from sinergia.data.file_store import FileStore
from sinergia.data.intakes import IntakeRepository


@dataclass(frozen=True)
class Container:
    """Objetos de longa duração compartilhados pela API e pela CLI."""

    settings: Settings
    rules: RuleCatalog
    database: Database
    files: FileStore
    intakes: IntakeRepository
    audit: AuditLog
    reception: ReceptionService


def build_container(
    settings: Settings,
    clock: Clock | None = None,
    chat_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Container:
    """Cria banco, repositórios e agentes; parâmetros opcionais servem aos testes."""
    rules = load_rules(settings.rules_path)
    clock = clock or system_clock(settings.timezone)
    database = Database(settings.database_path)
    database.initialize()
    files = FileStore(settings.files_dir)
    intakes = IntakeRepository(database)
    audit = AuditLog(database, clock, rules.version)
    model = chat_model if chat_model is not None else build_chat_model(settings)
    deps = ReceptionDeps(
        rules=rules,
        inspector=FileInspector(rules.reception),
        files=files,
        intakes=intakes,
        audit=audit,
        composer=build_composer(rules.reception, model),
        clock=clock,
    )
    graph = build_reception_graph(deps, checkpointer or sqlite_checkpointer(settings))
    reception = ReceptionService(graph, files)
    return Container(settings, rules, database, files, intakes, audit, reception)


def sqlite_checkpointer(settings: Settings) -> SqliteSaver:
    """Checkpointer em SQLite: sessões pausadas sobrevivem a reinícios."""
    settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.checkpoint_path, check_same_thread=False)
    return SqliteSaver(conn)
