# Native Ads Scraper

Coleta criativos de **anúncio nativo** dos portais de notícia de grande escala
— AOL, Yahoo, MSN, ABC, NBC, CBS, Business Insider — e monta um acervo
pesquisável de *headline + imagem + anunciante + link de destino*.

Cobre os widgets de Taboola, Outbrain, Revcontent, MGID, MediaGo e o stream ad
nativo do Yahoo/AOL.

O ponto do projeto não é só baixar anúncio: é **saber há quantos dias cada
criativo está no ar**. Anúncio que o anunciante mantém rodando por uma semana
está pagando por si; anúncio que aparece um dia e some, não. Essa é a diferença
entre um arquivo de imagens e uma ferramenta de pesquisa.

---

## Por que não dá para fazer com `requests`

Três obstáculos, e cada um derruba a abordagem ingênua:

1. **O widget só existe depois do JavaScript.** O HTML que vem do servidor tem
   um `<div>` vazio. Daí o Playwright com Chromium de verdade.
2. **O widget só carrega quando entra na tela.** Ele fica abaixo da dobra e é
   lazy. Sem rolagem incremental com pausa, a página devolve zero criativo.
3. **O anúncio é escolhido pelo IP.** Rodando do Brasil você vê o pool
   brasileiro. Para ver o pool americano o navegador precisa sair por um IP
   americano — veja [Geografia](#geografia-de-onde-os-anúncios-são-servidos).

---

## Instalação

Requer Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium
```

No Linux/macOS troque `.venv/Scripts/` por `.venv/bin/`.

---

## Uso

```bash
.venv/Scripts/python -m scraper.run
```

Roda a lista inteira do `publishers.yaml`, em desktop e mobile, e no fim
publica no site (desligue com `--no-publish`).

| Flag | O que faz |
| --- | --- |
| `--only yahoo,msn` | só esses publishers |
| `--device {desktop,mobile,both}` | qual perfil de device simular |
| `--scrolls 14` | rolagens por página — mais rolagem, mais widget carregado |
| `--pause 900` | ms de espera entre rolagens |
| `--articles 5` | matérias visitadas a partir de cada página (padrão 3) |
| `--max-urls 1` | só a primeira URL de cada publisher (rodada rápida) |
| `--headful` | mostra o navegador na tela, bom para depurar |
| `--include-organic` | guarda também a recomendação não paga do widget |
| `--locale`, `--timezone` | idioma e fuso do navegador |
| `--no-publish` | não sincroniza com o site no fim |

**A flag que mais muda o resultado é `--articles`.** O widget nativo vive no
fim do texto de uma matéria, não na home. Coletar só das homes rende uma
fração do que rende seguir para dentro dos artigos.

---

## Geografia: de onde os anúncios são servidos

Para coletar o pool de um país, o navegador precisa sair por um IP de lá. Três
caminhos, do mais simples ao mais robusto:

### Proxy direto

```bash
.venv/Scripts/python -m scraper.run --proxy http://usuario:senha@host:porta --locale en-US --timezone America/New_York
```

Passe `--locale` e `--timezone` junto: um navegador que sai por IP de Nova York
anunciando `pt-BR` e fuso de São Paulo é incoerente, e alguns widgets mudam de
comportamento com isso.

### Navegador antidetect já aberto

```bash
.venv/Scripts/python -m scraper.run --cdp auto --device-label desktop
```

`--cdp auto` varre as portas locais, acha o navegador aberto e se pluga nele
via CDP. Havendo mais de um, ele lista as portas para você fixar qual quer
(`--cdp 51234`).

Nesse modo o script **não** mexe em user-agent, viewport nem locale — o perfil
antidetect já tem um fingerprint coerente, e sobrescrever justamente o que ele
cuidou é a forma mais rápida de ser detectado. Consequência prática: quem
define desktop vs. mobile é o perfil, não o `--device`. Use `--device-label`
só para rotular a coluna na saída, e tenha um perfil por device.

### MoreLogin, iniciando o perfil sozinho

```bash
.venv/Scripts/python -m scraper.run --morelogin "NOME DO PERFIL"
```

Sobe o perfil pela API local do MoreLogin (`127.0.0.1:40000`), coleta dentro
dele e fecha no fim (`--keep-open` deixa aberto).

> **Identifique o perfil pelo nome, não pelo número da interface.** A API
> devolve só o `id` longo de 19 dígitos e o `envName`. O número curto que
> aparece na tela do MoreLogin não existe no payload — passar ele dá
> "nenhum perfil chamado X".

---

## Streak: há quantos dias o anúncio está no ar

Cada coleta carimba a data em que viu o criativo. Com isso:

| Campo | Significado |
| --- | --- |
| `first_seen` / `last_seen` | primeira e última vez que apareceu |
| `days_seen` | em quantos dias distintos apareceu |
| `times_seen` | quantas vezes no total (várias por dia contam) |
| `streak` | dias **seguidos** de coleta em que apareceu |
| `best_streak` | a maior sequência já atingida |
| `active` | se apareceu na coleta mais recente |

**Streak conta dias de coleta, não dias de calendário.** Se você não coletar no
sábado, o sábado não quebra a sequência de ninguém — ele simplesmente não
existe na linha do tempo. Faz mais sentido: a ausência é sua, não do anúncio.

A diferença entre `days_seen` e `times_seen` importa. Um criativo com
`days_seen=3, times_seen=40` está em rodízio pesado dentro do widget. Um com
`days_seen=8, times_seen=9` é uma campanha estável e discreta. Os dois são
sinais de que está funcionando, mas são campanhas diferentes.

Para exportar só os que sobreviveram:

```bash
.venv/Scripts/python winners.py --min-days 3
```

---

## Nichos

Cada criativo é classificado por regras de palavra-chave ordenadas, da mais
específica para a mais genérica — primeira que casar vence. São ~30 nichos:
perda de peso, memória, diabetes, pulmão, visão, audição, próstata, finanças,
seguros, automotivo, casa, e assim por diante.

```bash
.venv/Scripts/python -m scraper.niches --lista
.venv/Scripts/python -m scraper.niches --amostra
.venv/Scripts/python -m scraper.niches --fora
```

**É palavra-chave, não compreensão.** A ordem das regras é o que impede
"melhor receita de brisket defumado" de cair em pulmão por causa de "smoked".
Ao adicionar um nicho, a posição dele na lista importa tanto quanto o regex —
rode `--amostra` e `--fora` depois de mexer.

---

## Visualizador

`viewer.html` é uma página só, sem build e sem servidor: abra no navegador.
Filtra por busca, período, publisher, rede, device, nicho e situação; ordena
por mais recente, anunciante, maior imagem, mais dias; mostra o selo de streak
e exporta CSV. Um clique em "N com 2+ dias" isola o que já provou alguma coisa.

---

## Publicação: site estático + imagens em resolução cheia

```bash
.venv/Scripts/python publish.py --init
.venv/Scripts/python publish.py
.venv/Scripts/python publish.py --dry-run
```

`publish.py` copia o viewer, grava os dados e dá push. Ligue esse repositório
a qualquer host estático (Cloudflare Pages, Netlify, GitHub Pages) e cada
coleta vira um deploy. Como é site estático puro, o *build command* fica
**vazio** e o *output directory* é a **raiz**.

### Por que o R2 (opcional)

A URL de imagem que o widget serve é a versão recortada para o slot — uns
21 KB. Ela carrega a URL de origem embutida no caminho, e a origem tem perto
de 1 MB. O projeto extrai a origem: 50× mais qualidade pelo mesmo custo.

O problema é que essa origem é o CDN do anunciante, e **quando a campanha sai
do ar a imagem morre**. Por isso os criativos que atingem 3 dias são baixados
e guardados no Cloudflare R2, que tem 10 GB grátis e não cobra tráfego de
saída. Abaixo de 3 dias ninguém é baixado — a maioria dos criativos nunca
chega lá, e guardar todos encheria o bucket em semanas.

Configuração: veja [Credenciais](#credenciais).

---

## Saída

`data/creatives.csv` e `data/creatives.json`, 30 colunas. As principais:

| Coluna | Conteúdo |
| --- | --- |
| `headline` | o texto do anúncio |
| `image_url` | imagem, já na melhor resolução disponível |
| `advertiser`, `landing_domain` | quem anuncia e para onde manda |
| `click_url`, `click_params` | destino e os parâmetros da URL, em JSON |
| `utm_source/medium/content`, `campaign_id` | rastreio, quando existe |
| `publisher`, `publishers`, `network`, `device` | onde foi visto |
| `niche` | nicho classificado |
| `fingerprint` | chave de deduplicação |
| *(campos de streak)* | ver a seção acima |

### A deduplicação

`fingerprint` é `sha1(headline + imagem_de_origem)`. Precisa ser a imagem de
**origem**, não a URL do CDN: o mesmo criativo sai do Taboola em `w_380`,
`w_480`, `w_700` e `w_880` conforme o tamanho do slot. Usar a URL transformada
cria um criativo novo a cada largura — na prática, cartões duplicados e streaks
que nunca passam de 1.

---

## Checagem

```bash
.venv/Scripts/python check.py
```

Roda dezenas de verificações sobre a base: duplicatas, imagens quebradas,
placeholders, vazamento de conteúdo editorial, coerência dos streaks, nichos.
Sai com código 1 se algo falhar.

---

## Estrutura

```
scraper/
  run.py        CLI e orquestração da varredura
  browser.py    sessão do Playwright, rolagem, consentimento, CDP
  adapters.py   extração do DOM e das APIs dos widgets
  connect.py    descoberta de CDP e cliente da API do MoreLogin
  models.py     o criativo, validação e esquema de saída
  storage.py    base incremental com carimbo de data
  streaks.py    cálculo dos dias no ar
  niches.py     classificação por nicho
  images.py     URL de origem, candidatos e medição
  r2.py         upload para o Cloudflare R2
publishers.yaml  a lista de portais — edite livremente
viewer.html      o visualizador
publish.py       monta e publica o site
check.py         suíte de verificação
winners.py       exporta os criativos que sobreviveram
```

---

## Credenciais

**Nenhum segredo entra no repositório.** Três formas de configurar o R2, em
ordem de prioridade:

1. **Variáveis de ambiente** — `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE`. É o caminho para CI:
   o segredo vem do cofre do runner e nada é escrito em disco.
2. **Arquivo `.env`** — copie de `.env.example`. Está no `.gitignore`.
3. **`r2.config.json`** — copie de `r2.config.exemplo.json`, ou rode
   `python configurar_r2.py`, que pede os valores com `getpass` para que a
   senha não passe pela linha de comando nem pelo histórico do shell.

O token do R2 deve ter permissão **Object Read & Write restrita a um único
bucket**. Não use um token de conta inteira.

Sem credencial nenhuma o projeto funciona: a coleta roda normal e o site usa as
URLs do CDN.

---

## Limites conhecidos

Coisas que são assim de verdade, não bugs a descobrir:

- **Nem todo publisher rende.** Alguns da lista padrão dão zero com
  frequência. `--only` com os que rendem economiza bastante tempo.
- **A sessão pode travar.** Se a conexão CDP com o navegador morre no meio, a
  chamada do Playwright fica pendurada indefinidamente: sem consumir CPU, sem
  abrir socket e sem estourar o `set_default_timeout`, que limita ação e não
  websocket mudo. Quem automatiza várias rodadas seguidas deve dar um teto de
  tempo por rodada (`subprocess.run(..., timeout=...)`) e seguir para a
  próxima.
- **Proxy rotativo embaralha o streak.** Se o IP muda de cidade entre coletas,
  o pool de anúncios muda junto, e um criativo pode "sumir" por geografia e não
  por ter saído do ar. Prefira sessão fixa (*sticky*) no proxy.
- **A classificação é por palavra-chave.** Headline criativa demais escapa.

---

## Segurança e uso responsável

O scraper lê **páginas públicas**, como qualquer visitante, e guarda o material
publicitário que elas exibem. Ainda assim:

- Respeite os termos de uso dos portais e a legislação aplicável.
- Mantenha um intervalo entre requisições — o padrão já faz isso.
- As imagens e textos coletados são de seus respectivos anunciantes. Usar o
  acervo para pesquisa de mercado é uma coisa; republicar criativo alheio como
  seu é outra.

Nunca faça commit de `r2.config.json`, `.env` ou da pasta `data/` — os três
estão no `.gitignore`. Se uma credencial vazar, **revogue-a**: chave exposta,
mesmo que por pouco tempo, deve ser considerada comprometida.

---

## Licença

MIT. Veja [LICENSE](LICENSE).
