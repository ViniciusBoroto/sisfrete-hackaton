"""Consultas ao OpenSearch e preparação dos resultados em DataFrames.

Regra do desafio: apenas setembro/2026, e todo eixo de tempo agregado em
janelas fixas de 7 ou 15 dias.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from api import INDEX, TIME_ZONE, get_client

# A carga vai de 01/09 a 14/09 — duas janelas fechadas de 7 dias.
INICIO = "2026-09-01"
FIM = "2026-09-15"

# Campos mínimos para correlacionar transportadora x custo x prazo.
CAMPOS = [
    "@timestamp",
    "nf.cliente",
    "nf.canal_web",
    "nf.nome_cidade",
    "nf.estado",
    "nf.peso",
    "nf.cubagem",
    "nf.cotacoes",
]


def periodo(inicio: str = INICIO, fim: str = FIM) -> dict:
    """Range fechado de datas — congela os números para a apresentação."""
    return {
        "range": {"@timestamp": {"gte": inicio, "lt": fim, "time_zone": TIME_ZONE}}
    }


def filtro(
    cidade: str | None = None,
    estado: str | None = None,
    canal: str | None = None,
    inicio: str = INICIO,
    fim: str = FIM,
) -> dict:
    """Monta a query booleana usada por todas as análises."""
    must: list[dict] = [periodo(inicio, fim)]
    if cidade:
        must.append({"term": {"nf.nome_cidade": cidade}})
    if estado:
        must.append({"term": {"nf.estado": estado}})
    if canal:
        must.append({"term": {"nf.canal_web": canal}})
    return {"bool": {"filter": must}}


# ------------------------------------------------------------ agregações


def canais(query: dict | None = None) -> pd.DataFrame:
    """Volume e custo médio por canal de venda."""
    aggs = {
        "canais": {
            "terms": {"field": "nf.canal_web", "size": 10},
            "aggs": {"custo_medio": {"avg": {"field": "nf.cotacoes.total"}}},
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["canais"]["buckets"]
    return pd.DataFrame(
        {
            "canal": b["key"],
            "cotacoes": b["doc_count"],
            "custo_medio": b["custo_medio"]["value"],
        }
        for b in buckets
    )


def cidades(query: dict | None = None, top: int = 50) -> pd.DataFrame:
    """Cidades de destino com mais cotações — alimenta o filtro do app."""
    aggs = {"cidades": {"terms": {"field": "nf.nome_cidade", "size": top}}}
    buckets = get_client().aggregate(aggs, query or periodo())["cidades"]["buckets"]
    return pd.DataFrame(
        {"cidade": b["key"], "cotacoes": b["doc_count"]} for b in buckets
    )


def _offset_janela(dias: int, inicio: str) -> str:
    """Alinha as janelas fixas ao início do período.

    O date_histogram ancora os buckets na época Unix; sem offset a primeira
    janela de setembro começaria em agosto.
    """
    desde_epoca = (dt.date.fromisoformat(inicio) - dt.date(1970, 1, 1)).days
    return f"+{desde_epoca % dias}d"


def volume_por_janela(
    query: dict | None = None,
    dias: int = 7,
    campo: str = "nf.cotacoes.total",
    inicio: str = INICIO,
) -> pd.DataFrame:
    """Série temporal agregada em janelas fixas de 7 ou 15 dias."""
    if dias not in (7, 15):
        raise ValueError("A janela deve ser de 7 ou 15 dias.")
    aggs = {
        "janelas": {
            "date_histogram": {
                "field": "@timestamp",
                "fixed_interval": f"{dias}d",
                "offset": _offset_janela(dias, inicio),
                "time_zone": TIME_ZONE,
                "min_doc_count": 1,
            },
            "aggs": {"custo_medio": {"avg": {"field": campo}}},
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["janelas"]["buckets"]
    df = pd.DataFrame(
        {
            "janela": pd.to_datetime(b["key_as_string"]),
            "cotacoes": b["doc_count"],
            "custo_medio": b["custo_medio"]["value"],
        }
        for b in buckets
    )
    return df


def canais_por_janela(
    query: dict | None = None, dias: int = 7, top: int = 8, inicio: str = INICIO
) -> pd.DataFrame:
    """Volume e custo de cada canal em cada janela.

    Com 14 dias de carga o eixo de tempo rende só duas janelas; cruzar com o
    canal transforma duas barras numa comparação de verdade.
    """
    if dias not in (7, 15):
        raise ValueError("A janela deve ser de 7 ou 15 dias.")
    aggs = {
        "canais": {
            "terms": {"field": "nf.canal_web", "size": top},
            "aggs": {
                "janelas": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": f"{dias}d",
                        "offset": _offset_janela(dias, inicio),
                        "time_zone": TIME_ZONE,
                        "min_doc_count": 1,
                    },
                    "aggs": {"custo_medio": {"avg": {"field": "nf.cotacoes.total"}}},
                }
            },
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["canais"]["buckets"]
    linhas = [
        {
            "canal": canal["key"],
            "janela": pd.to_datetime(j["key_as_string"]),
            "cotacoes": j["doc_count"],
            "custo_medio": j["custo_medio"]["value"],
        }
        for canal in buckets
        for j in canal["janelas"]["buckets"]
    ]
    return pd.DataFrame(linhas)


def custo_por_faixa_peso(
    query: dict | None = None, intervalo: int = 10, peso_max: int = 200
) -> pd.DataFrame:
    """Custo médio por faixa de peso — onde o frete dispara.

    Sem eixo de tempo: com 14 dias de carga qualquer série temporal caberia
    em duas janelas.
    """
    aggs = {
        "faixas": {
            "histogram": {
                "field": "nf.peso",
                "interval": intervalo,
                "min_doc_count": 1,
                "extended_bounds": {"min": 0, "max": peso_max},
            },
            "aggs": {"custo_medio": {"avg": {"field": "nf.cotacoes.total"}}},
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["faixas"]["buckets"]
    df = pd.DataFrame(
        {
            "inicio": b["key"],
            "cotacoes": b["doc_count"],
            "custo_medio": b["custo_medio"]["value"],
        }
        for b in buckets
        if b["key"] <= peso_max
    )
    if df.empty:
        return df
    df["faixa"] = (
        df["inicio"].astype(int).astype(str)
        + "–"
        + (df["inicio"] + intervalo).astype(int).astype(str)
        + " kg"
    )
    return df


# ----------------------------------------------- correlação transportadora

def cotacoes_detalhadas(
    cidade: str | None = None,
    estado: str | None = None,
    canal: str | None = None,
    max_docs: int = 5_000,
) -> pd.DataFrame:
    """Uma linha por (documento, transportadora).

    nf.cotacoes é array de objeto, não nested: o motor achata os campos e uma
    agregação pode casar a transportadora de uma cotação com o total de outra.
    Por isso puxamos os documentos e cruzamos aqui, em Python.
    """
    # Páginas grandes: cada round-trip em quotations-* custa segundos.
    docs = get_client().scan(
        query=filtro(cidade, estado, canal),
        source=CAMPOS,
        page_size=min(2_000, max_docs),
        max_docs=max_docs,
    )

    linhas = []
    for doc in docs:
        nf = doc.get("nf", {}) or {}
        for cot in nf.get("cotacoes") or []:
            linhas.append(
                {
                    "timestamp": doc.get("@timestamp"),
                    "cliente": nf.get("cliente"),
                    "canal": nf.get("canal_web"),
                    "cidade": nf.get("nome_cidade"),
                    "estado": nf.get("estado"),
                    "peso": nf.get("peso"),
                    "cubagem": nf.get("cubagem"),
                    "transportadora": cot.get("transportadora"),
                    "frete": cot.get("frete"),
                    "total": cot.get("total"),
                    "p_min": cot.get("p_min"),
                    "p_max": cot.get("p_max"),
                }
            )

    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["prazo"] = df[["p_min", "p_max"]].mean(axis=1)
    # 99999 é sentinela de "sem cobertura" e zerados são cotação inválida:
    # três linhas dessas esticam o eixo do gráfico em 100x.
    return df[(df["total"] > 0) & (df["total"] < 99_999)]


def resumo_transportadoras(
    df: pd.DataFrame, min_cotacoes: int = 5
) -> pd.DataFrame:
    """Custo médio, prazo médio e volume por transportadora.

    Transportadoras com pouquíssimas cotações viram outlier visual sem
    significar nada; `min_cotacoes` corta esse ruído.
    """
    if df.empty:
        return df
    resumo = (
        df.groupby("transportadora")
        .agg(
            custo_medio=("total", "mean"),
            custo_mediano=("total", "median"),
            prazo_medio=("prazo", "mean"),
            cotacoes=("total", "size"),
        )
        .reset_index()
        .sort_values("custo_medio")
    )
    return resumo[resumo["cotacoes"] >= min_cotacoes]
