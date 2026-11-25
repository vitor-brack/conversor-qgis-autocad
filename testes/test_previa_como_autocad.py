# -*- coding: utf-8 -*-
"""
A previa tem de parecer com o AutoCAD 2007 do pai, com fundo branco.

O que ela deixava de fora e o AutoCAD mostra: a hachura cheia (um lago e uma area
azul, nao so a borda), o padrao das hachuras (HONEY, CROSS, GRASS...) e o
tracejado das linhas (DASHED2 com $LTSCALE 18 no desenho real). No fundo branco, a
cor 7 do AutoCAD (que o programa guarda como preto) aparece preta.

Hachura e tracejado nao mudam o que o clique escolhe: a hachura nao entra no mapa de
clique, e a linha tracejada continua inteira nele (clicar no vao pega a linha).
"""
import ezdxf
import numpy as np
import pytest

from conversor import dxf_estilo, previa, previa_raster as pr

AZUL, VERMELHO, PRETO = (0, 0, 255), (255, 0, 0), (0, 0, 0)
BRANCO = (255, 255, 255)


def desenho(id_, rgb, pontos, tipo="linha", inicio=None, **extra):
    xy = np.array(pontos, dtype=float)
    return pr.Desenho(id_, rgb, tipo, xy, np.array(inicio or [0, len(xy)], dtype=np.int64),
                      **extra)


def aneis(*lista):
    """Um desenho de preenchimento com estes aneis (cada um fechado)."""
    pontos, inicio = [], [0]
    for anel in lista:
        anel = list(anel) + [anel[0]]
        pontos.extend(anel)
        inicio.append(len(pontos))
    return pontos, inicio


def tela(desenhos, w=24, h=14, escala=1.0, x0=0.0, y_topo=10.0, destaque=None):
    return pr.desenhar(desenhos, pr.Vista(escala, x0, y_topo), w, h, destaque=destaque)


def pintado(img):
    return (img != np.array(pr.FUNDO, dtype=np.uint8)).any(axis=2)


# --------------------------------------------------------------------------- fundo
def test_o_fundo_e_branco_como_no_autocad_do_pai():
    assert pr.FUNDO == BRANCO
    img, _ = tela([])
    assert (img == 255).all()


def test_no_fundo_branco_a_cor_7_fica_preta_e_as_outras_nao_mudam():
    # o programa guarda a cor 7 como preto; no fundo branco o AutoCAD a mostra preta
    assert pr.cor_na_tela("#000000") == PRETO
    for cor in ("#0000ff", "#ff0000", "#ffff00", "#00ffff", "#a55252", "#dcdcdc"):
        esperado = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
        assert pr.cor_na_tela(cor) == esperado, "%s fica como e" % cor


def test_o_contorno_da_camada_escolhida_aparece_no_fundo_branco():
    a = desenho(0, PRETO, [(0, 5), (10, 5)])
    img, _ = tela([a], destaque=0)
    assert tuple(img[5, 3]) == PRETO, "a linha continua preta"
    contorno = tuple(img[3, 3])
    assert contorno not in (BRANCO, PRETO), "o contorno e de uma cor que se ve -> %s" % (contorno,)


# --------------------------------------------------------------------------- preenchimento
def test_hachura_solida_pinta_por_dentro():
    pontos, inicio = aneis([(2, 2), (8, 2), (8, 8), (2, 8)])
    img, ids = tela([desenho(0, AZUL, pontos, "preenchimento", inicio, clicavel=False)])
    assert (img[3:7, 3:7] == AZUL).all(), "o miolo fica azul"
    assert not pintado(img)[:, 10:].any() and not pintado(img)[10:].any(), "e nada fora"
    assert not ids.any(), "hachura nao entra no mapa do clique"


def test_furo_fica_vazio_e_ilha_dentro_do_furo_volta_a_ser_cheia():
    pontos, inicio = aneis([(0, 0), (10, 0), (10, 10), (0, 10)],          # borda de fora
                           [(3, 3), (7, 3), (7, 7), (3, 7)],              # furo
                           [(4.5, 4.5), (5.5, 4.5), (5.5, 5.5), (4.5, 5.5)])  # ilha
    img, _ = tela([desenho(0, AZUL, pontos, "preenchimento", inicio, clicavel=False)],
                  w=12, h=12)
    assert tuple(img[10 - 1, 1]) == AZUL, "entre a borda e o furo: cheio"
    assert tuple(img[10 - 4, 4]) == BRANCO, "no furo: vazio"
    assert tuple(img[10 - 5, 5]) == AZUL, "na ilha: cheio de novo"


