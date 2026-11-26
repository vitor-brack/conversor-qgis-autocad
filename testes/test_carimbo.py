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
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import fiona
import pytest

import gerar_carimbo
from conversor import convert, textos_cad

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "_saida", "carimbo")
# Regra do AutoCAD para a caixa de um MTEXT: a linha de base de cada linha fica
# a 5/3 da altura da anterior, e a caixa desce 0,2778 da altura abaixo da ultima.
DESCIDA, PASSO = 0.2778, 5.0 / 3.0


@pytest.fixture(scope="module")
def conv():
    """Gera o desenho do carimbo e o converte, como o programa faria."""
    shutil.rmtree(BASE, ignore_errors=True)
    dxf, esperado = gerar_carimbo.gerar(BASE)
    with open(os.path.join(BASE, "esperado.json"), "w", encoding="utf-8") as fp:
        json.dump(esperado, fp, ensure_ascii=False, indent=1)
    log = []
    saida = os.path.join(BASE, "saida", "c.gpkg")
    res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
    return SimpleNamespace(dxf=dxf, esperado=esperado, log=log, saida=saida, res=res,
                           camadas=convert.listar_camadas(saida))


def feicoes(arquivo, camada):
    with fiona.open(arquivo, layer=camada) as c:
        return [f for f in c]


@pytest.fixture(scope="module")
def textos(conv):
    """(textos por conteudo, linhas de cada MTEXT agrupadas pelo handle)."""
    por_texto = {}
    por_mtext = {}         # cada linha de um MTEXT e uma feicao, todas com o mesmo handle
    for camada in conv.camadas:
        if camada.endswith("_Texto"):
            for f in feicoes(conv.saida, camada):
                por_texto[f["properties"]["Text"]] = f
                if "MText" in (f["properties"]["SubClasses"] or ""):
                    por_mtext.setdefault(f["properties"]["EntityHandle"], []).append(f)
    return por_texto, por_mtext


# ---------------------------------------------------------------------------
def test_textos_ancoragem_alinhamento_tamanho_e_rotacao(conv, textos, subtests):
    por_texto, por_mtext = textos
    for conteudo, dados in conv.esperado.items():
        ax, ay, hali, vali, altura, angulo = dados[:6]
        largura_quadro = dados[6] if len(dados) > 6 else 0.0
        nome = conteudo.replace("\n", " / ")[:30]
        if len(dados) > 6:
            with subtests.test(msg=nome):
                # MTEXT: as linhas, juntas, tem de dar o texto (quebrado ou nao)
                grupo = next((g for g in por_mtext.values() if " ".join(
                    f["properties"]["Text"] for f in g) == conteudo.replace("\n", " ")), None)
                assert grupo is not None, "'%s' convertido, uma feicao por linha" % nome
                # linha de base de cada linha pela regra do AutoCAD, calculada aqui:
                # a caixa vai do topo da maiuscula da primeira linha ate 0,2778 da
                # altura abaixo da base da ultima; as linhas a 5/3 da altura
                n = len(grupo)
                primeira = {"Top": ay - altura,
                            "Bottom": ay + DESCIDA * altura + (n - 1) * PASSO * altura,
                            "Half": ay + (altura + (n - 1) * PASSO * altura
                                          + DESCIDA * altura) / 2 - altura}[vali]
                erro = max(abs(f["geometry"]["coordinates"][1] - (primeira - k * PASSO * altura))
                           + abs(f["geometry"]["coordinates"][0] - ax)
                           for k, f in enumerate(grupo))
                assert erro < 1e-3, \
                    "'%s' cada linha na sua linha de base (%s) -> erro %.4f m" % (nome, vali, erro)
                assert all((f["properties"]["txt_h"], f["properties"]["txt_v"]) == (hali, "Base")
                           for f in grupo), "'%s' alinhamento %s, pela base" % (nome, hali)
                assert all(abs(f["properties"]["txt_tam"] - textos_cad.tamanho_qgis(altura)) < 1e-4
                           for f in grupo), "'%s' tamanho" % nome
                if largura_quadro:
                    maior = max(textos_cad.largura_texto(f["properties"]["Text"], altura)
                                for f in grupo)
                    assert n > 1 and maior <= largura_quadro, \
                        "'%s' quebrado na largura do quadro -> %d linhas, a maior com %.1f de %.0f" % (
                            nome, n, maior, largura_quadro)
            continue
        with subtests.test(msg=nome):
            f = por_texto.get(conteudo)
            if f is None:
                pytest.fail("'%s' convertido -> nao encontrado" % nome)
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
            assert abs(x - ex) < 1e-3 and abs(y - ey) < 1e-3, \
                "'%s' ancorado no ponto certo -> (%.3f, %.3f) esperado (%.3f, %.3f)" % (
                    nome, x - 412000, y - 6711000, ex - 412000, ey - 6711000)
            assert (p["txt_h"], p["txt_v"]) == (hali, vali), \
                "'%s' alinhamento %s/%s -> %s/%s" % (nome, hali, vali, p["txt_h"], p["txt_v"])
            assert abs(p["txt_tam"] - textos_cad.tamanho_qgis(altura)) < 1e-4, \
                "'%s' tamanho -> %.3f" % (nome, p["txt_tam"])
            if angulo:
                assert abs(p["txt_ang"] - angulo) < 1e-6, \
                    "'%s' rotacao -> %s" % (nome, p["txt_ang"])


