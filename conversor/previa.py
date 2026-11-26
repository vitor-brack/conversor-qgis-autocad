# -*- coding: utf-8 -*-
"""
O desenho lido para a lista de camadas e a previa. Sem nenhuma interface.

Uma passada pelas entidades, do mesmo jeito que a conversao as le (mesmo
VRT, mesmo nome de camada, mesmas exclusoes), guardando para cada camada:

  - quantas feicoes de cada tipo ela tem (pontos, linhas, areas, textos,
    hachuras), para a lista dizer o que tem dentro;
  - a cor dominante (para a amostra de cor da lista);
  - os vertices de pontos, linhas e areas, em vetores do numpy, para a previa
    desenhar sem criar um objeto por feicao. Cada forma leva a cor propria da
    feicao (a cor do CAD significa algo: azul pode ser um corrego), o tracejado
    da linha (o padrao que o GDAL ja da na escala do desenho) e se o AutoCAD a
    esconde. Texto, aqui, so e contado: as letras vem do ezdxf (ver previa_ezdxf.py).

As hachuras vem do ezdxf (cad_ezdxf.py), as mesmas que a conversao leva para o
QGIS: a solida como poligonos (com furos e ilhas), a com padrao como as linhas do
padrao recortadas pela borda, na cor certa. Elas sao desenhadas, mas nao entram no
clique.

As feicoes longe do desenho (ver fora_da_area.py) ficam de fora das formas e
do enquadramento, mas sao contadas, para a janela avisar.

Cada forma tambem diz de que "linha" e cada vetor dela. No AutoCAD cada trecho reto
e uma entidade (um quadrado de quatro LINE tem quatro), mas para quem olha e uma linha
so: as pecas que se encostam pelas pontas, na mesma camada e na mesma cor, formam um
`Grupo`. Ponto e area contam um por um. O clique no desenho acha o grupo mais perto
(`Previa.achar_grupo`) e a conversao leva as feicoes dele (`Grupo.fids`: o id que o
GDAL da a cada feicao, que e o mesmo em toda leitura do mesmo arquivo -- o handle do
AutoCAD nao serve, porque repete dentro de blocos).

Cada texto tambem e um grupo: o clique dentro da caixa dele o escolhe
(`Previa.achar_texto`). As letras vem do ezdxf e a feicao, do GDAL; o handle liga um ao
outro (ver _grupos_dos_textos).
"""
import collections
import itertools
from dataclasses import dataclass, field

import numpy as np

from . import cad_ezdxf, convert, dxf_estilo, fora_da_area

GEOMETRIA = ("ponto", "linha", "area")
ORDEM = ("ponto", "linha", "area", "texto", "hachura", "imagem")
ROTULOS = {"ponto": ("ponto", "pontos"), "linha": ("linha", "linhas"),
           "area": ("area", "areas"), "texto": ("texto", "textos"),
           "hachura": ("hachura", "hachuras"), "imagem": ("figura", "figuras")}


class _Resumo:
    """O que a lista mostra de uma camada, ou de uma cor de camada."""

    @property
    def tem_geometria(self):
        return any(self.contagem.get(tipo) for tipo in GEOMETRIA)

    @property
    def tem_desenho(self):
        """Tem algo que a previa desenha: pontos, linhas, areas, textos, hachuras ou
        figuras."""
        return self.tem_geometria or any(self.contagem.get(t)
                                         for t in ("texto", "hachura", "imagem"))

    def resumo(self):
        """"1860 pontos, 483 linhas": o que tem dentro."""
        partes = []
        for tipo in ORDEM:
            n = self.contagem.get(tipo, 0)
            if n:
                partes.append("%d %s" % (n, ROTULOS[tipo][0 if n == 1 else 1]))
        return ", ".join(partes)


@dataclass
class Camada(_Resumo):
    nome: str
    cor: str                       # #rrggbb dominante
    oculta: bool                   # TODAS as feicoes escondidas no AutoCAD
    contagem: dict = field(default_factory=dict)
    fora: int = 0                  # feicoes longe do desenho
    bbox: tuple = None             # (xmin, ymin, xmax, ymax) de tudo o que se desenha
    n_ocultas: int = 0             # feicoes que o AutoCAD nao mostra (camada desligada...)
    bbox_visivel: tuple = None     # o mesmo, so do que o AutoCAD mostra

    @property
    def chave(self):
        return self.nome


@dataclass
class Unidade(_Resumo):
    """Uma cor dentro de uma camada: o que a lista mostra quando separa por cor."""
    camada: str
    cor: str                       # #rrggbb
    rotulo: str                    # "0 · ciano" (ou so o nome, se a camada tem uma cor)
    oculta: bool
    contagem: dict = field(default_factory=dict)
    bbox: tuple = None
    n_ocultas: int = 0
    bbox_visivel: tuple = None

    @property
    def nome(self):
        return self.rotulo

    @property
    def chave(self):
        return (self.camada, self.cor)


@dataclass
class Forma:
    """As formas de um tipo, de uma cor e de uma situacao (escondida ou nao)."""
    tipo: str                      # ponto, linha ou area
    cor: str                       # #rrggbb da feicao
    oculta: bool                   # o AutoCAD nao mostra
    xy: np.ndarray                 # Nx2
    inicio: np.ndarray             # onde cada forma comeca em xy (M+1 valores)
    fids: np.ndarray = None        # M ids de feicao do GDAL: de que feicao e cada vetor
    grupos: np.ndarray = None      # M ids de grupo: a que linha pertence cada vetor
    tracejado: tuple = ()          # (traco, vao, ...) em unidades do desenho; () = cheia
    ordem: np.ndarray = None       # M: a vez de cada vetor na ordem do AutoCAD (ver _chave)
    seq: np.ndarray = None         # M: o desempate (a ordem de leitura do GDAL)
    cheia: bool = False            # area pintada por dentro (o SOLID do AutoCAD)


