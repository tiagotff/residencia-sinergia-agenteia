"""Configuração da aplicação, lida de variáveis de ambiente e do arquivo .env."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parâmetros de execução; segredos nunca ficam no código."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["groq", "none"] = "none"
    llm_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.2
    groq_api_key: SecretStr | None = None
    data_dir: Path = Path("data")
    rules_path: Path = Path("config/rules.yaml")
    timezone: str = "America/Sao_Paulo"
    crm_verifier: Literal["cfm", "local", "none"] = "none"
    cfm_access_key: SecretStr | None = None
    cfm_wsdl_url: str = (
        "https://ws.cfm.org.br:8080/WebServiceConsultaMedicos/ServicoConsultaMedicos?wsdl"
    )
    cfm_timeout_seconds: float = 10.0
    crm_registry_path: Path = Path("config/crm_registry.yaml")
    pseudonym_salt: SecretStr = SecretStr("sal-de-desenvolvimento-troque-no-env")

    @property
    def database_path(self) -> Path:
        """Caminho do banco SQLite de negócio."""
        return self.data_dir / "sinergia.sqlite"

    @property
    def checkpoint_path(self) -> Path:
        """Caminho do banco SQLite de checkpoints do LangGraph."""
        return self.data_dir / "checkpoints.sqlite"

    @property
    def ocr_models_dir(self) -> Path:
        """Pasta dos modelos do EasyOCR (baixados no primeiro uso)."""
        return self.data_dir / "ocr_models"

    @property
    def files_dir(self) -> Path:
        """Pasta raiz dos arquivos recebidos."""
        return self.data_dir / "files"