def test_texto_alinhado_a_esquerda_nao_voa_para_a_origem(textos):
    # o caso que mandava o texto para a origem do desenho
    area = textos[0].get("Prancha")
    assert area is not None and area["geometry"]["coordinates"][0] > 400000, \
        "texto alinhado a esquerda nao voa para (0, 0)"


# ---------------------------------------------------------------------------
def test_hachuras(conv):
    assert {"Logo_Hachura", "Fundo_Hachura"} <= set(conv.camadas), \
        "hachuras em camadas proprias -> %s" % conv.camadas
    logo = [f["properties"] for f in feicoes(conv.saida, "Logo_Hachura")]
    fundo = [f["properties"] for f in feicoes(conv.saida, "Fundo_Hachura")]
    assert [p["hachura"] for p in logo] == ["SOLID", "SOLID"], "logotipo: duas hachuras solidas"
    assert sorted(p["cor_cad"] for p in logo) == ["#a57c52", "#ff0000"], \
        "logotipo: cores da cabeca e do cabo -> %s" % sorted(p["cor_cad"] for p in logo)
    assert [p["hachura"] for p in fundo] == ["ANSI31"], "hachura com padrao identificada"
    assert all(not p["Text"] for p in logo + fundo), "nome do padrao nao vira texto do desenho"


# ---------------------------------------------------------------------------
def test_imagem(conv):
    pasta_img = os.path.join(BASE, "saida", "c_imagens")
    assert os.path.isfile(os.path.join(pasta_img, "logo_teste.png")), \
        "imagem copiada para junto dos dados"
    with open(os.path.join(pasta_img, "logo_teste.pgw")) as fp:
        mundo = [float(v) for v in fp]
    # pixel de 0,5 m; canto inferior esquerdo em (310, 110); 60 x 20 pixels
    assert [round(v, 6) for v in mundo] == [0.5, 0.0, 0.0, -0.5, 412310.25, 6711119.75], \
        "arquivo de mundo correto -> %s" % mundo
    with open(os.path.join(pasta_img, "logo_teste.png.aux.xml"), encoding="utf-8") as fp:
        aux = fp.read()
    assert "<SRS" in aux and "SIRGAS 2000" in aux and "UTM zone 22S" in aux, \
        "sistema de coordenadas ao lado da imagem"
    assert any("NAO encontrada" in m and "foto_que_nao_existe.jpg" in m for m in conv.log), \
        "imagem faltante avisada no log"
    assert conv.res["imagens"] == 1, "uma imagem incluida -> %d" % conv.res["imagens"]


# ---------------------------------------------------------------------------
def test_projeto_ordem_de_desenho(conv):
    raiz = ET.parse(conv.res["projeto"]).getroot()
    ordem = [e.get("name") for e in raiz.iter("layer-tree-layer")]   # painel do QGIS, de cima para baixo
    posicao = {nome: i for i, nome in enumerate(ordem)}
    assert (max(posicao[n] for n in ordem if n.endswith("_Texto"))
            < min(posicao[n] for n in ordem if not n.endswith("_Texto"))), \
        "textos por cima de tudo -> %s" % ordem
    assert (min(posicao[n] for n in ordem if n.endswith("_Hachura"))
            > max(posicao[n] for n in ordem if n.endswith("_LineString"))), \
        "hachuras por baixo das linhas -> %s" % ordem
    assert ordem[-1].startswith("Imagem_"), "imagem por ultimo -> %s" % ordem[-1]
    provedores = {e.get("name"): e.get("providerKey") for e in raiz.iter("layer-tree-layer")}
    assert provedores.get("Imagem_logo_teste") == "gdal", "imagem aberta pelo provedor de raster"
    fonte = [m.findtext("datasource") for m in raiz.iter("maplayer") if m.get("type") == "raster"]
    assert fonte == ["./c_imagens/logo_teste.png"], \
        "imagem com caminho relativo ao projeto -> %s" % fonte


# ---------------------------------------------------------------------------
def test_sem_imagens(conv):
    saida2 = os.path.join(BASE, "saida2", "c.gpkg")
    res2 = convert.cad_para_qgis(conv.dxf, saida2, 31982, incluir_imagens=False,
                                 registrar=lambda *_: None)
    raiz2 = ET.parse(res2["projeto"]).getroot()
    assert (res2["imagens"] == 0
            and not any(m.get("type") == "raster" for m in raiz2.iter("maplayer"))
            and not os.path.exists(os.path.join(BASE, "saida2", "c_imagens"))), \
        "opcao desligada deixa as imagens de fora"