@dataclass
class Hachura:
    """Uma hachura como o AutoCAD a mostra.

    `tipo` "solida": `xy`/`inicio` sao os aneis de todos os poligonos dela (borda, furos,
    ilhas), pintados pela regra par-impar -- a mesma do AutoCAD. "translucida": idem, para
    um padrao fino demais para desenhar linha a linha. "padrao": `xy`/`inicio` sao os
    tracos do padrao, ja recortados pela borda."""
    camada: str
    cor: str                       # #rrggbb, a do ezdxf (o GDAL erra a de algumas)
    oculta: bool
    tipo: str
    xy: np.ndarray
    inicio: np.ndarray
    handle: str = ""
    ordem: int = 0                 # a vez dela na ordem do AutoCAD
    seq: int = 0
    # "padrao": uma Familia por linha do padrao, para de longe desenhar as linhas inteiras
    familias: tuple = ()


@dataclass
class Familia:
    """Uma linha do padrao de uma hachura (a de 0 graus, a de 90...): os tracos dela sao os
    vetores `de` a `ate` da hachura; `xy`/`inicio` sao as mesmas linhas inteiras, sem os
    vaos, que o AutoCAD desenha quando o padrao fica miudo na tela."""
    de: int
    ate: int
    xy: np.ndarray
    inicio: np.ndarray
    periodo: float                 # traco + vao, em unidades do desenho (0: linha cheia)
    menor_vao: float


@dataclass
class Texto:
    """Um texto como o AutoCAD o mostra: o contorno das letras, em unidades do desenho,
    pintado por dentro (ver previa_ezdxf.py). So os que o AutoCAD mostra."""
    camada: str
    cor: str
    texto: str
    fonte: str
    xy: np.ndarray                 # os aneis das letras
    inicio: np.ndarray
    ordem: int = 0
    seq: int = 0
    # Miudo na tela, o AutoCAD pinta a caixa do texto no lugar das letras (o girado, ja um pouco
    # maior): `caixa` (5x2, anel fechado) e a celula da fonte ao longo da linha; `altura`, a
    # das maiusculas.
    girado: bool = False
    altura: float = 0.0
    caixa: np.ndarray = None
    # Os pedacos de um mesmo texto (as palavras de um MTEXT) tem a mesma `entidade`; `handle`
    # e o da feicao do GDAL que e ele; `grupo`, o Grupo que o clique escolhe (-1: nenhum).
    entidade: int = -1
    handle: str = ""
    grupo: int = -1
    # a cor em que o texto esta na lista (a do Grupo, ver cad_ezdxf.cor_do_mtext); num MTEXT
    # de duas cores, cada palavra se pinta com a sua, mas o texto e de uma cor so na lista
    cor_da_lista: str = ""


@dataclass
class Imagem:
    """Uma figura colada no desenho (a tabela de areas do desenho real), no retangulo
    `caixa`. `piramide` e a figura e as reducoes dela pela metade: de longe se desenha
    a reducao do tamanho da tela, e a figura nao vira chuvisco."""
    camada: str
    caixa: tuple                   # (xmin, ymin, xmax, ymax)
    piramide: list                 # [HxWx3 uint8, H/2 x W/2 x 3, ...]


@dataclass
class Trecho:
    """Um pedaco do desenho, na ordem em que o AutoCAD o desenha: vetores seguidos de uma
    mesma forma, uma hachura, ou textos seguidos de uma mesma camada e cor.

    O AutoCAD desenha tudo numa ordem so (a do "trazer para a frente"); o que vem depois
    cobre o que veio antes, seja linha, hachura ou texto. `Previa.trechos` e essa ordem."""
    origem: str                    # "forma", "hachura" ou "texto"
    camada: str
    cor: str
    tipo: str                      # forma: ponto/linha/area; hachura: solida/translucida/padrao;
                                   # texto: "texto" (aneis das letras)
    oculta: bool
    xy: np.ndarray
    inicio: np.ndarray
    grupos: np.ndarray = None      # forma: o grupo (a linha) de cada vetor; texto: de cada texto
    tracejado: tuple = ()
    cheia: bool = False            # forma: area pintada por dentro (SOLID)
    familias: tuple = ()           # hachura de padrao: ver Familia
    # texto: (aneis de cada texto [T], altura das maiusculas [T] (0: sem caixa, nunca vira
    # caixa), girado [T], caixas [T x 5 x 2]); ver Texto
    letreiros: tuple = ()
    cor_da_lista: str = ""         # texto: a cor deles na lista (ver Texto.cor_da_lista)


@dataclass
class Grupo:
    """Uma linha como a pessoa a enxerga: pecas ligadas pelas pontas (ou um ponto, ou uma
    area), de uma camada e de uma cor."""
    camada: str
    cor: str
    oculta: bool                   # o AutoCAD nao mostra
    fids: frozenset                # as feicoes do GDAL que a formam
    texto: str = None              # um texto do desenho (e nao uma linha): o que esta escrito

    @property
    def pecas(self):
        return len(self.fids)


