# -*- coding: utf-8 -*-
"""Interface grafica. Toda a logica de conversao esta em convert.py."""

import os
import queue
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import __version__, config, convert, crs_presets, dwg, dxfio
from .gui_camadas import PainelCamadas, contar_escolhidas
from .gui_saida import CampoSaida

SEM_ROTULO = "(nenhum)"
POR_CAMADA = "(usar o nome da camada de origem)"

FILTRO_VETOR = [("Todos os formatos do QGIS",
                 "*.shp *.gpkg *.geojson *.json *.gml *.tab *.kml"),
                ("Shapefile", "*.shp"), ("GeoPackage", "*.gpkg"),
                ("GeoJSON", "*.geojson *.json"), ("Todos os arquivos", "*.*")]
FILTRO_CAD = [("Desenhos do AutoCAD", "*.dxf *.dwg"),
              ("DXF", "*.dxf"), ("DWG", "*.dwg"), ("Todos os arquivos", "*.*")]


class SeletorCRS(ttk.Frame):
    """Menu de sistemas de coordenadas + campo para digitar um EPSG qualquer."""

    def __init__(self, pai, epsg_inicial=crs_presets.PADRAO, ao_mudar=None):
        super().__init__(pai)
        self.ao_mudar = ao_mudar
        self._rotulos = [texto for _, texto in crs_presets.PRESETS]
        self._codigos = [codigo for codigo, _ in crs_presets.PRESETS]

        self.combo = ttk.Combobox(self, values=self._rotulos, state="readonly", width=46)
        self.combo.grid(row=0, column=0, sticky="we")
        self.combo.bind("<<ComboboxSelected>>", self._do_combo)

        ttk.Label(self, text="  EPSG:").grid(row=0, column=1)
        self.entrada = ttk.Entry(self, width=8)
        self.entrada.grid(row=0, column=2)
        self.entrada.bind("<KeyRelease>", self._do_entrada)

        self.aviso = ttk.Label(self, text="", foreground="#b35c00")
        self.aviso.grid(row=1, column=0, columnspan=3, sticky="w")
        self.columnconfigure(0, weight=1)

        self.definir(epsg_inicial)

    def definir(self, epsg):
        if epsg is None:
            return
        epsg = int(epsg)
        self.entrada.delete(0, tk.END)
        self.entrada.insert(0, str(epsg))
        if epsg in self._codigos:
            self.combo.set(self._rotulos[self._codigos.index(epsg)])
        else:
            self.combo.set(crs_presets.rotulo(epsg))
        self._atualizar_aviso(epsg)

    def obter(self):
        try:
            return int(self.entrada.get().strip())
        except ValueError:
            return None

    def _do_combo(self, _evento=None):
        indice = self.combo.current()
        codigo = self._codigos[indice] if 0 <= indice < len(self._codigos) else None
        if codigo is None:              # linha separadora do menu
            self.definir(self.obter() or crs_presets.PADRAO)
            return
        self.definir(codigo)
        if self.ao_mudar:
            self.ao_mudar()

    def _do_entrada(self, _evento=None):
        epsg = self.obter()
        if epsg and crs_presets.valido(epsg):
            if epsg in self._codigos:
                self.combo.set(self._rotulos[self._codigos.index(epsg)])
            else:
                self.combo.set(crs_presets.rotulo(epsg))
            self._atualizar_aviso(epsg)
            if self.ao_mudar:
                self.ao_mudar()
        else:
            self.aviso.config(text="Codigo EPSG desconhecido." if epsg else "")

    def _atualizar_aviso(self, epsg):
        if not crs_presets.eh_projetado(epsg):
            self.aviso.config(
                text="Atencao: este sistema usa graus. No AutoCAD o desenho fica "
                     "minusculo e nao da para medir. Prefira um UTM.")
        else:
            self.aviso.config(text="")


