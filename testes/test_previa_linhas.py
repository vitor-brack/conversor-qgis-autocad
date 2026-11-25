# -*- coding: utf-8 -*-
"""
"Uma linha" do desenho, do jeito que a pessoa a enxerga.

No AutoCAD cada trecho reto e uma entidade: um quadrado desenhado com quatro LINE tem
quatro entidades, mas e uma linha so para quem olha. A previa junta as pecas que se
encostam pelas pontas (na mesma camada e na mesma cor) e deixa achar a linha que esta
mais perto do clique. Pontos e areas contam um por um.

Quem usa isto e o painel de camadas: clicar no desenho escolhe so a linha clicada.
"""
import numpy as np
import ezdxf
import pytest

from conversor import previa

VERMELHO, AZUL = 1, 5


def ler(tmp_path, montar, camadas=("A", "B")):
    doc = ezdxf.new("R2010")
    for nome in camadas:
        doc.layers.add(nome, color=7)
    montar(doc.modelspace())
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    return previa.ler(caminho)


def reta(msp, a, b, camada="A", cor=VERMELHO):
    return msp.add_line(a, b, dxfattribs={"layer": camada, "color": cor})


def quadrado(msp, x0, y0, lado=10, camada="A", cor=VERMELHO):
    p = [(x0, y0), (x0 + lado, y0), (x0 + lado, y0 + lado), (x0, y0 + lado)]
    for a, b in zip(p, p[1:] + p[:1]):
        reta(msp, a, b, camada, cor)


def grupos_da_camada(p, camada):
    return [g for g in p.grupos.values() if g.camada == camada]


# ---------------------------------------------------------------------------
# o que e uma linha
def test_pecas_que_se_encostam_pelas_pontas_sao_uma_linha_so(tmp_path):
    def montar(msp):
        quadrado(msp, 0, 0)                      # quatro LINE que se fecham
        reta(msp, (50, 0), (60, 0))              # uma solta, longe
    p = ler(tmp_path, montar)
    grupos = sorted(grupos_da_camada(p, "A"), key=lambda g: -g.pecas)
    assert [g.pecas for g in grupos] == [4, 1], \
        "o quadrado e uma linha de 4 pecas e a solta e outra -> %s" % [g.pecas for g in grupos]
    assert len(grupos[0].fids) == 4 and len(grupos[1].fids) == 1


def test_uma_polilinha_e_uma_linha_mesmo_com_muitos_vertices(tmp_path):
    def montar(msp):
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True,
                           dxfattribs={"layer": "A", "color": VERMELHO})
    p = ler(tmp_path, montar)
    assert [g.pecas for g in grupos_da_camada(p, "A")] == [1]


def test_cores_diferentes_nao_se_juntam_mesmo_encostando(tmp_path):
    def montar(msp):
        reta(msp, (0, 0), (10, 0), cor=VERMELHO)
        reta(msp, (10, 0), (20, 0), cor=AZUL)           # encosta, mas e de outra cor
    p = ler(tmp_path, montar)
    assert sorted(g.pecas for g in grupos_da_camada(p, "A")) == [1, 1]
    assert {g.cor for g in grupos_da_camada(p, "A")} == {"#ff0000", "#0000ff"}


def test_camadas_diferentes_nao_se_juntam_mesmo_encostando(tmp_path):
    def montar(msp):
        reta(msp, (0, 0), (10, 0), camada="A")
        reta(msp, (10, 0), (20, 0), camada="B")
    p = ler(tmp_path, montar)
    assert len(grupos_da_camada(p, "A")) == 1 and len(grupos_da_camada(p, "B")) == 1


def test_linha_fechada_e_uma_forma_completa_e_nao_se_junta_a_outras(tmp_path):
    # Dois lotes vizinhos que dividem o canto onde cada polilinha comeca: a ponta de uma
    # coincide com a ponta da outra por acaso (depende de onde o desenhista comecou a
    # polilinha), e juntar os dois lotes numa linha so seria um erro
    def montar(msp):
        for x0 in (0, 10):
            msp.add_lwpolyline([(x0, 0), (x0 + 10, 0), (x0 + 10, 10), (x0, 10)], close=True,
                               dxfattribs={"layer": "A", "color": VERMELHO})
        reta(msp, (0, 0), (-5, -5))              # uma linha aberta saindo do canto de um lote
    p = ler(tmp_path, montar)
    assert sorted(g.pecas for g in grupos_da_camada(p, "A")) == [1, 1, 1], \
        "os dois lotes e a linha aberta ficam separados -> %s" % \
        sorted(g.pecas for g in grupos_da_camada(p, "A"))


def test_ponta_encostando_no_meio_de_outra_nao_junta(tmp_path):
    # So as pontas contam. Juntar tambem o encontro em T pode amarrar um desenho inteiro
    # numa linha so, e uma linha escolhida demais nao tem como ser desfeita
    def montar(msp):
        reta(msp, (0, 0), (20, 0))
        reta(msp, (10, 0), (10, 10))                    # sai do meio da primeira
    p = ler(tmp_path, montar)
    assert sorted(g.pecas for g in grupos_da_camada(p, "A")) == [1, 1]


def test_pontas_quase_iguais_juntam_o_erro_de_arredondamento_nao_separa(tmp_path):
    def montar(msp):
        reta(msp, (0, 0), (100, 0))
        reta(msp, (100.0000001, 0.0000001), (100, 100))      # 1e-7 de diferenca
        reta(msp, (100.5, 100), (200, 100))                   # meio metro: outra linha
    p = ler(tmp_path, montar)
    assert sorted(g.pecas for g in grupos_da_camada(p, "A")) == [1, 2]


