"""Camada fina de comunicação HTTP com a API OpenSearch da Sisfrete.

Único lugar do projeto que fala HTTP. Cuida de autenticação, timeouts,
retentativas e tradução de erros; não interpreta dados de negócio.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

BASE_URL = os.getenv("SISFRETE_BASE_URL", "https://api.opensearch.sisfrete.com.br")
USER = os.getenv("SISFRETE_USER")
PASSWORD = os.getenv("SISFRETE_PASSWORD")
TIMEOUT = float(os.getenv("SISFRETE_TIMEOUT", "120"))

# Setembro é o único mês com carga completa; agosto é artefato de migração.
INDEX = "quotations-*-2026.09"
# @timestamp vem em UTC; Brasília é UTC-3.
TIME_ZONE = "-03:00"

_MENSAGENS = {
    400: "Consulta malformada. Confira o campo 'reason' da resposta.",
    401: "Usuário ou senha incorretos.",
    403: "Operação não permitida para a credencial do grupo.",
    404: "Índice não existe. Confira o nome em _cat/indices/quotations-*.",
    429: "Cluster sob carga. Reduza a concorrência e tente de novo.",
}


class SisfreteError(RuntimeError):
    """Falha ao conversar com a API."""

    def __init__(self, mensagem: str, status: int | None = None, payload: Any = None):
        self.status = status
        self.payload = payload
        super().__init__(mensagem if status is None else f"[{status}] {mensagem}")


class SisfreteClient:
    """Cliente somente-leitura do cluster OpenSearch da Sisfrete."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        user: str | None = USER,
        password: str | None = PASSWORD,
        timeout: float = TIMEOUT,
    ):
        if not user or not password:
            raise SisfreteError(
                "Credenciais ausentes: copie .env.example para .env e preencha "
                "SISFRETE_USER e SISFRETE_PASSWORD."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.headers.update({"Content-Type": "application/json"})
        # Concorrência baixa (2-3 req simultâneas por grupo) é regra do evento.
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=3)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # ------------------------------------------------------------------ core

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise SisfreteError(
                "Timeout: consulta ampla demais. Restrinja por mês ou cliente "
                "e use size=0."
            ) from exc
        except requests.RequestException as exc:
            raise SisfreteError(f"Falha de rede: {exc}") from exc

        if resp.status_code >= 400:
            try:
                payload = resp.json()
                reason = payload.get("error", {}).get("reason", "")
            except ValueError:
                payload, reason = resp.text, resp.text[:300]
            base = _MENSAGENS.get(resp.status_code, "Erro na API.")
            raise SisfreteError(
                f"{base} {reason}".strip(), status=resp.status_code, payload=payload
            )

        return resp.json()

    # --------------------------------------------------------------- leituras

    def ping(self) -> dict:
        """Testa a conexão e devolve a versão do cluster."""
        return self._request("GET", "/")

    def indices(self, pattern: str = "quotations-*") -> list[dict]:
        """Lista os índices visíveis para a credencial."""
        return self._request("GET", f"/_cat/indices/{pattern}?format=json")

    def mapping(self, index: str = INDEX) -> dict:
        return self._request("GET", f"/{index}/_mapping")

    def count(self, query: dict | None = None, index: str = INDEX) -> int:
        body = {"query": query} if query else {}
        return self._request("POST", f"/{index}/_count", json=body)["count"]

    def search(self, body: dict, index: str = INDEX) -> dict:
        """Executa um _search cru e devolve a resposta completa."""
        return self._request("POST", f"/{index}/_search", json=body)

    def aggregate(
        self, aggs: dict, query: dict | None = None, index: str = INDEX
    ) -> dict:
        """Agrega no servidor (size=0) e devolve só o bloco de agregações."""
        body: dict[str, Any] = {"size": 0, "aggs": aggs}
        if query:
            body["query"] = query
        return self.search(body, index=index).get("aggregations", {})

    def msearch(self, requests_: list[tuple[str, dict]]) -> list[dict]:
        """Várias buscas numa requisição. Cada item é (índice, corpo)."""
        import json

        linhas = []
        for index, body in requests_:
            linhas.append(json.dumps({"index": index}))
            linhas.append(json.dumps(body))
        payload = "\n".join(linhas) + "\n"
        resp = self._request(
            "POST",
            "/_msearch",
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
        )
        return resp["responses"]

    def scan(
        self,
        query: dict | None = None,
        index: str = INDEX,
        source: list[str] | None = None,
        page_size: int = 1000,
        max_docs: int = 50_000,
    ) -> Iterator[dict]:
        """Pagina documentos com search_after (from/size trava em 10.000).

        `max_docs` existe de propósito: varredura contínua sobre quotations-*
        é proibida pelas regras de uso.
        """
        body: dict[str, Any] = {
            "size": page_size,
            "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
        }
        if query:
            body["query"] = query
        if source:
            body["_source"] = source

        trazidos = 0
        while trazidos < max_docs:
            body["size"] = min(page_size, max_docs - trazidos)
            hits = self.search(body, index=index)["hits"]["hits"]
            if not hits:
                return
            for hit in hits:
                yield hit["_source"]
            trazidos += len(hits)
            body["search_after"] = hits[-1]["sort"]


_client: SisfreteClient | None = None


def get_client() -> SisfreteClient:
    """Cliente único do processo — reaproveita a conexão HTTP."""
    global _client
    if _client is None:
        _client = SisfreteClient()
    return _client
