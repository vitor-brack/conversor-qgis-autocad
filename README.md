# Conversor QGIS ⇄ AutoCAD

Programa de janela para Windows que converte camadas vetoriais do QGIS para
desenhos do AutoCAD e vice-versa. Pensado para AutoCAD 2007 e QGIS recente.

O executável final **não precisa de Python, nem de QGIS, nem do AutoCAD
instalados** — o GDAL, o PROJ e o ezdxf vão embutidos. O manual de quem usa
o programa é o [`COMO USAR.txt`](COMO%20USAR.txt), que vai junto com o
executável.

---

## Instalação para desenvolvimento

Python 3.13 no Windows. Com o repositório clonado, dentro da pasta dele:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements.txt` tem o que o programa usa (Fiona, pyproj, ezdxf);
`requirements-dev.txt` acrescenta o PyInstaller, que gera o executável.

## Como rodar durante o desenvolvimento

```powershell
.\.venv\Scripts\python.exe -m conversor
```

Sem argumentos abre a janela. Com argumentos funciona por linha de comando:

```powershell
# QGIS -> AutoCAD
.\.venv\Scripts\python.exe -m conversor paracad campo.gpkg campo.dxf --epsg 31982 --campo-rotulo codigo

# AutoCAD -> QGIS
.\.venv\Scripts\python.exe -m conversor paraqgis campo.dxf saida.gpkg --epsg 31982
```

## Como gerar o executável

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean conversor.spec
```

