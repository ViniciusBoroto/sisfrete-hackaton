"""Chatbot com acesso aos dados, via OpenRouter e tool use.

O modelo não escreve query de OpenSearch: ele escolhe entre as funções já
validadas de queries.py. Cada ferramenta devolve um resumo em texto (que volta
para o modelo) e figuras Plotly (que o app renderiza).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

import charts
import queries

load_dotenv()

MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731:free")
BASE_URL = "https://openrouter.ai/api/v1"
MAX_RODADAS = 6

SISTEMA = """Você é analista de dados de frete no hackathon da Unimar.
Responde em português, curto e direto, sempre com os números que as ferramentas
devolveram — nunca invente valores.

Contexto dos dados:
- Cotações da Sisfrete, 01/09 a 14/09/2026. Só existe esse período.
- Nomes de cidade vêm em CAIXA ALTA e sem acento (SAO PAULO, GOIANIA).
- Transportadora sai com nome (Jadlog, Correios) nas ferramentas de vencedoras.
- Loja/cliente também é por nome; use `lojas` para descobrir quais existem.
- nf.cotacoes é array achatado: a correlação transportadora x custo x prazo já
  é feita em Python pelas ferramentas. Não tente contornar isso.

Quando uma ferramenta gerar gráfico, comente o que ele mostra em uma frase.
"""


def _normalizar_cidade(nome: str | None) -> str | None:
    """A base grava cidade em caixa alta e sem acento."""
    if not nome:
        return None
    acentos = str.maketrans("ÁÀÂÃÉÊÍÓÔÕÚÜÇ", "AAAAEEIOOOUUC")
    return nome.upper().translate(acentos)


# --------------------------------------------------------------- ferramentas


def _cliente_id(nome: str | None) -> int | None:
    """Converte o nome da loja no ID interno, que é o que a query usa."""
    if not nome:
        return None
    lojas = queries.clientes(top=60)
    achado = lojas[lojas["nome"].str.lower() == nome.strip().lower()]
    if achado.empty:
        achado = lojas[lojas["nome"].str.lower().str.contains(nome.strip().lower())]
    return int(achado.iloc[0]["cliente"]) if not achado.empty else None


def _comparar_transportadoras(
    cidade: str | None = None, canal: str | None = None, loja: str | None = None
) -> dict:
    consulta = queries.filtro(
        cidade=_normalizar_cidade(cidade), canal=canal, cliente=_cliente_id(loja)
    )
    resumo = queries.transportadoras_vencedoras(consulta)
    if resumo.empty:
        return {"texto": "Sem cotações para esse filtro.", "figuras": []}
    destino = cidade or loja or "todos os destinos"
    colunas = ["transportadora", "cotacoes", "custo_mediano", "prazo_medio"]
    return {
        "texto": resumo[colunas].head(10).to_markdown(index=False),
        "figuras": [
            charts.custo_x_prazo(resumo, f"Custo x prazo · {destino}"),
            charts.comparativo_transportadoras(resumo),
        ],
    }


def _cobertura(
    cidade: str | None = None, canal: str | None = None, loja: str | None = None
) -> dict:
    amostra = queries.amostra(
        cidade=_normalizar_cidade(cidade),
        canal=canal,
        cliente=_cliente_id(loja),
        max_docs=2_000,
    )
    cobertura = queries.cobertura(amostra)
    if cobertura.empty:
        return {"texto": "Sem consultas para esse filtro.", "figuras": []}
    return {
        "texto": cobertura.to_markdown(index=False),
        "figuras": [charts.funil_cobertura(cobertura)],
    }


def _pressao_estados(canal: str | None = None, loja: str | None = None) -> dict:
    df = queries.pressao_por_estado(
        queries.filtro(canal=canal, cliente=_cliente_id(loja))
    )
    if df.empty:
        return {"texto": "Sem dados para esse filtro.", "figuras": []}
    return {
        "texto": df.head(10).to_markdown(index=False),
        "figuras": [charts.pressao_estados(df)],
    }


def _preco_da_pressa(
    cidade: str | None = None, canal: str | None = None, loja: str | None = None
) -> dict:
    amostra = queries.amostra(
        cidade=_normalizar_cidade(cidade),
        canal=canal,
        cliente=_cliente_id(loja),
        max_docs=2_000,
    )
    premios = queries.premio_por_dia(amostra)
    if premios.empty:
        return {"texto": "Amostra sem par barato/rápido para medir.", "figuras": []}
    mediana = amostra["premio_por_dia"].median()
    return {
        "texto": f"Prêmio mediano geral: R$ {mediana:.2f} por dia economizado.\n\n"
        + premios.to_markdown(index=False),
        "figuras": [charts.premio_por_dia(premios)],
    }


def _lojas(top: int = 20) -> dict:
    df = queries.clientes(top=top)
    return {"texto": df[["nome", "cotacoes"]].to_markdown(index=False), "figuras": []}


def _custo_por_peso(
    cidade: str | None = None, canal: str | None = None, loja: str | None = None
) -> dict:
    df = queries.custo_por_faixa_peso(
        queries.filtro(
            cidade=_normalizar_cidade(cidade), canal=canal, cliente=_cliente_id(loja)
        )
    )
    if df.empty:
        return {"texto": "Sem cotações para esse filtro.", "figuras": []}
    return {
        "texto": df[["faixa", "cotacoes", "custo_medio"]].to_markdown(index=False),
        "figuras": [charts.custo_por_faixa_peso(df)],
    }


def _volume_por_canal() -> dict:
    df = queries.canais()
    return {
        "texto": df.to_markdown(index=False),
        "figuras": [charts.volume_por_canal(df)],
    }


def _cidades(top: int = 20) -> dict:
    df = queries.cidades(top=top)
    return {"texto": df.to_markdown(index=False), "figuras": []}


FERRAMENTAS: dict[str, Callable[..., dict]] = {
    "comparar_transportadoras": _comparar_transportadoras,
    "custo_por_peso": _custo_por_peso,
    "volume_por_canal": _volume_por_canal,
    "cidades_com_mais_cotacoes": _cidades,
    "cobertura": _cobertura,
    "pressao_por_estado": _pressao_estados,
    "preco_da_pressa": _preco_da_pressa,
    "lojas": _lojas,
}

ESPECIFICACAO = [
    {
        "type": "function",
        "function": {
            "name": "comparar_transportadoras",
            "description": (
                "Transportadoras que ganham as cotações, por NOME, com custo "
                "mediano, prazo médio e volume, mais gráficos de custo x prazo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string", "description": "Cidade de destino"},
                    "canal": {
                        "type": "string",
                        "description": "Canal de venda, ex.: Mercado Livre",
                    },
                    "loja": {
                        "type": "string",
                        "description": "Nome do cliente/loja, ex.: Pneuweb",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "custo_por_peso",
            "description": "Custo médio por faixa de peso de 10 kg, com gráfico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string"},
                    "canal": {"type": "string"},
                    "loja": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_por_canal",
            "description": "Volume e custo médio por canal de venda, com gráfico.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cidades_com_mais_cotacoes",
            "description": "Cidades de destino com mais cotações no período.",
            "parameters": {
                "type": "object",
                "properties": {"top": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cobertura",
            "description": (
                "Funil de cobertura: quantas consultas tiveram 0, 1, 2 ou 3+ "
                "opções de frete. Mostra deserto logístico e monopólio."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string"},
                    "canal": {"type": "string"},
                    "loja": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pressao_por_estado",
            "description": (
                "Ranking de estados por pressão logística: volume, custo "
                "mediano, prazo e número de transportadoras. Responde 'onde "
                "agir primeiro'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "canal": {"type": "string"},
                    "loja": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preco_da_pressa",
            "description": (
                "Quanto custa economizar um dia de prazo: diferença entre a "
                "opção mais rápida e a mais barata, por estado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string"},
                    "canal": {"type": "string"},
                    "loja": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lojas",
            "description": "Clientes (lojas) com mais cotações, por nome.",
            "parameters": {
                "type": "object",
                "properties": {"top": {"type": "integer"}},
            },
        },
    },
]


class ChatIndisponivel(RuntimeError):
    """Falta chave de API."""


def cliente() -> OpenAI:
    chave = os.getenv("OPENROUTER_API_KEY")
    if not chave:
        raise ChatIndisponivel(
            "Defina OPENROUTER_API_KEY no .env para usar o chat."
        )
    return OpenAI(base_url=BASE_URL, api_key=chave)


def responder(historico: list[dict[str, Any]]) -> tuple[str, list]:
    """Roda o laço de tool use e devolve (resposta, figuras)."""
    api = cliente()
    mensagens = [{"role": "system", "content": SISTEMA}, *historico]
    figuras: list = []

    for _ in range(MAX_RODADAS):
        resposta = api.chat.completions.create(
            model=MODEL, messages=mensagens, tools=ESPECIFICACAO
        )
        msg = resposta.choices[0].message
        mensagens.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or "", figuras

        for chamada in msg.tool_calls:
            funcao = FERRAMENTAS.get(chamada.function.name)
            try:
                argumentos = json.loads(chamada.function.arguments or "{}")
                resultado = funcao(**argumentos) if funcao else {
                    "texto": "Ferramenta desconhecida.",
                    "figuras": [],
                }
            except Exception as exc:  # devolve o erro ao modelo, não quebra o app
                resultado = {"texto": f"Erro na ferramenta: {exc}", "figuras": []}
            figuras.extend(resultado["figuras"])
            mensagens.append(
                {
                    "role": "tool",
                    "tool_call_id": chamada.id,
                    "content": resultado["texto"],
                }
            )

    return "Não consegui fechar a análise em poucas rodadas.", figuras
