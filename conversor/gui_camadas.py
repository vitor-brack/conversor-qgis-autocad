# -*- coding: utf-8 -*-
"""
O painel de camadas: uma lista com caixas de marcar e, ao lado, o desenho.

O desenho aparece como o AutoCAD do pai mostra (fundo branco, as cores do desenho,
as hachuras pintadas, o tracejado das linhas, so as camadas ligadas -- as desligadas
so entram se a caixinha pedir). Marcar uma
camada e escolher o que vai para a conversao: as marcadas ficam em negrito, na
mesma cor (a cor do CAD significa algo e nao pode mudar). Clicar numa linha do
desenho escolhe so aquela linha (as pecas que se encostam pelas pontas, ver
previa.Grupo), sem levar a camada nem a cor inteira; segurando Ctrl, soma outras.
Escolher a camada inteira e na caixa da lista. As duas coisas somam na conversao.

A lista tem uma linha por camada, com as amostras das cores dela; a camada de mais de
uma cor abre uma linha por cor (no desenho real, quase tudo estava na camada 0 e o
desenhista diferenciou pela cor). A caixa de cada linha diz o que vai dela: tudo, uma
parte (algumas cores, ou linhas e textos clicados no desenho) ou nada; a coluna "Na
conversao" diz qual parte. A opcao "Na saida, uma camada do QGIS para cada cor" so muda
como a conversao grava, e nao mexe na lista.

A logica de ler e desenhar esta em previa.py e previa_raster.py; aqui so tem
interface.

Estados do painel (`estado`):
  vazio         nenhum desenho escolhido ainda: diz o que fazer
  carregando    lendo o arquivo, em segundo plano (o DWG passa pelo ODA)
  erro          nao abriu: explica e oferece tentar de novo
  sem_geometria abriu, mas so tem texto ou hachura
  pronto        lista e desenho

A leitura roda numa thread que nunca mexe no Tk: ela deixa o resultado numa
fila e o painel o recolhe com `after`.
"""
import collections
import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import convert, dwg, dxf_estilo, previa, previa_raster as pr

LARGURA, ALTURA = 560, 300
MARGEM_DO_VER_TUDO = 16                          # pixels de folga em volta do "Ver tudo"
MAX_AMOSTRAS = 3                                # amostras de cor ao lado da caixa da camada
COR_DA_MARCA = "#0067c0"                        # a caixa marcada: o azul do Windows 11
FATOR_DO_ZOOM = 1.25
LIMITE_DO_CLIQUE = 4                            # pixels: abaixo disto o arrasto e um clique
RAIO_DO_CLIQUE = 6                              # pixels: a linha mais perto que isto e a clicada
FOLGA_DO_TEXTO = 2                              # pixels em volta da caixa do texto que ainda o escolhem
CONTROL = 0x0004                                # bit do Ctrl em event.state


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def contar_escolhidas(linhas, textos):
    """"1 linha escolhida", "2 textos escolhidos", "1 linha e 1 texto escolhidos"..."""
    partes = []
    if linhas:
        partes.append("%d %s" % (linhas, "linha" if linhas == 1 else "linhas"))
    if textos:
        partes.append("%d %s" % (textos, "texto" if textos == 1 else "textos"))
    genero = "escolhida" if not textos else "escolhido"
    return "%s %s%s" % (" e ".join(partes), genero, "s" if linhas + textos > 1 else "")


def _misturar(cor, outra, quanto):
    """A cor `cor` levada `quanto` (0 a 1) na direcao de `outra`."""
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(outra[i:i + 2], 16) for i in (1, 3, 5)]
    return _hex(int(round(x + (y - x) * quanto)) for x, y in zip(a, b))


