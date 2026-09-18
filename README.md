# Frete Estratégico em Dados — Grupo 05

Dashboard de análise das cotações de frete da Sisfrete (Hackathon Unimar Tech Summit 2026).

## Estrutura

| Arquivo | Responsabilidade |
| --- | --- |
| `app.py` | Interface Streamlit: filtros, orquestração e exibição |
| `api.py` | Camada fina de HTTP: autenticação, retentativas, erros, paginação |
| `queries.py` | Consultas OpenSearch e preparação em DataFrames |
| `charts.py` | Gráficos Plotly |
| `chat.py` | Chatbot: tool use sobre as funções de `queries.py` (OpenRouter) |

Fluxo: `app.py` → `queries.py` → `api.py` → Sisfrete/OpenSearch → `queries.py` → `charts.py` → dashboard.

## Rodando

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (no Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env          # preencha as credenciais do grupo
streamlit run app.py
```

## Chatbot

A aba "Pergunte aos dados" usa um modelo via OpenRouter. Ele não escreve query
de OpenSearch: escolhe entre quatro ferramentas (`comparar_transportadoras`,
`custo_por_peso`, `volume_por_canal`, `cidades_com_mais_cotacoes`), que devolvem
números e os mesmos gráficos do dashboard.

Preencha no `.env`:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=anthropic/claude-sonnet-5
```

Sem a chave o dashboard funciona normalmente; só a aba de chat avisa que falta
configurar.

## Regras do desafio

- Apenas setembro/2026 (`quotations-*-2026.09`); agosto está incompleto.
- A carga real vai de 01/09 a 14/09 — como a janela obrigatória é de 7 ou 15
  dias, qualquer série temporal caberia em duas barras. Os gráficos cortam por
  peso, transportadora e canal; `queries.volume_por_janela` segue disponível.
- Mínimo de 3 gráficos que contem uma história conectada.

## Cuidados com a API

- `nf.cotacoes` é array de objeto, **não** nested: agregações misturam campos de
  cotações diferentes. Correlação transportadora × custo × prazo é feita em Python
  (`queries.cotacoes_detalhadas`).
- `@timestamp` é UTC; as agregações de data usam `time_zone: -03:00`.
- Prefira agregação no servidor (`size: 0`) a baixar documentos.
- Concorrência baixa (2–3 requisições) e nada de varredura contínua — o cluster
  atende produção real.
- `.env` nunca vai para o Git.
