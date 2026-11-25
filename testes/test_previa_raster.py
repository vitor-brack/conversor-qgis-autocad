# -*- coding: utf-8 -*-
"""
O desenho da previa: uma imagem montada com numpy, sem criar um objeto por
feicao (o desenho real tem 500 mil vertices), e um mapa de qual camada esta em
cada pixel, para clicar no desenho e achar a camada.
"""
import time

import numpy as np
import pytest

import gerar_camadas
from conversor import previa, previa_raster as pr

VERMELHO, AZUL = (255, 0, 0), (0, 0, 255)
FUNDO = pr.FUNDO


def reta(id_, rgb, pontos, tipo="linha", inicio=None, grosso=False):
    xy = np.array(pontos, dtype=float)
    return pr.Desenho(id_, rgb, tipo, xy, np.array(inicio or [0, len(xy)], dtype=np.int64),
                      grosso)


def tela(desenhos, w=20, h=12, escala=1.0, x0=0.0, y_topo=5.0, destaque=None):
    return pr.desenhar(desenhos, pr.Vista(escala, x0, y_topo), w, h, destaque=destaque)


def colorido(img):
    return (img != np.array(FUNDO, dtype=np.uint8)).any(axis=2)


# ---------------------------------------------------------------------------
def test_reta_horizontal_pinta_do_primeiro_ao_ultimo_pixel():
    img, ids = tela([reta(0, VERMELHO, [(0, 0), (10, 0)])])
    assert (img[5, 0:11] == VERMELHO).all() and tuple(img[5, 11]) == FUNDO, \
        "linha na linha 5, de x=0 a x=10 -> %s" % np.flatnonzero(colorido(img)[5]).tolist()
    assert ids[5, 3] == 1 and ids[0, 0] == 0, "o mapa guarda o id + 1, e zero onde nao tem nada"


def test_reta_diagonal_nao_tem_buraco():
    img, _ = tela([reta(0, VERMELHO, [(0, 0), (10, 7)])], y_topo=9.0)     # sobe de 9 a 2: cabe
    assert colorido(img).sum() >= 11, "ao menos um pixel por coluna -> %d" % colorido(img).sum()
    colunas = np.flatnonzero(colorido(img).any(axis=0))
    assert colunas.tolist() == list(range(11)), "sem falha entre o comeco e o fim -> %s" % colunas


def test_ponto_vira_quadrado_de_3_por_3():
    img, _ = tela([reta(0, AZUL, [(5, 0)], tipo="ponto")])
    assert colorido(img).sum() == 9 and (img[4:7, 4:7] == AZUL).all(), \
        "3x3 em volta do ponto -> %d pixels" % colorido(img).sum()


def test_muitos_pontos_viram_pixels_e_nao_escondem_as_linhas():
    # 600 pontos num desenho de 94 x 54: com quadrados 3x3 eles se emendavam numa
    # mancha so e cobriam as curvas de nivel (foi o que aconteceu no desenho real)
    rng = np.random.default_rng(3)
    xs, ys = rng.integers(2, 96, 600), rng.integers(2, 56, 600)
    linha = reta(0, VERMELHO, [(0, -30), (99, -30)])
    pontos = reta(1, AZUL, list(zip(xs.tolist(), (-ys).tolist())), tipo="ponto")
    img, _ = tela([linha, pontos], w=100, h=60, y_topo=0.0)
    sobrou = (img[30, 0:100] == VERMELHO).all(axis=1).mean()
    assert sobrou >= 0.75, "a linha continua aparecendo por entre os pontos -> %.0f%%" % (100 * sobrou)


def test_com_zoom_poucos_pontos_na_tela_voltam_a_ser_quadrados():
    # mil pontos no desenho, mas so um aparece na tela: ai o quadrado ajuda a ver
    longe = [(5000 + i, -5000) for i in range(999)]
    img, _ = tela([reta(0, AZUL, longe + [(50, -30)], tipo="ponto")], w=100, h=60, y_topo=0.0)
    assert colorido(img).sum() == 9, "so o ponto visivel conta -> %d pixels" % colorido(img).sum()


