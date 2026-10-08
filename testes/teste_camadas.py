# -*- coding: utf-8 -*-
"""
Camadas escondidas, espaco de papel, estilo de ponto e letra comprimida --
sem precisar do QGIS. Para o que o QGIS desenha, ver verificar_camadas_no_qgis.py.
"""
import json
import os
import re
import shutil
import sys
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
sys.path.insert(0, AQUI)

import fiona

import gerar_camadas
from conversor import convert, textos_cad

BASE = os.path.join(AQUI, "_saida", "camadas")
shutil.rmtree(BASE, ignore_errors=True)
X0, Y0 = gerar_camadas.X0, gerar_camadas.Y0
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


dxf, esperado = gerar_camadas.gerar(BASE)
json.dump(esperado, open(os.path.join(BASE, "esperado.json"), "w"))
saida = os.path.join(BASE, "saida", "c.gpkg")
log = []
res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
camadas = fiona.listlayers(saida)
raiz = ET.parse(res["projeto"]).getroot()
marcada = {n.get("name"): n.get("checked") == "Qt::Checked" for n in raiz.iter("layer-tree-layer")}


def feicoes(camada):
    with fiona.open(saida, layer=camada) as c:
        return [f for f in c]


# ---------------------------------------------------------------------------
print("=== CAMADAS DESLIGADAS E CONGELADAS ===")
for camada_cad in esperado["ocultas"]:
    delas = [c for c in camadas if c.startswith(camada_cad + "_")]
    checar("'%s': os dados vem (linha, ponto, texto, hachura)" % camada_cad,
           {c.split("_", 1)[1] for c in delas} >= {"LineString", "Point", "Texto", "Hachura"},
           "-> %s" % delas)
    checar("'%s': no QGIS, desmarcadas" % camada_cad,
           delas and all(marcada.get(c) is False for c in delas),
           "-> %s" % {c: marcada.get(c) for c in delas})
visiveis = [c for c in camadas if not c.startswith(tuple(esperado["ocultas"]))]
checar("as visiveis, marcadas", all(marcada.get(c) for c in visiveis),
       "-> %s" % {c: marcada.get(c) for c in visiveis})
checar("o log explica", any("desligadas ou congeladas" in linha for linha in log))
cor = {f["properties"]["cor_cad"] for f in feicoes("Desligada_LineString")}
checar("cor de verdade guardada (vermelho da camada), nao a transparencia",
       cor == {"#ff0000"}, "-> %s" % cor)

vista = raiz.find(".//DefaultViewExtent")
x1, y1, x2, y2 = (float(vista.get(k)) - (X0 if k[0] == "x" else Y0)
                  for k in ("xmin", "ymin", "xmax", "ymax"))
checar("abre enquadrado so no que aparece (nada a 100 km)",
       -20 < x1 and x2 < 130 and -20 < y1 and y2 < 80,
       "-> x %.0f..%.0f  y %.0f..%.0f" % (x1, x2, y1, y2))

# ---------------------------------------------------------------------------
print("\n=== ESPACO DE PAPEL (a folha da aba Layout) ===")
textos = [f["properties"]["Text"] for c in camadas if c.endswith("_Texto") for f in feicoes(c)]
checar("o carimbo da folha nao entra no desenho",
       not [t for t in textos if t in esperado["papel"]], "-> %s" % textos)
checar("o log explica", any("folha de impressao" in linha for linha in log))
so_papel = gerar_camadas.gerar_so_papel(os.path.join(BASE, "papel"))
res2 = convert.cad_para_qgis(so_papel, os.path.join(BASE, "papel", "saida", "p.gpkg"), 31982,
                             registrar=lambda *_: None)
checar("desenho feito so no espaco de papel: a folha e o desenho", res2["feicoes"] >= 2,
       "-> %d feicoes" % res2["feicoes"])

