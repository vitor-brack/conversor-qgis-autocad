# -*- coding: utf-8 -*-
"""
A copia do desenho do cliente que o ODA deixa no TEMP tem de sumir mesmo quando a pessoa
fecha o programa (ou desmarca "Escolher as camadas") no MEIO do carregamento.

Quem cria a pasta e a thread de trabalho; o painel so ficava sabendo dela quando a janela
lia a mensagem "ok" da fila, depois da leitura do desenho (uns 10 s no DWG real). Fechar
antes disso -- com o ODA ainda rodando ou com a leitura em andamento -- deixava no TEMP o
DWG e o DXF do cliente, e o painel nem sabia que eles existiam.

O ODA aqui e de mentira (ver test_copias_do_dwg.py); o do primeiro teste e um .cmd de
verdade, para provar que o processo e encerrado.
"""
import glob
import os
import shutil
import tempfile
import threading
import time

import ezdxf
import pytest

from conversor import dwg, previa


@pytest.fixture
def temp(tmp_path, monkeypatch):
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
def oda_instantaneo(monkeypatch, desenho):
    def executar(entrada_dir, saida_dir, versao, formato, filtro):
        for nome in os.listdir(entrada_dir):
            shutil.copy(desenho[1], os.path.join(saida_dir, os.path.splitext(nome)[0] + ".dxf"))

    monkeypatch.setattr(dwg, "_executar", executar)
    monkeypatch.setattr(dwg, "disponivel", lambda: True)


@pytest.fixture
def leitura_travada(monkeypatch):
    """O painel le o desenho so quando o teste mandar (um Event)."""
    from conversor import gui_camadas
    liberada = threading.Event()
    original = previa.ler

    def ler(caminho, *a, **k):
        liberada.wait(30)
        return original(caminho, *a, **k)

    monkeypatch.setattr(gui_camadas.previa, "ler", ler)
    yield liberada
    liberada.set()


def sobras(temp):
    return sorted(os.path.basename(p) for p in glob.glob(str(temp / "conv_*")))


def esperar(raiz, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        raiz.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def test_fechar_com_o_oda_rodando_apaga_a_pasta_e_encerra_o_oda(raiz, temp, desenho, tmp_path,
                                                                 monkeypatch):
    from conversor import gui_camadas
    marcador = tmp_path / "oda_terminou_sozinho.txt"
    falso = tmp_path / "oda_lento.cmd"
    falso.write_text("@echo off\r\nping -n 4 127.0.0.1 >nul\r\necho fim > \"%s\"\r\n" % marcador)
    monkeypatch.setattr(dwg, "localizar_oda", lambda: str(falso))

    painel = gui_camadas.PainelCamadas(raiz)
    try:
        painel.carregar(desenho[0])
        assert esperar(raiz, lambda: sobras(temp)), "o ODA nem comecou"
        painel.liberar(forcar=True)                    # o que App.fechar faz
        assert sobras(temp) == [], "a copia do desenho ficou no TEMP com o ODA rodando"
        time.sleep(4.5)                                # tempo de sobra para o falso terminar
        assert not marcador.exists(), "o ODA continuou rodando depois que o programa fechou"
    finally:
        painel.destroy()


def test_fechar_no_meio_da_leitura_apaga_a_copia(raiz, temp, desenho, oda_instantaneo,
                                                 leitura_travada):
    from conversor import gui_camadas
    painel = gui_camadas.PainelCamadas(raiz)
    try:
        painel.carregar(desenho[0])
        assert esperar(raiz, lambda: glob.glob(str(temp / "conv_dwg_*" / "saida" / "*.dxf")))
        assert painel.estado == "carregando", "a leitura devia estar em andamento"
        painel.liberar(forcar=True)                    # o que App.fechar faz
        assert sobras(temp) == [], "a copia do desenho ficou no TEMP durante a leitura"
    finally:
        painel.destroy()


def _fechar_apaga(caminho):
    """O arquivo existe (a leitura do desenho o criou e ainda nao acabou) e o programa
    fecha: ele nao pode ficar no TEMP."""
    try:
        assert os.path.exists(caminho), "o teste precisava do arquivo temporario criado"
        dwg.encerrar()
        assert not os.path.exists(caminho), "o temporario da leitura ficou no TEMP ao fechar"
    finally:
        if os.path.exists(caminho):
            os.remove(caminho)


def test_fechar_apaga_o_vrt_que_a_leitura_deixou(desenho):
    from conversor import dxf_estilo
    _fechar_apaga(dxf_estilo._escrever_vrt(desenho[1]))


def test_fechar_apaga_a_copia_filtrada_do_ezdxf(desenho):
    from conversor import cad_ezdxf
    copia, _tipos = cad_ezdxf._filtrar(desenho[1], "utf-8")
    _fechar_apaga(copia)


def test_fechar_apaga_a_copia_que_o_gdal_entende(tmp_path):
    from conversor import dxf_estilo
    from test_hachura_spline_gdal import doc_com_hachura_em_spline
    doc, _h, _l = doc_com_hachura_em_spline()
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    copia = dxf_estilo._copia_que_o_gdal_entende(caminho)
    assert copia, "o DXF 2004 com hachura em spline devia ganhar copia corrigida"
    _fechar_apaga(copia)


@pytest.mark.skipif(os.name != "nt", reason="arquivo aberto trava o apagar so no Windows")
def test_arquivo_preso_na_hora_de_fechar_e_apagado_logo_depois_que_o_programa_sai(
        tmp_path, monkeypatch, desenho, oda_instantaneo):
    # a leitura real do desenho segura o DXF aberto; o Windows nao apaga arquivo aberto.
    # Pasta com espaco no nome: o TEMP de muita gente tem.
    pasta_temp = tmp_path / "temp com espaco"
    pasta_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(pasta_temp))
    dxf = dwg.dwg_para_dxf(desenho[0])
    pasta = dwg.pasta_temporaria(dxf)
    preso = open(dxf, "rb")
    try:
        dwg.encerrar()
        assert os.path.isdir(pasta), "o teste precisava do arquivo preso impedindo o apagar"
    finally:
        preso.close()                                  # o programa terminou de sair
    fim = time.time() + 15
    while os.path.isdir(pasta) and time.time() < fim:
        time.sleep(0.2)
    assert not os.path.isdir(pasta), "a copia do desenho ficou no TEMP depois de o programa sair"


def test_desmarcar_no_meio_da_leitura_apaga_a_copia_quando_ela_acaba(raiz, temp, desenho,
                                                                      oda_instantaneo,
                                                                      leitura_travada):
    from conversor import gui_camadas
    painel = gui_camadas.PainelCamadas(raiz)
    try:
        painel.carregar(desenho[0])
        assert esperar(raiz, lambda: glob.glob(str(temp / "conv_dwg_*" / "saida" / "*.dxf")))
        painel.limpar()                                # "Escolher as camadas" desmarcado
        leitura_travada.set()                          # a leitura antiga termina
        assert esperar(raiz, lambda: not sobras(temp)), \
            "a copia de uma leitura descartada ficou no TEMP"
        assert painel.estado == "vazio"
    finally:
        painel.destroy()