def test_o_que_vem_depois_na_lista_cobre_o_que_veio_antes():
    # A lista ja vem na ordem do AutoCAD (ver test_previa_igual_ao_autocad.py): a linha
    # desenhada antes de uma hachura solida fica coberta; a de depois, por cima.
    pontos, inicio = aneis([(0, 0), (20, 0), (20, 10), (0, 10)])
    fundo = desenho(1, AZUL, pontos, "preenchimento", inicio, clicavel=False)
    antes = desenho(0, VERMELHO, [(0, 3), (20, 3)])
    depois = desenho(0, VERMELHO, [(0, 7), (20, 7)])
    img, ids = tela([antes, fundo, depois])
    assert tuple(img[10 - 7, 10]) == VERMELHO, "a linha de depois aparece por cima da hachura"
    assert tuple(img[10 - 3, 10]) == AZUL, "a de antes fica coberta"
    assert tuple(img[10 - 5, 10]) == AZUL
    assert ids[10 - 3, 10] == 1 and ids[10 - 7, 10] == 1, "as duas continuam no clique"
    assert ids[10 - 5, 10] == 0


def test_hachura_translucida_mistura_com_o_fundo():
    pontos, inicio = aneis([(2, 2), (8, 2), (8, 8), (2, 8)])
    img, _ = tela([desenho(0, AZUL, pontos, "preenchimento", inicio, clicavel=False,
                           alfa=0.5)])
    r, g, b = (int(v) for v in img[5, 5])
    assert b == 255 and 100 < r < 160 and r == g, "meio azul, meio branco -> %s" % ((r, g, b),)


def test_linhas_do_padrao_da_hachura_nao_entram_no_clique():
    img, ids = tela([desenho(0, VERMELHO, [(0, 5), (20, 5)], clicavel=False)])
    assert pintado(img)[5, 2] and not ids.any()


# --------------------------------------------------------------------------- tracejado
def test_linha_tracejada_tem_vaos_do_tamanho_do_padrao():
    # traco de 4 e vao de 2 unidades, escala 1: tracos em 0-4, 6-10, 12-16, 18-20
    img, ids = tela([desenho(0, VERMELHO, [(0, 5), (20, 5)], tracejado=(4.0, 2.0))])
    linha = pintado(img)[5, 0:21]
    assert np.flatnonzero(~linha).tolist() == [5, 11, 17], \
        "vaos -> %s" % np.flatnonzero(~linha).tolist()
    assert (ids[5, 0:21] == 1).all(), "no mapa do clique a linha e inteira"


def test_traco_de_comprimento_zero_vira_um_pingo():
    img, _ = tela([desenho(0, VERMELHO, [(0, 5), (20, 5)], tracejado=(0.0, 4.0))])
    assert np.flatnonzero(pintado(img)[5]).tolist() == [0, 4, 8, 12, 16, 20]


def test_padrao_menor_que_poucos_pixels_desenha_a_linha_cheia():
    # de longe o AutoCAD tambem mostra o tracejado miudo como linha cheia
    img, _ = tela([desenho(0, VERMELHO, [(0, 50), (200, 50)], tracejado=(4.0, 2.0))],
                  escala=0.1, y_topo=100.0)
    assert pintado(img)[5, 0:21].all()


def test_vao_menor_que_dois_pixels_tambem_desenha_a_linha_cheia():
    # a triangulacao do terreno do desenho real: pingos a cada 4,5 m; de longe, um pingo a
    # cada 1,5 pixel ja parece linha cheia (e gerar pingo a pingo pesava no desenho)
    # o padrao de la tem quatro pingos por periodo: o periodo (6 px) passa do minimo, o vao nao
    img, _ = tela([desenho(0, VERMELHO, [(0, 5), (20, 5)], tracejado=(0.0, 1.5) * 4)])
    assert pintado(img)[5, 0:21].all()


def test_tracejado_segue_pelos_vertices_e_recomeca_em_cada_linha():
    # uma polilinha com um canto: o padrao continua depois do canto
    canto = desenho(0, VERMELHO, [(0, 8), (6, 8), (6, 2)], tracejado=(4.0, 2.0))
    img, _ = tela([canto])
    assert pintado(img)[2, 0:5].all() and not pintado(img)[2, 5], "4 de traco, 2 de vao"
    assert pintado(img)[2, 6], "no canto (distancia 6) recomeca um traco"


