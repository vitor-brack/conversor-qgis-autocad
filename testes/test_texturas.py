# -*- coding: utf-8 -*-
"""
Texturas de hachura, logo formatado e altura dos textos -- sem precisar do QGIS.

Para conferir o que o QGIS realmente desenha, ver verificar_texturas_no_qgis.py.
"""
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import fiona
import pytest

import gerar_texturas
from apoio import requer_fonte
from conversor import convert, textos_cad

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "_saida", "texturas")
X0, Y0 = gerar_texturas.X0, gerar_texturas.Y0
BOOKMAN = "font-family:'Bookman Old Style'"
# Regra do AutoCAD para a caixa de um MTEXT: a linha de base de cada linha fica
# a 5/3 da altura da anterior, e a caixa desce 0,2778 da altura abaixo da ultima.
DESCIDA, PASSO = 0.2778, 5.0 / 3.0


@pytest.fixture(scope="module")
def conv():
    """Gera o desenho de texturas e o converte, como o programa faria."""
    shutil.rmtree(BASE, ignore_errors=True)
    dxf, esperado = gerar_texturas.gerar(BASE)
    with open(os.path.join(BASE, "esperado.json"), "w") as fp:
        json.dump(esperado, fp)
    saida = os.path.join(BASE, "saida", "plot.gpkg")
    log = []
    res = convert.cad_para_qgis(dxf, saida, 31982, registrar=log.append)
    return SimpleNamespace(dxf=dxf, esperado=esperado, saida=saida, log=log, res=res,
                           camadas=convert.listar_camadas(saida))


@pytest.fixture(scope="module")
def raiz(conv):
    return ET.parse(conv.res["projeto"]).getroot()


def feicoes(conv, camada):
    with fiona.open(conv.saida, layer=camada) as c:
        return [f for f in c]


def pontos(geom):
    for linha in geom["coordinates"]:
        for x, y in (ponto[:2] for ponto in linha):
            yield x - X0, y - Y0


# ---------------------------------------------------------------------------
def test_perfil_cruzes_abaixo_do_terreno(conv):
    assert "Perfil_Textura" in conv.camadas, "camada de textura do perfil -> %s" % conv.camadas
    perfil = feicoes(conv, "Perfil_Textura")
    assert len(perfil) == 1, "uma feicao por hachura"
    p = perfil[0]["properties"]
    assert (p["cor_cad"], p["hachura"]) == ("#000000", "CROSS"), \
        "cor e padrao do desenho -> %s %s" % (p["cor_cad"], p["hachura"])
    xs, ys = zip(*pontos(perfil[0]["geometry"]))
    assert (min(xs) >= -0.01 and max(xs) <= 180.01 and min(ys) >= -0.01 and max(ys) <= 45.5), \
        "linhas dentro da borda -> x %.1f..%.1f  y %.1f..%.1f" % (min(xs), max(xs), min(ys), max(ys))
    tracos = len(perfil[0]["geometry"]["coordinates"])
    assert tracos > 200, "muitas cruzes (padrao desenhado de verdade) -> %d tracos" % tracos
    # a borda da hachura (que o GDAL devolvia como linha solta) nao entra no desenho
    linhas_perfil = feicoes(conv, "Perfil_LineString")
    assert len(linhas_perfil) == 1, \
        "so a curva do terreno como linha (a borda da hachura nao duplica) -> %d linhas" % len(
            linhas_perfil)


# ---------------------------------------------------------------------------
@pytest.mark.parametrize("indice,cor,padrao", [(0, "#0000ff", "DASH"),
                                               (1, "#ff7f00", "GRAVEL"),
                                               (2, "#00a5a5", "ANSI31")])
