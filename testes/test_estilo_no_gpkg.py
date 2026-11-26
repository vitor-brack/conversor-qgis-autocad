# -*- coding: utf-8 -*-
"""
A cor do AutoCAD tem de chegar ao QGIS quando o .gpkg e aberto sozinho, sem o .qgs.

O GeoPackage guarda a cor de cada feicao no campo cor_cad, mas o QGIS nao pinta pelo
campo: sem estilo, sorteia uma cor. O lugar do estilo e a tabela layer_styles dentro do
proprio .gpkg (e la que o QGIS grava quando se pede "salvar estilo no banco de dados");
uma linha por camada, marcada como padrao, faz o QGIS aplica-la sozinho ao abrir.
"""
import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing

import ezdxf
import fiona
import pytest

from conversor import convert, previa


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("estilo_gpkg")
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A", "color": 1})      # vermelho
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 1})      # vermelho
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})      # azul
    msp.add_line((40, 0), (50, 10), dxfattribs={"layer": "B"})                # cor da camada: verde
    msp.add_text("rotulo", dxfattribs={"layer": "C", "color": 1}).set_placement((1, 1))
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta


def converter(dxf, nome, **opcoes):
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), nome + ".gpkg")
    opcoes.setdefault("gerar_projeto", False)
    convert.cad_para_qgis(caminho, saida, 31982, formato="GPKG",
                          registrar=lambda *_: None, **opcoes)
    return saida


def tabelas_com_geometria(gpkg):
    """{tabela: coluna da geometria} de gpkg_geometry_columns."""
    with closing(sqlite3.connect(gpkg)) as con:
        return dict(con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns"))


def estilos(gpkg):
    """{tabela: linha de layer_styles}."""
    with closing(sqlite3.connect(gpkg)) as con:
        tem = con.execute("SELECT count(*) FROM sqlite_master "
                          "WHERE type = 'table' AND name = 'layer_styles'").fetchone()[0]
        assert tem, "o .gpkg nao tem a tabela layer_styles"
        con.row_factory = sqlite3.Row
        return {linha["f_table_name"]: dict(linha)
                for linha in con.execute("SELECT * FROM layer_styles")}


def qml(gpkg, tabela):
    return ET.fromstring(estilos(gpkg)[tabela]["styleQML"].encode("utf-8"))


def cores_dos_simbolos(raiz):
    """{nome do simbolo: cor da linha 'r,g,b,a'} de todos os simbolos do estilo."""
    return {s.get("name"): next(p.get("v") for p in s.iter("prop") if p.get("k") == "line_color")
            for s in raiz.iter("symbol")}


def test_cada_camada_do_gpkg_tem_o_seu_estilo_padrao(dxf):
    gpkg = converter(dxf, "um")
    geometrias = tabelas_com_geometria(gpkg)
    achados = estilos(gpkg)
    assert set(achados) == set(geometrias), "um estilo por camada -> %s" % sorted(achados)
    for tabela, linha in achados.items():
        assert linha["useAsDefault"] == 1, "o QGIS so aplica sozinho o estilo padrao"
        assert linha["f_geometry_column"] == geometrias[tabela]
        # o QGIS procura o estilo por f_table_schema = '' (NULL nao casa)
        assert linha["f_table_schema"] == "" and linha["f_table_catalog"] == ""


def test_o_estilo_do_gpkg_tem_as_cores_do_autocad(dxf):
    gpkg = converter(dxf, "dois")
    so_verde = qml(gpkg, "B_LineString")
    assert so_verde.find("renderer-v2").get("type") == "singleSymbol"
    assert list(cores_dos_simbolos(so_verde).values()) == ["0,255,0,255"], "verde, como no AutoCAD"

    renderizador = qml(gpkg, "A_LineString").find("renderer-v2")
    assert renderizador.get("type") == "categorizedSymbol"
    assert renderizador.get("attr") == "cor_cad"
    categorias = {c.get("value"): c.get("symbol") for c in renderizador.iter("category")}
    assert set(categorias) == {"#ff0000", "#0000ff"}
    cores = cores_dos_simbolos(renderizador)
    assert cores[categorias["#ff0000"]] == "255,0,0,255"
    assert cores[categorias["#0000ff"]] == "0,0,255,255"


def test_uma_linha_escolhida_no_desenho_leva_a_cor_dela(dxf):
    """O caso de quem escolhe uma linha so na previa e converte para GeoPackage."""
    caminho, _pasta = dxf
    desenho = previa.ler(caminho)
    grupo = desenho.achar_grupo(5, 9, 0.5, "A")
    assert grupo is not None, "nao achei a linha azul"
    gpkg = converter(dxf, "tres", camadas=set(), feicoes_escolhidas=set(desenho.grupos[grupo].fids))
    raiz = qml(gpkg, "A_LineString")
    assert raiz.find("renderer-v2").get("type") == "singleSymbol"
    assert list(cores_dos_simbolos(raiz).values()) == ["0,0,255,255"], "azul, como no AutoCAD"


def test_camada_de_texto_do_gpkg_leva_os_rotulos(dxf):
    raiz = qml(converter(dxf, "quatro"), "C_Texto")
    assert raiz.find("renderer-v2").get("type") == "nullSymbol"
    assert raiz.find("labeling") is not None, "rotulos do texto"
    assert raiz.get("labelsEnabled") == "1", "rotulos ligados"


def test_o_estilo_vai_dentro_tambem_quando_se_cria_o_projeto(dxf):
    gpkg = converter(dxf, "cinco", gerar_projeto=True)
    assert set(estilos(gpkg)) == set(tabelas_com_geometria(gpkg))
    assert os.path.exists(os.path.splitext(gpkg)[0] + ".qgs")


def test_a_tabela_de_estilo_nao_aparece_como_camada(dxf):
    """Quem traz o .gpkg de volta para o AutoCAD escolhe entre camadas de dados; a
    tabela de estilo do QGIS nao tem geometria nem e dado do desenho."""
    gpkg = converter(dxf, "seis")
    assert "layer_styles" in fiona.listlayers(gpkg), "o GDAL ve a tabela de estilo"
    assert "layer_styles" not in convert.listar_camadas(gpkg)
    assert set(convert.listar_camadas(gpkg)) == set(tabelas_com_geometria(gpkg))
