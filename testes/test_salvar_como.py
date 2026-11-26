# -*- coding: utf-8 -*-
"""
O passo "Onde salvar" da aba AutoCAD -> QGIS: a pasta e o nome ficam em campos
separados, para trocar o nome sem ter que apagar o caminho no meio.

Duas partes: as funcoes puras que montam e desmontam o caminho, e o campo na
janela (um Tk escondido, nada aparece na tela).
"""
import os
import tkinter as tk

import pytest

import gerar_camadas
from conversor import config
from conversor.gui_saida import (CampoSaida, dividir_caminho, montar_caminho,
                                 problema_no_nome)

GPKG, SHP, JSON = "GPKG", "ESRI Shapefile", "GeoJSON"
PASTA = os.path.join(os.path.abspath(os.sep), "dados", "obra")


# ---------------------------------------------------------------------------
# funcoes puras
def test_geopackage_ganha_a_extensao():
    assert montar_caminho(PASTA, "planta", GPKG) == os.path.join(PASTA, "planta.gpkg")


@pytest.mark.parametrize("digitado", ["planta.gpkg", "planta.GPKG", "  planta  "])
def test_extensao_digitada_nao_dobra(digitado):
    assert montar_caminho(PASTA, digitado, GPKG) == os.path.join(PASTA, "planta.gpkg")


@pytest.mark.parametrize("formato", [SHP, JSON])
def test_shapefile_e_geojson_gravam_uma_pasta_com_o_nome(formato):
    assert montar_caminho(PASTA, "planta", formato) == os.path.join(PASTA, "planta")


def test_dividir_e_o_inverso_de_montar():
    assert dividir_caminho(os.path.join(PASTA, "planta.gpkg"), GPKG) == (PASTA, "planta")
    assert dividir_caminho(os.path.join(PASTA, "planta"), SHP) == (PASTA, "planta")


def test_dividir_aceita_a_barra_do_seletor_de_pastas():
    # o seletor de pastas do Windows devolve "C:/dados/obra"
    pasta, nome = dividir_caminho("C:/dados/obra/planta.gpkg", GPKG)
    assert nome == "planta"
    assert os.path.normpath(pasta) == os.path.normpath("C:/dados/obra")


@pytest.mark.parametrize("nome", ["", "   "])
def test_nome_vazio_tem_problema(nome):
    assert "nome" in problema_no_nome(nome, GPKG).lower()


@pytest.mark.parametrize("nome", ['a/b', 'a\\b', 'a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b'])
def test_caracteres_que_o_windows_nao_aceita(nome):
    assert problema_no_nome(nome, GPKG)


@pytest.mark.parametrize("nome", ["planta.", "CON", "nul", "com1", "LPT9"])
def test_nomes_que_o_windows_nao_aceita(nome):
    assert problema_no_nome(nome, GPKG)


def test_ponto_no_nome_so_atrapalha_quando_o_nome_vira_pasta():
    # no GeoPackage "planta v1.2" vira "planta v1.2.gpkg"; nos outros formatos o
    # programa tira tudo depois do ultimo ponto e a pasta sairia com outro nome
    assert problema_no_nome("planta v1.2", GPKG) is None
    assert problema_no_nome("planta v1.2", SHP)
    assert problema_no_nome("planta v1.2", JSON)


def test_nome_bom_nao_tem_problema():
    for formato in (GPKG, SHP, JSON):
        assert problema_no_nome("CARLOS SOST_qgis_2", formato) is None


# ---------------------------------------------------------------------------
# o campo na janela
@pytest.fixture
def formato(raiz):
    return tk.StringVar(master=raiz, value=GPKG)


@pytest.fixture
def campo(raiz, formato):
    c = CampoSaida(raiz, formato)
    yield c
    c.destroy()


def desenho_em(tmp_path, nome="CARLOS SOST.dwg"):
    return str(tmp_path / nome)


def test_comeca_vazio_e_explica_o_que_fazer(campo):
    assert campo.pasta() == "" and campo.nome() == ""
    assert campo.caminho_saida() == ""
    assert "desenho" in campo.aviso.cget("text").lower()
    assert campo.problema()


