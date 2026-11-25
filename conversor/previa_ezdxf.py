# -*- coding: utf-8 -*-
"""
O que a previa desenha a partir do ezdxf, alem das hachuras: os textos e as imagens
coladas no desenho (a tabela de areas do desenho real e uma).

TEXTOS
  Cada letra pelo contorno de verdade da fonte, em unidades do desenho -- o mesmo
  contorno que o AutoCAD preenche. De perto se le; de longe vira o borrao que o
  AutoCAD tambem mostra. O MTEXT e quebrado em textos simples pelo ezdxf
  (MTextExplode), com a fonte, a cor e o negrito de cada trecho; a cota mostra o
  texto do bloco dela.

  So entra o que o AutoCAD mostra:
    - camada desligada ou congelada: o texto some;
    - bloco (INSERT) em camada congelada: some tudo dele, inclusive os atributos;
      em camada desligada, some o que esta na camada 0 (que herda a do INSERT);
    - atributo invisivel some.
  No desenho real sao 9 mil rotulos de pontos do levantamento em blocos congelados
  -- o GDAL da 5 mil deles como visiveis (ele so olha a camada do proprio atributo);
  `ocultos` corrige isso na lista.

IMAGENS
  O OLE2FRAME guarda o objeto colado num "arquivo composto" do Windows. Quando o
  objeto e uma figura (o fluxo CONTENTS e um BMP), ela vai para a previa no
  retangulo do quadro. Outros tipos (uma planilha viva do Excel, por exemplo) ficam
  de fora.
"""
import struct

import numpy as np

# Os textos de dentro de um bloco saem por cima do resto do bloco (o desempate dentro
# da vez do INSERT; as pecas do GDAL tem desempate de 0 em diante).
SEQ_DO_TEXTO = 1 << 40
# A curva de uma letra vira trechos retos com no maximo esta fracao da altura de erro.
FRACAO_DA_CURVA = 1.0 / 40.0
_COTAS = {"DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION"}
_PREFIXO_EXPLODIDO = "MtXpl_"


def ler(doc, cores):
    """{'textos': [...], 'ocultos': {handles}, 'imagens': [...]} do espaco do modelo.
    `cores` e o cad_ezdxf._Cores do documento.

    Cada texto: {'camada', 'cor' (r, g, b), 'texto', 'fonte' (arquivo), 'aneis' [Nx2],
    'topo' (handle da entidade solta de onde veio), 'seq', 'entidade' (o numero do texto de
    onde veio: os pedacos de um MTEXT tem o mesmo), 'handle' (o que o GDAL da a feicao dele:
    o do proprio texto ou atributo; o do INSERT ou da cota, se ele mora dentro de um bloco)}.
    Cada imagem: {'camada',
    'caixa' (xmin, ymin, xmax, ymax), 'imagem' HxWx3 uint8, 'topo'}. `ocultos` sao os
    handles que o GDAL da (o do INSERT, para o que vem de dentro do bloco; o do proprio
    atributo) cujas feicoes o AutoCAD nao mostra."""
    camadas = {c.dxf.name.upper(): c for c in doc.layers}
    return {"textos": _textos(doc, cores, camadas), "ocultos": _ocultos(doc, camadas),
            "imagens": _imagens(doc)}


def _escondida(camadas, nome, congelada_basta=False):
    """A camada esta desligada ou congelada (so congelada, com `congelada_basta`)."""
    estado = camadas.get((nome or "0").upper())
    if estado is None:
        return False
    return estado.is_frozen() or (not congelada_basta and estado.is_off())


def _ocultos(doc, camadas):
    ocultos = set()
    for insert in doc.modelspace().query("INSERT"):
        camada = insert.dxf.get("layer", "0") or "0"
        congelado = _escondida(camadas, camada, congelada_basta=True)
        if congelado:
            ocultos.add((insert.dxf.get("handle") or "").upper())
        for a in insert.attribs:
            if congelado or a.is_invisible or _escondida(camadas, _efetiva(a, camada)):
                ocultos.add((a.dxf.get("handle") or "").upper())
    ocultos.discard("")
    return ocultos


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

# As fontes TrueType que vem com o AutoCAD (a Swiss 721, da Bitstream) e as do Windows de mesmo
# desenho. Sem a original, o ezdxf poe a Arial normal -- e a swissc e estreita: o "Poco Raso
# Escavado" do desenho do pai saia 20% mais comprido que na foto do AutoCAD.
_EQUIVALENTES = {
    "swiss.ttf": "arial.ttf", "swissb.ttf": "arialbd.ttf", "swissi.ttf": "ariali.ttf",
    "swissbi.ttf": "arialbi.ttf", "swissk.ttf": "ariblk.ttf",
    "swissc.ttf": "arialn.ttf", "swisscb.ttf": "arialnb.ttf", "swissci.ttf": "arialni.ttf",
    "swisscbi.ttf": "arialnbi.ttf",
}


