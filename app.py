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
def _clientes(top: int):
    return queries.clientes(top=top)


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _total(cidade: str | None, canal: str | None, cliente: int | None):
    return get_client().count(
        queries.filtro(cidade=cidade, canal=canal, cliente=cliente)
    )


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _vencedoras(cidade: str | None, canal: str | None, cliente: int | None):
    return queries.transportadoras_vencedoras(
        queries.filtro(cidade=cidade, canal=canal, cliente=cliente)
    )


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _pressao(canal: str | None, cliente: int | None):
    return queries.pressao_por_estado(queries.filtro(canal=canal, cliente=cliente))


@st.cache_data(ttl=TTL, show_spinner="Amostrando consultas...")
def _amostra(cidade: str | None, canal: str | None, cliente: int | None, max_docs: int):
    return queries.amostra(
        cidade=cidade, canal=canal, cliente=cliente, max_docs=max_docs
    )


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _canais_cliente(canal: str | None, cliente: int | None):
    return queries.canais_por_cliente(queries.filtro(canal=canal, cliente=cliente))


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _velocidade(cidade: str | None, canal: str | None, cliente: int | None):
    return queries.velocidade_transportadoras(
        queries.filtro(cidade=cidade, canal=canal, cliente=cliente)
    )


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _por_estado(canal: str | None, cliente: int | None):
    return queries.cotacoes_por_estado(queries.filtro(canal=canal, cliente=cliente))


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _erros_estado(canal: str | None, cliente: int | None):
    return queries.erros_por_estado(queries.filtro(canal=canal, cliente=cliente))


@st.cache_data(ttl=TTL, show_spinner="Consultando a Sisfrete...")
def _faixas_peso(cidade: str | None, canal: str | None, cliente: int | None):
    return queries.custo_por_faixa_peso(
        queries.filtro(cidade=cidade, canal=canal, cliente=cliente)
    )


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
        lojas = _clientes(top=40)
        nome_loja = st.selectbox("Cliente (loja)", ["Todos", *lojas["nome"]], index=0)
        max_docs = st.slider("Consultas amostradas", 1_000, 20_000, 2_000, 1_000)

    cidade = None if cidade == "Todas" else cidade
    canal = None if canal == "Todos" else canal
    cliente = (
        None
        if nome_loja == "Todos"
        else int(lojas.loc[lojas["nome"] == nome_loja, "cliente"].iloc[0])
    )

    painel, por_cliente, geografia, conversa = st.tabs(
        ["Dashboard", "Por cliente", "Geografia", "Pergunte aos dados"]
    )

    with conversa:
        _chat(cidade, canal, nome_loja)

    with painel:
        _dashboard(cidade, canal, cliente, nome_loja, canais, max_docs)

    with por_cliente:
        _por_cliente(cidade, canal, cliente, max_docs)

    with geografia:
        _geografia(canal, cliente, max_docs)


def _dashboard(cidade, canal, cliente, nome_loja, canais, max_docs) -> None:
    amostra = _amostra(cidade, canal, cliente, max_docs)
    cobertura = queries.cobertura(amostra)
    vencedoras = _vencedoras(cidade, canal, cliente)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Consultas no período", _br(_total(cidade, canal, cliente), 0))
    sem_opcao = (
        0.0
        if cobertura.empty
        else float(
            cobertura.loc[cobertura["faixa"] == "sem opção", "participacao"].sum()
        )
    )
    col2.metric("Consultas sem nenhuma opção", f"{sem_opcao:.0%}")
    col3.metric(
        "Custo mediano da mais barata",
        "—" if amostra.empty else f"R$ {_br(amostra['preco_barato'].median())}",
    )
    premio = amostra["premio_por_dia"].median() if not amostra.empty else float("nan")
    col4.metric(
        "Preço de um dia a menos",
        "—" if premio != premio else f"R$ {_br(premio)}",
    )

    if amostra.empty:
        st.info("Sem consultas para este filtro.")
        return

    st.subheader("1. Quem tem escolha e quem não tem")
    esq, dir_ = st.columns(2)
    esq.plotly_chart(
        charts.funil_cobertura(cobertura), width="stretch", key="funil"
    )
    dir_.plotly_chart(
        charts.pressao_estados(_pressao(canal, cliente)),
        width="stretch",
        key="pressao",
    )

    st.subheader("2. Quem ganha as cotações e a que preço")
    esq2, dir2 = st.columns(2)
    destino = cidade or (nome_loja if nome_loja != "Todos" else "todos os destinos")
    esq2.plotly_chart(
        charts.custo_x_prazo(vencedoras, f"Custo x prazo · {destino}"),
        width="stretch",
        key="custo_prazo",
    )
    dir2.plotly_chart(
        charts.comparativo_transportadoras(vencedoras),
        width="stretch",
        key="comparativo",
    )

    st.subheader("3. Onde o custo aperta")
    esq3, dir3 = st.columns(2)
    esq3.plotly_chart(
        charts.custo_por_faixa_peso(_faixas_peso(cidade, canal, cliente)),
        width="stretch",
        key="faixa_peso",
    )
    premios = queries.premio_por_dia(amostra)
    if premios.empty:
        dir3.info("Amostra sem par barato/rápido suficiente para medir o prêmio.")
    else:
        dir3.plotly_chart(
            charts.premio_por_dia(premios), width="stretch", key="premio"
        )

    st.plotly_chart(
        charts.volume_por_canal(canais), width="stretch", key="canais"
    )

    with st.expander("Transportadoras vencedoras · tabela"):
        st.dataframe(vencedoras, width="stretch")


