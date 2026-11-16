# -*- coding: utf-8 -*-
"""Teste de ponta a ponta com dados parecidos com os de um geologo.

Ciclo completo QGIS -> AutoCAD -> QGIS: o que sai do GeoPackage vira DXF e
volta com as mesmas coordenadas.
"""
import glob
import os
import shutil

import fiona
import pyproj
import pytest
from fiona.crs import CRS

from conversor import convert, dxfio

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida", "rt")
CAMADAS = ["curvas_nivel", "amostras", "corpos"]


@pytest.fixture(scope="module")
def campo():
    """GeoPackage com 3 camadas, em SIRGAS 2000 / UTM 22S."""
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    gpkg = os.path.join(BASE, "campo.gpkg")
    crs = CRS.from_epsg(31982)

    # 1) curvas de nivel, 3D
    with fiona.open(gpkg, "w", driver="GPKG", layer="curvas_nivel", crs=crs,
                    schema={"geometry": "LineString",
                            "properties": {"cota": "int", "tipo": "str"}}) as c:
        for i, cota in enumerate([100, 120, 140]):
            coords = [(412000.0 + j * 50, 6712000.0 + i * 80 + j * 3, float(cota))
                      for j in range(6)]
            c.write({"type": "Feature",
                     "geometry": {"type": "LineString", "coordinates": coords},
                     "properties": {"cota": cota,
                                    "tipo": "mestra" if cota % 40 == 0 else "intermediaria"}})

    # 2) pontos de amostra, com rotulo e acentos
    with fiona.open(gpkg, "w", driver="GPKG", layer="amostras", crs=crs,
                    schema={"geometry": "Point",
                            "properties": {"codigo": "str", "litologia": "str",
                                           "prof": "float"}}) as c:
        amostras = [("AM-01", "Basalto vesicular", 12.5),
                    ("AM-02", "Arenito Botucatu", 30.0),
                    ("AM-03", "Riolito Pórfiro", 8.25)]
        for k, (cod, lit, prof) in enumerate(amostras):
            c.write({"type": "Feature",
                     "geometry": {"type": "Point",
                                  "coordinates": (412100.0 + k * 120, 6712250.0, 0.0)},
                     "properties": {"codigo": cod, "litologia": lit, "prof": prof}})

    # 3) corpo geologico com buraco, e nome de camada acentuado
    with fiona.open(gpkg, "w", driver="GPKG", layer="corpos", crs=crs,
                    schema={"geometry": "Polygon", "properties": {"unidade": "str"}}) as c:
        externo = [(412000.0, 6712400.0), (412400.0, 6712400.0), (412400.0, 6712700.0),
                   (412000.0, 6712700.0), (412000.0, 6712400.0)]
        buraco = [(412150.0, 6712500.0), (412250.0, 6712500.0), (412250.0, 6712600.0),
                  (412150.0, 6712600.0), (412150.0, 6712500.0)]
        c.write({"type": "Feature",
                 "geometry": {"type": "Polygon", "coordinates": [externo, buraco]},
                 "properties": {"unidade": "Formação Serra Geral"}})
        c.write({"type": "Feature",
                 "geometry": {"type": "Polygon",
                              "coordinates": [[(412500.0, 6712400.0), (412700.0, 6712400.0),
                                               (412700.0, 6712550.0), (412500.0, 6712400.0)]]},
                 "properties": {"unidade": "Intrusão Ácida"}})
    return gpkg


@pytest.fixture(scope="module")
def para_cad(campo):
    """QGIS -> AutoCAD: devolve (resultado da conversao, caminho do DXF)."""
    dxf = os.path.join(BASE, "campo.dxf")
    res = convert.qgis_para_cad(
        entradas=[{"caminho": campo, "camada": n} for n in CAMADAS],
        saida=dxf, epsg_destino=31982,
        campo_camada=None, campo_rotulo="codigo", registrar=lambda *_: None)
    return res, dxf


@pytest.fixture(scope="module")
def volta(para_cad):
    """AutoCAD -> QGIS (GPKG): devolve o caminho do GeoPackage de volta."""
    _, dxf = para_cad
    saida = os.path.join(BASE, "volta.gpkg")
    convert.cad_para_qgis(dxf, saida, epsg_origem=dxfio.ler_crs_acompanhante(dxf),
                          formato="GPKG", poli_fechada_como_poligono=True,
                          registrar=lambda *_: None)
    return saida


