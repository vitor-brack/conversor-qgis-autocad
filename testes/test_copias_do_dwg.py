# -*- coding: utf-8 -*-
"""
O .dwg passa pelo ODA File Converter, que trabalha numa pasta do TEMP (conv_dwg_* ou
conv_dxf_*) com uma copia do desenho do cliente. Essa pasta tem de sumir quando o trabalho
acaba -- deu certo ou nao. Antes ficava la:
  - na conversao para o QGIS sem o painel de camadas ("Escolher as camadas" desmarcado, ou
    pela linha de comando);
  - quando o ODA falhava ou nao gerava nada;
  - quando o painel lia o DWG e a leitura falhava depois do ODA;
  - ao gravar .dwg (QGIS -> AutoCAD).
O DXF que o painel ja converteu (dxf_pronto) e dele: a conversao nao o apaga.

O ODA aqui e de mentira (copia um DXF pronto), entao os testes rodam sem ele instalado.
"""
import glob
import os
import shutil
import tempfile
import time

import ezdxf
import pytest

from conversor import convert, dwg


@pytest.fixture
def temp(tmp_path, monkeypatch):
    """Um TEMP so do teste, para ver o que sobra nele."""
    pasta = tmp_path / "temp"
    pasta.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(pasta))
    return pasta


@pytest.fixture
def desenho(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("A")
    doc.modelspace().add_line((448000, 6743000), (448100, 6743000), dxfattribs={"layer": "A"})
    dxf = str(tmp_path / "pronto.dxf")
    doc.saveas(dxf)
    dwg_falso = tmp_path / "obra.dwg"
    dwg_falso.write_bytes(b"AC1018 desenho de mentira")
    return str(dwg_falso), dxf


@pytest.fixture
def oda(monkeypatch, desenho):
    """O ODA de mentira: do DWG faz o DXF pronto; do DXF faz um .dwg qualquer."""
    chamadas = []

    def executar(entrada_dir, saida_dir, versao, formato, filtro):
        chamadas.append(formato)
        for nome in os.listdir(entrada_dir):
            base = os.path.splitext(nome)[0]
            if formato == "DXF":
                shutil.copy(desenho[1], os.path.join(saida_dir, base + ".dxf"))
            else:
                with open(os.path.join(saida_dir, base + ".dwg"), "wb") as f:
                    f.write(b"AC1018")

    monkeypatch.setattr(dwg, "_executar", executar)
    monkeypatch.setattr(dwg, "disponivel", lambda: True)
    return chamadas


def sobras(temp):
    return sorted(os.path.basename(p) for p in glob.glob(str(temp / "conv_*")))


def converter(entrada, saida, **opcoes):
    return convert.cad_para_qgis(entrada, saida, 31982, formato="GPKG", gerar_projeto=False,
                                 registrar=lambda *_: None, **opcoes)


def test_converter_dwg_sem_o_painel_apaga_a_copia_do_desenho(temp, desenho, oda, tmp_path):
    saida = str(tmp_path / "saida.gpkg")
    resultado = converter(desenho[0], saida)
    assert resultado["feicoes"] == 1 and os.path.exists(saida)
    assert oda == ["DXF"]
    assert sobras(temp) == [], "a copia do desenho do cliente ficou no TEMP"


def test_conversao_que_falha_no_meio_tambem_apaga_a_copia(temp, desenho, oda, tmp_path,
                                                          monkeypatch):
    def quebra(*_a, **_k):
        raise RuntimeError("falhou no meio")
    monkeypatch.setattr(convert.dxf_extras, "ler", quebra)
    with pytest.raises(RuntimeError):
        converter(desenho[0], str(tmp_path / "saida.gpkg"))
    assert sobras(temp) == []


def test_o_dxf_que_o_painel_ja_converteu_nao_e_apagado(temp, desenho, oda, tmp_path):
    do_painel = dwg.dwg_para_dxf(desenho[0])          # como o painel faz
    converter(desenho[0], str(tmp_path / "saida.gpkg"), dxf_pronto=do_painel)
    assert os.path.exists(do_painel), "o painel ainda usa esse DXF"
    assert oda == ["DXF"], "e o ODA nao roda de novo"


def test_oda_que_nao_gera_nada_nao_deixa_copia(temp, desenho, monkeypatch):
    monkeypatch.setattr(dwg, "_executar", lambda *a: None)
    with pytest.raises(dwg.ErroDWG):
        dwg.dwg_para_dxf(desenho[0])
    assert sobras(temp) == []


def test_oda_que_falha_nao_deixa_copia(temp, desenho, monkeypatch):
    def demora(*_a):
        raise dwg.ErroDWG("demorou demais")
    monkeypatch.setattr(dwg, "_executar", demora)
    with pytest.raises(dwg.ErroDWG):
        dwg.dwg_para_dxf(desenho[0])
    assert sobras(temp) == []


def test_gravar_dwg_apaga_a_pasta_do_oda(temp, desenho, oda, tmp_path):
    final = str(tmp_path / "entrega.dwg")
    assert dwg.dxf_para_dwg(desenho[1], final) == final
    assert os.path.exists(final)
    assert sobras(temp) == [], "a copia do DXF ficou no TEMP"


def test_painel_que_nao_consegue_ler_o_dwg_apaga_a_copia(raiz, temp, desenho, oda, monkeypatch):
    from conversor import gui_camadas

    def quebra(*_a, **_k):
        raise RuntimeError("nao li")
    monkeypatch.setattr(gui_camadas.previa, "ler", quebra)
    painel = gui_camadas.PainelCamadas(raiz)
    try:
        painel.carregar(desenho[0])
        fim = time.time() + 15
        while painel.estado != "erro" and time.time() < fim:
            raiz.update()
            time.sleep(0.02)
        assert painel.estado == "erro"
        assert sobras(temp) == [], "a copia do DWG ficou no TEMP"
    finally:
        painel.destroy()
