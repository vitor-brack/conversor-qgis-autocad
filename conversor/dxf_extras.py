# -*- coding: utf-8 -*-
"""
O que o GDAL nao entrega e precisa ser lido direto do DXF.

  MTEXT   largura do quadro (grupo 41) e espacamento entre linhas (grupo 44).
          O GDAL devolve o texto numa linha so, ignorando a largura; sem ela
          nao da para quebrar as linhas como o AutoCAD quebra.

  IMAGE   imagens raster. O GDAL as descarta por completo, sem aviso -- um
          logotipo ou uma foto aerea simplesmente some. A entidade IMAGE diz
          onde a imagem fica e em que tamanho; o arquivo da imagem em si e
          apontado por um objeto IMAGEDEF na secao OBJECTS.

O DXF e lido uma vez so, como pares (codigo de grupo, valor).
"""

from . import dxf_estilo

_TIPOS = {"MTEXT", "IMAGE", "IMAGEDEF"}


def _numero(valor, padrao=0.0):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return padrao


def ler(caminho_dxf):
    """Devolve {'mtext': {handle: {...}}, 'imagens': [...], 'arquivos': {handle: caminho}}.

    Qualquer problema de leitura devolve o que foi lido ate ali: estes dados
    melhoram a conversao, mas ela nao pode depender deles.
    """
    mtext = {}
    imagens = []
    arquivos = {}
    codec, _ = dxf_estilo.detectar_codificacao(caminho_dxf)

    secao = None
    proximo_e_secao = False
    tipo = None
    reg = None

    def fechar():
        if not reg or tipo is None:
            return
        handle = (reg.get(5) or "").upper()
        if tipo == "MTEXT" and secao == "ENTITIES" and handle:
            mtext[handle] = {"largura": _numero(reg.get(41)),
                             "espacamento": _numero(reg.get(44), 1.0) or 1.0}
        elif tipo == "IMAGE" and secao == "ENTITIES" and reg.get(67) != "1":
            imagens.append({
                "handle": handle,
                "camada": reg.get(8) or "0",
                "origem": (_numero(reg.get(10)), _numero(reg.get(20))),
                "u": (_numero(reg.get(11)), _numero(reg.get(21))),
                "v": (_numero(reg.get(12)), _numero(reg.get(22))),
                "pixels": (_numero(reg.get(13)), _numero(reg.get(23))),
                "definicao": (reg.get(340) or "").upper(),
            })
        elif tipo == "IMAGEDEF" and handle and reg.get(1):
            arquivos[handle] = reg.get(1)

    try:
        for codigo, valor in dxf_estilo._pares(caminho_dxf, codec):
            if codigo == 0:
                fechar()
                proximo_e_secao = valor == "SECTION"
                if valor in _TIPOS:
                    tipo, reg = valor, {}
                else:
                    tipo, reg = None, None
                continue
            if proximo_e_secao and codigo == 2:
                secao, proximo_e_secao = valor, False
                continue
            if reg is not None and codigo not in reg:
                # so a primeira ocorrencia: os codigos 14/24 de recorte, por
                # exemplo, se repetem e nao interessam aqui
                reg[codigo] = valor
        fechar()
    except Exception:
        pass
    return {"mtext": mtext, "imagens": imagens, "arquivos": arquivos}