def test_vertices_longe_da_tela_nao_atrapalham_o_tracejado():
    longa = desenho(0, VERMELHO, [(-1e6, 5), (1e6, 5)], tracejado=(4.0, 2.0))
    img, _ = tela([longa])
    vaos = np.flatnonzero(~pintado(img)[5]).tolist()
    assert vaos and all(b - a == 6 for a, b in zip(vaos, vaos[1:])), "um vao a cada 6 -> %s" % vaos


# --------------------------------------------------------------------------- estilo do GDAL
def test_o_padrao_do_tracejado_vem_da_style_string():
    estilo = dxf_estilo.analisar_estilo('PEN(c:#ff0000,p:"4.5g 2.25g")')
    assert estilo["tracejado"] == (4.5, 2.25)
    assert dxf_estilo.analisar_estilo("PEN(c:#ff0000)")["tracejado"] == ()


# --------------------------------------------------------------------------- do DXF a tela
@pytest.fixture(scope="module")
def dxf(tmp_path_factory):
    doc = ezdxf.new("R2010", setup=True)            # com os linetypes padrao (DASHED...)
    doc.header["$LTSCALE"] = 2.0
    doc.layers.add("AGUA", color=5)
    doc.layers.add("TERRENO", color=1)
    doc.layers.add("LIMITE", color=7)
    msp = doc.modelspace()
    msp.add_line((0, 0), (20, 0), dxfattribs={"layer": "LIMITE", "linetype": "DASHED"})
    msp.add_line((0, 2), (20, 2), dxfattribs={"layer": "LIMITE"})
    lago = msp.add_hatch(color=256, dxfattribs={"layer": "AGUA"})
    lago.paths.add_polyline_path([(30, 0), (40, 0), (40, 10), (30, 10)], is_closed=True)
    capim = msp.add_hatch(color=256, dxfattribs={"layer": "TERRENO"})
    capim.set_pattern_fill("ANSI31", scale=0.5)
    capim.paths.add_polyline_path([(0, 10), (10, 10), (10, 20), (0, 20)], is_closed=True)
    caminho = str(tmp_path_factory.mktemp("como_autocad") / "d.dxf")
    doc.saveas(caminho)
    return caminho


def test_previa_guarda_as_hachuras_com_a_cor_do_autocad(dxf):
    p = previa.ler(dxf)
    por_camada = {h.camada: h for h in p.hachuras}
    assert por_camada["AGUA"].tipo == "solida" and por_camada["AGUA"].cor == "#0000ff"
    assert por_camada["TERRENO"].tipo == "padrao" and len(por_camada["TERRENO"].inicio) > 3
    assert not any(h.oculta for h in p.hachuras)


def test_previa_guarda_o_tracejado_de_cada_linha_ja_na_escala_do_desenho(dxf):
    p = previa.ler(dxf)
    tracejados = sorted(f.tracejado for f in p.formas("LIMITE"))
    # o padrao do DASHED gravado no desenho, vezes o $LTSCALE (2)
    doc = ezdxf.readfile(dxf)
    definicao = [abs(t.value) for t in doc.linetypes.get("DASHED").pattern_tags.tags
                 if t.code == 49]
    esperado = tuple(v * doc.header["$LTSCALE"] for v in definicao)
    assert tracejados[0] == () and tracejados[1] == pytest.approx(esperado), tracejados


def test_o_lago_sai_azul_por_dentro_e_o_clique_dentro_dele_nao_acha_camada(dxf):
    p = previa.ler(dxf)
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    nomes = {c.nome for c in p.camadas}
    desenhos = pr.montar_desenhos(p, nomes, indice)
    vista = pr.ajustar((0, 0, 40, 20), 400, 200, margem=0)
    img, ids = pr.desenhar(desenhos, vista, 400, 200)
    x, y = (int(round(v)) for v in vista.para_tela(35, 5))
    assert tuple(img[y, x]) == AZUL, "o lago e azul por dentro"
    assert ids[y, x] == 0
    x, y = (int(round(v)) for v in vista.para_tela(5, 2))
    assert tuple(img[y, x]) == PRETO, "a cor 7 sai preta no fundo branco"
    padrao = pintado(img)[int(vista.para_tela(0, 20)[1]) + 2:int(vista.para_tela(0, 10)[1]) - 2,
                          int(vista.para_tela(0, 0)[0]) + 2:int(vista.para_tela(10, 0)[0]) - 2]
    assert 0.03 < padrao.mean() < 0.6, "o capim tem as linhas do padrao -> %.2f" % padrao.mean()