def test_formas_diferentes_na_mesma_camada_nao_se_ligam():
    # duas linhas na mesma camada: nao pode ter risco ligando o fim de uma ao comeco da outra
    d = reta(0, VERMELHO, [(0, 0), (2, 0), (8, 0), (10, 0)], inicio=[0, 2, 4])
    img, _ = tela([d])
    assert not colorido(img)[5, 3:8].any(), "o vao entre as duas fica vazio"
    assert colorido(img)[5, 0:3].all() and colorido(img)[5, 8:11].all()


def test_linha_enorme_e_cortada_na_janela():
    # a linha da origem ate o terreno: milhoes de pixels de comprimento
    inicio = time.time()
    img, _ = tela([reta(0, VERMELHO, [(-1e7, 0), (1e7, 0)])])
    assert colorido(img)[5].all(), "cruza a janela inteira"
    assert time.time() - inicio < 1.0, "sem gerar milhoes de amostras"


def test_segmento_fora_da_janela_nao_desenha_nada():
    img, ids = tela([reta(0, VERMELHO, [(100, 100), (200, 150)])])
    assert not colorido(img).any() and not ids.any()


def test_o_desenho_de_depois_cobre_o_de_antes_e_o_mapa_acompanha():
    a = reta(0, VERMELHO, [(0, 0), (10, 0)])
    b = reta(1, AZUL, [(5, -3), (5, 3)])
    img, ids = tela([a, b])
    assert tuple(img[5, 5]) == AZUL and ids[5, 5] == 2, "no cruzamento, o de depois"
    assert tuple(img[5, 2]) == VERMELHO and ids[5, 2] == 1


def test_destaque_fica_mais_grosso_e_por_cima_sem_trocar_a_cor():
    a = reta(0, VERMELHO, [(0, 0), (10, 0)])
    b = reta(1, AZUL, [(5, -3), (5, 3)])
    sem, _ = tela([a, b])
    com, ids = tela([a, b], destaque=0)
    assert colorido(com).sum() > colorido(sem).sum(), "o destaque ocupa mais pixels"
    assert tuple(com[5, 5]) == VERMELHO and ids[5, 5] == 1, "e fica por cima da outra camada"
    # a cor do CAD significa algo: a linha segue vermelha, e o destaque e um contorno
    assert all(tuple(com[r, 2]) == VERMELHO for r in (4, 5, 6)), "tres pixels, na cor dela"
    assert tuple(com[3, 2]) == pr.CONTORNO and tuple(com[7, 2]) == pr.CONTORNO, \
        "com um contorno (azul de selecao, que se ve no fundo branco) em volta"


def test_camada_marcada_fica_em_negrito_na_mesma_cor():
    fina, _ = tela([reta(0, AZUL, [(0, 0), (10, 0)])])
    grossa, ids = tela([reta(0, AZUL, [(0, 0), (10, 0)], grosso=True)])
    # a grossa passa 1 pixel das pontas: 12 colunas visiveis (0 a 11) x 3 linhas
    assert colorido(fina).sum() == 11 and colorido(grossa).sum() == 36,         "a fina tem 1 pixel de espessura e a marcada 3 -> %d e %d" % (
            colorido(fina).sum(), colorido(grossa).sum())
    assert all(tuple(grossa[r, 4]) == AZUL for r in (4, 5, 6)), "e a cor continua a mesma"
    assert ids[4, 4] == 1, "o clique pega a linha grossa tambem"


def test_negrito_fica_mais_fino_quando_ha_muita_linha_na_tela():
    # 40 mil vertices marcados numa mancha pequena: com 3 pixels de negrito as curvas
    # de nivel viravam um bloco de uma cor so (foi o que se viu no desenho real)
    zigue = [(1 + (i % 2), -1 - (i % 3)) for i in range(40000)]
    isolada = reta(1, AZUL, [(0, -30), (99, -30)], grosso=True)
    densa = reta(0, VERMELHO, zigue, grosso=True)
    img, _ = tela([densa, isolada], w=100, h=60, y_topo=0.0)
    assert colorido(img)[:, 60].sum() == 2,         "muita linha na tela: negrito de 2 pixels -> %d" % colorido(img)[:, 60].sum()
    img, _ = tela([isolada], w=100, h=60, y_topo=0.0)
    assert colorido(img)[:, 60].sum() == 3, "pouca linha: negrito de 3 pixels"


