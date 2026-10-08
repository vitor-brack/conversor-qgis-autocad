# -*- coding: utf-8 -*-
"""
Suporte a arquivos .dwg via ODA File Converter.

Por que um programa externo: o .dwg e um formato binario fechado da Autodesk.
Nenhuma biblioteca livre le ou escreve .dwg de forma confiavel -- o GDAL so
faz isso com um SDK proprietario que nao pode ser redistribuido. O ODA File
Converter e gratuito e resolve o problema, entao o programa o usa quando esta
instalado e explica como instalar quando nao esta.

O DXF continua funcionando sem nada disso instalado.
"""

import glob
import os
import shutil
import subprocess
import tempfile

LINK_DOWNLOAD = "https://www.opendesign.com/guestfiles/oda_file_converter"

MENSAGEM_AUSENTE = (
    "Para trabalhar com arquivos .dwg e preciso instalar o ODA File Converter "
    "(gratuito):\n\n"
    "  1. Acesse  " + LINK_DOWNLOAD + "\n"
    "  2. Baixe a versao 'Windows 8-11 64-bit'\n"
    "  3. Instale e abra este programa de novo\n\n"
    "Alternativa sem instalar nada: no AutoCAD, use Arquivo > Salvar Como e "
    "escolha 'AutoCAD 2004/LT2004 DXF (*.dxf)'. O programa converte DXF sem "
    "precisar de nenhum extra."
)

# Versao de saida ao gerar .dwg. O AutoCAD 2007 abre 2004 e 2007; 2004 e a
# escolha mais conservadora e abre tambem em versoes mais antigas.
VERSAO_SAIDA_DWG = "ACAD2004"


def localizar_oda():
    """Caminho do ODAFileConverter.exe, ou None se nao estiver instalado."""
    no_path = shutil.which("ODAFileConverter")
    if no_path:
        return no_path

    padroes = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        raiz = os.environ.get(var)
        if raiz:
            padroes.append(os.path.join(raiz, "ODA", "*", "ODAFileConverter.exe"))
            padroes.append(os.path.join(raiz, "ODA", "*", "*", "ODAFileConverter.exe"))

    for padrao in padroes:
        achados = sorted(glob.glob(padrao))
        if achados:
            return achados[-1]     # a versao mais recente
    return None


def disponivel():
    return localizar_oda() is not None


class ErroDWG(Exception):
    pass


def _executar(entrada_dir, saida_dir, versao, formato, filtro):
    exe = localizar_oda()
    if not exe:
        raise ErroDWG(MENSAGEM_AUSENTE)

    comando = [exe, entrada_dir, saida_dir, versao, formato, "0", "1", filtro]

    # O ODA e um programa de janela; roda e fecha sozinho. Escondemos a janela
    # para nao piscar na cara do usuario.
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.run(comando, timeout=600, creationflags=flags,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise ErroDWG("O ODA File Converter demorou demais (mais de 10 minutos) "
                      "e foi interrompido. O arquivo pode ser grande demais.")
    except Exception as erro:
        raise ErroDWG("Falha ao executar o ODA File Converter: %s" % erro)


def dwg_para_dxf(caminho_dwg, registrar=None):
    """Converte um .dwg em .dxf temporario. Devolve o caminho do .dxf."""
    pasta = tempfile.mkdtemp(prefix="conv_dwg_")
    entrada = os.path.join(pasta, "entrada")
    saida = os.path.join(pasta, "saida")
    os.makedirs(entrada)
    os.makedirs(saida)

    nome = os.path.basename(caminho_dwg)
    shutil.copy2(caminho_dwg, os.path.join(entrada, nome))

    if registrar:
        registrar("Convertendo %s para DXF com o ODA File Converter..." % nome)
    _executar(entrada, saida, "ACAD2004", "DXF", "*.DWG")

    gerados = glob.glob(os.path.join(saida, "*.dxf")) + glob.glob(os.path.join(saida, "*.DXF"))
    if not gerados:
        raise ErroDWG(
            "O ODA File Converter nao gerou nenhum DXF a partir de '%s'.\n"
            "O arquivo pode estar corrompido, protegido por senha, ou nao ser "
            "um DWG valido." % nome)
    return gerados[0]


def dxf_para_dwg(caminho_dxf, caminho_dwg_final, registrar=None):
    """Converte um .dxf em .dwg, salvando no caminho pedido."""
    pasta = tempfile.mkdtemp(prefix="conv_dxf_")
    entrada = os.path.join(pasta, "entrada")
    saida = os.path.join(pasta, "saida")
    os.makedirs(entrada)
    os.makedirs(saida)

    nome = os.path.basename(caminho_dxf)
    shutil.copy2(caminho_dxf, os.path.join(entrada, nome))

    if registrar:
        registrar("Convertendo para DWG (%s) com o ODA File Converter..." % VERSAO_SAIDA_DWG)
    _executar(entrada, saida, VERSAO_SAIDA_DWG, "DWG", "*.DXF")

    gerados = glob.glob(os.path.join(saida, "*.dwg")) + glob.glob(os.path.join(saida, "*.DWG"))
    if not gerados:
        raise ErroDWG("O ODA File Converter nao gerou o arquivo .dwg.")

    shutil.move(gerados[0], caminho_dwg_final)
    return caminho_dwg_final
