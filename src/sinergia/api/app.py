"""API FastAPI do Agente 1.

Execução local:
    uvicorn sinergia.api.app:create_default_app --factory --reload
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile

from sinergia.agents.reception.service import ReceptionInput, ReceptionResult
from sinergia.bootstrap import Container, build_container
from sinergia.core.domain import DocumentType
from sinergia.core.errors import NotFoundError, SessionStateError
from sinergia.core.settings import Settings

router = APIRouter()


def create_app(container: Container) -> FastAPI:
    """Cria a aplicação com o contêiner de dependências informado."""
    app = FastAPI(title="Sinergia", version="0.1.0")
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