class AbaQgisParaCad(ttk.Frame):
    """QGIS -> AutoCAD."""

    def __init__(self, pai, app):
        super().__init__(pai, padding=12)
        self.app = app
        self.itens = []          # dicts {'caminho', 'camada', 'campos'}
        self.columnconfigure(0, weight=1)
        linha = 0

        # ---- 1. camadas
        caixa = ttk.LabelFrame(self, text=" 1. Camadas do QGIS que serao convertidas ",
                               padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)

        self.lista = tk.Listbox(caixa, height=5, selectmode=tk.EXTENDED,
                                activestyle="none")
        self.lista.grid(row=0, column=0, sticky="we", rowspan=3)
        barra = ttk.Scrollbar(caixa, orient="vertical", command=self.lista.yview)
        barra.grid(row=0, column=1, sticky="ns", rowspan=3)
        self.lista.config(yscrollcommand=barra.set)

        ttk.Button(caixa, text="Adicionar...", command=self.adicionar, width=14
                   ).grid(row=0, column=2, padx=(8, 0), sticky="we")
        ttk.Button(caixa, text="Remover", command=self.remover, width=14
                   ).grid(row=1, column=2, padx=(8, 0), sticky="we")
        ttk.Button(caixa, text="Limpar", command=self.limpar, width=14
                   ).grid(row=2, column=2, padx=(8, 0), sticky="we")
        linha += 1

        # ---- 2. coordenadas
        caixa = ttk.LabelFrame(self, text=" 2. Sistema de coordenadas ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(1, weight=1)

        ttk.Label(caixa, text="Origem:").grid(row=0, column=0, sticky="w")
        self.rotulo_origem = ttk.Label(caixa, text="(adicione uma camada)",
                                       foreground="#555")
        self.rotulo_origem.grid(row=0, column=1, sticky="w")

        self.forcar_origem = tk.BooleanVar(value=False)
        ttk.Checkbutton(caixa, text="O arquivo nao informa - eu declaro:",
                        variable=self.forcar_origem, command=self._alternar_origem
                        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.crs_origem = SeletorCRS(caixa, crs_presets.PADRAO)
        self.crs_origem.grid(row=2, column=0, columnspan=2, sticky="we", padx=(20, 0))

        ttk.Separator(caixa, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="we", pady=8)
        ttk.Label(caixa, text="Gravar o desenho em:").grid(row=4, column=0,
                                                           columnspan=2, sticky="w")
        self.crs_destino = SeletorCRS(caixa, app.cfg["epsg_cad"])
        self.crs_destino.grid(row=5, column=0, columnspan=2, sticky="we")
        self._alternar_origem()
        linha += 1

        # ---- 3. opcoes
        caixa = ttk.LabelFrame(self, text=" 3. Como montar o desenho ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(1, weight=1)

        ttk.Label(caixa, text="Nome da camada vem de:").grid(row=0, column=0, sticky="w")
        self.combo_camada = ttk.Combobox(caixa, state="readonly", values=[POR_CAMADA])
        self.combo_camada.set(POR_CAMADA)
        self.combo_camada.grid(row=0, column=1, sticky="we", padx=(6, 0))

        ttk.Label(caixa, text="Escrever texto do campo:").grid(row=1, column=0,
                                                               sticky="w", pady=(4, 0))
        self.combo_rotulo = ttk.Combobox(caixa, state="readonly", values=[SEM_ROTULO])
        self.combo_rotulo.set(SEM_ROTULO)
        self.combo_rotulo.grid(row=1, column=1, sticky="we", padx=(6, 0), pady=(4, 0))

        ttk.Label(caixa, text="Altura do texto (unidades):").grid(row=2, column=0,
                                                                  sticky="w", pady=(4, 0))
        self.altura = ttk.Entry(caixa, width=8)
        self.altura.insert(0, "2.5")
        self.altura.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        self.somente_ascii = tk.BooleanVar(value=app.cfg["somente_ascii"])
        ttk.Checkbutton(caixa, text="Trocar acentos por letras simples "
                                    "(Secao em vez de Seção) - recomendado "
                                    "para o AutoCAD 2007",
                        variable=self.somente_ascii
                        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.salvar_csv = tk.BooleanVar(value=app.cfg["salvar_atributos_csv"])
        ttk.Checkbutton(caixa, text="Salvar a tabela de atributos num .csv ao lado "
                                    "(o DXF nao guarda atributos)",
                        variable=self.salvar_csv
                        ).grid(row=4, column=0, columnspan=2, sticky="w")
        linha += 1

        # ---- 4. saida
        caixa = ttk.LabelFrame(self, text=" 4. Salvar o desenho como ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)
        self.saida = ttk.Entry(caixa)
        self.saida.grid(row=0, column=0, sticky="we")
        ttk.Button(caixa, text="Procurar...", command=self.escolher_saida, width=14
                   ).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(caixa, text="Use .dxf (abre direto no AutoCAD 2007) ou .dwg "
                              "(precisa do ODA File Converter).",
                  foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w")
        linha += 1

        self.botao = ttk.Button(self, text="CONVERTER PARA AUTOCAD",
                                command=self.converter, style="Grande.TButton")
        self.botao.grid(row=linha, column=0, sticky="we", ipady=6)

    # -------------------------------------------------- acoes
    def _alternar_origem(self):
        estado = "normal" if self.forcar_origem.get() else "disabled"
        for filho in self.crs_origem.winfo_children():
            try:
                filho.config(state=estado)
            except tk.TclError:
                pass

    def adicionar(self):
        caminho = filedialog.askopenfilename(
            title="Escolha um arquivo do QGIS", filetypes=FILTRO_VETOR,
            initialdir=self.app.cfg.get("ultima_pasta") or None)
        if not caminho:
            return
        self.app.cfg["ultima_pasta"] = os.path.dirname(caminho)
        try:
            camadas = convert.listar_camadas(caminho)
        except convert.ErroConversao as erro:
            messagebox.showerror("Nao consegui abrir", str(erro))
            return

        escolhidas = camadas
        if len(camadas) > 1:
            escolhidas = self._perguntar_camadas(caminho, camadas)
            if not escolhidas:
                return

        for camada in escolhidas:
            try:
                epsg, campos, total, _tipo = convert.inspecionar(caminho, camada)
            except Exception as erro:
                messagebox.showerror("Nao consegui ler a camada",
                                     "Camada '%s':\n%s" % (camada, erro))
                continue
            self.itens.append({"caminho": caminho, "camada": camada,
                               "campos": campos, "epsg": epsg})
            self.lista.insert(tk.END, "%s  ::  %s   (%s feicoes)"
                              % (os.path.basename(caminho), camada,
                                 total if total is not None else "?"))
        self._atualizar_derivados()

    def _perguntar_camadas(self, caminho, camadas):
        janela = tk.Toplevel(self)
        janela.title("Camadas de %s" % os.path.basename(caminho))
        janela.transient(self.winfo_toplevel())
        janela.grab_set()
        ttk.Label(janela, text="Este arquivo tem varias camadas. Quais converter?",
                  padding=10).pack()
        lista = tk.Listbox(janela, selectmode=tk.EXTENDED, height=min(12, len(camadas)),
                           width=44)
        for camada in camadas:
            lista.insert(tk.END, camada)
        lista.select_set(0, tk.END)
        lista.pack(padx=10, fill="both", expand=True)
        resultado = []

        def confirmar():
            resultado.extend(lista.get(i) for i in lista.curselection())
            janela.destroy()

        barra = ttk.Frame(janela, padding=10)
        barra.pack()
        ttk.Button(barra, text="Adicionar", command=confirmar).pack(side="left", padx=4)
        ttk.Button(barra, text="Cancelar", command=janela.destroy).pack(side="left")
        janela.wait_window()
        return resultado

    def remover(self):
        for indice in sorted(self.lista.curselection(), reverse=True):
            self.lista.delete(indice)
            del self.itens[indice]
        self._atualizar_derivados()

    def limpar(self):
        self.lista.delete(0, tk.END)
        self.itens.clear()
        self._atualizar_derivados()

    def _atualizar_derivados(self):
        """Atualiza CRS detectado e os menus de campos a partir das camadas."""
        if not self.itens:
            self.rotulo_origem.config(text="(adicione uma camada)")
            self.combo_camada.config(values=[POR_CAMADA])
            self.combo_camada.set(POR_CAMADA)
            self.combo_rotulo.config(values=[SEM_ROTULO])
            self.combo_rotulo.set(SEM_ROTULO)
            return

        codigos = {item["epsg"] for item in self.itens}
        if codigos == {None}:
            self.rotulo_origem.config(
                text="nao informado pelo arquivo - marque a opcao abaixo",
                foreground="#b35c00")
            self.forcar_origem.set(True)
            self._alternar_origem()
        elif len(codigos - {None}) == 1:
            epsg = (codigos - {None}).pop()
            self.rotulo_origem.config(text="EPSG:%s  -  %s"
                                      % (epsg, crs_presets.rotulo(epsg)),
                                      foreground="#0a6")
        else:
            self.rotulo_origem.config(
                text="camadas em sistemas diferentes - cada uma sera reprojetada",
                foreground="#555")

        # so oferece campos presentes em TODAS as camadas, senao a conversao
        # falharia para as que nao tem o campo
        comuns = set(self.itens[0]["campos"])
        for item in self.itens[1:]:
            comuns &= set(item["campos"])
        comuns = sorted(comuns)

        anterior = self.combo_camada.get()
        self.combo_camada.config(values=[POR_CAMADA] + comuns)
        self.combo_camada.set(anterior if anterior in ([POR_CAMADA] + comuns) else POR_CAMADA)

        anterior = self.combo_rotulo.get()
        self.combo_rotulo.config(values=[SEM_ROTULO] + comuns)
        self.combo_rotulo.set(anterior if anterior in ([SEM_ROTULO] + comuns) else SEM_ROTULO)

        if not self.saida.get() and self.itens:
            base = os.path.splitext(self.itens[0]["caminho"])[0]
            self.saida.delete(0, tk.END)
            self.saida.insert(0, base + ".dxf")

    def escolher_saida(self):
        caminho = filedialog.asksaveasfilename(
            title="Salvar desenho como", defaultextension=".dxf",
            filetypes=[("AutoCAD DXF", "*.dxf"), ("AutoCAD DWG", "*.dwg")],
            initialdir=self.app.cfg.get("ultima_pasta") or None)
        if caminho:
            self.saida.delete(0, tk.END)
            self.saida.insert(0, caminho)

    def converter(self):
        if not self.itens:
            messagebox.showwarning("Faltou a entrada",
                                   "Adicione pelo menos uma camada do QGIS.")
            return
        saida = self.saida.get().strip()
        if not saida:
            messagebox.showwarning("Faltou a saida", "Escolha onde salvar o desenho.")
            return
        epsg_destino = self.crs_destino.obter()
        if not epsg_destino or not crs_presets.valido(epsg_destino):
            messagebox.showwarning("Coordenadas",
                                   "Escolha um sistema de coordenadas valido para o desenho.")
            return
        try:
            altura = float(self.altura.get().replace(",", "."))
        except ValueError:
            altura = 2.5

        campo_camada = self.combo_camada.get()
        campo_camada = None if campo_camada == POR_CAMADA else campo_camada
        campo_rotulo = self.combo_rotulo.get()
        campo_rotulo = None if campo_rotulo == SEM_ROTULO else campo_rotulo

        self.app.cfg["epsg_cad"] = epsg_destino
        self.app.cfg["somente_ascii"] = self.somente_ascii.get()
        self.app.cfg["salvar_atributos_csv"] = self.salvar_csv.get()

        entradas = [{"caminho": i["caminho"], "camada": i["camada"]} for i in self.itens]
        self.app.executar(
            self.botao,
            lambda registrar: convert.qgis_para_cad(
                entradas=entradas, saida=saida, epsg_destino=epsg_destino,
                campo_camada=campo_camada, campo_rotulo=campo_rotulo,
                epsg_origem_forcado=(self.crs_origem.obter()
                                     if self.forcar_origem.get() else None),
                somente_ascii=self.somente_ascii.get(),
                salvar_csv=self.salvar_csv.get(), altura_texto=altura,
                registrar=registrar))


class AbaCadParaQgis(ttk.Frame):
    """AutoCAD -> QGIS."""

    FORMATOS = [("GeoPackage (.gpkg) - um arquivo com todas as camadas", "GPKG"),
                ("Shapefile (.shp) - uma pasta com varios arquivos", "ESRI Shapefile"),
                ("GeoJSON (.geojson)", "GeoJSON")]

    def __init__(self, pai, app):
        super().__init__(pai, padding=12)
        self.app = app
        self.columnconfigure(0, weight=1)
        linha = 0

        caixa = ttk.LabelFrame(self, text=" 1. Desenho do AutoCAD ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)
        self.entrada = ttk.Entry(caixa)
        self.entrada.grid(row=0, column=0, sticky="we")
        ttk.Button(caixa, text="Procurar...", command=self.escolher_entrada, width=14
                   ).grid(row=0, column=1, padx=(8, 0))
        self.aviso_dwg = ttk.Label(caixa, text="", foreground="#b35c00", wraplength=600)
        self.aviso_dwg.grid(row=1, column=0, columnspan=2, sticky="w")
        self.entrada.bind("<Return>", lambda _e: self._atualizar_painel())
        self.entrada.bind("<FocusOut>", lambda _e: self._atualizar_painel())
        self.escolher_camadas = tk.BooleanVar(value=False)
        ttk.Checkbutton(caixa, text="Escolher as camadas que vao para a conversao "
                                    "(mostra o desenho ao lado)",
                        variable=self.escolher_camadas, command=self._alternar_camadas
                        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        linha += 1

        caixa = ttk.LabelFrame(self, text=" 2. Em que coordenadas o desenho esta ",
                               padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)
        ttk.Label(caixa, text="O DXF nao guarda essa informacao, entao ela precisa "
                              "ser declarada:", foreground="#555"
                  ).grid(row=0, column=0, sticky="w")
        self.crs_origem = SeletorCRS(caixa, app.cfg["epsg_cad"])
        self.crs_origem.grid(row=1, column=0, sticky="we")
        self.rotulo_detectado = ttk.Label(caixa, text="", foreground="#0a6")
        self.rotulo_detectado.grid(row=2, column=0, sticky="w")
        linha += 1

        caixa = ttk.LabelFrame(self, text=" 3. Formato de saida ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)
        self.formato = tk.StringVar(value=app.cfg["formato_saida"])
        for i, (texto, valor) in enumerate(self.FORMATOS):
            ttk.Radiobutton(caixa, text=texto, value=valor, variable=self.formato
                            ).grid(row=i, column=0, sticky="w")

        ttk.Separator(caixa, orient="horizontal").grid(row=9, column=0, sticky="we", pady=8)

        self.separar = tk.BooleanVar(value=app.cfg["separar_por_camada"])
        ttk.Checkbutton(caixa, text="Criar uma camada do QGIS para cada camada do "
                                    "AutoCAD", variable=self.separar
                        ).grid(row=12, column=0, sticky="w", pady=(6, 0))
        self.fechadas = tk.BooleanVar(value=app.cfg["polilinha_fechada_vira_area"])
        ttk.Checkbutton(caixa, text="Transformar polilinhas fechadas em areas "
                                    "(para calcular area; deixe desmarcado se "
                                    "forem curvas de nivel)", variable=self.fechadas
                        ).grid(row=13, column=0, sticky="w")
        self.sem_textos = tk.BooleanVar(value=app.cfg["sem_textos_e_hachuras"])
        ttk.Checkbutton(caixa, text="Nao levar textos nem hachuras (juntando as camadas "
                                    "em um arquivo por tipo, saem so pontos, linhas e areas)",
                        variable=self.sem_textos).grid(row=17, column=0, sticky="w")
        self.imagens = tk.BooleanVar(value=app.cfg["incluir_imagens"])
        ttk.Checkbutton(caixa, text="Trazer as imagens do desenho (tabelas coladas, "
                                    "logotipos, fotos ligadas que estejam na pasta do "
                                    "desenho)", variable=self.imagens
                        ).grid(row=16, column=0, sticky="w")

        self.gerar_projeto = tk.BooleanVar(value=app.cfg["gerar_projeto_qgis"])
        ttk.Checkbutton(caixa, text="Criar tambem um projeto .qgs que abre com "
                                    "dois cliques", variable=self.gerar_projeto
                        ).grid(row=14, column=0, sticky="w")
        ttk.Label(caixa, text="Sem o projeto, arraste o arquivo para a janela do QGIS: "
                              "vem tudo, inclusive as imagens (Camada > Adicionar "
                              "Camada Vetorial nao traz as imagens).",
                  foreground="#555", wraplength=620
                  ).grid(row=15, column=0, sticky="w", padx=(20, 0))
        linha += 1

        caixa = ttk.LabelFrame(self, text=" 4. Onde salvar ", padding=8)
        caixa.grid(row=linha, column=0, sticky="we", pady=(0, 8))
        caixa.columnconfigure(0, weight=1)
        # a pasta e o nome em campos separados: trocar o nome nao obriga a achar onde ele
        # comeca no meio do caminho (ver gui_saida)
        self.saida = CampoSaida(caixa, self.formato)
        self.saida.grid(row=0, column=0, sticky="we")
        # a conversao grava o arquivo sem escrever em campo nenhum: o aviso "ja existe,
        # sera substituido" so sabe disso se a janela avisar que a tarefa terminou
        self.bind("<<TarefaTerminou>>", lambda _e: self.saida.atualizar())
        linha += 1

        self.botao = ttk.Button(self, text="CONVERTER PARA QGIS",
                                command=self.converter, style="Grande.TButton")
        self.botao.grid(row=linha, column=0, sticky="we", ipady=6)
        # uma linha vazia embaixo dos passos fica com a altura que sobra na aba: os passos
        # ficam juntos em cima e o painel ao lado (que ocupa ate ela) vai ate embaixo. Sem
        # ela o painel parava na altura dos passos, e ampliado ficava com 300 pixels. Com o
        # desenho aberto, o quadro "O que aconteceu" mora nela (ver App.registro_ao_lado)
        self.rowconfigure(linha + 1, weight=1)
        self.linha_do_registro = linha + 1
        self._linhas = linha + 2

        # a lista de camadas com o desenho: so entra na janela quando a pessoa pede
        self.painel = PainelCamadas(self, ao_registrar=app.registrar,
                                    ao_ampliar=self._ao_ampliar)
        self._geometria_antes = None
        self._formulario = ()
        self._maximizei = False

    def _alternar_camadas(self):
        # com o desenho ao lado, o quadro "O que aconteceu" vai para baixo dos passos e o
        # desenho fica com a altura toda da janela
        registro_ao_lado = getattr(self.app, "registro_ao_lado", lambda _aba: None)
        if self.escolher_camadas.get():
            self.painel.grid(row=0, column=1, rowspan=self._linhas, sticky="nsew",
                             padx=(12, 0))
            self.columnconfigure(1, weight=1, minsize=600)
            registro_ao_lado(self)
            self._ajustar_janela(True)
            self._atualizar_painel()
        else:
            self.painel.ampliar(False)          # os passos voltam antes do painel sair
            self.painel.grid_remove()
            self.columnconfigure(1, weight=0, minsize=0)
            registro_ao_lado(None)
            self._ajustar_janela(False)

    def _ao_ampliar(self, ligado):
        """O desenho ampliado ocupa a janela: os passos da conversao e o quadro "O que
        aconteceu" saem da frente e a janela maximiza. Ao voltar, tudo volta como estava
        (a janela so sai do maximizado se fui eu que maximizei)."""
        topo = self.winfo_toplevel()
        mostrar_registro = getattr(self.app, "mostrar_registro", None)
        if ligado:
            # so os passos (o quadro "O que aconteceu", que pode estar nesta coluna, e da
            # janela: mostrar_registro cuida dele)
            self._formulario = [w for w in self.grid_slaves(column=0) if w.master is self]
            for parte in self._formulario:
                parte.grid_remove()
            self.columnconfigure(0, weight=0)
            self.painel.grid_configure(padx=0)
            if mostrar_registro:
                mostrar_registro(False)
            # janela escondida (os testes) nao pode aparecer por causa disto
            self._maximizei = False
            try:
                if topo.winfo_viewable() and topo.state() == "normal":
                    topo.state("zoomed")
                    self._maximizei = True
            except tk.TclError:
                pass
        else:
            for parte in self._formulario:
                parte.grid()
            self._formulario = ()
            self.columnconfigure(0, weight=1)
            self.painel.grid_configure(padx=(12, 0))
            if mostrar_registro:
                mostrar_registro(True)
            if self._maximizei:
                self._maximizei = False
                try:
                    topo.state("normal")
                except tk.TclError:
                    pass

    def _ajustar_janela(self, com_painel):
        """Alarga a janela para caber o painel e volta ao tamanho de antes ao fechar.
        Janela maximizada ja tem espaco: nao mexe."""
        topo = self.winfo_toplevel()
        try:
            if topo.state() == "zoomed":
                return
        except tk.TclError:
            return
        tela_l, tela_a = topo.winfo_screenwidth(), topo.winfo_screenheight()
        if com_painel:
            self._geometria_antes = (topo.winfo_width(), topo.winfo_height())
            topo.minsize(min(1180, tela_l - 40), 700)
            topo.geometry("%dx%d" % (min(max(topo.winfo_width(), 1400), tela_l - 40),
                                     min(max(topo.winfo_height(), 960), tela_a - 80)))
        else:
            topo.minsize(700, 700)
            if self._geometria_antes and self._geometria_antes[0] > 1:
                topo.geometry("%dx%d" % self._geometria_antes)

    def _atualizar_painel(self):
        """Faz o painel mostrar o desenho que esta no campo do passo 1."""
        if not self.escolher_camadas.get():
            return
        caminho = self.entrada.get().strip()
        if not caminho or not os.path.isfile(caminho):
            if self.painel.estado != "vazio":
                self.painel.limpar()
            return
        if caminho == self.painel.caminho and self.painel.estado != "vazio":
            return                      # ja esta mostrando (ou lendo) este
        epsg = self.crs_origem.obter()
        self.painel.unidade_em_metros = (crs_presets.eh_projetado(epsg)
                                         if epsg and crs_presets.valido(epsg) else True)
        self.painel.carregar(caminho)

    def escolher_entrada(self):
        caminho = filedialog.askopenfilename(
            title="Escolha o desenho do AutoCAD", filetypes=FILTRO_CAD,
            initialdir=self.app.cfg.get("ultima_pasta") or None)
        if not caminho:
            return
        self.app.cfg["ultima_pasta"] = os.path.dirname(caminho)
        self.entrada.delete(0, tk.END)
        self.entrada.insert(0, caminho)

        if caminho.lower().endswith(".dwg") and not dwg.disponivel():
            self.aviso_dwg.config(
                text="Este e um arquivo .dwg e o ODA File Converter nao esta "
                     "instalado. Clique em CONVERTER para ver como instalar, ou "
                     "salve o desenho como .dxf no AutoCAD.")
        else:
            self.aviso_dwg.config(text="")

        epsg = dxfio.ler_crs_acompanhante(caminho)
        if epsg:
            self.crs_origem.definir(epsg)
            self.rotulo_detectado.config(
                text="Sistema encontrado num arquivo ao lado do desenho: EPSG:%s" % epsg)
        else:
            self.rotulo_detectado.config(text="")
        self.saida.sugerir(caminho)
        self._atualizar_painel()

    def converter(self):
        entrada = self.entrada.get().strip()
        if not entrada or not os.path.exists(entrada):
            messagebox.showwarning("Faltou a entrada",
                                   "Escolha um arquivo .dxf ou .dwg do AutoCAD.")
            return
        # o clique em CONVERTER nao tira o foco do campo do nome: arruma o que foi colado
        self.saida.normalizar()
        problema = self.saida.problema()
        if problema:
            messagebox.showwarning("Onde salvar", problema)
            self.saida.focar_nome()
            return
        saida = self.saida.caminho_saida()
        epsg_origem = self.crs_origem.obter()
        if not epsg_origem or not crs_presets.valido(epsg_origem):
            messagebox.showwarning("Coordenadas",
                                   "Escolha o sistema de coordenadas do desenho.")
            return

        if entrada.lower().endswith(".dwg") and not dwg.disponivel():
            if messagebox.askyesno("Arquivo .dwg",
                                   dwg.MENSAGEM_AUSENTE +
                                   "\n\nAbrir a pagina de download agora?"):
                webbrowser.open(dwg.LINK_DOWNLOAD)
            return

        camadas = caixa = dxf_pronto = cores = separar_por_cor = feicoes = None
        n_linhas = n_textos = 0
        if self.escolher_camadas.get():
            if not (self.painel.pronto and self.painel.caminho == entrada):
                messagebox.showwarning(
                    "Camadas",
                    "Aguarde: o programa ainda nao terminou de ler as camadas do desenho.\n\n"
                    "Quando a lista aparecer ao lado, marque as camadas e converta de novo. "
                    "Para converter tudo, desmarque \"Escolher as camadas\".")
                return
            escolha = self.painel.selecao()
            if not escolha["camadas"] and not escolha["feicoes"]:
                messagebox.showwarning(
                    "Nenhuma camada marcada",
                    "Marque na lista, ao lado, ao menos uma camada para converter, ou clique "
                    "numa linha do desenho (ou num texto).")
                return
            camadas, caixa, dxf_pronto = escolha["camadas"], escolha["caixa"], escolha["dxf"]
            cores, separar_por_cor = escolha["cores"], escolha["separar_por_cor"]
            feicoes, n_linhas = escolha["feicoes"], escolha["linhas"]
            n_textos = escolha.get("textos", 0)

        self.app.cfg["epsg_cad"] = epsg_origem
        self.app.cfg["formato_saida"] = self.formato.get()
        self.app.cfg["separar_por_camada"] = self.separar.get()
        self.app.cfg["polilinha_fechada_vira_area"] = self.fechadas.get()
        self.app.cfg["sem_textos_e_hachuras"] = self.sem_textos.get()
        self.app.cfg["gerar_projeto_qgis"] = self.gerar_projeto.get()
        self.app.cfg["incluir_imagens"] = self.imagens.get()

        painel = self.painel
        # Enquanto converte, o DXF temporario do painel nao pode ser apagado. A
        # protecao comeca ja aqui, no clique: se so comecasse na thread, trocar
        # de desenho antes de ela iniciar apagaria o arquivo que ela vai usar.
        painel.em_uso += 1

        def tarefa(registrar):
            try:
                if camadas:
                    registrar("%d camadas escolhidas na lista." % len(camadas))
                if n_linhas or n_textos:
                    registrar("%s no desenho." % contar_escolhidas(n_linhas, n_textos))
                if n_textos and self.sem_textos.get():
                    registrar("Aviso: %s no desenho ficam de fora, porque a opcao \"Nao levar "
                              "textos nem hachuras\" esta marcada."
                              % ("o texto escolhido" if n_textos == 1
                                 else "os %d textos escolhidos" % n_textos))
                return convert.cad_para_qgis(
                    entrada=entrada, saida=saida, epsg_origem=epsg_origem,
                    formato=self.formato.get(),
                    separar_por_camada=self.separar.get(),
                    poli_fechada_como_poligono=self.fechadas.get(),
                    gerar_projeto=self.gerar_projeto.get(),
                    incluir_imagens=self.imagens.get(),
                    camadas=camadas, descartar_fora_da_caixa=caixa,
                    dxf_pronto=dxf_pronto, cores=cores, separar_por_cor=separar_por_cor,
                    sem_textos_e_hachuras=self.sem_textos.get(),
                    feicoes_escolhidas=feicoes, registrar=registrar)
            finally:
                painel.em_uso -= 1

        try:
            self.app.executar(self.botao, tarefa)
        except Exception:
            painel.em_uso -= 1            # a thread nem chegou a existir
            raise


class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Conversor QGIS ↔ AutoCAD   v%s" % __version__)
        self.geometry("760x900")
        self.minsize(700, 700)
        self.cfg = config.carregar()
        self.fila = queue.Queue()

        estilo = ttk.Style(self)
        try:
            estilo.theme_use("vista")
        except tk.TclError:
            pass
        estilo.configure("Grande.TButton", font=("Segoe UI", 11, "bold"))

        abas = self._abas = ttk.Notebook(self)
        abas.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.aba1 = AbaQgisParaCad(abas, self)
        self.aba2 = AbaCadParaQgis(abas, self)
        abas.add(self.aba1, text="   QGIS  →  AutoCAD   ")
        abas.add(self.aba2, text="   AutoCAD  →  QGIS   ")

        caixa = self._caixa_do_registro = ttk.LabelFrame(self, text=" O que aconteceu ",
                                                         padding=6)
        self._registro_visivel = True
        self._registro_na_aba = None         # a aba com o desenho aberto (ver registro_ao_lado)
        self._posicionar_registro()
        abas.bind("<<NotebookTabChanged>>", lambda _e: self._posicionar_registro())
        self.log = tk.Text(caixa, height=9, wrap="word", state="disabled",
                           font=("Consolas", 9), background="#f7f7f7")
        self.log.pack(side="left", fill="both", expand=True)
        barra = ttk.Scrollbar(caixa, orient="vertical", command=self.log.yview)
        barra.pack(side="right", fill="y")
        self.log.config(yscrollcommand=barra.set)

        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.after(100, self._drenar)
        self.registrar("Pronto. O DXF funciona sem instalar mais nada; "
                       ".dwg precisa do ODA File Converter (%s)."
                       % ("instalado" if dwg.disponivel() else "nao instalado"))

    def mostrar_registro(self, mostrar):
        """Mostra ou esconde o quadro "O que aconteceu" (o desenho ampliado usa o espaco)."""
        self._registro_visivel = bool(mostrar)
        self._posicionar_registro()

    def registro_ao_lado(self, aba):
        """Com o desenho aberto ao lado dos passos da `aba`, o quadro "O que aconteceu" sai de
        baixo das abas (onde ocupava a largura toda) e vai para baixo dos passos, na coluna
        deles, onde sobrava espaco: o desenho fica com a altura toda da janela. Na outra aba,
        ou com None (desenho fechado), ele volta para baixo das abas."""
        self._registro_na_aba = aba
        self._posicionar_registro()

    def _posicionar_registro(self):
        caixa = self._caixa_do_registro
        caixa.pack_forget()
        caixa.grid_forget()
        if not self._registro_visivel:
            return
        aba = self._registro_na_aba
        if aba is not None and str(self._abas.select()) == str(aba):
            caixa.grid(in_=aba, row=aba.linha_do_registro, column=0, sticky="nsew",
                       pady=(4, 0))
            caixa.lift()
        else:
            caixa.pack(fill="both", expand=False, padx=8, pady=8)

    def registrar(self, texto):
        self.log.config(state="normal")
        self.log.insert(tk.END, str(texto) + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def _drenar(self):
        """Traz para a interface as mensagens produzidas pela thread de conversao."""
        try:
            while True:
                tipo, carga = self.fila.get_nowait()
                if tipo == "log":
                    self.registrar(carga)
                elif tipo == "fim":
                    botao, resultado = carga
                    botao.config(state="normal")
                    self.config(cursor="")
                    self._tarefa_terminou()
                    self._avisar_sucesso(resultado)
                elif tipo == "erro":
                    botao, mensagem = carga
                    botao.config(state="normal")
                    self.config(cursor="")
                    self._tarefa_terminou()
                    self.registrar("ERRO: " + mensagem)
                    messagebox.showerror("Nao deu certo", mensagem)
        except queue.Empty:
            pass
        self.after(100, self._drenar)

    def _tarefa_terminou(self):
        """A conversao acabou, bem ou mal, e pode ter gravado arquivos: as abas conferem de
        novo o que mostram deles. Antes da caixa de "Concluido", que espera resposta."""
        for aba in (self.aba1, self.aba2):
            aba.event_generate("<<TarefaTerminou>>")

    def _avisar_sucesso(self, resultado):
        arquivos = resultado.get("arquivos", [])
        self.registrar("Pronto! %d feicoes convertidas." % resultado.get("feicoes", 0))
        for caminho in arquivos:
            self.registrar("  -> " + caminho)
        pasta = os.path.dirname(arquivos[0]) if arquivos else None
        mensagem = "Conversao concluida: %d feicoes.\n\n%s" % (
            resultado.get("feicoes", 0),
            "\n".join(os.path.basename(a) for a in arquivos[:8]))

        projeto = resultado.get("projeto")
        if projeto:
            mensagem += ("\n\nPara ver no QGIS, de dois cliques em:\n   %s"
                         % os.path.basename(projeto))
            pasta = os.path.dirname(projeto)
        elif arquivos and not arquivos[0].lower().endswith((".dxf", ".dwg")):
            mensagem += ("\n\nNo QGIS, arraste o arquivo para a janela do QGIS: vem "
                         "tudo, inclusive as imagens.\n(Camada > Adicionar Camada > "
                         "Adicionar Camada Vetorial nao traz as imagens.)\nO menu "
                         "'Abrir Projeto' NAO serve para dados - ele so aceita .qgs "
                         "e .qgz.")

        if pasta and messagebox.askyesno("Concluido", mensagem + "\n\nAbrir a pasta?"):
            try:
                os.startfile(pasta)
            except Exception:
                pass

    def executar(self, botao, tarefa):
        """Roda a conversao numa thread para a janela nao travar."""
        botao.config(state="disabled")
        self.config(cursor="watch")
        self.registrar("-" * 60)

        def registrar(texto):
            self.fila.put(("log", texto))

        def trabalhar():
            try:
                resultado = tarefa(registrar)
                self.fila.put(("fim", (botao, resultado)))
            except convert.ErroConversao as erro:
                self.fila.put(("erro", (botao, str(erro))))
            except Exception as erro:
                self.fila.put(("erro", (botao, "%s\n\n%s" % (erro, traceback.format_exc()))))

        threading.Thread(target=trabalhar, daemon=True).start()

    def fechar(self):
        config.salvar(self.cfg)
        self.aba2.painel.liberar(forcar=True)      # copias do DWG que o ODA deixou
        self.destroy()


def main():
    App().mainloop()
