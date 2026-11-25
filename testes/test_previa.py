# -*- coding: utf-8 -*-
"""
A leitura do desenho para a lista de camadas e a previa.

O que a previa mostra tem que ser o que a conversao grava: mesmos nomes de
camada, mesmas exclusoes (folha de impressao, pontos de definicao de cota).
Se os dois divergem, uma camada marcada converte em nada, ou uma desmarcada
vaza.
"""
import os

import ezdxf
import fiona
import pytest

import gerar_camadas
from conversor import convert, previa

X0, Y0 = gerar_camadas.X0, gerar_camadas.Y0


@pytest.fixture(scope="module")
def desenho(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("previa")
    dxf, esperado = gerar_camadas.gerar(str(pasta / "desenho"))
    return dxf, esperado, pasta


@pytest.fixture(scope="module")
def lida(desenho):
    return previa.ler(desenho[0])


def por_nome(p):
    return {c.nome: c for c in p.camadas}


def salvar(doc, pasta, nome):
    caminho = os.path.join(str(pasta), nome)
    doc.saveas(caminho)
    return caminho


# ---------------------------------------------------------------------------
def test_as_camadas_da_previa_sao_as_que_a_conversao_grava(desenho, lida):
    dxf, _, pasta = desenho
    saida = os.path.join(str(pasta), "c.gpkg")
    convert.cad_para_qgis(dxf, saida, 31982, gerar_projeto=False, registrar=lambda *_: None)
    gravadas = {c.rsplit("_", 1)[0] for c in fiona.listlayers(saida)}
    assert set(por_nome(lida)) == gravadas, \
        "mesmas camadas -> so na previa: %s, so na conversao: %s" % (
            sorted(set(por_nome(lida)) - gravadas), sorted(gravadas - set(por_nome(lida))))


def test_contagem_por_tipo_de_cada_camada(lida):
    c = por_nome(lida)
    assert c["Pontos"].contagem["ponto"] == 3, "tres pontos -> %s" % c["Pontos"].contagem
    assert (c["Visivel"].contagem["linha"], c["Visivel"].contagem["texto"]) == (1, 1), \
        "um quadrado e um texto; os da folha de impressao nao contam -> %s" % c["Visivel"].contagem
    assert {k: c["Desligada"].contagem[k] for k in ("linha", "ponto", "texto", "hachura")} \
        == {"linha": 1, "ponto": 1, "texto": 1, "hachura": 1}, c["Desligada"].contagem


def test_camada_desligada_ou_congelada_vem_marcada_como_oculta(lida):
    c = por_nome(lida)
    assert c["Desligada"].oculta and c["Congelada"].oculta, "as duas escondidas"
    assert not c["Visivel"].oculta and not c["Pontos"].oculta, "as outras nao"


def test_cor_da_camada_e_a_do_desenho(lida, desenho):
    assert por_nome(lida)["Pontos"].cor == desenho[1]["cor_pontos"], \
        "a cor azul dos pontos -> %s" % por_nome(lida)["Pontos"].cor


def test_formas_trazem_os_vertices_do_desenho(lida):
    formas = lida.formas("Visivel")
    linhas = [f for f in formas if f.tipo == "linha"]
    assert len(linhas) == 1, "uma cor, um grupo de linhas -> %d grupos" % len(linhas)
    xy, inicio = linhas[0].xy, linhas[0].inicio
    assert len(inicio) == 2 and len(xy) == 5, \
        "um quadrado fechado: 1 forma, 5 vertices -> %d formas, %d vertices" % (
            len(inicio) - 1, len(xy))
    assert tuple(xy[0]) == (X0, Y0) and tuple(xy[2]) == (X0 + 100, Y0 + 60), \
        "nas coordenadas do desenho -> %s" % (xy.tolist(),)
    assert all(f.tipo != "texto" for f in formas), "texto nao se desenha, so se conta"


def test_caixa_de_uma_camada(lida):
    x0, y0, x1, y1 = lida.caixa_de({"Visivel"})
    assert (x0, y0, x1, y1) == (X0, Y0, X0 + 100, Y0 + 60), "o quadrado -> %s" % ((x0, y0, x1, y1),)


def test_cada_cor_da_camada_vira_um_grupo_de_formas(tmp_path):
    # a cor do CAD significa algo (azul = corrego): nao pode virar uma cor so por camada
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)                                   # verde
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A"})                    # ByLayer: verde
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 1})        # vermelha propria
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})        # azul propria
    msp.add_line((0, 12), (10, 12), dxfattribs={"layer": "A", "color": 5})      # outra azul
    p = previa.ler(salvar(doc, tmp_path, "cores.dxf"))
    grupos = {f.cor: len(f.inicio) - 1 for f in p.formas("A")}
    assert grupos == {"#00ff00": 1, "#ff0000": 1, "#0000ff": 2},         "uma cor por grupo, com as formas dela -> %s" % grupos


