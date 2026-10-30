"""A crew real da CrewAI contra um servidor falso compatível com a OpenAI (sem rede)."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import SecretStr

from sinergia.core.settings import Settings
from sinergia.insights.crew import build_crew
from tests.conftest import NOW

pytest.importorskip("crewai")

ANSWERS = [
    "A Logística subiu para 9,6% (40 pessoas).",
    "# Relatório\n\nA Logística ficou em 9,6%.",
    "APROVADO\n# Relatório\n\nA Logística ficou em 9,6% na semana (40 pessoas).",
]


@pytest.fixture
def fake_llm():
    """Servidor local que responde como a API de chat do Groq/OpenAI."""
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silencia o servidor
            pass

        def do_POST(self) -> None:  # noqa: N802 — nome exigido pelo http.server
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            content = ANSWERS[min(len(requests), len(ANSWERS)) - 1]
            data = json.dumps(
                {
                    "id": "x",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", requests
    server.shutdown()


def test_crew_runs_three_agents_with_groq_model_name(fake_llm, settings: Settings) -> None:
    url, requests = fake_llm
    groq = settings.model_copy(
        update={"llm_provider": "groq", "groq_api_key": SecretStr("chave-de-teste")}
    )
    crew = build_crew(groq, base_url=url)
    result = crew.run("Período: 22/10/2026 a 28/10/2026.\n- Logística (40 pessoas): 9,6%")
    assert result.approved and "9,6%" in result.content
    assert [r["model"] for r in requests] == ["openai/gpt-oss-120b"] * 3
    roles = [r["messages"][0]["content"] for r in requests]
    assert ["Analista" in roles[0], "Redator" in roles[1], "Revisor" in roles[2]] == [True] * 3


def test_crew_is_only_built_with_groq_configured(settings: Settings) -> None:
    assert build_crew(settings) is None
    keyless = settings.model_copy(update={"llm_provider": "groq", "groq_api_key": None})
    assert build_crew(keyless) is None


def test_service_uses_the_real_crew(fake_llm, settings: Settings, make_app, monkeypatch) -> None:
    url, _ = fake_llm
    groq = settings.model_copy(
        update={"llm_provider": "groq", "groq_api_key": SecretStr("chave-de-teste")}
    )
    app = make_app(build_crew(groq, base_url=url))
    report = app.insights.run(NOW.date())
    assert report.method == "crew" and report.issues == []
