# -*- coding: utf-8 -*-
"""
Verifica que a aparencia do desenho chega ao QGIS: a cor de cada ENTIDADE e o
texto com os acentos certos.

Os dois defeitos que motivaram estes testes, ambos vistos num mapa real:

  - cores erradas, porque so a cor da CAMADA era lida. Entidades pintadas a
    mao, cores RGB de 24 bits e pecas de bloco saiam todas com a cor da camada.
    Num mapa geologico isso troca uma litologia por outra.

  - acentos quebrados, porque o arquivo do ODA File Converter grava o texto em
    UTF-8 mas mantem ANSI_1252 no cabecalho. O GDAL obedece o cabecalho e
    'PIEZOMETROS' vira 'PIEZAMETROS'.
"""
import os, re, sys, shutil, warnings
import xml.etree.ElementTree as ET
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fiona
from fiona.crs import CRS
from conversor import convert, dxf_estilo

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida", "estilo")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE)
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


def molde():
    """Um DXF minimo valido, para receber as entidades de teste."""
    caminho = os.path.join(BASE, "_molde.dxf")
    if not os.path.exists(caminho):
        origem = os.path.join(BASE, "_m.gpkg")
        with fiona.open(origem, "w", driver="GPKG", layer="u",
                        crs=CRS.from_epsg(31982),
                        schema={"geometry": "LineString", "properties": {"a": "str"}}) as c:
            c.write({"type": "Feature", "properties": {"a": "x"},
                     "geometry": {"type": "LineString",
                                  "coordinates": [(412000.0, 6712000.0),
                                                  (412010.0, 6712010.0)]}})
        convert.qgis_para_cad([{"caminho": origem, "camada": "u"}], caminho, 31982,
                              registrar=lambda *_: None)
    return open(caminho, encoding="utf-8").read()


def montar(nome, entidades, camadas=(), codificacao="utf-8"):
    corpo = molde()
    if camadas:
        registros = ""
        for i, (camada, aci) in enumerate(camadas):
            registros += ("  0\nLAYER\n  5\n%X\n100\nAcDbSymbolTableRecord\n"
                          "100\nAcDbLayerTableRecord\n  2\n%s\n 70\n     0\n"
                          " 62\n%6d\n  6\nContinuous\n" % (0xE50000 + i, camada, aci))
        marca = corpo.index("  0\nENDTAB", corpo.index("\nLAYER\n"))
        corpo = corpo[:marca] + registros + corpo[marca:]
    marca = corpo.index("  0\nENDSEC", corpo.index("\nENTITIES\n"))
    corpo = corpo[:marca] + entidades + corpo[marca:]
    caminho = os.path.join(BASE, nome)
    open(caminho, "wb").write(corpo.encode(codificacao, "replace"))
    return caminho


def linha(handle, camada, cor, x, extra=""):
    grupo = "" if cor is None else " 62\n%6d\n" % cor
    return ("  0\nLINE\n  5\n%X\n100\nAcDbEntity\n  8\n%s\n%s%s100\nAcDbLine\n"
            " 10\n%g\n 20\n0\n 30\n0\n 11\n%g\n 21\n10\n 31\n0\n"
            % (handle, camada, grupo, extra, x, x + 5))


def texto(handle, camada, cor, y, conteudo, altura=2.5):
    return ("  0\nTEXT\n  5\n%X\n100\nAcDbEntity\n  8\n%s\n 62\n%6d\n100\nAcDbText\n"
            " 10\n0\n 20\n%g\n 30\n0\n 40\n%g\n  1\n%s\n 50\n0\n100\nAcDbText\n"
            % (handle, camada, cor, y, altura, conteudo))


def cores_do_dado(gpkg, camada):
    with fiona.open(gpkg, layer=camada) as c:
        return [f["properties"][convert.CAMPO_COR] for f in c]


# ---------------------------------------------------------------------------
print("=== 1) PALETA ACI: a nossa tabela e a do GDAL ===")
# Uma tentativa anterior gerou a paleta por formula e errou 223 dos 255
# indices. Aqui ela e conferida contra o proprio GDAL, entidade por entidade:
# cada linha e desenhada com um indice e relida com a cor que o GDAL resolveu.
ents = "".join(linha(0xE10000 + aci, "0", aci, aci) for aci in range(1, 256))
dxf = montar("paleta.dxf", ents)
gpkg = os.path.join(BASE, "paleta.gpkg")
convert.cad_para_qgis(dxf, gpkg, 31982, formato="GPKG", separar_por_camada=False,
                      gerar_projeto=False, registrar=lambda *_: None)