def _trocar_fontes_do_autocad(doc):
    """Nos estilos com uma fonte do AutoCAD que este Windows nao tem, a equivalente dele (se
    ele a tiver)."""
    from ezdxf.fonts import fonts
    for estilo in doc.styles:
        fonte = (estilo.dxf.get("font") or "").strip()
        troca = _EQUIVALENTES.get(fonte.replace("\\", "/").rsplit("/", 1)[-1].lower())
        try:
            if troca and not fonts.font_manager.has_font(fonte) \
                    and fonts.font_manager.has_font(troca):
                estilo.dxf.font = troca
        except Exception:
            continue


def _textos(doc, cores, camadas):
    from ezdxf.addons import MTextExplode

    _trocar_fontes_do_autocad(doc)
    # (entidade TEXT/ATTRIB, camada, cor do bloco, topo, numero do texto de onde veio: os
    # pedacos de um MTEXT tem o mesmo, handle da feicao do GDAL)
    pendentes = []
    bloco = doc.blocks.new(_nome_livre(doc))
    with MTextExplode(bloco) as quebra:
        for de, (entidade, camada, cor_do_bloco, topo) in enumerate(
                _visiveis(doc.modelspace(), camadas, cores)):
            # O GDAL da ao atributo o handle dele; ao texto de dentro de um bloco ou de uma
            # cota (que aqui chega sem handle: e copia virtual), o do INSERT ou da cota.
            handle = (entidade.dxf.get("handle") or "").upper() or topo
            if entidade.dxftype() == "MTEXT":
                antes = len(bloco)
                try:
                    quebra.explode(entidade, destroy=False)
                except Exception:
                    continue
                for parte in list(bloco)[antes:]:
                    pendentes.append((parte, camada, cor_do_bloco, topo, de, handle))
            else:
                pendentes.append((entidade, camada, cor_do_bloco, topo, de, handle))
    # os estilos que o MTextExplode cria so existem depois que ele termina
    _corrigir_negrito(doc)
    _trocar_fontes_do_autocad(doc)
    saida = []
    for i, (entidade, camada, cor_do_bloco, topo, de, handle) in enumerate(pendentes):
        item = _texto(entidade, camada, cores.da_entidade(entidade, camada, cor_do_bloco), topo)
        if item:
            item["seq"] += i
            item["_de"] = item["entidade"] = de
            item["handle"] = handle
            saida.append(item)
    _caixas(saida)
    return saida


def _caixas(textos):
    """A caixa de cada texto: a celula da fonte (da descida a subida) ao longo da linha. O
    AutoCAD a pinta no lugar das letras quando o texto girado fica miudo na tela (ver
    previa_raster.PIXELS_DO_TEXTO_GIRADO) -- uma por linha, nao por palavra: os pedacos de
    uma linha de MTEXT (o MTextExplode quebra por palavra) vao cada um ate o proximo."""
    linhas = {}
    for t in textos:
        u, n, base = t.pop("_eixo")
        chave = (t.pop("_de"), round(u[0], 6), round(u[1], 6),
                 round(base / max(t["altura"], 1e-12) * 100))
        linhas.setdefault(chave, []).append(t)
    for lista in linhas.values():
        lista.sort(key=lambda t: t["_ao_longo"][0])
        for k, t in enumerate(lista):
            comeco, fim = t["_ao_longo"]
            if k + 1 < len(lista):
                fim = max(fim, lista[k + 1]["_ao_longo"][0])
            u, n, base, descida, subida = t.pop("_celula")
            u, n = np.asarray(u), np.asarray(n)
            cantos = [comeco * u + (base - descida) * n, fim * u + (base - descida) * n,
                      fim * u + (base + subida) * n, comeco * u + (base + subida) * n]
            t["caixa"] = np.array(cantos + cantos[:1], dtype=float)
        for t in lista:
            t.pop("_ao_longo", None)


