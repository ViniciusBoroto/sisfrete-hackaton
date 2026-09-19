"""Distância aproximada entre estados, a partir do CEP de origem.

A base não traz quilometragem (nf.cotacoes.mkm é zero em todos os documentos).
O que existe é o CEP de origem (nf.request_item.origin) e a UF de destino
(nf.uf). Daqui sai uma distância aproximada: capital da UF de origem até a
capital da UF de destino. Serve para comparar transportadoras entre si, não
para medir rota real.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

# Faixas de CEP por estado (limite superior do prefixo de 5 dígitos).
FAIXAS_CEP: list[tuple[int, int, str]] = [
    (1000, 19999, "SP"),
    (20000, 28999, "RJ"),
    (29000, 29999, "ES"),
    (30000, 39999, "MG"),
    (40000, 48999, "BA"),
    (49000, 49999, "SE"),
    (50000, 56999, "PE"),
    (57000, 57999, "AL"),
    (58000, 58999, "PB"),
    (59000, 59999, "RN"),
    (60000, 63999, "CE"),
    (64000, 64999, "PI"),
    (65000, 65999, "MA"),
    (66000, 68899, "PA"),
    (68900, 68999, "AP"),
    (69000, 69299, "AM"),
    (69300, 69399, "RR"),
    (69400, 69899, "AM"),
    (69900, 69999, "AC"),
    (70000, 72799, "DF"),
    (72800, 72999, "GO"),
    (73000, 73699, "DF"),
    (73700, 76799, "GO"),
    (76800, 76999, "RO"),
    (77000, 77999, "TO"),
    (78000, 78899, "MT"),
    (79000, 79999, "MS"),
    (80000, 87999, "PR"),
    (88000, 89999, "SC"),
    (90000, 99999, "RS"),
]

# Capitais (lat, lon).
CAPITAIS: dict[str, tuple[float, float]] = {
    "AC": (-9.97, -67.81),
    "AL": (-9.65, -35.73),
    "AM": (-3.10, -60.02),
    "AP": (0.03, -51.07),
    "BA": (-12.97, -38.50),
    "CE": (-3.73, -38.53),
    "DF": (-15.78, -47.93),
    "ES": (-20.32, -40.34),
    "GO": (-16.68, -49.25),
    "MA": (-2.53, -44.30),
    "MG": (-19.92, -43.94),
    "MS": (-20.44, -54.65),
    "MT": (-15.60, -56.10),
    "PA": (-1.46, -48.50),
    "PB": (-7.12, -34.86),
    "PE": (-8.05, -34.90),
    "PI": (-5.09, -42.80),
    "PR": (-25.43, -49.27),
    "RJ": (-22.91, -43.17),
    "RN": (-5.79, -35.21),
    "RO": (-8.76, -63.90),
    "RR": (2.82, -60.67),
    "RS": (-30.03, -51.23),
    "SC": (-27.59, -48.55),
    "SE": (-10.91, -37.07),
    "SP": (-23.55, -46.63),
    "TO": (-10.18, -48.33),
}

RAIO_TERRA_KM = 6371.0
# Distância mínima quando origem e destino são o mesmo estado: sem isso o
# preço por km explodiria ao dividir por zero.
MINIMO_KM = 60.0


def uf_por_cep(cep: str | int | None) -> str | None:
    """Descobre a UF a partir do CEP (aceita string com máscara ou inteiro)."""
    if cep is None:
        return None
    digitos = "".join(ch for ch in str(cep) if ch.isdigit())
    if len(digitos) < 5:
        return None
    prefixo = int(digitos[:5])
    for inicio, fim, uf in FAIXAS_CEP:
        if inicio <= prefixo <= fim:
            return uf
    return None


def distancia_km(origem: str | None, destino: str | None) -> float | None:
    """Haversine entre as capitais das duas UFs."""
    if not origem or not destino:
        return None
    a, b = CAPITAIS.get(origem), CAPITAIS.get(destino)
    if not a or not b:
        return None
    if origem == destino:
        return MINIMO_KM

    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return max(2 * RAIO_TERRA_KM * asin(sqrt(h)), MINIMO_KM)
