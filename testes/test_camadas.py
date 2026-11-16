# -*- coding: utf-8 -*-
"""
Camadas escondidas, espaco de papel, estilo de ponto e letra comprimida --
sem precisar do QGIS. Para o que o QGIS desenha, ver verificar_camadas_no_qgis.py.
"""
import json
import os
import shutil
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import fiona
import pytest

import gerar_camadas
from conversor import convert, dxf_estilo, textos_cad

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "_saida", "camadas")
X0, Y0 = gerar_camadas.X0, gerar_camadas.Y0


@pytest.fixture(scope="module")
def conv():
    """Gera o desenho com camadas escondidas e o converte, como o programa faria."""
    shutil.rmtree(BASE, ignore_errors=True)
    dxf, esperado = gerar_camadas.gerar(BASE)
    with open(os.path.join(BASE, "esperado.json"), "w") as fp:
        json.dump(esperado, fp)
    saida = os.path.join(BASE, "saida", "c.gpkg")
    log = []
    res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
    raiz = ET.parse(res["projeto"]).getroot()
    return SimpleNamespace(
        dxf=dxf, esperado=esperado, saida=saida, log=log, res=res, raiz=raiz,
        camadas=fiona.listlayers(saida),
        marcada={n.get("name"): n.get("checked") == "Qt::Checked"
                 for n in raiz.iter("layer-tree-layer")})


def feicoes(conv, camada):
    with fiona.open(conv.saida, layer=camada) as c:
        return [f for f in c]


# ---------------------------------------------------------------------------
# CAMADAS DESLIGADAS E CONGELADAS
def test_camadas_desligadas_trazem_os_dados_e_vem_desmarcadas(conv, subtests):
    for camada_cad in conv.esperado["ocultas"]:
        with subtests.test(msg=camada_cad):
            delas = [c for c in conv.camadas if c.startswith(camada_cad + "_")]
            assert {c.split("_", 1)[1] for c in delas} >= {"LineString", "Point", "Texto", "Hachura"}, \
                "'%s': os dados vem (linha, ponto, texto, hachura) -> %s" % (camada_cad, delas)
            assert delas and all(conv.marcada.get(c) is False for c in delas), \
                "'%s': no QGIS, desmarcadas -> %s" % (camada_cad, {c: conv.marcada.get(c) for c in delas})


def test_camadas_visiveis_marcadas_e_o_log_explica(conv):
    visiveis = [c for c in conv.camadas if not c.startswith(tuple(conv.esperado["ocultas"]))]
    assert all(conv.marcada.get(c) for c in visiveis), \
        "as visiveis, marcadas -> %s" % {c: conv.marcada.get(c) for c in visiveis}
    assert any("desligadas ou congeladas" in linha for linha in conv.log), "o log explica"


def test_cor_de_verdade_guardada_nas_camadas_desligadas(conv):
    cor = {f["properties"]["cor_cad"] for f in feicoes(conv, "Desligada_LineString")}
    assert cor == {"#ff0000"}, \
        "cor de verdade guardada (vermelho da camada), nao a transparencia -> %s" % cor


def test_projeto_abre_enquadrado_so_no_que_aparece(conv):
    vista = conv.raiz.find(".//DefaultViewExtent")
    x1, y1, x2, y2 = (float(vista.get(k)) - (X0 if k[0] == "x" else Y0)
                      for k in ("xmin", "ymin", "xmax", "ymax"))
    assert -20 < x1 and x2 < 130 and -20 < y1 and y2 < 80, \
        "abre enquadrado so no que aparece (nada a 100 km) -> x %.0f..%.0f  y %.0f..%.0f" % (
            x1, x2, y1, y2)


# ---------------------------------------------------------------------------
# ESPACO DE PAPEL (a folha da aba Layout)
def test_carimbo_da_folha_nao_entra_no_desenho(conv):
    textos = [f["properties"]["Text"] for c in conv.camadas if c.endswith("_Texto")
              for f in feicoes(conv, c)]
    assert not [t for t in textos if t in conv.esperado["papel"]], \
        "o carimbo da folha nao entra no desenho -> %s" % textos
    assert any("folha de impressao" in linha for linha in conv.log), "o log explica"


def test_desenho_feito_so_no_espaco_de_papel(conv):
    so_papel = gerar_camadas.gerar_so_papel(os.path.join(BASE, "papel"))
    res2 = convert.cad_para_qgis(so_papel, os.path.join(BASE, "papel", "saida", "p.gpkg"), 31982,
                                 registrar=lambda *_: None)
    assert res2["feicoes"] >= 2, \
        "desenho feito so no espaco de papel: a folha e o desenho -> %d feicoes" % res2["feicoes"]