def _subida_e_descida(nome_da_fonte, altura):
    """(subida, descida) da celula da fonte para letras maiusculas de `altura`: o que o
    Windows reserva para uma linha de texto. Na Arial, 1,26 e 0,30 vezes a altura."""
    try:
        from ezdxf.fonts import fonts
        cache = fonts.make_font(nome_da_fonte or "arial.ttf", altura).glyph_cache
        os2 = cache.font["OS/2"]
        escala = cache.get_scaling_factor(altura)
        subida, descida = os2.usWinAscent * escala, os2.usWinDescent * escala
        if subida > 0 and descida >= 0:
            return subida, descida
    except Exception:
        pass
    return 1.264 * altura, 0.296 * altura


def _visiveis(entidades, camadas, cores, camada_do_bloco=None, cor_do_bloco=None, topo=None,
              nivel=0):
    """(entidade, camada efetiva, cor do bloco, topo) de cada TEXT, MTEXT e ATTRIB que o
    AutoCAD mostra (ver o comeco do arquivo)."""
    for e in entidades:
        tipo = e.dxftype()
        camada = _efetiva(e, camada_do_bloco)
        # o INSERT em camada desligada ainda mostra o que esta em outras camadas
        if _escondida(camadas, camada, congelada_basta=tipo == "INSERT"):
            continue
        dono = topo or (e.dxf.get("handle") or "").upper()
        if tipo == "INSERT":
            if nivel >= 16:
                continue
            cor = cores.da_entidade(e, camada, cor_do_bloco)
            for a in e.attribs:
                camada_a = _efetiva(a, camada)
                if not a.is_invisible and not _escondida(camadas, camada_a):
                    yield a, camada_a, cor, dono
            try:
                copias = list(e.multi_insert()) if e.mcount > 1 else [e]
                for copia in copias:
                    yield from _visiveis(copia.virtual_entities(), camadas, cores, camada, cor,
                                         dono, nivel + 1)
            except Exception:
                continue
        elif tipo in ("TEXT", "MTEXT"):
            yield e, camada, cor_do_bloco, dono
        elif tipo in _COTAS:
            # o texto da cota mora no bloco dela, na cor da cota
            cor = cores.da_entidade(e, camada, cor_do_bloco)
            try:
                partes = list(e.virtual_entities())
            except Exception:
                continue
            for x in partes:
                camada_x = _efetiva(x, camada)
                if x.dxftype() in ("TEXT", "MTEXT") and not _escondida(camadas, camada_x):
                    yield x, camada_x, cor, dono


def _efetiva(entidade, camada_do_bloco):
    """Dentro de um bloco, o que esta na camada 0 assume a camada do INSERT."""
    propria = entidade.dxf.get("layer", "0") or "0"
    if camada_do_bloco is not None and propria == "0":
        return camada_do_bloco
    return propria


def _nome_livre(doc):
    nome, n = "__previa_textos", 0
    while nome in doc.blocks:
        n += 1
        nome = "__previa_textos_%d" % n
    return nome


def _corrigir_negrito(doc):
    """O MTextExplode guarda a fonte de cada trecho num estilo novo; para o negrito ele
    escolhia a Arial Black (peso 900) em vez da Arial Bold (700), a do AutoCAD."""
    from . import cad_ezdxf
    for estilo in doc.styles:
        if not estilo.dxf.name.startswith(_PREFIXO_EXPLODIDO):
            continue
        try:
            familia, italico, negrito = estilo.get_extended_font_data()
        except Exception:
            continue
        face = cad_ezdxf.escolher_face(familia, negrito, italico) if familia else None
        if face is not None:
            estilo.dxf.font = face.filename


def _texto(entidade, camada, cor, topo):
    """O texto (TEXT ou ATTRIB) como contornos de letra, ou None se nao houver o que
    desenhar."""
    from ezdxf.addons import text2path
    try:
        altura = abs(float(entidade.dxf.get("height", 1.0) or 1.0))
        caminhos = text2path.make_paths_from_entity(entidade)
    except Exception:
        return None
    passo = max(altura * FRACAO_DA_CURVA, 1e-9)
    aneis = []
    for caminho in caminhos:
        try:
            pontos = np.array([(v.x, v.y) for v in caminho.flattening(passo)], dtype=float)
        except Exception:
            continue
        if len(pontos) < 3:
            continue
        if not np.allclose(pontos[0], pontos[-1]):
            pontos = np.vstack([pontos, pontos[:1]])
        aneis.append(pontos)
    if not aneis:
        return None
    try:
        fonte = entidade.font_name()
    except Exception:
        fonte = ""
    # A linha do texto: u ao longo dela, n para cima, a linha de base em n. Sem giro (e de
    # frente) o AutoCAD 2007 manda o Windows escrever; girado, ele mesmo desenha.
    angulo = float(entidade.dxf.get("rotation", 0.0) or 0.0)
    extrusao = entidade.dxf.get("extrusion", (0.0, 0.0, 1.0))
    girado = abs(((angulo + 180.0) % 360.0) - 180.0) > 1e-6 or tuple(extrusao)[:3] != (0, 0, 1)
    rad = np.radians(angulo)
    u, n = np.array([np.cos(rad), np.sin(rad)]), np.array([-np.sin(rad), np.cos(rad)])
    insercao = entidade.dxf.get("insert", (0.0, 0.0, 0.0))
    base = float(np.dot((insercao[0], insercao[1]), n))
    ao_longo = np.concatenate(aneis) @ u
    subida, descida = _subida_e_descida(fonte, altura)
    return {"camada": camada, "cor": tuple(cor), "texto": entidade.plain_text(), "fonte": fonte,
            "aneis": aneis, "topo": topo, "seq": SEQ_DO_TEXTO, "girado": bool(girado),
            "altura": altura, "_eixo": (u, n, base),
            "_ao_longo": (float(ao_longo.min()), float(ao_longo.max())),
            "_celula": (u, n, base, descida, subida)}