def test_marcada_fica_por_cima_da_que_nao_esta():
    marcada = reta(0, VERMELHO, [(0, 0), (10, 0)], grosso=True)
    outra = reta(1, AZUL, [(5, -3), (5, 3)])
    img, ids = tela([marcada, outra])
    assert tuple(img[5, 5]) == VERMELHO and ids[5, 5] == 1,         "no cruzamento, a marcada ganha mesmo vindo antes na lista"


def test_pontos_marcados_ficam_maiores_na_mesma_cor():
    poucos = reta(0, AZUL, [(5, -3)], tipo="ponto")
    marcado = reta(0, AZUL, [(5, -3)], tipo="ponto", grosso=True)
    assert colorido(tela([poucos])[0]).sum() == 9 and colorido(tela([marcado])[0]).sum() == 25,         "poucos pontos: 3x3, e marcado 5x5"
    # 450 pontos a 4 pixels um do outro: viram 1 pixel, e marcados viram 2x2
    grade = [(4 * c, -4 * r) for c in range(25) for r in range(18)]
    fino = tela([reta(0, AZUL, grade, tipo="ponto")], w=110, h=80, y_topo=0.0)[0]
    grosso = tela([reta(0, AZUL, grade, tipo="ponto", grosso=True)], w=110, h=80, y_topo=0.0)[0]
    assert colorido(fino).sum() == 450 and colorido(grosso).sum() == 1800,         "muitos pontos: 1 pixel cada, e marcados 2x2 -> %d e %d" % (
            colorido(fino).sum(), colorido(grosso).sum())


def test_clicar_perto_acha_a_camada_e_longe_nao():
    _, ids = tela([reta(0, VERMELHO, [(0, 0), (10, 0)])])
    assert pr.camada_em(ids, 3, 7, raio=4) == 0, "a 2 pixels da linha"
    assert pr.camada_em(ids, 3, 11, raio=4) is None, "a 6 pixels: nada"
    assert pr.camada_em(ids, -50, 3) is None, "fora da imagem: nada"


def test_clicar_entre_duas_linhas_acha_a_mais_proxima():
    a = reta(0, VERMELHO, [(0, 0), (10, 0)])         # linha 5
    b = reta(1, AZUL, [(0, -4), (10, -4)])           # linha 9
    _, ids = tela([a, b])
    assert pr.camada_em(ids, 5, 7, raio=4) in (0, 1)
    assert pr.camada_em(ids, 5, 6, raio=4) == 0, "mais perto da primeira"
    assert pr.camada_em(ids, 5, 8, raio=4) == 1, "mais perto da segunda"


