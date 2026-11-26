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
import threading

LINK_DOWNLOAD = "https://www.opendesign.com/guestfiles/oda_file_converter"

MENSAGEM_AUSENTE = (
    "Para trabalhar com arquivos .dwg é preciso instalar o ODA File Converter "
    "(gratuito):\n\n"
    "  1. Acesse  " + LINK_DOWNLOAD + "\n"
    "  2. Baixe a versão 'Windows 8-11 64-bit'\n"
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


# O que esta em andamento agora: as pastas e os arquivos do TEMP com copia do desenho do
# cliente (ou de um pedaco dele) e os ODA rodando. Quem cria isso e uma thread de trabalho;
# sem este registro, fechar o programa antes de a thread terminar deixava a copia no TEMP
# sem que ninguem soubesse dela. `encerrar` apaga tudo isto.
_trava = threading.Lock()
_temporarios = set()
_canceladas = set()        # pastas que `encerrar` varreu: nenhum ODA pode mais rodar nelas
_processos = set()


def _nova_pasta(prefixo):
    pasta = tempfile.mkdtemp(prefix=prefixo)
    with _trava:
        _temporarios.add(pasta)
    return pasta


def _esquecer(pasta):
    with _trava:
        _temporarios.discard(pasta)
        _canceladas.discard(pasta)


def anotar_temporario(caminho):
    """Registra um arquivo temporario da leitura do desenho (a copia filtrada do ezdxf, a do
    GDAL, o VRT). Quem o criou o apaga ao terminar; isto so cobre o programa fechar antes.
    Devolve o proprio caminho."""
    with _trava:
        _temporarios.add(caminho)
    return caminho


def _apagar_do_disco(caminho):
    if os.path.isdir(caminho):
        shutil.rmtree(caminho, ignore_errors=True)
    else:
        try:
            os.remove(caminho)
        except OSError:
            pass


def encerrar():
    """O programa esta fechando: encerra o ODA que ainda roda e apaga o que ficou no TEMP com
    copia do desenho do cliente (a leitura ainda nao tinha terminado, por exemplo)."""
    with _trava:
        processos, pastas = list(_processos), list(_temporarios)
        _canceladas.update(pastas)         # a thread que ainda ia lancar o ODA desiste
    for processo in processos:
        try:
            if processo.poll() is None:
                processo.kill()
                processo.wait(timeout=5)       # solta os arquivos antes de apagar
        except Exception:
            pass
    presas = []
    for pasta in pastas:
        _apagar_do_disco(pasta)
        if os.path.lexists(pasta):
            presas.append(pasta)
        else:
            with _trava:
                # a marca em _canceladas fica: so a thread dona da pasta a tira (_esquecer)
                _temporarios.discard(pasta)
    if presas:
        _apagar_depois_que_eu_sair(presas)


def _apagar_depois_que_eu_sair(caminhos):
    """No Windows arquivo aberto nao se apaga, e a leitura do desenho segura o DXF aberto
    ate acabar. Um cmd escondido espera o programa terminar de sair e apaga."""
    if os.name != "nt":
        return
    apagar = " & ".join(('rmdir /s /q "%s"' if os.path.isdir(c) else 'del /f /q "%s"') % c
                        for c in caminhos)
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    try:
        # /s faz o cmd tirar so as aspas de fora, entao os caminhos podem ter espaco
        subprocess.Popen('cmd /s /c "ping -n 5 127.0.0.1 >nul & %s"' % apagar,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                         startupinfo=info, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _conferir_cancelamento(pasta):
    if pasta in _canceladas:
        raise ErroDWG("O programa foi fechado.")


def _executar(entrada_dir, saida_dir, versao, formato, filtro):
    exe = localizar_oda()
    if not exe:
        raise ErroDWG(MENSAGEM_AUSENTE)

    comando = [exe, entrada_dir, saida_dir, versao, formato, "0", "1", filtro]

    # O ODA e um programa de janela (Qt); roda e fecha sozinho. CREATE_NO_WINDOW so
    # esconde console e nao basta: o que esconde a janela dele e o STARTUPINFO pedir
    # SW_HIDE, que vale para a primeira janela do processo. Medido com o ODA 27.10:
    # sem isso a janela fica visivel durante a conversao; com isso nunca fica.
    flags = 0
    info = None
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
    pasta = os.path.dirname(entrada_dir)
    processo = None
    try:
        _conferir_cancelamento(pasta)
        processo = subprocess.Popen(comando, creationflags=flags, startupinfo=info,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with _trava:
            _processos.add(processo)
            cancelada = pasta in _canceladas
        if cancelada:                      # `encerrar` rodou entre o teste de cima e o Popen
            processo.kill()
            processo.wait(timeout=5)
            raise ErroDWG("O programa foi fechado.")
        processo.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.communicate()
        raise ErroDWG("O ODA File Converter demorou demais (mais de 10 minutos) "
                      "e foi interrompido. O arquivo pode ser grande demais.")
    except ErroDWG:
        raise
    except Exception as erro:
        raise ErroDWG("Falha ao executar o ODA File Converter: %s" % erro)
    finally:
        with _trava:
            _processos.discard(processo)


PREFIXO_TEMPORARIO = "conv_dwg_"


def dwg_para_dxf(caminho_dwg, registrar=None):
    """Converte um .dwg em .dxf temporario. Devolve o caminho do .dxf.

    O .dxf fica numa pasta do TEMP com uma copia do desenho do cliente: quem chama apaga
    com apagar_temporario quando nao precisar mais. Se a conversao falha, a pasta ja sai
    apagada."""
    pasta = _nova_pasta(PREFIXO_TEMPORARIO)
    try:
        _conferir_cancelamento(pasta)            # nao recria o que `encerrar` acabou de apagar
        entrada = os.path.join(pasta, "entrada")
        saida = os.path.join(pasta, "saida")
        os.makedirs(entrada)
        os.makedirs(saida)

        nome = os.path.basename(caminho_dwg)
        shutil.copy2(caminho_dwg, os.path.join(entrada, nome))

        if registrar:
            registrar("Convertendo %s para DXF com o ODA File Converter..." % nome)
        _executar(entrada, saida, "ACAD2004", "DXF", "*.DWG")

        gerados = (glob.glob(os.path.join(saida, "*.dxf"))
                   + glob.glob(os.path.join(saida, "*.DXF")))
        if not gerados:
            raise ErroDWG(
                "O ODA File Converter não gerou nenhum DXF a partir de '%s'.\n"
                "O arquivo pode estar corrompido, protegido por senha, ou não ser "
                "um DWG valido." % nome)
        return gerados[0]
    except BaseException:
        shutil.rmtree(pasta, ignore_errors=True)
        _esquecer(pasta)
        raise


def pasta_temporaria(caminho_dxf):
    """A pasta do TEMP que dwg_para_dxf criou para `caminho_dxf`, ou None se ele nao e um
    desses (um DXF que a pessoa escolheu, por exemplo)."""
    pasta = os.path.dirname(os.path.dirname(os.path.abspath(caminho_dxf)))
    return pasta if os.path.basename(pasta).startswith(PREFIXO_TEMPORARIO) else None


def apagar_temporario(caminho_dxf):
    """Apaga a pasta do TEMP de um DXF feito por dwg_para_dxf (a copia do desenho do
    cliente). Nao mexe em nenhum outro arquivo."""
    pasta = pasta_temporaria(caminho_dxf)
    if pasta and os.path.isdir(pasta):
        shutil.rmtree(pasta, ignore_errors=True)
    if pasta:
        _esquecer(pasta)


def dxf_para_dwg(caminho_dxf, caminho_dwg_final, registrar=None):
    """Converte um .dxf em .dwg, salvando no caminho pedido. A pasta de trabalho do ODA,
    no TEMP, sai apagada (deu certo ou nao)."""
    pasta = _nova_pasta("conv_dxf_")
    try:
        return _dxf_para_dwg(pasta, caminho_dxf, caminho_dwg_final, registrar)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
        _esquecer(pasta)


def _dxf_para_dwg(pasta, caminho_dxf, caminho_dwg_final, registrar):
    _conferir_cancelamento(pasta)
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
        raise ErroDWG("O ODA File Converter não gerou o arquivo .dwg.")

    shutil.move(gerados[0], caminho_dwg_final)
    return caminho_dwg_final
