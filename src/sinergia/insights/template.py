"""Relatório padrão, sem LLM: usado quando não há crew ou quando ela é barrada na conferência."""

from sinergia.insights.facts import Facts, _counts, _pct, _pp

_ACTIONS = {
    "A01": "Conversar com a gestão de {grupo} sobre mudanças recentes (escala, demanda, clima) "
    "que possam explicar a alta.",
    "A02": "Avaliar com o médico do trabalho as condições de {grupo} (ergonomia, ambiente) e a "
    "possível relação com o trabalho.",
    "A03": "Rever com o gestor e o RH a cobertura de {grupo}.",
}


def template_report(facts: Facts) -> str:
    """Relatório em Markdown com resumo, tendências, alertas, encaminhamentos e sugestões."""
    parts = [
        f"# Relatório de saúde ocupacional — {facts.period_start:%d/%m/%Y} a "
        f"{facts.period_end:%d/%m/%Y}",
        _summary(facts),
        _sectors(facts),
        _alerts(facts),
        _tasks(facts),
        _actions(facts),
        "_Rascunho gerado só com dados agregados; publicar depois da aprovação do médico do "
        "trabalho._",
    ]
    return "\n\n".join(parts)


def _summary(facts: Facts) -> str:
    """Números gerais do período."""
    return (
        f"## Resumo\n\n{facts.employees} colaboradores ativos, {len(facts.alerts)} alerta(s) de "
        f"grupo no período e {facts.tasks['vencidas']} encaminhamento(s) vencido(s)."
    )


def _sectors(facts: Facts) -> str:
    """Tabela de taxas por setor."""
    rows = [
        f"| {s['setor']} | {s['pessoas']} | {_pct(s['taxa_semana_pct'])} | "
        f"{_pct(s['media_anterior_pct'])} | {_pp(s['variacao_pp'])} |"
        for s in facts.sectors
    ]
    header = (
        "| Setor | Pessoas | Taxa na semana | Média anterior | Variação |\n"
        "| --- | --- | --- | --- | --- |"
    )
    return "## Tendências por setor\n\n" + "\n".join([header, *rows])


def _alerts(facts: Facts) -> str:
    """Alertas de grupo do período."""
    items = [f"- {a['regra']} em {a['grupo']}: {a['descricao']}." for a in facts.alerts]
    return "## Alertas do período\n\n" + ("\n".join(items) or "Nenhum alerta de grupo.")


def _tasks(facts: Facts) -> str:
    """Situação dos encaminhamentos."""
    tasks = facts.tasks
    return (
        f"## Encaminhamentos\n\nPor situação: {_counts(tasks['por_situacao'])}. Abertos por "
        f"destino: {_counts(tasks['abertas_por_destino'])}. Vencidos: {tasks['vencidas']}."
    )


def _actions(facts: Facts) -> str:
    """Sugestões de ação preventiva, uma por alerta, mais os vencidos."""
    items = [f"- {_ACTIONS[a['regra']].format(grupo=a['grupo'])}" for a in facts.alerts]
    if facts.tasks["vencidas"]:
        items.append(f"- Priorizar os {facts.tasks['vencidas']} encaminhamento(s) vencido(s).")
    items = items or ["- Manter o acompanhamento semanal."]
    return "## Sugestões de ação preventiva\n\n" + "\n".join(items)