def test_legenda_cada_amostra_com_o_seu_padrao_e_a_sua_cor(conv, indice, cor, padrao):
    caixa = conv.esperado["legenda"][indice][1]
    f = {f["properties"]["cor_cad"]: f for f in feicoes(conv, "Legenda_Textura")}.get(cor)
    assert f is not None and f["properties"]["hachura"] == padrao, \
        "amostra %s -> %s" % (padrao, f["properties"]["hachura"] if f else "ausente")
    xs, ys = zip(*pontos(f["geometry"]))
    assert (min(xs) >= caixa[0] - 1.01 and max(xs) <= caixa[2] + 1.01
            and min(ys) >= caixa[1] - 1.01 and max(ys) <= caixa[3] + 1.01), \
        "%s dentro do quadrado" % padrao


def test_legenda_bloco_espelhado_sem_copias_fantasmas(conv):
    # bloco espelhado: sem as copias fantasmas do ezdxf, tudo em x 262..270
    por_cor = {f["properties"]["cor_cad"]: f for f in feicoes(conv, "Legenda_Textura")}
    espelhado = por_cor.get("#ff0000")
    assert espelhado is not None, "hachura de bloco espelhado convertida"
    xs, ys = zip(*pontos(espelhado["geometry"]))
    assert min(xs) >= 261.99 and max(xs) <= 270.01 and min(ys) >= 9.99 and max(ys) <= 18.01, \
        "sem copias espelhadas fora do lugar -> x %.2f..%.2f" % (min(xs), max(xs))


# ---------------------------------------------------------------------------
def test_logo_texto_e_cores(conv):
    props = feicoes(conv, "Logo_Texto")[0]["properties"]
    html = props["txt_html"]
    assert props["Text"] == "Geosana", "texto puro preservado -> %r" % props["Text"]
    assert 'color:#0000ff' in html and ">Geo<" in html, "'Geo' em azul"
    assert 'color:#00ff00' in html and ">sana<" in html, "'sana' em verde"


@requer_fonte("Arial Rounded MT Bold")
def test_logo_fonte_e_negrito_do_desenho(conv):
    html = feicoes(conv, "Logo_Texto")[0]["properties"]["txt_html"]
    assert "Arial Rounded MT Bold" in html and "font-weight:bold" in html, \
        "fonte e negrito do desenho"


def test_logo_apoiado_na_linha_de_base(conv):
    logo = feicoes(conv, "Logo_Texto")[0]
    y = logo["geometry"]["coordinates"][1] - Y0
    assert abs(y - (118.0 - 10.0)) < 1e-6 and logo["properties"]["txt_v"] == "Base", \
        "apoiado na linha de base: uma altura abaixo da ancora (o topo da maiuscula) " \
        "-> y %.3f, %s (ancora 118)" % (y, logo["properties"]["txt_v"])


def test_rotulos_do_projeto_em_html_ou_simples(raiz):
    estilos = {}
    for ml in raiz.iter("maplayer"):
        ts = ml.find(".//labeling/settings/text-style")
        if ts is not None:
            tf = ml.find(".//labeling/settings/text-format")
            estilos[ml.findtext("layername")] = (ts.get("allowHtml"), ts.get("fieldName"),
                                                 tf.get("wrapChar"))
    assert estilos.get("Logo_Texto") == ("1", "txt_html", ""), \
        "logo com rotulo em HTML -> %s" % (estilos.get("Logo_Texto"),)
    assert estilos.get("Carimbo_Texto") == ("1", "txt_html", ""), \
        "carimbo com rotulo em HTML -> %s" % (estilos.get("Carimbo_Texto"),)
    assert estilos.get("Legenda_Texto") == ("0", "Text", ""), \
        "legenda (sem formatacao) com rotulo simples -> %s" % (estilos.get("Legenda_Texto"),)


def test_projeto_sem_o_que_o_qgis_ignora_ou_distorce(raiz):
    propriedades = {o.get("name") for ml in raiz.iter("maplayer")
                    if ml.findtext("layername") == "Carimbo_Texto"
                    for o in ml.iter("Option") if o.get("type") == "Map" and o.get("name")}
    assert "MultiLineHeight" not in propriedades and "Vali" in propriedades, \
        "sem altura de linha por campo (o QGIS a ignora) -> %s" % sorted(propriedades)
    assert "FontStretchFactor" not in propriedades, \
        "sem fator de largura (o QGIS encavala ou espalha as letras) -> %s" % sorted(propriedades)