# ---------------------------------------------------------------------------
# Imagens coladas (OLE2FRAME)
# ---------------------------------------------------------------------------

def _imagens(doc):
    camadas = {c.dxf.name.upper(): c for c in doc.layers}
    saida = []
    for ole in doc.modelspace().query("OLE2FRAME"):
        camada = ole.dxf.get("layer", "0") or "0"
        estado = camadas.get(camada.upper())
        if estado is not None and (estado.is_off() or estado.is_frozen()):
            continue
        tags = getattr(ole, "acdb_ole2frame", None)
        if tags is None:
            continue
        try:
            canto_a, canto_b = tags.get_first_value(10), tags.get_first_value(11)
            imagem = imagem_do_ole(ole.binary_data())
        except Exception:
            continue
        if imagem is None:
            continue
        caixa = (min(canto_a[0], canto_b[0]), min(canto_a[1], canto_b[1]),
                 max(canto_a[0], canto_b[0]), max(canto_a[1], canto_b[1]))
        if caixa[2] <= caixa[0] or caixa[3] <= caixa[1]:
            continue
        saida.append({"camada": camada, "caixa": caixa, "imagem": imagem,
                      "topo": (ole.dxf.get("handle") or "").upper()})
    return saida


_ASSINATURA = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FIM = 0xFFFFFFFA                   # daqui para cima: fim de cadeia, setor livre...


def imagem_do_ole(dados):
    """A figura (HxWx3 uint8) de um objeto colado, ou None se ele nao for uma figura."""
    i = dados.find(_ASSINATURA)
    if i < 0:
        return None
    conteudo = _fluxo(dados[i:], "CONTENTS")
    if conteudo is None or not conteudo.startswith(b"BM"):
        return None
    return imagem_do_bmp(conteudo)


