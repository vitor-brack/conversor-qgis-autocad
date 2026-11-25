# -*- coding: utf-8 -*-
"""
O desenho da previa, montado com numpy numa imagem so.

O desenho real tem 500 mil vertices: um objeto grafico por feicao travaria o
arrastar e o zoom. Aqui toda a previa e uma imagem RGB (que a interface poe
num Canvas) mais um mapa do mesmo tamanho dizendo qual camada esta em cada
pixel -- o clique no desenho acha a camada olhando esse mapa.

A previa imita o AutoCAD do pai, de fundo branco:
  - a cor de cada forma e a do desenho, sem alterar (no AutoCAD a cor significa
    algo: um azul pode ser um corrego). A cor 7, que o programa guarda como preto,
    fica preta -- e assim que o AutoCAD a mostra no fundo branco;
  - hachura solida e pintada por dentro (um lago e azul, nao so a borda) e a de
    padrao mostra as linhas do padrao. Hachura nao entra no mapa do clique;
  - linha tracejada sai tracejada, na escala do desenho. De longe, quando o padrao
    fica menor que uns poucos pixels, vira linha cheia, como no AutoCAD. No mapa do
    clique a linha e sempre inteira: clicar no vao tambem a escolhe.

Camada marcada fica em negrito, mais grossa, na mesma cor -- as linhas e os textos dela. O
texto escolhido no clique tambem (as letras ou, de longe, a barra dele).

Sem interface: so numpy. Tudo aqui e funcao pura, testada sem abrir janela.
"""
from dataclasses import dataclass, replace

import numpy as np

FUNDO = (255, 255, 255)            # branco, como o AutoCAD do pai
CONTORNO = (110, 170, 255)         # em volta da camada escolhida na lista: azul de selecao
LIMITE_AMOSTRAS = 2_000_000        # por bloco de segmentos (limita a memoria)
# Ate este tanto de pontos na tela, cada um e um quadrado (da para ver). Com mais,
# viram 1 pixel: milhares de quadrados se emendam numa mancha so que cobre as
# curvas de nivel (foi o que aconteceu no primeiro desenho real).
PONTOS_PARA_QUADRADO = 400
# O negrito das linhas marcadas tem 3 pixels; com mais de tantos vertices marcados na
# tela (curvas de nivel, por exemplo) ele vira 2, senao as linhas se emendam num bloco.
VERTICES_PARA_NEGRITO_LARGO = 30000
# Um padrao de tracejado (traco + vao) menor que isto, em pixels, vira linha cheia: os
# tracos se emendariam num pontilhado sem sentido. O AutoCAD faz o mesmo de longe.
PIXELS_DO_TRACEJADO = 3.0
# Idem se o menor vao fica abaixo disto: um pingo a cada pixel e meio ja e linha cheia a
# olho (a triangulacao do terreno do desenho real, de longe), e gerar pingo a pingo pesa.
PIXELS_DO_VAO = 2.0
# Hachura de padrao fino demais para desenhar linha a linha (ver cad_ezdxf): uma tinta
# da cor dela, deixando o fundo aparecer um pouco -- de perto, o padrao denso e quase isso.
ALFA_TRANSLUCIDA = 0.6
# Texto com as maiusculas mais baixas que isto, em pixels, o AutoCAD 2007 pinta como a caixa
# dele (uma barra cheia por linha). Nas fotos do pai, o girado: com 4,1 a 4,3 pixels, barras
# (o "Acude" a -9,47 graus, os "30,00" das cotas, o rotulo da APP a 0,2 grau); com 5,2 ou
# mais, letras. O sem giro quem escreve e o Windows, que vai mais longe: letras com 3,45
# pixels (os "50,00" da foto 4), barras com 2,6 ou menos (o carimbo na vista geral, foto 1).
PIXELS_DO_TEXTO_GIRADO = 4.75
PIXELS_DO_TEXTO = 3.0

# Quanto cada coisa se estende em volta do pixel: (de, ate), em pixels.
_LINHA = {"fina": (0, 0), "grossa": (-1, 1), "contorno": (-2, 2), "destaque": (-1, 1)}
_LINHA_MUITAS = {"fina": (0, 0), "grossa": (0, 1), "contorno": (-2, 2), "destaque": (-1, 1)}
_PONTO_POUCOS = {"fina": (-1, 1), "grossa": (-2, 2), "contorno": (-3, 3), "destaque": (-2, 2)}
_PONTO_MUITOS = {"fina": (0, 0), "grossa": (0, 1), "contorno": (-2, 2), "destaque": (-1, 1)}


