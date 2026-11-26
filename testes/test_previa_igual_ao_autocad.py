# -*- coding: utf-8 -*-
"""
A previa comparada com as fotos do AutoCAD 2007 do pai, no desenho real.

O que estava diferente e o que o AutoCAD faz:

  ORDEM       o AutoCAD desenha as entidades numa ordem so (a do "trazer para a
              frente", gravada na tabela SORTENTSTABLE; sem ela, a do handle). A
              divisa do desenho real sao tres polilinhas no mesmo lugar, duas
              amarelas e uma vermelha; a amarela e a ultima, e a divisa aparece
              amarela. A previa desenhava por tipo e cor, e a vermelha ficava por
              cima. Linha desenhada antes de uma hachura solida que a cobre some
              (a borda dos lagos, pedacos do martelo do logo).
  SOLID       a entidade SOLID (a seta do norte, as pontas das cotas) e cheia.
  TEXTO       cada letra pelo contorno da fonte, na cor do texto (inclusive a
              trocada no meio de um MTEXT), so o que o AutoCAD mostra: nada de
              camada desligada ou congelada, nem de atributo invisivel ou de bloco
              em camada congelada (os 9 mil rotulos dos pontos do levantamento).
  TABELA      a tabela de areas e uma imagem (OLE) colada no desenho; aparece por
              cima de tudo, como no AutoCAD 2007.
"""
import ezdxf
import numpy as np
import pytest

from conversor import previa, previa_raster as pr
from gerar_ole import arquivo_composto, bmp24, bmp32, com_ole

AMARELO, VERMELHO, AZUL, CIANO = (255, 255, 0), (255, 0, 0), (0, 0, 255), (0, 255, 255)
BRANCO, PRETO, VERDE = (255, 255, 255), (0, 0, 0), (0, 255, 0)


def ler_e_desenhar(caminho, caixa, w=200, h=200, com_ocultas=False):
    p = previa.ler(caminho)
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    desenhos = pr.montar_desenhos(p, {c.nome for c in p.camadas}, indice, com_ocultas=com_ocultas)
    vista = pr.ajustar(caixa, w, h, margem=0)
    img, ids = pr.desenhar(desenhos, vista, w, h)
    return p, vista, img, ids


def cor_em(img, vista, x, y):
    px, py = (int(round(v)) for v in vista.para_tela(x, y))
    return tuple(int(c) for c in img[py, px])


# --------------------------------------------------------------------------- ordem
def test_linhas_no_mesmo_lugar_a_que_o_autocad_desenha_por_ultimo_fica_por_cima(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.add("LOTE", color=2)
    msp = doc.modelspace()
    amarela = msp.add_line((0, 5), (20, 5), dxfattribs={"layer": "LOTE"})
    msp.add_line((0, 5), (20, 5), dxfattribs={"layer": "LOTE", "color": 1})
    msp.add_line((0, 0), (20, 0), dxfattribs={"layer": "LOTE"})        # so para a caixa
    msp.add_line((0, 10), (20, 10), dxfattribs={"layer": "LOTE"})
    msp.set_redraw_order({amarela.dxf.handle: "FFFF"})                 # "trazer para a frente"
    caminho = str(tmp_path / "divisa.dxf")
    doc.saveas(caminho)
    _p, vista, img, _ids = ler_e_desenhar(caminho, (0, 0, 20, 10))
    assert cor_em(img, vista, 10, 5) == AMARELO, "a amarela foi trazida para a frente"


def test_linha_desenhada_antes_da_hachura_solida_some_e_a_de_depois_aparece(tmp_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 3), (20, 3), dxfattribs={"color": 1})            # antes: fica embaixo
    lago = msp.add_hatch(color=5)
    lago.paths.add_polyline_path([(0, 0), (20, 0), (20, 10), (0, 10)], is_closed=True)
    msp.add_line((0, 7), (20, 7), dxfattribs={"color": 1})            # depois: por cima
    caminho = str(tmp_path / "lago.dxf")
    doc.saveas(caminho)
    _p, vista, img, ids = ler_e_desenhar(caminho, (0, 0, 20, 10))
    assert cor_em(img, vista, 10, 3) == AZUL, "a linha de antes fica coberta pela hachura"
    assert cor_em(img, vista, 10, 7) == VERMELHO, "a de depois aparece por cima"
    px, py = (int(round(v)) for v in vista.para_tela(10, 3))
    assert ids[py, px] != 0, "coberta ou nao, a linha continua no mapa do clique"