def test_feicao_escondida_dentro_de_camada_ligada_e_separada(tmp_path):
    # a linha do bloco esta na camada X (ligada), mas o INSERT esta numa camada
    # congelada: o AutoCAD nao a mostra
    doc = ezdxf.new("R2010")
    doc.layers.add("X", color=3)
    doc.layers.add("Congelada", color=1).freeze()
    bloco = doc.blocks.new("B")
    bloco.add_line((0, 0), (10, 0), dxfattribs={"layer": "X"})
    msp = doc.modelspace()
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "X"})
    msp.add_blockref("B", (0, 100), dxfattribs={"layer": "Congelada"})
    msp.add_blockref("B", (0, 40), dxfattribs={"layer": "X"})
    p = previa.ler(salvar(doc, tmp_path, "mista.dxf"))
    x = por_nome(p)["X"]
    assert not x.oculta and x.n_ocultas == 1 and x.contagem["linha"] == 3,         "a camada esta ligada, e uma das 3 linhas esta escondida -> %s" % x

    def n_formas(com_ocultas):
        return sum(len(f.inicio) - 1 for f in p.formas("X", com_ocultas=com_ocultas))
    assert n_formas(False) == 2 and n_formas(True) == 3,         "sem as escondidas 2 linhas, com elas 3 -> %d / %d" % (n_formas(False), n_formas(True))
    assert p.caixa_de({"X"}, com_ocultas=False)[3] == 40, "o enquadramento nao conta a escondida"
    assert p.caixa_de({"X"}, com_ocultas=True)[3] == 100


# ---------------------------------------------------------------------------
# separar cada camada por cor
def _desenho_com_cores(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 7), (10, 7), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})
    msp.add_point((3, 3), dxfattribs={"layer": "A", "color": 5})
    msp.add_line((20, 0), (30, 40), dxfattribs={"layer": "B"})
    return previa.ler(salvar(doc, tmp_path, "por_cor.dxf"))


def test_camada_com_varias_cores_vira_um_item_por_cor(tmp_path):
    p = _desenho_com_cores(tmp_path)
    unidades = {u.chave: u for u in p.unidades}
    assert set(unidades) == {("A", "#ff0000"), ("A", "#0000ff"), ("B", "#00ff00")},         "uma por camada e cor -> %s" % sorted(unidades)
    assert unidades[("A", "#ff0000")].contagem == {"linha": 3}
    assert unidades[("A", "#0000ff")].contagem == {"linha": 1, "ponto": 1}
    assert unidades[("A", "#ff0000")].nome == "A · vermelho" and         unidades[("A", "#0000ff")].nome == "A · azul", "o nome diz a cor"
    assert unidades[("B", "#00ff00")].nome == "B", "camada de uma cor so mantem o nome"
    assert [u.chave for u in p.unidades][:2] == [("A", "#ff0000"), ("A", "#0000ff")],         "na ordem das camadas e, dentro dela, a cor com mais feicoes primeiro"
    assert unidades[("A", "#ff0000")].resumo() == "3 linhas"


