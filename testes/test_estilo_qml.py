# -*- coding: utf-8 -*-
"""
A cor do AutoCAD tem de chegar ao QGIS mesmo quando so o .shp e arrastado.

Um shapefile nao guarda estilo: aberto sozinho, o QGIS sorteia uma cor. O .qgs
resolve, mas quem arrasta o .shp nunca o abre. O QGIS carrega sozinho um .qml com
o mesmo nome do arquivo que fica ao lado do dado; e la que a cor vai.
"""
import glob
import os
import xml.etree.ElementTree as ET

import ezdxf
import pytest

from conversor import convert


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("qml")
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    for y in (0, 5, 7):
        msp.add_line((0, y), (10, y), dxfattribs={"layer": "A", "color": 1})      # vermelho
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "A", "color": 5})          # azul
    msp.add_line((40, 0), (50, 10), dxfattribs={"layer": "B"})                    # cor da camada: verde
    msp.add_text("rotulo", dxfattribs={"layer": "C", "color": 1}).set_placement((1, 1))
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, pasta


def converter(dxf, nome, formato="ESRI Shapefile", **opcoes):
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), nome)
    convert.cad_para_qgis(caminho, saida, 31982, formato=formato, gerar_projeto=False,
                          registrar=lambda *_: None, **opcoes)
    return os.path.splitext(saida)[0]


def estilo(pasta, camada):
    return ET.parse(os.path.join(pasta, camada + ".qml")).getroot()


def cores_dos_simbolos(raiz):
    """{nome do simbolo: cor da linha 'r,g,b,a'} de todos os simbolos do estilo."""
    return {s.get("name"): next(p.get("v") for p in s.iter("prop") if p.get("k") == "line_color")
            for s in raiz.iter("symbol")}


def test_cada_shapefile_ganha_um_qml_com_o_mesmo_nome(dxf):
    pasta = converter(dxf, "um")
    shps = sorted(os.path.splitext(os.path.basename(f))[0]
                  for f in glob.glob(os.path.join(pasta, "*.shp")))
    qmls = sorted(os.path.splitext(os.path.basename(f))[0]
                  for f in glob.glob(os.path.join(pasta, "*.qml")))
    assert shps and qmls == shps, "um .qml por .shp -> %s vs %s" % (qmls, shps)


def test_camada_de_uma_cor_so_e_pintada_com_essa_cor(dxf):
    raiz = estilo(converter(dxf, "dois"), "B_LineString")
    assert raiz.tag == "qgis", "elemento raiz e <qgis>"
    assert raiz.find("renderer-v2").get("type") == "singleSymbol"
    assert list(cores_dos_simbolos(raiz).values()) == ["0,255,0,255"], "verde, como no AutoCAD"


def test_camada_com_varias_cores_e_categorizada_pelo_campo_da_cor(dxf):
    renderizador = estilo(converter(dxf, "tres"), "A_LineString").find("renderer-v2")
    assert renderizador.get("type") == "categorizedSymbol"
    assert renderizador.get("attr") == "cor_cad", "o campo que o .dbf realmente tem"
    categorias = {c.get("value"): c.get("symbol") for c in renderizador.iter("category")}
    assert set(categorias) == {"#ff0000", "#0000ff"}
    cores = cores_dos_simbolos(renderizador)
    assert cores[categorias["#ff0000"]] == "255,0,0,255"
    assert cores[categorias["#0000ff"]] == "0,0,255,255"


def test_camada_de_texto_leva_os_rotulos_e_nao_desenha_simbolo(dxf):
    raiz = estilo(converter(dxf, "quatro"), "C_Texto")
    assert raiz.find("renderer-v2").get("type") == "nullSymbol"
    assert raiz.find("labeling") is not None, "rotulos do texto"
    assert raiz.get("labelsEnabled") == "1", "rotulos ligados"


def test_o_qml_nao_depende_do_projeto_qgs(dxf):
    """Marcando ou nao 'criar o .qgs', o estilo ao lado do dado tem de existir."""
    caminho, pasta = dxf
    saida = os.path.join(str(pasta), "cinco")
    convert.cad_para_qgis(caminho, saida, 31982, formato="ESRI Shapefile",
                          gerar_projeto=True, registrar=lambda *_: None)
    assert os.path.exists(os.path.join(saida, "B_LineString.qml"))


def test_com_separar_por_cor_cada_arquivo_leva_a_sua_cor(dxf):
    pasta = converter(dxf, "seis", separar_por_cor={"A", "B"})
    verdes = estilo(pasta, "B_verde_LineString")
    assert list(cores_dos_simbolos(verdes).values()) == ["0,255,0,255"]
    azul = [os.path.basename(f) for f in glob.glob(os.path.join(pasta, "A_*azul*.qml"))]
    assert azul, "a camada A separada tem o .qml do azul -> %s" % os.listdir(pasta)


def test_geopackage_nao_ganha_qml(dxf):
    """No GPKG o estilo mora dentro do arquivo; um .qml serviria a todas as camadas."""
    pasta = converter(dxf, "sete.gpkg", formato="GPKG")
    caminho, pasta_dxf = dxf
    assert not glob.glob(os.path.join(str(pasta_dxf), "*.qml"))
    assert not glob.glob(pasta + "*.qml")
