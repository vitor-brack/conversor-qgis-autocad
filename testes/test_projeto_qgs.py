# -*- coding: utf-8 -*-
"""Valida a estrutura do .qgs gerado.

Nao substitui abrir no QGIS de verdade, mas pega os erros que dariam "camada
invalida": XML mal formado, id inconsistente entre as tres secoes que precisam
casar, caminho de dado que nao existe, geometria com nome errado.
"""
import os
import shutil
import xml.etree.ElementTree as ET

import fiona
import pytest
from fiona.crs import CRS

from conversor import convert

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida", "qgs")
FORMATOS = {"GPKG": "r.gpkg", "ESRI Shapefile": "r_shp", "GeoJSON": "r_json"}


@pytest.fixture(scope="module")
def dxf():
    """DXF de origem: uma curva e um ponto, gerados a partir de um GeoPackage."""
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    origem = os.path.join(BASE, "fonte.gpkg")
    with fiona.open(origem, "w", driver="GPKG", layer="curvas", crs=CRS.from_epsg(31982),
                    schema={"geometry": "LineString", "properties": {"cota": "int"}}) as c:
        c.write({"type": "Feature", "properties": {"cota": 100},
                 "geometry": {"type": "LineString",
                              "coordinates": [(412000.0, 6712000.0), (412300.0, 6712200.0)]}})
    with fiona.open(origem, "w", driver="GPKG", layer="pontos", crs=CRS.from_epsg(31982),
                    schema={"geometry": "Point", "properties": {"cod": "str"}}) as c:
        c.write({"type": "Feature", "properties": {"cod": "AM-1"},
                 "geometry": {"type": "Point", "coordinates": (412100.0, 6712050.0)}})
    saida = os.path.join(BASE, "fonte.dxf")
    convert.qgis_para_cad([{"caminho": origem, "camada": n} for n in ["curvas", "pontos"]],
                          saida, 31982, registrar=lambda *_: None)
    return saida


@pytest.fixture(scope="module", params=list(FORMATOS))
def projeto(request, dxf):
    """Resultado da conversao DXF -> QGIS, uma vez para cada formato de saida."""
    return convert.cad_para_qgis(dxf, os.path.join(BASE, FORMATOS[request.param]), 31982,
                                 formato=request.param, registrar=lambda *_: None)


@pytest.fixture(scope="module")
def raiz(projeto):
    return ET.parse(projeto["projeto"]).getroot()


def test_projeto_gerado(projeto):
    qgs = projeto.get("projeto")
    assert qgs and os.path.exists(qgs), "projeto gerado"


def test_xml_bem_formado(projeto):
    assert ET.parse(projeto["projeto"]).getroot() is not None, "XML bem formado"


def test_raiz_e_versao(raiz):
    assert raiz.tag == "qgis", "elemento raiz e <qgis>"
    assert raiz.get("version"), "tem versao -> %s" % raiz.get("version")


def test_as_tres_secoes_casam_por_id(raiz):
    ids_arvore = {e.get("id") for e in raiz.iter("layer-tree-layer")}
    ids_def = {e.findtext("id") for e in raiz.iter("maplayer")}
    ids_ordem = {e.get("id") for e in raiz.find("layerorder")}
    assert ids_arvore == ids_def, \
        "ids batem entre arvore e definicoes -> %d vs %d" % (len(ids_arvore), len(ids_def))
    assert ids_arvore == ids_ordem, "ids batem com a ordem de desenho"
    assert all(ids_arvore) and None not in ids_arvore, "nenhum id vazio"


def test_crs_do_projeto_e_das_camadas(raiz):
    crs_proj = raiz.find("projectCrs/spatialrefsys/authid")
    assert crs_proj is not None and crs_proj.text == "EPSG:31982", \
        "CRS do projeto presente -> %s" % (crs_proj.text if crs_proj is not None else "ausente")
    outros = {c.findtext("srs/spatialrefsys/authid") for c in raiz.iter("maplayer")} - {"EPSG:31982"}
    assert not outros, "CRS em todas as camadas -> %s" % outros


def test_todos_os_dados_referenciados_existem(projeto, raiz):
    pasta = os.path.dirname(projeto["projeto"])
    quebrados = []
    for camada in raiz.iter("maplayer"):
        fonte = camada.findtext("datasource")
        caminho = os.path.normpath(os.path.join(pasta, fonte.split("|")[0]))
        if not os.path.exists(caminho):
            quebrados.append(fonte)
    assert not quebrados, "todos os dados referenciados existem -> quebrados: %s" % quebrados


def test_geometrias_que_o_qgis_entende(raiz):
    geoms = {c.get("geometry") for c in raiz.iter("maplayer")}
    assert geoms <= {"Point", "Line", "Polygon"}, "geometrias validas p/ QGIS -> %s" % sorted(geoms)


def test_provider_ogr_e_caminhos_relativos(raiz):
    provs = {c.findtext("provider") for c in raiz.iter("maplayer")}
    assert provs == {"ogr"}, "provider = ogr -> %s" % provs
    absoluto = raiz.find("properties/Paths/Absolute")
    assert absoluto is not None and absoluto.text == "false", "caminhos relativos ligados"


def test_extensao_cobre_os_dados(raiz):
    ext = raiz.find("mapcanvas/extent")
    if ext is None:
        pytest.fail("extensao presente")
    xmin, xmax = float(ext.findtext("xmin")), float(ext.findtext("xmax"))
    assert xmin < 412000 and xmax > 412300, "extensao cobre os dados -> %.0f a %.0f" % (xmin, xmax)


def test_numero_de_camadas_bate_com_o_convertido(projeto, raiz):
    ids_arvore = {e.get("id") for e in raiz.iter("layer-tree-layer")}
    assert len(ids_arvore) == len(projeto["grupos"]), \
        "n de camadas bate com o convertido -> %d camadas" % len(ids_arvore)