with fiona.open(gpkg, layer="LineString") as c:
    pelo_gdal = {}
    for f in c:
        h = f["properties"]["EntityHandle"] or ""
        if h.upper().startswith("E1"):
            pelo_gdal[int(h, 16) - 0xE10000] = f["properties"][convert.CAMPO_COR]
divergentes = [(aci, dxf_estilo.para_hex(dxf_estilo.aci_para_rgb(aci)), pelo_gdal[aci])
               for aci in sorted(pelo_gdal)
               if dxf_estilo.para_hex(dxf_estilo.aci_para_rgb(aci)) != pelo_gdal[aci]]
checar("os 255 indices foram lidos", len(pelo_gdal) == 255, "-> %d" % len(pelo_gdal))
checar("nossa tabela bate com a do GDAL em todos", not divergentes,
       "" if not divergentes else "-> %d divergem: %s" % (len(divergentes), divergentes[:3]))

# ---------------------------------------------------------------------------
print("\n=== 2) COR POR ENTIDADE, NAO POR CAMADA ===")
ents = (linha(0xE20001, "misto", None, 0)            # ByLayer -> cor da camada (verde)
        + linha(0xE20002, "misto", 256, 10)          # ByLayer explicito
        + linha(0xE20003, "misto", 1, 20)            # vermelho, pintado a mao
        + linha(0xE20004, "misto", 163, 30)          # ACI fora dos basicos
        + linha(0xE20005, "misto", None, 40, extra="420\n%d\n" % 0x8A2BE2))  # RGB 24 bits
dxf = montar("entidades.dxf", ents, camadas=[("misto", 3)])
gpkg = os.path.join(BASE, "entidades.gpkg")
convert.cad_para_qgis(dxf, gpkg, 31982, formato="GPKG", gerar_projeto=False,
                      registrar=lambda *_: None)
obtidas = cores_do_dado(gpkg, "misto_LineString")
esperadas = ["#00ff00", "#00ff00", "#ff0000", "#5267a5", "#8a2be2"]
checar("ByLayer herda a cor da camada", obtidas[:2] == esperadas[:2], "-> %s" % obtidas[:2])
checar("cor propria da entidade e respeitada", obtidas[2] == esperadas[2], "-> %s" % obtidas[2])
checar("indice fora dos basicos (ACI 163)", obtidas[3] == esperadas[3], "-> %s" % obtidas[3])
checar("cor verdadeira de 24 bits", obtidas[4] == esperadas[4], "-> %s" % obtidas[4])

# ---------------------------------------------------------------------------
print("\n=== 3) PECAS DE BLOCO MANTEM SUAS CORES ===")
bloco = ("  0\nBLOCK\n  5\nE30000\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockBegin\n"
         "  2\nSIMB\n 70\n     0\n 10\n0\n 20\n0\n 30\n0\n  3\nSIMB\n  1\n\n"
         "  0\nLINE\n  5\nE30001\n100\nAcDbEntity\n  8\n0\n 62\n     0\n100\nAcDbLine\n"
         " 10\n0\n 20\n0\n 30\n0\n 11\n5\n 21\n0\n 31\n0\n"
         "  0\nLINE\n  5\nE30002\n100\nAcDbEntity\n  8\n0\n 62\n     1\n100\nAcDbLine\n"
         " 10\n5\n 20\n0\n 30\n0\n 11\n3\n 21\n2\n 31\n0\n"
         "  0\nENDBLK\n  5\nE30003\n100\nAcDbEntity\n  8\n0\n100\nAcDbBlockEnd\n")
ents = ("  0\nINSERT\n  5\nE30010\n100\nAcDbEntity\n  8\nsimb\n 62\n     3\n"
        "100\nAcDbBlockReference\n  2\nSIMB\n 10\n0\n 20\n0\n 30\n0\n")
corpo = molde()
marca = corpo.index("  0\nENDSEC", corpo.index("\nBLOCKS\n"))
corpo = corpo[:marca] + bloco + corpo[marca:]
marca = corpo.index("  0\nENDSEC", corpo.index("\nENTITIES\n"))
corpo = corpo[:marca] + ents + corpo[marca:]
dxf = os.path.join(BASE, "blocos.dxf")
open(dxf, "w", encoding="utf-8").write(corpo)
gpkg = os.path.join(BASE, "blocos.gpkg")
convert.cad_para_qgis(dxf, gpkg, 31982, formato="GPKG", gerar_projeto=False,
                      registrar=lambda *_: None)
obtidas = sorted(set(cores_do_dado(gpkg, "simb_LineString")))
checar("a peca ByBlock herda a cor do INSERT (verde)", "#00ff00" in obtidas, "-> %s" % obtidas)
checar("a peca com cor propria continua vermelha", "#ff0000" in obtidas, "-> %s" % obtidas)

