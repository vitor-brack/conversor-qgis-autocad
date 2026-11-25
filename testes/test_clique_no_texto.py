# -*- coding: utf-8 -*-
"""
Clicar num texto do desenho escolhe aquele texto, como clicar numa linha escolhe a linha.

A previa desenha os textos com o ezdxf (as letras como o AutoCAD as mostra), mas a conversao
le as feicoes pelo GDAL: cada texto desenhado precisa saber qual feicao do GDAL ele e (o id
que a conversao leva, ver Grupo.fids). O handle liga os dois:
  - texto solto e MTEXT: o handle dele; o MTEXT de duas linhas e uma feicao so no GDAL e
    quatro pedacos (palavras) na previa -- os quatro escolhem a mesma;
  - texto dentro de bloco e texto de cota: o handle do INSERT ou da cota (o mesmo bloco
    inserido duas vezes da duas feicoes, cada uma com o seu INSERT);
  - atributo (ATTRIB): o handle do proprio atributo, nao o do INSERT.

Clicar dentro da caixa do texto (a celula da fonte ao longo da linha) escolhe o texto; fora
dela, vale o clique de sempre, na linha mais perto.
"""
import collections
import time
import tkinter as tk

import ezdxf
import fiona
import numpy as np
import pytest

from conversor import config, dxf_estilo, previa

X0, Y0 = 448000.0, 6743000.0
BRANCO = 255 * 3


