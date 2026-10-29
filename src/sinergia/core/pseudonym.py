"""Pseudonimização: o Agente 3 nunca trabalha com a matrícula, só com um identificador derivado.

HMAC-SHA256 com um sal guardado fora do código. Sem o sal, não dá para voltar do
pseudônimo à matrícula; com ele, a reidentificação só acontece na requisição de detalhe.
"""

import hashlib
import hmac


def pseudonymize(employee_id: str, salt: str) -> str:
    """Identificador estável e não reversível sem o sal (ex.: P-3f9a1c27b0)."""
    digest = hmac.new(salt.encode(), employee_id.encode(), hashlib.sha256).hexdigest()
    return f"P-{digest[:10]}"