def test_itens_sao_as_camadas_ou_as_cores(tmp_path):
    p = _desenho_com_cores(tmp_path)
    assert [c.nome for c in p.itens(por_cor=False)] == ["A", "B"]
    assert len(p.itens(por_cor=True)) == 3


def test_formas_da_camada_podem_ser_filtradas_pela_cor(tmp_path):
    p = _desenho_com_cores(tmp_path)
    azuis = p.formas("A", cor="#0000ff")
    assert {f.cor for f in azuis} == {"#0000ff"} and {f.tipo for f in azuis} == {"linha", "ponto"}
    assert {f.cor for f in p.formas("A")} == {"#ff0000", "#0000ff"}, "sem filtro, todas"


def test_caixa_de_itens_usa_a_caixa_de_cada_cor(tmp_path):
    p = _desenho_com_cores(tmp_path)
    por_chave = {u.chave: u for u in p.unidades}
    azul = por_chave[("A", "#0000ff")]
    assert p.caixa_de_itens([azul]) == (0, 3, 10, 9), "linha em y=9 e ponto em (3, 3)"
    assert p.caixa_de_itens([por_chave[("A", "#ff0000")], azul]) == (0, 0, 10, 9)


def test_cor_escondida_de_uma_camada_ligada_e_separada_por_item(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("X", color=3)
    doc.layers.add("Congelada", color=1).freeze()
    bloco = doc.blocks.new("B")
    bloco.add_line((0, 0), (10, 0), dxfattribs={"layer": "X"})
    msp = doc.modelspace()
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "X"})
    msp.add_blockref("B", (0, 100), dxfattribs={"layer": "Congelada"})
    p = previa.ler(salvar(doc, tmp_path, "mista_cor.dxf"))
    visivel = [u for u in p.unidades if u.camada == "X" and u.cor == "#00ff00"][0]
    escondida = [u for u in p.unidades if u.camada == "X" and u.cor != "#00ff00"][0]
    assert not visivel.oculta and escondida.oculta,         "a linha do bloco congelado sai como item a parte, escondido -> %s / %s" % (
            visivel, escondida)


def _desenho_com_hachura(tmp_path, monkeypatch, cor_do_ezdxf):
    """Uma hachura verde e uma linha. O ezdxf, que le as hachuras do jeito certo,
    "diz" outra cor para ela (o GDAL erra a cor de algumas hachuras)."""
    from conversor import cad_ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("H", color=7)
    msp = doc.modelspace()
    h = msp.add_hatch(color=3, dxfattribs={"layer": "H"})
    h.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    msp.add_line((20, 0), (30, 0), dxfattribs={"layer": "H", "color": 3})
    caminho = salvar(doc, tmp_path, "hachura.dxf")
    desenho = cad_ezdxf.ler(caminho, lambda *_: None)
    for hachura in desenho["hachuras"]:
        hachura["cor"] = cor_do_ezdxf
    monkeypatch.setattr(cad_ezdxf, "ler", lambda *a, **k: desenho)
    return caminho


def test_cor_da_hachura_vem_do_ezdxf_quando_ele_leu_ela(tmp_path, monkeypatch):
    p = previa.ler(_desenho_com_hachura(tmp_path, monkeypatch, (255, 127, 0)))
    unidades = {u.chave: u for u in p.unidades}
    assert ("H", "#ff7f00") in unidades and unidades[("H", "#ff7f00")].contagem == {"hachura": 1},         "a hachura entra na cor que o ezdxf deu -> %s" % sorted(unidades)
    assert unidades[("H", "#00ff00")].contagem == {"linha": 1}, "e a linha segue verde"