def test_pontos_e_areas_sao_uma_linha_cada_um(tmp_path):
    def montar(msp):
        msp.add_point((5, 5), dxfattribs={"layer": "A"})
        msp.add_point((5, 5), dxfattribs={"layer": "A"})                 # no mesmo lugar
        # dois triangulos que dividem o vertice (10, 0), como numa malha
        msp.add_3dface([(0, 0), (10, 0), (10, 10), (10, 10)], dxfattribs={"layer": "B"})
        msp.add_3dface([(10, 0), (20, 0), (20, 10), (20, 10)], dxfattribs={"layer": "B"})
    p = ler(tmp_path, montar)
    assert [g.pecas for g in grupos_da_camada(p, "A")] == [1, 1], "dois pontos, duas linhas"
    assert [g.pecas for g in grupos_da_camada(p, "B")] == [1, 1], \
        "triangulos que dividem vertices (uma malha) nao viram uma coisa so"


def test_cada_forma_diz_a_linha_de_cada_vetor(tmp_path):
    def montar(msp):
        quadrado(msp, 0, 0)
        reta(msp, (50, 0), (60, 0))
    p = ler(tmp_path, montar)
    forma = p.formas("A")[0]
    n = len(forma.inicio) - 1
    assert len(forma.grupos) == n and len(forma.fids) == n
    assert len(set(forma.grupos.tolist())) == 2, "5 vetores, duas linhas"
    assert set(forma.grupos.tolist()) == set(p.grupos), "e cada uma esta em Previa.grupos"
    # os fids de cada linha sao os dos vetores dela
    for gid, g in p.grupos.items():
        assert set(forma.fids[forma.grupos == gid].tolist()) == set(g.fids)


def test_linha_de_camada_desligada_vem_marcada_como_oculta(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("Ligada", color=1)
    doc.layers.add("Desligada", color=1).off()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "Ligada"})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "Desligada"})
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert {g.camada: g.oculta for g in p.grupos.values()} == {"Ligada": False, "Desligada": True}


# ---------------------------------------------------------------------------
# achar a linha mais perto do clique
@pytest.fixture
def desenho(tmp_path):
    def montar(msp):
        quadrado(msp, 0, 0)                              # x e y de 0 a 10, vermelho
        reta(msp, (50, 0), (60, 0), cor=AZUL)            # azul, na mesma camada
        msp.add_point((30, 30), dxfattribs={"layer": "A", "color": VERMELHO})
        reta(msp, (0, 100), (10, 100), camada="B")
    return ler(tmp_path, montar)


def fids_de(p, gid):
    return set(p.grupos[gid].fids)


def test_acha_a_linha_que_esta_debaixo_do_clique(desenho):
    p = desenho
    gid = p.achar_grupo(5, 0.2, 1.0, "A")                # em cima do lado de baixo do quadrado
    assert gid is not None and p.grupos[gid].pecas == 4, \
        "clicar em um lado acha o quadrado inteiro, as 4 pecas"
    azul = p.achar_grupo(55, -0.1, 1.0, "A")
    assert p.grupos[azul].cor == "#0000ff" and p.grupos[azul].pecas == 1


def test_clicar_longe_demais_nao_acha_nada(desenho):
    assert desenho.achar_grupo(5, 5, 1.0, "A") is None, "o meio do quadrado nao tem linha"
    assert desenho.achar_grupo(5, 3, 1.0, "A") is None


def test_o_ponto_e_achado_pelo_vertice(desenho):
    gid = desenho.achar_grupo(30.2, 29.9, 1.0, "A")
    assert gid is not None and desenho.grupos[gid].pecas == 1
    assert desenho.grupos[gid].fids != desenho.grupos[desenho.achar_grupo(5, 0, 1.0, "A")].fids


def test_so_procura_na_camada_pedida(desenho):
    assert desenho.achar_grupo(5, 0, 1.0, "B") is None, "o quadrado e da A; na B nao tem nada ali"
    gid = desenho.achar_grupo(5, 100, 1.0, "B")
    assert desenho.grupos[gid].camada == "B"


def test_pode_procurar_so_numa_cor_da_camada(desenho):
    # a linha azul esta a 10 m do quadrado vermelho; com raio grande, a cor decide
    assert desenho.grupos[desenho.achar_grupo(20, 0, 50.0, "A", cor="#0000ff")].cor == "#0000ff"
    assert desenho.grupos[desenho.achar_grupo(20, 0, 50.0, "A", cor="#ff0000")].cor == "#ff0000"


def test_entre_duas_linhas_ganha_a_mais_perto(desenho):
    gid = desenho.achar_grupo(12, 0, 100.0, "A", cor="#ff0000")
    assert desenho.grupos[gid].pecas == 4, "a mais perto de x = 12 e o quadrado, nao o ponto"
    gid = desenho.achar_grupo(48, 0.5, 100.0, "A")
    assert desenho.grupos[gid].cor == "#0000ff"


def test_ocultas_so_sao_achadas_se_pedir(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("Desligada", color=1).off()
    doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "Desligada"})
    caminho = str(tmp_path / "d.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert p.achar_grupo(5, 0, 1.0, "Desligada", com_ocultas=False) is None
    assert p.achar_grupo(5, 0, 1.0, "Desligada", com_ocultas=True) is not None
