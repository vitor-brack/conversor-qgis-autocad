# -*- coding: utf-8 -*-
"""
A aba AutoCAD -> QGIS com o painel de camadas: da caixinha ate o arquivo gravado.

Usa um "app" de mentira que guarda a tarefa em vez de roda-la numa thread; o
teste a executa e confere o que foi gravado de verdade.
"""
import os
import time
import tkinter as tk

import fiona
import pytest

import gerar_camadas
from conversor import config


class AppFalso:
    def __init__(self):
        self.cfg = dict(config.PADROES)
        self.tarefa = None

    def registrar(self, _texto):
        pass

    def executar(self, _botao, tarefa):
        self.tarefa = tarefa


@pytest.fixture
def aba(raiz, monkeypatch):
    from conversor import gui
    avisos = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda t, m, **_: avisos.append((t, m)))
    app = AppFalso()
    a = gui.AbaCadParaQgis(raiz, app)
    a.app_falso, a.avisos = app, avisos
    yield a
    a.destroy()


@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("aba_camadas")
    caminho, _ = gerar_camadas.gerar(str(pasta / "d"))
    return caminho, pasta


def esperar(raiz, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        raiz.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def escolher(aba, caminho, saida):
    aba.entrada.delete(0, tk.END)
    aba.entrada.insert(0, caminho)
    aba.saida.delete(0, tk.END)
    aba.saida.insert(0, saida)


def ligar(aba, raiz, caminho, saida):
    escolher(aba, caminho, saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto"), aba.painel.estado


# ---------------------------------------------------------------------------
def test_a_opcao_comeca_desligada_e_o_painel_escondido(aba):
    assert aba.escolher_camadas.get() is False
    assert not aba.painel.winfo_manager(), "o painel so aparece quando a pessoa pede"


def test_ligar_a_opcao_mostra_o_painel_e_le_o_desenho(aba, raiz, dxf):
    ligar(aba, raiz, dxf[0], str(dxf[1] / "s.gpkg"))
    assert aba.painel.winfo_manager() == "grid"
    assert "Pontos" in aba.painel.nomes_na_lista()


def test_converte_so_as_camadas_marcadas(aba, raiz, dxf):
    caminho, pasta = dxf
    saida = str(pasta / "so_pontos.gpkg")
    ligar(aba, raiz, caminho, saida)
    aba.painel.desmarcar_todas()
    aba.painel.alternar("Pontos")
    aba.converter()
    assert aba.app_falso.tarefa is not None, "a conversao foi pedida -> avisos: %s" % aba.avisos
    aba.app_falso.tarefa(lambda *_: None)
    assert fiona.listlayers(saida) == ["Pontos_Point"], fiona.listlayers(saida)


def test_dxf_temporario_fica_protegido_desde_o_clique_em_converter(aba, raiz, dxf):
    # se a protecao so comecasse dentro da thread, trocar de desenho entre o clique
    # e o inicio da thread apagaria o DXF que a conversao vai usar
    ligar(aba, raiz, dxf[0], str(dxf[1] / "protegido.gpkg"))
    aba.painel.alternar("Pontos")
    aba.converter()
    assert aba.painel.em_uso == 1, "protegido ja no clique -> %d" % aba.painel.em_uso
    aba.app_falso.tarefa(lambda *_: None)
    assert aba.painel.em_uso == 0, "e liberado quando a conversao termina -> %d" % aba.painel.em_uso


def _dxf_com_cores(pasta):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("B", color=3)
    msp = doc.modelspace()
    for y in (0, 5, 7):
        msp.add_line((0, y), (100, y), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 30), (100, 30), dxfattribs={"layer": "A", "color": 5})
    msp.add_line((0, 60), (100, 60), dxfattribs={"layer": "B"})
    caminho = str(pasta / "cores.dxf")
    doc.saveas(caminho)
    return caminho


def test_converte_separando_a_camada_por_cor(aba, raiz, tmp_path):
    saida = str(tmp_path / "por_cor.gpkg")
    escolher(aba, _dxf_com_cores(tmp_path), saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    aba.painel.separar_por_cor.set(True)
    aba.painel.alternar(("A", "#ff0000"))
    aba.painel.alternar(("A", "#0000ff"))
    aba.painel.alternar(("B", "#00ff00"))
    aba.converter()
    assert aba.app_falso.tarefa is not None, "avisos: %s" % aba.avisos
    aba.app_falso.tarefa(lambda *_: None)
    assert fiona.listlayers(saida) == ["A_vermelho_LineString", "A_azul_LineString",
                                       "B_LineString"] or sorted(fiona.listlayers(saida)) ==         ["A_azul_LineString", "A_vermelho_LineString", "B_LineString"], fiona.listlayers(saida)


def test_converte_so_a_cor_marcada_de_uma_camada(aba, raiz, tmp_path):
    saida = str(tmp_path / "so_azul.gpkg")
    escolher(aba, _dxf_com_cores(tmp_path), saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    aba.painel.separar_por_cor.set(True)
    aba.painel.alternar(("A", "#0000ff"))
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert fiona.listlayers(saida) == ["A_azul_LineString"], fiona.listlayers(saida)
    with fiona.open(saida, layer="A_azul_LineString") as f:
        assert len(f) == 1, "so a linha azul"


def _arquivos_shp(pasta):
    import glob
    return sorted(os.path.basename(a)[:-4] for a in glob.glob(os.path.join(pasta, "*.shp")))


def test_juntar_por_tipo_sem_textos_e_hachuras_pela_janela(aba, dxf):
    caminho, pasta = dxf
    saida = str(pasta / "tres_arquivos")
    escolher(aba, caminho, saida)
    aba.formato.set("ESRI Shapefile")
    aba.separar.set(False)                     # juntar as camadas por tipo
    aba.sem_textos.set(True)
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert _arquivos_shp(saida) == ["LineString", "Point"],         "so linhas e pontos, sem Texto nem Hachura -> %s" % _arquivos_shp(saida)


def test_a_opcao_de_nao_levar_textos_comeca_desligada(aba, dxf):
    assert aba.sem_textos.get() is False
    caminho, pasta = dxf
    saida = str(pasta / "com_textos")
    escolher(aba, caminho, saida)
    aba.formato.set("ESRI Shapefile")
    aba.separar.set(False)
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert {"Texto", "Hachura"} <= set(_arquivos_shp(saida)), _arquivos_shp(saida)


def test_a_opcao_fica_guardada_para_a_proxima_vez(aba, dxf):
    caminho, pasta = dxf
    escolher(aba, caminho, str(pasta / "guarda"))
    aba.sem_textos.set(True)
    aba.converter()
    assert aba.app_falso.cfg["sem_textos_e_hachuras"] is True


def _clicar_na_linha(painel, x, y):
    painel.ver_tudo()
    px, py = painel.vista.para_tela(x, y)
    painel.clicar(int(round(px)), int(round(py)))


def test_converte_so_a_linha_clicada_no_desenho(aba, raiz, tmp_path):
    saida = str(tmp_path / "so_a_linha.gpkg")
    escolher(aba, _dxf_com_cores(tmp_path), saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    _clicar_na_linha(aba.painel, 50, 30)                 # a linha azul da camada A
    assert aba.painel.marcadas == set() and len(aba.painel.escolhidas) == 1
    aba.converter()
    assert aba.app_falso.tarefa is not None, \
        "so a linha clicada ja basta para converter -> avisos: %s" % aba.avisos
    aba.app_falso.tarefa(lambda *_: None)
    assert fiona.listlayers(saida) == ["A_LineString"], fiona.listlayers(saida)
    with fiona.open(saida, layer="A_LineString") as f:
        linhas = [ft["geometry"]["coordinates"] for ft in f]
    assert len(linhas) == 1 and round(linhas[0][0][1]) == 30, \
        "so a linha azul, sem as 3 vermelhas da mesma camada -> %s" % linhas


def test_linha_clicada_soma_com_a_camada_marcada_na_lista(aba, raiz, tmp_path):
    saida = str(tmp_path / "soma.gpkg")
    escolher(aba, _dxf_com_cores(tmp_path), saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    _clicar_na_linha(aba.painel, 50, 30)
    aba.painel.alternar("B")
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert sorted(fiona.listlayers(saida)) == ["A_LineString", "B_LineString"], \
        fiona.listlayers(saida)


def test_linha_clicada_com_a_camada_separada_por_cor_sai_com_o_nome_da_cor(aba, raiz, tmp_path):
    saida = str(tmp_path / "por_cor_clicada.gpkg")
    escolher(aba, _dxf_com_cores(tmp_path), saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    aba.painel.separar_por_cor.set(True)
    _clicar_na_linha(aba.painel, 50, 30)
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert fiona.listlayers(saida) == ["A_azul_LineString"], fiona.listlayers(saida)


def test_o_log_diz_quantas_linhas_foram_escolhidas_no_desenho(aba, raiz, tmp_path):
    escolher(aba, _dxf_com_cores(tmp_path), str(tmp_path / "log.gpkg"))
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    _clicar_na_linha(aba.painel, 50, 30)
    aba.converter()
    log = []
    aba.app_falso.tarefa(log.append)
    assert any("1 linha" in linha and "desenho" in linha for linha in log), log


def test_converter_sem_camada_marcada_avisa_e_nao_converte(aba, raiz, dxf):
    ligar(aba, raiz, dxf[0], str(dxf[1] / "nada.gpkg"))
    aba.painel.desmarcar_todas()
    aba.converter()
    assert aba.app_falso.tarefa is None
    assert aba.avisos and "camada" in aba.avisos[-1][1].lower(), aba.avisos
    assert "linha" in aba.avisos[-1][1].lower(), \
        "o aviso diz que tambem da para clicar numa linha do desenho -> %s" % aba.avisos[-1][1]


def test_converter_antes_da_leitura_terminar_pede_para_esperar(aba, raiz, dxf):
    escolher(aba, dxf[0], str(dxf[1] / "cedo.gpkg"))
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert aba.painel.estado == "carregando"
    aba.converter()
    assert aba.app_falso.tarefa is None
    assert aba.avisos and "aguarde" in aba.avisos[-1][1].lower(), aba.avisos
    esperar(raiz, lambda: aba.painel.estado == "pronto")


def test_com_a_opcao_desligada_converte_tudo_como_sempre(aba, raiz, dxf):
    caminho, pasta = dxf
    saida = str(pasta / "tudo.gpkg")
    escolher(aba, caminho, saida)
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    camadas = fiona.listlayers(saida)
    assert "Pontos_Point" in camadas and "Visivel_LineString" in camadas, camadas


def test_desligar_a_opcao_esconde_o_painel(aba, raiz, dxf):
    ligar(aba, raiz, dxf[0], str(dxf[1] / "x.gpkg"))
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    assert not aba.painel.winfo_manager()


def test_trocar_o_desenho_com_o_painel_aberto_le_o_novo(aba, raiz, dxf, tmp_path):
    ligar(aba, raiz, dxf[0], str(dxf[1] / "y.gpkg"))
    outro, _ = gerar_camadas.gerar(str(tmp_path / "outro"))
    os.replace(outro, str(tmp_path / "novo.dxf"))
    escolher(aba, str(tmp_path / "novo.dxf"), str(dxf[1] / "y.gpkg"))
    aba._atualizar_painel()
    assert aba.painel.estado == "carregando", aba.painel.estado
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    assert aba.painel._caminho == str(tmp_path / "novo.dxf")
