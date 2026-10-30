"""Crew de insights em CrewAI: analista de tendências → redator → revisor de privacidade.

A crew só recebe o texto dos fatos (agregados). O revisor responde "APROVADO" ou
"DEVOLVIDO: motivo" na primeira linha e o relatório final depois. A CrewAI é opcional
(extra ``insights``): sem ela, ou sem LLM configurado, vale o relatório padrão.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from sinergia.core.settings import Settings

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_RULES = (
    "Regras: use só os números do texto de fatos, exatamente como estão escritos; não cite "
    "pessoas, matrículas, pseudônimos nem códigos de CID; trate de grupos, nunca de indivíduos; "
    "não culpe ninguém e evite termos estigmatizantes; escreva em português do Brasil."
)


@dataclass
class CrewResult:
    """Resposta do revisor: veredito e texto."""

    approved: bool
    content: str
    reason: str = ""


class InsightsCrew:
    """Monta e roda a crew sequencial com o LLM informado."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def run(self, facts_text: str) -> CrewResult:
        """Roda as três tarefas e interpreta o veredito do revisor."""
        crew = self.build(facts_text)
        output = crew.kickoff()
        return parse_verdict(str(getattr(output, "raw", output)))

    def build(self, facts_text: str) -> Any:
        """Agentes e tarefas da crew (sem chamar o LLM)."""
        from crewai import Crew, Process, Task

        agents = self._agents()
        tasks: list[Any] = []
        for agent, (describe, expected) in zip(agents, _TASKS, strict=True):
            context = {"context": [tasks[-1]]} if tasks else {}
            tasks.append(
                Task(
                    description=describe(facts_text),
                    expected_output=expected,
                    agent=agent,
                    **context,
                )
            )
        return Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)

    def _agents(self) -> list[Any]:
        """Os três papéis da crew, na ordem em que trabalham."""
        from crewai import Agent

        return [
            Agent(
                role=role,
                goal=goal,
                backstory=backstory,
                llm=self._llm,
                allow_delegation=False,
                verbose=False,
            )
            for role, goal, backstory in _ROLES
        ]


_ROLES = (
    (
        "Analista de tendências",
        "Apontar o que mudou nos afastamentos por grupo",
        "Epidemiologista ocupacional que só afirma o que os números mostram.",
    ),
    (
        "Redator de saúde ocupacional",
        "Transformar achados em ações preventivas",
        "Escreve para o SESMT com clareza, sem jargão e sem culpar pessoas.",
    ),
    (
        "Revisor de privacidade",
        "Garantir que o relatório respeite a LGPD",
        "Encarregado de dados: barra indivíduos, CID, grupos pequenos e estigma.",
    ),
)


def _analyze(facts_text: str) -> str:
    """Tarefa do analista."""
    return f"Analise os fatos e liste o que mudou no período.\n\n{_RULES}\n\nFatos:\n{facts_text}"


def _draft(facts_text: str) -> str:
    """Tarefa do redator."""
    return (
        "Escreva o relatório semanal para o SESMT em Markdown, com as seções: Resumo, "
        "Tendências por setor, Alertas do período, Encaminhamentos e Sugestões de ação "
        f"preventiva. Até 400 palavras.\n\n{_RULES}\n\nFatos:\n{facts_text}"
    )


def _review(facts_text: str) -> str:
    """Tarefa do revisor de privacidade."""
    return (
        "Revise o relatório. Se ele cumprir as regras, responda APROVADO na primeira linha e o "
        "relatório inteiro em seguida. Se não der para corrigir, responda DEVOLVIDO: motivo. "
        f"Se der, corrija e responda APROVADO com o texto corrigido.\n\n{_RULES}\n\n"
        f"Fatos:\n{facts_text}"
    )


_TASKS = (
    (_analyze, "Lista de achados, cada um com métrica, grupo e período."),
    (_draft, "Relatório em Markdown com as seções pedidas."),
    (_review, "APROVADO ou DEVOLVIDO na primeira linha; depois o relatório."),
)


def parse_verdict(raw: str) -> CrewResult:
    """Primeira linha = veredito; o resto = relatório."""
    first, _, rest = raw.strip().partition("\n")
    verdict = first.strip().strip("*#").strip()
    if verdict.upper().startswith("APROVADO"):
        return CrewResult(approved=True, content=rest.strip())
    reason = verdict.partition(":")[2].strip() or "sem motivo informado"
    return CrewResult(approved=False, content=rest.strip(), reason=reason)


def build_crew(settings: Settings, base_url: str = GROQ_BASE_URL) -> InsightsCrew | None:
    """A crew com o Groq pelo caminho compatível com a OpenAI, ou None se indisponível."""
    if settings.llm_provider != "groq" or settings.groq_api_key is None:
        return None
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    try:
        from crewai import LLM
    except ImportError:
        logger.warning("CrewAI não instalada (extra 'insights'); usando o relatório padrão.")
        return None
    logging.getLogger("crewai.llms.base_llm").setLevel(logging.ERROR)
    llm = LLM(
        model=f"openai/{settings.llm_model}",  # a CrewAI remove o primeiro "openai/"
        custom_openai=True,
        base_url=base_url,
        api_key=settings.groq_api_key.get_secret_value(),
        temperature=settings.llm_temperature,
    )
    return InsightsCrew(llm)
