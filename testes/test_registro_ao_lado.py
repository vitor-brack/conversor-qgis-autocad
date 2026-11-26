# -*- coding: utf-8 -*-
"""
Com o desenho aberto ao lado dos passos (aba AutoCAD -> QGIS, "Escolher as camadas"), o
quadro "O que aconteceu" sai de baixo das abas, onde ocupava a largura toda da janela, e vai
para baixo dos passos, na coluna deles (onde sobrava espaco). O desenho fica com a altura toda
da janela. Na outra aba, ou com o desenho fechado, o quadro volta para baixo. Ampliado, ele
some, como antes.

A janela nasce escondida: nada aparece na tela de quem roda os testes.
"""
import time

import pytest

import gerar_camadas
from conversor import config


@pytest.fixture(scope="module")
def janela(tmp_path_factory):
    """Uma janela so para o arquivo: criar varios Tk no mesmo processo falha de vez em quando
    (ver conftest.py)."""
    tk = pytest.importorskip("tkinter")
    pasta = tmp_path_factory.mktemp("registro")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PASTA", str(pasta))
        mp.setattr(config, "ARQUIVO", str(pasta / "config.json"))
        original = tk.Tk.__init__

        def nasce_escondida(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.withdraw()

        mp.setattr(tk.Tk, "__init__", nasce_escondida)
        from conversor.gui import App
        try:
            j = App()
        except tk.TclError as erro:
            pytest.skip("sem ambiente grafico: %s" % erro)
        j.geometry("1400x960")
        j.dxf, _ = gerar_camadas.gerar(str(pasta / "d"))
        yield j                      # as preferencias de verdade ficam fora ate o fim
        j.destroy()


@pytest.fixture
def app(janela):
    """A janela como ela abre: desenho fechado, na primeira aba."""
    aba = janela.aba2
    if aba.painel.ampliado:
        aba.painel.ampliar(False)
    if aba.escolher_camadas.get():
        aba.escolher_camadas.set(False)
        aba._alternar_camadas()
    aba.entrada.delete(0, "end")
    janela._abas.select(janela.aba1)
    janela.update()
    return janela


def esperar(janela, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        janela.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def abrir_o_desenho(app):
    aba = app.aba2
    app._abas.select(aba)
    aba.entrada.insert(0, app.dxf)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(app, lambda: aba.painel.estado == "pronto"), aba.painel.estado
    app.update()
    return aba


def onde_esta_o_registro(app):
    caixa = app._caixa_do_registro
    gerente = caixa.winfo_manager()
    if gerente == "grid":
        return "aba2" if caixa.grid_info().get("in") is app.aba2 else "grid fora da aba"
    return gerente or "escondido"


def test_sem_o_desenho_o_registro_fica_embaixo_das_abas(app):
    app.update()
    assert onde_esta_o_registro(app) == "pack"


def test_com_o_desenho_aberto_o_registro_vai_para_baixo_dos_passos(app):
    aba = abrir_o_desenho(app)
    assert onde_esta_o_registro(app) == "aba2"
    info = app._caixa_do_registro.grid_info()
    assert int(info["column"]) == 0 and int(info["row"]) == aba.linha_do_registro
    assert app._caixa_do_registro.winfo_y() > aba.botao.winfo_y(), "embaixo do CONVERTER"


def test_o_desenho_ganha_a_altura_que_era_do_registro(app):
    aba = abrir_o_desenho(app)
    ao_lado = aba.painel.tela.winfo_height()
    app.registro_ao_lado(None)                       # como era antes
    app.update()
    embaixo = aba.painel.tela.winfo_height()
    assert ao_lado > embaixo + 120, (embaixo, ao_lado)


def test_na_outra_aba_o_registro_volta_para_baixo(app):
    abrir_o_desenho(app)
    app._abas.select(app.aba1)
    app.update()
    assert onde_esta_o_registro(app) == "pack"
    app._abas.select(app.aba2)
    app.update()
    assert onde_esta_o_registro(app) == "aba2"


def test_ampliado_o_registro_some_e_volta_para_o_mesmo_lugar(app):
    aba = abrir_o_desenho(app)
    aba.painel.botao_ampliar.invoke()
    app.update()
    assert onde_esta_o_registro(app) == "escondido"
    assert aba.entrada.master.winfo_manager() == "", "os passos saem, como antes"
    aba.painel.botao_ampliar.invoke()
    app.update()
    assert onde_esta_o_registro(app) == "aba2"
    assert aba.entrada.master.winfo_manager() == "grid" and aba.botao.winfo_manager() == "grid"


def test_fechar_o_desenho_devolve_o_registro_para_baixo(app):
    aba = abrir_o_desenho(app)
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    app.update()
    assert onde_esta_o_registro(app) == "pack"


def test_fechar_o_desenho_ampliado_devolve_o_registro_para_baixo(app):
    aba = abrir_o_desenho(app)
    aba.painel.botao_ampliar.invoke()
    aba.escolher_camadas.set(False)
    aba._alternar_camadas()
    app.update()
    assert onde_esta_o_registro(app) == "pack"
    assert aba.entrada.master.winfo_manager() == "grid"


def test_o_registro_continua_escrevendo(app):
    abrir_o_desenho(app)
    app.registrar("mensagem de teste")
    assert "mensagem de teste" in app.log.get("1.0", "end")


# ---------------------------------------------------------------------------
# O fim de uma conversao avisa as abas. O aviso "ja existe, sera substituido" do passo
# "Onde salvar" depende disso: a conversao grava o arquivo sem escrever em nenhum campo
# (e quem converte uma camada de cada vez, sem trocar o nome, e quem mais precisa do aviso).
def _sem_janelas_de_aviso(monkeypatch):
    from conversor import gui
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)


def test_o_fim_da_conversao_atualiza_o_aviso_de_substituir(app, monkeypatch, tmp_path):
    _sem_janelas_de_aviso(monkeypatch)
    aba = app.aba2
    destino = tmp_path / "camada_um.gpkg"
    aba.formato.set("GPKG")
    aba.saida.definir_saida(str(destino))
    assert "substitu" not in aba.saida.aviso.cget("text").lower()

    def tarefa(registrar):
        destino.write_bytes(b"x")
        return {"feicoes": 1, "arquivos": [str(destino)]}

    app.executar(aba.botao, tarefa)
    assert esperar(app, lambda: "substitu" in aba.saida.aviso.cget("text").lower())


def test_a_conversao_que_falha_no_meio_tambem_atualiza_o_aviso(app, monkeypatch, tmp_path):
    # falhou depois de gravar: o arquivo parcial existe e o proximo CONVERTER o substitui
    from conversor import convert
    _sem_janelas_de_aviso(monkeypatch)
    aba = app.aba2
    destino = tmp_path / "camada_dois.gpkg"
    aba.formato.set("GPKG")
    aba.saida.definir_saida(str(destino))

    def tarefa(registrar):
        destino.write_bytes(b"x")
        raise convert.ErroConversao("falhou no meio")

    app.executar(aba.botao, tarefa)
    assert esperar(app, lambda: "substitu" in aba.saida.aviso.cget("text").lower())


# --------------------------------------------------------------- sem "Reprojetar"
# Na aba AutoCAD -> QGIS a caixa 2 so DECLARA em que sistema o desenho esta, e o arquivo sai
# nesse mesmo sistema. Nao ha mais "Reprojetar para outro sistema": mudar a caixa 2 nao
# transforma numero nenhum, so troca o que o QGIS entende que eles sao. (O motor continua
# sabendo reprojetar: a linha de comando usa.)
def _textos_da_tela(widget):
    achados = []
    for filho in widget.winfo_children():
        try:
            achados.append(str(filho.cget("text")))
        except Exception:
            pass                        # nem todo widget tem texto
        achados.extend(_textos_da_tela(filho))
    return achados


def test_a_aba_do_autocad_nao_oferece_reprojetar(app):
    textos = _textos_da_tela(app.aba2)
    assert any("Em que coordenadas" in t for t in textos), "a caixa 2 continua la"
    assert not [t for t in textos if "eprojet" in t], \
        "nenhum texto da aba fala em reprojetar: %s" % [t for t in textos if "eprojet" in t]


@pytest.mark.parametrize("epsg", [31982, 4674])
def test_o_sistema_da_caixa_2_so_declara_de_onde_o_desenho_vem(app, monkeypatch, tmp_path,
                                                               epsg):
    # guarda de regressao: ja passava antes de o checkbox sair, e tem de continuar passando
    from conversor import convert
    chamadas = []

    def falsa(**opcoes):
        chamadas.append(opcoes)
        return {"feicoes": 0, "arquivos": []}

    monkeypatch.setattr(convert, "cad_para_qgis", falsa)
    avisos, tarefas = [], []
    monkeypatch.setattr("conversor.gui.messagebox.showwarning",
                        lambda *a, **k: avisos.append(a))
    # a tarefa le as variaveis do Tk de dentro da thread, o que so funciona com o mainloop
    # rodando (no programa roda; aqui so ha update()): ela e chamada daqui mesmo
    monkeypatch.setattr(app, "executar", lambda botao, tarefa: tarefas.append(tarefa))
    aba = app.aba2
    sistema_antes = aba.crs_origem.obter()
    try:
        aba.entrada.insert(0, app.dxf)
        aba.crs_origem.definir(epsg)
        aba.saida.definir_saida(str(tmp_path / "declarado.gpkg"))
        aba.converter()
        assert not avisos, "a janela reclamou: %s" % (avisos,)
        assert len(tarefas) == 1, "o CONVERTER comecou a conversao"
        tarefas[0](lambda *_: None)
    finally:
        aba.entrada.delete(0, "end")
        aba.crs_origem.definir(sistema_antes)
    assert chamadas[0]["epsg_origem"] == epsg
    assert chamadas[0].get("epsg_destino") is None, "o arquivo sai no sistema declarado"