def test_hachura_solida_com_degrade_desligado_fica_com_a_cor_dela(tmp_path):
    # O AutoCAD grava dados de degrade (codigo 450 = 0, "nao e degrade") em hachura solida
    # comum, com um azul padrao como primeira cor. No desenho real os lagos (ciano) e as APP
    # (verde) saiam azuis -- na previa e na conversao para o QGIS.
    from conversor import cad_ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    lago = msp.add_hatch(color=4)
    lago.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    lago.set_gradient((0, 0, 255), (255, 255, 255))
    lago.gradient.kind = 0                    # degrade desligado: e solida
    lago.dxf.pattern_name = "SOLID"
    degrade = msp.add_hatch(color=4)
    degrade.paths.add_polyline_path([(20, 0), (30, 0), (30, 10), (20, 10)], is_closed=True)
    degrade.set_gradient((255, 0, 0), (255, 255, 255))     # degrade de verdade
    caminho = str(tmp_path / "degrade.dxf")
    doc.saveas(caminho)
    assert ezdxf.readfile(caminho).modelspace().query("HATCH")[0].gradient.kind == 0
    cores = {h["handle"]: h["cor"] for h in cad_ezdxf.ler(caminho, lambda *_: None)["hachuras"]}
    assert cores[lago.dxf.handle.upper()] == (0, 255, 255), "a cor 4 (ciano), nao o azul do degrade"
    assert cores[degrade.dxf.handle.upper()] == (255, 0, 0), "degrade de verdade: a primeira cor"


def test_hachura_trazida_para_a_frente_no_autocad_fica_por_cima(tmp_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    vermelha = msp.add_hatch(color=1)
    vermelha.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    azul = msp.add_hatch(color=5)
    azul.paths.add_polyline_path([(5, 0), (15, 0), (15, 10), (5, 10)], is_closed=True)
    # "trazer para a frente" a vermelha, que foi criada antes
    msp.set_redraw_order({vermelha.dxf.handle: "FFFF"})
    msp.add_line((0, 20), (15, 20))
    caminho = str(tmp_path / "ordem.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert [h.cor for h in p.hachuras] == ["#0000ff", "#ff0000"], "a vermelha por ultimo"
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    desenhos = pr.montar_desenhos(p, {c.nome for c in p.camadas}, indice)
    vista = pr.ajustar((0, 0, 15, 20), 150, 200, margem=0)
    img, _ = pr.desenhar(desenhos, vista, 150, 200)
    x, y = (int(round(v)) for v in vista.para_tela(7.5, 5))
    assert tuple(img[y, x]) == VERMELHO, "onde as duas se cobrem, a que veio para a frente"


def test_camada_so_com_hachura_entra_no_desenho_da_janela(raiz, dxf):
    from conversor.gui_camadas import PainelCamadas
    painel = PainelCamadas(raiz)
    try:
        painel.definir_previa(previa.ler(dxf), dxf_pronto=dxf)
        raiz.update_idletasks()
        painel.ver_tudo()
        x, y = (int(round(v)) for v in painel.vista.para_tela(35, 5))
        assert tuple(painel.imagem[y, x]) == AZUL, "o lago aparece na janela"
    finally:
        painel.destroy()


def test_letra_pinta_pela_regra_do_nao_zero():
    # Dois pedacos de letra que se sobrepoem, girando no mesmo sentido: na fonte, a parte
    # comum continua cheia (pela regra par-impar ela viraria um furo). O anel que gira ao
    # contrario e o furo de verdade (o miolo do O).
    a = [(1, 1), (11, 1), (11, 9), (1, 9)]                  # anti-horario
    b = [(7, 1), (17, 1), (17, 9), (7, 9)]                  # anti-horario, sobre o a
    furo = [(14, 3), (14, 7), (16, 7), (16, 3)]             # horario, dentro do b
    pontos, inicio = aneis(a, b, furo)
    letra = desenho(-1, VERMELHO, pontos, "texto", inicio, clicavel=False)
    img, ids = tela([letra])
    assert tuple(img[10 - 5, 9]) == VERMELHO, "a parte comum dos dois pedacos e cheia"
    assert tuple(img[10 - 5, 3]) == VERMELHO
    assert tuple(img[10 - 5, 15]) == pr.FUNDO, "o anel ao contrario e furo"
    assert not ids.any(), "texto fora do clique"
