"""Leitura de datas nos formatos usados em atestados e planilhas brasileiras."""

from datetime import date, datetime
from typing import Any

_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def parse_date(value: Any) -> date | None:
    """Converte DD/MM/AAAA, AAAA-MM-DD e variações em ``date``."""
    if value is None or isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