@dataclass
class Desenho:
    """As formas de um tipo e de uma cor, de uma camada.

    `tipo` e "ponto", "linha", "area", "preenchimento" (o miolo de uma hachura: os
    aneis de `inicio` pintados pela regra par-impar), "texto" (as letras: os aneis
    pintados pela regra do nao-zero, a das fontes, mais o contorno) ou "imagem" (a
    `piramide` de uma figura esticada na `caixa`). `clicavel` falso deixa a forma fora
    do mapa do clique (hachuras, textos, figuras). `tracejado` e (traco, vao, ...) em
    unidades do desenho; () e linha cheia. `alfa` abaixo de 1 deixa o fundo aparecer no
    miolo."""
    id: int
    rgb: tuple
    tipo: str
    xy: np.ndarray                 # Nx2, coordenadas do desenho
    inicio: np.ndarray             # onde cada forma comeca em xy (M+1 valores)
    grosso: bool = False           # camada marcada: negrito
    tracejado: tuple = ()
    clicavel: bool = True
    alfa: float = 1.0
    piramide: list = None          # imagem: a figura e as reducoes dela pela metade
    caixa: tuple = None            # imagem: (xmin, ymin, xmax, ymax) no desenho
    # Hachura de padrao: os tracos sao linhas comuns (o AutoCAD acende do pixel do comeco
    # ao do fim, e o GRASS de longe e um tufo em Y). `cheias` (xy, inicio) sao as linhas do
    # padrao inteiras, desenhadas no lugar dos tracos quando o padrao (`periodo`,
    # `menor_vao`) fica miudo na tela -- como o AutoCAD faz.
    cheias: tuple = None
    periodo: float = 0.0
    menor_vao: float = 0.0
    letreiros: tuple = ()          # texto: ver previa.Trecho.letreiros


class Vista:
    """Que parte do desenho aparece: escala (pixels por unidade) e o canto
    superior esquerdo. O y do desenho cresce para cima, o da tela para baixo."""

    def __init__(self, escala, x0, y_topo):
        self.escala, self.x0, self.y_topo = float(escala), float(x0), float(y_topo)

    def para_tela(self, x, y):
        return ((x - self.x0) * self.escala, (self.y_topo - y) * self.escala)

    def para_desenho(self, px, py):
        return (px / self.escala + self.x0, self.y_topo - py / self.escala)

    def zoom(self, fator, px, py):
        """Aproxima ou afasta mantendo o ponto sob (px, py) onde esta."""
        x, y = self.para_desenho(px, py)
        self.escala *= fator
        self.x0 = x - px / self.escala
        self.y_topo = y + py / self.escala

    def deslocar(self, dx, dy):
        """Arrasta o desenho dx, dy pixels."""
        self.x0 -= dx / self.escala
        self.y_topo += dy / self.escala


def ajustar(caixa, largura, altura, margem=16):
    """A vista que enquadra a caixa inteira, centralizada, sem distorcer."""
    xmin, ymin, xmax, ymax = caixa
    bw, bh = xmax - xmin, ymax - ymin
    util_w, util_h = max(largura - 2 * margem, 1), max(altura - 2 * margem, 1)
    cabe = [util / lado for util, lado in ((util_w, bw), (util_h, bh)) if lado > 0]
    escala = min(cabe) if cabe else 1.0
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    return Vista(escala, cx - (largura / 2) / escala, cy + (altura / 2) / escala)


def regiao_visivel(vista, largura, altura):
    """(xmin, ymin, xmax, ymax): o pedaco do desenho que aparece numa tela de
    `largura` x `altura` pixels."""
    x0, y1 = vista.para_desenho(0, 0)
    x1, y0 = vista.para_desenho(largura, altura)
    return (x0, y0, x1, y1)