# ---------------------------------------------------------------------------
print("\n=== 4) ACENTOS: UTF-8 com cabecalho ANSI (o que o ODA produz) ===")
LINHAS = ["CONVENÇÕES", "PIEZÔMETROS", "Geográfica",
          "COTA ALTIMÉTRICA", "NÍVEL FREÁTICO", "45° ± 2°"]
for rotulo, codificacao in [("UTF-8 (ODA)", "utf-8"), ("ANSI (AutoCAD)", "cp1252")]:
    ents = "".join(texto(0xE40000 + i, "txt", 7, i * 10, t)
                   for i, t in enumerate(LINHAS))
    dxf = montar("acentos_%s.dxf" % codificacao, ents, camadas=[("txt", 7)],
                 codificacao=codificacao)
    detectado = dxf_estilo.detectar_codificacao(dxf)
    gpkg = os.path.join(BASE, "acentos_%s.gpkg" % codificacao)
    convert.cad_para_qgis(dxf, gpkg, 31982, formato="GPKG", gerar_projeto=False,
                          registrar=lambda *_: None)
    with fiona.open(gpkg, layer="txt_Texto") as c:
        lidos = [f["properties"]["Text"] for f in c]
    checar("%s -> codificacao detectada" % rotulo, detectado[0] == codificacao.replace("cp1252", "cp1252"),
           "-> %s" % (detectado,))
    checar("%s -> acentos intactos" % rotulo, lidos == LINHAS,
           "" if lidos == LINHAS else "-> %r" % lidos[:2])

# ---------------------------------------------------------------------------
print("\n=== 5) PROJETO: renderizador por cor e textos separados ===")
ents = (linha(0xE60001, "misto", 1, 0) + linha(0xE60002, "misto", 3, 10)
        + linha(0xE60003, "misto", 5, 20)
        + texto(0xE60010, "misto", 1, 40, "Título", altura=6.0)
        + texto(0xE60011, "misto", 7, 50, "corpo", altura=6.0))
dxf = montar("projeto.dxf", ents, camadas=[("misto", 7)])
gpkg = os.path.join(BASE, "projeto.gpkg")
res = convert.cad_para_qgis(dxf, gpkg, 31982, formato="GPKG",
                            registrar=lambda *_: None)
raiz = ET.parse(res["projeto"]).getroot()
camadas = {ml.findtext("layername"): ml for ml in raiz.iter("maplayer")}
checar("textos foram para camada propria", "misto_Texto" in camadas, "-> %s" % sorted(camadas))

linhas_ml = camadas["misto_LineString"]
rend = linhas_ml.find(".//renderer-v2")
categorias = {c.get("value") for c in rend.iter("category")}
checar("linhas usam renderizador categorizado", rend.get("type") == "categorizedSymbol",
       "-> %s" % rend.get("type"))
checar("categorizado pelo campo da cor", rend.get("attr") == convert.CAMPO_COR)
checar("uma categoria por cor do desenho",
       categorias == {"#ff0000", "#00ff00", "#0000ff"}, "-> %s" % sorted(categorias))

texto_ml = camadas["misto_Texto"]
checar("camada de texto nao desenha simbolo",
       texto_ml.find(".//renderer-v2").get("type") == "nullSymbol")
ts = texto_ml.find(".//labeling/settings/text-style")
checar("rotulo pelo campo Text", ts.get("fieldName") == "Text")
dd = texto_ml.find(".//labeling/settings/dd_properties")
por_nome = {}
for opt in dd.iter("Option"):
    if opt.get("type") == "Map" and opt.get("name") not in (None, "properties"):
        campo = [o.get("value") for o in opt if o.get("name") in ("field", "expression")]
        por_nome[opt.get("name")] = campo[0] if campo else None
checar("tamanho do rotulo vem de cada texto", por_nome.get("Size") == "txt_tam",
       "-> %s" % por_nome.get("Size"))
with fiona.open(gpkg, layer="misto_Texto") as c:
    tamanhos = sorted({round(f["properties"]["txt_tam"], 3) for f in c})
checar("tamanho = altura do CAD / altura da maiuscula da Arial",
       tamanhos == [round(6.0 / 0.7167, 3)], "-> %s" % tamanhos)
checar("posicao e alinhamento vem de cada texto",
       por_nome.get("PositionX") == "$x" and por_nome.get("Hali") == "txt_h"
       and por_nome.get("Vali") == "txt_v", "-> %s" % por_nome)
campos_dd = [o.get("value") for o in dd.iter("Option") if o.get("name") == "field"]
checar("cor do rotulo vem do campo, nao fixa", convert.CAMPO_COR in campos_dd,
       "-> %s" % campos_dd)

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
