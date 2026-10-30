"""Painel da Sinergia por perfil (Streamlit).

Execução: ``sinergia dashboard`` ou ``streamlit run src/sinergia/dashboard/app.py``.
Os dados vêm de ``views.py``; aqui só se desenha a tela.
"""

from datetime import date

import pandas as pd
import streamlit as st

from sinergia.bootstrap import Container, build_container
from sinergia.core.settings import Settings
from sinergia.dashboard import views


@st.cache_resource
def _container() -> Container:
    """Aplicação montada uma vez por sessão do Streamlit."""
    return build_container(Settings())


def main() -> None:
    """Escolha do perfil e da data, e a tela do perfil."""
    st.set_page_config(page_title="Sinergia", layout="wide")
    container = _container()
    st.sidebar.title("Sinergia")
    profile = st.sidebar.radio("Perfil", views.PROFILES)
    today = st.sidebar.date_input("Data de referência", value=container.clock().date())
    st.sidebar.caption("Perfil escolhido na tela: o controle de acesso entra com a autenticação.")
    PAGES[profile](container, today)


def employee_page(container: Container, _: date) -> None:
    """Acompanhamento do próprio atestado."""
    st.header("Acompanhamento da solicitação")
    protocol = st.text_input("Protocolo", placeholder="SNG-AAAAMMDD-XXXXXX")
    if not protocol:
        return
    case = views.employee_case(container, protocol)
    if case is None:
        st.warning("Protocolo não encontrado.")
        return
    st.write(f"Recebido em {case['recebido_em']} — situação: **{case['entrada']}**")
    if case["afastamento"]:
        st.json(case["afastamento"])
    _table("Pendências", [{"pendencia": kind} for kind in case["pendencias"]])
    _table("Encaminhamentos", case["encaminhamentos"])


def hr_page(container: Container, today: date) -> None:
    """Volume, automação, fila e prazos."""
    st.header("RH / Departamento Pessoal")
    data = views.hr_overview(container, today)
    cols = st.columns(4)
    cols[0].metric("Documentos recebidos", data["recebidos"])
    cols[1].metric("Afastamentos registrados", data["afastamentos"])
    cols[2].metric("Processados sem revisão", f"{data['automatico_pct']:.1f}%")
    cols[3].metric("Na fila de revisão", data["fila_revisao"])
    _table("Tarefas abertas (INSS, mesma doença, alertas)", data["tarefas"])


def manager_page(container: Container, today: date) -> None:
    """Ausências e cobertura, sem informação de saúde."""
    st.header("Painel de ausências")
    sectors = views.manager_view(container, today)["setores"]
    sector = st.selectbox("Setor", ["Todos", *sectors])
    data = views.manager_view(container, today, None if sector == "Todos" else sector)
    st.metric("Ausentes hoje", len(data["ausentes"]))
    _table("Quem está ausente e até quando", data["ausentes"])
    _table("Cobertura das funções críticas", data["cobertura"])
    _table("Tarefas do gestor", data["tarefas"])


def sesmt_page(container: Container, today: date) -> None:
    """Alertas, tendência, tarefas da saúde e relatório da crew."""
    st.header("SESMT / médico do trabalho")
    data = views.sesmt_view(container, today)
    trend = data["tendencia"]
    if trend["series"]:
        st.subheader("Taxa semanal de afastamento por setor (%)")
        st.line_chart(pd.DataFrame(trend["series"], index=trend["semanas"]))
        st.caption(
            "Cada ponto é a semana que termina na data; grupos com menos de 5 pessoas "
            "ficam fora (A05)."
        )
    _table("Alertas", data["alertas"])
    _table("Tarefas da saúde", data["tarefas"])
    _reports(container, today, data["relatorios"])


def _reports(container: Container, today: date, reports: list) -> None:
    """Gerar, ler e aprovar o relatório da crew."""
    st.subheader("Relatório de insights")
    if st.button("Gerar rascunho do período"):
        container.insights.run(today)
        st.rerun()
    if not reports:
        st.info("Nenhum relatório ainda.")
        return
    report = reports[0]
    st.caption(f"#{report.id} — {report.status.value} — feito por: {report.method}")
    st.markdown(_demote(report.content))
    if report.status.value == "rascunho":
        by = st.text_input("Médico do trabalho (nome)")
        if by and st.button("Aprovar"):
            container.insights.decide(report.id, True, by)
            st.rerun()


def _demote(markdown: str) -> str:
    """Desce dois níveis os títulos do relatório, para caberem na página."""
    return "\n".join(
        f"##{line}" if line.startswith("#") else line for line in markdown.splitlines()
    )


def audit_page(container: Container, _: date) -> None:
    """Trilha de auditoria."""
    st.header("Trilha de auditoria")
    actor = st.text_input("Filtrar por ator (opcional)")
    _table("Entradas mais recentes", views.audit_trail(container, actor=actor or None))


LABELS = {
    "id": "Nº",
    "regra": "Regra",
    "assunto": "Assunto",
    "area": "Área",
    "urgencia": "Urgência",
    "prazo": "Prazo",
    "vencida": "Vencida",
    "resumo": "Resumo",
    "matricula": "Matrícula",
    "setor": "Setor",
    "funcao": "Função",
    "turno": "Turno",
    "ausente_ate": "Ausente até",
    "equipe": "Equipe",
    "disponiveis": "Disponíveis",
    "disponivel_pct": "% disponível",
    "grupo": "Grupo",
    "periodo": "Período",
    "pessoas_no_grupo": "Pessoas no grupo",
    "grupo_cid": "Grupo de CID",
    "situacao": "Situação",
    "explicacao": "Explicação",
    "pendencia": "Pendência",
    "occurred_at": "Quando",
    "actor": "Quem",
    "action": "Ação",
    "reference": "Referência",
    "rule_ids": "Regras",
    "rules_version": "Versão das regras",
    "details": "Detalhes",
}


def _table(title: str, rows: list[dict]) -> None:
    """Tabela com título e colunas com nomes legíveis, ou aviso de vazio."""
    st.subheader(title)
    if rows:
        frame = pd.DataFrame(rows).rename(columns=LABELS)
        st.dataframe(frame.astype(str), width="stretch", hide_index=True)
    else:
        st.caption("Nada a mostrar.")


PAGES = {
    "Colaborador": employee_page,
    "RH/DP": hr_page,
    "Gestor": manager_page,
    "SESMT / médico do trabalho": sesmt_page,
    "Auditoria": audit_page,
}

main()
