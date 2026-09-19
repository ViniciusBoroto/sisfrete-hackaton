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
    resumo = resumo.nlargest(top, "cotacoes").sort_values("custo_medio")
    fig = go.Figure()
    rotulos = resumo["transportadora"].astype(str)
    fig.add_bar(x=rotulos, y=resumo["custo_medio"], name="Custo médio (R$)")
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
        yaxis_title="Custo médio (R$)",
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