# ---------------------------------------------------------------------------
def test_ponto_de_definicao_de_cota_nao_conta(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("A")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "A"})
    msp.add_point((5, 5), dxfattribs={"layer": "Defpoints"})
    p = previa.ler(salvar(doc, tmp_path, "def.dxf"))
    assert [c.nome for c in p.camadas] == ["A"], "como na conversao -> %s" % [c.nome for c in p.camadas]


def test_desenho_so_no_papel_usa_a_folha(desenho):
    _, _, pasta = desenho
    so_papel = gerar_camadas.gerar_so_papel(str(pasta / "so_papel"))
    p = previa.ler(so_papel)
    assert [c.nome for c in p.camadas] == ["0"] and p.camadas[0].contagem["linha"] == 1, \
        "sem nada na aba Model, a folha e o desenho -> %s" % [(c.nome, c.contagem) for c in p.camadas]


def test_camada_so_de_texto_aparece_no_desenho_mas_nao_tem_geometria(tmp_path):
    # A previa desenha os textos: a camada so de texto fica entre as outras da lista (por
    # nome), mas continua sem nada que a conversao leve como ponto, linha ou area.
    doc = ezdxf.new("R2010")
    for nome in ("A_TEXTOS", "Z_DADOS"):
        doc.layers.add(nome)
    msp = doc.modelspace()
    msp.add_text("ola", dxfattribs={"layer": "A_TEXTOS"}).set_placement((1, 1))
    msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "Z_DADOS"})
    p = previa.ler(salvar(doc, tmp_path, "txt.dxf"))
    assert [c.nome for c in p.camadas] == ["A_TEXTOS", "Z_DADOS"], \
        "as duas aparecem no desenho, por nome -> %s" % [c.nome for c in p.camadas]
    textos, dados = p.camadas
    assert textos.tem_desenho and not textos.tem_geometria
    assert dados.tem_geometria


def test_resumo_diz_o_que_tem_na_camada():
    c = previa.Camada("X", "#ff0000", False, {"ponto": 1860, "linha": 1, "texto": 5580})
    assert c.resumo() == "1860 pontos, 1 linha, 5580 textos", c.resumo()
    assert previa.Camada("Y", "#000000", False, {"ponto": 1}).resumo() == "1 ponto"


# ---------------------------------------------------------------------------
def test_feicoes_longe_do_desenho_sao_contadas_e_ficam_fora_do_enquadramento(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("CURVAS")
    msp = doc.modelspace()
    bom = [(448000 + 20 * i, 6743000 + 30 * (i % 7)) for i in range(120)]
    msp.add_lwpolyline(bom, dxfattribs={"layer": "CURVAS", "elevation": 500.0})
    for _ in range(3):
        msp.add_lwpolyline([(0, 0), (0, 0)], dxfattribs={"layer": "CURVAS"})
    p = previa.ler(salvar(doc, tmp_path, "lixo.dxf"))
    curvas = por_nome(p)["CURVAS"]
    assert curvas.fora == 3 and p.fora_total == 3, \
        "as 3 polilinhas na origem -> %d / %d" % (curvas.fora, p.fora_total)
    assert curvas.contagem["linha"] == 4, "contam como feicoes da camada -> %s" % curvas.contagem
    x0, y0, _, _ = p.caixa_de({"CURVAS"})
    assert x0 > 400000 and y0 > 6_000_000, \
        "o enquadramento ignora o lixo e abraca o terreno -> x0=%.0f y0=%.0f" % (x0, y0)
    assert p.distancia_fora > 400000, "e diz a que distancia elas estao -> %.0f" % p.distancia_fora
    assert p.caixa_area is not None and fora_da_conversao(p.caixa_area), \
        "a caixa serve para a conversao descartar as mesmas"


def fora_da_conversao(caixa):
    from conversor import fora_da_area
    return fora_da_area.todos_fora([(0.0, 0.0), (0.0, 0.0)], caixa)
