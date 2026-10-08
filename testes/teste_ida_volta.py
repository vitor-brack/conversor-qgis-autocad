# -*- coding: utf-8 -*-
"""Teste de ponta a ponta com dados parecidos com os de um geologo."""
import os, sys, shutil, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fiona
from fiona.crs import CRS
from conversor import convert, dxfio

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida")
os.makedirs(BASE, exist_ok=True)
TMP = os.path.join(BASE, "rt")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

def p(*a): print(*a)

# ---------------------------------------------------------------- dados fonte
# GPKG com 3 camadas, em SIRGAS 2000 / UTM 22S
gpkg = os.path.join(TMP, "campo.gpkg")
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
                 "properties": {"cota": cota, "tipo": "mestra" if cota % 40 == 0 else "intermediaria"}})

# 2) pontos de amostra, com rotulo e acentos
with fiona.open(gpkg, "w", driver="GPKG", layer="amostras", crs=crs,
                schema={"geometry": "Point",
                        "properties": {"codigo": "str", "litologia": "str", "prof": "float"}}) as c:
    amostras = [("AM-01", "Basalto vesicular", 12.5),
                ("AM-02", "Arenito Botucatu", 30.0),
                ("AM-03", "Riolito P\u00f3rfiro", 8.25)]
    for k, (cod, lit, prof) in enumerate(amostras):
        c.write({"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": (412100.0 + k * 120, 6712250.0, 0.0)},
                 "properties": {"codigo": cod, "litologia": lit, "prof": prof}})

# 3) corpo geologico com buraco, e nome de camada acentuado
with fiona.open(gpkg, "w", driver="GPKG", layer="corpos", crs=crs,
                schema={"geometry": "Polygon", "properties": {"unidade": "str"}}) as c:
    ext = [(412000.0, 6712400.0), (412400.0, 6712400.0), (412400.0, 6712700.0),
           (412000.0, 6712700.0), (412000.0, 6712400.0)]
    int = [(412150.0, 6712500.0), (412250.0, 6712500.0), (412250.0, 6712600.0),
           (412150.0, 6712600.0), (412150.0, 6712500.0)]
    c.write({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ext, int]},
             "properties": {"unidade": "Forma\u00e7\u00e3o Serra Geral"}})
    c.write({"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": [[(412500.0, 6712400.0),
                          (412700.0, 6712400.0), (412700.0, 6712550.0), (412500.0, 6712400.0)]]},
             "properties": {"unidade": "Intrus\u00e3o \u00c1cida"}})

p("camadas de origem:", fiona.listlayers(gpkg))

# --------------------------------------------------- QGIS -> AutoCAD
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        p("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        p("  [FALHA] %s %s" % (nome, extra))


p("")
p("===== QGIS -> AUTOCAD =====")
dxf = os.path.join(TMP, "campo.dxf")
res = convert.qgis_para_cad(
    entradas=[{"caminho": gpkg, "camada": n} for n in ["curvas_nivel", "amostras", "corpos"]],
    saida=dxf, epsg_destino=31982,
    campo_camada=None, campo_rotulo="codigo", registrar=lambda *_: None)
checar("8 feicoes gravadas", res["feicoes"] == 8, "-> %d" % res["feicoes"])
checar("3 rotulos gravados", res["rotulos"] == 3)

with open(dxf, "rb") as fp:
    raw = fp.read()
checar("arquivo e ASCII puro", all(b < 128 for b in raw))
entidades = raw.decode("ascii")
entidades = entidades[entidades.index("ENTITIES"):]
# poligono do QGIS vira contorno no AutoCAD, nao uma mancha preenchida
checar("poligonos saem como contorno, sem HATCH",
       "HATCH" not in entidades and "LWPOLYLINE" in entidades)
acompanhantes = sorted(os.path.basename(f) for f in
                       __import__("glob").glob(os.path.join(TMP, "campo.*")))
checar("CRS gravado ao lado do desenho",
       {"campo.prj", "campo.crs.txt", "campo.conversor.json"} <= set(acompanhantes))

# --------------------------------------------------- AutoCAD -> QGIS
p("")
p("===== AUTOCAD -> QGIS (GPKG) =====")
volta = os.path.join(TMP, "volta.gpkg")
epsg_lido = dxfio.ler_crs_acompanhante(dxf)
checar("CRS recuperado do acompanhante", epsg_lido == 31982, "-> %s" % epsg_lido)
convert.cad_para_qgis(dxf, volta, epsg_origem=epsg_lido, formato="GPKG",
                      poli_fechada_como_poligono=True, registrar=lambda *_: None)
p("  camadas:", fiona.listlayers(volta))

orig = {}
for n in ["curvas_nivel", "amostras", "corpos"]:
    with fiona.open(gpkg, layer=n) as c:
        orig[n] = [f for f in c]

with fiona.open(volta, layer="curvas_nivel_LineString") as c:
    linhas = [f for f in c]
a = orig["curvas_nivel"][0]["geometry"]["coordinates"][0]
b = linhas[0]["geometry"]["coordinates"][0]
checar("curvas: mesma quantidade", len(linhas) == len(orig["curvas_nivel"]))
checar("curvas: coordenadas identicas",
       tuple(round(v, 6) for v in a) == tuple(round(v, 6) for v in b), "-> %s" % (b,))
checar("curvas: cota Z preservada", len(b) == 3 and b[2] == a[2])

# O buraco do poligono vira um contorno a parte: o DXF nao tem como dizer que
# uma polilinha e o buraco de outra. Com a opcao de areas, cada contorno
# fechado volta como um poligono.
with fiona.open(volta, layer="corpos_Polygon") as c:
    pols = [f for f in c]
checar("corpos: contornos voltam como areas (externo, buraco e triangulo)",
       len(pols) == 3, "-> %d" % len(pols))
vertices = sorted(len(f["geometry"]["coordinates"][0]) for f in pols)
checar("corpos: vertices preservados", vertices == [4, 5, 5], "-> %s" % vertices)

with fiona.open(volta, layer="amostras_Point") as c:
    pts = [f for f in c]
with fiona.open(volta, layer="amostras_Texto") as c:
    textos = sorted(f["properties"]["Text"] for f in c)
checar("amostras: 3 pontos", len(pts) == 3)
checar("amostras: rotulos lidos de volta", textos == ["AM-01", "AM-02", "AM-03"],
       "-> %s" % textos)

import pyproj
t = pyproj.Transformer.from_crs("EPSG:31982", "EPSG:4326", always_xy=True)
lon, lat = t.transform(a[0], a[1])
checar("posicao geografica no RS", -52.5 < lon < -51.5 and -30.0 < lat < -29.5,
       "-> %.5f, %.5f" % (lon, lat))

p("")
p("%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