def test_titulo_comprimido_guarda_o_fator(conv):
    comp = conv.esperado["comprimido"]
    titulo = [f for f in feicoes(conv, "Legenda_Texto") if f["properties"]["Text"] == comp["texto"]]
    assert len(titulo) == 1 and abs(titulo[0]["properties"]["txt_larg"] - 85.0) < 0.01, \
        "titulo comprimido convertido, fator guardado (85) -> %s" % [
            f["properties"]["txt_larg"] for f in titulo]


# ---------------------------------------------------------------------------
@requer_fonte("Bookman Old Style")
def test_carimbo_uma_feicao_por_linha_na_base_do_autocad_com_a_fonte_certa(conv, subtests):
    assert "Carimbo_Texto" in conv.camadas, "camada de texto do carimbo"
    # cada linha de um MTEXT e uma feicao; as de um mesmo MTEXT tem o mesmo handle
    por_mtext = {}
    for f in feicoes(conv, "Carimbo_Texto"):
        por_mtext.setdefault(f["properties"]["EntityHandle"], []).append(f)
    achados = {"\n".join(f["properties"]["Text"] for f in grupo): grupo
               for grupo in por_mtext.values()}
    for e in conv.esperado["carimbo"]:
        nome = e["texto"].split("\n")[0][:32]
        with subtests.test(msg=nome):
            grupo = achados.get(e["texto"])
            assert grupo is not None, "'%s': as %d linha(s) do AutoCAD, nada colado -> %r" % (
                nome, e["linhas"], [t for t in achados if t[:10] == e["texto"][:10]])
            # A linha de base de cada linha pela regra do AutoCAD, calculada aqui sem
            # o conversor: a caixa do MTEXT vai do topo da maiuscula da primeira linha
            # ate 0,2778 da altura abaixo da base da ultima, com as linhas a 5/3 da
            # altura uma da outra.
            h, n = e["altura"], e["linhas"]
            ax, ay = e["ancora"]
            primeira = {"Top": ay - h, "Bottom": ay + DESCIDA * h + (n - 1) * PASSO * h,
                        "Half": ay + (h + (n - 1) * PASSO * h + DESCIDA * h) / 2 - h}[e["v"]]
            erro = max(abs(f["geometry"]["coordinates"][1] - Y0 - (primeira - k * PASSO * h))
                       + abs(f["geometry"]["coordinates"][0] - X0 - ax)
                       for k, f in enumerate(grupo))
            assert erro < 1e-6 and all(f["properties"]["txt_v"] == "Base"
                                       and f["properties"]["txt_h"] == e["h"] for f in grupo), \
                "cada linha apoiada na sua linha de base -> erro %.4f m" % erro
            htmls = [f["properties"]["txt_html"] for f in grupo]
            assert all("<br" not in t and textos_cad.QUEBRA_HTML not in t
                       and t.count("<span") == t.count("</span>") for t in htmls), \
                "HTML de cada linha sem quebra e com os trechos fechados -> %r" % htmls[0][:90]
            estilos_css = [s for t in htmls for s in re.findall(r'<span style="([^"]*)">', t)]
            if e["forma"] == "sem fonte":
                assert not estilos_css, "texto sem formatacao continua sem trechos"
            elif e["forma"] == "inexistente":
                assert estilos_css and all("font-family" not in s and "font-weight:bold" in s
                                           for s in estilos_css), \
                    "fonte que nao existe: Arial (sem font-family), negrito mantido -> %s" % estilos_css
            else:
                assert estilos_css and all(BOOKMAN in s and "font-weight:bold" in s
                                           for s in estilos_css), \
                    "fonte gravada como %s -> Bookman Old Style negrito -> %s" % (
                        e["forma"], estilos_css)
            assert all(f["properties"]["txt_larg"] == 115.0 for f in grupo), \
                "fator de largura do estilo (1,15) guardado so como informacao -> %s" % (
                    grupo[0]["properties"]["txt_larg"])


