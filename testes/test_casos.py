# -*- coding: utf-8 -*-
"""Constroi a janela e exercita reprojecao, avisos e erros."""
import os
import shutil

import fiona
import pytest
from fiona.crs import CRS

from conversor import config, convert

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_saida", "casos")


@pytest.fixture(scope="module")
def pasta():
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    return BASE


@pytest.fixture(scope="module")
def wgs(pasta):
    """Um ponto em WGS84 (graus), no RS."""
    caminho = os.path.join(pasta, "wgs.geojson")
    with fiona.open(caminho, "w", driver="GeoJSON", crs=CRS.from_epsg(4326),
                    schema={"geometry": "Point", "properties": {"nome": "str"}}) as c:
        c.write({"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": (-51.90984, -29.71904)},
                 "properties": {"nome": "ponto1"}})
    return caminho


@pytest.fixture(scope="module")
def sem_prj(pasta):
    """Shapefile sem .prj: o programa nao tem como saber o sistema de coordenadas."""
    pasta_shp = os.path.join(pasta, "semprj")
    os.makedirs(pasta_shp)
    shp = os.path.join(pasta_shp, "x.shp")
    with fiona.open(shp, "w", driver="ESRI Shapefile", crs=None,
                    schema={"geometry": "Point", "properties": {"a": "str"}}) as c:
        c.write({"type": "Feature", "geometry": {"type": "Point", "coordinates": (1.0, 2.0)},
                 "properties": {"a": "b"}})
    prj = os.path.join(pasta_shp, "x.prj")
    if os.path.exists(prj):
        os.remove(prj)
    return shp


@pytest.fixture(scope="module")
def ok_dxf(pasta, sem_prj):
    """A mesma camada sem .prj, convertida depois de o usuario declarar o CRS."""
    dxf = os.path.join(pasta, "ok.dxf")
    res = convert.qgis_para_cad([{"caminho": sem_prj, "camada": None}], dxf, 31982,
                                epsg_origem_forcado=31982, registrar=lambda *_: None)
    return res, dxf


@pytest.fixture(scope="module")
def acentos(pasta):
    """Camada com acentos nos valores que viram nome de camada do desenho."""
    gpkg = os.path.join(pasta, "ac.gpkg")
    with fiona.open(gpkg, "w", driver="GPKG", layer="u", crs=CRS.from_epsg(31982),
                    schema={"geometry": "Point", "properties": {"unidade": "str"}}) as c:
        for u in ["Formação Serra Geral", "Intrusão Ácida", "Seção A-A"]:
            c.write({"type": "Feature",
                     "geometry": {"type": "Point", "coordinates": (400000.0, 6700000.0)},
                     "properties": {"unidade": u}})
    dxf = os.path.join(pasta, "ac.dxf")
    res = convert.qgis_para_cad([{"caminho": gpkg, "camada": "u"}], dxf, 31982,
                                campo_camada="unidade", registrar=lambda *_: None)
    return res, dxf