# ---------------------------------------------------------------------------
print("\n=== ESTILO DE PONTO ($PDMODE 34, $PDSIZE 2) ===")
ml = [m for m in raiz.iter("maplayer") if m.findtext("layername") == "Pontos_Point"]
checar("camada de pontos no projeto", len(ml) == 1)
if ml:
    marcadores = []
    for camada in ml[0].iter("layer"):
        props = {p.get("k"): p.get("v") for p in camada.iter("prop")}
        if props.get("name"):
            marcadores.append((props["name"], float(props["size"]), props["size_unit"]))
    s = esperado["pdsize"]
    checar("circulo de diametro PDSIZE e cruz com o dobro, em unidades do desenho",
           sorted(set(marcadores)) == [("circle", s, "MapUnit"), ("cross", 2 * s, "MapUnit")],
           "-> %s" % sorted(set(marcadores)))
    checar("na cor do desenho", '"0,0,255,255"' in ET.tostring(ml[0]).decode().replace("'", '"'))

# ---------------------------------------------------------------------------
print("\n=== LETRA COMPRIMIDA ===")
rot = esperado["rotulo"]
por_texto = {f["properties"]["Text"]: f for f in feicoes("Carimbo_Texto")}
f = por_texto.get(rot["texto"])
checar("rotulo comprimido convertido", f is not None)
if f:
    fator = f["properties"]["txt_tam"] / textos_cad.tamanho_qgis(rot["altura"])
    # 57% no AutoCAD, com a folga de 15%: a letra sai a 66% da altura
    checar("encolhido ate 15%% alem da largura do AutoCAD (%.0f%%)"
           % (100 * convert.FOLGA_LARGURA * rot["fator"]),
           abs(fator - convert.FOLGA_LARGURA * rot["fator"]) < 0.01, "-> %.3f" % fator)
    fim_rotulo = (f["geometry"]["coordinates"][0] - X0
                  + textos_cad.largura_texto(rot["texto"], rot["altura"] * fator))
    valor = por_texto[rot["valor"]]["geometry"]["coordinates"][0] - X0
    checar("acaba antes do valor ao lado (na largura normal, ia por cima)",
           fim_rotulo < valor, "-> rotulo ate x=%.1f, valor em x=%.1f" % (fim_rotulo, valor))
tit = esperado["titulo"]
f = por_texto.get(tit["texto"])
checar("titulo em Verdana a 85%: nao encolhe (ja e da largura da Arial)",
       f is not None and f["properties"]["txt_tam"] / textos_cad.tamanho_qgis(tit["altura"]) > 0.97,
       "-> %.3f" % (f["properties"]["txt_tam"] / textos_cad.tamanho_qgis(tit["altura"]) if f else 0))

# ---------------------------------------------------------------------------
print("\n=== LINHAS SOBREPOSTAS: a de cima no AutoCAD por cima no QGIS ===")
arvore = [n.get("name") for n in raiz.iter("layer-tree-layer")]
for caso in esperado["sobrepostas"]:
    cima, baixo = caso["cima"], caso["baixo"]
    checar("%s acima de %s (%s)" % (cima, baixo, caso["como"]),
           cima in arvore and baixo in arvore and arvore.index(cima) < arvore.index(baixo),
           "-> %s" % [n for n in arvore if n.endswith("_LineString")])

# ---------------------------------------------------------------------------
print("\n=== FONTE DE TRACO (simplex) E TEXTO COM VAO PARA ATRIBUTO ===")
from conversor import dxf_estilo
q = esperado["quadro"]
# o AutoCAD grava onde comeca o texto alinhado pela direita/centro: "RS " deu
# 62 unidades no LOTEAMENTO (romans, maiuscula = 21)
checar("largura da romans: 'RS ' = 62 unidades (espaco de 21)",
       abs(textos_cad.largura_shx("RS ", 21, "romans") - 62) < 1e-9,
       "-> %g" % textos_cad.largura_shx("RS ", 21, "romans"))
checar("letra acentuada mede como a letra sem acento",
       textos_cad.largura_shx("ÁREA", 21, "simplex") == textos_cad.largura_shx("AREA", 21, "simplex"))