# ---------------------------------------------------------------------------
def luminancia(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


# (a cor de cada forma no fundo branco: ver test_previa_como_autocad.py)


def test_montar_desenhos_leva_a_cor_de_cada_forma_o_negrito_e_filtra_as_escondidas(tmp_path):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    doc.layers.add("Apagada", color=1).off()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A"})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 5})
    msp.add_line((0, 9), (10, 9), dxfattribs={"layer": "Apagada"})
    caminho = str(tmp_path / "m.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    des = pr.montar_desenhos(p, {"A", "Apagada"}, indice, marcadas={"A"}, com_ocultas=True)
    cores_a = sorted(d.rgb for d in des if d.id == indice["A"])
    assert cores_a == [(0, 0, 255), (0, 255, 0)], "uma forma por cor, sem alterar -> %s" % cores_a
    assert all(d.grosso for d in des if d.id == indice["A"]), "marcada: negrito"
    assert not any(d.grosso for d in des if d.id == indice["Apagada"]), "nao marcada: fina"
    assert {d.id for d in pr.montar_desenhos(p, {"A", "Apagada"}, indice, com_ocultas=False)}         == {indice["A"]}, "sem as escondidas, a camada desligada some"


def test_montar_desenhos_por_cor_da_um_id_a_cada_camada_e_cor(tmp_path):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=3)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A", "color": 1})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A", "color": 5})
    caminho = str(tmp_path / "pc.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    indice = {u.chave: i for i, u in enumerate(p.unidades)}
    azul, vermelho = ("A", "#0000ff"), ("A", "#ff0000")
    des = pr.montar_desenhos(p, {azul, vermelho}, indice, marcadas={azul}, por_cor=True)
    por_id = {d.id: d for d in des}
    assert set(por_id) == {indice[azul], indice[vermelho]}, "um id por cor"
    assert por_id[indice[azul]].rgb == (0, 0, 255) and por_id[indice[azul]].grosso
    assert por_id[indice[vermelho]].rgb == (255, 0, 0) and not por_id[indice[vermelho]].grosso
    so_azul = pr.montar_desenhos(p, {azul}, indice, por_cor=True)
    assert [d.rgb for d in so_azul] == [(0, 0, 255)], "so as cores pedidas"


def test_ajustar_enquadra_a_caixa_centralizada_e_sem_distorcer():
    v = pr.ajustar((0, 0, 100, 50), 220, 120, margem=10)
    assert v.escala == pytest.approx(2.0), "cabe 200x100 de area util -> escala 2"
    px, py = v.para_tela(50, 25)
    assert (px, py) == (pytest.approx(110), pytest.approx(60)), "o centro vai para o centro"
    assert v.para_tela(0, 0)[1] == pytest.approx(110), "y cresce para cima no desenho"


def test_ajustar_caixa_de_um_ponto_so_nao_quebra():
    v = pr.ajustar((5, 5, 5, 5), 100, 100)
    assert v.escala > 0 and v.para_tela(5, 5) == (pytest.approx(50), pytest.approx(50))


def test_zoom_mantem_o_ponto_sob_o_mouse():
    v = pr.ajustar((0, 0, 100, 50), 220, 120)
    antes = v.para_desenho(77, 33)
    v.zoom(2.0, 77, 33)
    assert v.para_desenho(77, 33) == (pytest.approx(antes[0]), pytest.approx(antes[1]))
    assert v.escala > 1


def test_arrastar_desloca_o_desenho():
    v = pr.Vista(1.0, 0.0, 0.0)
    v.deslocar(10, -4)
    assert v.para_tela(0, 0) == (pytest.approx(10), pytest.approx(-4))


def test_ppm_tem_o_cabecalho_certo():
    img, _ = tela([])
    dados = pr.para_ppm(img)
    assert dados.startswith(b"P6 20 12 255\n") and len(dados) == len(b"P6 20 12 255\n") + 20 * 12 * 3


# ---------------------------------------------------------------------------
def test_do_desenho_de_verdade_ate_o_clique(tmp_path):
    """Le um DXF, monta os desenhos, desenha e acha a camada pelo clique."""
    dxf, _ = gerar_camadas.gerar(str(tmp_path / "d"))
    p = previa.ler(dxf)
    marcadas = {"Visivel", "Pontos"}
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    desenhos = pr.montar_desenhos(p, marcadas, indice)
    # o texto "AREA VISIVEL" tambem e desenhado, fora do clique
    assert {d.tipo for d in desenhos} == {"linha", "ponto", "texto"}
    assert not any(d.clicavel for d in desenhos if d.tipo == "texto")
    vista = pr.ajustar(p.caixa_de(marcadas), 400, 300, margem=20)
    img, ids = pr.desenhar(desenhos, vista, 400, 300)
    x, y = vista.para_tela(gerar_camadas.X0 + 50, gerar_camadas.Y0 + 20)    # um dos pontos
    assert ids[int(round(y)), int(round(x))] == indice["Pontos"] + 1
    assert pr.camada_em(ids, int(round(x)) + 2, int(round(y)) - 1) == indice["Pontos"]
    x, y = vista.para_tela(gerar_camadas.X0 + 50, gerar_camadas.Y0 + 60)    # lado de cima do quadrado
    assert pr.camada_em(ids, int(round(x)), int(round(y))) == indice["Visivel"]