# ---------------------------------------------------------------------------
def no_poligono(x, y, poligono):
    """Par ou impar de cruzamentos: o ponto esta dentro do poligono?"""
    dentro = False
    for (x1, y1), (x2, y2) in zip(poligono, poligono[1:] + poligono[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


def test_perfil_futuro_borda_remendada_so_o_solo_hachurado(conv):
    fut = conv.esperado["futuro"]
    assert fut["camada"] in conv.camadas, "camada de textura do perfil futuro"
    meios = [((a[0] + b[0]) / 2 - X0, (a[1] + b[1]) / 2 - Y0)
             for f in feicoes(conv, fut["camada"])
             for a, b in (linha[:2] for linha in f["geometry"]["coordinates"])]
    solo = [tuple(v) for v in fut["solo"]]
    fora = [m for m in meios if not no_poligono(m[0], m[1], solo)]
    assert len(meios) > 100, "padrao desenhado no solo -> %d tracos" % len(meios)
    assert not fora, "nenhum traco fora do solo (nem na fatia do topo, nem na escavacao) " \
        "-> %d fora, ex.: %s" % (len(fora), ["(%.2f, %.2f)" % m for m in fora[:3]])
    x1, y1, x2, y2 = fut["escavacao"]
    assert not [m for m in meios if x1 < m[0] < x2 and y1 < m[1] < y2], "escavacao em branco"


# ---------------------------------------------------------------------------
def test_cotas_pontas_de_seta_e_pontos_de_definicao(conv):
    cot = conv.esperado["cotas"]
    pintados = feicoes(conv, cot["camada"]) if cot["camada"] in conv.camadas else []
    assert len(pintados) == cot["solidos"], \
        "pontas de seta e SOLID solto convertidos (pintados) -> %d de %d" % (
            len(pintados), cot["solidos"])
    cores = {f["properties"]["cor_cad"] for f in pintados}
    assert cores == {cot["cor"]}, "na cor da cota -> %s" % cores
    assert not [c for c in conv.camadas if c.lower().startswith("defpoints")], \
        "pontos de definicao (camada Defpoints) fora do QGIS -> %s" % conv.camadas
    assert any("Defpoints" in linha for linha in conv.log), "e o log explica por que"
    assert any(f["properties"]["Text"] == "12" for f in feicoes(conv, "Cotas_Texto")), \
        "texto da cota convertido"


def test_martelo_hachuras_solidas_dentro_de_bloco(conv):
    martelo = sorted(f["properties"]["cor_cad"] for f in feicoes(conv, "Logo_Hachura"))
    assert martelo == ["#0000ff", "#545454"], \
        "cabeca cinza e cabo azul (ByBlock herda do INSERT) -> %s" % martelo


# ---------------------------------------------------------------------------
def test_projeto_ordem_das_camadas_e_espessura_dos_tracos(raiz):
    ordem = [e.get("name") for e in raiz.iter("layer-tree-layer")]
    posicao = {n: i for i, n in enumerate(ordem)}
    assert (max(posicao[n] for n in ordem if n.endswith("_LineString"))
            < min(posicao[n] for n in ordem if n.endswith("_Textura"))
            < min(posicao[n] for n in ordem if n.endswith("_Hachura"))), \
        "texturas por baixo das linhas e por cima das hachuras solidas -> %s" % ordem
    larguras = set()
    for ml in raiz.iter("maplayer"):
        if ml.findtext("layername", "").endswith("_Textura"):
            for prop in ml.iter("prop"):
                if prop.get("k") == "line_width":
                    larguras.add(prop.get("v"))
    assert larguras == {"0.13"}, "tracos finos, como na hachura do AutoCAD -> %s" % larguras
