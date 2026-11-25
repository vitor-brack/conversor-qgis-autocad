# -*- coding: utf-8 -*-
"""
A cota (Z) das curvas de nivel e dos pontos altimetricos tem que sobreviver no
Shapefile. O GeoPackage sempre guardou; o Shapefile gravava X e Y e jogava a
cota fora, porque a camada era declarada 2D.
"""
import os

import ezdxf
import fiona
import pytest

from conversor import convert

X0, Y0 = 448000.0, 6743000.0


@pytest.fixture(scope="module")
def shapefiles(tmp_path_factory):
    """Um DXF com curvas e um ponto com cota, e uma linha sem cota nenhuma."""
    pasta = tmp_path_factory.mktemp("cota")
    doc = ezdxf.new("R2010")
    for nome in ("CURVAS", "PONTOS", "PLANA"):
        doc.layers.add(nome)
    msp = doc.modelspace()
    msp.add_lwpolyline([(X0, Y0), (X0 + 50, Y0 + 10), (X0 + 100, Y0)],
                       dxfattribs={"layer": "CURVAS", "elevation": 520.0})
    # na mesma camada, uma curva a zero metros: nao pode se perder nem dar erro
    msp.add_lwpolyline([(X0, Y0 + 200), (X0 + 50, Y0 + 210)],
                       dxfattribs={"layer": "CURVAS", "elevation": 0.0})
    msp.add_point((X0 + 10, Y0 + 10, 533.25), dxfattribs={"layer": "PONTOS"})
    msp.add_lwpolyline([(X0, Y0 + 100), (X0 + 50, Y0 + 110)], dxfattribs={"layer": "PLANA"})
    dxf = str(pasta / "d.dxf")
    doc.saveas(dxf)
    saida = str(pasta / "saida")
    convert.cad_para_qgis(dxf, saida, 31982, formato="ESRI Shapefile",
                          gerar_projeto=False, registrar=lambda *_: None)
    return os.path.join(saida)


def abrir(pasta, nome):
    with fiona.open(os.path.join(pasta, nome + ".shp")) as f:
        return f.schema["geometry"], [ft["geometry"]["coordinates"] for ft in f]


def test_curvas_de_nivel_guardam_a_cota_no_shapefile(shapefiles):
    geometria, linhas = abrir(shapefiles, "CURVAS_LineString")
    assert geometria == "3D LineString", \
        "a camada de curvas e 3D (a cota esta no Z) -> %s" % geometria
    cotas = sorted({round(v[2], 3) for linha in linhas for v in linha})
    assert cotas == [0.0, 520.0], \
        "as duas curvas chegam, uma na cota 520 e outra a zero -> %s" % cotas


def test_pontos_altimetricos_guardam_a_cota_no_shapefile(shapefiles):
    geometria, pontos = abrir(shapefiles, "PONTOS_Point")
    assert geometria == "3D Point", "a camada de pontos e 3D -> %s" % geometria
    assert round(pontos[0][2], 3) == 533.25, "cota do ponto -> %s" % (pontos[0],)


def test_camada_sem_cota_continua_2d(shapefiles):
    geometria, _ = abrir(shapefiles, "PLANA_LineString")
    assert geometria == "LineString", \
        "sem cota nenhuma, a camada nao vira 3D a toa -> %s" % geometria