def cor_na_tela(cor):
    """A cor do AutoCAD como aparece no fundo branco: exatamente a do desenho. O "branco"
    do AutoCAD (cor 7), que o programa guarda como preto, fica preto: e como o AutoCAD o
    mostra quando o fundo e branco."""
    if isinstance(cor, str):
        cor = tuple(int(cor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(c) for c in cor)


def montar_desenhos(previa, nomes, indice, marcadas=(), com_ocultas=True, por_cor=False,
                    linhas_marcadas=()):
    """Os desenhos das camadas `nomes`, na ordem em que o AutoCAD desenha (o que vem
    depois cobre o que veio antes: ver Previa.trechos). `indice` da o id de cada camada;
    as `marcadas` saem em negrito; sem `com_ocultas`, o que o AutoCAD nao mostra fica de
    fora (com ele, entra por cima de tudo). Com `por_cor`, `nomes`, `indice` e `marcadas`
    falam de (camada, cor) em vez de so camada, e cada cor tem o seu id.

    `linhas_marcadas` sao ids de grupo (as linhas e os textos escolhidos um a um, ver
    Previa.grupos): cada um sai em negrito, por cima, na sua cor; o resto da camada fica
    como estava.

    Hachuras ficam fora do clique."""
    desenhos = []
    camadas_pedidas = {k[0] for k in nomes} if por_cor else set(nomes)
    escolhidas = list(linhas_marcadas)
    for t in previa.trechos:
        if t.origem == "forma":
            _da_forma(desenhos, t.camada, t, nomes, indice, marcadas, por_cor, escolhidas)
        elif t.camada in camadas_pedidas and (com_ocultas or not t.oculta):
            rgb = cor_na_tela(t.cor)
            if t.origem == "texto":
                # o id da camada serve para o destaque da lista; o clique acha o texto pela
                # caixa dele (Previa.achar_texto), nao pelo mapa
                chave = (t.camada, t.cor) if por_cor else t.camada
                ident = indice.get(chave, -1)
                letreiros = getattr(t, "letreiros", ())
                desenhos.append(Desenho(ident, rgb, "texto", t.xy, t.inicio,
                                        grosso=chave in marcadas, clicavel=False,
                                        letreiros=letreiros))
                recorte = _so_os_textos(t, escolhidas) if escolhidas else None
                if recorte is not None:
                    desenhos.append(Desenho(ident, rgb, "texto", recorte[0], recorte[1],
                                            grosso=True, clicavel=False, letreiros=recorte[2]))
            elif t.tipo == "padrao":
                _do_padrao(desenhos, t, rgb)
            else:
                desenhos.append(Desenho(-1, rgb, "preenchimento", t.xy, t.inicio, clicavel=False,
                                        alfa=1.0 if t.tipo == "solida" else ALFA_TRANSLUCIDA))
    # o AutoCAD 2007 mostra o que foi colado (a tabela de areas) por cima de tudo
    vazio = np.empty((0, 2))
    for imagem in getattr(previa, "imagens", ()):
        if imagem.camada in camadas_pedidas:
            desenhos.append(Desenho(-1, (0, 0, 0), "imagem", vazio, np.zeros(1, dtype=np.int64),
                                    clicavel=False, piramide=imagem.piramide,
                                    caixa=imagem.caixa))
    if com_ocultas:
        # o que o AutoCAD esconde nao tem vez na ordem dele: vai por cima, para se ver
        for camada in previa.camadas:
            for forma in previa.formas(camada.nome):
                if forma.oculta:
                    _da_forma(desenhos, camada.nome, forma, nomes, indice, marcadas, por_cor,
                              escolhidas)
    return desenhos


def _do_padrao(desenhos, t, rgb):
    """Os tracos de uma hachura de padrao: um desenho por linha do padrao (cada uma tem o
    seu periodo), com as linhas inteiras para quando o padrao fica miudo."""
    familias = [f for f in getattr(t, "familias", ()) or () if f.ate > f.de]
    if not familias:
        desenhos.append(Desenho(-1, rgb, "linha", t.xy, t.inicio, clicavel=False))
        return
    for f in familias:
        a = t.inicio[f.de]
        desenhos.append(Desenho(-1, rgb, "linha", t.xy[a:t.inicio[f.ate]],
                                t.inicio[f.de:f.ate + 1] - a, clicavel=False,
                                cheias=(f.xy, f.inicio), periodo=f.periodo,
                                menor_vao=f.menor_vao))


def _da_forma(desenhos, camada, forma, nomes, indice, marcadas, por_cor, escolhidas):
    """Os desenhos de uma forma (ou de um trecho dela) da `camada`, se ela foi pedida."""
    chave = (camada, forma.cor) if por_cor else camada
    if chave not in nomes:
        return
    rgb = cor_na_tela(forma.cor)
    tracejado = getattr(forma, "tracejado", ())
    if getattr(forma, "cheia", False):
        # o SOLID: o miolo pintado (fora do clique) e a borda, que o clique acha
        desenhos.append(Desenho(-1, rgb, "preenchimento", forma.xy, forma.inicio,
                                clicavel=False))
    desenhos.append(Desenho(indice[chave], rgb, forma.tipo, forma.xy, forma.inicio,
                            grosso=chave in marcadas, tracejado=tracejado))
    recorte = _so_as_linhas(forma, escolhidas) if escolhidas else None
    if recorte is not None:
        desenhos.append(Desenho(indice[chave], rgb, forma.tipo, recorte[0], recorte[1],
                                grosso=True, tracejado=tracejado))


def _so_os_textos(t, grupos):
    """(xy, inicio, letreiros) so dos textos do trecho que pertencem aos `grupos`; None se nao
    tem nenhum (ou se o trecho nao diz o grupo de cada texto)."""
    letreiros = getattr(t, "letreiros", ())
    grupos_dos_textos = getattr(t, "grupos", None)
    if grupos_dos_textos is None or not letreiros or len(grupos_dos_textos) != len(letreiros[0]):
        return None
    quais = np.flatnonzero(np.isin(grupos_dos_textos, list(grupos)))
    if not len(quais):
        return None
    aneis, alturas, girados, caixas = letreiros
    fim = np.cumsum(aneis)
    comeco = fim - aneis
    pedacos, inicios, deslocamento = [], [], 0
    for i in quais.tolist():
        a, b = int(t.inicio[comeco[i]]), int(t.inicio[fim[i]])
        pedacos.append(t.xy[a:b])
        inicios.append(t.inicio[comeco[i]:fim[i]] - a + deslocamento)
        deslocamento += b - a
    inicio = np.concatenate(inicios + [[deslocamento]]).astype(np.int64)
    return (np.vstack(pedacos), inicio,
            (aneis[quais], alturas[quais], girados[quais], caixas[quais]))


def _so_as_linhas(forma, grupos):
    """(xy, inicio) so dos vetores da forma que pertencem aos `grupos`; None se nao tem nenhum."""
    if forma.grupos is None:
        return None
    vetores = np.flatnonzero(np.isin(forma.grupos, grupos))
    if not len(vetores):
        return None
    pedacos = [forma.xy[forma.inicio[i]:forma.inicio[i + 1]] for i in vetores]
    inicio = np.concatenate([[0], np.cumsum([len(v) for v in pedacos])]).astype(np.int64)
    return np.vstack(pedacos), inicio


def desenhar(desenhos, vista, largura, altura, destaque=None, fundo=FUNDO):
    """Devolve (imagem HxWx3 uint8, mapa HxW uint16 com o id da camada + 1).

    Primeiro as camadas comuns, na ordem da lista (a do AutoCAD: o que vem depois cobre o
    que veio antes), depois as marcadas (em negrito, por cima) e por fim a escolhida na
    lista: um contorno azul e, por dentro, a cor dela."""
    img = np.empty((altura, largura, 3), dtype=np.uint8)
    img[:] = fundo
    ids = np.zeros((altura, largura), dtype=np.uint16)
    poucos = _pontos_na_tela(desenhos, vista, largura, altura) <= PONTOS_PARA_QUADRADO
    muitas = _linhas_marcadas_na_tela(desenhos, vista, largura, altura) > VERTICES_PARA_NEGRITO_LARGO
    comuns = [d for d in desenhos if d.id != destaque and not d.grosso]
    marcadas = [d for d in desenhos if d.id != destaque and d.grosso]
    escolhidos = [d for d in desenhos if d.id == destaque]
    for d in comuns:
        _desenhar_um(img, ids, d, vista, d.rgb, "fina", poucos, muitas)
    for d in marcadas:
        _desenhar_um(img, ids, d, vista, d.rgb, "grossa", poucos, muitas)
    for d in escolhidos:
        _desenhar_um(img, ids, d, vista, CONTORNO, "contorno", poucos, muitas)
    for d in escolhidos:
        _desenhar_um(img, ids, d, vista, d.rgb, "destaque", poucos, muitas)
    return img, ids


def para_ppm(img):
    """A imagem como PPM (P6), que o Tk aceita direto, sem biblioteca de imagem."""
    altura, largura = img.shape[:2]
    return b"P6 %d %d 255\n" % (largura, altura) + np.ascontiguousarray(img).tobytes()


def camada_em(ids, x, y, raio=4):
    """O id da camada no pixel (x, y) ou no mais proximo dentro do raio."""
    altura, largura = ids.shape
    x0, x1 = max(x - raio, 0), min(x + raio + 1, largura)
    y0, y1 = max(y - raio, 0), min(y + raio + 1, altura)
    if x0 >= x1 or y0 >= y1:
        return None
    janela = ids[y0:y1, x0:x1]
    ys, xs = np.nonzero(janela)
    if not len(ys):
        return None
    k = int(((xs + x0 - x) ** 2 + (ys + y0 - y) ** 2).argmin())
    return int(janela[ys[k], xs[k]]) - 1


# ---------------------------------------------------------------------------
def _pontos_na_tela(desenhos, vista, largura, altura):
    """Quantos pontos caem dentro da janela (so eles contam para o tamanho do ponto)."""
    total = 0
    for d in desenhos:
        if d.tipo != "ponto":
            continue
        px = (d.xy[:, 0] - vista.x0) * vista.escala
        py = (vista.y_topo - d.xy[:, 1]) * vista.escala
        total += int(((px >= 0) & (px < largura) & (py >= 0) & (py < altura)).sum())
    return total


def _linhas_marcadas_na_tela(desenhos, vista, largura, altura):
    """Quantos vertices de linhas e areas marcadas caem dentro da janela."""
    total = 0
    for d in desenhos:
        if d.tipo in ("ponto", "texto") or not d.grosso:
            continue
        px = (d.xy[:, 0] - vista.x0) * vista.escala
        py = (vista.y_topo - d.xy[:, 1]) * vista.escala
        total += int(((px >= 0) & (px < largura) & (py >= 0) & (py < altura)).sum())
    return total


def _desenhar_um(img, ids, d, vista, rgb, nivel, poucos_pontos, muitas_linhas):
    if d.tipo == "preenchimento":
        _preencher(img, d, vista, rgb, d.alfa)
        return
    if d.tipo == "imagem":
        _colar(img, d, vista)
        return
    if d.tipo == "texto":
        for parte, contorno in _letras_ou_caixas(d, vista):
            # As letras: o miolo e o contorno, de 1 pixel -- o AutoCAD pinta todo pixel que a
            # letra toca, e de longe o texto fica cheio como na tela dele, em vez de sumir. A
            # caixa, so o miolo: com o contorno, as barras das linhas de um MTEXT se emendavam
            # (na foto, 6,5 pixels de barra para a celula de 6,45, e um fio entre as linhas).
            # Em negrito (camada marcada, texto escolhido) ou em destaque, as duas ganham o
            # contorno mais grosso das linhas.
            _preencher(img, parte, vista, rgb, regra="nao-zero")
            if not contorno and nivel == "fina":
                continue
            px = (parte.xy[:, 0] - vista.x0) * vista.escala
            py = (vista.y_topo - parte.xy[:, 1]) * vista.escala
            segmentos = _segmentos(parte, px, py)
            if segmentos is not None:
                _i, ax, ay, bx, by = segmentos
                _tracos(img, None, *_cortar(ax, ay, bx, by, img.shape[1], img.shape[0]), rgb, 0,
                        _LINHA[nivel])
        return
    if d.cheias is not None and d.periodo > 0 and (
            d.periodo * vista.escala < PIXELS_DO_TRACEJADO
            or d.menor_vao * vista.escala < PIXELS_DO_VAO):
        # padrao de hachura miudo na tela: as linhas dele inteiras
        d = replace(d, xy=d.cheias[0], inicio=d.cheias[1], cheias=None)
    mapa = ids if d.clicavel else None
    px = (d.xy[:, 0] - vista.x0) * vista.escala
    py = (vista.y_topo - d.xy[:, 1]) * vista.escala
    if d.tipo == "ponto":
        ok = np.isfinite(px) & np.isfinite(py)
        tamanho = (_PONTO_POUCOS if poucos_pontos else _PONTO_MUITOS)[nivel]
        _marcar(img, mapa, np.rint(px[ok]).astype(np.int64), np.rint(py[ok]).astype(np.int64),
                rgb, d.id + 1, tamanho)
        return
    segmentos = _segmentos(d, px, py)
    if segmentos is None:
        return
    indices, ax, ay, bx, by = segmentos
    largura, altura = img.shape[1], img.shape[0]
    tamanho = (_LINHA_MUITAS if muitas_linhas else _LINHA)[nivel]
    padrao = d.tracejado
    if (not padrao or nivel == "contorno"
            or sum(padrao) * vista.escala < PIXELS_DO_TRACEJADO
            or min(padrao[1::2]) * vista.escala < PIXELS_DO_VAO):
        _tracos(img, mapa, *_cortar(ax, ay, bx, by, largura, altura), rgb, d.id + 1, tamanho)
        return
    if mapa is not None:            # no mapa do clique a linha continua inteira
        _tracos(None, mapa, *_cortar(ax, ay, bx, by, largura, altura), rgb, d.id + 1, tamanho)
    _tracos(img, None, *_tracejar(d, indices, ax, ay, bx, by, padrao, largura, altura),
            rgb, d.id + 1, tamanho)


def _segmentos(d, px, py):
    """(indice do primeiro vertice, ax, ay, bx, by) dos segmentos das formas, em pixels, sem
    ligar uma forma a outra e sem os que tem vertice invalido. None se nao ha segmento."""
    n = len(px)
    if n < 2:
        return None
    valido = np.ones(n - 1, dtype=bool)
    valido[d.inicio[1:-1] - 1] = False            # nao liga uma forma a outra
    indices = np.flatnonzero(valido)
    ax, ay, bx, by = px[indices], py[indices], px[indices + 1], py[indices + 1]
    ok = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(bx) & np.isfinite(by)
    return indices[ok], ax[ok], ay[ok], bx[ok], by[ok]


def _limites(ax, ay, bx, by, largura, altura):
    """Liang-Barsky em vetor: (dentro, t0, t1) de cada segmento na janela (com 1 pixel de
    folga). `dentro` e falso para os que ficam inteiros fora."""
    dx, dy = bx - ax, by - ay
    t0 = np.zeros(len(ax))
    t1 = np.ones(len(ax))
    for p, q in ((-dx, ax + 1), (dx, largura - ax), (-dy, ay + 1), (dy, altura - ay)):
        with np.errstate(divide="ignore", invalid="ignore"):
            r = q / p
        t0 = np.where(p < 0, np.maximum(t0, r), t0)
        t1 = np.where(p > 0, np.minimum(t1, r), t1)
        t1 = np.where((p == 0) & (q < 0), -1.0, t1)       # paralelo e fora
    return t0 <= t1, t0, t1


def _cortar(ax, ay, bx, by, largura, altura):
    """Corta os segmentos na janela e descarta os que ficam inteiros fora."""
    ok, t0, t1 = _limites(ax, ay, bx, by, largura, altura)
    ax, ay, dx, dy, t0, t1 = ax[ok], ay[ok], (bx - ax)[ok], (by - ay)[ok], t0[ok], t1[ok]
    return ax + t0 * dx, ay + t0 * dy, ax + t1 * dx, ay + t1 * dy


def _tracejar(d, indices, ax, ay, bx, by, padrao, largura, altura):
    """Os tracos acesos do `padrao` (traco, vao, traco, vao... em unidades do desenho) ao
    longo de cada linha da forma, ja cortados na janela, em pixels.

    O padrao corre pela linha inteira, atravessando os vertices, e recomeca em cada linha
    (cada feicao). Traco de comprimento zero e um pingo. So se gera o que cai na janela:
    uma linha de quilometros com zoom de perto continua barata."""
    xy = d.xy
    passo = np.hypot(xy[1:, 0] - xy[:-1, 0], xy[1:, 1] - xy[:-1, 1])
    passo = np.where(np.isfinite(passo), passo, 0.0)
    passo[d.inicio[1:-1] - 1] = 0.0               # a ligacao entre duas linhas nao conta
    acumulado = np.concatenate([[0.0], np.cumsum(passo)])
    linha_do_vertice = np.searchsorted(d.inicio, np.arange(len(xy)), side="right") - 1
    distancia = acumulado - acumulado[d.inicio[linha_do_vertice]]

    comprimento, comeco = passo[indices], distancia[indices]
    ok, t0, t1 = _limites(ax, ay, bx, by, largura, altura)
    ok &= comprimento > 0
    ax, ay, bx, by = ax[ok], ay[ok], bx[ok], by[ok]
    comprimento, comeco, t0, t1 = comprimento[ok], comeco[ok], t0[ok], t1[ok]
    u0, u1 = comeco + t0 * comprimento, comeco + t1 * comprimento   # o trecho na janela

    periodo = float(sum(padrao))
    acesos, pos = [], 0.0
    for i, medida in enumerate(padrao):
        if i % 2 == 0:
            acesos.append((pos, pos + medida))
        pos += medida
    k0 = np.floor(u0 / periodo).astype(np.int64)
    quantos = np.floor(u1 / periodo).astype(np.int64) - k0 + 1
    seg = np.repeat(np.arange(len(u0)), quantos)
    primeiro = np.cumsum(quantos) - quantos
    base = (k0[seg] + (np.arange(len(seg)) - primeiro[seg])) * periodo

    pedacos = []
    for a, b in acesos:
        s, e = base + a, base + b
        if b > a:
            s, e = np.maximum(s, u0[seg]), np.minimum(e, u1[seg])
            fica = e > s
        else:                                      # pingo
            fica = (s >= u0[seg]) & (s <= u1[seg])
        j = seg[fica]
        ta = (s[fica] - comeco[j]) / comprimento[j]
        tb = (e[fica] - comeco[j]) / comprimento[j]
        dx, dy = bx[j] - ax[j], by[j] - ay[j]
        pedacos.append((ax[j] + ta * dx, ay[j] + ta * dy, ax[j] + tb * dx, ay[j] + tb * dy))
    if not pedacos:
        vazio = np.empty(0)
        return vazio, vazio, vazio, vazio
    return tuple(np.concatenate([p[k] for p in pedacos]) for k in range(4))


def _letras_ou_caixas(d, vista):
    """As letras dos textos e, no lugar das do texto que fica miudo na tela, a caixa dele (ver
    PIXELS_DO_TEXTO): [(Desenho, com contorno)], um ou dois."""
    if not d.letreiros:
        return [(d, True)]
    aneis, alturas, girados, caixas = d.letreiros
    limite = np.where(girados, PIXELS_DO_TEXTO_GIRADO, PIXELS_DO_TEXTO)
    miudo = (alturas > 0) & (alturas * vista.escala < limite)
    if not miudo.any():
        return [(d, True)]
    partes = []
    manter = ~np.repeat(miudo, aneis)                     # um valor por anel
    if manter.any():
        tamanhos = np.diff(d.inicio)
        xy = d.xy[np.repeat(manter, tamanhos)]
        inicio = np.concatenate([[0], np.cumsum(tamanhos[manter])]).astype(np.int64)
        partes.append((replace(d, xy=xy, inicio=inicio, letreiros=()), True))
    k = int(miudo.sum())
    partes.append((replace(d, xy=caixas[miudo].reshape(-1, 2),
                           inicio=np.arange(0, 5 * k + 1, 5, dtype=np.int64), letreiros=()),
                   False))
    return partes


def _tracos(img, ids, ax, ay, bx, by, rgb, valor, tamanho):
    """Desenha os segmentos (ja na janela), em blocos para limitar a memoria."""
    if not len(ax):
        return
    comprimento = np.maximum(np.abs(bx - ax), np.abs(by - ay))
    passos = np.ceil(comprimento).astype(np.int64) + 1
    acumulado = np.cumsum(passos)
    comeco = 0
    while comeco < len(passos):
        base = acumulado[comeco - 1] if comeco else 0
        fim = max(int(np.searchsorted(acumulado, base + LIMITE_AMOSTRAS, side="right")),
                  comeco + 1)
        _amostrar(img, ids, ax[comeco:fim], ay[comeco:fim], bx[comeco:fim], by[comeco:fim],
                  passos[comeco:fim], rgb, valor, tamanho)
        comeco = fim


def _preencher(img, d, vista, rgb, alfa=1.0, regra="par-impar"):
    """Pinta o miolo dos aneis de `d` pela regra par-impar (a das hachuras do AutoCAD: a
    borda de fora e cheia, o furo e vazio, a ilha dentro do furo volta a ser cheia) ou
    pela do nao-zero (a das fontes: o furo e o anel que gira ao contrario, e dois
    pedacos de letra que se sobrepoem continuam cheios).

    Um pixel e pintado quando o centro dele esta dentro. Para cada linha da tela, os
    cruzamentos com as bordas, em ordem, abrem e fecham trechos pintados."""
    altura, largura = img.shape[:2]
    px = (d.xy[:, 0] - vista.x0) * vista.escala
    py = (vista.y_topo - d.xy[:, 1]) * vista.escala
    segmentos = _segmentos(d, px, py)
    if segmentos is None:
        return
    _i, ax, ay, bx, by = segmentos
    baixo, cima = np.minimum(ay, by), np.maximum(ay, by)
    # as linhas da tela que a aresta cruza: baixo <= j < cima (a horizontal nao cruza nada)
    j0 = np.maximum(np.ceil(baixo), 0)
    j1 = np.minimum(np.ceil(cima) - 1, altura - 1)
    ok = (j1 >= j0) & (cima > baixo)
    if not ok.any():
        return
    ax, ay, bx, by = ax[ok], ay[ok], bx[ok], by[ok]
    j0, j1 = j0[ok].astype(np.int64), j1[ok].astype(np.int64)
    quantos = j1 - j0 + 1
    aresta = np.repeat(np.arange(len(quantos)), quantos)
    primeiro = np.cumsum(quantos) - quantos
    j = j0[aresta] + (np.arange(len(aresta)) - primeiro[aresta])
    x = ax[aresta] + (j - ay[aresta]) * (bx[aresta] - ax[aresta]) / (by[aresta] - ay[aresta])
    sentido = np.where(by[aresta] > ay[aresta], 1, -1)
    ordem = np.lexsort((x, j))
    j, x, sentido = j[ordem], x[ordem], sentido[ordem]
    # Cada linha da tela cruza as bordas um numero par de vezes (e, no nao-zero, com a soma
    # dos sentidos zero). Uma linha que nao fecha (borda aberta por um vertice invalido)
    # fica sem pintar, em vez de pintar errado ate a beira.
    linhas_, comeco, contagem = np.unique(j, return_index=True, return_counts=True)
    if regra == "nao-zero":
        giro = np.cumsum(sentido)
        antes = np.repeat(giro[comeco] - sentido[comeco], contagem)
        giro = giro - antes                      # o giro depois de cada cruzamento
        aberta = np.add.reduceat(sentido, comeco) != 0
    else:
        aberta = contagem % 2 == 1
    if aberta.any():
        manter = ~np.repeat(aberta, contagem)
        j, x = j[manter], x[manter]
        if regra == "nao-zero":
            giro = giro[manter]
    if not len(j):
        return
    if regra == "nao-zero":
        # pinta de um cruzamento ao seguinte, na mesma linha, enquanto o giro nao e zero
        par = (j[1:] == j[:-1]) & (giro[:-1] != 0)
        linha, xa, xb = j[:-1][par], x[:-1][par], x[1:][par]
    else:
        linha, xa, xb = j[0::2], x[0::2], x[1::2]
    i0 = np.maximum(np.ceil(xa), 0)
    i1 = np.minimum(np.ceil(xb) - 1, largura - 1)
    ok = i1 >= i0
    linha, i0, i1 = linha[ok], i0[ok].astype(np.int64), i1[ok].astype(np.int64)
    n = i1 - i0 + 1
    if not n.sum():
        return
    linhas = np.repeat(linha, n)
    colunas = np.repeat(i0, n) + (np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n))
    if alfa >= 1.0:
        img[linhas, colunas] = rgb
    else:
        misturado = img[linhas, colunas] * (1.0 - alfa) + np.array(rgb, dtype=float) * alfa
        img[linhas, colunas] = np.clip(misturado + 0.5, 0, 255).astype(np.uint8)


