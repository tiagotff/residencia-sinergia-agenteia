"""Fábrica do modelo de linguagem, configurável por variável de ambiente.

Os agentes recebem um ``BaseChatModel`` (ou ``None``) e nunca importam o provedor
diretamente; trocar Groq por outro provedor muda só esta fábrica e o .env.
"""

from langchain_core.language_models import BaseChatModel

from sinergia.core.errors import ConfigurationError
from sinergia.core.settings import Settings


def build_chat_model(settings: Settings) -> BaseChatModel | None:
    """Cria o modelo de chat do provedor configurado, ou ``None`` sem LLM."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "groq":
        return _build_groq(settings)
    raise ConfigurationError(f"Provedor de LLM não suportado: {settings.llm_provider}")


def _build_groq(settings: Settings) -> BaseChatModel:
    """Cria o cliente do Groq a partir das configurações."""
    if settings.groq_api_key is None:
        raise ConfigurationError("GROQ_API_KEY não definida no .env para LLM_PROVIDER=groq.")
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        api_key=settings.groq_api_key,
        max_retries=2,
    )
