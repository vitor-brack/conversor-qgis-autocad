# -*- coding: utf-8 -*-
"""
Sistemas de coordenadas (CRS) mais usados no Brasil.

Por que este modulo existe: arquivos DXF/DWG do AutoCAD NAO guardam o sistema
de coordenadas. Sao apenas numeros ("X = 412350, Y = 6712100"), sem dizer a que
projecao pertencem. Entao alguem precisa declarar isso na mao em toda conversao.
Este modulo oferece a lista pronta para o usuario escolher, em vez de exigir que
ele decore codigos EPSG.
"""

import pyproj

# EPSG padrao do programa. SIRGAS 2000 / UTM 22S cobre RS, SC, PR e boa parte
# do Centro-Oeste -- e o mais comum em levantamentos no Sul do Brasil.
PADRAO = 31982

# (epsg, rotulo exibido). A ordem e a ordem do menu suspenso.
PRESETS = [
    (31982, "SIRGAS 2000 / UTM 22S  -  RS, SC, PR, MS (padrao)"),
    (31981, "SIRGAS 2000 / UTM 21S  -  MS oeste, MT, RO"),
    (31983, "SIRGAS 2000 / UTM 23S  -  SP, RJ, MG, GO"),
    (31984, "SIRGAS 2000 / UTM 24S  -  BA, ES, sul da BA"),
    (31985, "SIRGAS 2000 / UTM 25S  -  PE, PB, RN, AL, SE"),
    (31979, "SIRGAS 2000 / UTM 19S  -  AC, AM oeste"),
    (31980, "SIRGAS 2000 / UTM 20S  -  AM, RO oeste"),
    (None, "---- Geograficas (graus) - evite no AutoCAD ----"),
    (4674, "SIRGAS 2000 (graus, lat/lon)"),
    (4326, "WGS 84 (graus, lat/lon - GPS, Google Earth)"),
    (None, "---- WGS 84 / UTM ----"),
    (32721, "WGS 84 / UTM 21S"),
    (32722, "WGS 84 / UTM 22S"),
    (32723, "WGS 84 / UTM 23S"),
    (32724, "WGS 84 / UTM 24S"),
    (None, "---- Datums antigos (levantamentos pre-2005) ----"),
    (29192, "SAD69 / UTM 22S"),
    (29193, "SAD69 / UTM 23S"),
    (22522, "Corrego Alegre / UTM 22S"),
    (22523, "Corrego Alegre / UTM 23S"),
]


def rotulo(epsg):
    """Rotulo amigavel de um EPSG; consulta o pyproj se nao estiver na lista."""
    for code, texto in PRESETS:
        if code == epsg:
            return texto
    try:
        return pyproj.CRS.from_epsg(epsg).name
    except Exception:
        return "EPSG:%s" % epsg


def eh_projetado(epsg):
    """True se o CRS usa metros (projetado). False se usa graus (geografico).

    Importa muito: desenhar em graus no AutoCAD produz um desenho de ~0,01
    unidade de largura, inutil para medir distancia ou area.
    """
    try:
        return pyproj.CRS.from_epsg(epsg).is_projected
    except Exception:
        return True


def unidade(epsg):
    """Nome da unidade do eixo ('metre', 'degree', ...)."""
    try:
        return pyproj.CRS.from_epsg(epsg).axis_info[0].unit_name
    except Exception:
        return "?"


def valido(epsg):
    try:
        pyproj.CRS.from_epsg(int(epsg))
        return True
    except Exception:
        return False


def sugerir_utm(lon, lat):
    """Sugere o SIRGAS 2000 / UTM adequado a partir de uma coordenada geografica.

    Usado para avisar o usuario quando ele manda dados em graus para o AutoCAD:
    o programa consegue propor a zona correta em vez de so reclamar.
    """
    zona = int((lon + 180) / 6) + 1
    if lat < 0 and 17 <= zona <= 25:
        return 31960 + zona          # 31981 = zona 21S, 31982 = 22S, ...
    return None