def feicoes(arquivo, camada):
    with fiona.open(arquivo, layer=camada) as c:
        return [f for f in c]


# --------------------------------------------------- QGIS -> AutoCAD
def test_qgis_para_cad_grava_feicoes_e_rotulos(para_cad):
    res, _ = para_cad
    assert res["feicoes"] == 8, "8 feicoes gravadas -> %d" % res["feicoes"]
    assert res["rotulos"] == 3, "3 rotulos gravados -> %s" % res["rotulos"]


def test_dxf_e_ascii_e_poligono_sai_como_contorno(para_cad):
    _, dxf = para_cad
    with open(dxf, "rb") as fp:
        raw = fp.read()
    assert all(b < 128 for b in raw), "arquivo e ASCII puro"
    entidades = raw.decode("ascii")
    entidades = entidades[entidades.index("ENTITIES"):]
    # poligono do QGIS vira contorno no AutoCAD, nao uma mancha preenchida
    assert "HATCH" not in entidades and "LWPOLYLINE" in entidades, \
        "poligonos saem como contorno, sem HATCH"


def test_crs_gravado_ao_lado_do_desenho(para_cad):
    _, dxf = para_cad
    pasta, nome = os.path.split(dxf)
    acompanhantes = {os.path.basename(f)
                     for f in glob.glob(os.path.join(pasta, os.path.splitext(nome)[0] + ".*"))}
    assert {"campo.prj", "campo.crs.txt", "campo.conversor.json"} <= acompanhantes, \
        "CRS gravado ao lado do desenho -> %s" % sorted(acompanhantes)


# --------------------------------------------------- AutoCAD -> QGIS
def test_crs_recuperado_do_acompanhante(para_cad):
    _, dxf = para_cad
    epsg_lido = dxfio.ler_crs_acompanhante(dxf)
    assert epsg_lido == 31982, "CRS recuperado do acompanhante -> %s" % epsg_lido


def test_curvas_voltam_identicas(campo, volta):
    original = feicoes(campo, "curvas_nivel")
    linhas = feicoes(volta, "curvas_nivel_LineString")
    a = original[0]["geometry"]["coordinates"][0]
    b = linhas[0]["geometry"]["coordinates"][0]
    assert len(linhas) == len(original), "curvas: mesma quantidade"
    assert tuple(round(v, 6) for v in a) == tuple(round(v, 6) for v in b), \
        "curvas: coordenadas identicas -> %s" % (b,)
    assert len(b) == 3 and b[2] == a[2], "curvas: cota Z preservada"


def test_corpos_voltam_como_areas(volta):
    # O buraco do poligono vira um contorno a parte: o DXF nao tem como dizer que
    # uma polilinha e o buraco de outra. Com a opcao de areas, cada contorno
    # fechado volta como um poligono.
    pols = feicoes(volta, "corpos_Polygon")
    assert len(pols) == 3, \
        "corpos: contornos voltam como areas (externo, buraco e triangulo) -> %d" % len(pols)
    vertices = sorted(len(f["geometry"]["coordinates"][0]) for f in pols)
    assert vertices == [4, 5, 5], "corpos: vertices preservados -> %s" % vertices


def test_amostras_voltam_com_os_rotulos(volta):
    pts = feicoes(volta, "amostras_Point")
    textos = sorted(f["properties"]["Text"] for f in feicoes(volta, "amostras_Texto"))
    assert len(pts) == 3, "amostras: 3 pontos"
    assert textos == ["AM-01", "AM-02", "AM-03"], "amostras: rotulos lidos de volta -> %s" % textos


def test_posicao_geografica_cai_no_rs(campo):
    a = feicoes(campo, "curvas_nivel")[0]["geometry"]["coordinates"][0]
    t = pyproj.Transformer.from_crs("EPSG:31982", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(a[0], a[1])
    assert -52.5 < lon < -51.5 and -30.0 < lat < -29.5, \
        "posicao geografica no RS -> %.5f, %.5f" % (lon, lat)