# ---------------------------------------------------------------------------
# ESTILO DE PONTO ($PDMODE 34, $PDSIZE 2)
def test_estilo_de_ponto_pdmode_34(conv):
    ml = [m for m in conv.raiz.iter("maplayer") if m.findtext("layername") == "Pontos_Point"]
    assert len(ml) == 1, "camada de pontos no projeto"
    marcadores = []
    for camada in ml[0].iter("layer"):
        props = {p.get("k"): p.get("v") for p in camada.iter("prop")}
        if props.get("name"):
            marcadores.append((props["name"], float(props["size"]), props["size_unit"]))
    s = conv.esperado["pdsize"]
    assert sorted(set(marcadores)) == [("circle", s, "MapUnit"), ("cross", 2 * s, "MapUnit")], \
        "circulo de diametro PDSIZE e cruz com o dobro, em unidades do desenho -> %s" % sorted(
            set(marcadores))
    assert '"0,0,255,255"' in ET.tostring(ml[0]).decode().replace("'", '"'), "na cor do desenho"


# ---------------------------------------------------------------------------
# LETRA COMPRIMIDA
def test_rotulo_comprimido_encolhe_ate_caber(conv):
    rot = conv.esperado["rotulo"]
    por_texto = {f["properties"]["Text"]: f for f in feicoes(conv, "Carimbo_Texto")}
    f = por_texto.get(rot["texto"])
    assert f is not None, "rotulo comprimido convertido"
    fator = f["properties"]["txt_tam"] / textos_cad.tamanho_qgis(rot["altura"])
    # 57% no AutoCAD, com a folga de 15%: a letra sai a 66% da altura
    assert abs(fator - convert.FOLGA_LARGURA * rot["fator"]) < 0.01, \
        "encolhido ate 15%% alem da largura do AutoCAD (%.0f%%) -> %.3f" % (
            100 * convert.FOLGA_LARGURA * rot["fator"], fator)
    fim_rotulo = (f["geometry"]["coordinates"][0] - X0
                  + textos_cad.largura_texto(rot["texto"], rot["altura"] * fator))
    valor = por_texto[rot["valor"]]["geometry"]["coordinates"][0] - X0
    assert fim_rotulo < valor, \
        "acaba antes do valor ao lado (na largura normal, ia por cima) " \
        "-> rotulo ate x=%.1f, valor em x=%.1f" % (fim_rotulo, valor)


def test_titulo_em_verdana_a_85_nao_encolhe(conv):
    por_texto = {f["properties"]["Text"]: f for f in feicoes(conv, "Carimbo_Texto")}
    tit = conv.esperado["titulo"]
    f = por_texto.get(tit["texto"])
    fator = f["properties"]["txt_tam"] / textos_cad.tamanho_qgis(tit["altura"]) if f else 0
    assert f is not None and fator > 0.97, \
        "titulo em Verdana a 85%%: nao encolhe (ja e da largura da Arial) -> %.3f" % fator


# ---------------------------------------------------------------------------
# LINHAS SOBREPOSTAS: a de cima no AutoCAD por cima no QGIS
def test_linhas_sobrepostas_a_de_cima_no_autocad_fica_por_cima(conv, subtests):
    arvore = [n.get("name") for n in conv.raiz.iter("layer-tree-layer")]
    for caso in conv.esperado["sobrepostas"]:
        cima, baixo = caso["cima"], caso["baixo"]
        with subtests.test(msg="%s acima de %s" % (cima, baixo)):
            assert cima in arvore and baixo in arvore and arvore.index(cima) < arvore.index(baixo), \
                "%s acima de %s (%s) -> %s" % (cima, baixo, caso["como"],
                                              [n for n in arvore if n.endswith("_LineString")])


# ---------------------------------------------------------------------------
# FONTE DE TRACO (simplex) E TEXTO COM VAO PARA ATRIBUTO
def test_largura_das_fontes_de_traco_e_texto_decodificado():
    # o AutoCAD grava onde comeca o texto alinhado pela direita/centro: "RS " deu
    # 62 unidades no LOTEAMENTO (romans, maiuscula = 21)
    assert abs(textos_cad.largura_shx("RS ", 21, "romans") - 62) < 1e-9, \
        "largura da romans: 'RS ' = 62 unidades (espaco de 21) -> %g" % textos_cad.largura_shx(
            "RS ", 21, "romans")
    assert (textos_cad.largura_shx("ÁREA", 21, "simplex")
            == textos_cad.largura_shx("AREA", 21, "simplex")), \
        "letra acentuada mede como a letra sem acento"
    assert [textos_cad.fonte_de_traco(n) for n in ("simplex", "ROMANS.shx", "romans__.ttf", "txt")] \
        == ["simplex", "romans", "romans", None], "simplex, ROMANS.shx e romans__.ttf tem tabela; txt nao"
    assert dxf_estilo._decodificar_texto("45%%d %%p1 \\U+00B0") == "45° ±1 °", \
        "%%d, %%p e \\U+00B0 lidos como o GDAL le"