class Previa:
    def __init__(self, camadas, formas, caixa_area, fora_total, distancia_fora, unidades=(),
                 grupos=None, hachuras=(), trechos=None, textos=(), imagens=()):
        self.camadas = camadas
        self.unidades = list(unidades)     # uma por camada e cor
        self.grupos = grupos or {}         # id do grupo -> Grupo
        self.hachuras = list(hachuras)     # na ordem em que o AutoCAD as desenha
        self.textos = list(textos)         # idem
        self.imagens = list(imagens)       # o AutoCAD 2007 as mostra por cima de tudo
        # o que o AutoCAD mostra, na ordem em que ele desenha (ver _plano)
        self.trechos = (_plano(formas, self.hachuras, self.textos) if trechos is None
                        else list(trechos))
        self._formas = formas              # {camada: [Forma, ...]}
        self.caixa_area = caixa_area       # para a conversao descartar o que esta longe
        self.fora_total = fora_total
        self.distancia_fora = distancia_fora

    def itens(self, por_cor=False):
        """O que a lista mostra: as camadas, ou as cores de cada camada."""
        return self.unidades if por_cor else self.camadas

    def formas(self, nome, com_ocultas=True, cor=None):
        """As formas da camada (so as de uma `cor`, se pedida). Sem `com_ocultas`, so o
        que o AutoCAD mostra."""
        return [f for f in self._formas.get(nome, ())
                if (com_ocultas or not f.oculta) and (cor is None or f.cor == cor)]

    def caixa_de_itens(self, itens, com_ocultas=True):
        """Caixa (xmin, ymin, xmax, ymax) de camadas ou de cores de camada."""
        caixas = [(i.bbox if com_ocultas else i.bbox_visivel) for i in itens]
        caixas = [c for c in caixas if c]
        if not caixas:
            return None
        return (min(c[0] for c in caixas), min(c[1] for c in caixas),
                max(c[2] for c in caixas), max(c[3] for c in caixas))

    def achar_grupo(self, x, y, raio, camada, cor=None, com_ocultas=True):
        """O id do grupo (a linha) mais perto de (x, y), a ate `raio` (unidades do desenho), entre
        as formas da camada (e so da `cor`, se pedida). None se nao houver nenhum perto.
        Num empate, o ponto ganha da linha e a linha da area, como na tela."""
        melhor, achado = float("inf"), None
        for forma in sorted(self.formas(camada, com_ocultas=com_ocultas, cor=cor),
                            key=lambda f: _PRIORIDADE_DO_CLIQUE[f.tipo]):
            if forma.grupos is None or not len(forma.grupos):
                continue
            distancia, vetor = _mais_perto(forma, x, y)
            if vetor is not None and distancia <= raio and distancia < melhor:
                melhor, achado = distancia, int(forma.grupos[vetor])
        return achado

    def achar_texto(self, x, y, folga=0.0, camadas=None):
        """O id do grupo do texto em (x, y): dentro da caixa dele (a celula da fonte ao longo
        da linha, ver Texto.caixa), com `folga` (unidades do desenho) em volta. Entre os que
        estao ali, o que o AutoCAD desenha por ultimo (o que aparece por cima). So os textos
        das `camadas` (None: todas) que a conversao conhece (com grupo). None se nao ha."""
        alvos = self._alvos_de_texto()
        if alvos is None:
            return None
        origem, u, comprimento, n, altura, camada_de, grupo_de = alvos
        d = np.array([x, y], dtype=float) - origem
        ao_longo, acima = (d * u).sum(axis=1), (d * n).sum(axis=1)
        dentro = ((ao_longo >= -folga) & (ao_longo <= comprimento + folga)
                  & (acima >= -folga) & (acima <= altura + folga) & (grupo_de >= 0))
        if camadas is not None:
            dentro &= np.array([c in camadas for c in camada_de], dtype=bool)
        quais = np.flatnonzero(dentro)
        return int(grupo_de[quais[-1]]) if len(quais) else None

    def _alvos_de_texto(self):
        """A caixa de cada texto como canto, direcao e tamanho ao longo da linha e para
        cima, para o clique (calculado uma vez)."""
        if getattr(self, "_alvos", None) is None and self.textos:
            linhas = []
            for t in self.textos:
                c = None if t.caixa is None else np.asarray(t.caixa, dtype=float)
                if c is not None and len(c) >= 4:
                    origem, ao_longo, acima = c[0], c[1] - c[0], c[3] - c[0]
                else:                                   # sem caixa: o retangulo das letras
                    v = t.xy[np.isfinite(t.xy).all(axis=1)]
                    if not len(v):
                        continue
                    origem = v.min(axis=0)
                    ao_longo = np.array([v[:, 0].max() - origem[0], 0.0])
                    acima = np.array([0.0, v[:, 1].max() - origem[1]])
                comprimento, altura = np.hypot(*ao_longo), np.hypot(*acima)
                u = ao_longo / comprimento if comprimento > 0 else np.array([1.0, 0.0])
                n = acima / altura if altura > 0 else np.array([0.0, 1.0])
                linhas.append((origem, u, comprimento, n, altura, t.camada, t.grupo))
            if linhas:
                self._alvos = tuple(np.array([l[i] for l in linhas], dtype=float)
                                    for i in range(5)) + (
                    [l[5] for l in linhas], np.array([l[6] for l in linhas], dtype=np.int64))
        return getattr(self, "_alvos", None)

    def caixa_de(self, nomes, com_ocultas=True):
        """Caixa (xmin, ymin, xmax, ymax) das camadas, sem o que esta longe."""
        por_nome = {c.nome: c for c in self.camadas}
        caixas = []
        for n in nomes:
            camada = por_nome.get(n)
            caixa = camada and (camada.bbox if com_ocultas else camada.bbox_visivel)
            if caixa:
                caixas.append(caixa)
        if not caixas:
            return None
        return (min(c[0] for c in caixas), min(c[1] for c in caixas),
                max(c[2] for c in caixas), max(c[3] for c in caixas))


_PRIORIDADE_DO_CLIQUE = {"ponto": 0, "linha": 1, "area": 2}
# Acima de tantos trechos (desenho em que as camadas se alternam o tempo todo), cada forma
# vira um desenho so, na vez da ultima peca dela: milhares de desenhos pequenos travariam o
# arrastar, e num desenho assim a ordem fina quase nao se ve.
LIMITE_TRECHOS = 3000


def _chave(handle, ordem):
    """A vez da entidade na ordem do AutoCAD: a chave do "trazer para a frente" (tabela
    SORTENTSTABLE) ou, sem ela, o proprio handle. 0 se nao houver handle."""
    h = (handle or "").upper()
    if h in ordem:
        return int(ordem[h])
    try:
        return int(h, 16)
    except ValueError:
        return 0


