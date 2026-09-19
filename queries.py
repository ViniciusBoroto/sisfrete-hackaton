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

# A loja aparece com nome só aqui; nf.cliente é ID e não diz nada a ninguém.
LOJA = "nf.token_nome"

# Vencedoras de cada consulta: trazem o NOME da transportadora, além de preço
# e prazo, em objetos de um elemento — agregar direto é seguro.
BARATA = "nf.menor_preco"
RAPIDA = "nf.menor_prazo"

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
    cliente: int | None = None,
    inicio: str = INICIO,
    fim: str = FIM,
) -> dict:
    """Monta a query booleana usada por todas as análises."""
    must: list[dict] = [periodo(inicio, fim)]
    if cidade:
        must.append({"term": {"nf.nome_cidade": cidade}})
    if estado:
        must.append({"term": {"nf.uf": estado}})
    if canal:
        must.append({"term": {"nf.canal_web": canal}})
    if cliente:
        must.append({"term": {"nf.cliente": cliente}})
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


# Tokens que são nome de marketplace, não da loja.
GENERICOS = {
    "shopee",
    "mercado livre",
    "magalu",
    "magazine luiza",
    "magazine",
    "api sisfrete",
    "ws sisfrete",
    "via varejo",
    "carrefour",
    "tray corp",
    "leroy merlin",
    "madeira madeira",
}
PREFIXOS = ("p-ml-", "p-sh-", "ml - ", "mercado livre - ", "shopee - ", "magalu - ")
SUFIXOS = (" - shopee", " - mercado livre", " - magalu", " - magazine luiza")


def _nome_cliente(tokens: list[str]) -> str:
    """Extrai um nome legível dos tokens de integração do cliente.

    Não existe campo com a razão social: o que há é nf.token_nome, no formato
    "Mercado Livre - PNEUWEB" ou "P-ML-FORMIGAO". Tiramos o prefixo do
    marketplace e ficamos com o que identifica a loja.
    """
    for token in tokens:
        limpo = (token or "").strip()
        if not limpo or limpo.replace(".", "").replace("/", "").replace("-", "").isdigit():
            continue
        minusculo = limpo.lower()
        for prefixo in PREFIXOS:
            if minusculo.startswith(prefixo):
                limpo = limpo[len(prefixo) :]
                minusculo = limpo.lower()
                break
        for sufixo in SUFIXOS:
            if minusculo.endswith(sufixo):
                limpo = limpo[: -len(sufixo)]
                minusculo = limpo.lower()
                break
        if minusculo in GENERICOS or not limpo:
            continue
        return limpo.title()
    return ""


