# -*- coding: utf-8 -*-
"""
Feicao perdida longe do desenho: no mapa real havia 9 polilinhas de dois
vertices, os dois em (0, 0), num terreno a 448 km da origem. A regra e geometrica
(todos os vertices longe da area principal), e a mesma na previa e na conversao.
"""
import numpy as np

from conversor import fora_da_area

X0, Y0 = 448000.0, 6743000.0


def desenho_com_lixo():
    """Mil vertices no terreno (2 km de lado) e um segmento (0,0)-(0,0)."""
    rng = np.random.default_rng(1)
    bom = np.column_stack([X0 + rng.uniform(0, 2000, 1000), Y0 + rng.uniform(0, 1500, 1000)])
    lixo = np.array([[0.0, 0.0], [0.0, 0.0]])
    return bom, lixo


def test_caixa_principal_ignora_o_lixo_na_origem():
    bom, lixo = desenho_com_lixo()
    xmin, ymin, xmax, ymax = fora_da_area.caixa_principal(np.vstack([bom, lixo]))
    # a caixa envolve o terreno (com folga) e fica longe da origem
    assert xmin > 400000 and ymin > 6_000_000, \
        "a caixa nao chega na origem -> x=%.0f y=%.0f" % (xmin, ymin)
    assert xmin < X0 and xmax > X0 + 2000 and ymin < Y0 and ymax > Y0 + 1500, \
        "e envolve o terreno -> %s" % ((xmin, ymin, xmax, ymax),)


def test_feicao_com_todos_os_vertices_na_origem_esta_fora():
    bom, lixo = desenho_com_lixo()
    caixa = fora_da_area.caixa_principal(np.vstack([bom, lixo]))
    assert fora_da_area.todos_fora([(0.0, 0.0), (0.0, 0.0)], caixa), "o segmento na origem"
    assert not fora_da_area.todos_fora([(X0 + 10, Y0 + 10), (X0 + 500, Y0 + 90)], caixa), \
        "uma linha no terreno fica"


def test_linha_que_sai_do_terreno_mas_tem_vertice_dentro_nao_e_descartada():
    # a linha cuja ponta foi parar na origem e a outra esta no terreno: ela e
    # um defeito, mas e um defeito de verdade do desenho; so o que esta INTEIRO
    # fora some, para nao cortar dado bom
    bom, lixo = desenho_com_lixo()
    caixa = fora_da_area.caixa_principal(np.vstack([bom, lixo]))
    assert not fora_da_area.todos_fora([(0.0, 0.0), (X0 + 10, Y0 + 10)], caixa)


def test_desenho_pequeno_demais_nao_tem_area_principal():
    # com poucos vertices nao da para dizer o que e normal: nada e descartado
    assert fora_da_area.caixa_principal(np.array([[0.0, 0.0], [1e6, 1e6]])) is None
    assert not fora_da_area.todos_fora([(0.0, 0.0)], None)


def test_lixo_em_desenho_pequeno_tambem_e_pego():
    # 3 vertices na origem entre 100 do terreno (3%): num desenho pequeno o lixo
    # pesa mais, e mesmo assim a area principal nao pode ir ate a origem
    rng = np.random.default_rng(2)
    bom = np.column_stack([X0 + rng.uniform(0, 800, 100), Y0 + rng.uniform(0, 600, 100)])
    caixa = fora_da_area.caixa_principal(np.vstack([bom, np.zeros((3, 2))]))
    assert caixa is not None and fora_da_area.todos_fora([(0.0, 0.0)], caixa), \
        "a origem esta fora da area principal -> %s" % (caixa,)
    assert not fora_da_area.todos_fora([(X0 + 400, Y0 + 300)], caixa), "o terreno fica"


def test_vertices_fora_diz_vertice_por_vertice():
    caixa = (0.0, 0.0, 10.0, 10.0)
    xy = np.array([[5, 5], [11, 5], [5, -1], [float("nan"), 1], [0, 10]], dtype=float)
    assert list(fora_da_area.vertices_fora(xy, caixa)) == [False, True, True, True, False], \
        "dentro, a direita, abaixo, nao-numero, e na borda (que e dentro)"


def test_vertice_que_nao_e_numero_conta_como_fora():
    bom, _ = desenho_com_lixo()
    caixa = fora_da_area.caixa_principal(bom)
    assert fora_da_area.todos_fora([(float("nan"), 1.0), (float("inf"), 2.0)], caixa)


def test_terreno_comprido_com_dados_espalhados_nao_perde_nada():
    # uma estrada de 30 km, vertices distribuidos ao longo dela: nada e lixo
    x = np.linspace(X0, X0 + 30000, 3000)
    caixa = fora_da_area.caixa_principal(np.column_stack([x, np.full_like(x, Y0)]))
    assert not any(fora_da_area.todos_fora([(xx, Y0)], caixa) for xx in x)