def _fluxo(cfb, procurado):
    """O conteudo do fluxo `procurado` de um arquivo composto do Windows, ou None."""
    setor = 1 << struct.unpack_from("<H", cfb, 30)[0]
    mini = 1 << struct.unpack_from("<H", cfb, 32)[0]
    n_fat, dir_ini = struct.unpack_from("<II", cfb, 44)
    corte, minifat_ini = struct.unpack_from("<II", cfb, 56)
    difat_ini, n_difat = struct.unpack_from("<II", cfb, 68)

    def ler_setor(s):
        return cfb[512 + s * setor:512 + (s + 1) * setor] if setor == 512 else \
            cfb[(s + 1) * setor:(s + 2) * setor]

    setores_fat = [s for s in struct.unpack_from("<109I", cfb, 76) if s < _FIM]
    s, voltas = difat_ini, 0
    while n_difat and s < _FIM and voltas < 10000:
        valores = struct.unpack_from("<%dI" % (setor // 4), ler_setor(s))
        setores_fat += [v for v in valores[:-1] if v < _FIM]
        s, voltas, n_difat = valores[-1], voltas + 1, n_difat - 1
    fat = []
    for s in setores_fat[:n_fat]:
        fat.extend(struct.unpack_from("<%dI" % (setor // 4), ler_setor(s)))

    def cadeia(s):
        partes, voltas = [], 0
        while s < _FIM and s < len(fat) and voltas <= len(fat):
            partes.append(ler_setor(s))
            s, voltas = fat[s], voltas + 1
        return b"".join(partes)

    diretorio = cadeia(dir_ini)
    entradas = []
    for k in range(len(diretorio) // 128):
        e = diretorio[k * 128:(k + 1) * 128]
        tamanho_nome = struct.unpack_from("<H", e, 64)[0]
        nome = e[:max(tamanho_nome - 2, 0)].decode("utf-16-le", "replace")
        inicio, tamanho = struct.unpack_from("<IQ", e, 116)
        entradas.append((nome, e[66], inicio, tamanho))
    alvo = next((x for x in entradas if x[1] == 2 and x[0].upper() == procurado.upper()), None)
    if alvo is None:
        return None
    _nome, _tipo, inicio, tamanho = alvo
    if tamanho >= corte:
        return cadeia(inicio)[:tamanho]
    # fluxo pequeno: mora no "mini fluxo" da raiz, em pedacos de `mini` bytes
    raiz = next((x for x in entradas if x[1] == 5), None)
    if raiz is None:
        return None
    mini_fluxo = cadeia(raiz[2])
    minifat = []
    s, voltas = minifat_ini, 0
    while s < _FIM and s < len(fat) and voltas <= len(fat):
        minifat.extend(struct.unpack_from("<%dI" % (setor // 4), ler_setor(s)))
        s, voltas = fat[s], voltas + 1
    partes, s, voltas = [], inicio, 0
    while s < _FIM and s < len(minifat) and voltas <= len(minifat):
        partes.append(mini_fluxo[s * mini:(s + 1) * mini])
        s, voltas = minifat[s], voltas + 1
    return b"".join(partes)[:tamanho]


def imagem_do_bmp(dados):
    """O BMP como HxWx3 uint8 (de cima para baixo), ou None se o formato nao for um dos
    comuns: 24 ou 32 bits (com ou sem mascaras de cor) ou 1, 4 e 8 bits com paleta."""
    if len(dados) < 54 or not dados.startswith(b"BM"):
        return None
    inicio = struct.unpack_from("<I", dados, 10)[0]
    tamanho_cab = struct.unpack_from("<I", dados, 14)[0]
    if tamanho_cab < 40:
        return None
    largura, altura, _planos, bits, compressao = struct.unpack_from("<iiHHI", dados, 18)
    cores_usadas = struct.unpack_from("<I", dados, 46)[0]
    de_baixo = altura > 0
    altura = abs(altura)
    if largura <= 0 or altura <= 0:
        return None
    passo = (largura * bits + 31) // 32 * 4
    bruto = np.frombuffer(dados, dtype=np.uint8, count=passo * altura, offset=inicio)
    linhas = bruto.reshape(altura, passo)
    if bits in (24, 32) and compressao in (0, 3):
        if bits == 24:
            if compressao != 0:
                return None
            bgr = linhas[:, :largura * 3].reshape(altura, largura, 3)
            rgb = bgr[..., ::-1]
        else:
            valores = linhas[:, :largura * 4].copy().view("<u4").reshape(altura, largura)
            if compressao == 3:
                onde = 14 + tamanho_cab if tamanho_cab == 40 else 54
                mascaras = struct.unpack_from("<III", dados, onde)
            else:
                mascaras = (0x00FF0000, 0x0000FF00, 0x000000FF)
            rgb = np.stack([_canal(valores, m) for m in mascaras], axis=-1)
    elif bits in (1, 4, 8) and compressao == 0:
        n_cores = cores_usadas or (1 << bits)
        paleta = np.frombuffer(dados, dtype=np.uint8, count=4 * n_cores,
                               offset=14 + tamanho_cab).reshape(n_cores, 4)[:, 2::-1]
        bits_por_linha = np.unpackbits(linhas, axis=1)[:, :largura * bits]
        pesos = (1 << np.arange(bits - 1, -1, -1)).astype(np.int64)
        indices = (bits_por_linha.reshape(altura, largura, bits) * pesos).sum(axis=2)
        rgb = paleta[np.minimum(indices, n_cores - 1)]
    else:
        return None
    rgb = np.ascontiguousarray(rgb[::-1] if de_baixo else rgb, dtype=np.uint8)
    return rgb


def _canal(valores, mascara):
    """Um canal de cor (0..255) tirado de pixels de 32 bits pela mascara dele."""
    if not mascara:
        return np.zeros(valores.shape, dtype=np.uint8)
    deslocamento = (mascara & -mascara).bit_length() - 1
    maximo = mascara >> deslocamento
    canal = (valores & np.uint32(mascara)) >> np.uint32(deslocamento)
    if maximo == 255:
        return canal.astype(np.uint8)
    return (canal.astype(np.float64) * 255.0 / maximo + 0.5).astype(np.uint8)
