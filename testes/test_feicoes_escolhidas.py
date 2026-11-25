# -*- coding: utf-8 -*-
"""
Converter so as linhas que a pessoa clicou no desenho, sem levar a camada inteira.

A previa da a cada linha escolhida o id que o GDAL da as feicoes dela (Grupo.fids); a
conversao leva essas feicoes alem das camadas marcadas, e elas passam por cima do
filtro de camadas e do filtro de cor. O id e o do GDAL e nao o handle do AutoCAD, que
repete dentro dos blocos.
"""
import glob
import os

import ezdxf
import fiona
import pytest

from conversor import convert, previa

VERMELHO, AZUL = 1, 5


@pytest.fixture(scope="module")
def desenho(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("escolhidas")
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A", "color": VERMELHO})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": VERMELHO})
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": AZUL})
    msp.add_line((0, 20), (10, 20), dxfattribs={"layer": "B"})
    msp.add_line((0, 30), (10, 30), dxfattribs={"layer": "B"})
    h = msp.add_hatch(color=1, dxfattribs={"layer": "A"})
    h.paths.add_polyline_path([(40, 0), (45, 0), (45, 5), (40, 5)], is_closed=True)
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta, previa.ler(caminho)


def fid_da_linha(desenho, y, camada="A"):
    p = desenho[2]
    gid = p.achar_grupo(5, y, 0.5, camada)
    assert gid is not None, "nao achei a linha em y=%s" % y
    return set(p.grupos[gid].fids)


def converter(desenho, nome, **opcoes):
    caminho, pasta, _ = desenho
    saida = os.path.join(str(pasta), nome)
    convert.cad_para_qgis(caminho, saida, 31982, formato="ESRI Shapefile", gerar_projeto=False,
                          registrar=lambda *_: None, **opcoes)
    return saida


def feicoes(saida):
    """{nome do arquivo: [y de cada linha]} dos shapefiles de linha (e o total dos outros)."""
    achado = {}
    for shp in sorted(glob.glob(os.path.join(saida, "*.shp"))):
        with fiona.open(shp) as f:
            nome = os.path.basename(shp)[:-4]
            achado[nome] = sorted(round(ft["geometry"]["coordinates"][0][1])
                                  for ft in f if ft["geometry"]["type"] == "LineString") \
                if f.schema["geometry"] in ("LineString", "3D LineString") else len(f)
    return achado


def test_so_a_linha_escolhida_sem_nenhuma_camada_marcada(desenho):
    saida = converter(desenho, "so_uma", camadas=set(), feicoes_escolhidas=fid_da_linha(desenho, 5))
    assert feicoes(saida) == {"A_LineString": [5]}, \
        "so a linha clicada, sem as outras da camada A, nem a hachura -> %s" % feicoes(saida)


def test_soma_com_as_camadas_marcadas(desenho):
    saida = converter(desenho, "soma", camadas={"B"}, feicoes_escolhidas=fid_da_linha(desenho, 5))
    assert feicoes(saida) == {"A_LineString": [5], "B_LineString": [20, 30]}, feicoes(saida)


def test_a_linha_escolhida_passa_por_cima_do_filtro_de_cor(desenho):
    # a camada A esta marcada so na cor vermelha, e a linha azul foi clicada
    saida = converter(desenho, "cor", camadas={"A"}, cores={"A": {"#ff0000"}},
                      feicoes_escolhidas=fid_da_linha(desenho, 9))
    assert feicoes(saida)["A_LineString"] == [0, 5, 9], feicoes(saida)


def test_sem_camada_nem_linha_escolhida_continua_dando_erro(desenho):
    with pytest.raises(convert.ErroConversao):
        converter(desenho, "nada", camadas=set())
    with pytest.raises(convert.ErroConversao):
        converter(desenho, "nada2", camadas=set(), feicoes_escolhidas=set())


def test_varias_linhas_escolhidas(desenho):
    fids = fid_da_linha(desenho, 0) | fid_da_linha(desenho, 30, "B")
    saida = converter(desenho, "varias", camadas=set(), feicoes_escolhidas=fids)
    assert feicoes(saida) == {"A_LineString": [0], "B_LineString": [30]}, feicoes(saida)


def test_linha_escolhida_de_camada_separada_por_cor_sai_com_o_nome_da_cor(desenho):
    saida = converter(desenho, "nome", camadas=set(), separar_por_cor={"A"},
                      feicoes_escolhidas=fid_da_linha(desenho, 9))
    assert list(feicoes(saida)) == ["A_azul_LineString"], feicoes(saida)


def test_sem_escolhidas_nada_muda(desenho):
    todas = converter(desenho, "todas")
    assert feicoes(converter(desenho, "igual", feicoes_escolhidas=None)) == feicoes(todas)
    assert feicoes(converter(desenho, "vazio", feicoes_escolhidas=set())) == feicoes(todas)

