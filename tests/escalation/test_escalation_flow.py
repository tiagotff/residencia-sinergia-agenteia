"""Agente 4 de ponta a ponta: propostas, confirmação humana, prazos, CLI e API."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sinergia.agents.escalation.models import EscalationDecision
from sinergia.api.app import create_app
from sinergia.bootstrap import Container
from sinergia.cli import main
from sinergia.core.errors import SessionStateError
from sinergia.data.tasks import TaskStatus
from tests.escalation.conftest import Clock

Submit = Callable[..., str]


def _decide(app: Container, session_id: str, **kwargs) -> list:
    return app.escalation.decide(session_id, EscalationDecision(reviewer="Ana (SESMT)", **kwargs))


def _by_rule(app: Container, session_id: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for task in app.tasks.for_session(session_id):
        found.setdefault(task.rule_id, []).append(task.destination)
    return found


def test_cycle_proposes_and_waits_for_confirmation(app: Container, cycle: str) -> None:
    [pending] = app.escalation.pending()
    assert (pending.session_id, pending.origin) == (cycle, "ciclo")
    assert _by_rule(app, cycle) == {
        "A01": ["sesmt", "gestor"],
        "A02": ["sesmt", "medico_trabalho", "sesmt", "medico_trabalho"],
        "A03": ["gestor"],
        "A04": ["medico_trabalho", "rh_dp"],
    }
    assert all(t.status is TaskStatus.PROPOSED for t in app.tasks.for_session(cycle))


def test_confirmation_opens_tasks_with_due_dates(app: Container, cycle: str) -> None:
    tasks = _decide(app, cycle, cancel=[4], redirect={2: "rh_dp"})
    status = {task.id: (task.status, task.destination) for task in tasks}
    assert status[4] == (TaskStatus.CANCELLED, "medico_trabalho")
    assert status[2] == (TaskStatus.OPEN, "rh_dp")
    coverage = next(task for task in tasks if task.rule_id == "A03")
    assert coverage.due_date == app.clock().date()
    assert app.escalation.pending() == []


def test_forbidden_or_foreign_choices_are_refused(app: Container, cycle: str) -> None:
    a02 = next(t for t in app.tasks.for_session(cycle) if t.rule_id == "A02")
    with pytest.raises(ValueError, match="gestor"):
        _decide(app, cycle, redirect={a02.id: "gestor"})
    with pytest.raises(ValueError, match="não são desta confirmação"):
        _decide(app, cycle, cancel=[999])
    with pytest.raises(SessionStateError):
        _decide(app, "sessao-inexistente")
    assert len(app.escalation.pending()) == 1


def test_overdue_tasks_climb_the_chain_then_expire(
    app: Container, cycle: str, clock: Clock
) -> None:
    _decide(app, cycle)
    clock.advance(11)
    first = app.escalation.sweep()
    assert first.reescalated and not first.expired
    child = app.tasks.get(first.reescalated[0])
    assert (child.attempt, child.status, child.parent_id) == (1, TaskStatus.OPEN, 1)
    assert child.destination == "coordenacao_sesmt" and child.urgency == "alta"
    clock.advance(11)
    app.escalation.sweep()
    clock.advance(11)
    last = app.escalation.sweep()
    assert last.expired and not last.reescalated
    assert {t.status for t in app.tasks.find(TaskStatus.OPEN)} == set()


def test_done_tasks_are_not_reescalated(app: Container, cycle: str, clock: Clock) -> None:
    tasks = _decide(app, cycle)
    done = app.escalation.complete(tasks[0].id, "Carla (SESMT)", "visita ao setor agendada")
    assert done.status is TaskStatus.DONE
    with pytest.raises(SessionStateError):
        app.escalation.complete(tasks[0].id, "Carla (SESMT)")
    clock.advance(11)
    assert tasks[0].id not in {t.parent_id for t in app.tasks.find()}
    app.escalation.sweep()
    assert app.tasks.get(tasks[0].id).status is TaskStatus.DONE


def test_long_absence_case_pauses_for_confirmation(app: Container, submit: Submit) -> None:
    protocol = submit("atestado_retorno_35dias")
    session = app.absences.get(protocol).session_id
    assert _by_rule(app, session) == {
        "R10": ["rh_dp"],
        "R12": ["sesmt", "medico_trabalho", "gestor"],
    }
    [pending] = app.escalation.pending()
    assert pending.origin == "caso"
    _decide(app, session)
    r10 = next(t for t in app.tasks.for_session(session) if t.rule_id == "R10")
    assert r10.status is TaskStatus.OPEN and r10.subject == "9001"


def test_injury_goes_to_sesmt_with_cid_only_for_health(app: Container, submit: Submit) -> None:
    protocol = submit("atestado_lesao_punho")
    tasks = app.tasks.for_session(app.absences.get(protocol).session_id)
    assert [(t.rule_id, t.destination) for t in tasks] == [
        ("R13", "sesmt"),
        ("R13", "medico_trabalho"),
    ]
    assert all("S62" in t.summary for t in tasks)
    audit = app.audit.list_for(protocol)
    assert "S62" not in str([entry.details for entry in audit])


def test_ordinary_certificate_creates_no_task(app: Container, submit: Submit) -> None:
    submit("atestado_medico")
    assert app.tasks.find() == [] and app.escalation.pending() == []


def test_cli_lists_shows_and_decides(
    app: Container, cycle: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    for key, value in {
        "DATA_DIR": str(app.settings.data_dir),
        "LLM_PROVIDER": "none",
        "CRM_VERIFIER": "local",
    }.items():
        monkeypatch.setenv(key, value)
    assert main(["escalation", "list"]) == 0
    assert main(["escalation", "show", cycle]) == 0
    assert (
        main(
            [
                "escalation",
                "decide",
                cycle,
                "--reviewer",
                "Ana (SESMT)",
                "--cancel",
                "4",
                "--redirect",
                "3=gestor",
            ]
        )
        == 1
    )
    assert main(["escalation", "decide", cycle, "--reviewer", "Ana (SESMT)", "--cancel", "4"]) == 0
    assert main(["tasks", "list", "--destination", "gestor"]) == 0
    assert main(["tasks", "done", "1", "--by", "Carla (SESMT)"]) == 0
    assert main(["escalation", "sweep"]) == 0
    out = capsys.readouterr()
    assert "9 proposta(s)" in out.out and "(principal)" in out.out
    assert "gestor não recebe" in out.err
    assert "[A03] → gestor (critica" in out.out and "[concluido]" in out.out


def test_api_confirms_lists_and_completes(app: Container, cycle: str) -> None:
    client = TestClient(create_app(app))
    [pending] = client.get("/escalation/pending").json()
    assert len(pending["payload"]["tasks"]) == 9
    refused = client.post(
        f"/escalation/pending/{cycle}/decision",
        json={"reviewer": "Ana (SESMT)", "redirect": {"3": "gestor"}},
    )
    assert refused.status_code == 422
    tasks = client.post(
        f"/escalation/pending/{cycle}/decision", json={"reviewer": "Ana (SESMT)"}
    ).json()
    assert {task["status"] for task in tasks} == {"aberto"}
    manager = client.get("/tasks", params={"destination": "gestor"}).json()
    assert {task["rule_id"] for task in manager} == {"A01", "A03"}
    done = client.post(f"/tasks/{tasks[0]['id']}/complete", json={"by": "Carla (SESMT)"})
    assert done.json()["status"] == "concluido"
    assert client.post(f"/tasks/{tasks[0]['id']}/complete", json={"by": "Carla"}).status_code == 409
    assert client.get("/escalation/pending/nada").status_code == 404
    assert client.post("/escalation/sweep").json() == {"reescalated": [], "expired": []}


def test_cycle_rerun_does_not_duplicate(app: Container, cycle: str) -> None:
    again = app.monitoring.run(app.clock().date())
    assert again["proposals"] == 0
    assert len(app.tasks.find()) == 9


def test_samples_folder_has_new_certificates(samples: Path) -> None:
    assert (samples / "atestado_retorno_35dias.pdf").exists()
    assert (samples / "atestado_lesao_punho.pdf").exists()