def clientes(query: dict | None = None, top: int = 40) -> pd.DataFrame:
    """Clientes (lojas) com mais cotações, já com nome no lugar do ID."""
    aggs = {
        "clientes": {
            "terms": {"field": "nf.cliente", "size": top},
            "aggs": {"tokens": {"terms": {"field": LOJA, "size": 10}}},
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["clientes"]["buckets"]
    linhas = []
    sem_nome = 0
    for b in buckets:
        tokens = [t["key"] for t in b["tokens"]["buckets"]]
        nome = _nome_cliente(tokens)
        if not nome:
            # Alguns clientes só têm o token do marketplace: a base não guarda
            # a razão social. Numeramos em vez de expor o ID.
            sem_nome += 1
            nome = f"Loja sem nome {sem_nome}"
        linhas.append(
            {"cliente": b["key"], "nome": nome, "cotacoes": b["doc_count"]}
        )
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    # Dois clientes podem cair no mesmo nome: numera em vez de mostrar o ID.
    duplicados = df["nome"].duplicated(keep=False)
    if duplicados.any():
        ordem = df[duplicados].groupby("nome").cumcount() + 1
        df.loc[duplicados, "nome"] = (
            df.loc[duplicados, "nome"] + " " + ordem.astype(str)
        )
    return df


def transportadoras_vencedoras(
    query: dict | None = None, top: int = 15, criterio: str = "preco"
) -> pd.DataFrame:
    """Transportadoras que ganham a cotação, com nome, custo e prazo.

    Agrega nf.menor_preco / nf.menor_prazo, que têm um elemento por consulta —
    ao contrário de nf.cotacoes, aqui não há risco de misturar transportadora
    de uma oferta com o preço de outra.
    """
    raiz = BARATA if criterio == "preco" else RAPIDA
    aggs = {
        "transportadoras": {
            "terms": {"field": f"{raiz}.shipping_company", "size": top},
            "aggs": {
                "custo": {
                    "percentiles": {"field": f"{raiz}.preco", "percents": [25, 50, 75]}
                },
                "custo_medio": {"avg": {"field": f"{raiz}.preco"}},
                "prazo_medio": {"avg": {"field": f"{raiz}.shipping_time"}},
            },
        }
    }
    aggs["transportadoras"]["terms"]["size"] = top * 3
    buckets = get_client().aggregate(aggs, query or periodo())["transportadoras"][
        "buckets"
    ]
    df = pd.DataFrame(
        {
            "transportadora": b["key"].title(),
            "cotacoes": b["doc_count"],
            "custo_mediano": b["custo"]["values"]["50.0"],
            "custo_p25": b["custo"]["values"]["25.0"],
            "custo_p75": b["custo"]["values"]["75.0"],
            "custo_medio": b["custo_medio"]["value"],
            "prazo_medio": b["prazo_medio"]["value"],
        }
        for b in buckets
    )
    if df.empty:
        return df
    # A base grava o mesmo nome em caixas diferentes ("JADLOG" e "Jadlog"):
    # junta os dois e pondera as medianas pelo volume de cada um.
    return (
        df.assign(
            peso_custo=df["custo_mediano"] * df["cotacoes"],
            peso_prazo=df["prazo_medio"] * df["cotacoes"],
        )
        .groupby("transportadora", as_index=False)
        .agg(
            cotacoes=("cotacoes", "sum"),
            peso_custo=("peso_custo", "sum"),
            peso_prazo=("peso_prazo", "sum"),
            custo_p25=("custo_p25", "min"),
            custo_p75=("custo_p75", "max"),
            custo_medio=("custo_medio", "mean"),
        )
        .assign(
            custo_mediano=lambda d: d["peso_custo"] / d["cotacoes"],
            prazo_medio=lambda d: d["peso_prazo"] / d["cotacoes"],
        )
        .drop(columns=["peso_custo", "peso_prazo"])
        .nlargest(top, "cotacoes")
        .sort_values("custo_mediano")
    )


def pressao_por_estado(query: dict | None = None, top: int = 27) -> pd.DataFrame:
    """Volume, custo, prazo e concorrência por UF, com índice de pressão.

    pressao = volume x custo x prazo x (falta de concorrência), tudo
    normalizado de 0 a 1 — é o ranking de "onde agir primeiro".
    """
    aggs = {
        "ufs": {
            "terms": {"field": "nf.uf", "size": top},
            "aggs": {
                "custo": {"percentiles": {"field": f"{BARATA}.preco", "percents": [50]}},
                "prazo_medio": {"avg": {"field": f"{BARATA}.shipping_time"}},
                "transportadoras": {
                    "cardinality": {"field": f"{BARATA}.shipping_company"}
                },
            },
        }
    }
    buckets = get_client().aggregate(aggs, query or periodo())["ufs"]["buckets"]
    df = pd.DataFrame(
        {
            "uf": b["key"],
            "cotacoes": b["doc_count"],
            "custo_mediano": b["custo"]["values"]["50.0"],
            "prazo_medio": b["prazo_medio"]["value"],
            "transportadoras": b["transportadoras"]["value"],
        }
        for b in buckets
    )
    if df.empty:
        return df

    def normalizar(serie: pd.Series) -> pd.Series:
        faixa = serie.max() - serie.min()
        return (serie - serie.min()) / faixa if faixa else serie * 0 + 0.5

    bruto = (
        normalizar(df["cotacoes"])
        * normalizar(df["custo_mediano"])
        * normalizar(df["prazo_medio"])
        * (1 - normalizar(df["transportadoras"]))
    )
    # O produto de quatro frações vira um número minúsculo; reescala para 0-100
    # onde 100 é o estado sob maior pressão.
    df["pressao"] = bruto / bruto.max() * 100 if bruto.max() else bruto
    return df.sort_values("pressao", ascending=False)


# --------------------------------------------------- amostra por consulta

AMOSTRA = [
    "nf.uf",
    "nf.nome_cidade",
    "nf.canal_web",
    "nf.peso",
    "nf.cotacoes.total",
    f"{BARATA}.preco",
    f"{BARATA}.shipping_time",
    f"{BARATA}.shipping_company",
    f"{RAPIDA}.preco",
    f"{RAPIDA}.shipping_time",
    f"{RAPIDA}.shipping_company",
]


def _primeiro(valor) -> dict:
    """menor_preco/menor_prazo vêm como lista de um elemento."""
    if isinstance(valor, list):
        return valor[0] if valor else {}
    return valor or {}


def amostra(
    cidade: str | None = None,
    estado: str | None = None,
    canal: str | None = None,
    cliente: int | None = None,
    max_docs: int = 3_000,
) -> pd.DataFrame:
    """Uma linha por consulta: quantas opções teve e quanto custa ter pressa."""
    docs = get_client().scan(
        query=filtro(cidade, estado, canal, cliente),
        source=AMOSTRA,
        page_size=min(2_000, max_docs),
        max_docs=max_docs,
    )
    linhas = []
    for doc in docs:
        nf = doc.get("nf", {}) or {}
        barata, rapida = _primeiro(nf.get("menor_preco")), _primeiro(nf.get("menor_prazo"))
        cotacoes = nf.get("cotacoes") or []
        linhas.append(
            {
                "uf": nf.get("uf"),
                "cidade": nf.get("nome_cidade"),
                "canal": nf.get("canal_web"),
                "peso": nf.get("peso"),
                "opcoes": len(cotacoes),
                "transportadora_barata": (barata.get("shipping_company") or "").title(),
                "preco_barato": barata.get("preco"),
                "prazo_barato": barata.get("shipping_time"),
                "preco_rapido": rapida.get("preco"),
                "prazo_rapido": rapida.get("shipping_time"),
            }
        )
    df = pd.DataFrame(linhas)
    if df.empty:
        return df

    dias = df["prazo_barato"] - df["prazo_rapido"]
    extra = df["preco_rapido"] - df["preco_barato"]
    # Só faz sentido quando a rápida é realmente mais rápida e mais cara.
    valido = (dias > 0) & (extra > 0)
    df["premio_por_dia"] = (extra / dias).where(valido)
    return df


def cobertura(df: pd.DataFrame) -> pd.DataFrame:
    """Quantas consultas tiveram 0, 1, 2 ou 3+ opções de frete."""
    if df.empty:
        return df
    faixas = pd.cut(
        df["opcoes"],
        bins=[-1, 0, 1, 2, float("inf")],
        labels=["sem opção", "1 opção", "2 opções", "3+ opções"],
    )
    total = len(df)
    resumo = (
        faixas.value_counts()
        .rename_axis("faixa")
        .reset_index(name="consultas")
        .sort_values("faixa")
    )
    resumo["participacao"] = resumo["consultas"] / total
    return resumo


def premio_por_dia(df: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Quanto custa, por UF, economizar um dia de prazo."""
    if df.empty or df["premio_por_dia"].isna().all():
        return pd.DataFrame()
    resumo = (
        df.dropna(subset=["premio_por_dia"])
        .groupby("uf")
        .agg(
            premio_mediano=("premio_por_dia", "median"),
            consultas=("premio_por_dia", "size"),
        )
        .reset_index()
        .nlargest(top, "consultas")
        .sort_values("premio_mediano")
    )
    return resumo


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
