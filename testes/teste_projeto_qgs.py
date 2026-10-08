# -*- coding: utf-8 -*-
"""Valida a estrutura do .qgs gerado.

Nao substitui abrir no QGIS de verdade, mas pega os erros que dariam "camada
invalida": XML mal formado, id inconsistente entre as tres secoes que precisam
casar, caminho de dado que nao existe, geometria com nome errado.
"""
import os, sys, shutil, warnings
import xml.etree.ElementTree as ET
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fiona
from conversor import convert

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida", "qgs")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE)
ok = fail = 0

def checar(nome, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  [OK]   %s %s" % (nome, extra))
    else:    fail += 1; print("  [FALHA] %s %s" % (nome, extra))

# monta um DXF de origem
origem = os.path.join(BASE, "fonte.gpkg")
from fiona.crs import CRS
with fiona.open(origem, "w", driver="GPKG", layer="curvas", crs=CRS.from_epsg(31982),
                schema={"geometry": "LineString", "properties": {"cota": "int"}}) as c:
    c.write({"type": "Feature", "properties": {"cota": 100},
             "geometry": {"type": "LineString",
                          "coordinates": [(412000.0, 6712000.0), (412300.0, 6712200.0)]}})
with fiona.open(origem, "w", driver="GPKG", layer="pontos", crs=CRS.from_epsg(31982),
                schema={"geometry": "Point", "properties": {"cod": "str"}}) as c:
    c.write({"type": "Feature", "properties": {"cod": "AM-1"},
             "geometry": {"type": "Point", "coordinates": (412100.0, 6712050.0)}})
dxf = os.path.join(BASE, "fonte.dxf")
convert.qgis_para_cad([{"caminho": origem, "camada": n} for n in ["curvas", "pontos"]],
                      dxf, 31982, registrar=lambda *_: None)

for formato, saida in [("GPKG", os.path.join(BASE, "r.gpkg")),
                       ("ESRI Shapefile", os.path.join(BASE, "r_shp")),
                       ("GeoJSON", os.path.join(BASE, "r_json"))]:
    print("\n=== %s ===" % formato)
    res = convert.cad_para_qgis(dxf, saida, 31982, formato=formato,
                               registrar=lambda *_: None)
    qgs = res.get("projeto")
    checar("projeto gerado", bool(qgs) and os.path.exists(qgs))
    if not qgs:
        continue

    # 1. XML bem formado
    try:
        raiz = ET.parse(qgs).getroot()
        checar("XML bem formado", True)
    except Exception as e:
        checar("XML bem formado", False, str(e)); continue

    checar("elemento raiz e <qgis>", raiz.tag == "qgis")
    checar("tem versao", bool(raiz.get("version")), "-> " + str(raiz.get("version")))

    # 2. as tres secoes que precisam casar por id
    ids_arvore = {e.get("id") for e in raiz.iter("layer-tree-layer")}
    ids_def = {e.findtext("id") for e in raiz.iter("maplayer")}
    ids_ordem = {e.get("id") for e in raiz.find("layerorder")}
    checar("ids batem entre arvore e definicoes", ids_arvore == ids_def,
           "%d vs %d" % (len(ids_arvore), len(ids_def)))
    checar("ids batem com a ordem de desenho", ids_arvore == ids_ordem)
    checar("nenhum id vazio", all(ids_arvore) and None not in ids_arvore)

    # 3. o CRS foi gravado
    crs_proj = raiz.find("projectCrs/spatialrefsys/authid")
    checar("CRS do projeto presente", crs_proj is not None and crs_proj.text == "EPSG:31982",
           "-> " + (crs_proj.text if crs_proj is not None else "ausente"))
    for camada in raiz.iter("maplayer"):
        aid = camada.findtext("srs/spatialrefsys/authid")
        if aid != "EPSG:31982":
            checar("CRS da camada", False, "-> %s" % aid); break
    else:
        checar("CRS em todas as camadas", True)

    # 4. os caminhos apontam para arquivos que existem
    pasta = os.path.dirname(qgs)
    todos_existem = True
    for camada in raiz.iter("maplayer"):
        fonte = camada.findtext("datasource")
        arquivo = fonte.split("|")[0]
        caminho = os.path.normpath(os.path.join(pasta, arquivo))
        if not os.path.exists(caminho):
            todos_existem = False
            print("       caminho quebrado: %s" % fonte)
    checar("todos os dados referenciados existem", todos_existem)

    # 5. nomes de geometria que o QGIS entende
    geoms = {c.get("geometry") for c in raiz.iter("maplayer")}
    checar("geometrias validas p/ QGIS", geoms <= {"Point", "Line", "Polygon"},
           "-> " + str(sorted(geoms)))

    # 6. provider e caminhos relativos
    provs = {c.findtext("provider") for c in raiz.iter("maplayer")}
    checar("provider = ogr", provs == {"ogr"}, "-> " + str(provs))
    abs_ = raiz.find("properties/Paths/Absolute")
    checar("caminhos relativos ligados", abs_ is not None and abs_.text == "false")

    # 7. extensao coerente com os dados
    ext = raiz.find("mapcanvas/extent")
    if ext is not None:
        xmin, xmax = float(ext.findtext("xmin")), float(ext.findtext("xmax"))
        checar("extensao cobre os dados", xmin < 412000 and xmax > 412300,
               "-> %.0f a %.0f" % (xmin, xmax))
    else:
        checar("extensao presente", False)

    checar("n de camadas bate com o convertido", len(ids_arvore) == len(res["grupos"]),
           "%d camadas" % len(ids_arvore))

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
