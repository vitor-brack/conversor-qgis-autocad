# -*- coding: utf-8 -*-
"""Constroi a janela e exercita reprojecao, avisos e erros."""
import os, sys, shutil, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fiona
from fiona.crs import CRS
from conversor import convert, crs_presets, dxfio

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida")
os.makedirs(BASE, exist_ok=True)
T = os.path.join(BASE, "casos")
shutil.rmtree(T, ignore_errors=True)
os.makedirs(T)
ok = fail = 0

def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1; print("  [FALHA] %s %s" % (nome, extra))

# ---------------------------------------------------------------- 1. interface
print("\n1) CONSTRUCAO DA JANELA")
try:
    from conversor.gui import App
    app = App()
    app.update_idletasks()
    abas = [w for w in app.winfo_children()]
    app.aba1._atualizar_derivados()
    app.aba2._alternar_reproj()
    app.aba1._alternar_origem()
    app.registrar("teste")
    app.aba1.crs_destino.definir(4326)
    aviso_graus = app.aba1.crs_destino.aviso.cget("text")
    app.aba1.crs_destino.definir(31982)
    aviso_utm = app.aba1.crs_destino.aviso.cget("text")
    app.destroy()
    checar("janela monta e destroi sem erro", True)
    checar("avisa ao escolher CRS em graus", "graus" in aviso_graus)
    checar("nao avisa em UTM", aviso_utm == "")
except Exception as e:
    import traceback; traceback.print_exc()
    checar("janela monta", False, str(e))

# ---------------------------------------------------------------- 2. reprojecao
print("\n2) REPROJECAO WGS84 (graus) -> UTM 22S (metros)")
wgs = os.path.join(T, "wgs.geojson")
with fiona.open(wgs, "w", driver="GeoJSON", crs=CRS.from_epsg(4326),
                schema={"geometry": "Point", "properties": {"nome": "str"}}) as c:
    c.write({"type": "Feature",
             "geometry": {"type": "Point", "coordinates": (-51.90984, -29.71904)},
             "properties": {"nome": "ponto1"}})
dxf = os.path.join(T, "reproj.dxf")
avisos = []
r = convert.qgis_para_cad([{"caminho": wgs, "camada": None}], dxf, 31982,
                          registrar=avisos.append)
with fiona.open(dxf) as c:
    xy = [f["geometry"]["coordinates"] for f in c][0]
checar("reprojetou para metros", 400000 < xy[0] < 500000 and 6_000_000 < xy[1] < 7_000_000,
       "-> %.1f, %.1f" % (xy[0], xy[1]))
checar("registrou a reprojecao", any("reprojetando" in a for a in avisos))

print("\n3) AVISO AO GRAVAR DESENHO EM GRAUS")
avisos = []
convert.qgis_para_cad([{"caminho": wgs, "camada": None}],
                      os.path.join(T, "graus.dxf"), 4326, registrar=avisos.append)
checar("avisa que graus nao serve p/ AutoCAD", any("graus" in a for a in avisos))

# ---------------------------------------------------------------- 4. sem .prj
print("\n4) CAMADA SEM SISTEMA DE COORDENADAS")
semprj = os.path.join(T, "semprj")
os.makedirs(semprj)
shp = os.path.join(semprj, "x.shp")
with fiona.open(shp, "w", driver="ESRI Shapefile", crs=None,
                schema={"geometry": "Point", "properties": {"a": "str"}}) as c:
    c.write({"type": "Feature", "geometry": {"type": "Point", "coordinates": (1.0, 2.0)},
             "properties": {"a": "b"}})
if os.path.exists(os.path.join(semprj, "x.prj")):
    os.remove(os.path.join(semprj, "x.prj"))
try:
    convert.qgis_para_cad([{"caminho": shp, "camada": None}],
                          os.path.join(T, "n.dxf"), 31982, registrar=lambda *_: None)
    checar("erro claro quando falta .prj", False, "nao levantou erro")
except convert.ErroConversao as e:
    checar("erro claro quando falta .prj", "sistema de coordenadas" in str(e))
# e funciona quando o usuario declara
r = convert.qgis_para_cad([{"caminho": shp, "camada": None}], os.path.join(T, "ok.dxf"),
                          31982, epsg_origem_forcado=31982, registrar=lambda *_: None)
checar("converte quando o usuario declara o CRS", r["feicoes"] == 1)

# ---------------------------------------------------------------- 5. DXF vazio
print("\n5) DESENHO SEM GEOMETRIA")
vazio = os.path.join(T, "vazio.dxf")
shutil.copy(os.path.join(T, "ok.dxf"), vazio)
corpo = open(vazio, encoding="utf-8", errors="replace").read()
i = corpo.find("\nENTITIES\n"); j = corpo.find("\n  0\nENDSEC", i)
open(vazio, "w", encoding="utf-8").write(corpo[:i + len("\nENTITIES\n")] + corpo[j + 1:])
try:
    convert.cad_para_qgis(vazio, os.path.join(T, "v.gpkg"), 31982, registrar=lambda *_: None)
    checar("erro claro em desenho vazio", False, "nao levantou erro")
except convert.ErroConversao as e:
    checar("erro claro em desenho vazio", "Nenhuma geometria" in str(e))

# ---------------------------------------------------------------- 6. acentos
print("\n6) ACENTOS NOS NOMES DE CAMADA")
ac = os.path.join(T, "ac.gpkg")
with fiona.open(ac, "w", driver="GPKG", layer="u", crs=CRS.from_epsg(31982),
                schema={"geometry": "Point", "properties": {"unidade": "str"}}) as c:
    for u in ["Forma\u00e7\u00e3o Serra Geral", "Intrus\u00e3o \u00c1cida", "Se\u00e7\u00e3o A-A"]:
        c.write({"type": "Feature", "geometry": {"type": "Point", "coordinates": (400000.0, 6700000.0)},
                 "properties": {"unidade": u}})
d = os.path.join(T, "ac.dxf")
r = convert.qgis_para_cad([{"caminho": ac, "camada": "u"}], d, 31982,
                          campo_camada="unidade", registrar=lambda *_: None)
raw = open(d, "rb").read()
checar("DXF ficou ASCII puro", all(b < 128 for b in raw))
checar("camadas transliteradas", r["camadas"] == ["Formacao_Serra_Geral", "Intrusao_Acida", "Secao_A-A"],
       str(r["camadas"]))

# ---------------------------------------------------------------- 7. CSV
print("\n7) CSV DE ATRIBUTOS")
csvp = os.path.join(T, "ac_atributos.csv")
checar("csv gerado", os.path.exists(csvp))
if os.path.exists(csvp):
    txt = open(csvp, encoding="utf-8-sig").read()
    checar("csv preserva o acento original", "Forma\u00e7\u00e3o Serra Geral" in txt)
    checar("csv usa ; (Excel pt-BR)", ";" in txt.splitlines()[0])

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
