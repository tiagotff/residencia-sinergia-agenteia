"""API FastAPI dos Agentes 1 e 2.

Execução local:
    uvicorn sinergia.api.app:create_default_app --factory --reload
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile

from sinergia.agents.processing.models import ReviewDecision
from sinergia.agents.processing.review import ReviewCase
from sinergia.agents.reception.service import ReceptionInput, ReceptionResult
from sinergia.bootstrap import Container, build_container
from sinergia.core.domain import DocumentType
from sinergia.core.errors import NotFoundError, SessionStateError
from sinergia.core.settings import Settings
from sinergia.data.vacations import Vacation

router = APIRouter()


def create_app(container: Container) -> FastAPI:
    """Cria a aplicação com o contêiner de dependências informado."""
    app = FastAPI(title="Sinergia", version="0.2.0")
    app.state.container = container
    app.include_router(router)
    return app


def create_default_app() -> FastAPI:
    """Cria a aplicação lendo as configurações do .env."""
    return create_app(build_container(Settings()))


def _container(request: Request) -> Container:
    """Dependência que entrega o contêiner da aplicação."""
    return request.app.state.container


async def _reception_input(
    employee_id: Annotated[str | None, Form()] = None,
    channel: Annotated[str, Form()] = "portal",
    declared_type: Annotated[DocumentType | None, Form()] = None,
    absence_start: Annotated[date | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> ReceptionInput:
    """Converte o formulário multipart em ``ReceptionInput``."""
    content = await file.read() if file is not None and file.filename else None
    return ReceptionInput(
        employee_id=employee_id or None,
        channel=channel,
        declared_type=declared_type,
        absence_start=absence_start,
        file_name=file.filename if content is not None else None,
        content=content,
    )


ContainerDep = Annotated[Container, Depends(_container)]
InputDep = Annotated[ReceptionInput, Depends(_reception_input)]


@router.get("/health")
def health() -> dict[str, str]:
    """Verificação simples de disponibilidade."""
    return {"status": "ok"}


@router.post("/reception/submissions")
def submit(container: ContainerDep, data: InputDep) -> ReceptionResult:
    """Primeiro envio do colaborador ao Agente 1."""
    return container.reception.start(data)


@router.post("/reception/submissions/{session_id}/reply")
def reply(session_id: str, container: ContainerDep, data: InputDep) -> ReceptionResult:
    """Resposta do colaborador ao que o Agente 1 pediu."""
    try:
        return container.reception.reply(session_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reception/intakes/{protocol}")
def intake(protocol: str, container: ContainerDep) -> dict[str, Any]:
    """Linha de entrada e pendências de um protocolo (sem o caminho interno do arquivo)."""
    try:
        found = container.intakes.get(protocol)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    pendencies = container.intakes.pendencies_for(protocol)
    return {
        "intake": found.model_dump(mode="json", exclude={"file_path"}),
        "pendencies": [p.model_dump(mode="json") for p in pendencies],
    }


@router.get("/absences/{protocol}")
def absence(protocol: str, container: ContainerDep) -> dict[str, Any]:
    """Registro do Agente 2; mostra só se há CID, nunca o código."""
    try:
        found = container.absences.get(protocol)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    data = found.model_dump(mode="json", exclude={"cid"})
    return {**data, "cid_present": found.cid is not None}


@router.get("/review/cases")
def review_cases(container: ContainerDep) -> list[ReviewCase]:
    """Fila de revisão humana, do caso mais antigo para o mais novo."""
    return container.review.pending()


@router.get("/review/cases/{protocol}")
def review_case(protocol: str, container: ContainerDep) -> ReviewCase:
    """O que o revisor precisa conferir num caso."""
    try:
        return container.review.get(protocol)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/review/cases/{protocol}/decision")
def review_decision(
    protocol: str, decision: ReviewDecision, container: ContainerDep
) -> dict[str, Any]:
    """Aprova (com correções) ou invalida o caso e devolve a nova situação."""
    try:
        updated = container.review.decide(protocol, decision)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "protocol": protocol,
        "status": updated.status.value,
        "violated_rules": updated.violated_rules,
    }


@router.post("/vacations")
def add_vacation(vacation: Vacation, container: ContainerDep) -> dict[str, Any]:
    """Cadastra um período de férias (fonte da R07)."""
    added = container.vacations.add(vacation, container.clock())
    return {"added": added}


@router.post("/vacations/import")
async def import_vacations(
    file: Annotated[UploadFile, File()], container: ContainerDep
) -> dict[str, Any]:
    """Importa um CSV com employee_id, start_date e end_date."""
    staged = container.files.stage(await file.read(), "ferias.csv")
    try:
        count = container.vacations.import_csv(staged, container.clock())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        container.files.discard(staged)
    return {"imported": count}


@router.get("/vacations/{employee_id}")
def list_vacations(employee_id: str, container: ContainerDep) -> list[Vacation]:
    """Férias cadastradas do colaborador."""
    return container.vacations.for_employee(employee_id)
