"""Gráficos Plotly construídos a partir dos DataFrames de queries.py."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

TEMPLATE = "plotly_white"


def custo_x_prazo(resumo: pd.DataFrame, titulo: str = "Custo x prazo") -> go.Figure:
    """Trade-off preço/prazo: cada ponto é uma transportadora.

    O tamanho é o volume de cotações; cor por transportadora viraria uma
    legenda de centenas de itens, então ela fica no hover.
    """
    # Mediana no eixo: a média de uma transportadora com poucas cotações caras
    # estica o gráfico e esconde o pelotão.
    fig = px.scatter(
        resumo,
        x="prazo_medio",
        y="custo_mediano",
        size="cotacoes",
        color="cotacoes",
        color_continuous_scale="Teal",
        hover_name=resumo["transportadora"].astype(str),
        hover_data={"custo_medio": ":.2f"},
        labels={
            "prazo_medio": "Prazo médio (dias)",
            "custo_mediano": "Custo mediano (R$)",
            "custo_medio": "Custo médio (R$)",
            "cotacoes": "Cotações",
        },
        title=titulo,
        template=TEMPLATE,
    )
    fig.update_traces(marker=dict(line=dict(width=0.5, color="rgba(255,255,255,.4)")))
    return fig


def comparativo_transportadoras(resumo: pd.DataFrame, top: int = 15) -> go.Figure:
    """Custo médio das transportadoras com maior volume, prazo no eixo direito."""
    resumo = resumo.nlargest(top, "cotacoes").sort_values("custo_mediano")
    fig = go.Figure()
    rotulos = resumo["transportadora"].astype(str)
    fig.add_bar(
        x=rotulos,
        y=resumo["custo_mediano"],
        name="Custo mediano (R$)",
        customdata=resumo[["custo_medio"]],
        hovertemplate="Transportadora %{x}<br>Mediano: R$ %{y:.2f}"
        "<br>Médio: R$ %{customdata[0]:.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=rotulos,
        y=resumo["prazo_medio"],
        name="Prazo médio (dias)",
        yaxis="y2",
        mode="lines+markers",
    )
    fig.update_layout(
        template=TEMPLATE,
        title=f"Custo e prazo · {top} transportadoras com mais volume",
        xaxis_title="Transportadora",
        xaxis_type="category",
        yaxis_title="Custo mediano (R$)",
        yaxis2=dict(title="Prazo médio (dias)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def _rotulo_janela(df: pd.DataFrame, dias: int) -> pd.Series:
    """"01–07/09" em vez de uma data solta: deixa o corte explícito."""
    inicio = df["janela"].dt.tz_localize(None)
    fim = inicio + pd.Timedelta(days=dias - 1)
    return inicio.dt.strftime("%d/%m") + "–" + fim.dt.strftime("%d/%m")


def volume_por_janela(df: pd.DataFrame, dias: int = 7) -> go.Figure:
    """Volume de cotações por janela fixa, com o custo médio sobreposto."""
    rotulos = _rotulo_janela(df, dias)
    fig = go.Figure()
    fig.add_bar(x=rotulos, y=df["cotacoes"], name="Cotações")
    fig.add_scatter(
        x=rotulos,
        y=df["custo_medio"],
        name="Custo médio (R$)",
        yaxis="y2",
        mode="lines+markers",
    )
    fig.update_layout(
        template=TEMPLATE,
        title=f"Volume e custo por janela de {dias} dias",
        xaxis_title=f"Janela de {dias} dias",
        xaxis_type="category",
        yaxis_title="Cotações",
        yaxis2=dict(title="Custo médio (R$)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def funil_cobertura(df: pd.DataFrame) -> go.Figure:
    """Quantas consultas têm escolha de verdade — onde não há, não há mercado."""
    cores = ["#dc5a5a", "#f3a712", "#6ba8c9", "#00b978"]
    fig = px.bar(
        df,
        x="faixa",
        y="consultas",
        color="faixa",
        color_discrete_sequence=cores,
        text=df["participacao"].map(lambda p: f"{p:.0%}"),
        labels={"faixa": "Opções na consulta", "consultas": "Consultas"},
        title="Funil de cobertura: quantas consultas têm escolha",
        template=TEMPLATE,
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False)
    return fig


def pressao_estados(df: pd.DataFrame, top: int = 12) -> go.Figure:
    """Ranking de onde agir: volume alto, caro, lento e com pouca concorrência."""
    dados = df.nlargest(top, "pressao").sort_values("pressao")
    fig = px.bar(
        dados,
        x="pressao",
        y="uf",
        orientation="h",
        color="pressao",
        # Escala escura -> clara: no fundo escuro, quanto mais brilhante, pior.
        color_continuous_scale=["#5b2419", "#f3a712"],
        custom_data=["cotacoes", "custo_mediano", "prazo_medio", "transportadoras"],
        labels={"pressao": "Índice de pressão (0-100)", "uf": "UF"},
        title="Onde agir primeiro · pressão logística por estado",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>Pressão: %{x:.0f}/100<br>Consultas: %{customdata[0]:,}"
        "<br>Custo mediano: R$ %{customdata[1]:.2f}"
        "<br>Prazo médio: %{customdata[2]:.1f} dias"
        "<br>Transportadoras: %{customdata[3]}<extra></extra>"
    )
    fig.update_layout(coloraxis_showscale=False)
    return fig


def premio_por_dia(df: pd.DataFrame) -> go.Figure:
    """Quanto custa comprar um dia a menos de prazo, por estado."""
    fig = px.bar(
        df,
        x="premio_mediano",
        y="uf",
        orientation="h",
        color="premio_mediano",
        color_continuous_scale="Teal",
        custom_data=["consultas"],
        labels={"premio_mediano": "R$ por dia economizado", "uf": "UF"},
        title="O preço da pressa: custo mediano de economizar um dia",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>R$ %{x:.2f} por dia"
        "<br>Consultas com escolha: %{customdata[0]}<extra></extra>"
    )
    fig.update_layout(coloraxis_showscale=False)
    return fig


def canais_por_cliente(df: pd.DataFrame) -> go.Figure:
    """Mix de canais de cada loja, em participação — o volume absoluto esconde
    as lojas menores."""
    ordem = (
        df.groupby("loja")["cotacoes"].sum().sort_values(ascending=True).index.tolist()
    )
    fig = px.bar(
        df,
        x="participacao",
        y="loja",
        color="canal",
        orientation="h",
        category_orders={"loja": ordem},
        custom_data=["cotacoes", "canal"],
        labels={"participacao": "Participação", "loja": "Loja", "canal": "Canal"},
        title="Uso de cada canal por cliente",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>%{customdata[1]}: %{x:.1%}"
        "<br>Consultas: %{customdata[0]:,}<extra></extra>"
    )
    fig.update_layout(
        xaxis_tickformat=".0%",
        legend=dict(orientation="h", yanchor="top", y=-0.18),
    )
    return fig


def desvio_estados(df: pd.DataFrame) -> go.Figure:
    """Distância entre a oferta mais cara e a mais barata da mesma consulta."""
    fig = px.bar(
        df,
        x="desvio_mediano",
        y="uf",
        orientation="h",
        color="desvio_mediano",
        color_continuous_scale=["#123b32", "#00b978"],
        custom_data=["desvio_pct_mediano", "consultas"],
        labels={"desvio_mediano": "Desvio mediano (R$)", "uf": "UF"},
        title="Dispersão de preço dentro da mesma cotação",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>Desvio: R$ %{x:.2f}"
        "<br>Equivale a %{customdata[0]:.0%} do preço mais barato"
        "<br>Consultas: %{customdata[1]}<extra></extra>"
    )
    fig.update_layout(coloraxis_showscale=False)
    return fig


def velocidade_transportadoras(df: pd.DataFrame) -> go.Figure:
    """Prazo prometido, separando manuseio de transporte."""
    rotulos = df["transportadora"]
    fig = go.Figure()
    fig.add_bar(x=df["manuseio"], y=rotulos, orientation="h", name="Manuseio (dias)")
    fig.add_bar(x=df["transporte"], y=rotulos, orientation="h", name="Transporte (dias)")
    fig.update_layout(
        template=TEMPLATE,
        barmode="stack",
        title="Velocidade prometida pelas transportadoras mais rápidas",
        xaxis_title="Dias até a entrega",
        yaxis_title="Transportadora",
        legend=dict(orientation="h", yanchor="top", y=-0.18),
    )
    return fig


def cotacoes_estados(df: pd.DataFrame, top: int = 15) -> go.Figure:
    """Volume de consultas por UF de destino."""
    dados = df.nlargest(top, "cotacoes").sort_values("cotacoes")
    fig = px.bar(
        dados,
        x="cotacoes",
        y="uf",
        orientation="h",
        color="canal_dominante",
        labels={
            "cotacoes": "Consultas",
            "uf": "UF",
            "canal_dominante": "Canal dominante",
        },
        title="Consultas por estado de destino",
        template=TEMPLATE,
    )
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.18))
    return fig


def sem_cobertura_estados(df: pd.DataFrame, top: int = 15) -> go.Figure:
    """Onde a consulta volta vazia: x_error_cotacao 3 e 4."""
    dados = df.nlargest(top, "participacao").sort_values("participacao")
    fig = px.bar(
        dados,
        x="participacao",
        y="uf",
        orientation="h",
        color="participacao",
        color_continuous_scale=["#5b2419", "#dc5a5a"],
        custom_data=["sem_cobertura", "consultas"],
        labels={"participacao": "Consultas sem cobertura", "uf": "UF"},
        title="Estados onde a cotação volta vazia",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>%{x:.1%} sem cobertura"
        "<br>%{customdata[0]:,} de %{customdata[1]:,} consultas<extra></extra>"
    )
    fig.update_layout(xaxis_tickformat=".0%", coloraxis_showscale=False)
    return fig


def preco_por_km(df: pd.DataFrame) -> go.Figure:
    """R$ por km aproximado de cada transportadora vencedora."""
    fig = px.bar(
        df,
        x="preco_km_mediano",
        y="transportadora",
        orientation="h",
        color="preco_km_mediano",
        color_continuous_scale="Teal",
        custom_data=["distancia_mediana", "consultas"],
        labels={"preco_km_mediano": "R$ por km", "transportadora": "Transportadora"},
        title="Preço por quilômetro (distância aproximada entre capitais)",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{y}<br>R$ %{x:.3f} por km"
        "<br>Distância mediana: %{customdata[0]:.0f} km"
        "<br>Consultas: %{customdata[1]}<extra></extra>"
    )
    fig.update_layout(coloraxis_showscale=False)
    return fig


def custo_por_faixa_peso(df: pd.DataFrame) -> go.Figure:
    """Custo médio por faixa de peso, com o volume de cotações no hover."""
    fig = px.bar(
        df,
        x="faixa",
        y="custo_medio",
        color="custo_medio",
        color_continuous_scale="Teal",
        custom_data=["cotacoes"],
        labels={"faixa": "Faixa de peso", "custo_medio": "Custo médio (R$)"},
        title="Custo médio por faixa de peso",
        template=TEMPLATE,
    )
    fig.update_traces(
        hovertemplate="%{x}<br>Custo médio: R$ %{y:.2f}"
        "<br>Cotações: %{customdata[0]:,}<extra></extra>"
    )
    fig.update_layout(xaxis_type="category", coloraxis_showscale=False)
    return fig


def volume_por_canal(df: pd.DataFrame) -> go.Figure:
    """Participação de cada canal de venda no volume de cotações."""
    fig = px.bar(
        df.sort_values("cotacoes"),
        x="cotacoes",
        y="canal",
        orientation="h",
        text="cotacoes",
        labels={"cotacoes": "Cotações", "canal": "Canal"},
        title="Volume de cotações por canal",
        template=TEMPLATE,
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    return fig
