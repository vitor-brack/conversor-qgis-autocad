# -*- coding: utf-8 -*-
"""
Hachuras e texto formatado, lidos com o ezdxf.

O GDAL, que le todo o resto do desenho, falha em tres pontos que num mapa
geologico importam muito:

  HACHURA COM PADRAO   o GDAL entrega so o contorno, e com a cor errada
                       (preta, mesmo quando a hachura tem cor propria). O
                       padrao -- as cruzes, os tracos, o cascalho -- se perde.
  BORDA CURVA          se a borda da hachura tem um trecho em spline (o perfil
                       de um terreno, por exemplo), o GDAL nao fecha o poligono
                       e a hachura some.
  MTEXT FORMATADO      cor, fonte e negrito trocados no meio do texto sao
                       descartados. O logo "Geosana", com "Geo" azul e "sana"
                       verde, chegava todo preto.

O ezdxf resolve os tres: sabe gerar as linhas reais de um padrao de hachura
(com os tracos e os deslocamentos de cada familia de linhas, exatamente como o
AutoCAD) e sabe ler a formatacao de dentro do MTEXT. De quebra, conhece as
fontes instaladas: traduz o nome de fonte gravado no MTEXT para o que o QGIS
entende e mede as palavras na fonte de verdade.

Desenhos grandes nao pesam: antes de o ezdxf ler, o arquivo e copiado so com
hachuras, MTEXT e blocos. As curvas de nivel, que costumam ser o grosso do
arquivo, ficam de fora da copia.

Se o ezdxf nao estiver disponivel ou nao conseguir ler o arquivo, `ler`
devolve None e o conversor segue como antes, so com o GDAL.
"""

import math
import os
import re
import tempfile

from . import dwg, dxf_estilo, textos_cad

try:
    import ezdxf
    from ezdxf import path as ezpath
    from ezdxf.math import Vec2, Vec3
    from ezdxf.render import hatching
    from ezdxf.tools.text import MTextContext, MTextParser, TokenType
    DISPONIVEL = True
    ERRO_IMPORTACAO = None
except Exception as _erro:   # a conversao continua sem este modulo
    DISPONIVEL = False
    ERRO_IMPORTACAO = "%s: %s" % (type(_erro).__name__, _erro)

# Acima disto por hachura, o padrao e fino demais para valer a pena desenhar
# linha a linha (o proprio AutoCAD recusa hachuras densas assim); a hachura
# sai como tinta translucida, como antes.
LIMITE_SEGMENTOS = 250000

