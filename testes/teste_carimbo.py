# -*- coding: utf-8 -*-
"""
Carimbo com textos alinhados, hachuras e imagem: confere o que vai para o
arquivo e para o projeto, sem precisar do QGIS instalado.

Para conferir onde o QGIS realmente desenha cada texto, ver
verificar_textos_no_qgis.py (precisa do QGIS).
"""
import json
import math
import os
import shutil
import sys
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
sys.path.insert(0, AQUI)

import fiona

import gerar_carimbo
from conversor import convert, textos_cad

BASE = os.path.join(AQUI, "_saida", "carimbo")
shutil.rmtree(BASE, ignore_errors=True)
ok = fail = 0


def checar(nome, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]   %s %s" % (nome, extra))
    else:
        fail += 1
        print("  [FALHA] %s %s" % (nome, extra))


dxf, esperado = gerar_carimbo.gerar(BASE)
json.dump(esperado, open(os.path.join(BASE, "esperado.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
log = []
saida = os.path.join(BASE, "saida", "c.gpkg")
res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
camadas = fiona.listlayers(saida)

# ---------------------------------------------------------------------------
print("=== TEXTOS: ancoragem, alinhamento, tamanho e rotacao ===")
textos = {}
por_mtext = {}         # cada linha de um MTEXT e uma feicao, todas com o mesmo handle
for camada in camadas:
    if camada.endswith("_Texto"):
        with fiona.open(saida, layer=camada) as c:
            for f in c:
                textos[f["properties"]["Text"]] = f
                if "MText" in (f["properties"]["SubClasses"] or ""):
                    por_mtext.setdefault(f["properties"]["EntityHandle"], []).append(f)
DESCIDA, PASSO = 0.2778, 5.0 / 3.0
for conteudo, dados in esperado.items():
    ax, ay, hali, vali, altura, angulo = dados[:6]
    largura_quadro = dados[6] if len(dados) > 6 else 0.0
    nome = conteudo.replace("\n", " / ")[:30]
    if len(dados) > 6:
        # MTEXT: as linhas, juntas, tem de dar o texto (quebrado ou nao)
        grupo = next((g for g in por_mtext.values() if " ".join(
            f["properties"]["Text"] for f in g) == conteudo.replace("\n", " ")), None)
        checar("'%s' convertido, uma feicao por linha" % nome, grupo is not None)
        if grupo is None:
            continue
        # linha de base de cada linha pela regra do AutoCAD, calculada aqui:
        # a caixa vai do topo da maiuscula da primeira linha ate 0,2778 da
        # altura abaixo da base da ultima; as linhas a 5/3 da altura
        n = len(grupo)
        primeira = {"Top": ay - altura,
                    "Bottom": ay + DESCIDA * altura + (n - 1) * PASSO * altura,
                    "Half": ay + (altura + (n - 1) * PASSO * altura + DESCIDA * altura) / 2
                    - altura}[vali]
        erro = max(abs(f["geometry"]["coordinates"][1] - (primeira - k * PASSO * altura))
                   + abs(f["geometry"]["coordinates"][0] - ax) for k, f in enumerate(grupo))
        checar("'%s' cada linha na sua linha de base (%s)" % (nome, vali), erro < 1e-3,
               "-> erro %.4f m" % erro)
        checar("'%s' alinhamento %s, pela base" % (nome, hali),
               all((f["properties"]["txt_h"], f["properties"]["txt_v"]) == (hali, "Base")
                   for f in grupo))
        checar("'%s' tamanho" % nome,
               all(abs(f["properties"]["txt_tam"] - textos_cad.tamanho_qgis(altura)) < 1e-4
                   for f in grupo))
        if largura_quadro:
            maior = max(textos_cad.largura_texto(f["properties"]["Text"], altura) for f in grupo)
            checar("'%s' quebrado na largura do quadro" % nome,
                   n > 1 and maior <= largura_quadro,
                   "-> %d linhas, a maior com %.1f de %.0f" % (n, maior, largura_quadro))
        continue
    f = textos.get(conteudo)
    if f is None:
        checar("'%s' convertido" % nome, False, "-> nao encontrado")
        continue
    p = f["properties"]
    x, y = f["geometry"]["coordinates"][:2]
    # O ponto gravado e onde o QGIS precisa ancorar para o texto cair onde o
    # AutoCAD o desenha: a ancora do CAD mais a correcao vertical (o QGIS mede
    # "topo" e "meio" pela caixa da fonte, o AutoCAD pela maiuscula).
    # 1 mm de tolerancia: para texto justificado o GDAL escreve o deslocamento
    # ate o ponto de alinhamento com 6 algarismos significativos.
    ajuste = textos_cad.correcao_vertical(vali, False, altura)
    ex = ax - math.sin(math.radians(angulo)) * ajuste
    ey = ay + math.cos(math.radians(angulo)) * ajuste
    checar("'%s' ancorado no ponto certo" % nome,
           abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3,
           "-> (%.3f, %.3f) esperado (%.3f, %.3f)" % (x - 412000, y - 6711000,
                                                      ex - 412000, ey - 6711000))
    checar("'%s' alinhamento %s/%s" % (nome, hali, vali),
           (p["txt_h"], p["txt_v"]) == (hali, vali),
           "-> %s/%s" % (p["txt_h"], p["txt_v"]))
    checar("'%s' tamanho" % nome,
           abs(p["txt_tam"] - textos_cad.tamanho_qgis(altura)) < 1e-4,
           "-> %.3f" % p["txt_tam"])
    if angulo:
        checar("'%s' rotacao" % nome, abs(p["txt_ang"] - angulo) < 1e-6,
               "-> %s" % p["txt_ang"])

# o caso que mandava o texto para a origem do desenho
area = textos.get("Prancha")
checar("texto alinhado a esquerda nao voa para (0, 0)",
       area is not None and area["geometry"]["coordinates"][0] > 400000)

# ---------------------------------------------------------------------------
print("\n=== HACHURAS ===")
checar("hachuras em camadas proprias",
       {"Logo_Hachura", "Fundo_Hachura"} <= set(camadas), "-> %s" % camadas)
with fiona.open(saida, layer="Logo_Hachura") as c:
    logo = [f["properties"] for f in c]
with fiona.open(saida, layer="Fundo_Hachura") as c:
    fundo = [f["properties"] for f in c]
checar("logotipo: duas hachuras solidas",
       [p["hachura"] for p in logo] == ["SOLID", "SOLID"])
checar("logotipo: cores da cabeca e do cabo",
       sorted(p["cor_cad"] for p in logo) == ["#a57c52", "#ff0000"],
       "-> %s" % sorted(p["cor_cad"] for p in logo))
checar("hachura com padrao identificada", [p["hachura"] for p in fundo] == ["ANSI31"])
checar("nome do padrao nao vira texto do desenho",
       all(not p["Text"] for p in logo + fundo))

# ---------------------------------------------------------------------------
print("\n=== IMAGEM ===")
pasta_img = os.path.join(BASE, "saida", "c_imagens")
checar("imagem copiada para junto dos dados",
       os.path.isfile(os.path.join(pasta_img, "logo_teste.png")))
mundo = [float(v) for v in open(os.path.join(pasta_img, "logo_teste.pgw"))]
# pixel de 0,5 m; canto inferior esquerdo em (310, 110); 60 x 20 pixels
checar("arquivo de mundo correto",
       [round(v, 6) for v in mundo] == [0.5, 0.0, 0.0, -0.5, 412310.25, 6711119.75],
       "-> %s" % mundo)
aux = open(os.path.join(pasta_img, "logo_teste.png.aux.xml"), encoding="utf-8").read()
checar("sistema de coordenadas ao lado da imagem",
       "<SRS" in aux and "SIRGAS 2000" in aux and "UTM zone 22S" in aux)
checar("imagem faltante avisada no log",
       any("NAO encontrada" in m and "foto_que_nao_existe.jpg" in m for m in log))
checar("uma imagem incluida", res["imagens"] == 1, "-> %d" % res["imagens"])

# ---------------------------------------------------------------------------
print("\n=== PROJETO: ordem de desenho ===")
raiz = ET.parse(res["projeto"]).getroot()
ordem = [e.get("name") for e in raiz.iter("layer-tree-layer")]
print("  painel do QGIS, de cima para baixo:", ordem)
posicao = {nome: i for i, nome in enumerate(ordem)}
checar("textos por cima de tudo",
       max(posicao[n] for n in ordem if n.endswith("_Texto"))
       < min(posicao[n] for n in ordem if not n.endswith("_Texto")))
checar("hachuras por baixo das linhas",
       min(posicao[n] for n in ordem if n.endswith("_Hachura"))
       > max(posicao[n] for n in ordem if n.endswith("_LineString")))
checar("imagem por ultimo", ordem[-1].startswith("Imagem_"), "-> %s" % ordem[-1])
provedores = {e.get("name"): e.get("providerKey") for e in raiz.iter("layer-tree-layer")}
checar("imagem aberta pelo provedor de raster",
       provedores.get("Imagem_logo_teste") == "gdal")
fonte = [m.findtext("datasource") for m in raiz.iter("maplayer")
         if m.get("type") == "raster"]
checar("imagem com caminho relativo ao projeto", fonte == ["./c_imagens/logo_teste.png"],
       "-> %s" % fonte)

# ---------------------------------------------------------------------------
print("\n=== SEM IMAGENS ===")
saida2 = os.path.join(BASE, "saida2", "c.gpkg")
res2 = convert.cad_para_qgis(dxf, saida2, 31982, incluir_imagens=False,
                             registrar=lambda *_: None)
raiz2 = ET.parse(res2["projeto"]).getroot()
checar("opcao desligada deixa as imagens de fora",
       res2["imagens"] == 0 and not any(m.get("type") == "raster"
                                        for m in raiz2.iter("maplayer"))
       and not os.path.exists(os.path.join(BASE, "saida2", "c_imagens")))

print("\n%d passaram, %d falharam" % (ok, fail))
sys.exit(1 if fail else 0)