checar("simplex, ROMANS.shx e romans__.ttf tem tabela; txt nao",
       [textos_cad.fonte_de_traco(n) for n in ("simplex", "ROMANS.shx", "romans__.ttf", "txt")]
       == ["simplex", "romans", "romans", None])
checar("%%d, %%p e \\U+00B0 lidos como o GDAL le",
       dxf_estilo._decodificar_texto("45%%d %%p1 \\U+00B0") == "45° ±1 °")

quadro = feicoes("Quadro_Texto")
por_texto = {f["properties"]["Text"]: f for f in quadro}
indice = dxf_estilo.fontes_dos_textos(dxf)
f_antes = por_texto.get(q["antes"])
checar("o GDAL diz Arial, mas o estilo do texto do bloco e simplex (pelo handle do INSERT)",
       f_antes is not None and (indice.achar(f_antes["properties"]["EntityHandle"],
                                             "MERIDIANO CENTRAL    ° WGr") or {}).get("arquivo") == "simplex")
f_valor = por_texto.get(q["valor"])
checar("e o do atributo tambem (pelo handle dele)",
       f_valor is not None and (indice.achar(f_valor["properties"]["EntityHandle"], "45")
                                or {}).get("arquivo") == "simplex")
checar("o texto e dividido no vao de quatro espacos",
       q["antes"] in por_texto and q["depois"] in por_texto
       and not [t for t in por_texto if "    " in t], "-> %s" % sorted(por_texto))


def extensao(f):
    """Onde a tinta do rotulo comeca e termina no QGIS (x, sem o X0)."""
    pr = f["properties"]
    x = f["geometry"]["coordinates"][0] - X0
    w = textos_cad.largura_texto(pr["Text"], pr["txt_tam"] * textos_cad.CAP_ARIAL)
    return {"Left": (x, x + w), "Center": (x - w / 2, x + w / 2), "Right": (x - w, x)}[pr["txt_h"]]


inicio = q["insercao"][0]
if f_antes and f_valor and q["depois"] in por_texto:
    no_cad = textos_cad.largura_shx(q["recuo"], q["altura"], "simplex") * q["fator"]
    x_depois = extensao(por_texto[q["depois"]])[0]
    checar("o '%s' comeca onde comeca no AutoCAD" % q["depois"],
           abs(x_depois - (inicio + no_cad)) < 1e-3,
           "-> x=%.3f, no AutoCAD %.3f" % (x_depois, inicio + no_cad))
    fim, (v0, v1) = extensao(f_antes)[1], extensao(f_valor)
    checar("'%s' termina antes do 45 (na Arial passava por cima)" % q["antes"], fim < v0,
           "-> termina em %.2f, o 45 vai de %.2f a %.2f" % (fim, v0, v1))
    checar("o 45 termina antes do '%s'" % q["depois"], v1 < x_depois,
           "-> %.2f < %.2f" % (v1, x_depois))
    # como era: largura do AutoCAD medida na Arial e 15% de folga
    tam_antigo = textos_cad.tamanho_qgis(q["altura"] * convert.FOLGA_LARGURA * q["fator"])
    checar("(o caso testa algo: no tamanho de antes o CENTRAL ia ate o 45)",
           inicio + textos_cad.largura_texto(q["antes"], tam_antigo * textos_cad.CAP_ARIAL) > v0)
if q["primeira"] in por_texto:
    borda = inicio + q["borda"] * q["escala"]
    fim = extensao(por_texto[q["primeira"]])[1]
    checar("a primeira linha termina antes da borda do quadro", fim < borda,
           "-> %.2f < %.2f" % (fim, borda))
tamanhos = {round(f["properties"]["txt_tam"], 6) for f in quadro}
checar("todas as linhas do quadro com a mesma letra, como no AutoCAD", len(tamanhos) == 1,
       "-> %s" % sorted(tamanhos))

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
