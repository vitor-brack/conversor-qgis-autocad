# -*- coding: utf-8 -*-
"""
Texturas de hachura, logo formatado e altura dos textos -- sem precisar do QGIS.

Para conferir o que o QGIS realmente desenha, ver verificar_texturas_no_qgis.py.
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

import gerar_texturas
from conversor import convert, textos_cad

BASE = os.path.join(AQUI, "_saida", "texturas")
shutil.rmtree(BASE, ignore_errors=True)
X0, Y0 = gerar_texturas.X0, gerar_texturas.Y0
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


dxf, esperado = gerar_texturas.gerar(BASE)
json.dump(esperado, open(os.path.join(BASE, "esperado.json"), "w"))
saida = os.path.join(BASE, "saida", "plot.gpkg")
log = []
res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
camadas = fiona.listlayers(saida)


def feicoes(camada):
    with fiona.open(saida, layer=camada) as c:
        return [f for f in c]


def pontos(geom):
    for linha in geom["coordinates"]:
        for x, y in (ponto[:2] for ponto in linha):
            yield x - X0, y - Y0


# ---------------------------------------------------------------------------
print("=== PERFIL: cruzes abaixo do terreno ===")
checar("camada de textura do perfil", "Perfil_Textura" in camadas, "-> %s" % camadas)
perfil = feicoes("Perfil_Textura")
checar("uma feicao por hachura", len(perfil) == 1)
p = perfil[0]["properties"]
checar("cor e padrao do desenho", (p["cor_cad"], p["hachura"]) == ("#000000", "CROSS"),
       "-> %s %s" % (p["cor_cad"], p["hachura"]))
xs, ys = zip(*pontos(perfil[0]["geometry"]))
checar("linhas dentro da borda", min(xs) >= -0.01 and max(xs) <= 180.01
       and min(ys) >= -0.01 and max(ys) <= 45.5,
       "-> x %.1f..%.1f  y %.1f..%.1f" % (min(xs), max(xs), min(ys), max(ys)))
checar("muitas cruzes (padrao desenhado de verdade)",
       len(perfil[0]["geometry"]["coordinates"]) > 200,
       "-> %d tracos" % len(perfil[0]["geometry"]["coordinates"]))
# a borda da hachura (que o GDAL devolvia como linha solta) nao entra no desenho
linhas_perfil = feicoes("Perfil_LineString")
checar("so a curva do terreno como linha (a borda da hachura nao duplica)",
       len(linhas_perfil) == 1, "-> %d linhas" % len(linhas_perfil))

# ---------------------------------------------------------------------------
print("\n=== LEGENDA: cada amostra com o seu padrao e a sua cor ===")
legenda = feicoes("Legenda_Textura")
por_cor = {f["properties"]["cor_cad"]: f for f in legenda}
for cor, (padrao, caixa) in zip(("#0000ff", "#ff7f00", "#00a5a5"),
                                zip(("DASH", "GRAVEL", "ANSI31"),
                                    [c for _, c in esperado["legenda"]])):
    f = por_cor.get(cor)
    checar("amostra %s" % padrao, f is not None and f["properties"]["hachura"] == padrao,
           "-> %s" % (f["properties"]["hachura"] if f else "ausente"))
    if f:
        xs, ys = zip(*pontos(f["geometry"]))
        checar("  %s dentro do quadrado" % padrao,
               min(xs) >= caixa[0] - 1.01 and max(xs) <= caixa[2] + 1.01
               and min(ys) >= caixa[1] - 1.01 and max(ys) <= caixa[3] + 1.01)

# bloco espelhado: sem as copias fantasmas do ezdxf, tudo em x 262..270
espelhado = por_cor.get("#ff0000")
checar("hachura de bloco espelhado convertida", espelhado is not None)
if espelhado:
    xs, ys = zip(*pontos(espelhado["geometry"]))
    checar("  sem copias espelhadas fora do lugar",
           min(xs) >= 261.99 and max(xs) <= 270.01 and min(ys) >= 9.99 and max(ys) <= 18.01,
           "-> x %.2f..%.2f" % (min(xs), max(xs)))

# ---------------------------------------------------------------------------
print("\n=== LOGO ===")
logo = feicoes("Logo_Texto")[0]
props = logo["properties"]
checar("texto puro preservado", props["Text"] == "Geosana", "-> %r" % props["Text"])
html = props["txt_html"]
checar("'Geo' em azul", 'color:#0000ff' in html and ">Geo<" in html)
checar("'sana' em verde", 'color:#00ff00' in html and ">sana<" in html)
checar("fonte e negrito do desenho",
       "Arial Rounded MT Bold" in html and "font-weight:bold" in html)
y = logo["geometry"]["coordinates"][1] - Y0
checar("apoiado na linha de base: uma altura abaixo da ancora (o topo da maiuscula)",
       abs(y - (118.0 - 10.0)) < 1e-6 and props["txt_v"] == "Base",
       "-> y %.3f, %s (ancora 118)" % (y, props["txt_v"]))

raiz = ET.parse(res["projeto"]).getroot()
estilos = {}
for ml in raiz.iter("maplayer"):
    ts = ml.find(".//labeling/settings/text-style")
    if ts is not None:
        tf = ml.find(".//labeling/settings/text-format")
        estilos[ml.findtext("layername")] = (ts.get("allowHtml"), ts.get("fieldName"),
                                             tf.get("wrapChar"))
checar("logo com rotulo em HTML", estilos.get("Logo_Texto") == ("1", "txt_html", ""),
       "-> %s" % (estilos.get("Logo_Texto"),))
checar("carimbo com rotulo em HTML", estilos.get("Carimbo_Texto") == ("1", "txt_html", ""),
       "-> %s" % (estilos.get("Carimbo_Texto"),))
checar("legenda (sem formatacao) com rotulo simples",
       estilos.get("Legenda_Texto") == ("0", "Text", ""),
       "-> %s" % (estilos.get("Legenda_Texto"),))
propriedades = {o.get("name") for ml in raiz.iter("maplayer")
                if ml.findtext("layername") == "Carimbo_Texto"
                for o in ml.iter("Option") if o.get("type") == "Map" and o.get("name")}
checar("sem altura de linha por campo (o QGIS a ignora)",
       "MultiLineHeight" not in propriedades and "Vali" in propriedades,
       "-> %s" % sorted(propriedades))
checar("sem fator de largura (o QGIS encavala ou espalha as letras)",
       "FontStretchFactor" not in propriedades, "-> %s" % sorted(propriedades))
comp = esperado["comprimido"]
titulo = [f for f in feicoes("Legenda_Texto") if f["properties"]["Text"] == comp["texto"]]
checar("titulo comprimido convertido, fator guardado (85)",
       len(titulo) == 1 and abs(titulo[0]["properties"]["txt_larg"] - 85.0) < 0.01,
       "-> %s" % [f["properties"]["txt_larg"] for f in titulo])

# ---------------------------------------------------------------------------
print("\n=== CARIMBO: uma feicao por linha, na base do AutoCAD, com a fonte certa ===")
checar("camada de texto do carimbo", "Carimbo_Texto" in camadas)
# cada linha de um MTEXT e uma feicao; as de um mesmo MTEXT tem o mesmo handle
por_mtext = {}
for f in feicoes("Carimbo_Texto"):
    por_mtext.setdefault(f["properties"]["EntityHandle"], []).append(f)
achados = {"\n".join(f["properties"]["Text"] for f in grupo): grupo
           for grupo in por_mtext.values()}
BOOKMAN = "font-family:'Bookman Old Style'"
DESCIDA, PASSO = 0.2778, 5.0 / 3.0
for e in esperado["carimbo"]:
    nome = e["texto"].split("\n")[0][:32]
    grupo = achados.get(e["texto"])
    checar("'%s': as %d linha(s) do AutoCAD, nada colado" % (nome, e["linhas"]),
           grupo is not None,
           "" if grupo else "-> %r" % [t for t in achados if t[:10] == e["texto"][:10]])
    if grupo is None:
        continue
    # A linha de base de cada linha pela regra do AutoCAD, calculada aqui sem
    # o conversor: a caixa do MTEXT vai do topo da maiuscula da primeira linha
    # ate 0,2778 da altura abaixo da base da ultima, com as linhas a 5/3 da
    # altura uma da outra.
    h, n = e["altura"], e["linhas"]
    ax, ay = e["ancora"]
    primeira = {"Top": ay - h, "Bottom": ay + DESCIDA * h + (n - 1) * PASSO * h,
                "Half": ay + (h + (n - 1) * PASSO * h + DESCIDA * h) / 2 - h}[e["v"]]
    erro = max(abs(f["geometry"]["coordinates"][1] - Y0 - (primeira - k * PASSO * h))
               + abs(f["geometry"]["coordinates"][0] - X0 - ax) for k, f in enumerate(grupo))
    checar("  cada linha apoiada na sua linha de base",
           erro < 1e-6 and all(f["properties"]["txt_v"] == "Base"
                               and f["properties"]["txt_h"] == e["h"] for f in grupo),
           "-> erro %.4f m" % erro)
    htmls = [f["properties"]["txt_html"] for f in grupo]
    checar("  HTML de cada linha sem quebra e com os trechos fechados",
           all("<br" not in t and textos_cad.QUEBRA_HTML not in t
               and t.count("<span") == t.count("</span>") for t in htmls),
           "-> %r" % htmls[0][:90])
    props = grupo[0]["properties"]
    estilos_css = [s for t in htmls for s in re.findall(r'<span style="([^"]*)">', t)]
    if e["forma"] == "sem fonte":
        checar("  texto sem formatacao continua sem trechos", not estilos_css)
    elif e["forma"] == "inexistente":
        checar("  fonte que nao existe: Arial (sem font-family), negrito mantido",
               estilos_css and all("font-family" not in s and "font-weight:bold" in s
                                   for s in estilos_css), "-> %s" % estilos_css)
    else:
        checar("  fonte gravada como %s -> Bookman Old Style negrito" % e["forma"],
               estilos_css and all(BOOKMAN in s and "font-weight:bold" in s
                                   for s in estilos_css), "-> %s" % estilos_css)
    checar("  fator de largura do estilo (1,15) guardado so como informacao",
           all(f["properties"]["txt_larg"] == 115.0 for f in grupo),
           "-> %s" % props["txt_larg"])

# ---------------------------------------------------------------------------
print("\n=== PERFIL FUTURO: borda remendada, so o solo hachurado ===")


def no_poligono(x, y, poligono):
    """Par ou impar de cruzamentos: o ponto esta dentro do poligono?"""
    dentro = False
    for (x1, y1), (x2, y2) in zip(poligono, poligono[1:] + poligono[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


fut = esperado["futuro"]
checar("camada de textura do perfil futuro", fut["camada"] in camadas)
meios = [((a[0] + b[0]) / 2 - X0, (a[1] + b[1]) / 2 - Y0)
         for f in (feicoes(fut["camada"]) if fut["camada"] in camadas else [])
         for a, b in (linha[:2] for linha in f["geometry"]["coordinates"])]
solo = [tuple(v) for v in fut["solo"]]
fora = [m for m in meios if not no_poligono(m[0], m[1], solo)]
checar("padrao desenhado no solo", len(meios) > 100, "-> %d tracos" % len(meios))
checar("nenhum traco fora do solo (nem na fatia do topo, nem na escavacao)", not fora,
       "-> %d fora, ex.: %s" % (len(fora), ["(%.2f, %.2f)" % m for m in fora[:3]]))
x1, y1, x2, y2 = fut["escavacao"]
checar("escavacao em branco",
       not [m for m in meios if x1 < m[0] < x2 and y1 < m[1] < y2])

# ---------------------------------------------------------------------------
print("\n=== COTAS: pontas de seta e pontos de definicao ===")
cot = esperado["cotas"]
pintados = feicoes(cot["camada"]) if cot["camada"] in camadas else []
checar("pontas de seta e SOLID solto convertidos (pintados)",
       len(pintados) == cot["solidos"], "-> %d de %d" % (len(pintados), cot["solidos"]))
checar("na cor da cota", {f["properties"]["cor_cad"] for f in pintados} == {cot["cor"]},
       "-> %s" % {f["properties"]["cor_cad"] for f in pintados})
checar("pontos de definicao (camada Defpoints) fora do QGIS",
       not [c for c in camadas if c.lower().startswith("defpoints")], "-> %s" % camadas)
checar("e o log explica por que", any("Defpoints" in linha for linha in log))
checar("texto da cota convertido", any(f["properties"]["Text"] == "12"
                                       for f in feicoes("Cotas_Texto")))

# ---------------------------------------------------------------------------
print("\n=== MARTELO: hachuras solidas dentro de bloco ===")
martelo = sorted(f["properties"]["cor_cad"] for f in feicoes("Logo_Hachura"))
checar("cabeca cinza e cabo azul (ByBlock herda do INSERT)",
       martelo == ["#0000ff", "#545454"], "-> %s" % martelo)

# ---------------------------------------------------------------------------
print("\n=== PROJETO ===")
ordem = [e.get("name") for e in raiz.iter("layer-tree-layer")]
posicao = {n: i for i, n in enumerate(ordem)}
checar("texturas por baixo das linhas e por cima das hachuras solidas",
       max(posicao[n] for n in ordem if n.endswith("_LineString"))
       < min(posicao[n] for n in ordem if n.endswith("_Textura"))
       < min(posicao[n] for n in ordem if n.endswith("_Hachura")), "-> %s" % ordem)
larguras = set()
for ml in raiz.iter("maplayer"):
    if ml.findtext("layername", "").endswith("_Textura"):
        for prop in ml.iter("prop"):
            if prop.get("k") == "line_width":
                larguras.add(prop.get("v"))
checar("tracos finos, como na hachura do AutoCAD", larguras == {"0.13"}, "-> %s" % larguras)

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
