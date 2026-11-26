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
MARCADA, DESMARCADA = "☑", "☐"        # caixa marcada e desmarcada
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
        self.marcadas = set()
        self.escolhidas = set()              # ids de grupo (previa.Grupo): linhas clicadas
        self.destaque = None
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
        self._iid = {}
        self._nome_de = {}
        self._camadas = {}
        self._fotos = {}
        self._silencio = False
        self._sem_aviso_de_ocultas = False
        self._sem_aviso_de_cor = False
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
        self.separar_por_cor.trace_add("write", self._ao_alternar_cor)
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
        c.rowconfigure(2, weight=0)
        c.rowconfigure(6, weight=1)

        barra = ttk.Frame(c)
        barra.grid(row=0, column=0, sticky="we")
        barra.columnconfigure(1, weight=1)
        ttk.Label(barra, text="Buscar:").grid(row=0, column=0, padx=(0, 4))
        self.campo_busca = ttk.Entry(barra, textvariable=self.busca)
        self.campo_busca.grid(row=0, column=1, sticky="we")
        self.busca.trace_add("write", lambda *_: self.filtrar(self.busca.get(), _do_campo=True))
        ttk.Button(barra, text="Limpar", width=7,
                   command=lambda: self.filtrar("")).grid(row=0, column=2, padx=(4, 8))
        ttk.Button(barra, text="Marcar todas", command=self.marcar_todas
                   ).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(barra, text="Desmarcar todas", command=self.desmarcar_todas
                   ).grid(row=0, column=4)

        opcoes = ttk.Frame(c)
        opcoes.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(opcoes, text="Mostrar camadas desligadas no AutoCAD",
                        variable=self.mostrar_ocultas).grid(row=0, column=0, padx=(0, 18))
        ttk.Checkbutton(opcoes, text="Separar cada camada por cor",
                        variable=self.separar_por_cor).grid(row=0, column=1)

        quadro = ttk.Frame(c)
        quadro.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        quadro.columnconfigure(0, weight=1)
        quadro.rowconfigure(0, weight=1)
        self.arvore = ttk.Treeview(quadro, columns=("marca", "nome", "conteudo"),
                                   show="tree headings", height=7, selectmode="browse")
        self.arvore.heading("#0", text="")
        self.arvore.heading("marca", text="")
        self.arvore.heading("nome", text="Camada")
        self.arvore.heading("conteudo", text="O que tem")
        self.arvore.column("#0", width=28, minwidth=28, stretch=False)
        self.arvore.column("marca", width=30, minwidth=30, stretch=False, anchor="center")
        self.arvore.column("nome", width=190, minwidth=90)
        self.arvore.column("conteudo", width=240, minwidth=90)
        negrito = tkfont.nametofont("TkDefaultFont").copy()
        negrito.configure(weight="bold")
        self._negrito = negrito                      # o Tk perde a fonte se o Python a descarta
        self.arvore.tag_configure("apagada", foreground="#7a7a7a")
        self.arvore.tag_configure("marcada", font=negrito)
        self.arvore.grid(row=0, column=0, sticky="nsew")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.arvore.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.arvore.config(yscrollcommand=rolagem.set)
        self.arvore.bind("<Button-1>", self._clique_na_lista)
        self.arvore.bind("<<TreeviewSelect>>", self._ao_selecionar)
        self.arvore.bind("<space>", self._espaco)

        rotulo_busca = ttk.Label(c, textvariable=self.aviso_busca, foreground="#555")
        rotulo_busca.grid(row=3, column=0, sticky="w", pady=(2, 0))
        # o que sai da frente quando o desenho e ampliado
        self._partes_da_lista = (barra, opcoes, quadro, rotulo_busca)
        ttk.Label(c, textvariable=self.detalhe, wraplength=520, justify="left"
                  ).grid(row=4, column=0, sticky="w", pady=(2, 4))

        ferramentas = ttk.Frame(c)
        ferramentas.grid(row=5, column=0, sticky="we")
        ttk.Button(ferramentas, text="Ver tudo", width=9, command=self.ver_tudo
                   ).grid(row=0, column=0)
        self.botao_ampliar = ttk.Button(ferramentas, text="Ampliar desenho",
                                        command=self.alternar_ampliado)
        self.botao_ampliar.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(ferramentas, foreground="#555",
                  text="  Roda: zoom   Arrastar: mover   Clique: escolhe a linha ou o texto   "
                       "Ctrl+clique: soma"
                  ).grid(row=0, column=2, sticky="w")

        self.tela = tk.Canvas(c, width=LARGURA, height=ALTURA, background=_hex(pr.FUNDO),
                              highlightthickness=1, highlightbackground="#555", takefocus=True)
        self.tela.grid(row=6, column=0, sticky="nsew", pady=(4, 0))
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
        aviso.grid(row=7, column=0, sticky="we", pady=(6, 0))
        aviso.columnconfigure(0, weight=1)
        self.rotulo_fora = ttk.Label(aviso, textvariable=self.aviso_fora, foreground="#b35c00",
                                     wraplength=520, justify="left")
        self.caixa_fora = ttk.Checkbutton(
            aviso, text="Deixar de fora essas feicoes (recomendado)", variable=self.ignorar_fora)
        ttk.Label(c, textvariable=self.resumo).grid(row=8, column=0, sticky="w", pady=(4, 0))

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
        self._sem_aviso_de_cor = True                # desenho novo: volta a camada inteira
        self.separar_por_cor.set(False)
        self._sem_aviso_de_cor = False
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
        self.marcadas = set()
        self.escolhidas = set()
        self.destaque = None
        self.vista = self._regiao = None
        self.busca.set("")
        self.aviso_busca.set("")
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
    def _foto_da_cor(self, hex_cor):
        if hex_cor not in self._fotos:
            foto = tk.PhotoImage(master=self, width=14, height=14)
            foto.put("#8a8a8a", to=(0, 0, 14, 14))
            foto.put(hex_cor, to=(1, 1, 13, 13))
            self._fotos[hex_cor] = foto
        return self._fotos[hex_cor]

    def _itens(self):
        """O que a lista mostra: as camadas ou, separando por cor, cada cor de cada camada."""
        return self.previa.itens(por_cor=self.separar_por_cor.get())

    def _recalcular_itens(self):
        itens = self._itens()
        self._camadas = {i.chave: i for i in itens}          # chave -> camada ou cor de camada
        self.indice = {i.chave: n for n, i in enumerate(itens)}

    def _eligiveis(self):
        """O que a lista mostra: as desligadas no AutoCAD so com a caixinha."""
        return [i for i in self._itens() if self.mostrar_ocultas.get() or not i.oculta]

    def _exibidas(self):
        """As chaves que entram no desenho: as eligiveis com pontos, linhas, areas, textos,
        hachuras ou figuras."""
        return {i.chave for i in self._eligiveis() if i.tem_desenho}

    def _escolhidas_por_item(self):
        """[linhas, textos] clicados de cada linha da lista (a camada, ou a cor da camada)."""
        por_cor = self.separar_por_cor.get()
        contagem = collections.defaultdict(lambda: [0, 0])
        for gid in self.escolhidas:
            g = self.previa.grupos[gid]
            contagem[(g.camada, g.cor) if por_cor else g.camada][g.texto is not None] += 1
        return contagem

    def _linha(self, camada):
        conteudo = camada.resumo()
        if camada.oculta:
            conteudo += "  (desligada no AutoCAD)"
        linhas, textos = self._escolhidas_por_item()[camada.chave]
        if linhas or textos:
            conteudo += "  (%s)" % contar_escolhidas(linhas, textos)
        return (MARCADA if camada.chave in self.marcadas else DESMARCADA, camada.nome, conteudo)

    def _etiquetas(self, camada):
        etiquetas = []
        if camada.oculta or not camada.tem_desenho:
            etiquetas.append("apagada")
        if camada.chave in self.marcadas or any(self._escolhidas_por_item()[camada.chave]):
            etiquetas.append("marcada")
        return tuple(etiquetas)

    def _contagem_escolhidas(self):
        """(linhas, textos) escolhidos no desenho."""
        textos = sum(1 for g in self.escolhidas if self.previa.grupos[g].texto is not None)
        return len(self.escolhidas) - textos, textos

    def _atualizar_linhas(self):
        for chave in list(self._iid):
            self._atualizar_linha(chave)

    def _popular(self):
        """Recria as linhas da lista segundo a busca e a caixinha das desligadas."""
        self._silencio = True
        self.arvore.delete(*self.arvore.get_children())
        self._iid, self._nome_de = {}, {}
        texto = self.busca.get().strip().casefold()
        for camada in self._eligiveis():
            if texto and texto not in camada.nome.casefold():
                continue
            iid = "c%d" % self.indice[camada.chave]
            self._iid[camada.chave] = iid
            self._nome_de[iid] = camada.chave
            foto = self._foto_da_cor(_hex(pr.cor_na_tela(camada.cor)))
            self.arvore.insert("", "end", iid=iid, image=foto, values=self._linha(camada),
                               tags=self._etiquetas(camada))
        if self.destaque in self._iid:
            self.arvore.selection_set(self._iid[self.destaque])
        self._silencio = False
        self._atualizar_resumo()

    def nomes_na_lista(self):
        return [self._nome_de[i] for i in self.arvore.get_children()]

    def selecionada(self):
        sel = self.arvore.selection()
        return self._nome_de.get(sel[0]) if sel else None

    def _atualizar_linha(self, nome):
        iid = self._iid.get(nome)
        if iid:
            camada = self._camadas[nome]
            self.arvore.item(iid, values=self._linha(camada), tags=self._etiquetas(camada))

    def _atualizar_resumo(self):
        por_cor = self.separar_por_cor.get()
        total = len(self._eligiveis())
        n = len(self.escolhidas)
        if not self.marcadas and not n:
            self.resumo.set("Nenhuma %s marcada (de %d). Clique numa linha ou num texto do "
                            "desenho ou marque na lista."
                            % ("cor de camada" if por_cor else "camada", total))
            return
        partes = []
        if self.marcadas:
            partes.append("%d de %d %s marcadas" % (
                len(self.marcadas), total, "camadas por cor" if por_cor else "camadas"))
        if n:
            partes.append("%s no desenho" % contar_escolhidas(*self._contagem_escolhidas()))
        self.resumo.set(" e ".join(partes))

    def _ao_alternar_cor(self, *_):
        """A caixinha de separar por cor mudou: a lista passa a ter uma linha por cor (ou
        volta a ter uma por camada), e as marcas vao junto."""
        if self.previa is None or self.estado != "pronto" or self._sem_aviso_de_cor:
            return
        unidades = self.previa.unidades
        desfeitas = 0
        if self.separar_por_cor.get():
            novas = {u.chave for u in unidades if u.camada in self.marcadas}
        else:
            novas = set()
            for camada in self.previa.camadas:
                dela = [u.chave for u in unidades if u.camada == camada.nome]
                marcadas = [k for k in dela if k in self.marcadas]
                if marcadas and len(marcadas) == len(dela):
                    novas.add(camada.nome)
                elif marcadas:
                    desfeitas += 1               # so parte das cores: nao e a camada inteira
        self.marcadas = novas
        self.destaque = None
        self._recalcular_itens()
        self.detalhe.set("" if not desfeitas else
                         "%d camada(s) com so parte das cores marcada(s): a selecao foi "
                         "desfeita." % desfeitas)
        self._popular()
        self.ver_tudo()

    def _ao_alternar_ocultas(self, *_):
        """A caixinha das desligadas mudou: refaz a lista e o desenho."""
        if self.previa is None or self.estado != "pronto" or self._sem_aviso_de_ocultas:
            return
        if not self.mostrar_ocultas.get():
            # o que a lista nao mostra mais nao pode ir para a conversao
            tirar = [n for n in self.marcadas if self._camadas[n].oculta]
            for nome in tirar:
                self.marcadas.discard(nome)
            if tirar:
                self.detalhe.set("%d camada(s) desligada(s) no AutoCAD foram desmarcadas."
                                 % len(tirar))
            sumidas = {g for g in self.escolhidas if self.previa.grupos[g].oculta}
            self.escolhidas -= sumidas
            if sumidas:
                self.detalhe.set(" ".join(filter(None, (
                    self.detalhe.get(),
                    "%d linha(s) escolhida(s) em camada desligada no AutoCAD foram tiradas."
                    % len(sumidas)))))
            if self.destaque and self._camadas[self.destaque].oculta:
                self.destaque = None
        self._popular()
        self.ver_tudo()

    def alternar(self, nome):
        if nome in self.marcadas:
            self.marcadas.discard(nome)
        else:
            self.marcadas.add(nome)
        self._atualizar_linha(nome)
        self._atualizar_resumo()
        self._renderizar()

    def marcar_todas(self):
        """Marca tudo o que tem desenho entre o que a lista mostra: pontos, linhas, areas,
        textos, hachuras ou figuras. Camada so de textos entra tambem, porque os textos
        (e as hachuras) vao para a conversao pela camada marcada."""
        for nome in self.nomes_na_lista():
            if self._camadas[nome].tem_desenho:
                self.marcadas.add(nome)
            self._atualizar_linha(nome)
        self._atualizar_resumo()
        self._renderizar()

    def desmarcar_todas(self):
        """Tira as marcas das camadas que a lista mostra e todas as linhas escolhidas."""
        for nome in self.nomes_na_lista():
            self.marcadas.discard(nome)
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
        else:
            self.aviso_busca.set("")

    def selecionar(self, nome):
        if nome not in self._iid:
            self.busca.set("")
        if nome in self._iid:
            self._silencio = True
            self.arvore.selection_set(self._iid[nome])
            self.arvore.see(self._iid[nome])
            self._silencio = False
        self._definir_destaque(nome)

    def _ao_selecionar(self, _evento=None):
        if self._silencio:
            return
        self._definir_destaque(self.selecionada())

    def _definir_destaque(self, nome):
        self.destaque = nome
        if nome is None:
            self.detalhe.set("")
        else:
            camada = self._camadas[nome]
            texto = "%s: %s." % (camada.nome, camada.resumo() or "vazia")
            if camada.oculta:
                texto += " Desligada no AutoCAD: marque a caixa para levar para a conversao."
            if (camada.tem_desenho and not camada.tem_geometria
                    and not camada.contagem.get("texto")):
                texto += (" Aparece no desenho, mas o clique so escolhe pontos, linhas, areas "
                          "e textos (hachuras e figuras vao pela camada marcada).")
            self.detalhe.set(texto)
        self._renderizar()

    def _clique_na_lista(self, evento):
        """Clicar na caixinha marca e desmarca; no resto da linha, so seleciona."""
        if self.arvore.identify_column(evento.x) != "#1":
            return None
        iid = self.arvore.identify_row(evento.y)
        if iid:
            self.alternar(self._nome_de[iid])
        return "break"

    def _espaco(self, _evento):
        nome = self.selecionada()
        if nome:
            self.alternar(nome)
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
        desenhos = pr.montar_desenhos(self.previa, self._exibidas(), self.indice,
                                      marcadas=self.marcadas,
                                      com_ocultas=self.mostrar_ocultas.get(),
                                      por_cor=self.separar_por_cor.get(),
                                      linhas_marcadas=self.escolhidas)
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
        img, self.ids = pr.desenhar(
            desenhos, self.vista, largura, altura,
            destaque=self.indice[self.destaque] if self.destaque else None)
        self.imagem = img
        self._foto = tk.PhotoImage(master=self.tela, data=pr.para_ppm(img))
        self.tela.itemconfigure(self._item, image=self._foto)
        self.tela.coords(self._item, 0, 0)

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
        por_cor = self.separar_por_cor.get()
        camadas = {k[0] if por_cor else k for k in self._exibidas()}
        texto = self.previa.achar_texto(dx, dy, FOLGA_DO_TEXTO / self.vista.escala, camadas)
        if texto is not None:
            return texto
        indice = pr.camada_em(self.ids, x, y)
        if indice is None:
            return None
        item = self._itens()[indice]
        camada, cor = (item.camada, item.cor) if por_cor else (item.nome, None)
        return self.previa.achar_grupo(dx, dy, RAIO_DO_CLIQUE / self.vista.escala, camada, cor,
                                       com_ocultas=self.mostrar_ocultas.get())

    def _texto_da_linha(self, gid):
        g = self.previa.grupos[gid]
        if g.texto is not None:
            escrito = " ".join(g.texto.split())
            if len(escrito) > 60:
                escrito = escrito[:57] + "..."
            return "Texto escolhido: \"%s\", camada %s, cor %s." % (
                escrito, g.camada, dxf_estilo.nome_da_cor(g.cor))
        pecas = "1 peca" if g.pecas == 1 else "%d pecas ligadas pelas pontas" % g.pecas
        return "Linha escolhida: camada %s, cor %s, %s." % (
            g.camada, dxf_estilo.nome_da_cor(g.cor), pecas)

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
            self.marcadas = set()
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
        caixa a descartar."""
        caixa = None
        if self.previa is not None and self.previa.fora_total and self.ignorar_fora.get():
            caixa = self.previa.caixa_area
        cores, dividir = None, set()
        feicoes = {f for g in self.escolhidas for f in self.previa.grupos[g].fids}
        linhas, textos = self._contagem_escolhidas() if self.previa is not None else (0, 0)
        if self.separar_por_cor.get():
            camadas = {camada for camada, _cor in self.marcadas}
            cores = {}
            for camada, cor in self.marcadas:
                cores.setdefault(camada, set()).add(cor)
            # so sai dividida a camada que tem mais de uma cor no desenho; as linhas escolhidas
            # saem com o nome da cor, como o resto da lista
            tocadas = camadas | {self.previa.grupos[g].camada for g in self.escolhidas}
            dividir = {c for c in tocadas
                       if sum(1 for u in self.previa.unidades if u.camada == c) > 1}
        else:
            camadas = set(self.marcadas)
        return {"camadas": camadas, "cores": cores, "separar_por_cor": dividir,
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