def test_sugestao_usa_a_pasta_e_o_nome_do_desenho(campo, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    assert campo.pasta() == os.path.normpath(str(tmp_path))
    assert campo.nome() == "CARLOS SOST_qgis"
    assert campo.caminho_saida() == str(tmp_path / "CARLOS SOST_qgis.gpkg")
    assert campo.problema() is None


def test_o_sufixo_acompanha_o_formato(campo, formato):
    assert campo.sufixo.cget("text") == ".gpkg"
    formato.set(SHP)
    assert ".gpkg" not in campo.sufixo.cget("text")
    assert "pasta" in campo.sufixo.cget("text").lower()


def test_trocar_o_formato_nao_apaga_o_nome_digitado(campo, formato, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("so_os_pontos")
    formato.set(SHP)
    assert campo.nome() == "so_os_pontos"
    assert campo.caminho_saida() == str(tmp_path / "so_os_pontos")
    formato.set(GPKG)
    assert campo.nome() == "so_os_pontos"
    assert campo.caminho_saida() == str(tmp_path / "so_os_pontos.gpkg")


def test_escolher_a_pasta_so_troca_a_pasta(campo, tmp_path, monkeypatch):
    outra = tmp_path / "outra"
    outra.mkdir()
    pedidos = []
    monkeypatch.setattr("conversor.gui_saida.filedialog.askdirectory",
                        lambda **kw: pedidos.append(kw) or str(outra).replace("\\", "/"))
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("camada_um")
    campo.escolher_pasta()
    assert campo.pasta() == os.path.normpath(str(outra))
    assert campo.nome() == "camada_um"
    assert os.path.normpath(pedidos[0]["initialdir"]) == os.path.normpath(str(tmp_path))


def test_cancelar_o_seletor_de_pastas_nao_muda_nada(campo, tmp_path, monkeypatch):
    monkeypatch.setattr("conversor.gui_saida.filedialog.askdirectory", lambda **kw: "")
    campo.sugerir(desenho_em(tmp_path))
    antes = (campo.pasta(), campo.nome())
    campo.escolher_pasta()
    assert (campo.pasta(), campo.nome()) == antes


def test_novo_desenho_muda_o_nome_e_a_pasta(campo, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    campo.sugerir(desenho_em(tmp_path / "a", "um.dxf"))
    campo.sugerir(desenho_em(tmp_path / "b", "dois.dxf"))
    assert campo.pasta() == os.path.normpath(str(tmp_path / "b"))
    assert campo.nome() == "dois_qgis"


def test_pasta_escolhida_a_mao_sobrevive_a_um_novo_desenho(campo, tmp_path, monkeypatch):
    # quem escolheu a pasta de saida quer ela nas proximas conversoes; o nome acompanha o desenho
    (tmp_path / "a").mkdir()
    escolhida = tmp_path / "entregas"
    escolhida.mkdir()
    monkeypatch.setattr("conversor.gui_saida.filedialog.askdirectory",
                        lambda **kw: str(escolhida))
    campo.sugerir(desenho_em(tmp_path / "a", "um.dxf"))
    campo.escolher_pasta()
    campo.sugerir(desenho_em(tmp_path / "a", "dois.dxf"))
    assert campo.pasta() == os.path.normpath(str(escolhida))
    assert campo.nome() == "dois_qgis"


def test_caminho_completo_colado_no_nome_vira_pasta_e_nome(campo, tmp_path):
    destino = tmp_path / "entregas"
    destino.mkdir()
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set(str(destino / "lote_7.gpkg"))
    campo.normalizar()
    assert campo.pasta() == os.path.normpath(str(destino))
    assert campo.nome() == "lote_7"
    assert campo.caminho_saida() == str(destino / "lote_7.gpkg")


def test_pasta_relativa_digitada_no_nome_fica_dentro_da_pasta_atual(campo, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("sub" + os.sep + "lote_8")
    campo.normalizar()
    assert campo.pasta() == os.path.normpath(str(tmp_path / "sub"))
    assert campo.nome() == "lote_8"


def test_avisa_quando_o_arquivo_ja_existe(campo, tmp_path):
    (tmp_path / "CARLOS SOST_qgis.gpkg").write_bytes(b"x")
    campo.sugerir(desenho_em(tmp_path))
    assert "substitu" in campo.aviso.cget("text").lower()
    campo.nome_var.set("outro_nome")
    assert "substitu" not in campo.aviso.cget("text").lower()


def test_avisa_quando_a_pasta_do_shapefile_ja_existe(campo, formato, tmp_path):
    (tmp_path / "CARLOS SOST_qgis").mkdir()
    formato.set(SHP)
    campo.sugerir(desenho_em(tmp_path))
    assert "substitu" in campo.aviso.cget("text").lower()


def test_shapefile_explica_que_cria_uma_pasta(campo, formato, tmp_path):
    formato.set(SHP)
    campo.sugerir(desenho_em(tmp_path))
    assert "CARLOS SOST_qgis" in campo.aviso.cget("text")


def test_nome_invalido_aparece_ao_lado_do_campo(campo, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("lote*1")
    assert campo.problema()
    assert campo.aviso.cget("text") == campo.problema()


def test_nome_apagado_pede_um_nome(campo, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("")
    assert "nome" in campo.aviso.cget("text").lower()
    assert campo.caminho_saida() == ""


def test_definir_saida_aceita_um_caminho_inteiro(campo, tmp_path):
    campo.definir_saida(str(tmp_path / "x.gpkg"))
    assert campo.pasta() == os.path.normpath(str(tmp_path))
    assert campo.nome() == "x"


def test_gpkg_digitado_no_nome_some_ao_normalizar(campo, tmp_path):
    # o ".gpkg" ja aparece ao lado do campo: deixar nos dois confundiria
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_var.set("planta.gpkg")
    campo.normalizar()
    assert campo.nome_var.get() == "planta"


def test_focar_o_nome_seleciona_tudo_para_digitar_por_cima(campo, raiz, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    campo.nome_entrada.event_generate("<FocusIn>")
    raiz.update()
    assert campo.nome_entrada.selection_present()
    assert campo.nome_entrada.selection_get() == campo.nome()


def test_focar_o_nome_confere_de_novo_se_o_arquivo_existe(campo, raiz, tmp_path):
    campo.sugerir(desenho_em(tmp_path))
    (tmp_path / "CARLOS SOST_qgis.gpkg").write_bytes(b"x")     # apareceu depois da sugestao
    assert "substitu" not in campo.aviso.cget("text").lower()
    campo.nome_entrada.event_generate("<FocusIn>")
    raiz.update()
    assert "substitu" in campo.aviso.cget("text").lower()


def test_a_pasta_fica_cinza_e_nao_da_para_clicar_nem_selecionar(campo, tmp_path):
    # so o botao "Escolher pasta..." muda a pasta (e o texto continua aparecendo)
    assert str(campo.pasta_entrada.cget("state")) == "disabled"
    campo.sugerir(desenho_em(tmp_path))
    assert campo.pasta_var.get() == os.path.normpath(str(tmp_path))
    assert campo.pasta_entrada.instate(["disabled"])


# ---------------------------------------------------------------------------
# dentro da aba
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
    pasta = tmp_path_factory.mktemp("salvar_como")
    caminho, _ = gerar_camadas.gerar(str(pasta / "d"))
    return caminho, pasta


def test_a_aba_sugere_a_saida_ao_escolher_o_desenho(aba, dxf, monkeypatch):
    from conversor import gui
    caminho, pasta = dxf
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: caminho)
    aba.escolher_entrada()
    assert aba.saida.pasta() == os.path.normpath(os.path.dirname(caminho))
    assert aba.saida.nome() == os.path.splitext(os.path.basename(caminho))[0] + "_qgis"


def test_converte_so_com_o_nome_digitado_na_pasta_escolhida(aba, dxf):
    caminho, pasta = dxf
    aba.entrada.insert(0, caminho)
    aba.saida.sugerir(caminho)
    aba.saida.definir_saida(str(pasta / "x.gpkg"))
    aba.saida.nome_var.set("so_o_nome")
    aba.converter()
    assert aba.app_falso.tarefa is not None, aba.avisos
    aba.app_falso.tarefa(lambda *_: None)
    assert (pasta / "so_o_nome.gpkg").is_file()


def test_o_aviso_de_substituir_se_atualiza_quando_a_tarefa_termina(aba, tmp_path):
    # converte uma camada, troca a escolha e converte de novo sem mexer no nome: o aviso
    # tem que aparecer, mesmo que nenhum campo tenha sido escrito (so o arquivo nasceu)
    destino = tmp_path / "camada_um.gpkg"
    aba.formato.set(GPKG)
    aba.saida.definir_saida(str(destino))
    assert "substitu" not in aba.saida.aviso.cget("text").lower()
    destino.write_bytes(b"x")                      # a conversao gravou o arquivo
    aba.event_generate("<<TarefaTerminou>>")
    assert "substitu" in aba.saida.aviso.cget("text").lower()


def test_caminho_colado_no_nome_vale_mesmo_sem_sair_do_campo(aba, dxf, tmp_path):
    # o clique no botao CONVERTER nao tira o foco do campo: converter() tem que arrumar
    caminho, _ = dxf
    destino = tmp_path / "entregas"
    destino.mkdir()
    aba.entrada.insert(0, caminho)
    aba.saida.sugerir(caminho)
    aba.saida.nome_var.set(str(destino / "colado.gpkg"))
    aba.converter()
    assert aba.app_falso.tarefa is not None, aba.avisos
    aba.app_falso.tarefa(lambda *_: None)
    assert (destino / "colado.gpkg").is_file()


def test_nome_invalido_nao_inicia_a_conversao(aba, dxf):
    caminho, pasta = dxf
    aba.entrada.insert(0, caminho)
    aba.saida.sugerir(caminho)
    aba.saida.nome_var.set("lote?")
    aba.converter()
    assert aba.app_falso.tarefa is None
    assert aba.avisos and "caracteres" in aba.avisos[0][1].lower()


def test_sem_pasta_nao_inicia_a_conversao(aba, dxf):
    caminho, _ = dxf
    aba.entrada.insert(0, caminho)
    aba.converter()
    assert aba.app_falso.tarefa is None
    assert aba.avisos