# o que a copia filtrada leva da secao ENTITIES (OLE2FRAME: as figuras coladas, que o GDAL
# nao le e a conversao leva como imagem)
_ENTIDADES = {"HATCH", "MTEXT", "INSERT", "OLE2FRAME"}
# e o que ela leva a mais para a previa: os textos e as cotas (o texto delas)
_DA_PREVIA = {"TEXT", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION"}
_UNICODE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def ler(caminho_dxf, registrar=print, para_previa=False):
    """Devolve {'hachuras': [...], 'mtexts': [...], 'falhas': set(), 'ordem': {...},
    'figuras': [...]} ou None. `figuras` sao as figuras coladas no desenho
    (previa_ezdxf.figuras_coladas), que a conversao leva como imagem.

    `para_previa` le tambem o que so a previa desenha: os textos como o AutoCAD os mostra
    ('textos', 'textos_visiveis') e as imagens coladas no desenho ('imagens'), ver
    previa_ezdxf.py; e a ordem de desenho vem mesmo sem hachura nem MTEXT."""
    if not DISPONIVEL:
        registrar("Aviso: texturas de hachura e texto formatado indisponíveis "
                  "(%s); eles saem como antes." % ERRO_IMPORTACAO)
        return None
    codec, _ = dxf_estilo.detectar_codificacao(caminho_dxf)
    copia = None
    try:
        copia, tipos = _filtrar(caminho_dxf, codec,
                                _ENTIDADES | _DA_PREVIA if para_previa else _ENTIDADES)
        if (not para_previa and not (tipos & {"HATCH", "MTEXT", "OLE2FRAME"})
                and not _blocos_tem(copia)):
            return {"hachuras": [], "mtexts": [], "falhas": set(), "ordem": {}, "figuras": []}
        doc = ezdxf.readfile(copia, encoding="utf-8")
        desenho = _extrair(doc)
        # A ordem em que o AutoCAD desenha (o "trazer para a frente"), da tabela
        # SORTENTSTABLE, que a copia mantem: {handle: chave}, so do que mudou de lugar --
        # para as outras, a chave e o proprio handle (ver dxf_estilo.ordem_de_desenho).
        try:
            desenho["ordem"] = {h.upper(): int(k, 16)
                                for h, k in doc.modelspace().get_redraw_order()}
        except Exception:
            desenho["ordem"] = {}
        # Hachura em camada desligada ou congelada o AutoCAD nao mostra; o
        # GDAL marca as entidades que ele le, mas as hachuras vem daqui.
        ocultas = {c.dxf.name for c in doc.layers if c.is_off() or c.is_frozen()}
        for h in desenho["hachuras"]:
            h["oculta"] = h["camada"] in ocultas
        from . import previa_ezdxf
        if para_previa:
            desenho.update(previa_ezdxf.ler(doc, _Cores(doc)))
            desenho["figuras"] = desenho["imagens"]
        else:
            desenho["figuras"] = previa_ezdxf.figuras_coladas(doc)
        return desenho
    except Exception as erro:
        registrar("Aviso: não consegui ler hachuras e textos formatados (%s); "
                  "eles saem como antes." % erro)
        return None
    finally:
        if copia and os.path.exists(copia):
            try:
                os.remove(copia)
            except OSError:
                pass


def _blocos_tem(copia):
    """Blocos podem ter hachuras mesmo sem nenhuma hachura solta no desenho."""
    with open(copia, encoding="utf-8") as fp:
        texto = fp.read()
    i = texto.find("\nBLOCKS\n")
    j = texto.find("\nENDSEC\n", i)
    trecho = texto[i:j] if i != -1 else ""
    return "\nHATCH\n" in trecho or "\nMTEXT\n" in trecho


def _filtrar(caminho_dxf, codec, entidades=_ENTIDADES):
    """Copia o DXF em UTF-8 levando da secao ENTITIES so as `entidades`.

    Os atributos (ATTRIB) e o SEQEND que fecham um INSERT vao junto com ele;
    VERTEX e SEQEND de polilinhas antigas, nao -- a polilinha foi descartada,
    e um SEQEND solto quebraria a leitura.
    """
    descritor, destino = tempfile.mkstemp(suffix=".dxf", prefix="conversor_ez_")
    os.close(descritor)
    dwg.anotar_temporario(destino)             # se o programa fechar no meio da leitura
    try:
        return destino, _copiar_filtrando(caminho_dxf, codec, entidades, destino)
    except BaseException:
        # a copia (um pedaco do desenho do cliente) nao pode ficar no TEMP
        try:
            os.remove(destino)
        except OSError:
            pass
        raise


def _copiar_filtrando(caminho_dxf, codec, entidades, destino):
    """O trabalho de _filtrar: grava a copia em `destino` e devolve os tipos levados."""
    tipos = set()
    secao = None
    proximo_e_secao = False
    manter = True
    ultimo_principal = None
    with open(destino, "w", encoding="utf-8", newline="\n") as saida:
        for codigo, valor in dxf_estilo._pares(caminho_dxf, codec):
            if codigo == 0:
                if valor == "SECTION":
                    proximo_e_secao, manter = True, True
                elif valor == "ENDSEC":
                    secao, manter = None, True
                elif secao == "ENTITIES":
                    if valor in ("ATTRIB", "SEQEND", "VERTEX"):
                        manter = ultimo_principal == "INSERT" and valor != "VERTEX"
                    else:
                        ultimo_principal = valor
                        manter = valor in entidades
                        if manter:
                            tipos.add(valor)
                else:
                    manter = True
            elif proximo_e_secao and codigo == 2:
                secao, proximo_e_secao = valor, False
            if manter:
                saida.write("%3d\n%s\n" % (codigo, valor))
    return tipos


# ---------------------------------------------------------------------------
# Cor e camada efetivas, com as regras do AutoCAD
# ---------------------------------------------------------------------------

class _Cores:
    def __init__(self, doc):
        self.camadas = {}
        for camada in doc.layers:
            self.camadas[camada.dxf.name.upper()] = camada

    def da_camada(self, nome):
        camada = self.camadas.get((nome or "0").upper())
        if camada is None:
            return (0, 0, 0)
        if camada.dxf.hasattr("true_color"):
            return tuple(camada.rgb)
        return dxf_estilo.aci_para_rgb(abs(camada.dxf.get("color", 7)))

    def da_entidade(self, entidade, camada, cor_do_bloco):
        """Cor verdadeira > indice proprio > ByBlock (cor do INSERT) > ByLayer."""
        if entidade.dxf.hasattr("true_color"):
            return tuple(entidade.rgb)
        indice = entidade.dxf.get("color", 256)
        if indice == 0:
            return cor_do_bloco or (0, 0, 0)
        if indice == 256:
            return self.da_camada(camada)
        return dxf_estilo.aci_para_rgb(indice)


def _camada_efetiva(entidade, camada_do_bloco):
    """Dentro de um bloco, o que esta na camada 0 assume a camada do INSERT."""
    propria = entidade.dxf.get("layer", "0")
    if camada_do_bloco is not None and propria == "0":
        return camada_do_bloco
    return propria


def _blocos_uteis(doc):
    """Nomes dos blocos que contem, direta ou indiretamente, hachura ou MTEXT.
    So esses precisam ser expandidos."""
    diretos = {}
    for bloco in doc.blocks:
        tipos = set()
        referencias = set()
        for e in bloco:
            t = e.dxftype()
            tipos.add(t)
            if t == "INSERT":
                referencias.add(e.dxf.name)
        diretos[bloco.name] = (bool(tipos & {"HATCH", "MTEXT"}), referencias)
    uteis = set()
    mudou = True
    while mudou:
        mudou = False
        for nome, (proprio, refs) in diretos.items():
            if nome not in uteis and (proprio or refs & uteis):
                uteis.add(nome)
                mudou = True
    return uteis


def _percorrer(entidades, cores, uteis, camada_do_bloco=None, cor_do_bloco=None,
               profundidade=0, topo=None):
    """(tipo, entidade, camada, cor, dentro de bloco, topo) das hachuras e MTEXT. `topo` e o
    handle da entidade solta no desenho de onde ela veio (o INSERT, se veio de um bloco)."""
    for entidade in entidades:
        tipo = entidade.dxftype()
        dono = topo or (entidade.dxf.get("handle") or "").upper()
        if tipo == "INSERT":
            if profundidade >= 16 or entidade.dxf.get("name") not in uteis:
                continue
            camada = _camada_efetiva(entidade, camada_do_bloco)
            cor = cores.da_entidade(entidade, camada, cor_do_bloco)
            try:
                copias = (list(entidade.multi_insert()) if entidade.mcount > 1
                          else [entidade])
                for copia in copias:
                    yield from _percorrer(copia.virtual_entities(), cores, uteis,
                                          camada, cor, profundidade + 1, dono)
            except Exception:
                continue
        elif tipo in ("HATCH", "MTEXT"):
            camada = _camada_efetiva(entidade, camada_do_bloco)
            dentro_de_bloco = camada_do_bloco is not None
            yield (tipo, entidade, camada, cores.da_entidade(entidade, camada, cor_do_bloco),
                   dentro_de_bloco, dono)


def _extrair(doc):
    cores = _Cores(doc)
    uteis = _blocos_uteis(doc)
    hachuras, mtexts, falhas = [], [], set()
    for tipo, entidade, camada, cor, em_bloco, topo in _percorrer(doc.modelspace(), cores,
                                                                   uteis):
        try:
            if tipo == "HATCH":
                item = _hachura(entidade, camada, cor)
                if item:
                    item["topo"] = topo
                    hachuras.append(item)
            else:
                mtexts.append(_mtext(entidade, camada, cor))
        except Exception:
            if not em_bloco and entidade.dxf.get("handle"):
                falhas.add(entidade.dxf.handle.upper())
    return {"hachuras": hachuras, "mtexts": mtexts, "falhas": falhas}


# ---------------------------------------------------------------------------
# Hachuras
# ---------------------------------------------------------------------------

def _hachura(h, camada, cor):
    padrao = (h.dxf.get("pattern_name") or "").upper()
    # copias vindas de blocos nao tem handle proprio
    base = {"camada": camada, "cor": cor, "padrao": padrao or "SOLID",
            "handle": (h.dxf.get("handle") or "").upper()}
    gradiente = getattr(h, "gradient", None)
    # O AutoCAD grava dados de degrade (codigo 450) ate em hachura solida comum: tipo 0 e
    # "nao e degrade", com um azul padrao como primeira cor. So o tipo 1 e degrade de verdade.
    if gradiente is not None and getattr(gradiente, "kind", 1) == 0:
        gradiente = None
    if h.dxf.get("solid_fill", 0) or gradiente is not None:
        if gradiente is not None and getattr(gradiente, "color1", None):
            base["cor"] = tuple(gradiente.color1)
        base.update(tipo="solida", padrao="SOLID", poligonos=_poligonos(h))
        return base if base["poligonos"] else None
    familias = []
    try:
        linhas = _linhas_do_padrao(h, familias)
    except (_Densa, hatching.HatchingError):
        linhas = None       # fino demais para desenhar linha a linha
    if not linhas:
        # Sem linhas para desenhar -- padrao denso demais, ou hachura sem a
        # definicao do padrao gravada. Nunca deixar a hachura sumir: sai como
        # a tinta translucida de antes.
        base.update(tipo="translucida", poligonos=_poligonos(h))
        return base if base["poligonos"] else None
    base.update(tipo="padrao", linhas=linhas, familias=familias)
    return base


class _Densa(Exception):
    pass


def _linhas_do_padrao(h, familias=None):
    """As linhas do padrao, recortadas pela borda, em coordenadas do desenho.

    Com a lista `familias`, junta nela, para cada linha do padrao (a 0 graus, a 90...), um
    {'de', 'ate': os tracos dela em `linhas`; 'cheias': as mesmas linhas inteiras, sem os
    vaos; 'periodo': traco + vao; 'menor_vao'}. De longe, quando o padrao fica menor que
    uns poucos pixels, o AutoCAD desenha as linhas inteiras (ver previa_raster).

    Faz o que hatching.hatch_entity do ezdxf faz, com tres erros corrigidos:

    - o recorte (ver _dentro), que deixava trechos de linha vertical do padrao
      fora da borda -- foram os tracos soltos no meio da escavacao do perfil;
    - o sorteio: o ezdxf desloca o padrao por um valor aleatorio para fugir
      de linha passando por vertice, e cada conversao errava num lugar
      diferente. Aqui o padrao fica exatamente onde o AutoCAD o poe;
    - bloco espelhado (sistema de coordenadas invertido): a original devolve
      cada linha duas vezes -- uma no lugar certo e outra espelhada, fora do
      desenho -- porque falta um `else`.

    Tracos de comprimento zero (os pontos de padroes como DOTS) viram tracos
    minimos, senao o QGIS nao desenha nada.
    """
    if h.pattern is None or not h.pattern.lines:
        return []
    ocs = h.ocs()
    elevacao = h.dxf.elevation.z
    aneis = _bordas(h)
    def no_desenho(ponto):
        if ocs.transform:
            ponto = ocs.to_wcs((ponto.x, ponto.y, elevacao))
        return (ponto.x, ponto.y)

    saida = []
    for base in hatching.pattern_baselines(h):
        de, cheias = len(saida), []
        for distancia, comeco, termino in _dentro(base, aneis):
            cheias.append([no_desenho(comeco), no_desenho(termino)])
            for inicio, fim in base.pattern_renderer(distancia).render(comeco, termino):
                a, b = no_desenho(inicio), no_desenho(fim)
                if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
                    b = (a[0] + 1e-3, a[1])
                saida.append([a, b])
                if len(saida) > LIMITE_SEGMENTOS:
                    raise _Densa()
        if familias is not None:
            medidas = [abs(float(v)) for v in base.line_pattern]
            vaos = [abs(float(v)) for v in base.line_pattern if v < 0]
            familias.append({"de": de, "ate": len(saida), "cheias": cheias,
                             "periodo": sum(medidas), "menor_vao": min(vaos) if vaos else 0.0})
    return saida


def _bordas(h):
    """As bordas da hachura como aneis de vertices, no sistema da hachura.

    Uma borda de arestas (linhas, arcos, splines) devia vir encadeada, cada
    aresta comecando onde a anterior termina. Nem sempre vem: o perfil futuro
    do mapa real tem a curva do terreno DUAS vezes, uma em cada sentido, e as
    arestas fora de ordem -- resto de edicoes do contorno associativo no
    AutoCAD. O ezdxf liga cada aresta a seguinte NA ORDEM GRAVADA e fecha os
    vaos com retas; essas retas atravessavam o perfil inteiro e criavam uma
    fatia fina, ao longo do topo, onde apareciam pedacinhos das cruzes. Aqui
    a proxima aresta e a que tem uma ponta mais perto do fim da cadeia (do
    jeito que vier, invertida se preciso). A curva repetida se anula na
    contagem de dentro/fora, e so o vao que existe de fato e fechado.
    """
    from ezdxf.entities.boundary_paths import PolylinePath
    from ezdxf.lldxf.const import BOUNDARY_PATH_TEXTBOX
    from ezdxf.path import from_hatch_edge_path, from_hatch_polyline_path

    bordas = []                   # cada borda: lista de pecas (caminhos)
    for borda in h.paths.rendering_paths(h.dxf.hatch_style):
        if borda.path_type_flags & BOUNDARY_PATH_TEXTBOX:   # nao e borda
            continue
        if isinstance(borda, PolylinePath):
            pecas = [from_hatch_polyline_path(borda)]
        else:
            pecas = [_aresta(from_hatch_edge_path([aresta])) for aresta in borda.edges]
        pecas = [p for p in pecas if p is not None and len(p)]
        if pecas:
            bordas.append(pecas)
    vertices = [v for pecas in bordas for p in pecas for v in p.control_vertices()]
    if not vertices:
        return []
    xs = [v.x for v in vertices]
    ys = [v.y for v in vertices]
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    # 1/100.000 do tamanho da hachura: o fim de um traco do padrao fica a
    # menos disso da curva verdadeira
    tolerancia = max(diagonal * 1e-5, 1e-9)
    junta = max(diagonal * 1e-9, 1e-12)        # pontas que se tocam
    aneis = []
    for pecas in bordas:
        polilinhas = []
        for peca in pecas:
            # Toda peca e achatada no mesmo sentido (da ponta "menor" para a
            # "maior"). Uma curva que aparece duas vezes, uma em cada sentido,
            # da entao exatamente os mesmos pontos, e as duas se anulam na
            # contagem de dentro/fora; achatada em sentidos opostos, sobrava
            # uma fresta de um milesimo com pedacinhos do padrao.
            inverter = (peca.end.x, peca.end.y) < (peca.start.x, peca.start.y)
            linha = []
            for v in (peca.reversed() if inverter else peca).flattening(tolerancia):
                v = Vec2(v)
                if not linha or (v - linha[-1]).magnitude > junta:
                    linha.append(v)
            if inverter:
                linha.reverse()
            # borda de polilinha ja vem fechada: o ultimo vertice repete o primeiro
            if len(linha) > 2 and (linha[-1] - linha[0]).magnitude <= junta:
                linha.pop()
            if len(linha) >= 2:
                polilinhas.append(linha)
        polilinhas = _sem_curvas_repetidas(polilinhas, 4 * tolerancia + junta)
        for anel in _encadear(polilinhas, junta):
            if len(anel) > 1 and (anel[0] - anel[-1]).magnitude <= junta:
                anel.pop()
            if len(anel) >= 3:
                aneis.append(anel)
    return aneis


def _sem_curvas_repetidas(polilinhas, perto):
    """Tira as curvas que aparecem duas vezes na mesma borda (em qualquer
    sentido), as duas copias.

    Na contagem de dentro/fora uma copia anula a outra -- e o que o AutoCAD
    faz com a curva do terreno repetida no perfil futuro. Mas cada copia e
    achatada por conta propria, em pontos um pouco diferentes, e a fresta de
    um milesimo entre elas ficava com pedacinhos do padrao. Linha reta
    repetida nao precisa disso: as duas copias coincidem exatamente.
    """
    curvas = [i for i, p in enumerate(polilinhas) if len(p) > 2]
    fora = set()
    for n, i in enumerate(curvas):
        if i in fora:
            continue
        for j in curvas[n + 1:]:
            if j not in fora and _mesma_curva(polilinhas[i], polilinhas[j], perto):
                fora.update((i, j))
                break
    return [p for i, p in enumerate(polilinhas) if i not in fora]


def _mesma_curva(a, b, perto):
    """As duas polilinhas sao a mesma curva, em qualquer sentido?"""
    if (a[0] - b[0]).magnitude <= perto and (a[-1] - b[-1]).magnitude <= perto:
        pass
    elif (a[0] - b[-1]).magnitude <= perto and (a[-1] - b[0]).magnitude <= perto:
        b = b[::-1]
    else:
        return False

    def distancia(v, linha):
        menor = None
        for p, q in zip(linha, linha[1:]):
            d = q - p
            t = 0.0 if d.is_null else max(0.0, min(1.0, (v - p).dot(d) / d.dot(d)))
            m = (v - (p + d * t)).magnitude
            if menor is None or m < menor:
                menor = m
        return menor

    passo_a = max(1, len(a) // 24)
    passo_b = max(1, len(b) // 24)
    return (all(distancia(v, b) <= perto for v in a[::passo_a])
            and all(distancia(v, a) <= perto for v in b[::passo_b]))


def _aresta(caminho):
    """O caminho de UMA aresta de borda, aberto.

    O ezdxf fecha todo caminho de borda, ate o de uma aresta so: uma linha
    vira ida e volta, e a volta anularia a ida na contagem de dentro/fora.
    Sai o retorno (o LineTo final de volta ao inicio); aresta que ja e
    fechada sozinha, como um circulo inteiro, nao tem retorno e fica igual.
    """
    from ezdxf.path import Path
    from ezdxf.path.commands import Curve3To, Curve4To, LineTo

    comandos = list(caminho.commands())
    if (len(comandos) > 1 and isinstance(comandos[-1], LineTo)
            and comandos[-1].end.isclose(caminho.start)):
        comandos.pop()
    aberto = Path(caminho.start)
    for c in comandos:
        if isinstance(c, Curve4To):
            aberto.curve4_to(c.end, c.ctrl1, c.ctrl2)
        elif isinstance(c, Curve3To):
            aberto.curve3_to(c.end, c.ctrl)
        else:
            aberto.line_to(c.end)
    return aberto


def _encadear(pecas, junta):
    """Junta as pecas (polilinhas) de uma borda em aneis, pela ponta mais
    perto. No caso comum -- cada peca comeca onde a anterior termina -- e
    so seguir a ordem; a busca so roda quando a ordem gravada nao encaixa.
    Empate fica com a peca gravada antes."""
    restantes = list(pecas)
    aneis = []
    while restantes:
        cadeia = list(restantes.pop(0))
        while restantes:
            fim = cadeia[-1]
            seguinte = restantes[0]
            if (seguinte[0] - fim).magnitude <= junta:
                escolhida, inverter, distancia = 0, False, 0.0
            elif (seguinte[-1] - fim).magnitude <= junta:
                escolhida, inverter, distancia = 0, True, 0.0
            else:
                escolhida, inverter, distancia = None, False, None
                for i, peca in enumerate(restantes):
                    for inv, ponta in ((False, peca[0]), (True, peca[-1])):
                        d = (ponta - fim).magnitude
                        if distancia is None or d < distancia - junta:
                            escolhida, inverter, distancia = i, inv, d
                # cadeia ja fechada e a proxima peca longe: e outro anel
                if (cadeia[0] - fim).magnitude <= junta and distancia > junta:
                    break
            peca = restantes.pop(escolhida)
            if inverter:
                peca = peca[::-1]
            cadeia.extend(peca[1:] if distancia <= junta else peca)
        aneis.append(cadeia)
    return aneis


def _dentro(base, aneis):
    """Os trechos de cada linha do padrao que ficam dentro da hachura:
    (distancia da linha, inicio, fim).

    Cada linha do padrao entra e sai da hachura onde cruza uma borda. O ezdxf
    ordena esses cruzamentos comparando x e, so no empate, y, com os valores
    arredondados a 10 casas. Numa linha vertical todos tem o mesmo x a menos
    de erros de arredondamento na 13a casa -- e de vez em quando esse
    residuo, e nao o y, decidia a ordem. Os pontos saiam fora de ordem, um
    trecho de fora virava de dentro, e apareciam tracos verticais soltos no
    meio da escavacao do perfil. Aqui a ordem e a posicao AO LONGO da linha.

    Linha passando exatamente por um vertice da borda (frequente em desenho
    alinhado a grade) segue a regra do "meio aberto": o vertice conta como
    acima da linha. Assim um vertice que cruza a linha conta um cruzamento, e
    um que so encosta conta zero ou dois -- sem precisar sortear nada. As
    bordas de dentro (buracos, ilhas) entram na mesma contagem, alternando
    cheio e vazio como o AutoCAD.
    """
    passo = base.normal_distance
    direcao = base.direction
    cortes = {}             # numero da linha -> [(posicao ao longo dela, ponto)]
    total = 0
    for anel in aneis:
        # em que "numero de linha" fica cada vertice; calculado uma vez so por
        # vertice, para as duas arestas que o tocam concordarem
        f = [base.signed_distance(v) / passo for v in anel]
        total += math.floor(max(f)) - math.floor(min(f))
        if total > LIMITE_SEGMENTOS:
            raise _Densa()
        n = len(anel)
        for i in range(n):
            fa, fb = f[i], f[(i + 1) % n]
            if fa == fb:
                continue          # aresta paralela as linhas: nao cruza nenhuma
            a, b = anel[i], anel[(i + 1) % n]
            for k in range(math.floor(min(fa, fb)) + 1, math.floor(max(fa, fb)) + 1):
                p = a + (b - a) * ((k - fa) / (fb - fa))
                cortes.setdefault(k, []).append((p.dot(direcao), p))
    for k in sorted(cortes):
        pontos = sorted(cortes[k], key=lambda c: c[0])
        for i in range(0, len(pontos) - 1, 2):
            if pontos[i + 1][0] - pontos[i][0] > 1e-12:
                yield k * passo, pontos[i][1], pontos[i + 1][1]


def _poligonos(h):
    """Poligonos (com buracos e ilhas) a partir das bordas da hachura.

    O AutoCAD preenche alternando: a borda de fora e cheia, a de dentro e
    buraco, uma ilha dentro do buraco volta a ser cheia. O estilo 1 ("outer")
    ignora as ilhas e o estilo 2 ("ignore") ignora ate os buracos.
    """
    caminhos = [c for c in ezpath.from_hatch(h) if len(c)]
    if not caminhos:
        return []
    xs, ys = [], []
    for c in caminhos:
        for v in c.control_vertices():
            xs.append(v.x)
            ys.append(v.y)
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs else 1.0
    tolerancia = max(diagonal * 1e-4, 1e-4)
    estilo = h.dxf.get("hatch_style", 0)

    def anel(caminho):
        pontos = [(v.x, v.y) for v in caminho.flattening(tolerancia)]
        if len(pontos) >= 3 and pontos[0] != pontos[-1]:
            pontos.append(pontos[0])
        return pontos if len(pontos) >= 4 else None

    saida = []

    def visitar(poligono):
        externo = anel(poligono[0])
        buracos = []
        for filho in poligono[1:]:
            if isinstance(filho, list):
                buracos.append(filho[0])
                if estilo == 0:
                    for ilha in filho[1:]:
                        visitar(ilha if isinstance(ilha, list) else [ilha])
            else:
                buracos.append(filho)
        if externo is None:
            return
        aneis = [externo]
        if estilo != 2:
            aneis.extend(a for a in (anel(b) for b in buracos) if a)
        saida.append(aneis)

    for poligono in ezpath.make_polygon_structure(caminhos):
        visitar(poligono)
    return saida


# ---------------------------------------------------------------------------
# MTEXT
# ---------------------------------------------------------------------------

def _mtext(m, camada, cor):
    altura = float(m.dxf.get("char_height", 2.5) or 2.5)
    conteudo = _UNICODE.sub(lambda g: chr(int(g.group(1), 16)), m.text)
    ponto = m.dxf.insert
    return {
        "ponto": (ponto.x, ponto.y),
        "texto": _UNICODE.sub(lambda g: chr(int(g.group(1), 16)),
                              m.plain_text(split=False)),
        "altura": altura,
        "largura": float(m.dxf.get("width", 0.0) or 0.0),
        "espacamento": float(m.dxf.get("line_spacing_factor", 1.0) or 1.0),
        "camada": camada,
        "cor": cor,
        "trechos": _trechos(conteudo, altura),
    }


_FONTE_PADRAO = MTextContext().font_face if DISPONIVEL else None


def _trechos(conteudo, altura):
    """O conteudo do MTEXT em trechos para textos_cad.montar_texto."""
    ctx = MTextContext()
    ctx.aci = 256            # sem codigo de cor: fica com a cor da entidade
    ctx.cap_height = altura
    saida = []
    for token in MTextParser(conteudo, ctx):
        t = token.type
        if t in (TokenType.NEW_PARAGRAPH, TokenType.NEW_COLUMN, TokenType.WRAP_AT_DIMLINE):
            saida.append(("quebra",))
            continue
        estilo = _estilo(token.ctx, altura)
        if t == TokenType.WORD:
            saida.append(("palavra", token.data, estilo))
        elif t == TokenType.SPACE:
            saida.append(("espaco", estilo))
        elif t == TokenType.NBSP:
            saida.append(("palavra", " ", estilo))
        elif t == TokenType.TABULATOR:
            saida.append(("palavra", "    ", estilo))
        elif t == TokenType.STACK:
            cima, baixo = token.data[0], token.data[1]
            saida.append(("palavra", "%s/%s" % (cima, baixo), estilo))
    return saida


def _estilo(ctx, altura):
    """Estilo de um trecho, so com o que o MTEXT muda de fato.

    O contexto do ezdxf ja nasce com uma fonte ('sans-serif'); tratada como
    fonte escolhida, ela transformava todo MTEXT em "formatado" e o rotulo
    inteiro virava HTML com uma fonte generica. So conta a fonte que um
    codigo de fonte (barra-f) do proprio texto escolheu.
    """
    estilo = {}
    if ctx.rgb is not None:
        estilo["cor"] = dxf_estilo.para_hex(tuple(ctx.rgb))
    elif ctx.aci not in (0, 256):
        estilo["cor"] = dxf_estilo.para_hex(dxf_estilo.aci_para_rgb(ctx.aci))
    face = ctx.font_face
    if face is not None and face.family and face != _FONTE_PADRAO:
        familia, negrito, italico = resolver_fonte(
            face.family, (face.weight or 400) >= 600, "italic" in (face.style or "").lower())
        if familia:
            estilo["fonte"] = familia
        if negrito:
            estilo["negrito"] = True
        if italico:
            estilo["italico"] = True
    if ctx.underline:
        estilo["sublinhado"] = True
    if ctx.strike_through:
        estilo["riscado"] = True
    if altura and ctx.cap_height and abs(ctx.cap_height - altura) > 1e-9:
        estilo["escala"] = ctx.cap_height / altura
    # fator de largura de um codigo barra-W; sem ele vale o do estilo de texto
    if ctx.width_factor and abs(ctx.width_factor - 1.0) > 1e-9:
        estilo["largura"] = ctx.width_factor
    return estilo


# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------
#
# O MTEXT grava a fonte de um trecho de qualquer jeito que o AutoCAD aceite, e
# ele aceita varios: a familia ("Bookman Old Style|b1"), o arquivo
# ("bookosb.ttf", com ou sem extensao) ou o nome completo ("Bookman Old Style
# Bold"). O QGIS so entende a familia. Com outro nome, desenha numa fonte
# substituta -- no Windows, uma com cara de Times New Roman -- e sem o
# negrito, que vinha do arquivo: foi assim que o carimbo do mapa real, em
# Bookman negrito no AutoCAD, saiu fino e em outra letra. O indice abaixo,
# montado com as fontes que o ezdxf acha no Windows, traduz qualquer uma
# dessas formas para a familia.

_NEGRITO = {"bold", "negrito", "black", "heavy", "semibold", "demibold", "demi",
            "extrabold", "ultrabold"}
_ITALICO = {"italic", "italico", "itálico", "oblique"}
_EXTENSOES_TTF = (".ttf", ".ttc", ".otf")
_indice = None
_fontes_medida = {}


def _indice_fontes():
    """(por familia, por arquivo) das fontes TrueType instaladas, com as chaves
    em minusculas. Os dois vazios se o ezdxf nao conseguir listar as fontes."""
    global _indice
    if _indice is None:
        por_familia, por_arquivo = {}, {}
        try:
            from ezdxf.fonts import fonts
            for entrada in fonts.font_manager._font_cache._cache.values():
                face = entrada.font_face
                if face.family and face.filename.lower().endswith(_EXTENSOES_TTF):
                    por_familia.setdefault(face.family.lower(), []).append(face)
                    por_arquivo[face.filename.lower()] = face
        except Exception:
            por_familia, por_arquivo = {}, {}
        _indice = (por_familia, por_arquivo)
    return _indice


def resolver_fonte(nome, negrito=False, italico=False):
    """(familia, negrito, italico) para o nome de fonte de um trecho de MTEXT.

    `familia` e o nome que o QGIS reconhece, ou None se a fonte nao esta
    instalada: o trecho fica na Arial, como os textos sem fonte propria, em
    vez de cair na substituta do Windows. O negrito e o italico podem vir do
    codigo, do arquivo (bookosb = Bookman negrito) ou do nome completo. Sem a
    lista de fontes, o nome passa como veio.
    """
    nome = (nome or "").strip()
    por_familia, por_arquivo = _indice_fontes()
    if not nome or not por_familia:
        return (nome or None), negrito, italico
    faces = por_familia.get(nome.lower())
    if faces:
        return faces[0].family, negrito, italico
    base = nome.lower()
    for arquivo in (base,) + tuple(base + ext for ext in _EXTENSOES_TTF):
        face = por_arquivo.get(arquivo)
        if face:
            return face.family, negrito or face.weight >= 600, italico or face.is_italic
    palavras = nome.split()
    for k in range(len(palavras) - 1, 0, -1):
        faces = por_familia.get(" ".join(palavras[:k]).lower())
        if faces:
            resto = {p.lower() for p in palavras[k:]}
            return (faces[0].family, negrito or bool(resto & _NEGRITO),
                    italico or bool(resto & _ITALICO))
    return None, negrito, italico


def medir(texto, altura, estilo, esticamento=100):
    """Largura de um trecho, em unidades do desenho, na fonte do proprio trecho.

    E pela largura na fonte de verdade que o AutoCAD decide onde quebrar as
    linhas de um MTEXT. Medir tudo na Arial, mais estreita que as fontes de
    carimbo (a Bookman negrito e 14% mais larga), juntava na mesma linha
    palavras que no desenho estao em linhas diferentes. A altura e a da
    maiuscula, como no AutoCAD. Devolve None para trecho sem fonte propria,
    e quem chama usa a medida da Arial.
    """
    familia = estilo.get("fonte")
    if not familia or not texto:
        return None
    negrito, italico = bool(estilo.get("negrito")), bool(estilo.get("italico"))
    chave = (familia.lower(), negrito, italico)
    if chave not in _fontes_medida:
        _fontes_medida[chave] = _carregar_fonte(familia, negrito, italico)
    fonte = _fontes_medida[chave]
    if fonte is None:
        return None
    fator = float(esticamento or 100.0) / 100.0
    palavra = texto.replace(" ", "")      # o ezdxf mede espaco sozinho como zero
    largura = fonte.text_width_ex(palavra, altura, fator) if palavra else 0.0
    return largura + texto.count(" ") * fonte.space_width() * altura * fator


def escolher_face(familia, negrito, italico):
    """A face instalada da `familia` mais perto do pedido, ou None. O negrito do AutoCAD
    e o peso 700 (Arial Bold), nao o mais pesado da familia (Arial Black, 900)."""
    faces = _indice_fontes()[0].get((familia or "").lower())
    if not faces:
        return None
    return min(faces, key=lambda f: ((f.weight >= 600) != negrito, f.is_italic != italico,
                                     abs(f.weight - (700 if negrito else 400))))


def _carregar_fonte(familia, negrito, italico):
    face = escolher_face(familia, negrito, italico)
    if face is None:
        return None
    try:
        from ezdxf.fonts import fonts
        fonte = fonts.make_font(face.filename, cap_height=1.0)
    except Exception:
        return None
    # sem o arquivo, o ezdxf devolve uma fonte de largura fixa, que nao serve
    return fonte if isinstance(fonte, fonts.TrueTypeFont) else None


# ---------------------------------------------------------------------------
# Associacao com os textos que o GDAL devolve
# ---------------------------------------------------------------------------

class IndiceMtext:
    """Acha, para cada MTEXT do GDAL, o MTEXT correspondente lido pelo ezdxf.

    Pela posicao de insercao, que os dois calculam igual -- inclusive dentro
    de blocos, onde o GDAL nao da o handle do MTEXT e sim o do INSERT. O texto
    desempata quando dois MTEXT comecam no mesmo ponto.
    """

    def __init__(self, mtexts):
        self._grade = {}
        for m in mtexts:
            self._grade.setdefault(self._celula(*m["ponto"]), []).append(m)

    @staticmethod
    def _celula(x, y):
        return (int(math.floor(x * 100)), int(math.floor(y * 100)))

    def achar(self, x, y, texto):
        cx, cy = self._celula(x, y)
        candidatos = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidatos.extend(self._grade.get((cx + dx, cy + dy), []))
        candidatos = [m for m in candidatos
                      if abs(m["ponto"][0] - x) < 0.01 and abs(m["ponto"][1] - y) < 0.01]
        if not candidatos:
            return None
        alvo = "".join(str(texto or "").split())
        for m in candidatos:
            if "".join(m["texto"].split()) == alvo:
                return m
        return candidatos[0] if len(candidatos) == 1 else None

    def cor_do_texto(self, x, y, texto, cor):
        """A cor do MTEXT do GDAL em (x, y) como o AutoCAD o mostra (ver cor_do_mtext); `cor`
        e a que o GDAL deu, a da entidade."""
        achado = self.achar(x, y, texto)
        return cor_do_mtext(achado, cor) if achado else cor


def cor_do_mtext(m, cor_da_entidade):
    """'#rrggbb' em que o AutoCAD mostra o MTEXT: a cor escrita dentro dele (um codigo como
    barra-C5) quando todas as palavras tem a mesma; sem cor propria, ou com mais de uma, a
    da entidade.

    O GDAL so conhece a da entidade: no carimbo do desenho real, o endereco e azul por dentro
    numa camada laranja. A previa (a lista e o clique) e a conversao (o filtro e o nome da
    camada separada por cor) usam esta mesma regra, para a cor escolhida na lista ser a que
    a conversao procura. Com duas cores no mesmo texto o rotulo em HTML ja leva cada uma, e
    o campo fica com a da entidade, a das palavras sem codigo."""
    cores = {t[2].get("cor") or cor_da_entidade for t in m.get("trechos") or ()
             if t[0] == "palavra" and t[1].strip()}
    return cores.pop() if len(cores) == 1 else cor_da_entidade