def _colar(img, d, vista):
    """Estica a figura de `d` na caixa dela. Aumentando, cada pixel da tela pega o pixel
    da figura mais perto; diminuindo, junta todos os pixels da figura que caem nele como o
    Windows faz (o E bit a bit do modo "preto sobre branco"): o traco fino e o texto da
    tabela continuam pretos de longe, em vez de sumir ou virar cinza. A piramide (as
    reducoes pela metade, feitas do mesmo jeito) poupa o trabalho de longe."""
    altura, largura = img.shape[:2]
    xmin, ymin, xmax, ymax = d.caixa
    sx0, sy0 = vista.para_tela(xmin, ymax)           # canto de cima, a esquerda
    sx1, sy1 = vista.para_tela(xmax, ymin)
    if not (sx1 > sx0 and sy1 > sy0):
        return
    # o pixel i tem o centro em i (como no resto deste arquivo)
    i0, i1 = max(int(np.ceil(sx0)), 0), min(int(np.ceil(sx1)), largura)
    j0, j1 = max(int(np.ceil(sy0)), 0), min(int(np.ceil(sy1)), altura)
    if i0 >= i1 or j0 >= j1:
        return
    base = d.piramide[0]
    reducao = max((sx1 - sx0) / base.shape[1], (sy1 - sy0) / base.shape[0])
    nivel = 0
    while nivel + 1 < len(d.piramide) and reducao * 2 ** (nivel + 1) <= 1.0:
        nivel += 1
    fig = _no_eixo(d.piramide[nivel], 0, j0, j1, sy0, sy1)
    img[j0:j1, i0:i1] = _no_eixo(fig, 1, i0, i1, sx0, sx1)