def test_desenho_grande_entrelacado_continua_na_ordem_por_camada(tmp_path):
    # Com muitos pedacos alternando de camada, a previa nao pode virar milhares de desenhos
    # pequenos (o arrastar travaria): junta cada forma num desenho so.
    doc = ezdxf.new("R2010")
    doc.layers.add("A", color=1)
    doc.layers.add("B", color=5)
    msp = doc.modelspace()
    for i in range(pr_limite() + 10):
        msp.add_line((i, 0), (i, 1), dxfattribs={"layer": "A" if i % 2 else "B"})
    caminho = str(tmp_path / "muitos.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    indice = {c.nome: i for i, c in enumerate(p.camadas)}
    desenhos = pr.montar_desenhos(p, {"A", "B"}, indice)
    assert len(desenhos) <= 4, len(desenhos)


def pr_limite():
    return previa.LIMITE_TRECHOS


# --------------------------------------------------------------------------- SOLID
def test_solid_do_autocad_e_pintado_por_dentro(tmp_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # a ordem dos vertices do SOLID e 1, 2, 4, 3 (o "laco" do AutoCAD)
    msp.add_solid([(0, 0), (10, 0), (0, 10), (10, 10)], dxfattribs={"color": 4})
    caminho = str(tmp_path / "solid.dxf")
    doc.saveas(caminho)
    _p, vista, img, _ids = ler_e_desenhar(caminho, (0, 0, 10, 10))
    assert cor_em(img, vista, 5, 5) == CIANO, "o miolo do SOLID e ciano"
    assert cor_em(img, vista, 2, 8) == CIANO and cor_em(img, vista, 8, 2) == CIANO


# --------------------------------------------------------------------------- textos
def doc_com_estilo():
    doc = ezdxf.new("R2010")
    doc.styles.add("ARIAL", font="arial.ttf")
    return doc


def pintados(img, vista, caixa, rgb):
    """Quantos pixels da cor `rgb` ha dentro da caixa (xmin, ymin, xmax, ymax) do desenho."""
    (x0, y1), (x1, y0) = vista.para_tela(caixa[0], caixa[1]), vista.para_tela(caixa[2], caixa[3])
    recorte = img[int(y0):int(y1) + 1, int(x0):int(x1) + 1]
    return int((recorte == np.array(rgb, dtype=np.uint8)).all(axis=2).sum())


def test_texto_aparece_com_as_letras_na_cor_dele_e_fora_do_clique(tmp_path):
    doc = doc_com_estilo()
    msp = doc.modelspace()
    msp.add_text("OHO", height=10, dxfattribs={"style": "ARIAL", "color": 1, "insert": (0, 0)})
    msp.add_line((0, -5), (40, -5))                     # para a caixa do desenho
    caminho = str(tmp_path / "texto.dxf")
    doc.saveas(caminho)
    p, vista, img, ids = ler_e_desenhar(caminho, (0, -5, 40, 15), w=400, h=200)
    assert [t.texto for t in p.textos] == ["OHO"]
    vermelhos = (img == np.array(VERMELHO, dtype=np.uint8)).all(axis=2)
    assert vermelhos.sum() > 800, "as letras pintadas por dentro -> %d pixels" % vermelhos.sum()
    assert not ids[vermelhos].any(), "texto nao entra no mapa do clique"
    # o primeiro O da Arial com altura 10: a perna vai de x=0,7 a 2,0 e o furo ate 8,9
    assert cor_em(img, vista, 5.4, 5.0) == BRANCO, "o furo do O e furo"
    assert cor_em(img, vista, 1.3, 5.0) == VERMELHO, "a perna do O e cheia"


def test_texto_em_camada_desligada_ou_congelada_nao_aparece(tmp_path):
    doc = doc_com_estilo()
    doc.layers.add("DESLIGADA").off()
    doc.layers.add("CONGELADA").freeze()
    msp = doc.modelspace()
    msp.add_text("AAA", height=10, dxfattribs={"style": "ARIAL", "layer": "DESLIGADA"})
    msp.add_text("BBB", height=10, dxfattribs={"style": "ARIAL", "layer": "CONGELADA",
                                               "insert": (0, 20)})
    msp.add_text("CCC", height=10, dxfattribs={"style": "ARIAL", "insert": (0, 40)})
    caminho = str(tmp_path / "ocultos.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert [t.texto for t in p.textos] == ["CCC"]


def test_cor_trocada_no_meio_do_mtext(tmp_path):
    doc = doc_com_estilo()
    msp = doc.modelspace()
    msp.add_mtext("{\\fArial|b0|i0|c0|p34;\\C1;VVVV \\C5;AAAA}",
                  dxfattribs={"char_height": 10, "insert": (0, 10), "color": 7})
    msp.add_line((0, -2), (120, -2))
    caminho = str(tmp_path / "mtext.dxf")
    doc.saveas(caminho)
    p, vista, img, _ids = ler_e_desenhar(caminho, (0, -2, 120, 12), w=600, h=80)
    assert {t.cor for t in p.textos} == {"#ff0000", "#0000ff"}
    assert (img == np.array(VERMELHO, dtype=np.uint8)).all(axis=2).sum() > 200
    assert (img == np.array(AZUL, dtype=np.uint8)).all(axis=2).sum() > 200


def test_negrito_do_mtext_usa_a_arial_negrito_e_nao_a_arial_black(tmp_path):
    # o logo do desenho real: "Geo" em {\fArial|b1;...}. O ezdxf escolhia a Arial Black.
    doc = doc_com_estilo()
    msp = doc.modelspace()
    msp.add_mtext("{\\fArial|b1|i0|c0|p34;Geo}", dxfattribs={"char_height": 10})
    caminho = str(tmp_path / "negrito.dxf")
    doc.saveas(caminho)
    fontes = {t.fonte.lower() for t in previa.ler(caminho).textos}
    assert fontes == {"arialbd.ttf"}, fontes


def test_atributo_de_bloco_congelado_ou_invisivel_nao_aparece(tmp_path):
    # os 9 mil rotulos dos pontos do levantamento: blocos em camadas congeladas, com os
    # atributos em camadas ligadas. O AutoCAD nao mostra nenhum.
    doc = doc_com_estilo()
    doc.layers.add("PONTOS").freeze()
    doc.layers.add("ROTULOS")
    bloco = doc.blocks.new("PT")
    bloco.add_circle((0, 0), 1)
    bloco.add_attdef("NOME", (2, 0), dxfattribs={"height": 5, "style": "ARIAL", "layer": "ROTULOS"})
    bloco.add_attdef("OBS", (2, -8), dxfattribs={"height": 5, "style": "ARIAL", "layer": "ROTULOS"})
    msp = doc.modelspace()
    congelado = msp.add_blockref("PT", (0, 0), dxfattribs={"layer": "PONTOS"})
    congelado.add_auto_attribs({"NOME": "ESCONDIDO", "OBS": "ESCONDIDO2"})
    ligado = msp.add_blockref("PT", (0, 50))
    ligado.add_auto_attribs({"NOME": "APARECE", "OBS": "INVISIVEL"})
    for a in ligado.attribs:
        if a.dxf.tag == "OBS":
            a.is_invisible = True
    caminho = str(tmp_path / "atributos.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert [t.texto for t in p.textos] == ["APARECE"]
    rotulos = next(c for c in p.camadas if c.nome == "ROTULOS")
    assert rotulos.n_ocultas == 3, "os atributos que o AutoCAD nao mostra contam como ocultos"


def test_texto_da_cota_aparece(tmp_path):
    doc = doc_com_estilo()
    msp = doc.modelspace()
    cota = msp.add_aligned_dim(p1=(0, 0), p2=(50, 0), distance=10,
                               dxfattribs={"color": 1})
    cota.render()
    caminho = str(tmp_path / "cota.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    assert any("50" in t.texto for t in p.textos), [t.texto for t in p.textos]
    assert all(t.cor == "#ff0000" for t in p.textos), "na cor da cota"


def desenho_do_texto(tmp_path, angulo, pixels, mtext=False):
    """O texto "I        I" (com um vao no meio), com `pixels` de altura na tela; devolve
    a cor no meio dele (no vao) e quantos pixels vermelhos ha."""
    doc = doc_com_estilo()
    msp = doc.modelspace()
    if mtext:
        msp.add_mtext("I        I", dxfattribs={"char_height": 1.0, "style": "ARIAL", "color": 1,
                                                 "insert": (10, 10), "rotation": angulo})
    else:
        msp.add_text("I        I", height=1.0, rotation=angulo,
                     dxfattribs={"style": "ARIAL", "color": 1, "insert": (10, 10)})
    caminho = str(tmp_path / ("girado_%s_%s_%s.dxf" % (angulo, pixels, mtext)))
    doc.saveas(caminho)
    p = previa.ler(caminho)
    # entre os dois I, no meio da altura (o MTEXT chega quebrado em um texto por palavra)
    centro = np.vstack([t.xy for t in p.textos]).mean(axis=0)
    nomes = {c.nome for c in p.camadas}
    desenhos = pr.montar_desenhos(p, nomes, {n: i for i, n in enumerate(sorted(nomes))})
    vista = pr.Vista(float(pixels), centro[0] - 40 / pixels, centro[1] + 40 / pixels)
    img, _ = pr.desenhar(desenhos, vista, 80, 80)
    vermelhos = int((img == np.array(VERMELHO, dtype=np.uint8)).all(axis=2).sum())
    return cor_em(img, vista, *centro), vermelhos


@pytest.mark.parametrize("angulo, mtext", [(30.0, False), (0.2, True), (-9.47, True)])
def test_texto_girado_miudo_vira_a_caixa_dele_como_no_autocad(tmp_path, angulo, mtext):
    # Nas fotos do pai, texto girado com ate ~4 pixels de altura na tela do AutoCAD aparece
    # como um retangulo cheio do tamanho dele (o "Acude" a -9,47 graus, os "30,00" das cotas,
    # o rotulo da APP a 0,2 grau); com 4,4 ou mais, as letras.
    meio, _ = desenho_do_texto(tmp_path, angulo, 3.0, mtext)
    assert meio == VERMELHO, "o vao entre as letras fica cheio: e a caixa do texto"
    meio, _ = desenho_do_texto(tmp_path, angulo, 6.0, mtext)
    assert meio == BRANCO, "maior, sao as letras, com o vao aparecendo"


def test_texto_sem_giro_sai_em_letras_ate_menor_e_depois_vira_caixa(tmp_path):
    # O texto sem giro o AutoCAD 2007 manda o Windows escrever, que da conta de letras menores
    # que as do girado: os "50,00" das cotas, com 3,45 pixels, saem em letras na foto 4; o
    # carimbo, com 2,2 a 2,6 pixels na vista geral (foto 1), sai em barras.
    meio, vermelhos = desenho_do_texto(tmp_path, 0.0, 3.5)
    assert meio == BRANCO and vermelhos > 0, "com 3,5 pixels, ainda as letras"
    meio, _ = desenho_do_texto(tmp_path, 0.0, 2.5)
    assert meio == VERMELHO, "com 2,5 pixels, a caixa do texto"


def _tem_fonte(nome):
    try:
        from ezdxf.fonts import fonts
        return fonts.font_manager.has_font(nome)
    except Exception:
        return False


@pytest.mark.skipif(not _tem_fonte("arialn.ttf"), reason="sem a Arial Narrow no Windows")
def test_fonte_estreita_do_autocad_sai_estreita(tmp_path):
    # A swissc.ttf (Swiss 721 Condensed) vem com o AutoCAD. Sem ela, a Arial normal deixava
    # o "Poco Raso Escavado" do desenho do pai 20% mais comprido que na foto (55,6 x 69 px);
    # a Arial Narrow e a do Windows de mesmo desenho.
    doc = ezdxf.new("R2010")
    doc.styles.add("ESTREITA", font="swissc.ttf")
    doc.styles.add("NORMAL", font="arial.ttf")
    msp = doc.modelspace()
    msp.add_text("Poco Raso Escavado", height=1, dxfattribs={"style": "ESTREITA", "insert": (0, 0)})
    msp.add_text("Poco Raso Escavado", height=1, dxfattribs={"style": "NORMAL", "insert": (0, 10)})
    caminho = str(tmp_path / "estreita.dxf")
    doc.saveas(caminho)
    estreita, normal = sorted(previa.ler(caminho).textos, key=lambda t: t.xy[:, 1].min())
    largura = lambda t: float(np.ptp(t.xy[:, 0]))
    razao = largura(estreita) / largura(normal)
    assert 0.75 < razao < 0.88, "a swissc e estreita: %.2f da Arial" % razao
    doc = doc_com_estilo()
    doc.layers.add("NOMES", color=3)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_text("RUA", height=5, dxfattribs={"style": "ARIAL", "layer": "NOMES",
                                              "insert": (100, 100)})
    caminho = str(tmp_path / "so_texto.dxf")
    doc.saveas(caminho)
    p = previa.ler(caminho)
    nomes = next(c for c in p.camadas if c.nome == "NOMES")
    assert nomes.tem_desenho
    caixa = p.caixa_de_itens([nomes], com_ocultas=False)
    assert caixa and caixa[0] >= 99 and caixa[2] > 105, caixa


# --------------------------------------------------------------------------- tabela (OLE)
def test_bmp_de_24_e_de_32_bits_viram_a_mesma_imagem():
    from conversor import previa_ezdxf
    rgb = np.zeros((6, 5, 3), dtype=np.uint8)
    rgb[:3] = VERMELHO
    rgb[3:] = AZUL
    rgb[0, 0] = VERDE
    for dados in (bmp32(rgb), bmp24(rgb)):
        assert (previa_ezdxf.imagem_do_bmp(dados) == rgb).all()


def test_tabela_colada_aparece_no_lugar_dela_por_cima_de_tudo(tmp_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((-5, -5), (25, 15))                         # so para a caixa
    rgb = np.zeros((24, 64, 3), dtype=np.uint8)
    rgb[:12] = VERMELHO                                      # metade de cima
    rgb[12:] = AZUL
    com_ole(msp, b"\0" * 128 + arquivo_composto("CONTENTS", bmp32(rgb)), (0, 10), (20, 0))
    msp.add_line((0, 7.5), (20, 7.5), dxfattribs={"color": 3})    # criada depois, por cima?
    caminho = str(tmp_path / "ole.dxf")
    doc.saveas(caminho)
    p, vista, img, ids = ler_e_desenhar(caminho, (-5, -5, 25, 15), w=300, h=200)
    assert cor_em(img, vista, 10, 2.5) == AZUL
    assert cor_em(img, vista, 10, 7.5) == VERMELHO, "o AutoCAD 2007 mostra a tabela por cima"
    assert cor_em(img, vista, 22, 12) == BRANCO, "e nada fora dela"


# --------------------------------------------------------------------------- padroes miudos
def doc_com_cross(tmp_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    h = msp.add_hatch(color=3)
    h.set_pattern_fill("CROSS", color=3, scale=1.0)        # (sem a cor, o ezdxf poe a 7)
    h.paths.add_polyline_path([(0, 0), (100, 0), (100, 100), (0, 100)], is_closed=True)
    periodo = sum(abs(v) for v in h.pattern.lines[0].dash_length_items)
    caminho = str(tmp_path / "cross.dxf")
    doc.saveas(caminho)
    return caminho, periodo


def fracao_verde(img, vista, a, b):
    (x0, y1), (x1, y0) = vista.para_tela(a, a), vista.para_tela(b, b)
    recorte = img[int(y0) + 1:int(y1), int(x0) + 1:int(x1)]
    return float((recorte == np.array(VERDE, dtype=np.uint8)).all(axis=2).mean())


def test_padrao_miudo_de_longe_vira_tinta_cheia_como_no_autocad(tmp_path):
    # A APP do desenho real (CROSS): de longe o AutoCAD desenha as linhas do padrao
    # inteiras, e a area fica verde cheia; de perto aparecem as cruzinhas.
    caminho, periodo = doc_com_cross(tmp_path)
    p = previa.ler(caminho)
    nomes = {c.nome for c in p.camadas}
    desenhos = pr.montar_desenhos(p, nomes, {n: i for i, n in enumerate(sorted(nomes))})
    # Ate 2 pixels por periodo (as linhas do CROSS ficam a menos de 1 pixel uma da outra; na
    # vista geral da foto do AutoCAD sao 1,6), em qualquer escala: os furos apareciam num
    # xadrez, onde o periodo batia com os pixels. (Mais que isso, as linhas inteiras ficam a
    # mais de 1 pixel e deixam fileiras vazias -- no AutoCAD tambem.)
    for pixels in (0.8, 1.3, 1.6, 1.81, 1.95):
        longe = pr.Vista(pixels / periodo, 0.0, 100.0)
        lado = int(100 * pixels / periodo) + 2
        img, _ = pr.desenhar(desenhos, longe, lado, lado)
        verde = fracao_verde(img, longe, 10, 90)
        assert verde > 0.95, "de longe e verde cheio (%.2f com %.2f px)" % (verde, pixels)
    perto = pr.Vista(12.0 / periodo, 0.0, 100.0)            # 12 pixels por periodo
    img, _ = pr.desenhar(desenhos, perto, int(1200 / periodo) + 2, int(1200 / periodo) + 2)
    verde = fracao_verde(img, perto, 10, 90)
    assert 0.0 < verde < 0.5, "de perto, cruzinhas com o fundo aparecendo (%.2f)" % verde


def test_traco_de_hachura_pinta_como_uma_linha_comum(tmp_path):
    # O AutoCAD acende o traco de hachura do pixel do comeco ao do fim, como qualquer linha.
    # Medido nas fotos do pai pela tinta media de cada regiao (o JPEG e o redimensionamento
    # a preservam): com as pontas incluidas, o GRASS e o CROSS dao a mesma razao foto/nosso
    # das linhas comuns (~1,2); pintando so os pixels de centro coberto, de 1,5 a 3 -- o
    # GRASS virava pingos onde o AutoCAD mostra tufos em Y, e a APP ficava rala.
    caminho, periodo = doc_com_cross(tmp_path)
    p = previa.ler(caminho)
    nomes = {c.nome for c in p.camadas}
    desenhos = pr.montar_desenhos(p, nomes, {n: i for i, n in enumerate(sorted(nomes))})
    vista = pr.Vista(5.25 / periodo, 0.0, 100.0)            # o zoom da foto 4: traco de 1,3 px
    lado = int(100 * 5.25 / periodo) + 2
    img, _ = pr.desenhar(desenhos, vista, lado, lado)
    h = p.hachuras[0]
    comum = pr.Desenho(-1, VERDE, "linha", h.xy, h.inicio, clicavel=False)
    esperado, _ = pr.desenhar([comum], vista, lado, lado)
    verde = np.array(VERDE, dtype=np.uint8)
    pintado = (img == verde).all(axis=2)
    como_linha = (esperado == verde).all(axis=2)
    assert pintado.sum() > 0
    assert (pintado == como_linha).all(), "%d pixels da hachura contra %d da linha comum" % (
        pintado.sum(), como_linha.sum())


def test_tabela_reduzida_mantem_o_traco_preto_como_o_windows():
    # O Windows encolhe figura no modo "preto sobre branco": o pixel escuro sobrevive.
    # Pela media, o texto da tabela ficava cinza claro de longe.
    rgb = np.full((40, 64, 3), 255, dtype=np.uint8)
    rgb[:, 21] = 0                                           # uma coluna preta de 1 pixel
    imagem = previa._imagens_do_ezdxf({"imagens": [
        {"camada": "0", "caixa": (0.0, 0.0, 64.0, 40.0), "imagem": rgb}]})[0]
    d = pr.Desenho(-1, PRETO, "imagem", np.empty((0, 2)), np.zeros(1, dtype=np.int64),
                   clicavel=False, piramide=imagem.piramide, caixa=imagem.caixa)
    vista = pr.Vista(0.25, 0.0, 40.0)                       # 16 x 10 pixels
    img, _ = pr.desenhar([d], vista, 16, 10)
    assert (img[:, 5] == 0).all(), "a coluna preta continua preta: %s" % img[:, 5, 0]
    assert (img[:, 0] == 255).all() and (img[:, 15] == 255).all()
