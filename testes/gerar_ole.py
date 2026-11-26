# -*- coding: utf-8 -*-
"""
Figuras coladas (OLE2FRAME) para os testes: um BMP de 24 ou 32 bits, o "arquivo
composto" do Windows que o embrulha e a entidade no desenho.
"""
import struct

import numpy as np


def bmp32(rgb):
    """Um BMP de 32 bits com mascaras de cor (o formato da tabela do desenho real)."""
    altura, largura = rgb.shape[:2]
    bgra = np.zeros((altura, largura, 4), dtype=np.uint8)
    bgra[..., 0], bgra[..., 1], bgra[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]
    pixels = bgra[::-1].tobytes()                          # de baixo para cima
    cabecalho = struct.pack("<IiiHHIIiiII", 40, largura, altura, 1, 32, 3, len(pixels),
                            3780, 3780, 0, 0)
    mascaras = struct.pack("<III", 0x00FF0000, 0x0000FF00, 0x000000FF)
    deslocamento = 14 + 40 + 12
    return (b"BM" + struct.pack("<IHHI", deslocamento + len(pixels), 0, 0, deslocamento)
            + cabecalho + mascaras + pixels)


def bmp24(rgb):
    altura, largura = rgb.shape[:2]
    passo = (largura * 3 + 3) // 4 * 4
    linhas = b"".join(rgb[y, :, ::-1].tobytes().ljust(passo, b"\0") for y in range(altura - 1, -1, -1))
    cabecalho = struct.pack("<IiiHHIIiiII", 40, largura, altura, 1, 24, 0, len(linhas), 0, 0, 0, 0)
    return b"BM" + struct.pack("<IHHI", 54 + len(linhas), 0, 0, 54) + cabecalho + linhas


def arquivo_composto(nome, dados):
    """Um arquivo composto do Windows (o recheio de um OLE) com um fluxo so."""
    setor, fim, livre = 512, 0xFFFFFFFE, 0xFFFFFFFF
    corpo = dados + b"\0" * (-len(dados) % setor)
    n = len(corpo) // setor
    fat = [0xFFFFFFFD, fim] + list(range(3, 2 + n)) + [fim]
    fat += [livre] * (setor // 4 - len(fat))

    def entrada(texto, tipo, inicio, tamanho, filho=livre):
        nome_ = (texto + "\0").encode("utf-16-le")
        return (nome_.ljust(64, b"\0") + struct.pack("<HBB", len(nome_), tipo, 1)
                + struct.pack("<III", livre, livre, filho) + b"\0" * 36
                + struct.pack("<IQ", inicio, tamanho))
    diretorio = (entrada("Root Entry", 5, fim, 0, filho=1) + entrada(nome, 2, 2, len(dados))
                 ).ljust(setor, b"\0")
    cabecalho = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
                 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
                 + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, fim, 0, fim, 0)
                 + struct.pack("<109I", 0, *([livre] * 108)))
    return cabecalho + struct.pack("<128I", *fat) + diretorio + corpo


def com_ole(msp, dados, canto_sup_esq, canto_inf_dir, camada="0"):
    from ezdxf.lldxf.tags import Tags
    from ezdxf.lldxf.types import DXFBinaryTag, DXFTag, DXFVertex
    ole = msp.new_entity("OLE2FRAME", {"layer": camada})
    pedacos = [DXFBinaryTag(310, dados[i:i + 127]) for i in range(0, len(dados), 127)]
    ole.acdb_ole2frame = Tags(
        [DXFTag(100, "AcDbOle2Frame"), DXFTag(70, 2), DXFTag(3, "Paintbrush Picture"),
         DXFVertex(10, (*canto_sup_esq, 0.0)), DXFVertex(11, (*canto_inf_dir, 0.0)),
         DXFTag(71, 2), DXFTag(72, 0), DXFTag(90, len(dados))] + pedacos + [DXFTag(1, "OLE")])
    return ole