def _no_eixo(fig, eixo, p0, p1, s0, s1):
    """A figura ao longo de um eixo nos pixels p0..p1-1 da tela, sendo que ela vai de s0 a
    s1 (em pixels) nesse eixo. Ver _colar."""
    n = fig.shape[eixo]
    pixels = np.arange(p0, p1, dtype=float)
    if s1 - s0 >= n:                                 # aumentando: o mais perto
        indices = np.clip(((pixels - s0) / (s1 - s0) * n).astype(np.int64), 0, n - 1)
        return np.take(fig, indices, axis=eixo)
    # diminuindo: o pixel i cobre a figura de (i - 0.5) a (i + 0.5)
    comecos = np.clip(np.floor((pixels - 0.5 - s0) / (s1 - s0) * n).astype(np.int64), 0, n - 1)
    fim = int(np.clip(np.floor((p1 - 0.5 - s0) / (s1 - s0) * n), comecos[-1] + 1, n))
    corte = [slice(None)] * fig.ndim
    corte[eixo] = slice(0, fim)
    return np.bitwise_and.reduceat(fig[tuple(corte)], comecos, axis=eixo)


def _amostrar(img, ids, ax, ay, bx, by, passos, rgb, valor, tamanho):
    """Um pixel por passo ao longo de cada segmento, das duas pontas, sem deixar buraco."""
    seg = np.repeat(np.arange(len(passos)), passos)
    primeiro = np.cumsum(passos) - passos
    k = np.arange(len(seg)) - primeiro[seg]
    t = k / np.maximum(passos[seg] - 1, 1)
    x = np.rint(ax[seg] + t * (bx[seg] - ax[seg])).astype(np.int64)
    y = np.rint(ay[seg] + t * (by[seg] - ay[seg])).astype(np.int64)
    _marcar(img, ids, x, y, rgb, valor, tamanho)


def _marcar(img, ids, ix, iy, rgb, valor, tamanho):
    """Pinta, em cada pixel (ix, iy) que cabe na imagem, um quadrado que vai de
    `de` a `ate` pixels em volta (tamanho = (de, ate)). Sem `img`, so o mapa do clique;
    sem `ids`, so a imagem."""
    de, ate = tamanho
    altura, largura = (ids if ids is not None else img).shape[:2]
    for dy in range(de, ate + 1):
        for dx in range(de, ate + 1):
            x, y = ix + dx, iy + dy
            ok = (x >= 0) & (x < largura) & (y >= 0) & (y < altura)
            if img is not None:
                img[y[ok], x[ok]] = rgb
            if ids is not None:
                ids[y[ok], x[ok]] = valor
