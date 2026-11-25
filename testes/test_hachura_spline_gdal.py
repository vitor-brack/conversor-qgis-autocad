# -*- coding: utf-8 -*-
"""
Hachura com borda em spline num DXF antigo (ate o 2007, como o que o ODA grava do DWG do
pai) engolia as entidades seguintes.

No DXF 2004 a borda em spline termina nos pontos de controle; o numero de pontos de ajuste
(grupo 97) so existe a partir do 2010. O GDAL espera esse 97 em qualquer versao: le o 97
seguinte (o dos objetos de origem da borda) no lugar dele, se perde e junta a hachura com as
entidades depois dela numa feicao so, com a geometria da hachura e o handle da ultima.
No desenho do pai sumiam assim uma linha de chamada preta e uma spline, na previa e na
conversao.
"""
import os
import tempfile

import ezdxf
import fiona
import pytest

from conversor import convert, dxf_estilo, previa

X0, Y0 = 448000.0, 6743000.0


def doc_com_hachura_em_spline(versao="R2004"):
    doc = ezdxf.new(versao)
    doc.layers.add("LAGO")
    doc.layers.add("CHAMADA")
    msp = doc.modelspace()
    hachura = msp.add_hatch(color=4, dxfattribs={"layer": "LAGO"})
    borda = hachura.paths.add_edge_path()
    borda.add_spline(control_points=[(X0, Y0), (X0 + 40, Y0 - 10), (X0 + 60, Y0 + 30),
                                     (X0 + 20, Y0 + 50), (X0, Y0)], degree=3)
    linha = msp.add_line((X0 - 100, Y0 + 100), (X0 + 200, Y0 - 50),
                         dxfattribs={"layer": "CHAMADA"})
    msp.add_line((X0, Y0 - 100), (X0 + 10, Y0 - 100), dxfattribs={"layer": "CHAMADA"})
    return doc, hachura.dxf.handle.upper(), linha.dxf.handle.upper()


def feicoes(caminho):
    saida = []
    with dxf_estilo.abrir_entidades(caminho) as (origem, _tem_estilo):
        for f in origem:
            p = f["properties"]
            saida.append(((p.get("EntityHandle") or "").upper(), p.get("SubClasses") or "",
                          f["geometry"] and f["geometry"]["type"]))
    return saida


@pytest.mark.parametrize("versao", ["R2004", "R2007", "R2010", "R2018"])
def test_linha_depois_de_hachura_em_spline_chega_inteira(tmp_path, versao):
    doc, h_hachura, h_linha = doc_com_hachura_em_spline(versao)
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    lidas = feicoes(caminho)
    juntas = [f for f in lidas if f[1].count("AcDbEntity") > 1]
    assert not juntas, "o GDAL juntou entidades: %s" % juntas
    por_handle = {h: (sc, tipo) for h, sc, tipo in lidas}
    assert por_handle.get(h_linha) == ("AcDbEntity:AcDbLine", "LineString"), lidas
    assert "AcDbHatch" in por_handle.get(h_hachura, ("", ""))[0], lidas
    assert os.path.exists(caminho)


def copias_no_temp():
    return {n for n in os.listdir(tempfile.gettempdir())
            if n.startswith("conversor_") and n.endswith(".dxf")}


def test_correcao_nao_mexe_no_arquivo_original_e_apaga_a_copia(tmp_path):
    doc, _h, _l = doc_com_hachura_em_spline()
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    antes = open(caminho, "rb").read()
    temp_antes = copias_no_temp()
    feicoes(caminho)
    assert open(caminho, "rb").read() == antes
    assert sorted(os.listdir(tmp_path)) == ["d.dxf"]
    assert copias_no_temp() <= temp_antes, "a copia corrigida (desenho do cliente) ficou no TEMP"


def test_leitura_que_falha_no_meio_nao_deixa_copia_no_temp(tmp_path):
    # A copia filtrada que o ezdxf le (conversor_ez_*.dxf) ficava no TEMP quando a leitura
    # do DXF falhava no meio -- um pedaco do desenho do cliente esquecido la.
    from conversor import cad_ezdxf
    antes = copias_no_temp()
    erros = []
    assert cad_ezdxf.ler(str(tmp_path / "nao_existe.dxf"), erros.append) is None
    assert erros, "avisa que nao leu"
    assert copias_no_temp() <= antes, "sobrou copia no TEMP"


@pytest.mark.parametrize("versao", ["R2010", "R2018"])
def test_dxf_que_ja_tem_o_97_nao_ganha_outro(tmp_path, versao):
    doc, _h, _l = doc_com_hachura_em_spline(versao)
    borda = list(doc.modelspace().query("HATCH"))[0].paths.paths[0]
    borda.edges[0].fit_points = [(X0, Y0), (X0 + 40, Y0 + 20), (X0, Y0)]
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    copia = dxf_estilo._copia_que_o_gdal_entende(caminho)
    if copia:
        os.remove(copia)
    assert copia is None, "pos um 97 a mais num DXF que ja tinha"


def test_dxf_2004_como_o_do_pai_borda_com_objeto_de_origem_e_semente(tmp_path):
    # Como no DWG do pai: hachura associativa, a borda em spline seguida do 97 dos objetos
    # de origem com 1 handle, e um ponto-semente.
    doc, h_hachura, h_linha = doc_com_hachura_em_spline()
    hachura = doc.entitydb[h_hachura]
    hachura.dxf.associative = 1
    hachura.paths.paths[0].source_boundary_objects = [h_linha]
    hachura.set_seed_points([(X0 + 10, Y0 + 10)])
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    lidas = feicoes(caminho)
    assert not [f for f in lidas if f[1].count("AcDbEntity") > 1], lidas
    assert {h: t for h, _sc, t in lidas}.get(h_linha) == "LineString", lidas


def test_previa_desenha_a_linha_depois_da_hachura_em_spline(tmp_path):
    doc, _h, _l = doc_com_hachura_em_spline()
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    chamada = {c.nome: c for c in p.camadas}["CHAMADA"]
    assert chamada.contagem["linha"] == 2, chamada.contagem


def test_conversao_leva_a_linha_depois_da_hachura_em_spline(tmp_path):
    doc, _h, _l = doc_com_hachura_em_spline()
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    saida = str(tmp_path / "saida.gpkg")
    convert.cad_para_qgis(caminho, saida, 31982, formato="GPKG", gerar_projeto=False,
                          registrar=lambda *_: None)
    linhas = 0
    for camada in fiona.listlayers(saida):
        with fiona.open(saida, layer=camada) as f:
            linhas += sum(1 for ft in f if ft["properties"].get("Layer") == "CHAMADA"
                          and ft["geometry"]["type"].endswith("LineString"))
    assert linhas == 2, "a linha de chamada sumiu da conversao (%d de 2)" % linhas
