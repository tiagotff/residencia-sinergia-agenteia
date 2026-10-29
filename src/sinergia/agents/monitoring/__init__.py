"""Agente 3 — Monitoramento (reativo baseado em modelo).

Objetivo: detectar padrões fora do esperado. Mantém uma representação interna da base
(linha de base por setor, grupos de CID, cobertura de funções críticas) e compara o
estado atual com ela. Trabalha só com pseudônimos e emite alertas sobre grupos.
"""
