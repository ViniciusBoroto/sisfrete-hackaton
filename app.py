"""Dashboard Streamlit — Frete Estratégico em Dados (Hackathon Unimar 2026).

Pergunta central: qual é o equilíbrio entre custo e prazo das transportadoras
para cada destino?
"""

from __future__ import annotations

import streamlit as st

import charts
import chat
import queries
from api import SisfreteError, get_client

st.set_page_config(page_title="Frete Estratégico", page_icon="📦", layout="wide")

TTL = 600  # dados de setembro seguem chegando; 10 min de cache basta.


def _br(valor: float, casas: int = 2) -> str:
    """Formata número no padrão brasileiro (1.234,56)."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _cidades(top: int):
    return queries.cidades(top=top)


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _canais():
    return queries.canais()


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _total(cidade: str | None, canal: str | None):
    return get_client().count(queries.filtro(cidade=cidade, canal=canal))


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _faixas_peso(cidade: str | None, canal: str | None):
    return queries.custo_por_faixa_peso(queries.filtro(cidade=cidade, canal=canal))


@st.cache_data(ttl=TTL, show_spinner="Baixando cotações...")
def _detalhe(cidade: str | None, canal: str | None, max_docs: int):
    return queries.cotacoes_detalhadas(cidade=cidade, canal=canal, max_docs=max_docs)


def main() -> None:
    st.title("📦 Frete Estratégico em Dados")
    st.caption("Cotações da Sisfrete · setembro/2026 · Grupo 05")

    with st.sidebar:
        st.header("Filtros")
        # A carga cobre 01/09 a 14/09; séries temporais caberiam em duas
        # janelas de 7 dias, então os gráficos cortam por outras dimensões.
        st.caption("Período: 01/09 a 14/09/2026")
        cidades = _cidades(top=50)
        cidade = st.selectbox(
            "Cidade de destino", ["Todas", *cidades["cidade"]], index=0
        )
        canais = _canais()
        canal = st.selectbox("Canal de venda", ["Todos", *canais["canal"]], index=0)
        max_docs = st.slider("Documentos por análise", 1_000, 20_000, 2_000, 1_000)

    cidade = None if cidade == "Todas" else cidade
    canal = None if canal == "Todos" else canal

    detalhe = _detalhe(cidade, canal, max_docs)
    resumo = queries.resumo_transportadoras(detalhe)

    painel, conversa = st.tabs(["Dashboard", "Pergunte aos dados"])

    with conversa:
        _chat(cidade, canal)

    with painel:
        _dashboard(detalhe, resumo, cidade, canal, canais)


def _dashboard(detalhe, resumo, cidade, canal, canais) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Cotações no período", _br(_total(cidade, canal), 0))
    col2.metric("Transportadoras", 0 if resumo.empty else len(resumo))
    col3.metric(
        "Custo médio",
        "—" if resumo.empty else f"R$ {_br(detalhe['total'].mean())}",
    )

    st.plotly_chart(
        charts.custo_por_faixa_peso(_faixas_peso(cidade, canal)), width="stretch"
    )

    if resumo.empty:
        st.info("Sem cotações para este filtro.")
        return

    esq, dir_ = st.columns(2)
    esq.plotly_chart(
        charts.custo_x_prazo(resumo, f"Custo x prazo · {cidade or 'todos os destinos'}"),
        width="stretch",
    )
    dir_.plotly_chart(
        charts.comparativo_transportadoras(resumo), width="stretch"
    )

    st.plotly_chart(charts.volume_por_canal(canais), width="stretch")

    with st.expander("Detalhamento por transportadora"):
        st.dataframe(resumo, width="stretch")


def _chat(cidade: str | None, canal: str | None) -> None:
    """Conversa com os dados: o modelo chama as funções de queries.py."""
    st.caption(
        "Pergunte em português. Ex.: “qual transportadora é mais barata em "
        "GOIANIA?” ou “como o custo muda com o peso no Mercado Livre?”"
    )
    if "historico" not in st.session_state:
        st.session_state.historico = []

    for msg in st.session_state.historico:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for fig in msg.get("figuras", []):
                st.plotly_chart(fig, width="stretch")

    pergunta = st.chat_input("Pergunte sobre as cotações")
    if not pergunta:
        return

    ativos = (
        f"cidade {cidade}" if cidade else "",
        f"canal {canal}" if canal else "",
    )
    contexto = ", ".join(f for f in ativos if f)
    if contexto:
        pergunta += f" (Filtros ativos no dashboard: {contexto}.)"

    st.session_state.historico.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"), st.spinner("Consultando os dados..."):
        try:
            texto, figuras = chat.responder(
                [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.historico
                ]
            )
        except chat.ChatIndisponivel as exc:
            st.warning(str(exc))
            st.session_state.historico.pop()
            return
        st.markdown(texto)
        for fig in figuras:
            st.plotly_chart(fig, width="stretch")

    st.session_state.historico.append(
        {"role": "assistant", "content": texto, "figuras": figuras}
    )


if __name__ == "__main__":
    try:
        get_client().ping()
        main()
    except SisfreteError as exc:
        st.error(str(exc))