def _por_cliente(cidade, canal, cliente, max_docs) -> None:
    """Canais, dispersão de preço, quem cobra mais e velocidade — por loja."""
    amostra = _amostra(cidade, canal, cliente, max_docs)

    st.subheader("Canais usados por cliente")
    mix = _canais_cliente(canal, cliente)
    if mix.empty:
        st.info("Sem consultas para este filtro.")
    else:
        st.plotly_chart(
            charts.canais_por_cliente(mix), width="stretch", key="mix_canais"
        )

    st.subheader("Maior desvio de preço dentro da mesma cotação")
    st.caption(
        "nf.menor_preco tem um elemento só — a dispersão real está entre as "
        "ofertas de nf.cotacoes da mesma consulta."
    )
    desvios = queries.maiores_desvios(amostra)
    por_uf = queries.desvio_por_estado(amostra)
    if desvios.empty:
        st.info("Amostra sem consultas com mais de uma oferta.")
    else:
        esq, dir_ = st.columns([3, 2])
        esq.dataframe(desvios, width="stretch", hide_index=True)
        dir_.plotly_chart(
            charts.desvio_estados(por_uf), width="stretch", key="desvio_uf"
        )

    st.subheader("Quem mais cobra quando ganha, e quem entrega mais rápido")
    vencedoras = _vencedoras(cidade, canal, cliente)
    esq2, dir2 = st.columns(2)
    if vencedoras.empty:
        esq2.info("Sem transportadoras vencedoras neste filtro.")
    else:
        caras = vencedoras.nlargest(10, "custo_mediano")
        esq2.dataframe(
            caras[["transportadora", "custo_mediano", "custo_medio", "cotacoes"]],
            width="stretch",
            hide_index=True,
        )
    velocidade = _velocidade(cidade, canal, cliente)
    if velocidade.empty:
        dir2.info("Sem dados de prazo neste filtro.")
    else:
        dir2.plotly_chart(
            charts.velocidade_transportadoras(velocidade),
            width="stretch",
            key="velocidade",
        )


def _geografia(canal, cliente, max_docs) -> None:
    """Destino: volume, cobertura e preço por quilômetro."""
    st.subheader("Consultas por estado de destino")
    st.caption("Use o filtro de canal na barra lateral para ver o efeito do canal.")
    estados = _por_estado(canal, cliente)
    erros = _erros_estado(canal, cliente)
    esq, dir_ = st.columns(2)
    if estados.empty:
        esq.info("Sem consultas para este filtro.")
    else:
        esq.plotly_chart(
            charts.cotacoes_estados(estados), width="stretch", key="uf_volume"
        )
    if erros.empty:
        dir_.info("Sem dados de cobertura para este filtro.")
    else:
        dir_.plotly_chart(
            charts.sem_cobertura_estados(erros), width="stretch", key="uf_erro"
        )

    st.subheader("Preço por quilômetro")
    st.caption(
        "Distância aproximada entre a capital da UF de origem (CEP de "
        "nf.request_item.origin) e a capital do destino. O CEP de origem "
        "aparece em parte das consultas; o resto fica de fora do cálculo."
    )
    amostra = _amostra(None, canal, cliente, max_docs)
    por_km = queries.preco_por_km(amostra)
    if por_km.empty:
        st.info("Amostra sem CEP de origem suficiente para calcular km.")
    else:
        st.plotly_chart(charts.preco_por_km(por_km), width="stretch", key="preco_km")


def _chat(cidade: str | None, canal: str | None, loja: str = "Todos") -> None:
    """Conversa com os dados: o modelo chama as funções de queries.py."""
    st.caption(
        "Pergunte em português. Ex.: “qual transportadora é mais barata em "
        "GOIANIA?” ou “como o custo muda com o peso no Mercado Livre?”"
    )
    if "historico" not in st.session_state:
        st.session_state.historico = []

    for i, msg in enumerate(st.session_state.historico):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for j, fig in enumerate(msg.get("figuras", [])):
                st.plotly_chart(fig, width="stretch", key=f"hist_{i}_{j}")

    pergunta = st.chat_input("Pergunte sobre as cotações")
    if not pergunta:
        return

    ativos = (
        f"cidade {cidade}" if cidade else "",
        f"canal {canal}" if canal else "",
        f"loja {loja}" if loja != "Todos" else "",
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
        rodada = len(st.session_state.historico)
        for j, fig in enumerate(figuras):
            st.plotly_chart(fig, width="stretch", key=f"nova_{rodada}_{j}")

    st.session_state.historico.append(
        {"role": "assistant", "content": texto, "figuras": figuras}
    )


if __name__ == "__main__":
    try:
        get_client().ping()
        main()
    except SisfreteError as exc:
        st.error(str(exc))
