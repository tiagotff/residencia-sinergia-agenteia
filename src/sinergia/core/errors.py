"""Exceções de domínio da Sinergia."""


class SinergiaError(Exception):
    """Erro base da aplicação."""


class ConfigurationError(SinergiaError):
    """Configuração ausente ou inválida."""


class NotFoundError(SinergiaError):
    """Registro solicitado não existe."""


class SessionStateError(SinergiaError):
    """A sessão não está em um estado que aceite a operação pedida."""