def _plano(formas, hachuras, textos=(), limite=None):
    """[Trecho] do que o AutoCAD mostra, na ordem em que ele desenha.

    Cada vetor das formas visiveis, cada hachura e cada texto tem a sua vez (ordem, seq). Os
    vetores seguidos de uma mesma forma viram um trecho so; os textos seguidos de uma mesma
    camada e cor, tambem. Com trechos demais, um por forma, na vez da ultima peca dela."""
    limite = LIMITE_TRECHOS if limite is None else limite
    donos, chaves, seqs, de_quem, qual = [], [], [], [], []

    def somar(dono, ordem, seq):
        d = len(donos)
        donos.append(dono)
        chaves.append(np.asarray(ordem, dtype=np.int64))
        seqs.append(np.asarray(seq, dtype=np.int64))
        de_quem.append(np.full(len(chaves[-1]), d, dtype=np.int64))
        qual.append(np.arange(len(chaves[-1]), dtype=np.int64))

    for camada, lista in formas.items():
        for f in lista:
            if not f.oculta and f.ordem is not None and len(f.ordem):
                somar((camada, f), f.ordem, f.seq)
    for h in hachuras:
        somar((None, h), [h.ordem], [h.seq])
    por_cor = collections.defaultdict(list)
    for t in textos:
        por_cor[(t.camada, t.cor, t.cor_da_lista or t.cor)].append(t)
    for (camada, _cor, _da_lista), lista in por_cor.items():
        somar((camada, lista), [t.ordem for t in lista], [t.seq for t in lista])
    if not donos:
        return []
    chaves, seqs = np.concatenate(chaves), np.concatenate(seqs)
    de_quem, qual = np.concatenate(de_quem), np.concatenate(qual)
    vez = np.lexsort((seqs, chaves))
    de_quem, qual = de_quem[vez], qual[vez]
    quebra = np.flatnonzero(de_quem[1:] != de_quem[:-1]) + 1
    comecos = np.concatenate([[0], quebra])
    fins = np.concatenate([quebra, [len(de_quem)]])
    if len(comecos) > limite:
        # um trecho por dono, na vez da ultima peca dele
        ultima = np.zeros(len(donos), dtype=np.int64)
        np.maximum.at(ultima, de_quem, np.arange(len(de_quem)))
        return [_trecho(*donos[d], None) for d in np.argsort(ultima, kind="stable")]
    return [_trecho(*donos[de_quem[a]], qual[a:b]) for a, b in zip(comecos, fins)]


def _trecho(camada, dono, vetores):
    """O Trecho de uma hachura, dos `vetores` (indices; None = todos) de uma forma, ou dos
    textos de numero `vetores` de uma lista de textos de mesma camada e cor."""
    if isinstance(dono, Hachura):
        return Trecho("hachura", dono.camada, dono.cor, dono.tipo, dono.oculta, dono.xy,
                      dono.inicio, familias=dono.familias)
    if isinstance(dono, list):
        escolhidos = dono if vetores is None else [dono[i] for i in np.sort(vetores).tolist()]
        xy, inicio = _emendar([(t.xy, t.inicio) for t in escolhidos])
        aneis = np.array([len(t.inicio) - 1 for t in escolhidos], dtype=np.int64)
        alturas = np.array([t.altura if t.caixa is not None else 0.0 for t in escolhidos],
                           dtype=float)
        girados = np.array([t.girado for t in escolhidos], dtype=bool)
        caixas = np.array([t.caixa if t.caixa is not None else np.zeros((5, 2))
                           for t in escolhidos], dtype=float).reshape(-1, 5, 2)
        return Trecho("texto", camada, escolhidos[0].cor, "texto", False, xy, inicio,
                      grupos=np.array([t.grupo for t in escolhidos], dtype=np.int64),
                      letreiros=(aneis, alturas, girados, caixas),
                      cor_da_lista=escolhidos[0].cor_da_lista or escolhidos[0].cor)
    f = dono
    if vetores is None or len(vetores) == len(f.inicio) - 1:
        xy, inicio, grupos = f.xy, f.inicio, f.grupos
    else:
        vetores = np.sort(vetores)
        a, b = int(vetores[0]), int(vetores[-1])
        if b - a + 1 == len(vetores):                 # seguidos: uma fatia, sem copiar
            xy = f.xy[f.inicio[a]:f.inicio[b + 1]]
            inicio = f.inicio[a:b + 2] - f.inicio[a]
        else:
            pedacos = [f.xy[f.inicio[i]:f.inicio[i + 1]] for i in vetores.tolist()]
            xy = np.vstack(pedacos)
            inicio = np.concatenate([[0], np.cumsum([len(p) for p in pedacos])]).astype(np.int64)
        grupos = None if f.grupos is None else f.grupos[vetores]
    return Trecho("forma", camada, f.cor, f.tipo, f.oculta, xy, inicio, grupos=grupos,
                  tracejado=f.tracejado, cheia=f.cheia)


def _emendar(partes):
    """(xy, inicio) de varias listas de aneis (xy, inicio) postas uma depois da outra."""
    if len(partes) == 1:
        return partes[0]
    xy = np.vstack([p[0] for p in partes])
    deslocamentos = np.cumsum([0] + [len(p[0]) for p in partes])
    inicio = np.concatenate([p[1][:-1] + d for p, d in zip(partes, deslocamentos)]
                            + [[len(xy)]]).astype(np.int64)
    return xy, inicio


# Duas pontas mais perto que isto (a milionesima parte do tamanho do desenho: 1 mm num desenho
# de 1 km) estao no mesmo lugar: o AutoCAD as poe no mesmo ponto, e o que sobra e arredondamento.
FRACAO_DA_PONTA = 1e-6


def _tolerancia_das_pontas(feicoes):
    """A distancia abaixo da qual duas pontas sao a mesma, pelo tamanho do desenho (a faixa
    central dos vertices, para um ponto perdido bem longe nao alargar a conta)."""
    vertices = [v for (_c, _t, vetores, _cor, _o, _f) in feicoes for v in vetores]
    if not vertices:
        return 1e-9
    xy = np.vstack(vertices)
    xy = xy[np.isfinite(xy).all(axis=1)]
    if not len(xy):
        return 1e-9
    x0, x1 = np.percentile(xy[:, 0], fora_da_area.PERCENTIS)
    y0, y1 = np.percentile(xy[:, 1], fora_da_area.PERCENTIS)
    return max(FRACAO_DA_PONTA * max(x1 - x0, y1 - y0), 1e-9)


