"""Relógio injetável, para que regras de prazo sejam testáveis."""

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]


def system_clock(timezone: str) -> Clock:
    """Retorna um relógio que lê a hora atual no fuso informado."""
    zone = ZoneInfo(timezone)
    return lambda: datetime.now(zone)


def fixed_clock(moment: datetime) -> Clock:
    """Retorna um relógio parado num instante, útil em testes."""
    return lambda: moment