@pytest.fixture(scope="module")
def desenho(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("clique_texto")
    doc = ezdxf.new("R2010", setup=True)
    for nome in ("TEXTOS", "LINHAS", "PLACAS", "NOTAS", "COTAS"):
        doc.layers.add(nome)
    msp = doc.modelspace()
    msp.add_lwpolyline([(X0, Y0), (X0 + 120, Y0), (X0 + 120, Y0 + 100), (X0, Y0 + 100)],
                       close=True, dxfattribs={"layer": "LINHAS"})
    msp.add_line((X0 + 10, Y0 + 6), (X0 + 60, Y0 + 6), dxfattribs={"layer": "LINHAS"})
    msp.add_text("POCO", dxfattribs={"layer": "TEXTOS", "height": 2}).set_placement(
        (X0 + 10, Y0 + 10))
    msp.add_text("OUTRO", dxfattribs={"layer": "TEXTOS", "height": 2}).set_placement(
        (X0 + 10, Y0 + 20))
    placa = doc.blocks.new("PLACA")
    placa.add_text("NO BLOCO", dxfattribs={"layer": "0", "height": 2}).set_placement((0, 0))
    placa.add_attdef("NUM", (0, 4), dxfattribs={"height": 2})
    for i, x in enumerate((40, 80)):
        ref = msp.add_blockref("PLACA", (X0 + x, Y0 + 40), dxfattribs={"layer": "PLACAS"})
        ref.add_auto_attribs({"NUM": "P%d" % (i + 1)})
    nota = msp.add_mtext("Linha um\\PLinha dois",
                         dxfattribs={"layer": "NOTAS", "char_height": 2})
    nota.set_location((X0 + 10, Y0 + 70))
    msp.add_linear_dim(base=(X0 + 70, Y0 + 90), p1=(X0 + 70, Y0 + 80), p2=(X0 + 110, Y0 + 80),
                       dxfattribs={"layer": "COTAS"}).render()
    caminho = str(pasta / "d.dxf")
    doc.saveas(caminho)
    return caminho, previa.ler(caminho)


def textos_do_gdal(caminho):
    """{id da feicao: Text} das feicoes de texto que a conversao le."""
    saida = {}
    with dxf_estilo.abrir_entidades(
            caminho, opcoes_extra={"DXF_CLOSED_LINE_AS_POLYGON": "FALSE"}) as (origem, _):
        for n, f in enumerate(origem):
            p = f["properties"]
            if f.get("geometry") and p.get("Text"):
                saida[dxf_estilo.id_da_feicao(f, n)] = p["Text"]
    return saida


def meio(t):
    return t.caixa[:4].mean(axis=0)


def os_textos(p, conteudo):
    return [t for t in p.textos if t.texto == conteudo]


# ---------------------------------------------------------------------------
# a previa: cada texto desenhado sabe qual feicao do GDAL ele e
def test_cada_texto_desenhado_escolhe_a_feicao_dele(desenho):
    caminho, p = desenho
    gdal = textos_do_gdal(caminho)
    por_grupo = collections.defaultdict(set)
    for t in p.textos:
        gid = p.achar_texto(*meio(t), 0.0)
        assert gid is not None, "o texto %r nao se escolhe" % t.texto
        g = p.grupos[gid]
        assert len(g.fids) == 1, g
        (fid,) = g.fids
        assert t.texto in gdal[fid], "clicou em %r e escolheu %r" % (t.texto, gdal[fid])
        por_grupo[gid].add(t.texto)
    assert len(por_grupo) == len(gdal) == 8, \
        "um grupo por texto do GDAL (o MTEXT inteiro e um so) -> %s" % dict(por_grupo)


def test_os_pedacos_do_mtext_escolhem_o_mtext_inteiro(desenho):
    _caminho, p = desenho
    pedacos = [t for t in p.textos if t.camada == "NOTAS"]
    assert len(pedacos) >= 2
    grupos = {p.achar_texto(*meio(t), 0.0) for t in pedacos}
    assert len(grupos) == 1, grupos
    assert "Linha um" in p.grupos[grupos.pop()].texto


def test_o_mesmo_bloco_inserido_duas_vezes_da_duas_escolhas(desenho):
    caminho, p = desenho
    gdal = textos_do_gdal(caminho)
    blocos = os_textos(p, "NO BLOCO")
    assert len(blocos) == 2
    fids = {next(iter(p.grupos[p.achar_texto(*meio(t), 0.0)].fids)) for t in blocos}
    assert len(fids) == 2 and all(gdal[f] == "NO BLOCO" for f in fids), fids
    (p1,), (p2,) = os_textos(p, "P1"), os_textos(p, "P2")
    assert gdal[next(iter(p.grupos[p.achar_texto(*meio(p1), 0.0)].fids))] == "P1"
    assert gdal[next(iter(p.grupos[p.achar_texto(*meio(p2), 0.0)].fids))] == "P2"


def test_fora_da_caixa_do_texto_nao_escolhe_texto(desenho):
    _caminho, p = desenho
    (poco,) = os_textos(p, "POCO")
    x, y = meio(poco)
    assert p.achar_texto(x, y - 3.0, 0.0) is None, "3 unidades abaixo ja e fora da caixa"
    assert p.achar_texto(x, y - 3.0, 4.0) is not None, "mas a folga alcanca"


def test_so_escolhe_texto_das_camadas_pedidas(desenho):
    _caminho, p = desenho
    (poco,) = os_textos(p, "POCO")
    assert p.achar_texto(*meio(poco), 0.0, camadas={"NOTAS"}) is None
    assert p.achar_texto(*meio(poco), 0.0, camadas={"TEXTOS"}) is not None


# ---------------------------------------------------------------------------
# o painel
@pytest.fixture
def painel(raiz, desenho):
    from conversor.gui_camadas import PainelCamadas
    p = PainelCamadas(raiz)
    p.definir_previa(desenho[1], dxf_pronto=desenho[0])
    raiz.update_idletasks()
    p.ver_tudo()
    yield p
    p.destroy()


def no_texto(painel, conteudo):
    (t,) = os_textos(painel.previa, conteudo)
    px, py = painel.vista.para_tela(*meio(t))
    return int(round(px)), int(round(py))


def tinta_em_volta(painel, conteudo, folga=3):
    """Quantos pixels nao brancos ha na caixa do texto (mais a folga), na tela."""
    (t,) = os_textos(painel.previa, conteudo)
    xs, ys = painel.vista.para_tela(t.caixa[:, 0], t.caixa[:, 1])
    x0, x1 = int(np.floor(xs.min())) - folga, int(np.ceil(xs.max())) + folga
    y0, y1 = int(np.floor(ys.min())) - folga, int(np.ceil(ys.max())) + folga
    pedaco = painel.imagem[max(y0, 0):y1, max(x0, 0):x1].astype(int)
    return int((pedaco.sum(axis=2) < BRANCO).sum())


def test_clicar_no_texto_escolhe_o_texto(painel):
    painel.clicar(*no_texto(painel, "POCO"))
    assert len(painel.escolhidas) == 1
    g = painel.previa.grupos[next(iter(painel.escolhidas))]
    assert g.texto == "POCO" and g.camada == "TEXTOS", g
    assert "POCO" in painel.detalhe.get() and "Texto" in painel.detalhe.get(), \
        painel.detalhe.get()
    assert "1 texto escolhido" in painel.resumo.get(), painel.resumo.get()
    assert "1 texto escolhido" in painel.arvore.item(painel._iid["TEXTOS"], "values")[2]
    assert "marcada" in painel.arvore.item(painel._iid["TEXTOS"], "tags"), "negrito na lista"


def test_a_selecao_leva_a_feicao_do_texto(painel, desenho):
    painel.clicar(*no_texto(painel, "POCO"))
    sel = painel.selecao()
    gdal = textos_do_gdal(desenho[0])
    assert [gdal[f] for f in sel["feicoes"]] == ["POCO"], sel["feicoes"]
    assert sel["textos"] == 1 and sel["linhas"] == 0, sel


def test_clicar_fora_da_caixa_ainda_escolhe_a_linha(painel):
    px, py = painel.vista.para_tela(X0 + 40, Y0 + 6)      # a linha embaixo do POCO
    painel.clicar(int(round(px)), int(round(py)))
    (gid,) = painel.escolhidas
    g = painel.previa.grupos[gid]
    assert g.texto is None and g.camada == "LINHAS", g
    assert "1 linha escolhida" in painel.resumo.get(), painel.resumo.get()


def test_ctrl_soma_linha_e_texto(painel):
    px, py = painel.vista.para_tela(X0 + 40, Y0 + 6)
    painel.clicar(int(round(px)), int(round(py)))
    painel.clicar(*no_texto(painel, "OUTRO"), ctrl=True)
    assert "1 linha e 1 texto escolhidos" in painel.resumo.get(), painel.resumo.get()
    painel.clicar(*no_texto(painel, "OUTRO"), ctrl=True)
    assert "1 linha escolhida" in painel.resumo.get(), "Ctrl de novo tira o texto"


def test_texto_escolhido_fica_em_negrito_no_desenho(painel):
    antes = tinta_em_volta(painel, "POCO")
    outro_antes = tinta_em_volta(painel, "OUTRO")
    painel.clicar(*no_texto(painel, "POCO"))
    assert tinta_em_volta(painel, "POCO") > antes * 1.3, (antes, tinta_em_volta(painel, "POCO"))
    assert tinta_em_volta(painel, "OUTRO") == outro_antes, "o outro texto da camada nao muda"


def test_texto_escolhido_tambem_se_ve_quando_vira_barra(painel):
    largura, altura = painel.tamanho()
    painel.vista.zoom(0.35, largura / 2, altura / 2)        # maiuscula com uns 2 pixels: barra
    painel._lembrar_regiao()
    painel._renderizar()
    antes = tinta_em_volta(painel, "POCO", folga=1)
    assert antes > 0
    painel.clicar(*no_texto(painel, "POCO"))
    (gid,) = painel.escolhidas
    assert getattr(painel.previa.grupos[gid], "texto", None) == "POCO", \
        "escolheu o texto, e nao a linha logo abaixo"
    depois = tinta_em_volta(painel, "POCO", folga=1)
    assert depois > antes * 1.3, (antes, depois)


def test_camada_marcada_deixa_os_textos_dela_em_negrito(painel):
    antes = tinta_em_volta(painel, "POCO")
    painel.alternar("TEXTOS")
    assert tinta_em_volta(painel, "POCO") > antes * 1.3


def test_clique_no_texto_separando_por_cor(painel):
    painel.separar_por_cor.set(True)
    painel.clicar(*no_texto(painel, "POCO"))
    assert len(painel.escolhidas) == 1
    assert "1 texto escolhido" in painel.resumo.get(), painel.resumo.get()


def test_camada_so_de_texto_nao_diz_mais_que_o_clique_nao_escolhe_texto(painel):
    painel.selecionar("TEXTOS")
    assert "nao textos" not in painel.detalhe.get(), painel.detalhe.get()


# ---------------------------------------------------------------------------
# da janela ate o arquivo
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


def esperar(raiz, condicao, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        raiz.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


def abrir(aba, raiz, caminho, saida):
    aba.entrada.delete(0, tk.END)
    aba.entrada.insert(0, caminho)
    aba.saida.definir_saida(saida)
    aba.escolher_camadas.set(True)
    aba._alternar_camadas()
    assert esperar(raiz, lambda: aba.painel.estado == "pronto")
    aba.painel.ver_tudo()


def textos_gravados(saida):
    textos = []
    for camada in fiona.listlayers(saida):
        with fiona.open(saida, layer=camada) as f:
            textos += [ft["properties"].get("Text") for ft in f if ft["properties"].get("Text")]
    return sorted(textos)


def test_converte_so_o_texto_clicado(aba, raiz, desenho, tmp_path):
    saida = str(tmp_path / "so_o_texto.gpkg")
    abrir(aba, raiz, desenho[0], saida)
    aba.painel.clicar(*no_texto(aba.painel, "POCO"))
    aba.converter()
    assert aba.app_falso.tarefa is not None, "avisos: %s" % aba.avisos
    log = []
    aba.app_falso.tarefa(log.append)
    assert textos_gravados(saida) == ["POCO"], \
        "so o POCO, sem o OUTRO da mesma camada -> %s" % textos_gravados(saida)
    assert any("1 texto escolhido" in linha and "desenho" in linha for linha in log), log


def test_converte_o_mtext_clicado_inteiro(aba, raiz, desenho, tmp_path):
    saida = str(tmp_path / "mtext.gpkg")
    abrir(aba, raiz, desenho[0], saida)
    aba.painel.clicar(*no_texto(aba.painel, "dois"))
    aba.converter()
    aba.app_falso.tarefa(lambda *_: None)
    assert textos_gravados(saida) == ["Linha dois", "Linha um"], textos_gravados(saida)


def test_texto_escolhido_com_a_opcao_sem_textos_avisa_no_log(aba, raiz, desenho, tmp_path):
    saida = str(tmp_path / "sem_textos.gpkg")
    abrir(aba, raiz, desenho[0], saida)
    aba.sem_textos.set(True)
    px, py = aba.painel.vista.para_tela(X0 + 40, Y0 + 6)
    aba.painel.clicar(int(round(px)), int(round(py)))
    aba.painel.clicar(*no_texto(aba.painel, "POCO"), ctrl=True)
    aba.converter()
    log = []
    aba.app_falso.tarefa(log.append)
    assert any("texto" in linha and "fora" in linha for linha in log), log
