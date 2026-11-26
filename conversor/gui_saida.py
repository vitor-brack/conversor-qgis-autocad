# -*- coding: utf-8 -*-
"""
O passo "Onde salvar" da aba AutoCAD -> QGIS: a pasta e o nome em campos separados.

Antes era um campo so com o caminho inteiro; para dar outro nome a cada conversao
(a pessoa converte uma camada de cada vez) era preciso achar, no meio do caminho,
onde o nome comeca. Agora a pasta aparece de um lado e so o nome do outro.

Duas partes: as funcoes que montam e desmontam o caminho (sem janela, faceis de
testar) e o campo (CampoSaida).
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk

GPKG = "GPKG"
EXTENSAO_GPKG = ".gpkg"
# o que cada formato grava dentro da pasta (so o GeoPackage e um arquivo so)
ARQUIVOS_DA_PASTA = {"ESRI Shapefile": ".shp", "GeoJSON": ".geojson"}

COR_AVISO = "#b35c00"       # a mesma laranja dos outros avisos da janela
COR_NOTA = "#555"

_PROIBIDOS = '\\/:*?"<>|'
_RESERVADOS = ({"CON", "PRN", "AUX", "NUL"}
               | {"COM%d" % i for i in range(1, 10)}
               | {"LPT%d" % i for i in range(1, 10)})


def grava_arquivo(formato):
    """So o GeoPackage e um arquivo; Shapefile e GeoJSON gravam uma pasta com um
    arquivo por camada (convert._gravar_grupos)."""
    return formato == GPKG


def _sem_extensao_gpkg(nome):
    nome = nome.strip()
    if nome.lower().endswith(EXTENSAO_GPKG):
        nome = nome[:-len(EXTENSAO_GPKG)].rstrip()
    return nome


def montar_caminho(pasta, nome, formato):
    """O caminho que vai para a conversao: pasta + nome (+ .gpkg no GeoPackage)."""
    if grava_arquivo(formato):
        return os.path.join(pasta, _sem_extensao_gpkg(nome) + EXTENSAO_GPKG)
    return os.path.join(pasta, nome.strip())


def dividir_caminho(caminho, formato):
    """O inverso de montar_caminho: (pasta, nome). Aceita a barra do Windows e a
    barra comum (o seletor de pastas devolve "C:/dados/obra")."""
    caminho = caminho.strip()
    if not caminho:
        return "", ""
    pasta, nome = os.path.split(os.path.normpath(caminho))
    if grava_arquivo(formato):
        nome = _sem_extensao_gpkg(nome)
    return pasta, nome


def problema_no_nome(nome, formato):
    """Diz o que esta errado no nome (ou None). O Windows e o motivo da maioria."""
    nome = nome.strip()
    if grava_arquivo(formato):
        nome = _sem_extensao_gpkg(nome)
    if not nome:
        return ("Digite o nome do arquivo." if grava_arquivo(formato)
                else "Digite o nome da pasta.")
    if any(c in _PROIBIDOS or ord(c) < 32 for c in nome):
        return "O nome nao pode ter estes caracteres: \\ / : * ? \" < > |"
    if nome.endswith("."):
        return "O nome nao pode terminar com ponto."
    if nome.split(".")[0].strip().upper() in _RESERVADOS:
        return "O Windows nao aceita \"%s\" como nome." % nome.split(".")[0].strip()
    if not grava_arquivo(formato) and "." in nome:
        # a conversao tira o que vem depois do ultimo ponto para achar a pasta
        return "Neste formato o nome vira o de uma pasta: tire o ponto do nome."
    return None


class CampoSaida(ttk.Frame):
    """Pasta (so para ver, muda no botao) e nome (o que se digita), com o sufixo do
    formato ao lado e um aviso embaixo: o que vai ser criado, ou o que esta errado."""

    PRIMEIRO_USO = ("Escolha o desenho no passo 1: o programa sugere a pasta e o nome. "
                    "Voce tambem pode escolher a pasta aqui.")

    def __init__(self, pai, formato):
        super().__init__(pai)
        self._formato = formato                 # tk.StringVar com o formato de saida
        self._pasta_manual = False              # a pessoa escolheu a pasta, nao o desenho
        self.pasta_var = tk.StringVar(master=self)
        self.nome_var = tk.StringVar(master=self)
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Pasta").grid(row=0, column=0, sticky="w", padx=(0, 8))
        # cinza e sem clique: o caminho comprido ninguem edita nem seleciona, escolhe-se no
        # botao (o texto entra pela variavel, que funciona com o campo desligado). Aparece
        # o fim dele (a pasta em que se esta)
        self.pasta_entrada = ttk.Entry(self, textvariable=self.pasta_var, state="disabled")
        self.pasta_entrada.grid(row=0, column=1, sticky="we")
        self.pasta_entrada.bind("<Configure>", lambda _e: self._mostrar_o_fim_da_pasta())
        self.botao_pasta = ttk.Button(self, text="Escolher pasta...", width=16,
                                      command=self.escolher_pasta)
        self.botao_pasta.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(self, text="Nome").grid(row=1, column=0, sticky="w", padx=(0, 8),
                                          pady=(6, 0))
        self.nome_entrada = ttk.Entry(self, textvariable=self.nome_var)
        self.nome_entrada.grid(row=1, column=1, sticky="we", pady=(6, 0))
        self.sufixo = ttk.Label(self, text="", foreground=COR_NOTA)
        self.sufixo.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(6, 0))
        # clicar no nome seleciona tudo: digitar ja troca o nome inteiro
        self.nome_entrada.bind("<FocusIn>", self._selecionar_o_nome)
        self.nome_entrada.bind("<FocusOut>", lambda _e: self.normalizar())
        self.nome_entrada.bind("<Return>", lambda _e: self.normalizar())

        self.aviso = ttk.Label(self, text="", wraplength=560, justify="left")
        self.aviso.grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        # o texto quebra na largura que a janela tem (fixo, cortava na janela estreita e
        # quebrava a toa na larga)
        self.bind("<Configure>", self._ajustar_a_quebra_do_aviso)

        self._tracos = [(var, var.trace_add("write", self.atualizar))
                        for var in (self.pasta_var, self.nome_var, formato)]
        self.atualizar()

    def destroy(self):
        for var, traco in self._tracos:
            try:
                var.trace_remove("write", traco)
            except tk.TclError:
                pass
        super().destroy()

    # ---- o que a pessoa ve e o que vai para a conversao
    def pasta(self):
        return self.pasta_var.get()

    def nome(self):
        return self.nome_var.get().strip()

    def problema(self):
        if not self.pasta():
            return "Escolha a pasta onde salvar."
        return problema_no_nome(self.nome(), self._formato.get())

    def caminho_saida(self):
        """O caminho completo, ou "" enquanto faltar a pasta ou o nome estiver errado."""
        if self.problema():
            return ""
        return montar_caminho(self.pasta(), self.nome(), self._formato.get())

    # ---- como o campo muda
    def sugerir(self, desenho):
        """O desenho mudou: nome novo, e pasta nova se a pessoa nao escolheu uma."""
        desenho = os.path.abspath(desenho)
        base = os.path.splitext(os.path.basename(desenho))[0]
        if not grava_arquivo(self._formato.get()):
            base = base.replace(".", "_")       # o nome vira pasta: sem ponto
        self.nome_var.set(base + "_qgis")
        if not self._pasta_manual:
            self._definir_pasta(os.path.dirname(desenho))

    def definir_saida(self, caminho):
        """Poe um caminho inteiro nos dois campos."""
        pasta, nome = dividir_caminho(caminho, self._formato.get())
        self._pasta_manual = True
        self._definir_pasta(pasta)
        self.nome_var.set(nome)

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Pasta onde salvar",
                                        initialdir=self.pasta() or None)
        if pasta:
            self._pasta_manual = True
            self._definir_pasta(pasta)

    def normalizar(self):
        """Arruma o que foi digitado no nome. Caminho inteiro colado ali vira pasta e
        nome; ".gpkg" no fim some (o sufixo ja esta ao lado). Chamado ao sair do campo
        e antes de converter."""
        texto = self.nome_var.get().strip()
        if "/" in texto or "\\" in texto:
            pasta, nome = dividir_caminho(texto, self._formato.get())
            if pasta and not os.path.isabs(pasta) and self.pasta():
                pasta = os.path.join(self.pasta(), pasta)
            if pasta:
                self._pasta_manual = True
                self._definir_pasta(pasta)
            texto = nome
        elif grava_arquivo(self._formato.get()):
            texto = _sem_extensao_gpkg(texto)
        if texto != self.nome_var.get():
            self.nome_var.set(texto)

    def focar_nome(self):
        self.nome_entrada.focus_set()

    # ---- por dentro
    def _definir_pasta(self, pasta):
        self.pasta_var.set(os.path.normpath(pasta) if pasta else "")
        self.after_idle(self._mostrar_o_fim_da_pasta)

    def _ajustar_a_quebra_do_aviso(self, evento):
        self.aviso.config(wraplength=max(200, evento.width - self.aviso.winfo_x() - 8))

    def _mostrar_o_fim_da_pasta(self):
        try:
            self.pasta_entrada.xview_moveto(1)
        except tk.TclError:
            pass                                # a janela ja foi fechada

    def _selecionar_o_nome(self, _evento=None):
        self.atualizar()                        # o arquivo pode ter nascido desde a ultima vez
        # depois do clique: o clique em si tira a selecao
        def selecionar():
            try:
                self.nome_entrada.selection_range(0, tk.END)
            except tk.TclError:
                pass
        self.after_idle(selecionar)

    def atualizar(self, *_):
        """Reconfere o sufixo e o aviso. Os campos avisam sozinhos quando mudam; o que
        eles nao veem e o arquivo que apareceu (ou sumiu) fora deles, por exemplo o que
        a conversao acabou de gravar: quem chama sabe, ver App._tarefa_terminou."""
        formato = self._formato.get()
        self.sufixo.config(text=EXTENSAO_GPKG if grava_arquivo(formato) else "(pasta)")
        texto, cor = self._texto_do_aviso(formato)
        self.aviso.config(text=texto, foreground=cor)

    def _texto_do_aviso(self, formato):
        if not self.pasta() and not self.nome_var.get().strip():
            return self.PRIMEIRO_USO, COR_NOTA
        problema = self.problema()
        if problema:
            return problema, COR_AVISO
        caminho = self.caminho_saida()
        if grava_arquivo(formato):
            if os.path.isfile(caminho):
                return ("Ja existe um arquivo com este nome nesta pasta: ele sera "
                        "substituido.", COR_AVISO)
            return "", COR_NOTA
        if os.path.isdir(caminho):
            return ("Ja existe a pasta \"%s\": os arquivos de mesmo nome dentro dela "
                    "serao substituidos." % self.nome(), COR_AVISO)
        return ("Cria a pasta \"%s\" com um arquivo %s para cada camada."
                % (self.nome(), ARQUIVOS_DA_PASTA.get(formato, "")), COR_NOTA)