# ---------------------------------------------------------------- 1. interface
def test_janela_monta_e_avisa_sobre_crs_em_graus(monkeypatch, tmp_path):
    tk = pytest.importorskip("tkinter")
    # As preferencias de quem roda os testes nao entram nem saem do teste.
    monkeypatch.setattr(config, "PASTA", str(tmp_path))
    monkeypatch.setattr(config, "ARQUIVO", str(tmp_path / "config.json"))
    # A janela nasce escondida: nada aparece na tela de quem roda os testes.
    original = tk.Tk.__init__

    def nasce_escondida(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.withdraw()

    monkeypatch.setattr(tk.Tk, "__init__", nasce_escondida)
    from conversor.gui import App
    try:
        app = App()
    except tk.TclError as erro:
        pytest.skip("sem ambiente grafico: %s" % erro)
    try:
        app.update_idletasks()
        abas = app.winfo_children()
        app.aba1._atualizar_derivados()
        app.aba2._alternar_reproj()
        app.aba1._alternar_origem()
        app.registrar("teste")
        app.aba1.crs_destino.definir(4326)
        aviso_graus = app.aba1.crs_destino.aviso.cget("text")
        app.aba1.crs_destino.definir(31982)
        aviso_utm = app.aba1.crs_destino.aviso.cget("text")
    finally:
        app.destroy()
    assert abas, "janela monta e destroi sem erro"
    assert "graus" in aviso_graus, "avisa ao escolher CRS em graus"
    assert aviso_utm == "", "nao avisa em UTM"


# ---------------------------------------------------------------- 2. reprojecao
def test_reprojecao_wgs84_graus_para_utm_22s(pasta, wgs):
    dxf = os.path.join(pasta, "reproj.dxf")
    avisos = []
    convert.qgis_para_cad([{"caminho": wgs, "camada": None}], dxf, 31982,
                          registrar=avisos.append)
    with fiona.open(dxf) as c:
        xy = [f["geometry"]["coordinates"] for f in c][0]
    assert 400000 < xy[0] < 500000 and 6_000_000 < xy[1] < 7_000_000, \
        "reprojetou para metros -> %.1f, %.1f" % (xy[0], xy[1])
    assert any("reprojetando" in a for a in avisos), "registrou a reprojecao"


def test_aviso_ao_gravar_desenho_em_graus(pasta, wgs):
    avisos = []
    convert.qgis_para_cad([{"caminho": wgs, "camada": None}],
                          os.path.join(pasta, "graus.dxf"), 4326, registrar=avisos.append)
    assert any("graus" in a for a in avisos), "avisa que graus nao serve p/ AutoCAD"


# ---------------------------------------------------------------- 4. sem .prj
def test_erro_claro_quando_falta_prj(pasta, sem_prj):
    with pytest.raises(convert.ErroConversao) as erro:
        convert.qgis_para_cad([{"caminho": sem_prj, "camada": None}],
                              os.path.join(pasta, "n.dxf"), 31982, registrar=lambda *_: None)
    assert "sistema de coordenadas" in str(erro.value), "erro claro quando falta .prj"


def test_converte_quando_o_usuario_declara_o_crs(ok_dxf):
    res, _ = ok_dxf
    assert res["feicoes"] == 1, "converte quando o usuario declara o CRS"


# ---------------------------------------------------------------- 5. DXF vazio
def test_erro_claro_em_desenho_sem_geometria(pasta, ok_dxf):
    _, ok = ok_dxf
    vazio = os.path.join(pasta, "vazio.dxf")
    shutil.copy(ok, vazio)
    with open(vazio, encoding="utf-8", errors="replace") as fp:
        corpo = fp.read()
    i = corpo.find("\nENTITIES\n")
    j = corpo.find("\n  0\nENDSEC", i)
    with open(vazio, "w", encoding="utf-8") as fp:
        fp.write(corpo[:i + len("\nENTITIES\n")] + corpo[j + 1:])
    with pytest.raises(convert.ErroConversao) as erro:
        convert.cad_para_qgis(vazio, os.path.join(pasta, "v.gpkg"), 31982,
                              registrar=lambda *_: None)
    assert "Nenhuma geometria" in str(erro.value), "erro claro em desenho vazio"


# ---------------------------------------------------------------- 6. acentos
def test_dxf_ascii_e_nomes_de_camada_transliterados(acentos):
    res, dxf = acentos
    with open(dxf, "rb") as fp:
        raw = fp.read()
    assert all(b < 128 for b in raw), "DXF ficou ASCII puro"
    assert res["camadas"] == ["Formacao_Serra_Geral", "Intrusao_Acida", "Secao_A-A"], \
        "camadas transliteradas -> %s" % res["camadas"]


# ---------------------------------------------------------------- 7. CSV
def test_csv_de_atributos_guarda_o_texto_original(pasta, acentos):
    csv = os.path.join(pasta, "ac_atributos.csv")
    assert os.path.exists(csv), "csv gerado"
    with open(csv, encoding="utf-8-sig") as fp:
        txt = fp.read()
    assert "Formação Serra Geral" in txt, "csv preserva o acento original"
    assert ";" in txt.splitlines()[0], "csv usa ; (Excel pt-BR)"