def _mais_perto(forma, x, y):
    """(distancia, indice do vetor) da geometria da forma mais perto de (x, y)."""
    xy, inicio = forma.xy, forma.inicio
    if forma.tipo == "ponto":
        d = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
    else:
        if len(xy) < 2:
            return float("inf"), None
        a, b = xy[:-1], xy[1:]
        ab = b - a
        n2 = (ab ** 2).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.clip(((x - a[:, 0]) * ab[:, 0] + (y - a[:, 1]) * ab[:, 1])
                        / np.where(n2 == 0, 1.0, n2), 0.0, 1.0)
        d = np.hypot(a[:, 0] + t * ab[:, 0] - x, a[:, 1] + t * ab[:, 1] - y)
        d[inicio[1:-1] - 1] = np.inf              # nao liga uma forma a outra
    d = np.where(np.isfinite(d), d, np.inf)
    k = int(d.argmin())
    if not np.isfinite(d[k]):
        return float("inf"), None
    return float(d[k]), int(np.searchsorted(inicio, k, side="right")) - 1


def _ligar_pecas(feicoes, tolerancia):
    """{fid: fid da raiz}: as feicoes de linha que se encostam pelas pontas, na mesma camada e
    na mesma cor, ficam com a mesma raiz. `feicoes` sao tuplas (camada, tipo, vetores, cor,
    oculta, fid). Quem nao e linha, ou nao encosta em ninguem, e a propria raiz. Uma linha
    fechada (a ponta final no mesmo lugar da inicial) ja e uma forma completa: o canto onde ela
    comecou e acaso do desenhista, entao ela nao se junta a nenhuma outra."""
    pai = {}

    def raiz(i):
        pai.setdefault(i, i)
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    celulas = collections.defaultdict(list)       # (camada, cor, ix, iy) -> [(fid, x, y)]
    for camada, tipo, vetores, cor, _oculta, fid in feicoes:
        raiz(fid)
        if tipo != "linha":
            continue
        for v in vetores:
            if len(v) > 2 and np.hypot(*(v[0] - v[-1])) <= tolerancia:
                continue          # linha fechada: forma completa, nao se junta a outras
            for x, y in (v[0], v[-1]):
                if np.isfinite(x) and np.isfinite(y):
                    celulas[(camada, cor, int(x // tolerancia), int(y // tolerancia))
                            ].append((fid, x, y))
    for (camada, cor, ix, iy), pontas in celulas.items():
        for fid, x, y in pontas:
            for dx, dy in itertools.product((-1, 0, 1), repeat=2):
                for outro, ox, oy in celulas.get((camada, cor, ix + dx, iy + dy), ()):
                    if outro != fid and np.hypot(ox - x, oy - y) <= tolerancia:
                        pai[raiz(fid)] = raiz(outro)
    return {fid: raiz(fid) for fid in list(pai)}


class _Coleta:
    """O que uma passada junta, em um dos espacos (modelo ou papel)."""

    def __init__(self):
        self.feicoes = []            # (camada, tipo, [vetores Nx2], cor, oculta, fid)
        self.contagem = collections.defaultdict(collections.Counter)
        self.votos = collections.defaultdict(collections.Counter)         # cor, so geometria
        self.votos_todos = collections.defaultdict(collections.Counter)   # cor, tudo
        self.ocultas = collections.Counter()
        self.contagem_cor = collections.defaultdict(lambda: collections.defaultdict(
            collections.Counter))                                # camada -> cor -> tipo
        self.ocultas_cor = collections.defaultdict(collections.Counter)   # camada -> cor
        self.tracejados = {}                                     # fid -> (traco, vao, ...)
        self.ordem = {}                                          # fid -> (vez, desempate)
        self.cheias = set()                                      # fids de SOLID (area cheia)

    def somar(self, camada, tipo, cor, oculta, coords, fid=None, tracejado=(), ordem=(0, 0),
              cheia=False):
        if tracejado and tipo in ("linha", "area"):
            self.tracejados[fid] = tuple(tracejado)
        self.ordem[fid] = ordem
        if cheia and tipo == "area":
            self.cheias.add(fid)
        self.contagem[camada][tipo] += 1
        self.contagem_cor[camada][cor][tipo] += 1
        if oculta:
            self.ocultas_cor[camada][cor] += 1
        self.votos_todos[camada][cor] += 1
        if tipo in GEOMETRIA:
            self.votos[camada][cor] += 1
        if oculta:
            self.ocultas[camada] += 1
        if tipo == "ponto" or tipo == "texto":
            vetores = [np.array([(coords[0], coords[1])], dtype=float)]
        elif tipo == "linha":
            vetores = [_vetor(coords)]
        elif tipo == "area":
            vetores = [_vetor(anel) for anel in coords]
        else:                                        # hachura: so conta
            return
        self.feicoes.append((camada, tipo, vetores, cor, oculta, fid))


def _vetor(vertices):
    return np.array([(v[0], v[1]) for v in vertices], dtype=float).reshape(-1, 2)


def _ler_ezdxf(caminho_dxf):
    """O que o ezdxf le do desenho (ver cad_ezdxf.ler), ou None se ele nao puder ler: ai
    vale a cor do GDAL e a previa fica sem as hachuras, como antes."""
    try:
        return cad_ezdxf.ler(caminho_dxf, lambda *_: None, para_previa=True)
    except Exception:
        return None


def _hachuras_do_ezdxf(desenho):
    """({handle: #rrggbb}, [Hachura]) lidos pelo ezdxf, que acerta a cor das hachuras (o GDAL
    erra a de algumas) e sabe desenhar o padrao."""
    cores, hachuras = {}, []
    ordem = (desenho or {}).get("ordem") or {}
    for h in (desenho["hachuras"] if desenho else ()):
        cor = dxf_estilo.para_hex(h["cor"])
        handle = str(h.get("handle") or "").upper()
        if handle:
            cores[handle] = cor
        if h.get("tipo") == "padrao":
            pedacos = [np.array(t, dtype=float).reshape(-1, 2) for t in h.get("linhas") or ()]
        else:
            pedacos = [np.array(anel, dtype=float).reshape(-1, 2)
                       for poligono in h.get("poligonos") or () for anel in poligono]
        pedacos = [p for p in pedacos if len(p) >= 2]
        if not pedacos:
            continue
        inicio = np.concatenate([[0], np.cumsum([len(p) for p in pedacos])]).astype(np.int64)
        familias = ()
        if h.get("tipo") == "padrao" and len(pedacos) == len(h.get("linhas") or ()):
            familias = tuple(_familia(f) for f in h.get("familias") or ())
        # A vez dela: a do proprio handle ou, se veio de um bloco, a do INSERT (o AutoCAD
        # desenha o bloco inteiro na vez do INSERT; dentro dele, a hachura vai por baixo).
        topo = str(h.get("topo") or handle).upper()
        hachuras.append(Hachura(h["camada"], cor, bool(h.get("oculta")), h.get("tipo", "solida"),
                                np.vstack(pedacos), inicio, handle,
                                ordem=_chave(topo, ordem), seq=0 if handle else -1,
                                familias=familias))
    # quem o AutoCAD desenha depois fica por cima (DRAWORDER muda a ordem dos handles)
    hachuras.sort(key=lambda h: (h.ordem, h.seq))
    return cores, hachuras


def ler(caminho_dxf, registrar=None):
    """Le o DXF e devolve a Previa. Mesmas regras da conversao."""
    registrar = registrar or (lambda *_: None)
    cores_tabela = dxf_estilo.ler_cores_das_camadas(caminho_dxf)
    desenho_ez = _ler_ezdxf(caminho_dxf)
    cor_da_hachura, hachuras = _hachuras_do_ezdxf(desenho_ez)
    # a cor escrita dentro dos MTEXT, que o GDAL nao ve (a mesma regra da conversao)
    indice_mtext = cad_ezdxf.IndiceMtext(desenho_ez.get("mtexts") or ()) if desenho_ez else None
    ordem = (desenho_ez or {}).get("ordem") or {}
    # o que o AutoCAD esconde e o GDAL nao sabe (atributos de bloco congelado...)
    ocultos = (desenho_ez or {}).get("ocultos") or set()
    modelo, papel = _Coleta(), _Coleta()
    textos_gdal = []                # as feicoes de texto do espaco do modelo (ver _TextoGdal)

    with dxf_estilo.abrir_entidades(
            caminho_dxf, opcoes_extra={"DXF_CLOSED_LINE_AS_POLYGON": "FALSE"}
    ) as (origem, tem_estilo):
        # sem o estilo do OGR so da para saber a cor da camada (a mesma reserva
        # da conversao)
        cores_camada = {} if tem_estilo else cores_tabela
        for n, feicao in enumerate(origem):
            bruta = feicao.get("geometry")
            if bruta is None:
                continue
            fid = dxf_estilo.id_da_feicao(feicao, n)
            props = feicao["properties"]
            camada = props.get("Layer") or "0"
            destino = papel if props.get("PaperSpace") else modelo
            aparencia = dxf_estilo.analisar_estilo(props.get("estilo"))
            handle = (props.get("EntityHandle") or "").upper()
            oculta = aparencia["oculta"] or (handle in ocultos and not props.get("PaperSpace"))
            cor = aparencia["cor"] or cores_camada.get(camada) or (0, 0, 0)
            if oculta and cor == (0, 0, 0):
                cor = cores_tabela.get(camada) or cor
            hex_cor = dxf_estilo.para_hex(cor)
            subclasses = props.get("SubClasses") or ""
            eh_hatch = "AcDbHatch" in subclasses
            if eh_hatch:
                hex_cor = cor_da_hachura.get(handle, hex_cor)
            elif (indice_mtext is not None and "MText" in subclasses
                  and convert._tipo_base(bruta) == "Point"):
                ponto = bruta["coordinates"]
                hex_cor = indice_mtext.cor_do_texto(ponto[0], ponto[1], props.get("Text"),
                                                    hex_cor)
            # o SOLID (e o TRACE), cheio por dentro no AutoCAD: a seta do norte, as pontas
            # das cotas. O GDAL o entrega com pincel (BRUSH), como as hachuras, mas ele e
            # uma area do desenho.
            eh_cheia = "AcDbTrace" in subclasses
            eh_hachura = eh_hatch or (aparencia["hachura"] and not eh_cheia)
            # A vez dela na ordem do AutoCAD. O que vem de um bloco chega com o handle do
            # INSERT; o desempate e a ordem em que o GDAL le, a do proprio bloco.
            vez = (_chave(handle, ordem), n)

            for geom in convert._explodir(bruta):
                coords = geom.get("coordinates")
                if not coords:
                    continue
                base = convert._tipo_base(geom)
                if camada.lower() == "defpoints" and base == "Point":
                    continue
                if base == "Point":
                    tipo = "texto" if (aparencia["rotulo"] or props.get("Text")) else "ponto"
                elif base == "LineString":
                    tipo = "linha"
                elif base == "Polygon":
                    tipo = "hachura" if eh_hachura else "area"
                else:
                    continue
                destino.somar(camada, tipo, hex_cor, oculta, coords, fid,
                              aparencia["tracejado"], ordem=vez, cheia=eh_cheia)
                if tipo == "texto" and destino is modelo:
                    textos_gdal.append(_TextoGdal(fid, handle, camada, float(coords[0]),
                                                  float(coords[1]), props.get("Text") or "",
                                                  hex_cor, oculta))

    # a folha de impressao so e o desenho se nao houver mais nada
    coleta = modelo if modelo.feicoes or modelo.contagem else papel
    if coleta is not modelo:
        return _montar(coleta)
    # as hachuras, os textos e as figuras do ezdxf sao os do espaco do modelo
    imagens = _imagens_do_ezdxf(desenho_ez)
    for imagem in imagens:
        modelo.contagem[imagem.camada]["imagem"] += 1
    return _montar(coleta, hachuras, _textos_do_ezdxf(desenho_ez, ordem), imagens, textos_gdal)


def _familia(f):
    cheias = [np.array(s, dtype=float).reshape(-1, 2) for s in f.get("cheias") or ()]
    if cheias:
        xy, inicio = _emendar([(s, np.array([0, len(s)], dtype=np.int64)) for s in cheias])
    else:
        xy, inicio = np.empty((0, 2)), np.zeros(1, dtype=np.int64)
    return Familia(int(f["de"]), int(f["ate"]), xy, inicio, float(f.get("periodo") or 0.0),
                   float(f.get("menor_vao") or 0.0))


def _textos_do_ezdxf(desenho, ordem):
    """[Texto] lidos pelo ezdxf (so os que o AutoCAD mostra), na ordem dele."""
    textos = []
    for t in (desenho or {}).get("textos") or ():
        aneis = [np.asarray(a, dtype=float).reshape(-1, 2) for a in t["aneis"]]
        aneis = [a for a in aneis if len(a) >= 3]
        if not aneis:
            continue
        xy, inicio = _emendar([(a, np.array([0, len(a)], dtype=np.int64)) for a in aneis])
        caixa = t.get("caixa")
        textos.append(Texto(t["camada"], dxf_estilo.para_hex(t["cor"]), t["texto"], t["fonte"],
                            xy, inicio, ordem=_chave(t.get("topo"), ordem), seq=t["seq"],
                            girado=bool(t.get("girado")), altura=float(t.get("altura") or 0.0),
                            caixa=None if caixa is None else np.asarray(caixa, dtype=float),
                            entidade=int(t.get("entidade", -1)),
                            handle=str(t.get("handle") or t.get("topo") or "").upper()))
    textos.sort(key=lambda t: (t.ordem, t.seq))
    return textos


def _imagens_do_ezdxf(desenho):
    """[Imagem] das figuras coladas no desenho, cada uma com as reducoes dela.

    Cada reducao junta 2x2 pixels como o Windows encolhe figura (o modo "preto sobre
    branco" do StretchBlt): um E bit a bit, em que o pixel escuro ganha. E por isso que,
    de longe, o texto da tabela continua preto no AutoCAD, e nao cinza."""
    imagens = []
    for i in (desenho or {}).get("imagens") or ():
        piramide = [np.ascontiguousarray(i["imagem"], dtype=np.uint8)]
        while min(piramide[-1].shape[:2]) >= 2:
            a = piramide[-1]
            h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
            a = a[:h, :w]
            piramide.append(a[0::2, 0::2] & a[1::2, 0::2] & a[0::2, 1::2] & a[1::2, 1::2])
        imagens.append(Imagem(i["camada"], tuple(float(v) for v in i["caixa"]), piramide))
    return imagens


@dataclass
class _TextoGdal:
    """Uma feicao de texto como o GDAL (e a conversao) a le."""
    fid: int
    handle: str
    camada: str
    x: float
    y: float
    texto: str
    cor: str
    oculta: bool


def _grupos_dos_textos(textos, textos_gdal, grupos):
    """Da a cada texto desenhado o grupo da feicao do GDAL que e ele, para o clique escolher o
    texto e a conversao levar essa feicao. Os pedacos de um mesmo texto (as palavras de um
    MTEXT) ficam no mesmo grupo. Liga pelo handle; se o handle tem mais de uma feicao (um
    bloco com dois textos), ganha a de texto igual e, depois, a de ponto mais perto das
    letras. O texto sem par fica sem grupo: aparece, mas o clique passa por ele.

    Os grupos novos entram em `grupos` com o texto, a camada e a cor da feicao do GDAL (as
    que a conversao usa). Devolve quantos textos ficaram sem par."""
    por_handle = collections.defaultdict(list)
    for g in textos_gdal:
        por_handle[g.handle].append(g)
    entidades = collections.defaultdict(list)
    for i, t in enumerate(textos):
        entidades[t.entidade if t.entidade >= 0 else -1 - i].append(t)
    pares = []
    for chave, lista in entidades.items():
        candidatas = por_handle.get(lista[0].handle)
        if not candidatas:
            continue
        xy = np.vstack([t.xy for t in lista])
        xy = xy[np.isfinite(xy).all(axis=1)]
        if not len(xy):
            continue
        (xmin, ymin), (xmax, ymax) = xy.min(axis=0), xy.max(axis=0)
        letras = "".join("".join(t.texto for t in lista).split())
        for k, g in enumerate(candidatas):
            longe = np.hypot(max(xmin - g.x, 0.0, g.x - xmax), max(ymin - g.y, 0.0, g.y - ymax))
            pares.append(("".join(g.texto.split()) != letras, float(longe), chave, k))
    pares.sort(key=lambda p: (p[0], p[1]))
    proximo = max(grupos) + 1 if grupos else 0
    ligadas, usadas = set(), set()
    for _diferente, _longe, chave, k in pares:
        lista = entidades[chave]
        g = por_handle[lista[0].handle][k]
        if chave in ligadas or g.fid in usadas:
            continue
        ligadas.add(chave)
        usadas.add(g.fid)
        grupos[proximo] = Grupo(g.camada, g.cor, g.oculta, frozenset([g.fid]),
                                texto=" ".join(t.texto for t in lista))
        for t in lista:
            t.grupo = proximo
            t.cor_da_lista = g.cor
        proximo += 1
    return sum(len(lista) for chave, lista in entidades.items() if chave not in ligadas)


def _montar(coleta, hachuras=(), textos=(), imagens=(), textos_gdal=()):
    # area principal: vertices de pontos, linhas e areas de todas as camadas
    todos = [v for (_c, tipo, vetores, _cor, _o, _f) in coleta.feicoes
             if tipo in GEOMETRIA for v in vetores]
    caixa_area = fora_da_area.caixa_principal(np.vstack(todos)) if todos else None

    # (camada, tipo, cor, oculta, tracejado) -> [vetores]
    pedacos = collections.defaultdict(list)
    fids_dos_pedacos = collections.defaultdict(list)        # o mesmo -> [fid de cada vetor]
    mantidas = []                                           # as que entram no desenho
    fora = collections.Counter()
    distancia = 0.0
    if caixa_area:
        cx, cy = (caixa_area[0] + caixa_area[2]) / 2, (caixa_area[1] + caixa_area[3]) / 2
    for camada, tipo, vetores, cor, oculta, fid in coleta.feicoes:
        longe = False
        if caixa_area:
            xy = np.vstack(vetores)
            if fora_da_area.vertices_fora(xy, caixa_area).all():
                longe = True
                fora[camada] += 1
                d = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)
                d = d[np.isfinite(d)]
                if d.size:
                    distancia = max(distancia, float(d.max()))
        if not longe and tipo in GEOMETRIA:
            chave = (camada, tipo, cor, oculta, coleta.tracejados.get(fid, ()),
                     fid in coleta.cheias)
            pedacos[chave].extend(vetores)
            fids_dos_pedacos[chave].extend([fid] * len(vetores))
            mantidas.append((camada, tipo, vetores, cor, oculta, fid))

    # as linhas: pecas que se encostam pelas pontas
    raiz_de = _ligar_pecas(mantidas, _tolerancia_das_pontas(mantidas))
    grupo_de_raiz = {}
    grupo_do_fid = {}
    for fid, raiz_ in raiz_de.items():
        grupo_do_fid[fid] = grupo_de_raiz.setdefault(raiz_, len(grupo_de_raiz))
    grupos_info = {}              # id do grupo -> [camada, cor, fids, todas ocultas]
    for (camada, tipo, cor, oculta, _tracejado, _cheia), fids_ in fids_dos_pedacos.items():
        for fid in fids_:
            info = grupos_info.setdefault(grupo_do_fid[fid], [camada, cor, set(), True])
            info[2].add(fid)
            info[3] = info[3] and oculta
    grupos = {gid: Grupo(camada, cor, oculta, frozenset(fids_))
              for gid, (camada, cor, fids_, oculta) in grupos_info.items()}
    _grupos_dos_textos(textos, textos_gdal, grupos)

    formas = collections.defaultdict(list)
    bbox, bbox_visivel = {}, {}
    bbox_cor, bbox_cor_visivel = {}, {}
    def somar_caixa(camada, cor, oculta, xy):
        validos = xy[np.isfinite(xy).all(axis=1)]
        if not len(validos):
            return
        b = (float(validos[:, 0].min()), float(validos[:, 1].min()),
             float(validos[:, 0].max()), float(validos[:, 1].max()))
        _juntar(bbox, camada, b)
        _juntar(bbox_cor, (camada, cor), b)
        if not oculta:
            _juntar(bbox_visivel, camada, b)
            _juntar(bbox_cor_visivel, (camada, cor), b)

    for chave, vetores in pedacos.items():
        camada, tipo, cor, oculta, tracejado, cheia = chave
        xy = np.vstack(vetores)
        inicio = np.concatenate([[0], np.cumsum([len(v) for v in vetores])]).astype(np.int64)
        fids_forma = np.array(fids_dos_pedacos[chave], dtype=np.int64)
        vezes = [coleta.ordem.get(f, (0, 0)) for f in fids_forma.tolist()]
        formas[camada].append(Forma(
            tipo, cor, oculta, xy, inicio, fids=fids_forma,
            grupos=np.array([grupo_do_fid[f] for f in fids_forma.tolist()], dtype=np.int64),
            tracejado=tracejado,
            ordem=np.array([v[0] for v in vezes], dtype=np.int64),
            seq=np.array([v[1] for v in vezes], dtype=np.int64), cheia=cheia))
        somar_caixa(camada, cor, oculta, xy)
    # a hachura tambem conta para o "ver tudo" (uma camada pode ter so hachuras), menos a
    # que esta longe do desenho, pela mesma regra das outras feicoes
    for h in hachuras:
        if caixa_area and fora_da_area.vertices_fora(h.xy, caixa_area).all():
            continue
        somar_caixa(h.camada, h.cor, h.oculta, h.xy)
    # os textos e as figuras, idem (o carimbo e a tabela ficam ao lado do desenho)
    for t in textos:
        if caixa_area and fora_da_area.vertices_fora(t.xy, caixa_area).all():
            continue
        somar_caixa(t.camada, t.cor, False, t.xy)
    for i in imagens:
        cantos = np.array([(i.caixa[0], i.caixa[1]), (i.caixa[2], i.caixa[3])])
        if caixa_area and fora_da_area.vertices_fora(cantos, caixa_area).all():
            continue
        _juntar(bbox, i.camada, i.caixa)
        _juntar(bbox_visivel, i.camada, i.caixa)

    camadas = []
    for nome, contagem in coleta.contagem.items():
        votos = coleta.votos.get(nome) or coleta.votos_todos[nome]
        total = sum(contagem.values())
        camadas.append(Camada(
            nome=nome, cor=votos.most_common(1)[0][0],
            oculta=coleta.ocultas[nome] == total, contagem=dict(contagem),
            fora=fora[nome], bbox=bbox.get(nome), n_ocultas=coleta.ocultas[nome],
            bbox_visivel=bbox_visivel.get(nome)))
    camadas.sort(key=lambda c: (not c.tem_desenho, c.nome.casefold()))

    unidades = []
    for camada in camadas:
        por_cor = coleta.contagem_cor[camada.nome]
        # a cor com mais feicoes primeiro
        ordem = sorted(por_cor, key=lambda cor: (-sum(por_cor[cor].values()), cor))
        for cor in ordem:
            contagem = dict(por_cor[cor])
            rotulo = (camada.nome if len(ordem) == 1
                      else "%s · %s" % (camada.nome, dxf_estilo.nome_da_cor(cor)))
            n_ocultas = coleta.ocultas_cor[camada.nome][cor]
            unidades.append(Unidade(
                camada=camada.nome, cor=cor, rotulo=rotulo,
                oculta=n_ocultas == sum(contagem.values()), contagem=contagem,
                bbox=bbox_cor.get((camada.nome, cor)), n_ocultas=n_ocultas,
                bbox_visivel=bbox_cor_visivel.get((camada.nome, cor))))
    return Previa(camadas, dict(formas), caixa_area, sum(fora.values()), distancia, unidades,
                  grupos=grupos, hachuras=hachuras, textos=textos, imagens=imagens)


def _juntar(caixas, camada, b):
    antiga = caixas.get(camada)
    caixas[camada] = b if antiga is None else (
        min(antiga[0], b[0]), min(antiga[1], b[1]),
        max(antiga[2], b[2]), max(antiga[3], b[3]))