class _Fotos:
    """As imagens da coluna da camada: a caixa de marcar, com os tres estados, e as amostras
    das cores, desenhadas pixel a pixel no tamanho da tela (o glifo da fonte saia miudo e
    quase do tamanho da amostra, e as duas coisas se confundiam)."""

    def __init__(self, mestre):
        self.mestre = mestre
        try:
            escala = float(mestre.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except (tk.TclError, ValueError):
            escala = 1.0
        escala = max(escala, 1.0)
        self.lado = int(round(13 * escala))
        self.amostra = int(round(10 * escala))
        self.vao = max(2, int(round(3 * escala)))
        self.entre = int(round(8 * escala))
        self._guardadas = {}

    def desenhar(self, estado, cores, ativa=True, lugares=MAX_AMOSTRAS):
        """A imagem da caixa no `estado` ("marcada", "parcial", "vazia"; `ativa` falso: nao
        ha o que levar) com as `cores` ao lado, em `lugares` lugares (a largura e sempre a
        mesma, para os nomes ficarem alinhados)."""
        chave = (estado, tuple(cores), bool(ativa), lugares)
        foto = self._guardadas.get(chave)
        if foto is None:
            foto = self._guardadas[chave] = self._nova(estado, cores, ativa, lugares)
        return foto

    def _nova(self, estado, cores, ativa, lugares):
        lado, amostra = self.lado, self.amostra
        largura = lado + self.entre + lugares * (amostra + self.vao) - self.vao
        foto = tk.PhotoImage(master=self.mestre, width=largura, height=lado)
        self._caixa(foto, estado, ativa)
        x, y = lado + self.entre, (lado - amostra) // 2
        for cor in list(cores)[:lugares]:
            foto.put(_misturar(cor, "#000000", 0.35), to=(x, y, x + amostra, y + amostra))
            foto.put(cor, to=(x + 1, y + 1, x + amostra - 1, y + amostra - 1))
            x += amostra + self.vao
        return foto

    def _caixa(self, foto, estado, ativa):
        s = self.lado
        if not ativa:
            borda, fundo = "#c6c6c6", "#f3f3f3"
        elif estado == "vazia":
            borda, fundo = "#858585", "#ffffff"
        else:
            borda = fundo = COR_DA_MARCA
        foto.put(borda, to=(0, 0, s, s))
        foto.put(fundo, to=(1, 1, s - 1, s - 1))
        for x, y in ((0, 0), (s - 1, 0), (0, s - 1), (s - 1, s - 1)):
            foto.transparency_set(x, y, True)              # os cantos arredondados
        if not ativa:
            return
        grossura = max(2, int(round(s / 6.5)))
        if estado == "marcada":
            self._risco(foto, ((0.24, 0.52), (0.42, 0.70), (0.76, 0.30)), max(1.6, s / 7.0))
        elif estado == "parcial":
            topo = (s - grossura) // 2
            foto.put("#ffffff", to=(int(s * 0.25), topo, s - int(s * 0.25), topo + grossura))

    def _risco(self, foto, pontos, grossura):
        """O visto, em branco sobre o azul: a linha pelos `pontos` (fracoes do lado da caixa),
        com a borda suave (cada pixel leva o tanto de branco que o traco cobre dele)."""
        s = self.lado
        segmentos = [((x0 * s, y0 * s), (x1 * s, y1 * s))
                     for (x0, y0), (x1, y1) in zip(pontos, pontos[1:])]
        meia = grossura / 2.0
        for py in range(1, s - 1):
            for px in range(1, s - 1):
                c = (px + 0.5, py + 0.5)
                d = min(_distancia(c, a, b) for a, b in segmentos)
                cobre = min(1.0, max(0.0, meia + 0.5 - d))
                if cobre > 0:
                    foto.put(_misturar(COR_DA_MARCA, "#ffffff", cobre), (px, py))


def _distancia(p, a, b):
    """A distancia do ponto p ao segmento a-b."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / float(dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    return ((p[0] - ax - t * dx) ** 2 + (p[1] - ay - t * dy) ** 2) ** 0.5


class PainelCamadas(ttk.LabelFrame):

    def __init__(self, pai, ao_registrar=None, ao_ampliar=None):
        super().__init__(pai, text=" Camadas que vao para a conversao ", padding=8)
        self.ao_registrar = ao_registrar or (lambda _texto: None)
        # quem esta em volta abre espaco para o desenho grande (ver ampliar)
        self.ao_ampliar = ao_ampliar or (lambda _ligado: None)
        self.ampliado = False
        self._esc = None
        # o que a pessoa pediu para ver: (caixa do desenho, margem em pixels). Vem do "Ver
        # tudo" ou de onde o zoom e o arrasto pararam; quando a tela muda de tamanho, e isso
        # que se enquadra de novo (a vista de antes nao: ir e voltar a encolheria)
        self._regiao = None
        self.estado = "vazio"
        self.previa = None
        self.dxf_pronto = None
        self.cores_marcadas = set()          # (camada, cor) marcadas na lista
        self.escolhidas = set()              # ids de grupo (previa.Grupo): linhas clicadas
        self.destaque = None                 # a linha escolhida na lista: camada ou (camada, cor)
        self.vista = None
        self.ids = None
        self.imagem = None                   # a ultima imagem desenhada
        self.indice = {}
        self.unidade_em_metros = True
        self.em_uso = 0                      # conversoes usando o DXF temporario
        self._caminho = None
        self._token = 0
        self._fila = queue.Queue()
        self._pendentes = []                 # pastas temporarias do ODA a apagar
        self._iid = {}                       # chave (camada ou (camada, cor)) -> linha da lista
        self._nome_de = {}
        self._camadas = {}                   # chave -> previa.Camada ou previa.Unidade
        self._unidades_de = {}               # camada -> [previa.Unidade]
        self._nome_cor = {}
        self._abertas = set()                # camadas com as cores abertas na lista
        self._fotos = _Fotos(self)
        self._silencio = False
        self._sem_aviso_de_ocultas = False
        self._depois_render = None
        self._depois_fila = None
        self._arrasto = None
        self._foto = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.mensagem_de_estado = tk.StringVar()
        self.resumo = tk.StringVar()
        self.detalhe = tk.StringVar()
        self.aviso_busca = tk.StringVar()
        self.aviso_fora = tk.StringVar()
        self.ignorar_fora = tk.BooleanVar(value=True)
        self.mostrar_ocultas = tk.BooleanVar(value=False)
        self.separar_por_cor = tk.BooleanVar(value=False)
        self.busca = tk.StringVar()

        self._montar_estado()
        self._montar_corpo()
        self.mostrar_ocultas.trace_add("write", self._ao_alternar_ocultas)
        self.limpar()

    # ------------------------------------------------------------------
    # montagem
    def _montar_estado(self):
        self.quadro_estado = ttk.Frame(self)
        self.quadro_estado.columnconfigure(0, weight=1)
        self.rotulo_estado = ttk.Label(self.quadro_estado, textvariable=self.mensagem_de_estado,
                                       wraplength=440, justify="center", anchor="center")
        self.rotulo_estado.grid(row=0, column=0, pady=(60, 8), padx=20)
        self.progresso = ttk.Progressbar(self.quadro_estado, mode="indeterminate", length=240)
        self.botao_repetir = ttk.Button(self.quadro_estado, text="Tentar de novo",
                                        command=self._tentar_de_novo)

    def _montar_corpo(self):
        c = self.corpo = ttk.Frame(self)
        c.columnconfigure(0, weight=1)
        # a lista fica com as linhas dela (tem barra de rolagem); a altura que sobra na
        # janela vai toda para o desenho
        c.rowconfigure(1, weight=0)
        c.rowconfigure(7, weight=1)

        barra = ttk.Frame(c)
        barra.grid(row=0, column=0, sticky="we")
        barra.columnconfigure(1, weight=1)
        ttk.Label(barra, text="Buscar camada:").grid(row=0, column=0, padx=(0, 6))
        self.campo_busca = ttk.Entry(barra, textvariable=self.busca)
        self.campo_busca.grid(row=0, column=1, sticky="we")
        self.busca.trace_add("write", lambda *_: self.filtrar(self.busca.get(), _do_campo=True))
        ttk.Button(barra, text="Limpar", width=7,
                   command=lambda: self.filtrar("")).grid(row=0, column=2, padx=(4, 16))
        ttk.Button(barra, text="Marcar todas", command=self.marcar_todas
                   ).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(barra, text="Desmarcar todas", command=self.desmarcar_todas
                   ).grid(row=0, column=4)

        quadro = ttk.Frame(c)
        quadro.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        quadro.columnconfigure(0, weight=1)
        quadro.rowconfigure(0, weight=1)
        fonte = tkfont.nametofont("TkDefaultFont")
        negrito = fonte.copy()
        negrito.configure(weight="bold")
        self._negrito = negrito                      # o Tk perde a fonte se o Python a descarta
        estilo = ttk.Style(self)
        # linhas mais altas que o padrao do Windows: a caixa e as amostras respiram
        estilo.configure("Camadas.Treeview",
                         rowheight=max(fonte.metrics("linespace"), self._fotos.lado) + 9)
        self.arvore = ttk.Treeview(quadro, columns=("conteudo", "vai"), style="Camadas.Treeview",
                                   show="tree headings", height=8, selectmode="browse")
        self.arvore.heading("#0", text="Camada", anchor="w")
        self.arvore.heading("conteudo", text="O que tem", anchor="w")
        self.arvore.heading("vai", text="Na conversao", anchor="w")
        self.arvore.column("#0", width=250, minwidth=160, stretch=True)
        self.arvore.column("conteudo", width=170, minwidth=110, stretch=True)
        self.arvore.column("vai", width=140, minwidth=90, stretch=False)
        self.arvore.tag_configure("apagada", foreground="#8a8a8a")
        self.arvore.tag_configure("marcada", font=negrito)
        self.arvore.grid(row=0, column=0, sticky="nsew")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.arvore.config(yscrollcommand=rolagem.set)
        self.arvore.bind("<Button-1>", self._clique_na_lista)
        self.arvore.bind("<<TreeviewSelect>>", self._ao_selecionar)
        self.arvore.bind("<space>", self._espaco)

        # so aparece quando a busca nao acha nada
        self.rotulo_busca = ttk.Label(c, textvariable=self.aviso_busca, foreground="#555")
        self.rotulo_busca.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.rotulo_busca.grid_remove()

        opcoes = ttk.Frame(c)
        opcoes.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opcoes, text="Mostrar camadas desligadas no AutoCAD",
                        variable=self.mostrar_ocultas).grid(row=0, column=0, padx=(0, 18))
        ttk.Checkbutton(opcoes, text="Na saida, uma camada do QGIS para cada cor",
                        variable=self.separar_por_cor).grid(row=0, column=1)
        # o que sai da frente quando o desenho e ampliado
        self._partes_da_lista = (barra, quadro, opcoes)

        ttk.Label(c, textvariable=self.resumo, wraplength=560, justify="left"
                  ).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Label(c, textvariable=self.detalhe, wraplength=560, justify="left",
                  foreground="#555").grid(row=5, column=0, sticky="w", pady=(2, 6))

        ferramentas = ttk.Frame(c)
        ferramentas.grid(row=6, column=0, sticky="we")
        ttk.Button(ferramentas, text="Ver tudo", width=9, command=self.ver_tudo
                   ).grid(row=0, column=0)
        self.botao_ampliar = ttk.Button(ferramentas, text="Ampliar desenho",
                                        command=self.alternar_ampliado)
        self.botao_ampliar.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(ferramentas, foreground="#555",
                  text="Roda: zoom  ·  Arrastar: mover  ·  Clique: escolhe a linha ou o texto  ·  "
                       "Ctrl+clique: soma"
                  ).grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.tela = tk.Canvas(c, width=LARGURA, height=ALTURA, background=_hex(pr.FUNDO),
                              highlightthickness=1, highlightbackground="#555", takefocus=True)
        self.tela.grid(row=7, column=0, sticky="nsew", pady=(4, 0))
        self._item = self.tela.create_image(0, 0, anchor="nw")
        self._texto = self.tela.create_text(LARGURA / 2, ALTURA / 2, fill="#9aa0a6", text="",
                                            width=LARGURA - 60, justify="center",
                                            font=("Segoe UI", 10))
        self.tela.bind("<Configure>", self._ao_redimensionar)
        self.tela.bind("<MouseWheel>", self._roda)
        self.tela.bind("<ButtonPress-1>", self._apertou)
        self.tela.bind("<B1-Motion>", self._arrastou)
        self.tela.bind("<ButtonRelease-1>", self._soltou)
        for tecla in ("<plus>", "<equal>", "<KP_Add>"):
            self.tela.bind(tecla, lambda e: self._zoom_no_centro(FATOR_DO_ZOOM))
        for tecla in ("<minus>", "<KP_Subtract>"):
            self.tela.bind(tecla, lambda e: self._zoom_no_centro(1 / FATOR_DO_ZOOM))
        self.tela.bind("<Key-0>", lambda e: self.ver_tudo())

        aviso = ttk.Frame(c)
        aviso.grid(row=8, column=0, sticky="we", pady=(6, 0))
        aviso.columnconfigure(0, weight=1)
        self.rotulo_fora = ttk.Label(aviso, textvariable=self.aviso_fora, foreground="#b35c00",
                                     wraplength=520, justify="left")
        self.caixa_fora = ttk.Checkbutton(
            aviso, text="Deixar de fora essas feicoes (recomendado)", variable=self.ignorar_fora)

    def _mostrar(self, qual):
        """Mostra o quadro de estado (vazio, carregando, erro...) ou a lista com o desenho."""
        if qual == "corpo":
            self.quadro_estado.grid_remove()
            self.corpo.grid(row=0, column=0, sticky="nsew")
        else:
            self.corpo.grid_remove()
            self.quadro_estado.grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------------
    # estados
    def _estado(self, estado, mensagem=""):
        if estado != "pronto":
            self.ampliar(False)              # sem desenho, nada pode ficar escondido
        self.estado = estado
        self.mensagem_de_estado.set(mensagem)
        self._mostrar("corpo" if estado == "pronto" else "estado")
        if estado == "carregando":
            self.progresso.grid(row=1, column=0)
            self.progresso.start(14)
        else:
            self.progresso.stop()
            self.progresso.grid_remove()
        if estado == "erro":
            self.botao_repetir.grid(row=2, column=0, pady=8)
        else:
            self.botao_repetir.grid_remove()

    def botao_tentar_de_novo_visivel(self):
        return bool(self.botao_repetir.winfo_manager())

    def limpar(self):
        """Volta ao comeco: nenhum desenho. Descarta qualquer leitura em andamento."""
        self._token += 1
        self._caminho = None
        self.previa = None
        self.vista = self._regiao = None
        self.ids = None
        self.liberar()
        self._estado("vazio", "Escolha o desenho do AutoCAD no passo 1 e as camadas "
                              "dele aparecem aqui, com uma previa.")

    def carregar(self, caminho):
        """Le o desenho em segundo plano. O DWG passa antes pelo ODA."""
        self._token += 1
        token = self._token
        self._caminho = caminho
        self.previa = None
        self.liberar()
        self._estado("carregando", "Lendo o desenho...")

        def trabalhar():
            dxf = caminho
            try:
                if caminho.lower().endswith(".dwg"):
                    if not dwg.disponivel():
                        raise convert.ErroConversao(dwg.MENSAGEM_AUSENTE)
                    self._fila.put((token, "msg", "Convertendo o DWG com o ODA File "
                                    "Converter (alguns segundos)..."))
                    dxf = dwg.dwg_para_dxf(caminho)
                if token == self._token:
                    self._fila.put((token, "msg", "Lendo as camadas do desenho..."))
                    lida = previa.ler(dxf)
                    if token == self._token:
                        self._fila.put((token, "ok", (lida, dxf, dxf != caminho)))
                        return
                if dxf != caminho:
                    # leitura descartada no meio (desmarcou a caixa ou trocou de arquivo): a
                    # janela nao vai mais ler a fila, entao a copia do cliente some aqui
                    dwg.apagar_temporario(dxf)
            except Exception as erro:
                if dxf != caminho:
                    # a leitura falhou depois do ODA: a copia do desenho do cliente nao serve
                    dwg.apagar_temporario(dxf)
                self._fila.put((token, "erro", erro))

        threading.Thread(target=trabalhar, daemon=True).start()
        self._recolher()

    def _recolher(self):
        """Traz para a janela o que a thread deixou na fila."""
        self._depois_fila = None
        try:
            while True:
                token, tipo, carga = self._fila.get_nowait()
                if token != self._token:
                    if tipo == "ok" and carga[2]:            # DXF temporario de uma leitura antiga
                        self._pendentes.append(os.path.dirname(os.path.dirname(carga[1])))
                    continue
                if tipo == "msg":
                    self.mensagem_de_estado.set(carga)
                elif tipo == "ok":
                    lida, dxf, temporario = carga
                    if temporario:
                        self._pendentes.append(os.path.dirname(os.path.dirname(dxf)))
                    self.definir_previa(lida, dxf_pronto=dxf)
                elif tipo == "erro":
                    self._falhou(carga)
        except queue.Empty:
            pass
        if self.estado == "carregando":
            self._depois_fila = self.after(80, self._recolher)

    def _falhou(self, erro):
        self.ao_registrar("Nao consegui ler o desenho: %s" % erro)
        if isinstance(erro, (convert.ErroConversao, dwg.ErroDWG)):
            texto = str(erro)
        else:
            texto = ("Nao consegui ler este desenho. Ele pode estar corrompido ou ser de "
                     "uma versao que o programa nao abre. Os detalhes estao no quadro "
                     "\"O que aconteceu\".")
        self._estado("erro", texto)

    def _tentar_de_novo(self):
        if self._caminho:
            self.carregar(self._caminho)

    def definir_previa(self, lida, dxf_pronto=None):
        """Mostra a lista e o desenho de uma Previa ja lida."""
        self.previa = lida
        self.dxf_pronto = dxf_pronto
        # as linhas do desenho anterior saem antes (nem as cores abertas nelas valem mais)
        self.arvore.delete(*self.arvore.get_children())
        self._iid, self._nome_de, self._abertas = {}, {}, set()
        self._recalcular_itens()
        if not lida.camadas:
            # o GDAL abre ate arquivo quebrado como um DXF vazio
            self._estado("erro", "Nao encontrei nada para desenhar neste arquivo. Ele pode "
                                 "estar vazio, corrompido ou ser de um formato que o "
                                 "programa nao le.")
            return
        if not any(c.tem_geometria for c in lida.camadas):
            self._estado("sem_geometria",
                         "Este desenho nao tem pontos, linhas nem areas para converter "
                         "(so textos ou hachuras).")
            return
        self._sem_aviso_de_ocultas = True            # desenho novo: volta a mostrar so o ligado
        self.mostrar_ocultas.set(False)
        self._sem_aviso_de_ocultas = False
        # abre sem nada marcado: o negrito so diz algo se for o que a pessoa escolheu
        self.cores_marcadas = set()
        self.escolhidas = set()
        self.destaque = None
        self.vista = self._regiao = None
        self.busca.set("")
        self.aviso_busca.set("")
        self.rotulo_busca.grid_remove()
        self.detalhe.set("")
        self._avisar_feicoes_longe()
        self._estado("pronto")
        self._popular()
        self.update_idletasks()
        self.ver_tudo()

    def _avisar_feicoes_longe(self):
        p = self.previa
        if not p.fora_total:
            self.aviso_fora.set("")
            self.rotulo_fora.grid_remove()
            self.caixa_fora.grid_remove()
            return
        d = p.distancia_fora
        distancia = ("%.0f km" % (d / 1000.0)) if self.unidade_em_metros else "%.4g unidades" % d
        self.aviso_fora.set(
            "%d feicoes (%s) estao a ate %s do desenho. Parecem lixo do desenho: "
            "na entrega cairiam longe do terreno, e a previa ignora elas."
            % (p.fora_total, ", ".join(c.nome for c in p.camadas if c.fora)[:90], distancia))
        self.rotulo_fora.grid(row=0, column=0, sticky="w")
        self.caixa_fora.grid(row=1, column=0, sticky="w")
        self.ignorar_fora.set(True)

    # ------------------------------------------------------------------
    # a lista
    #
    # Uma linha por camada; a camada de mais de uma cor abre (a setinha) uma linha por cor.
    # Por dentro, o que se marca e sempre a cor de uma camada (`cores_marcadas`, chaves
    # (camada, cor) das previa.Unidade): marcar a camada marca todas as cores dela que a lista
    # mostra. A caixa de cada linha tem tres estados (ver estado_da_caixa).
    def _recalcular_itens(self):
        p = self.previa
        self.indice = {u.chave: n for n, u in enumerate(p.unidades)}     # chave -> id no desenho
        self._unidades_de = collections.defaultdict(list)
        for u in p.unidades:
            self._unidades_de[u.camada].append(u)
        self._camadas = {c.nome: c for c in p.camadas}                   # chave -> item
        self._camadas.update({u.chave: u for u in p.unidades})
        self._nome_cor = {}
        for camada, unidades in self._unidades_de.items():
            nomes = [dxf_estilo.nome_para_ler(u.cor) for u in unidades]
            for u, nome in zip(unidades, nomes):
                # duas cores parecidas na mesma camada: o codigo desempata
                self._nome_cor[u.chave] = (nome if nomes.count(nome) == 1
                                           else "%s (%s)" % (nome, u.cor))

    def nome_da_cor(self, chave):
        """Como a cor (camada, cor) se chama na lista: "azul", "marrom"..."""
        return self._nome_cor.get(chave) or dxf_estilo.nome_para_ler(chave[1])

    def _mostra(self, item):
        """A lista mostra as desligadas no AutoCAD so com a caixinha."""
        return self.mostrar_ocultas.get() or not item.oculta

    def _cores_que_mostra(self, camada):
        return [u for u in self._unidades_de.get(camada, ()) if self._mostra(u)]

    def _exibidas(self):
        """As chaves (camada, cor) que entram no desenho: as que a lista mostra e tem pontos,
        linhas, areas, textos, hachuras ou figuras."""
        return {u.chave for u in self.previa.unidades if self._mostra(u) and u.tem_desenho}

    def _alvo(self, chave):
        """As cores que a caixa da linha marca: a propria cor ou, na camada, as cores dela
        que a lista mostra. Vazio se nao ha o que levar."""
        if isinstance(chave, tuple):
            return [chave] if self._camadas[chave].tem_desenho else []
        return [u.chave for u in self._cores_que_mostra(chave) if u.tem_desenho]

    def _dentro(self, gid, chave):
        g = self.previa.grupos[gid]
        return (g.camada, g.cor) == chave if isinstance(chave, tuple) else g.camada == chave

    def _escolhidas_em(self, chave, fora_das_marcadas=False):
        """[linhas, textos] escolhidos no desenho dentro da camada ou da cor (so os que nao
        estao numa cor marcada, se pedido: esses ja vao com ela)."""
        n = [0, 0]
        for gid in self.escolhidas:
            g = self.previa.grupos[gid]
            if fora_das_marcadas and (g.camada, g.cor) in self.cores_marcadas:
                continue
            if self._dentro(gid, chave):
                n[g.texto is not None] += 1
        return n

    def estado_da_caixa(self, chave):
        """"marcada": vai inteira; "parcial": vai uma parte (algumas cores, ou linhas e textos
        escolhidos no desenho); "vazia": nada dela vai."""
        alvo = self._alvo(chave)
        marcadas = sum(1 for k in alvo if k in self.cores_marcadas)
        if alvo and marcadas == len(alvo):
            return "marcada"
        if marcadas or any(self._escolhidas_em(chave)):
            return "parcial"
        return "vazia"

    @property
    def marcadas(self):
        """As camadas inteiras marcadas (todas as cores que a lista mostra)."""
        if self.previa is None:
            return set()
        return {camada for camada in {k[0] for k in self.cores_marcadas}
                if self._alvo(camada) and all(k in self.cores_marcadas
                                              for k in self._alvo(camada))}

    def _o_que_vai(self, chave):
        """A coluna "Na conversao": "tudo", "so azul", "1 linha escolhida", ou nada."""
        if self.estado_da_caixa(chave) == "marcada":
            return "tudo"
        partes = []
        if not isinstance(chave, tuple):
            alvo = self._alvo(chave)
            cores = [k for k in alvo if k in self.cores_marcadas]
            if len(cores) > 2:
                partes.append("%d de %d cores" % (len(cores), len(alvo)))
            elif cores:
                partes.append("so " + " e ".join(self.nome_da_cor(k) for k in cores))
        linhas, textos = self._escolhidas_em(chave, fora_das_marcadas=True)
        if linhas or textos:
            partes.append(contar_escolhidas(linhas, textos))
        return " + ".join(partes)

    def _o_que_tem(self, chave):
        item = self._camadas[chave]
        texto = item.resumo(" · ") or "vazia"
        if item.oculta:
            texto += " · desligada"
        return texto

    def cores_da_amostra(self, chave):
        """As cores da amostra ao lado da caixa: as da camada (ate MAX_AMOSTRAS, a mais usada
        primeiro), ou a da cor."""
        if isinstance(chave, tuple):
            return [chave[1]]
        return [u.cor for u in self._cores_que_mostra(chave)][:MAX_AMOSTRAS]

    def _imagem_da_linha(self, chave):
        item = self._camadas[chave]
        return self._fotos.desenhar(self.estado_da_caixa(chave), self.cores_da_amostra(chave),
                                    ativa=item.tem_desenho,
                                    lugares=1 if isinstance(chave, tuple) else MAX_AMOSTRAS)

    def _etiquetas(self, chave):
        item = self._camadas[chave]
        etiquetas = []
        if item.oculta or not item.tem_desenho:
            etiquetas.append("apagada")
        if self.estado_da_caixa(chave) != "vazia":
            etiquetas.append("marcada")             # vai para a conversao: negrito
        return tuple(etiquetas)

    def _contagem_escolhidas(self):
        """(linhas, textos) escolhidos no desenho."""
        textos = sum(1 for g in self.escolhidas if self.previa.grupos[g].texto is not None)
        return len(self.escolhidas) - textos, textos

    def _popular(self):
        """Recria as linhas da lista segundo a busca e a caixinha das desligadas."""
        self._silencio = True
        for iid in self.arvore.get_children():
            if self.arvore.item(iid, "open"):
                self._abertas.add(self._nome_de[iid])
            else:
                self._abertas.discard(self._nome_de[iid])
        self.arvore.delete(*self.arvore.get_children())
        self._iid, self._nome_de = {}, {}
        texto = self.busca.get().strip().casefold()
        for n, camada in enumerate(self.previa.camadas):
            if not self._mostra(camada) or (texto and texto not in camada.nome.casefold()):
                continue
            iid = self._inserir("", "c%d" % n, camada.nome, camada.nome)
            cores = self._cores_que_mostra(camada.nome)
            if len(cores) > 1:
                for u in cores:
                    self._inserir(iid, "u%d" % self.indice[u.chave], u.chave,
                                  self.nome_da_cor(u.chave))
                self.arvore.item(iid, open=camada.nome in self._abertas)
        if self.destaque in self._iid:
            self.arvore.selection_set(self._iid[self.destaque])
        self._silencio = False
        self._atualizar_resumo()

    def _inserir(self, pai, iid, chave, texto):
        self._iid[chave] = iid
        self._nome_de[iid] = chave
        self.arvore.insert(pai, "end", iid=iid, text=texto,
                           image=self._imagem_da_linha(chave),
                           values=(self._o_que_tem(chave), self._o_que_vai(chave)),
                           tags=self._etiquetas(chave))
        return iid

    def nomes_na_lista(self):
        """As camadas que a lista mostra, na ordem."""
        return [self._nome_de[i] for i in self.arvore.get_children()]

    def cores_na_lista(self, camada):
        """As cores (camada, cor) dentro da camada na lista; vazio se ela tem uma cor so."""
        iid = self._iid.get(camada)
        return [self._nome_de[i] for i in self.arvore.get_children(iid)] if iid else []

    def selecionada(self):
        sel = self.arvore.selection()
        return self._nome_de.get(sel[0]) if sel else None

    def _atualizar_camada(self, camada):
        """Refaz a linha da camada e as das cores dela (a caixa, as colunas, o negrito)."""
        for chave in [camada] + [u.chave for u in self._unidades_de.get(camada, ())]:
            iid = self._iid.get(chave)
            if iid:
                self.arvore.item(iid, image=self._imagem_da_linha(chave),
                                 values=(self._o_que_tem(chave), self._o_que_vai(chave)),
                                 tags=self._etiquetas(chave))

    def _atualizar_linhas(self):
        for camada in self.nomes_na_lista():
            self._atualizar_camada(camada)

    def _atualizar_resumo(self):
        """O que vai para a conversao, numa frase."""
        inteiras = self.marcadas
        partes_de = {k[0] for k in self.cores_marcadas} - inteiras
        linhas = textos = 0
        for gid in self.escolhidas:
            g = self.previa.grupos[gid]
            if (g.camada, g.cor) not in self.cores_marcadas:
                if g.texto is None:
                    linhas += 1
                else:
                    textos += 1
        if not (inteiras or partes_de or linhas or textos):
            self.resumo.set("Nada escolhido ainda. Marque as camadas na lista ou clique nas "
                            "linhas e textos do desenho (Ctrl+clique soma).")
            return
        partes = []
        if inteiras:
            partes.append("%d %s" % (len(inteiras), "camada inteira" if len(inteiras) == 1
                                     else "camadas inteiras"))
        if partes_de:
            partes.append("parte das cores de %d %s" % (
                len(partes_de), "camada" if len(partes_de) == 1 else "camadas"))
        if linhas or textos:
            partes.append("%s no desenho" % contar_escolhidas(linhas, textos))
        frase = partes[0] if len(partes) == 1 else "%s e %s" % (", ".join(partes[:-1]),
                                                                  partes[-1])
        self.resumo.set("Vai para a conversao: %s." % frase)

    def _ao_alternar_ocultas(self, *_):
        """A caixinha das desligadas mudou: refaz a lista e o desenho."""
        if self.previa is None or self.estado != "pronto" or self._sem_aviso_de_ocultas:
            return
        if not self.mostrar_ocultas.get():
            # o que a lista nao mostra mais nao pode ir para a conversao
            tirar = {k for k in self.cores_marcadas if self._camadas[k].oculta}
            self.cores_marcadas -= tirar
            avisos = []
            if tirar:
                avisos.append("%d camada(s) desligada(s) no AutoCAD foram desmarcadas."
                              % len({k[0] for k in tirar}))
            sumidas = {g for g in self.escolhidas if self.previa.grupos[g].oculta}
            self.escolhidas -= sumidas
            if sumidas:
                avisos.append("%d linha(s) escolhida(s) em camada desligada no AutoCAD foram "
                              "tiradas." % len(sumidas))
            if avisos:
                self.detalhe.set(" ".join(avisos))
            if self.destaque is not None and not self._mostra(self._camadas[self.destaque]):
                self.destaque = None
        self._popular()
        self.ver_tudo()

    def alternar(self, chave):
        """A caixa da linha (camada ou cor): vazia ou pela metade, passa a levar tudo; tudo,
        passa a nada -- e "nada" tira tambem as linhas e textos escolhidos nela."""
        alvo = self._alvo(chave)
        if not alvo:
            return
        if self.estado_da_caixa(chave) == "marcada":
            self.cores_marcadas.difference_update(alvo)
            self.escolhidas = {g for g in self.escolhidas if not self._dentro(g, chave)}
        else:
            self.cores_marcadas.update(alvo)
        self._atualizar_camada(chave[0] if isinstance(chave, tuple) else chave)
        self._atualizar_resumo()
        self._renderizar()

    def marcar_todas(self):
        """Marca tudo o que tem desenho entre o que a lista mostra: pontos, linhas, areas,
        textos, hachuras ou figuras. Camada so de textos entra tambem, porque os textos
        (e as hachuras) vao para a conversao pela camada marcada."""
        for nome in self.nomes_na_lista():
            self.cores_marcadas.update(self._alvo(nome))
        self._atualizar_linhas()
        self._atualizar_resumo()
        self._renderizar()

    def desmarcar_todas(self):
        """Tira as marcas das camadas que a lista mostra e todas as linhas escolhidas."""
        na_lista = set(self.nomes_na_lista())
        self.cores_marcadas = {k for k in self.cores_marcadas if k[0] not in na_lista}
        self.escolhidas = set()
        self._atualizar_linhas()
        self._atualizar_resumo()
        self._renderizar()

    def filtrar(self, texto, _do_campo=False):
        if not _do_campo:
            self.busca.set(texto)            # dispara o filtro de novo pelo campo
            return
        if self.previa is None:
            return
        self._popular()
        texto = texto.strip()
        if texto and not self._iid:
            self.aviso_busca.set("Nenhuma camada tem \"%s\" no nome. Use Limpar para ver "
                                 "todas." % texto)
            self.rotulo_busca.grid()
        else:
            self.aviso_busca.set("")
            self.rotulo_busca.grid_remove()

    def selecionar(self, chave):
        if chave not in self._iid:
            self.busca.set("")
        if chave in self._iid:
            self._silencio = True
            iid = self._iid[chave]
            pai = self.arvore.parent(iid)
            if pai:
                self.arvore.item(pai, open=True)
            self.arvore.selection_set(iid)
            self.arvore.see(iid)
            self._silencio = False
        self._definir_destaque(chave)

    def _ao_selecionar(self, _evento=None):
        if self._silencio:
            return
        self._definir_destaque(self.selecionada())

    def _definir_destaque(self, chave):
        self.destaque = chave
        if chave is None:
            self.detalhe.set("")
        else:
            item = self._camadas[chave]
            if isinstance(chave, tuple):
                nome = "%s, %s" % (chave[0], self.nome_da_cor(chave))
            else:
                nome = item.nome
            texto = "%s: %s." % (nome, item.resumo() or "vazia")
            if item.oculta:
                texto += " Desligada no AutoCAD: marque a caixa para levar para a conversao."
            if (item.tem_desenho and not item.tem_geometria
                    and not item.contagem.get("texto")):
                texto += (" Aparece no desenho, mas o clique so escolhe pontos, linhas, areas "
                          "e textos (hachuras e figuras vao pela camada marcada).")
            self.detalhe.set(texto)
        self._renderizar()

    def _clique_na_lista(self, evento):
        """Clicar na caixa (ou na amostra de cor ao lado) marca e desmarca; na setinha, abre
        as cores; no resto da linha, so seleciona."""
        iid = self.arvore.identify_row(evento.y)
        if not iid or self.arvore.identify_element(evento.x, evento.y) != "image":
            return None
        self.alternar(self._nome_de[iid])
        return "break"

    def _espaco(self, _evento):
        chave = self.selecionada()
        if chave is not None:
            self.alternar(chave)
        return "break"

    # ------------------------------------------------------------------
    # o desenho
    def tamanho(self):
        w, h = self.tela.winfo_width(), self.tela.winfo_height()
        if w < 50 or h < 50:                 # ainda nao apareceu na tela
            w, h = int(self.tela["width"]), int(self.tela["height"])
        return w, h

    def ver_tudo(self):
        """Enquadra tudo o que aparece no desenho (nao so o que esta marcado)."""
        if self.previa is None or self.estado != "pronto":
            return
        caixa = self.previa.caixa_de_itens([self._camadas[c] for c in self._exibidas()],
                                           com_ocultas=self.mostrar_ocultas.get())
        self._regiao = (caixa, MARGEM_DO_VER_TUDO) if caixa else None
        self._enquadrar()
        self._renderizar()

    def _enquadrar(self):
        """A vista que mostra a regiao pedida, inteira e no centro, no tamanho atual da tela."""
        if self._regiao is None:
            self.vista = None
            return
        caixa, margem = self._regiao
        largura, altura = self.tamanho()
        self.vista = pr.ajustar(caixa, largura, altura, margem=margem)

    def _lembrar_regiao(self):
        """Depois do zoom ou do arrasto, o que aparece passa a ser o que a pessoa quer ver."""
        if self.vista is not None:
            self._regiao = (pr.regiao_visivel(self.vista, *self.tamanho()), 0)

    def alternar_ampliado(self):
        self.ampliar(not self.ampliado)

    def ampliar(self, ligar=True):
        """O desenho grande: sem a lista de camadas, e quem esta em volta (a aba) esconde
        os passos da conversao, para o desenho ocupar a janela. Esc ou o mesmo botao
        voltam ao normal. So amplia quando ha desenho na tela."""
        ligar = bool(ligar) and self.estado == "pronto"
        if ligar == self.ampliado:
            return
        self.ampliado = ligar
        for parte in self._partes_da_lista:
            if ligar:
                parte.grid_remove()
            else:
                parte.grid()                 # volta com as mesmas opcoes de antes
        if ligar or not self.aviso_busca.get():
            self.rotulo_busca.grid_remove()
        else:
            self.rotulo_busca.grid()
        self.botao_ampliar.configure(text="Voltar ao normal (Esc)" if ligar else "Ampliar desenho")
        topo = self.winfo_toplevel()
        if ligar:
            self._esc = topo.bind("<Escape>", lambda _e: self.ampliar(False), add="+")
            self.tela.focus_set()
        else:
            self._soltar_esc()
        self.ao_ampliar(ligar)

    def _soltar_esc(self):
        if self._esc:
            try:
                self.winfo_toplevel().unbind("<Escape>", self._esc)
            except tk.TclError:
                pass
            self._esc = None

    def mensagem_do_desenho(self):
        return self.tela.itemcget(self._texto, "text")

    def _renderizar(self):
        if self.previa is None or self.estado != "pronto":
            return
        largura, altura = self.tamanho()
        # cada cor de cada camada tem o seu id no desenho (ver _recalcular_itens)
        desenhos = pr.montar_desenhos(self.previa, self._exibidas(), self.indice,
                                      marcadas=self.cores_marcadas,
                                      com_ocultas=self.mostrar_ocultas.get(),
                                      por_cor=True, linhas_marcadas=self.escolhidas)
        if not desenhos or self.vista is None:
            self.ids = self.imagem = None
            self.tela.itemconfigure(self._item, image="")
            if not self.mostrar_ocultas.get() and any(
                    c.oculta and c.tem_desenho for c in self.previa.camadas):
                texto = ("No AutoCAD, todas as camadas deste desenho estao desligadas. "
                         "Marque \"Mostrar camadas desligadas no AutoCAD\" para ver o desenho.")
            else:
                texto = "Nenhuma camada tem pontos, linhas ou areas para desenhar."
            self.tela.itemconfigure(self._texto, text=texto)
            self.tela.coords(self._texto, largura / 2, altura / 2)
            return
        self.tela.itemconfigure(self._texto, text="")
        img, self.ids = pr.desenhar(desenhos, self.vista, largura, altura,
                                    destaque=self._ids_do_destaque())
        self.imagem = img
        self._foto = tk.PhotoImage(master=self.tela, data=pr.para_ppm(img))
        self.tela.itemconfigure(self._item, image=self._foto)
        self.tela.coords(self._item, 0, 0)

    def _ids_do_destaque(self):
        """Os ids, no desenho, da linha escolhida na lista: todas as cores da camada, ou a
        cor."""
        if self.destaque is None:
            return None
        if isinstance(self.destaque, tuple):
            return {self.indice[self.destaque]}
        return {self.indice[u.chave] for u in self._unidades_de.get(self.destaque, ())}

    def _agendar_render(self):
        if self._depois_render:
            self.after_cancel(self._depois_render)
        self._depois_render = self.after(30, self._render_agendado)

    def _render_agendado(self):
        self._depois_render = None
        self._renderizar()

    def _ao_redimensionar(self, evento):
        if self.previa is None or self.estado != "pronto":
            return
        if self.vista is None or self._regiao is None:
            self.ver_tudo()
            return
        # o que a pessoa pediu para ver continua inteiro e no centro: tela maior, desenho maior
        self._enquadrar()
        self._agendar_render()

    def _roda(self, evento):
        if self.vista is None:
            return
        self.vista.zoom(FATOR_DO_ZOOM if evento.delta > 0 else 1 / FATOR_DO_ZOOM,
                        evento.x, evento.y)
        self._lembrar_regiao()
        self._agendar_render()

    def _zoom_no_centro(self, fator):
        if self.vista is None:
            return
        largura, altura = self.tamanho()
        self.vista.zoom(fator, largura / 2, altura / 2)
        self._lembrar_regiao()
        self._agendar_render()

    def _apertou(self, evento):
        self.tela.focus_set()
        self._arrasto = [evento.x, evento.y, 0, 0]

    def _arrastou(self, evento):
        if not self._arrasto or self.vista is None:
            return
        a = self._arrasto
        dx, dy = evento.x - a[0], evento.y - a[1]
        self.tela.move(self._item, dx - a[2], dy - a[3])      # so move a imagem; redesenha ao soltar
        a[2], a[3] = dx, dy

    def _soltou(self, evento):
        a, self._arrasto = self._arrasto, None
        if not a:
            return
        if abs(a[2]) + abs(a[3]) < LIMITE_DO_CLIQUE:
            self.clicar(evento.x, evento.y, ctrl=bool(getattr(evento, "state", 0) & CONTROL))
        elif self.vista is not None:
            self.vista.deslocar(a[2], a[3])
            self._lembrar_regiao()
            self._renderizar()

    def _linha_em(self, x, y):
        """O id do grupo (a linha ou o texto) que esta no pixel (x, y) ou perto dele, ou None.

        Dentro da caixa de um texto (a altura da letra ao longo da linha, mais uns pixels),
        e o texto. Fora, o mapa de pixels diz qual camada (ou cor) esta ali e a conta no
        desenho diz qual linha dela."""
        if self.ids is None or self.vista is None:
            return None
        dx, dy = self.vista.para_desenho(x, y)
        camadas = {k[0] for k in self._exibidas()}
        texto = self.previa.achar_texto(dx, dy, FOLGA_DO_TEXTO / self.vista.escala, camadas)
        if texto is not None:
            return texto
        indice = pr.camada_em(self.ids, x, y)
        if indice is None:
            return None
        u = self.previa.unidades[indice]
        return self.previa.achar_grupo(dx, dy, RAIO_DO_CLIQUE / self.vista.escala, u.camada,
                                       u.cor, com_ocultas=self.mostrar_ocultas.get())

    def _texto_da_linha(self, gid):
        g = self.previa.grupos[gid]
        cor = self.nome_da_cor((g.camada, g.cor))
        if g.texto is not None:
            escrito = " ".join(g.texto.split())
            if len(escrito) > 70:
                escrito = escrito[:67] + "..."
            return "Texto escolhido na camada %s (%s): \"%s\"" % (g.camada, cor, escrito)
        if g.pecas == 1:
            return "Linha escolhida na camada %s (%s)." % (g.camada, cor)
        return "Linha escolhida na camada %s (%s), feita de %d pecas ligadas pelas pontas." % (
            g.camada, cor, g.pecas)

    def clicar(self, x, y, ctrl=False):
        """Clique no desenho: escolhe a linha que esta ali (as pecas que se encostam pelas
        pontas) ou o texto, e nao a camada nem a cor inteira. Com Ctrl, soma (ou tira) a
        escolha das ja feitas e nao mexe nas camadas marcadas; sem Ctrl, ela passa a ser a
        unica coisa escolhida. Clicar no vazio nao mexe em nada: so tira o destaque da lista."""
        gid = self._linha_em(x, y)
        if gid is None:
            self._silencio = True
            self.arvore.selection_remove(*self.arvore.selection())
            self._silencio = False
            self._definir_destaque(None)
            return
        if ctrl:
            self.escolhidas ^= {gid}
        else:
            self.cores_marcadas = set()
            self.escolhidas = {gid}
        self._silencio = True
        self.arvore.selection_remove(*self.arvore.selection())
        self._silencio = False
        self.destaque = None                   # o contorno branco seria da camada inteira
        self._atualizar_linhas()
        self._atualizar_resumo()
        self.detalhe.set(self._texto_da_linha(gid) if gid in self.escolhidas else
                         "Texto tirado da escolha." if self.previa.grupos[gid].texto is not None
                         else "Linha tirada da escolha.")
        self._renderizar()

    # ------------------------------------------------------------------
    def selecao(self):
        """O que a conversao precisa saber: camadas inteiras, linhas e textos escolhidos um a
        um (`feicoes`, ids do GDAL; `linhas` e `textos` dizem quantos de cada), DXF pronto e a
        caixa a descartar.

        `cores` ({camada: {cores}}) so tem as camadas pela metade (algumas cores marcadas): a
        camada inteira vai sem filtro, ou None se nenhuma esta pela metade. `separar_por_cor`
        sao as camadas de mais de uma cor que a opcao "uma camada do QGIS para cada cor"
        divide na saida."""
        caixa = None
        if self.previa is None:
            return {"camadas": set(), "cores": None, "separar_por_cor": set(), "feicoes": set(),
                    "linhas": 0, "textos": 0, "dxf": self.dxf_pronto, "caixa": None}
        if self.previa.fora_total and self.ignorar_fora.get():
            caixa = self.previa.caixa_area
        feicoes = {f for g in self.escolhidas for f in self.previa.grupos[g].fids}
        linhas, textos = self._contagem_escolhidas()
        camadas = {k[0] for k in self.cores_marcadas}
        inteiras = self.marcadas
        cores = {}
        for camada, cor in self.cores_marcadas:
            if camada not in inteiras:
                cores.setdefault(camada, set()).add(cor)
        dividir = set()
        if self.separar_por_cor.get():
            # so sai dividida a camada que tem mais de uma cor no desenho; as linhas escolhidas
            # saem com o nome da cor, como o resto
            tocadas = camadas | {self.previa.grupos[g].camada for g in self.escolhidas}
            dividir = {c for c in tocadas if len(self._unidades_de.get(c, ())) > 1}
        return {"camadas": camadas, "cores": cores or None, "separar_por_cor": dividir,
                "feicoes": feicoes, "linhas": linhas, "textos": textos,
                "dxf": self.dxf_pronto, "caixa": caixa}

    @property
    def pronto(self):
        return self.estado == "pronto"

    @property
    def caminho(self):
        """O desenho que o painel esta lendo ou mostrando (None se nenhum)."""
        return self._caminho

    def liberar(self, forcar=False):
        """Apaga os DXF temporarios que o ODA deixou (copias do desenho do cliente).

        `forcar` e o programa fechando: alem do que o painel ja conhece, encerra o ODA que
        ainda roda e apaga o que uma thread de leitura em andamento criou e ainda nao
        entregou (`dwg.encerrar`)."""
        if self.em_uso and not forcar:
            return
        if forcar:
            dwg.encerrar()
        restantes = []
        for pasta in self._pendentes:
            nome = os.path.basename(pasta)
            if nome.startswith("conv_dwg_") and os.path.isdir(pasta):
                shutil.rmtree(pasta, ignore_errors=True)
                if os.path.isdir(pasta):
                    restantes.append(pasta)
        self._pendentes = restantes

    def destroy(self):
        for id_ in (self._depois_render, self._depois_fila):
            if id_:
                try:
                    self.after_cancel(id_)
                except tk.TclError:
                    pass
        self._token += 1
        self.liberar(forcar=True)
        self._soltar_esc()
        super().destroy()