@pytest.fixture(scope="module")
def quadro(conv):
    """Os textos do quadro de situacoes cartograficas, por conteudo."""
    return {f["properties"]["Text"]: f for f in feicoes(conv, "Quadro_Texto")}


def do_quadro(quadro, texto):
    f = quadro.get(texto)
    if f is None:
        pytest.fail("texto %r nao encontrado no quadro -> %s" % (texto, sorted(quadro)))
    return f


def extensao(f):
    """Onde a tinta do rotulo comeca e termina no QGIS (x, sem o X0)."""
    pr = f["properties"]
    x = f["geometry"]["coordinates"][0] - X0
    w = textos_cad.largura_texto(pr["Text"], pr["txt_tam"] * textos_cad.CAP_ARIAL)
    return {"Left": (x, x + w), "Center": (x - w / 2, x + w / 2), "Right": (x - w, x)}[pr["txt_h"]]


def test_quadro_a_fonte_vem_do_estilo_do_bloco_e_o_texto_se_divide_no_vao(conv, quadro):
    q = conv.esperado["quadro"]
    indice = dxf_estilo.fontes_dos_textos(conv.dxf)
    f_antes = quadro.get(q["antes"])
    assert f_antes is not None and (indice.achar(f_antes["properties"]["EntityHandle"],
                                                 "MERIDIANO CENTRAL    ° WGr") or {}
                                    ).get("arquivo") == "simplex", \
        "o GDAL diz Arial, mas o estilo do texto do bloco e simplex (pelo handle do INSERT)"
    f_valor = quadro.get(q["valor"])
    assert f_valor is not None and (indice.achar(f_valor["properties"]["EntityHandle"], "45")
                                    or {}).get("arquivo") == "simplex", \
        "e o do atributo tambem (pelo handle dele)"
    assert (q["antes"] in quadro and q["depois"] in quadro
            and not [t for t in quadro if "    " in t]), \
        "o texto e dividido no vao de quatro espacos -> %s" % sorted(quadro)


def test_quadro_cada_parte_comeca_e_termina_onde_o_autocad_manda(conv, quadro):
    q = conv.esperado["quadro"]
    inicio = q["insercao"][0]
    f_antes, f_valor = do_quadro(quadro, q["antes"]), do_quadro(quadro, q["valor"])
    depois = do_quadro(quadro, q["depois"])
    no_cad = textos_cad.largura_shx(q["recuo"], q["altura"], "simplex") * q["fator"]
    x_depois = extensao(depois)[0]
    assert abs(x_depois - (inicio + no_cad)) < 1e-3, \
        "o '%s' comeca onde comeca no AutoCAD -> x=%.3f, no AutoCAD %.3f" % (
            q["depois"], x_depois, inicio + no_cad)
    fim, (v0, v1) = extensao(f_antes)[1], extensao(f_valor)
    assert fim < v0, "'%s' termina antes do 45 (na Arial passava por cima) " \
        "-> termina em %.2f, o 45 vai de %.2f a %.2f" % (q["antes"], fim, v0, v1)
    assert v1 < x_depois, "o 45 termina antes do '%s' -> %.2f < %.2f" % (q["depois"], v1, x_depois)
    # como era: largura do AutoCAD medida na Arial e 15% de folga
    tam_antigo = textos_cad.tamanho_qgis(q["altura"] * convert.FOLGA_LARGURA * q["fator"])
    assert inicio + textos_cad.largura_texto(q["antes"], tam_antigo * textos_cad.CAP_ARIAL) > v0, \
        "(o caso testa algo: no tamanho de antes o CENTRAL ia ate o 45)"


def test_quadro_primeira_linha_termina_antes_da_borda(conv, quadro):
    q = conv.esperado["quadro"]
    borda = q["insercao"][0] + q["borda"] * q["escala"]
    fim = extensao(do_quadro(quadro, q["primeira"]))[1]
    assert fim < borda, "a primeira linha termina antes da borda do quadro -> %.2f < %.2f" % (
        fim, borda)


def test_quadro_todas_as_linhas_com_a_mesma_letra(conv):
    tamanhos = {round(f["properties"]["txt_tam"], 6) for f in feicoes(conv, "Quadro_Texto")}
    assert len(tamanhos) == 1, \
        "todas as linhas do quadro com a mesma letra, como no AutoCAD -> %s" % sorted(tamanhos)
