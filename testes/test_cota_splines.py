# -*- coding: utf-8 -*-
"""
A cota das curvas de nivel desenhadas como SPLINE.

O GDAL le a spline mas entrega os vertices sem Z, entao a curva chegava ao
QGIS na cota zero (o desenho real tinha 334 splines assim, mais da metade das
curvas de nivel). A cota esta nos pontos de controle do desenho, e e dali que
o conversor passa a tira-la.
"""
import os

import ezdxf
import fiona
import pytest

from conversor import convert

X0, Y0 = 448000.0, 6743000.0


@pytest.fixture(scope="module", params=["GPKG", "ESRI Shapefile"])
def curvas(request, tmp_path_factory):
    """(camada -> cotas dos vertices) da conversao de um DXF com duas splines."""
    pasta = tmp_path_factory.mktemp("spline_" + request.param.split()[0])
    doc = ezdxf.new("R2010")
    for nome in ("CURVAS", "RAMPA"):
        doc.layers.add(nome)
    msp = doc.modelspace()
    # curva de nivel: cota constante em todos os pontos de controle
    msp.add_open_spline(degree=3, dxfattribs={"layer": "CURVAS"}, control_points=[
        (X0, Y0, 520.0), (X0 + 30, Y0 + 40, 520.0), (X0 + 70, Y0 - 10, 520.0),
        (X0 + 100, Y0 + 20, 520.0)])
    # rampa: a cota sobe de 500 a 510 ao longo da spline
    msp.add_open_spline(degree=3, dxfattribs={"layer": "RAMPA"}, control_points=[
        (X0, Y0 + 100, 500.0), (X0 + 30, Y0 + 140, 503.0), (X0 + 70, Y0 + 90, 507.0),
        (X0 + 100, Y0 + 120, 510.0)])
    dxf = str(pasta / "d.dxf")
    doc.saveas(dxf)
    saida = str(pasta / ("s.gpkg" if request.param == "GPKG" else "s"))
    convert.cad_para_qgis(dxf, saida, 31982, formato=request.param, gerar_projeto=False,
                          registrar=lambda *_: None)

    def cotas(camada):
        if request.param == "GPKG":
            f = fiona.open(saida, layer=camada)
        else:
            f = fiona.open(os.path.join(saida, camada + ".shp"))
        with f:
            return [v[2] if len(v) > 2 else 0.0
                    for ft in f for v in ft["geometry"]["coordinates"]]
    return cotas


def test_spline_de_curva_de_nivel_mantem_a_cota(curvas):
    z = curvas("CURVAS_LineString")
    assert len(z) > 4, "a spline virou uma linha com varios vertices -> %d" % len(z)
    assert all(abs(v - 520.0) < 1e-6 for v in z), \
        "todos os vertices na cota 520 (era zero) -> %s" % sorted(set(round(v, 3) for v in z))


def test_spline_com_cota_variavel_vai_de_500_a_510_em_ordem(curvas):
    z = curvas("RAMPA_LineString")
    assert abs(z[0] - 500.0) < 1e-6 and abs(z[-1] - 510.0) < 1e-6, \
        "comeca em 500 e termina em 510 -> %.3f ... %.3f" % (z[0], z[-1])
    assert all(b >= a - 1e-9 for a, b in zip(z, z[1:])), "a cota so sobe ao longo da spline"
