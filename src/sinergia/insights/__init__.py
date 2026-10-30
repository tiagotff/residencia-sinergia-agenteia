"""Crew de insights (CrewAI): relatório semanal para o SESMT a partir só de agregados.

Fica fora do fluxo dos casos: lê o banco, nunca decide sobre um caso, e se falhar o
relatório padrão (sem LLM) ocupa o lugar. Todo relatório é rascunho até o médico do
trabalho aprovar.
"""