Sai em `dist\ConversorGeo\`, já com o `COMO USAR.txt` ao lado do
`ConversorGeo.exe`. Copie a pasta inteira para o computador de destino e crie
um atalho para o executável.

---

## Decisões de projeto (e por quê)

As escolhas abaixo não são óbvias; todas vieram de testes contra o GDAL
real, e estão anotadas aqui para não serem desfeitas por engano depois.

### 1. DXF é o formato principal; DWG é opcional

O `.dwg` é binário e fechado. Nenhuma biblioteca livre o lê ou escreve de forma
confiável. O programa trata DXF sozinho e usa o **ODA File Converter**
(gratuito) para DWG quando ele está instalado — detecta sozinho e explica como
instalar quando não está.

O AutoCAD 2007 abre DXF nativamente, então na prática o DWG é só conveniência.

### 2. O DXF é gravado no formato AutoCAD 2004 (AC1018)

É o que o driver do GDAL emite. O AutoCAD 2007 abre esse formato sem conversão —
versões mais novas do AutoCAD leem as antigas, nunca o contrário. Não há nada a
corrigir aqui.

### 3. Acentos: o conteúdo manda sobre o que o cabeçalho declara

O DXF declara sua codificação em `$DWGCODEPAGE`, e o GDAL obedece. O problema é
que **nem todo programa cumpre o que declara**:

| Quem gerou | Bytes | Cabeçalho diz | GDAL lê |
|---|---|---|---|
| AutoCAD | ANSI | ANSI_1252 | ✅ correto |
| ODA File Converter | **UTF-8** | ANSI_1252 | ❌ `PIEZÃMETROS` |
| GDAL | UTF-8 | ANSI_1252 | ❌ `CONVENÃÃES` |

Os dois últimos são inconsistentes consigo mesmos, e foi o do ODA que quebrou
o texto no mapa real — os bytes são UTF-8, mas o cabeçalho manda lê-los como
cp1252.

Por isso `detectar_codificacao` decide pelo **conteúdo**: se o arquivo inteiro
decodifica como UTF-8 válido e tem algum acento, é UTF-8, e o GDAL é avisado
com `DXF_ENCODING=UTF-8`. Um arquivo ANSI de verdade dificilmente passa por
UTF-8 válido por acidente, então o teste é seguro nos dois sentidos. A
verificação usa um decodificador incremental: cortar o arquivo em blocos de
tamanho fixo partiria caracteres de vários bytes ao meio e daria falso
negativo.

**Na escrita** (QGIS → AutoCAD) o programa resolve a inconsistência do mesmo
jeito, deixando os bytes de acordo com o que o cabeçalho promete:

- **Transliterar (padrão):** `Seção_Geológica` → `Secao_Geologica`. ASCII puro
  não depende de codepage nenhum, então é imune ao problema.
- **Preservar acentos:** grava em cp1252 de verdade, que é o que o cabeçalho
  declara e como o próprio AutoCAD grava.

Grau, mais-ou-menos e diâmetro são caso à parte: em modo ASCII viram `%%d`,
`%%p` e `%%c`, as sequências do AutoCAD. O arquivo continua ASCII puro, o
AutoCAD desenha o símbolo e o GDAL o reconstrói na leitura, então `45°`
sobrevive à ida e à volta.

Os acentos originais também ficam intactos no `.csv` de atributos.

### 4. A cor vem de cada ENTIDADE, não da camada

Num mapa geológico cada cor significa uma litologia — calcário, arenito,
basalto. Errar a cor não é detalhe estético: troca uma rocha por outra. Um
desenho real tem quatro origens de cor, e ler só a tabela `LAYER` acerta
apenas a primeira:

| Caso | O que é |
|---|---|
| ByLayer | a entidade herda a cor da camada |
| cor própria | o desenhista pintou aquela linha de vermelho |
| cor verdadeira | RGB de 24 bits (grupo 420), fora da paleta indexada |
| dentro de bloco | a peça herda a cor do `INSERT`, ou tem a sua |

O GDAL já resolve os quatro e entrega o resultado na *style string* do OGR
(`PEN(c:#ff0000)`, `LABEL(...,s:2.5g,c:#0000ff)`). O Fiona não a expõe, mas o
GDAL a devolve como coluna quando a fonte é consultada por SQL — então
`abrir_entidades` envolve o DXF num **VRT** que faz
`SELECT *, OGR_STYLE FROM entities`. Dali saem a cor e, nos textos, o tamanho.

**Blocos.** Por padrão o GDAL funde as peças de um bloco numa geometria só, e
todas passam a ter UMA cor — uma seta verde com ponta vermelha chega
inteiramente verde. `DXF_MERGE_BLOCK_GEOMETRIES=FALSE` desliga a fusão.

**No projeto**, cada camada com mais de uma cor vira um renderizador
**categorizado** pelo campo `cor_cad`, gravado junto com os dados. Cada tom
aparece como uma categoria separada na legenda do QGIS, e dá para renomear
"#a52a2a" para "Calcário" ali mesmo. A cor dos rótulos é *data-defined* pelo
mesmo campo, senão um título vermelho sairia preto junto com o resto.

**Sobre a paleta ACI.** Ela é usada só como reserva, se o VRT falhar — e foi
**extraída** do driver do GDAL, não deduzida. Uma tentativa anterior de gerá-la
por fórmula (24 matizes × 5 brilhos × 2 saturações) errou **223 dos 255
índices**, e pior: parecia correta, porque foi conferida contra valores
lembrados de cabeça em vez de contra uma fonte real. O teste atual desenha as
255 cores num DXF e compara com o que o GDAL devolve, uma a uma.

O índice 7 é "branco" no AutoCAD, que aparece preto sobre fundo claro. Como o
fundo do QGIS é branco, o GDAL já o entrega como preto — senão a camada sumiria.

Códigos de formatação de MTEXT (`{\fArial|b0;...}`, `\P`, `%%d`) não precisam
de tratamento: o GDAL os resolve na leitura.

### 5. O programa gera também um arquivo de projeto `.qgs`

`.qgs` e `.qgz` **não são formatos de dados** — são projetos. Guardam quais
camadas estão abertas, cores e layout, e *apontam* para os arquivos de dados,
que ficam fora deles. Quem procura os dados em "Projeto → Abrir Projeto" não
acha, porque o menu certo é "Camada → Adicionar Camada Vetorial".

Essa confusão é previsível o bastante para valer a pena resolver em código em
vez de na documentação: o programa grava um `.qgs` junto com os dados, já
apontando para eles com caminho relativo. Dois cliques e o QGIS abre com tudo
carregado e o mapa enquadrado.

Como usa caminho relativo, a pasta inteira pode ser copiada para outro
computador. Mas o `.qgs` sozinho não serve — precisa dos dados ao lado.

**Armadilha que custou caro:** o QGIS só lê o bloco `<projectCrs>` se a
propriedade `SpatialRefSys/ProjectionsEnabled` estiver ligada em
`<properties>`:

```xml
<SpatialRefSys><ProjectionsEnabled type="int">1</ProjectionsEnabled></SpatialRefSys>
```

Sem ela o QGIS considera as projeções desabilitadas e **ignora o `<projectCrs>`
inteiro, sem reclamar**: o projeto abre, as camadas aparecem, mas o projeto
fica sem sistema de coordenadas e a escala na barra de status vira um número
sem sentido (1:219986512). Não dá para descobrir isso lendo o XML — só abrindo
no QGIS e perguntando `QgsProject.instance().crs()`.

O enquadramento inicial vai em dois lugares: `<mapcanvas><extent>` (QGIS
antigo) e `<ProjectViewSettings><DefaultViewExtent>` (QGIS 3.18+). O QGIS 3.44
já não grava `<mapcanvas>`, mas ainda o aceita, então manter os dois cobre mais
versões.

Ver `conversor/qgis_project.py`.

### 6. Texto de CAD precisa de posição exata, não de "rótulo de mapa"

O QGIS trata texto como rótulo: por padrão escolhe onde colocar. Texto de CAD
tem um ponto de ancoragem exato, um alinhamento (esquerda/centro/direita ×
base/meio/topo), uma altura, uma rotação e às vezes uma largura comprimida.
Ignorar isso empilhou palavras e desalinhou o carimbo do mapa real.

O projeto usa propriedades **definidas por campo** — posição (`$x`, `$y`),
alinhamento, tamanho, rotação, largura e cor — que é também como o importador
de DWG do próprio QGIS faz. `textos_cad.py` calcula os valores.

Quatro armadilhas, todas medidas:

- **O ponto que o GDAL entrega nem sempre é a âncora.** Para texto
  justificado ele devolve o início do texto e põe o ponto de alinhamento real
  num deslocamento (`dx`, `dy`) da style string. Só que, para texto alinhado à
  esquerda, o AutoCAD grava esse segundo ponto como `(0, 0)`, e o GDAL devolve
  o deslocamento até a origem mesmo assim. Aplicar o deslocamento cegamente
  manda o texto para quilômetros de distância. Regra: só aplicar quando a
  ancoragem não é a 1 (base-esquerda). A ancoragem 1 também é o que o GDAL usa
  para texto "alinhado"/"ajustado", que começa no primeiro ponto. O
  deslocamento vem com 6 algarismos significativos — erro de centésimos de
  milímetro.
- **Altura no AutoCAD é a da maiúscula; no QGIS é a da caixa da fonte.** Na
  Arial a maiúscula mede 0,7167 do tamanho (medido com `QFontMetricsF`), então
  o tamanho no QGIS é a altura do CAD ÷ 0,7167. Sem isso tudo sai ~30% menor.
  O tamanho é por texto, não por camada: um logotipo com letras grandes numa
  camada de letras pequenas saía encolhido.
- **Rotação:** o AutoCAD mede no sentido anti-horário, o QGIS no horário —
  daí `360 - ângulo`. E o QGIS por padrão desvira rótulos de cabeça para baixo;
  `upsidedownLabels=2` impede.
- **MTEXT de largura fixa chega numa linha só.** O GDAL ignora a largura do
  quadro (grupo 41), e as quebras são calculadas aqui, palavra a palavra, como
  o AutoCAD faz. A largura de cada palavra é medida **na fonte do próprio
  trecho**, pela altura da maiúscula e pelo fator de largura do estilo — o
  ezdxf lê o arquivo da fonte (`cad_ezdxf.medir`). Medir tudo na Arial, como
  era antes, punha palavras na linha errada no carimbo real (Times New Roman
  num estilo de largura 1,4). A margem é estreita: num título de 4 linhas, 2%
  de erro na medida já muda uma palavra de linha. Trecho sem fonte própria é medido
  com as larguras da Arial extraídas do Qt, que é como o QGIS o desenha.
  Sem o ezdxf, `textos_cad.quebrar` faz o mesmo só com a Arial, e só para
  MTEXT fora de bloco (o GDAL devolve o handle do `INSERT`).

**"Topo" e "meio" não são a mesma coisa nos dois programas.** A linha de base
os dois concordam, mas o AutoCAD mede o topo pela MAIÚSCULA e o QGIS pela
caixa da fonte, que sobra acima dela. Medido (altura 10, só maiúsculas):

| Ancoragem | Linha de base no AutoCAD | No QGIS sem correção |
|---|---|---|
| Topo (TEXT e MTEXT) | 10 abaixo da âncora | 12,6 abaixo |
| Meio do MTEXT | 3,6 abaixo | 4,7 abaixo |
| Embaixo | 2,8 **acima** | 3,1 acima |

A referência do AutoCAD veio do renderizador do ezdxf, que o reproduz; a do
QGIS, das caixas que ele mesmo devolve (`QgsLabelingResults`): em volta da
linha de base vão de −0,215 a +0,905 do tamanho. `correcao_vertical` calcula
a diferença e o ponto sobe (ou desce) na direção do próprio texto. É o que
vale para TEXT, que tem sempre uma linha e é sempre em Arial.

**Texto de várias linhas: cada linha é uma feição.** O QGIS não consegue
reproduzir o espaçamento entre as linhas de um MTEXT, e isso foi medido — não
pela caixa que ele informa, mas pela tinta: linhas de "HHHHHH" (sem partes
acima ou abaixo, então a mancha vai exatamente da base ao topo da maiúscula),
renderizadas e localizadas pixel a pixel.

- **A altura de linha vinda de campo é ignorada.** Nas versões 3.44 e 4.2,
  em porcentagem ou em unidades do mapa, o valor por feição não tem efeito
  nenhum; só vale a altura fixa da camada. O espaçamento ficava sempre o
  padrão da fonte: 1,56–1,58 altura de letra, contra 1,667 do AutoCAD. Num
  texto de 4 linhas, a última saía 0,3 letra fora do lugar. Os testes antigos
  mediam a caixa do rótulo inteiro com folga e nunca pegaram.
- **O espaçamento padrão muda com a fonte e com a versão**: Bookman ocupa de
  4 a 10% mais que Arial, de um jeito no 3.44 e de outro no 4.2.
- **`<br>` entre dois trechos formatados é descartado.** O QGIS só quebra no
  `<br>` que fica *dentro* de um `<span>`; entre dois
  (`<span>…</span><br><span>…</span>`, que é como cada linha era montada) ele
  some e cola a última palavra de uma linha na primeira da seguinte. Foi o
  "daJazida" / "Planode" do carimbo real. Quebra de linha comum também não
  serve: o HTML a transforma em espaço.

Então `_preparar_texto` separa as linhas, e `textos_cad.linhas_de_base`
calcula, pela regra do AutoCAD, onde fica a linha de base de cada uma: a
caixa do MTEXT vai do topo da maiúscula da primeira linha até 0,2778 da
altura abaixo da base da última, e as linhas se sucedem a 5/3 da altura
(vezes o fator de espaçamento do MTEXT). Cada linha é um rótulo apoiado na
sua base (alinhamento "Base", que para uma linha só é exato). Medido de novo
com os "HHHHHH": erro de 0,000 a 0,02 altura de letra, passo de 1,667 em
Arial simples, Arial em HTML e Bookman em HTML, ancorados em cima, no meio e
embaixo, nas duas versões. Na tabela de atributos, um MTEXT de 3 linhas
aparece como 3 feições com o mesmo `EntityHandle`.

**MTEXT formatado vira rótulo em HTML.** Cor, fonte, negrito, itálico,
sublinhado e riscado trocados no meio do texto (`{\fArial Rounded MT
Bold|b1;\C5;Geo\C3;sana}`) são lidos pelo `MTextParser` do ezdxf e viram
`<span style="...">` no campo `txt_html`. O QGIS mostra HTML em rótulos desde
a 3.14; conferido que convive com a posição e o alinhamento por campo nas
versões 3.44 e 4.2. Só a camada que tem algum texto formatado usa HTML; as
outras continuam com o texto puro. Os MTEXT do ezdxf são associados aos do
GDAL pela posição de inserção — inclusive dentro de blocos, onde o GDAL dá o
handle do INSERT e não o do MTEXT.

Cuidado ao mexer: o contexto do ezdxf já nasce com a fonte `'sans-serif'`.
Tratada como escolha do desenho, ela marcava todo MTEXT como formatado.

**O nome da fonte é traduzido para a família instalada.** O AutoCAD aceita
a fonte de um trecho escrita de vários jeitos: a família
(`\fBookman Old Style|b1`), o arquivo (`bookosb.ttf`, com ou sem extensão) ou
o nome completo (`Bookman Old Style Bold`). O QGIS só entende a família; com
qualquer outro nome desenha numa substituta — no Windows, uma com cara de
Times New Roman — e sem o negrito, que vinha do arquivo.
`cad_ezdxf.resolver_fonte` usa a lista de fontes que o ezdxf monta a partir do
Windows e acha a família pelo nome, pelo arquivo ou pelo começo do nome
completo. Fonte que não está instalada fica em Arial (com o negrito do código),
nunca na substituta.

Cuidado com diagnóstico de fonte pela aparência. Numa captura de tela, o
carimbo do mapa real parecia Bookman negrito no AutoCAD e Times no QGIS; o
arquivo mostra Times New Roman **normal** (`\fTimes New Roman|b0`) num estilo
de largura 1,4 — a Times esticada 40% engrossa as hastes e parece negrito, e
o QGIS já usava a fonte certa. A tradução de nomes continua valendo, porque
os outros formatos existem; mas a fonte se confere no arquivo.

Detalhe do ezdxf 1.4.4 para quem for usar a lista: `find_best_match` compara
só o **começo** do nome ("Arial" casa com "Arial Narrow") e filtra pelo
estilo antes do peso, então pede a Bookman "Regular" para um texto marcado
negrito. Por isso o índice próprio, por nome exato.

**Fator de largura não vai para o QGIS.** Letra esticada ou comprimida (o
fator de largura do estilo) o QGIS desenha errado nas duas versões, de jeitos
opostos:

| Fator | QGIS 4.2 | QGIS 3.44 |
|---|---|---|
| acima de 1 (carimbo, 1,4) | afasta as letras sem esticá-las ("E m p r e e n d e d o r") | estica as letras sem afastá-las; elas se atropelam |
| abaixo de 1 (títulos das plantas, 0,85; cotas das curvas, 0,9) | encavala as letras e some com os espaços ("PLANTAESQUEMÁTICA…") | espalha as letras e passa da largura |

Todo texto sai com a largura normal da fonte; o fator fica no campo
`txt_larg` só como informação, e as quebras de linha continuam calculadas com
a largura do desenho. No mapa real isso fica bem: os títulos das plantas são
Verdana a 85%, e a Arial na largura normal tem quase a mesma largura. Num
estilo muito comprimido (há rótulos a 55% no LOTEAMENTO) o texto sai bem mais
largo que no AutoCAD.

Os textos vão para camadas `<camada>_Texto`, com renderizador `nullSymbol`
(só o rótulo, sem a bolinha do ponto de inserção) e sem contorno branco.

`testes/verificar_textos_no_qgis.py` abre o projeto no QGIS, renderiza e
confere, pela regra do AutoCAD, onde ficou a linha de base de cada texto — e
de cada linha de cada MTEXT.

### 7. Hachuras, polígonos e imagens

**Hachuras são lidas pelo ezdxf, não pelo GDAL** (`cad_ezdxf.py`). O GDAL
falha em dois pontos que num mapa geológico importam muito:

- **O padrão se perde.** O GDAL entrega só a borda da hachura. As cruzes de um
  perfil, os traços de uma bacia, o cascalho de um rejeito — tudo o que
  distingue uma litologia da outra na legenda — sumiam.
- **Borda com curva some.** Se a borda tem um trecho em spline (o perfil do
  terreno, por exemplo), o GDAL não fecha o polígono e devolve só as linhas
  do contorno. A hachura do perfil chegava como uma linha por cima da própria
  curva, sem preenchimento nenhum.

O ezdxf gera as linhas reais do padrão a partir da definição gravada na
própria HATCH (ângulo, origem, deslocamento entre linhas e traços de cada
família), recortadas pela borda — exatamente o que o AutoCAD desenha. Elas vão
para camadas `<camada>_Textura`, uma feição por hachura, com traço fino
(0,13 mm). Hachura sólida vira polígono preenchido em `<camada>_Hachura`.

O recorte do padrão pela borda é feito aqui (`_bordas`, `_dentro`), e não
pelo ezdxf, que erra em quatro pontos — todos achados no PLOT.dwg real:

- **Ordem dos cruzamentos.** Cada linha do padrão entra e sai da hachura onde
  cruza a borda; o ezdxf ordena os cruzamentos comparando x e, só no empate,
  y, arredondados a 10 casas. Numa linha **vertical** todos têm o mesmo x a
  menos de resíduos na 13ª casa, e de vez em quando o resíduo decidia a
  ordem: um trecho de fora virava de dentro. Foram os traços verticais soltos
  no meio da escavação do perfil futuro. Aqui a ordem é a posição **ao longo
  da linha**.
- **Sorteio.** Para fugir de linha passando por vértice, o ezdxf desloca o
  padrão por um valor aleatório — e cada conversão errava num lugar diferente,
  com os traços soltos em outras colunas a cada vez. Aqui não
  há sorteio: vértice exatamente sobre a linha segue a regra do "meio aberto"
  (conta como acima dela), e o resultado é sempre o mesmo.
- **Borda remendada.** Uma borda de arestas devia vir encadeada, e nem sempre
  vem: a do perfil futuro tem a curva do terreno **duas vezes**, uma em cada
  sentido, e as arestas fora de ordem (resto de edições do contorno
  associativo). O ezdxf liga as arestas na ordem gravada e fecha os vãos com
  retas que atravessavam o perfil, criando uma fatia ao longo do topo com
  pedacinhos das cruzes. Aqui a próxima aresta é a que tem a ponta mais
  perto, e a curva repetida sai (as duas cópias se anulam na contagem de
  dentro/fora, mas achatadas separadamente deixavam uma fresta de um
  milésimo).
- **Aresta isolada fechada.** `from_hatch_edge_path` fecha todo caminho, até
  o de uma aresta só — uma linha vira ida e volta e se anula. `_aresta` tira o
  retorno.

Nas nove hachuras de borda bem formada do PLOT real o resultado é idêntico ao
do ezdxf, traço por traço; só a do perfil futuro muda (194 → 177 traços: os
que sobravam fora do solo).

Mais três cuidados:

- **Bug do ezdxf 1.4.4 com bloco espelhado:** em hachura de bloco espelhado
  (sistema de coordenadas invertido), `hatching.hatch_entity` devolve cada
  linha duas vezes — uma no lugar e outra espelhada fora do desenho — porque
  falta um `else`. `_linhas_do_padrao` converte para o sistema do desenho uma
  vez só.
- **Cor pelas regras do AutoCAD**, resolvida à mão: cor verdadeira > índice
  próprio > ByBlock (cor do INSERT) > ByLayer; dentro de bloco, o que está na
  camada 0 assume a camada do INSERT. Conferido contra o GDAL nas sólidas.
- **Nunca sumir:** padrão denso demais (mais de 250 mil traços) ou hachura sem
  a definição do padrão gravada saem como tinta translúcida, como antes. Se o
  ezdxf nem carregar, o conversor volta a usar as hachuras do GDAL e avisa no
  log o motivo.

Para não pesar em desenho grande, o ezdxf lê uma **cópia filtrada** do DXF só
com HATCH, MTEXT e INSERT na seção ENTITIES — as curvas de nível, que são o
grosso do arquivo, ficam de fora. A cópia vai em UTF-8 com a codificação
informada explicitamente (`readfile(encoding="utf-8")`): o ezdxf, como o
GDAL, obedece o `$DWGCODEPAGE` e embaralharia os acentos do ODA. Escapes
`\U+XXXX` também não servem: o ezdxf não os desfaz ao ler.

Sólidas e texturas ficam por baixo das linhas do desenho, texturas acima das
sólidas — a convenção do AutoCAD, que manda a hachura para trás do contorno.

**SOLID e TRACE** (o triângulo cheio das pontas de seta de cota, setas,
marcadores) chegam do GDAL como polígono pintado, igual a uma hachura sólida.
Numa versão anterior, "pintado" passou a ser descartado para o ezdxf cuidar
— mas o ezdxf só lê HATCH, e as pontas de seta sumiram de todas as cotas. Só
o que é HATCH de verdade (subclasse `AcDbHatch`) vai para o ezdxf; o resto
vai para `<camada>_Hachura`, pintado.

**Pontos de definição de cota** ficam de fora. O AutoCAD os põe na camada
`Defpoints` para montar a cota (o vértice e os pontos das retas de um ângulo,
por exemplo) e nunca os imprime; no QGIS viravam bolinhas nos cantos da
cota. Só os pontos: uma hachura ou linha que alguém pôs na Defpoints aparece
na tela do AutoCAD, então continua aparecendo.

**Polígonos do QGIS** eram gravados pelo GDAL como hachura sólida: no AutoCAD,
cada unidade virava uma mancha preenchida escondendo tudo embaixo. Agora
saem como polilinhas fechadas (`DXF_WRITE_HATCH=FALSE`). O buraco de um
polígono vira um contorno à parte — o DXF não tem como dizer que uma
polilinha é o buraco de outra.

**Polilinhas fechadas como áreas:** o GDAL 3.9 embutido ignora
`DXF_CLOSED_LINE_AS_POLYGON`, então a opção da tela nunca funcionou. A
conversão agora é feita em `convert.py` (o GDAL repete o primeiro vértice nas
fechadas). Fica **desligada por padrão**: num mapa potenciométrico, curvas que
se fecham em torno de um ponto não são áreas.

**Imagens** (`IMAGE`) o GDAL descarta sem aviso. `dxf_extras.py` lê a entidade
(canto, vetores de pixel, tamanho) e o `IMAGEDEF` (caminho do arquivo);
`imagens_cad.py` acha o arquivo — pelo caminho gravado, relativo ao desenho
original, ou só pelo nome na pasta do desenho —, copia para junto dos dados e
escreve o arquivo de mundo (`.pgw`/`.jgw`/`.tfw`) e um `.aux.xml` com o
sistema de coordenadas. Se o arquivo tiver outra resolução, o quadro é mantido
e o pixel é recalculado, como o AutoCAD faz. Imagem não encontrada é avisada
no log. O recorte (clipping) da imagem não é aplicado.

### 8. Textos são escritos à mão no arquivo

O driver DXF do GDAL **descarta silenciosamente o campo `Text`** na escrita — o
texto não chega ao arquivo. Para rotular pontos (`AM-01`, `AM-02`...) o
programa injeta entidades `TEXT` diretamente na seção `ENTITIES`, com handles a
partir de `0xF00000` para não colidir com os que o GDAL emite. Ver
`conversor/dxfio.py`.

### 9. O que o AutoCAD não mostra fica escondido no QGIS

Achado no Desm_Ext.Condomínio, que no QGIS abria enquadrando **3.700 km**,
com o desenho de verdade como um pontinho num canto. Eram duas coisas que o
GDAL entrega misturadas com o desenho:

- **Camadas desligadas ou congeladas.** 69% das entidades do Condomínio
  (1.038 de 1.497, quase todas pontos de levantamento em coordenadas
  absurdas) estavam em camadas desligadas: o AutoCAD não as mostra. O GDAL as
  entrega com a cor inteiramente transparente (`#rrggbb00`), e a
  transparência era jogada fora — viravam pontos pretos e laranja. Agora
  `analisar_estilo` marca `oculta`, a camada vem para o QGIS **desmarcada**
  (os dados estão lá; é só marcar a caixinha) e não conta no enquadramento.
  Camada desligada o AutoCAD grava com a cor negativa, que o GDAL não
  resolve (entrega preto): a cor vem da tabela de camadas. As hachuras, lidas
  pelo ezdxf, e as imagens são marcadas pela tabela de camadas
  (`dxf_estilo.camadas_ocultas`). Escondida misturada com visível no mesmo
  grupo (entidade de um bloco inserido em camada congelada) ganha um grupo
  `<camada>_oculto`.
- **Espaço de papel.** A moldura, o carimbo e o logotipo da aba Layout estão
  em coordenadas de papel, sem nenhuma relação com as do mapa — no
  Condomínio, perto da origem, a 7.000 km do mapa. Na aba Model, que é o
  desenho, não aparecem. O GDAL os marca (`PaperSpace`) e os mistura; ficam
  de fora, com aviso no log — a não ser que o desenho só tenha espaço de
  papel, e aí a folha é o desenho.

Uma ideia descartada: abrir o QGIS na vista que o AutoCAD salvou no arquivo
(a tabela VPORT). No Condomínio seria perfeito, mas numa das saibreiras a
vista salva é um detalhe ampliado e no LOTEAMENTO está deslocada. O
enquadramento continua sendo o do desenho — só do que aparece.

### 10. Estilo de ponto

O AutoCAD desenha os pontos (`POINT`) conforme duas variáveis do cabeçalho:
`$PDMODE` (0 pingo, 1 nada, 2 cruz, 3 xis, 4 tracinho; +32 círculo em volta,
+64 quadrado) e `$PDSIZE` (tamanho em unidades do desenho; zero ou negativo é
uma fração da altura da tela). `qgis_project._simbolo_ponto` monta o mesmo
símbolo com camadas de marcador do QGIS. As medidas são as do AutoCAD, que o
ezdxf reproduz (`ezdxf.render.point`): círculo e quadrado com `PDSIZE` de
lado, **cruz e xis com o dobro** — os braços saem do círculo —, tracinho de
meio `PDSIZE` para cima. Tamanho absoluto vai em unidades do mapa; o relativo
à tela, em milímetros (5% de uma janela de ~160 mm). Conferido pixel a pixel
contra o desenho do ezdxf.

### 11. Largura da letra: encolhe até caber, olhando os vizinhos

Sem o fator de largura (ver a seção 6), letra comprimida sai mais larga que
no AutoCAD. No carimbo do INCRA do LOTEAMENTO, com rótulos a 57%
("Matrículas/Transcrições:", "Escala:", "Resp. Téc:"), cada rótulo
atropelava o valor ao lado. A letra encolhe até no máximo 15% além da
largura que o texto tem no AutoCAD (`FOLGA_LARGURA`). A folga existe porque
a fonte do QGIS nunca é a do AutoCAD e diferenças desse tamanho aparecem em
qualquer texto: com ela, os títulos do PLOT (Verdana a 85%, que na Arial
ficam 16% mais largos) e os números das curvas (90%) não mudam.

**A largura no AutoCAD é medida na fonte de verdade.** O GDAL informa a fonte
TrueType do estilo (`f:` na style string), mas escreve "Arial" para os
estilos de fonte de traço (`.shx`). `dxf_estilo.fontes_dos_textos` lê o
estilo de cada TEXT e atributo direto do DXF: pelo handle, ou, para texto de
dentro de bloco, pelo handle do INSERT e pelo texto igual no bloco. A
`simplex` e a `romans` são a "Roman Simplex" das fontes Hershey (domínio
público), e `textos_cad` tem a largura de cada letra — com o espaço de 21
unidades do AutoCAD, e não o de 16 da Hershey. Conferido com o que o próprio
AutoCAD gravou no LOTEAMENTO (onde começa um texto alinhado pela direita ou
pelo centro): "RS " dá 62 unidades pela tabela e no desenho; o nome do
proprietário, de 12 caracteres, 232 e 233. As fontes de traço sem tabela
(`txt`, `romanc`, `isocp`...)
continuam medidas pela Arial, como antes (`convert._encolher`).

**Texto com vão para atributo.** No quadro de situações cartográficas do
LOTEAMENTO, o texto é "MERIDIANO CENTRAL    %%d WGr" (simplex a 83%), com o
atributo 45 nos quatro espaços. O espaço da simplex é duas vezes e meia o da
Arial, e na Arial o "CENTRAL" passava por cima do 45. `_pecas_do_texto`
divide o texto alinhado à esquerda onde há dois ou mais espaços seguidos, e
cada trecho vira um rótulo que começa onde começa no AutoCAD.

**Vizinhos e grupos.** `_ajustar_textos` roda depois de lidos todos os
textos de fonte conhecida. Se há outro texto logo adiante na mesma linha, o
texto não ocupa mais que 45% do vão entre os dois (`FRACAO_DO_VAO`; o vizinho
também pode crescer na direção dele). E textos da mesma fonte, fator de
largura e altura saem com a letra do mais apertado deles, como as linhas de
um carimbo, que no AutoCAD têm todas a mesma altura. No quadro do LOTEAMENTO
tudo saiu a 88% da altura (antes, 95%, com o 45 encavalado e o "MERCATOR"
passando da borda do quadro); os rótulos do INCRA, a 65% (antes, 66%). Nos
outros quatro desenhos de teste nenhum texto mudou de tamanho nem de lugar.

### 12. Quem fica por cima: a ordem de desenho do AutoCAD

No AutoCAD, onde duas linhas passam uma por cima da outra, vê-se a que foi
desenhada **depois** — na ordem do arquivo, ou na que o "trazer para
frente/mandar para trás" (DRAWORDER) gravou na tabela `SORTENTSTABLE`. No
QGIS, cada camada do AutoCAD é uma camada, e a de cima no painel cobre as de
baixo; entre camadas de linha a ordem era alfabética. No Desm_Ext.Condomínio o
contorno dos lotes existe duas vezes — roxo na camada "0" e verde na
"terreno", desenhada depois —, e uma linha de cota azul na "terreno" cobre uma
roxa na "0". O AutoCAD mostra verde e azul; o QGIS mostrava roxo nos dois.

`_ordem_das_linhas` procura, com uma grade de busca, os trechos em que linhas
de **cores diferentes** de camadas diferentes andam juntas, e cada trecho vale
um voto, do tamanho dele, para a camada que o AutoCAD desenha por cima
(`dxf_estilo.ordem_de_desenho` lê a tabela; conferido contra o ezdxf). As
camadas seguem os votos — os mais fortes primeiro, sem criar ciclo — e as que
não disputam nada ficam na ordem alfabética. Dentro de cada camada, as
feições vão para o arquivo na ordem de desenho, e o QGIS as desenha nela.
Custa menos de meio segundo nos desenhos de teste. No PLOT a ordem mudou só
onde havia disputa (a camada "0", que já era a primeira, e um metro de
fotogrametria sobre as curvas de nível), nada visível.

Limite: a ordem é por camada. Se a camada A cobre a B num lugar e a B cobre a
A em outro, vale o lado com mais metros sobrepostos.

---

## Limitações conhecidas

- **O DXF não tem tabela de atributos.** Ele só guarda `Layer`, `Linetype`,
  `Text` e mais alguns campos fixos. Indo para o AutoCAD, os atributos são
  salvos num `.csv` ao lado do desenho, porque não há onde colocá-los no
  desenho. Não é contornável: é uma limitação do formato.
- **O DXF não guarda o sistema de coordenadas.** Por isso o programa grava um
  `.prj`, um `.crs.txt` e um `.conversor.json` ao lado, e lê esses arquivos de
  volta na conversão inversa. Se o desenho vier de outra pessoa, sem esses
  arquivos, o sistema precisa ser informado à mão — não há como adivinhar.
- **A fonte é Arial**, a não ser que o MTEXT escolha outra no próprio texto
  (e ela esteja instalada). Desenhos do AutoCAD usam muito fontes SHX (`txt`,
  `romans`), que o QGIS não lê, e a fonte do estilo de texto não é
  transferida. Como cada texto fica ancorado no ponto e alinhamento certos, a
  diferença de largura aparece só nas pontas, não desloca o texto; na
  `simplex` e na `romans`, que são medidas, o texto ainda encolhe se fosse
  encostar no vizinho (seção 11). Num MTEXT sem fonte própria, as quebras de
  linha podem cair em palavras diferentes das do AutoCAD.
- **Letra esticada** (fator de largura do estilo acima de 1) sai com a
  largura normal, mais estreita que no AutoCAD. **Comprimida**, sai mais
  baixa: encolhe até caber (seção 11).
- Na fonte que não é Arial, a maiúscula pode sair alguns por cento menor
  que no AutoCAD (Bookman: 0 a 5%): o tamanho é convertido pela proporção
  da Arial.
- Ponto com tamanho relativo à tela (`$PDSIZE` zero ou negativo) usa uma
  janela de AutoCAD de ~160 mm de altura como referência; no AutoCAD ele
  muda com o tamanho da janela.
- A folha de impressão (espaço de papel) não vem: no QGIS, ela se refaz no
  layout de impressão.
- **Altura trocada no meio de um MTEXT** (`\H2x;`) não é aplicada; cor, fonte,
  negrito, itálico, sublinhado e riscado são.
- Linhas tracejadas saem contínuas; o `Linetype` fica guardado como atributo,
  mas não vira padrão de traço.
- Espessuras de linha (lineweight) não são transferidas.
- Blocos (`INSERT`) são convertidos em geometria solta, não em símbolos.
- A textura de uma hachura é geometria fixa: é o padrão como o AutoCAD o
  desenharia naquela escala, não um estilo do QGIS que se possa trocar.
- Imagem com recorte (clipping) aparece inteira.

## Estrutura

```
conversor/
  convert.py       motor: lê, reprojeta, grava (nenhuma dependência de interface)
  dxfio.py         detalhes do formato DXF: codificação, entidades TEXT, CRS ao lado
  qgis_project.py  gera o .qgs: aponta para os dados, cores e rótulos
  dxf_estilo.py    cor e estilo de cada entidade, codificação
  dxf_extras.py    o que o GDAL não entrega: largura de MTEXT e imagens
  cad_ezdxf.py     o que o GDAL entrega errado: hachuras, MTEXT formatado, fontes
  textos_cad.py    posição, alinhamento e tamanho de texto de CAD no QGIS
  imagens_cad.py   copia e georreferencia as imagens do desenho
  dwg.py           integração com o ODA File Converter
  crs_presets.py   sistemas de coordenadas brasileiros
  config.py        lembra as últimas escolhas
  gui.py           janela (tkinter)
testes/            testes automatizados
executar.py        ponto de entrada que o PyInstaller empacota
conversor.spec     receita do PyInstaller
COMO USAR.txt      manual de quem usa o programa (vai junto com o executável)
```

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

São testes de pytest (`testes/test_*.py`). Rodam em cerca de um minuto e não
precisam do QGIS, do AutoCAD nem do ODA File Converter. Para um arquivo só,
passe o caminho: `-m pytest testes\test_casos.py`. A cada push o GitHub
Actions roda os mesmos testes (`.github/workflows/ci.yml`).

Dois testes usam fontes que vêm com o Office, não com o Windows (Bookman Old
Style e Arial Rounded MT Bold), e são pulados onde elas não estão instaladas:
o que confere a fonte do logo e o do carimbo em Bookman, ambos em
`test_texturas`. O resto não depende de fonte nenhuma.

`test_ida_volta` faz um ciclo completo QGIS → AutoCAD → QGIS e confere se as
coordenadas voltam idênticas. `test_casos` cobre reprojeção, acentos, arquivos
sem `.prj`, desenhos vazios e a construção da janela (que nasce escondida:
nada aparece na tela). `test_projeto_qgs` valida a estrutura do `.qgs` gerado.
`test_estilo` confere a cor de cada entidade e os acentos. `test_carimbo`
confere ancoragem, tamanho e rotação de cada texto de um carimbo, hachuras e
imagens; `test_texturas`, as texturas de
hachura (inclusive com borda em spline e em bloco espelhado), o logo formatado,
um carimbo em fonte de carimbo num estilo largo, com a fonte gravada de cada
jeito que o AutoCAD aceita, quebras escritas e um título que o próprio AutoCAD
quebra — as linhas têm de sair iguais às do AutoCAD, cada uma na sua linha de
base —, um perfil futuro com a borda remendada como a do PLOT.dwg (todo traço
do padrão tem de cair no solo; o recorte antigo deixava 74 fora), uma cota com
SOLID e pontos de definição, e um título comprimido. `test_camadas` cobre o
que veio dos outros desenhos: camadas desligadas e congeladas (desmarcadas,
fora do enquadramento, com a cor da camada), a folha do espaço de papel, o
estilo de ponto `$PDMODE 34`, um rótulo a 57% que não pode invadir o valor
ao lado, dois pares de linhas sobrepostas em que a ordem alfabética erraria
(um decidido pela ordem do arquivo, outro pela tabela `SORTENTSTABLE`) e uma
cópia do quadro de situações cartográficas do LOTEAMENTO (simplex a 83% num
bloco a 75%, com o 45 no vão de "MERIDIANO CENTRAL    %%d WGr" e a primeira
linha rente à borda); `verificar_camadas_no_qgis.py` confere o mesmo
desenhado pelo QGIS, pixel a pixel no caso dos pontos e da cor das linhas
sobrepostas, e pelos retângulos dos rótulos no caso do quadro.

Para comparar com o AutoCAD sem ter o AutoCAD, o desenhador do ezdxf
(`ezdxf.addons.drawing`, com matplotlib) serve de referência: ele reproduz
estilo de ponto, fator de largura e camadas escondidas. Atenção ao fundo:
pintar o fundo de branco não basta, a cor 7 continua sendo resolvida como
branca; é preciso `ctx.current_layout_properties.set_colors("#ffffff")`.

### Os desenhos de verdade

Os desenhos reais usados no desenvolvimento (o PLOT.dwg e outros quatro) são
de clientes e **não estão no repositório**: ficam na pasta local
`Arquivos de testes`, que o `.gitignore` deixa de fora. Para usar o
verificador, ponha nela os seus próprios `.dwg` ou `.dxf` (ou passe outra
pasta). `testes/verificar_desenhos_reais.py` converte cada um e confere
o que dá sem olhar: a conversão termina, nenhum traço de padrão sai da borda
da hachura, todo SOLID chega, nenhum ponto de definição aparece, nenhum rótulo
leva quebra de linha, camada escondida no AutoCAD vem desmarcada, o projeto
abre enquadrado só no que aparece na aba Model e nenhum texto passa por cima
de outro da mesma linha (a versão anterior falhava aqui no LOTEAMENTO, com o
45). Precisa do ODA File Converter; para testar sem instalá-lo, dá para
extrair o `.msi` numa pasta qualquer:

```powershell
msiexec /a ODAFileConverter_QT6_vc16_amd64dll.msi /qn TARGETDIR=C:\temp\oda
.\.venv\Scripts\python.exe testes\verificar_desenhos_reais.py --oda C:\temp\oda
```

### Verificação dentro do QGIS de verdade

Os testes acima validam a **estrutura** do XML. Isso não basta: o QGIS ignora
em silêncio o que não entende, então um projeto estruturalmente perfeito pode
abrir errado (foi o caso do `ProjectionsEnabled`). Com o QGIS instalado:

```powershell
# monta um desenho de exemplo com cara de mapa potenciométrico
.\.venv\Scripts\python.exe testes\gerar_mapa_exemplo.py saida\mapa.dxf
.\.venv\Scripts\python.exe -m conversor paraqgis saida\mapa.dxf saida\m.gpkg --epsg 31982

# abre no QGIS de verdade, confere a simbologia e RENDERIZA para PNG
& "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" `
    testes\verificar_no_qgis.py saida\m.qgs saida\render.png `
    "Curvas_Nivel_LineString=#ff7f00" "Pocos_Point=#0000ff"
```

Ele confere que o QGIS aceitou o projeto, que cada camada é válida, que as
cores do AutoCAD foram aplicadas e que os rótulos ligaram — e desenha o mapa
num PNG, que é a única prova de que o desenho chegou inteiro.

Truque útil quando algo não bate: peça ao próprio QGIS que salve um projeto
equivalente (`QgsProject.write()`) e compare os blocos. Foi assim que a chave
`ProjectionsEnabled` apareceu.

Há mais dois verificadores, cada um com o seu desenho de teste:

```powershell
# carimbo: onde fica a linha de base de cada texto, pela regra do AutoCAD
.\.venv\Scripts\python.exe -m pytest testes\test_carimbo.py   # gera testes\_saida\carimbo
& "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" `
    testes\verificar_textos_no_qgis.py testes\_saida\carimbo\saida\c.qgs `
    testes\_saida\carimbo\esperado.json render.png

# texturas, logo, carimbo, perfil futuro, cotas: desenha cada camada sozinha e conta
# os pixels; no carimbo, acha a linha de cada texto e mede o espacamento
.\.venv\Scripts\python.exe -m pytest testes\test_texturas.py  # gera testes\_saida\texturas
& "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" `
    testes\verificar_texturas_no_qgis.py testes\_saida\texturas\saida\plot.qgs `
    testes\_saida\texturas\esperado.json render.png
```

A contagem de pixels das texturas considera a suavização: uma linha fina sai
misturada com o branco do fundo (o preto vira cinza), então vale o pixel que
está na reta entre o branco e a cor, e "outra cor" é o que sai dessa reta.

No carimbo, a conferência é das linhas que o QGIS **desenhou**, cada uma
achada pelo seu texto: se uma quebra se perder, a linha não existe e o teste
falha. A versão anterior contava as quebras no texto do rótulo — que
continuavam lá quando o QGIS as jogava fora — e por isso não pegou as
palavras coladas.

Tudo conferido no **QGIS 3.44.12 LTR** e no **QGIS 4.2.0**, a partir do
executável empacotado.

**Ainda não coberto:** o DXF nunca foi aberto num AutoCAD 2007 de verdade.

## Licença

[MIT](LICENSE).
