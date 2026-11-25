# -*- coding: utf-8 -*-
"""
Juntar tudo em um arquivo por tipo (pontos, linhas, areas), sem os textos e as
hachuras que vinham como arquivos extras.

Quem entrega os dados num pacote com exatamente tres arquivos (um de pontos, um de
linhas, um de poligonos) precisa deixar os textos e as hachuras de fora, senao eles
viram o quarto e o quinto arquivo. A opcao fica desligada: nada muda para quem nao a
pede.
"""
import glob
import os

import ezdxf
import fiona
import pytest

from conversor import convert


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("sem_textos")
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=5)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A"})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "B"})
    msp.add_point((3, 3), dxfattribs={"layer": "A"})
    msp.add_point((4, 4), dxfattribs={"layer": "B"})
    msp.add_lwpolyline([(20, 0), (30, 0), (30, 10), (20, 10)], close=True,
                       dxfattribs={"layer": "A"})                 # vira area com --areas
    msp.add_text("rotulo", dxfattribs={"layer": "A"}).set_placement((1, 1))
    h = msp.add_hatch(color=1, dxfattribs={"layer": "B"})
    h.paths.add_polyline_path([(40, 0), (45, 0), (45, 5), (40, 5)], is_closed=True)
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta


def converter(dxf, nome, formato="ESRI Shapefile", **opcoes):
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), nome)
    res = convert.cad_para_qgis(caminho, saida, 31982, formato=formato, gerar_projeto=False,
                                registrar=lambda *_: None, **opcoes)
    return saida, res


def arquivos(saida):
    return sorted(os.path.basename(a)[:-4] for a in glob.glob(os.path.join(saida, "*.shp")))


def test_juntando_por_tipo_sem_textos_e_hachuras_saem_so_tres_arquivos(dxf):
    saida, _ = converter(dxf, "tres", separar_por_camada=False, poli_fechada_como_poligono=True,
                         sem_textos_e_hachuras=True)
    assert arquivos(saida) == ["LineString", "Point", "Polygon"], \
        "um de pontos, um de linhas e um de areas -> %s" % arquivos(saida)
    with fiona.open(os.path.join(saida, "LineString.shp")) as f:
        assert len(f) == 2 and {ft["properties"]["Layer"] for ft in f} == {"A", "B"}, \
            "as linhas das duas camadas juntas, e o campo Layer diz de qual veio"
    with fiona.open(os.path.join(saida, "Point.shp")) as f:
        assert len(f) == 2
    with fiona.open(os.path.join(saida, "Polygon.shp")) as f:
        assert len(f) == 1, "so a area da polilinha fechada; a hachura nao entra"


def test_sem_a_opcao_textos_e_hachuras_continuam_saindo(dxf):
    saida, _ = converter(dxf, "com_tudo", separar_por_camada=False,
                         poli_fechada_como_poligono=True)
    assert set(arquivos(saida)) >= {"Texto", "Hachura", "LineString", "Point", "Polygon"}, \
        "a opcao vem desligada: nada muda -> %s" % arquivos(saida)


def test_sem_textos_e_hachuras_tambem_vale_separando_por_camada(dxf):
    saida, _ = converter(dxf, "por_camada", sem_textos_e_hachuras=True)
    nomes = arquivos(saida)
    assert not [n for n in nomes if n.endswith(("_Texto", "_Hachura", "_Textura"))], nomes
    assert {"A_LineString", "B_LineString", "A_Point", "B_Point"} <= set(nomes), nomes


def test_o_log_diz_quantos_textos_e_hachuras_ficaram_de_fora(dxf):
    log = []
    caminho, pasta = dxf
    convert.cad_para_qgis(caminho, os.path.join(str(pasta), "log"), 31982,
                          formato="ESRI Shapefile", gerar_projeto=False,
                          sem_textos_e_hachuras=True, registrar=log.append)
    assert any("textos e hachuras" in linha and "ficaram de fora" in linha for linha in log), log


def test_desenho_so_de_texto_com_a_opcao_da_o_erro_de_sempre(tmp_path):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("so texto").set_placement((1, 1))
    caminho = str(tmp_path / "t.dxf")
    doc.saveas(caminho)
    with pytest.raises(convert.ErroConversao):
        convert.cad_para_qgis(caminho, str(tmp_path / "saida"), 31982, formato="ESRI Shapefile",
                              gerar_projeto=False, sem_textos_e_hachuras=True,
                              registrar=lambda *_: None)


def test_juntando_por_tipo_camada_desligada_nao_vira_arquivo_a_parte(tmp_path):
    # no AutoCAD as camadas desligadas (como as curvas de nivel do desenho real) vem
    # desmarcadas no QGIS, num grupo "oculto_*". Quem junta por tipo quer 3 arquivos, e
    # as desligadas que a pessoa escolheu levar entram nos mesmos arquivos
    doc = ezdxf.new("R2010")
    doc.layers.add("Ligada", color=3)
    doc.layers.add("Desligada", color=1).off()
    msp = doc.modelspace()
    for camada, y in (("Ligada", 0), ("Desligada", 5)):
        msp.add_line((0, y), (10, y), dxfattribs={"layer": camada})
        msp.add_point((3, y), dxfattribs={"layer": camada})
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    saida = str(tmp_path / "juntas")
    convert.cad_para_qgis(caminho, saida, 31982, formato="ESRI Shapefile", gerar_projeto=False,
                          separar_por_camada=False, registrar=lambda *_: None)
    assert arquivos(saida) == ["LineString", "Point"],         "so um arquivo de linhas e um de pontos -> %s" % arquivos(saida)
    with fiona.open(os.path.join(saida, "LineString.shp")) as f:
        assert {ft["properties"]["Layer"] for ft in f} == {"Ligada", "Desligada"},             "a desligada vai junto, e o campo Layer diz qual e qual"
