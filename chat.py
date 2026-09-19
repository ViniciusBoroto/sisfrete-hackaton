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
- Transportadoras são IDs numéricos, não têm nome.
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


def _comparar_transportadoras(
    cidade: str | None = None, canal: str | None = None, max_docs: int = 2_000
) -> dict:
    detalhe = queries.cotacoes_detalhadas(
        cidade=_normalizar_cidade(cidade), canal=canal, max_docs=max_docs
    )
    resumo = queries.resumo_transportadoras(detalhe)
    if resumo.empty:
        return {"texto": "Sem cotações para esse filtro.", "figuras": []}
    destino = cidade or "todos os destinos"
    return {
        "texto": resumo.head(10).to_markdown(index=False),
        "figuras": [
            charts.custo_x_prazo(resumo, f"Custo x prazo · {destino}"),
            charts.comparativo_transportadoras(resumo),
        ],
    }


def _custo_por_peso(cidade: str | None = None, canal: str | None = None) -> dict:
    df = queries.custo_por_faixa_peso(
        queries.filtro(cidade=_normalizar_cidade(cidade), canal=canal)
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
}

ESPECIFICACAO = [
    {
        "type": "function",
        "function": {
            "name": "comparar_transportadoras",
            "description": (
                "Custo médio, custo mediano, prazo médio e volume por "
                "transportadora, com gráficos de custo x prazo. Baixa documentos "
                "e correlaciona em Python — é a chamada mais lenta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string", "description": "Cidade de destino"},
                    "canal": {
                        "type": "string",
                        "description": "Canal de venda, ex.: Mercado Livre",
                    },
                    "max_docs": {
                        "type": "integer",
                        "description": "Documentos a baixar (1000 a 20000)",
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
