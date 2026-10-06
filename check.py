"""Quinze checagens sobre o raspador e a base que ele produziu.

    .venv/Scripts/python check.py           # as quinze
    .venv/Scripts/python check.py 4 5       # so a 4 e a 5
    .venv/Scripts/python check.py --lista   # o que cada uma faz

Cada checagem olha uma coisa diferente: codigo, esquema, identidade, contagem,
imagem, qualidade, URL, ida-e-volta do CSV, logica pura, ambiente, historico,
disco, cobertura, geografia e ferramentas. Sai com
codigo 1 se qualquer uma falhar, entao serve pra rodar antes de confiar numa
coleta.
"""

from __future__ import annotations

import ast
import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))


class Relatorio:
    """Acumula resultados e imprime cada checagem com seu veredito."""

    def __init__(self) -> None:
        self.falhas: list[str] = []
        self.testes = 0
        self.atual = ""

    def secao(self, numero: int, titulo: str) -> None:
        self.atual = titulo
        print(f"\n{numero:>2}. {titulo}")
        print("    " + "-" * (len(titulo) + 2))

    def ok(self, condicao: bool, descricao: str, detalhe: str = "") -> bool:
        self.testes += 1
        marca = "OK  " if condicao else "FALHA"
        print(f"    [{marca}] {descricao}" + (f"  — {detalhe}" if detalhe and not condicao else ""))
        if not condicao:
            self.falhas.append(f"{self.atual}: {descricao}" + (f" ({detalhe})" if detalhe else ""))
        return condicao

    def info(self, texto: str) -> None:
        print(f"    .      {texto}")


def carregar() -> tuple[list[dict], list[dict]]:
    rows = json.loads((DATA / "creatives.json").read_text(encoding="utf-8"))
    with (DATA / "creatives.csv").open(encoding="utf-8-sig") as fh:
        return rows, list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# 1. CODIGO
# ---------------------------------------------------------------------------
def check_codigo(r: Relatorio) -> None:
    r.secao(1, "Codigo: tudo importa e compila")
    modulos = ["run", "browser", "adapters", "storage", "models", "images", "connect", "streaks"]
    try:
        for nome in modulos:
            __import__(f"scraper.{nome}")
        r.ok(True, f"os {len(modulos)} modulos do pacote importam")
    except Exception as exc:  # noqa: BLE001
        r.ok(False, "os modulos do pacote importam", f"{type(exc).__name__}: {exc}")

    for script in ["diagnose.py", "upgrade_images.py", "winners.py", "check.py"]:
        caminho = ROOT / script
        if not caminho.exists():
            r.ok(False, f"{script} existe")
            continue
        try:
            ast.parse(caminho.read_text(encoding="utf-8"))
            r.ok(True, f"{script} compila")
        except SyntaxError as exc:
            r.ok(False, f"{script} compila", str(exc))

    # a CLI precisa pelo menos responder --help sem explodir
    proc = subprocess.run(
        [sys.executable, "-m", "scraper.run", "--help"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    r.ok(proc.returncode == 0, "scraper.run --help responde", proc.stderr[-200:])


# ---------------------------------------------------------------------------
# 2. ESQUEMA
# ---------------------------------------------------------------------------
def check_esquema(r: Relatorio) -> None:
    r.secao(2, "Esquema: JSON e CSV combinam")
    from scraper.models import CSV_FIELDS

    rows, cr = carregar()
    r.ok(len(rows) == len(cr), "JSON e CSV tem o mesmo numero de linhas", f"{len(rows)} vs {len(cr)}")
    cabecalho = list(cr[0].keys()) if cr else []
    esperado = CSV_FIELDS + ["publishers"]
    r.ok(cabecalho in (CSV_FIELDS, esperado), "cabecalho do CSV bate com CSV_FIELDS",
         f"sobrando/faltando: {set(cabecalho) ^ set(esperado)}")
    faltando = {k for row in rows for k in CSV_FIELDS if k not in row}
    r.ok(not faltando, "toda linha do JSON tem todos os campos", str(faltando))
    r.info(f"{len(rows)} criativos, {len(cabecalho)} colunas")


# ---------------------------------------------------------------------------
# 3. IDENTIDADE
# ---------------------------------------------------------------------------
def check_identidade(r: Relatorio) -> None:
    r.secao(3, "Identidade: um criativo, um card")
    from scraper.images import origin_image
    from scraper.models import Creative

    rows, _ = carregar()
    fps = [row["fingerprint"] for row in rows]
    r.ok(len(fps) == len(set(fps)), "fingerprints sao unicos", f"{len(fps) - len(set(fps))} repetidos")

    divergentes = []
    for row in rows:
        recalculado = Creative(
            publisher=row["publisher"], device=row["device"], network=row["network"],
            headline=row["headline"], click_url=row["click_url"], image_url=row["image_url"],
            advertiser=row.get("advertiser", ""), source_url=row["source_url"],
        ).fingerprint
        if recalculado != row["fingerprint"]:
            divergentes.append(row["fingerprint"])
    r.ok(not divergentes, "fingerprint gravado bate com o recalculado", f"{len(divergentes)} divergem")

    # o bug que ja aconteceu: mesmo criativo em tamanhos diferentes virando cards
    chave = Counter((row["headline"].strip().lower(), origin_image(row["image_url"])) for row in rows)
    repetidos = [k for k, n in chave.items() if n > 1]
    r.ok(not repetidos, "nenhuma headline+imagem duplicada", f"{len(repetidos)} pares repetidos")


# ---------------------------------------------------------------------------
# 4. CONTAGEM
# ---------------------------------------------------------------------------
def check_contagem(r: Relatorio) -> None:
    r.secao(4, "Contagem: streak e avistamentos coerentes")
    rows, _ = carregar()
    dias_coleta = sorted({d for row in rows for d in row.get("seen_dates") or []})

    ruins = [row for row in rows
             if row["times_seen"] != sum((row.get("seen_counts") or {}).values())]
    r.ok(not ruins, "times_seen e a soma de seen_counts", f"{len(ruins)} linhas")

    ruins = [row for row in rows if row["days_seen"] != len(row.get("seen_counts") or {})]
    r.ok(not ruins, "days_seen e a quantidade de dias em seen_counts", f"{len(ruins)} linhas")

    ruins = [row for row in rows if sorted(row.get("seen_counts") or {}) != row["seen_dates"]]
    r.ok(not ruins, "seen_dates e derivado de seen_counts", f"{len(ruins)} linhas")

    r.ok(all(row["times_seen"] >= row["days_seen"] for row in rows),
         "times_seen nunca menor que days_seen")
    r.ok(all(row["streak"] <= row["days_seen"] for row in rows),
         "streak nunca maior que days_seen")
    r.ok(all(row["streak"] <= row["best_streak"] for row in rows),
         "streak atual nunca maior que o melhor")
    r.ok(all(row["span_days"] >= row["days_seen"] for row in rows),
         "span_days nunca menor que days_seen")

    if dias_coleta:
        ultimo = dias_coleta[-1]
        errados = [row for row in rows if row["active"] != (row["last_seen"] == ultimo)]
        r.ok(not errados, f"active reflete a ultima coleta ({ultimo})", f"{len(errados)} linhas")
    r.info(f"coletas: {', '.join(dias_coleta)}")


# ---------------------------------------------------------------------------
# 5. IMAGENS
# ---------------------------------------------------------------------------
def check_imagens(r: Relatorio) -> None:
    r.secao(5, "Imagens: existem, medem e nao sao placeholder")
    from scraper.images import measure

    rows, _ = carregar()
    com_arquivo = [row for row in rows if row.get("image_file")]
    sumidas = [row for row in com_arquivo if not (DATA / row["image_file"]).exists()]
    r.ok(not sumidas, "todo image_file existe em disco", f"{len(sumidas)} sumidas")

    from scraper.images import origin_image
    from scraper.models import PLACEHOLDER_IMAGES

    conhecidos = [row for row in rows if origin_image(row["image_url"]) in PLACEHOLDER_IMAGES]
    r.ok(not conhecidos, "nenhum placeholder conhecido", f"{len(conhecidos)} linhas")

    # Placeholder que ainda nao esta na lista: criativo de verdade pertence a um
    # anunciante so, entao imagem atravessando varios dominios de destino e
    # quase sempre o PNG que a rede pinta quando o anuncio nao tem imagem.
    por_imagem: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        por_imagem[origin_image(row["image_url"])].add(row["landing_domain"])
    suspeitas = {img: doms for img, doms in por_imagem.items() if len(doms) >= 4}
    r.ok(not suspeitas, "nenhuma imagem servindo 4+ anunciantes diferentes",
         "; ".join(f"{img[-40:]} em {len(d)}" for img, d in list(suspeitas.items())[:2]))
    r.ok(not [row for row in rows if row["image_url"].lower().split("?")[0].endswith(".svg")],
         "nenhum criativo em SVG")
    r.ok(not [row for row in rows if "/logo" in row["image_url"].lower()],
         "nenhum logo de parceiro editorial")

    # placeholder novo se disfarca repetindo em muitos criativos
    repetida = Counter(row["image_url"] for row in com_arquivo)
    suspeitas = [(u, n) for u, n in repetida.most_common(5) if n >= 4]
    r.ok(not suspeitas, "nenhuma imagem usada por 4+ criativos", str(suspeitas[:1]))

    # confere a medicao relendo alguns arquivos do disco
    amostra = [row for row in com_arquivo if row.get("image_width")][:25]
    erradas = []
    for row in amostra:
        largura, altura = measure((DATA / row["image_file"]).read_bytes())
        if (largura, altura) != (row["image_width"], row["image_height"]):
            erradas.append(row["image_file"])
    r.ok(not erradas, f"dimensoes gravadas batem com o arquivo ({len(amostra)} conferidas)",
         str(erradas[:2]))
    r.info(f"{len(com_arquivo)}/{len(rows)} com imagem salva")


# ---------------------------------------------------------------------------
# 6. QUALIDADE
# ---------------------------------------------------------------------------
def check_qualidade(r: Relatorio) -> None:
    r.secao(6, "Qualidade: e anuncio, nao materia do portal")
    from scraper.models import EDITORIAL_DOMAINS, Creative

    rows, _ = carregar()
    invalidas = [row for row in rows if not Creative(
        publisher=row["publisher"], device=row["device"], network=row["network"],
        headline=row["headline"], click_url=row["click_url"], image_url=row["image_url"],
        advertiser=row.get("advertiser", ""), source_url=row["source_url"],
    ).is_valid()]
    r.ok(not invalidas, "toda linha guardada passa no is_valid", f"{len(invalidas)} invalidas")

    editoriais = [row for row in rows
                  if ".".join(row["landing_domain"].split(".")[-2:]) in EDITORIAL_DOMAINS]
    r.ok(not editoriais, "nenhum destino em dominio editorial", f"{len(editoriais)} linhas")
    r.ok(all(len(row["headline"]) >= 15 for row in rows), "nenhuma headline curta demais")
    r.ok(all(row["click_url"].startswith("http") for row in rows), "todo click_url e http(s)")

    sem_anunciante = sum(1 for row in rows if not row.get("advertiser"))
    r.info(f"sem advertiser: {sem_anunciante}/{len(rows)} (o widget nem sempre informa)")


# ---------------------------------------------------------------------------
# 7. URLS E PARAMETROS
# ---------------------------------------------------------------------------
def check_parametros(r: Relatorio) -> None:
    r.secao(7, "Parametros: nada se perde da URL de clique")
    from scraper.models import Creative

    rows, _ = carregar()
    quebrados, promovidos = [], []
    for row in rows:
        if not row.get("click_params"):
            continue
        try:
            params = json.loads(row["click_params"])
        except (json.JSONDecodeError, ValueError) as exc:
            quebrados.append(str(exc))
            continue
        creative = Creative(
            publisher=row["publisher"], device=row["device"], network=row["network"],
            headline=row["headline"], click_url=row["click_url"], image_url=row["image_url"],
            source_url=row["source_url"],
        )
        if params != creative.click_params:
            promovidos.append(row["fingerprint"])
    r.ok(not quebrados, "click_params sempre e JSON valido", f"{len(quebrados)} quebrados")
    r.ok(not promovidos, "click_params bate com a URL de clique", f"{len(promovidos)} divergem")

    incoerentes = [row for row in rows
                   if row.get("utm_source")
                   and row["utm_source"] not in row["click_url"]]
    r.ok(not incoerentes, "utm_source promovido existe na URL", f"{len(incoerentes)} linhas")

    com_query = sum(1 for row in rows if "?" in row["click_url"])
    r.info(f"{com_query}/{len(rows)} tem query string (o resto e redirect por caminho)")


# ---------------------------------------------------------------------------
# 8. IDA E VOLTA DO CSV
# ---------------------------------------------------------------------------
def check_csv(r: Relatorio) -> None:
    r.secao(8, "CSV: sobrevive a ida e volta")
    rows, cr = carregar()
    por_fp = {row["fingerprint"]: row for row in rows}

    diferentes = [linha["fingerprint"] for linha in cr
                  if linha["fingerprint"] in por_fp
                  and linha["click_url"] != por_fp[linha["fingerprint"]]["click_url"]]
    r.ok(not diferentes, "click_url identico no JSON e no CSV", f"{len(diferentes)} divergem")

    diferentes = [linha["fingerprint"] for linha in cr
                  if linha["fingerprint"] in por_fp
                  and linha["headline"] != por_fp[linha["fingerprint"]]["headline"]]
    r.ok(not diferentes, "headline identica (acentos preservados)", f"{len(diferentes)} divergem")

    ruins = [linha["fingerprint"] for linha in cr
             if linha["fingerprint"] in por_fp
             and linha["seen_dates"].split(";") != por_fp[linha["fingerprint"]]["seen_dates"]]
    r.ok(not ruins, "seen_dates reconstroi a lista original", f"{len(ruins)} divergem")

    booleanos = {linha["active"] for linha in cr}
    r.ok(booleanos <= {"sim", "nao"}, "active sai como sim/nao", str(booleanos))

    numericos = [linha["fingerprint"] for linha in cr
                 if not linha["times_seen"].isdigit() or not linha["days_seen"].isdigit()]
    r.ok(not numericos, "colunas numericas sao numeros", f"{len(numericos)} estranhas")


# ---------------------------------------------------------------------------
# 9. LOGICA PURA
# ---------------------------------------------------------------------------
def check_logica(r: Relatorio) -> None:
    r.secao(9, "Logica: as regras, sem depender dos dados")
    from scraper.adapters import parse_ad_payload
    from scraper.images import candidates, measure, origin_image
    from scraper.streaks import recompute

    # streak em dias de coleta
    linhas = [{"fingerprint": "a", "seen_counts": {"2026-09-20": 2, "2026-09-21": 1, "2026-09-22": 3}},
              {"fingerprint": "b", "seen_counts": {"2026-09-20": 1, "2026-09-22": 1}},
              {"fingerprint": "c", "seen_counts": {"2026-09-20": 1, "2026-09-21": 1}}]
    recompute(linhas)
    got = {x["fingerprint"]: (x["times_seen"], x["days_seen"], x["streak"], x["active"]) for x in linhas}
    r.ok(got["a"] == (6, 3, 3, True), "tres coletas seguidas = streak 3", str(got["a"]))
    r.ok(got["b"] == (2, 2, 1, True), "faltou o dia do meio = streak 1", str(got["b"]))
    r.ok(got["c"] == (2, 2, 2, False), "sumiu na ultima coleta = inativo", str(got["c"]))

    # normalizacao da imagem
    molde = ("https://images.taboola.com/taboola/image/fetch/f_jpg%2Cq_auto%2Ch_{h}%2Cw_{w}"
             "%2Cc_fill/https%3A//cdn.taboola.com/libtrc/static/thumbnails/abc123.png")
    origens = {origin_image(molde.format(h=h, w=w)) for h, w in [(350, 700), (240, 480), (190, 380)]}
    r.ok(len(origens) == 1, "tamanhos diferentes dao a mesma imagem de origem", str(origens))
    r.ok(origin_image("https://x.com/a.jpg?w=100&q=40") == "https://x.com/a.jpg",
         "parametros de encolhimento somem da origem")
    r.ok(candidates(molde.format(h=350, w=700))[0].endswith("abc123.png"),
         "a origem e o primeiro candidato de download")

    # medicao de imagem
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000001900000012c")
    r.ok(measure(png) == (400, 300), "le dimensoes de PNG pelo cabecalho", str(measure(png)))
    r.ok(measure(b"nada") == (0, 0), "formato irreconhecivel devolve zero")

    # parser de payload de widget
    payload = json.dumps({"list": [
        {"name": "Uma headline bem comprida de anuncio", "origin": "sponsored",
         "url": "https://trc.taboola.com/x", "thumbnail": [{"url": "https://img/a.jpg"}]},
        {"name": "Recomendacao editorial do proprio site", "origin": "default",
         "url": "https://nbcnews.com/y", "thumbnail": [{"url": "https://img/b.jpg"}]},
    ]})
    pagos = parse_ad_payload(payload, sponsored_only=True)
    todos = parse_ad_payload(payload, sponsored_only=False)
    r.ok(len(pagos) == 1 and len(todos) == 2, "parser separa pago de organico",
         f"pagos={len(pagos)} todos={len(todos)}")
    r.ok(parse_ad_payload("isso nao e json") == [], "payload invalido nao explode")


# ---------------------------------------------------------------------------
# 10. AMBIENTE
# ---------------------------------------------------------------------------
def check_ambiente(r: Relatorio) -> None:
    r.secao(10, "Ambiente: config, navegador e ferramentas")
    from scraper.connect import discover_cdp_endpoints
    from scraper.run import load_publishers

    publishers = load_publishers(ROOT / "publishers.yaml")
    r.ok(len(publishers) >= 1, f"publishers.yaml carrega ({len(publishers)} publishers)")
    urls_ruins = [p.name for p in publishers
                  if any(not u.startswith("http") for u in p.urls)]
    r.ok(not urls_ruins, "toda URL de publisher e http(s)", str(urls_ruins))
    devices_ruins = [p.name for p in publishers
                     if any(d not in ("desktop", "mobile") for d in p.devices)]
    r.ok(not devices_ruins, "todo device e desktop ou mobile", str(devices_ruins))

    endpoints = discover_cdp_endpoints()
    r.ok(isinstance(endpoints, list), "descoberta de navegador nao quebra")
    chrome = [e for e in endpoints if e[1].startswith("Chrome/")]
    if endpoints:
        r.info(f"navegadores abertos: {', '.join(f'{p} ({b})' for p, b in endpoints)}")
        r.info("perfil antidetect disponivel" if chrome else
               "so o navegador do sistema — abra o perfil no MoreLogin antes de coletar")
    else:
        r.info("nenhum navegador com porta de debug aberta")

    viewer = (ROOT / "viewer.html").read_text(encoding="utf-8")
    usados = ["days_seen", "times_seen", "seen_counts", "active", "streak", "image_file"]
    faltam = [c for c in usados if c not in viewer]
    r.ok(not faltam, "viewer usa os campos que o scraper grava", str(faltam))


# ---------------------------------------------------------------------------
# 11. HISTORICO
# ---------------------------------------------------------------------------
def check_historico(r: Relatorio) -> None:
    r.secao(11, "Historico: as datas fazem sentido no tempo")
    rows, _ = carregar()
    hoje = date.today().isoformat()

    r.ok(all(row["first_seen"] <= row["last_seen"] for row in rows),
         "first_seen nunca depois de last_seen")
    futuras = [row["fingerprint"] for row in rows if row["last_seen"] > hoje]
    r.ok(not futuras, "nenhuma data no futuro", f"{len(futuras)} linhas")
    r.ok(all(n >= 1 for row in rows for n in (row.get("seen_counts") or {}).values()),
         "nenhum contador de avistamento zerado ou negativo")

    # captured_at e quando a linha nasceu: nao pode ser depois do 1o avistamento
    incoerentes = [row["fingerprint"] for row in rows
                   if str(row.get("captured_at", ""))[:10] > row["first_seen"]]
    r.ok(not incoerentes, "captured_at nunca depois de first_seen", f"{len(incoerentes)} linhas")

    dias = sorted({d for row in rows for d in row["seen_dates"]})
    if len(dias) >= 2:
        buracos = [(a, b) for a, b in zip(dias, dias[1:])
                   if (date.fromisoformat(b) - date.fromisoformat(a)).days > 1]
        r.ok(not buracos, "nenhum dia de coleta pulado",
             "; ".join(f"{a} -> {b}" for a, b in buracos))
    r.info(f"{len(dias)} coletas: {', '.join(dias)}")

    backups = sorted(DATA.glob("creatives.*.json"), key=lambda p: p.stat().st_mtime)
    if backups:
        anterior = json.loads(backups[-1].read_text(encoding="utf-8"))
        r.info(f"ultimo backup: {backups[-1].name} ({len(anterior)} linhas) vs atual ({len(rows)})")


# ---------------------------------------------------------------------------
# 12. DISCO
# ---------------------------------------------------------------------------
def check_disco(r: Relatorio) -> None:
    r.secao(12, "Disco: arquivos saos e sem sobra")
    from scraper.images import measure

    rows, _ = carregar()
    referenciadas = {row["image_file"] for row in rows if row.get("image_file")}
    em_disco = {str(p.relative_to(DATA)).replace("\\", "/")
                for p in (DATA / "images").rglob("*.*")}

    orfas = em_disco - referenciadas
    r.ok(not orfas, "nenhuma imagem orfa em disco", f"{len(orfas)} arquivos sem dono")

    caminho_errado = [row["fingerprint"] for row in rows
                      if row.get("image_file")
                      and Path(row["image_file"]).stem != row["fingerprint"]]
    r.ok(not caminho_errado, "nome do arquivo e o fingerprint da linha",
         f"{len(caminho_errado)} divergem")

    vazios = [p for p in (DATA / "images").rglob("*.*") if p.stat().st_size < 1024]
    r.ok(not vazios, "nenhum arquivo menor que 1 KB", f"{len(vazios)} suspeitos")

    amostra = sorted(referenciadas)[:40]
    ilegiveis = [f for f in amostra if measure((DATA / f).read_bytes()) == (0, 0)]
    r.ok(not ilegiveis, f"as imagens decodificam ({len(amostra)} conferidas)",
         str(ilegiveis[:2]))

    total = sum(p.stat().st_size for p in (DATA / "images").rglob("*.*"))
    r.info(f"{len(em_disco)} arquivos, {total/1024/1024:.0f} MB")
    backups = list(DATA.glob("creatives.*.json"))
    if len(backups) > 3:
        r.info(f"{len(backups)} backups acumulados — da pra apagar os antigos")


# ---------------------------------------------------------------------------
# 13. COBERTURA
# ---------------------------------------------------------------------------
def check_cobertura(r: Relatorio) -> None:
    r.secao(13, "Cobertura: todo publisher esta rendendo")
    from scraper.run import load_publishers

    rows, _ = carregar()
    configurados = {p.name for p in load_publishers(ROOT / "publishers.yaml")}
    coletados = Counter(row["publisher"] for row in rows)
    mudos = sorted(configurados - set(coletados))

    r.ok(len(coletados) >= 1, "pelo menos um publisher rendeu")
    sobrando = set(coletados) - configurados
    r.ok(not sobrando, "todo publisher da base esta no yaml", str(sobrando))

    if mudos:
        r.info(f"sem nenhum criativo: {', '.join(mudos)}")
    r.ok(len(coletados) >= len(configurados) // 2,
         f"ao menos metade dos publishers rende ({len(coletados)}/{len(configurados)})")

    # visitar materia e o que rende: home quase nao tem widget
    materias = sum(1 for row in rows if row["source_url"].count("/") > 3)
    r.ok(materias > len(rows) * 0.5,
         "maioria dos criativos veio de materia, nao de home",
         f"{materias}/{len(rows)}")

    redes = Counter(row["network"] for row in rows)
    r.ok(len(redes) >= 2, "mais de uma rede de ad representada", str(dict(redes)))
    r.info(f"por publisher: {dict(coletados.most_common())}")
    r.info(f"por rede: {dict(redes.most_common())}")


# ---------------------------------------------------------------------------
# 14. GEOGRAFIA
# ---------------------------------------------------------------------------
GEO = re.compile(
    r"\b(nevada|california|texas|florida|arizona|oregon|washington|georgia|ohio|"
    r"las vegas|los angeles|oakland|san diego|phoenix|houston|miami|"
    r"zip code|in your area|near you|your state|your city|your county)\b",
    re.IGNORECASE,
)


def check_geografia(r: Relatorio) -> None:
    r.secao(14, "Geografia: o proxy nao esta falseando o streak")
    rows, _ = carregar()
    geo = [row for row in rows if GEO.search(row["headline"])]
    nacional = [row for row in rows if not GEO.search(row["headline"])]

    r.ok(bool(nacional), "existe criativo nacional na base")
    max_geo = max((row["days_seen"] for row in geo), default=0)
    max_nac = max((row["days_seen"] for row in nacional), default=0)

    # O sinal do problema: geo-segmentado nunca emenda tantos dias quanto
    # nacional porque o proxy troca de cidade e o anuncio some junto com ela.
    confundido = bool(geo) and max_geo < max_nac - 1
    r.ok(not confundido,
         "streak de geo-segmentado acompanha o de nacional",
         f"geo chega a {max_geo} dias, nacional a {max_nac} — proxy trocando de cidade")

    if geo:
        r.info(f"{len(geo)}/{len(rows)} criativos com copy geo-segmentada "
               f"({100 * len(geo) // len(rows)}%)")
        r.info(f"maior streak: geo {max_geo} dias, nacional {max_nac} dias")
    if confundido:
        r.info("para streak comparavel, fixe a cidade do proxy no perfil do MoreLogin")


# ---------------------------------------------------------------------------
# 15. FERRAMENTAS
# ---------------------------------------------------------------------------
def check_ferramentas(r: Relatorio) -> None:
    r.secao(15, "Ferramentas: os scripts de apoio rodam")
    from scraper.adapters import ARTICLE_LINKS_JS, DOM_EXTRACTOR_JS

    for nome, js in (("extrator de DOM", DOM_EXTRACTOR_JS),
                     ("coletor de links", ARTICLE_LINKS_JS)):
        chaves = js.count("{") == js.count("}")
        parenteses = js.count("(") == js.count(")")
        r.ok(chaves and parenteses and len(js) > 500,
             f"{nome}: chaves e parenteses fecham",
             f"chaves {js.count('{')}/{js.count('}')}, "
             f"parenteses {js.count('(')}/{js.count(')')}")

    destino = DATA / "_check_winners.csv"
    proc = subprocess.run(
        [sys.executable, "winners.py", "--quiet", "--out", str(destino)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    r.ok(proc.returncode == 0, "winners.py roda sem erro", proc.stderr[-160:])
    if destino.exists():
        with destino.open(encoding="utf-8-sig") as fh:
            linhas = list(csv.DictReader(fh))
        rows, _ = carregar()
        esperado = sum(1 for row in rows if row["days_seen"] >= 2)
        r.ok(len(linhas) == esperado, "winners.py exporta exatamente os de 2+ dias",
             f"{len(linhas)} no arquivo, {esperado} esperados")
        destino.unlink()

    for script in ("upgrade_images.py", "diagnose.py"):
        proc = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        r.ok(proc.returncode == 0, f"{script} --help responde", proc.stderr[-120:])

    viewer = (ROOT / "viewer.html").read_text(encoding="utf-8")
    r.ok(viewer.count("<script") == viewer.count("</script>"), "viewer.html: script fecha")
    r.ok("data/creatives.json" in viewer, "viewer carrega o JSON sozinho por http")


CHECAGENS = [
    ("codigo", "modulos importam, scripts compilam, a CLI responde", check_codigo),
    ("esquema", "JSON e CSV com as mesmas linhas e colunas", check_esquema),
    ("identidade", "um criativo = um card, sem fingerprint duplicado", check_identidade),
    ("contagem", "streak, dias e avistamentos coerentes entre si", check_contagem),
    ("imagens", "arquivos existem, medem certo e nao sao placeholder", check_imagens),
    ("qualidade", "e anuncio, nao materia nem UI do portal", check_qualidade),
    ("parametros", "a URL de clique chega inteira ao CSV", check_parametros),
    ("csv", "acento, lista e booleano sobrevivem a ida e volta", check_csv),
    ("logica", "as regras testadas sem depender dos dados", check_logica),
    ("ambiente", "config, navegador aberto e viewer alinhado", check_ambiente),
    ("historico", "as datas fazem sentido no tempo", check_historico),
    ("disco", "arquivos saos, sem orfao nem sobra", check_disco),
    ("cobertura", "todo publisher e toda rede rendendo", check_cobertura),
    ("geografia", "o proxy nao esta falseando o streak", check_geografia),
    ("ferramentas", "scripts de apoio e viewer rodam", check_ferramentas),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argumentos = [a for a in sys.argv[1:] if a != "--lista"]
    if "--lista" in sys.argv:
        for i, (nome, descricao, _) in enumerate(CHECAGENS, 1):
            print(f"{i:>2}. {nome:<12} {descricao}")
        return 0

    escolhidas = [int(a) for a in argumentos if a.isdigit()] or list(range(1, len(CHECAGENS) + 1))
    if not DATA.exists():
        print("[erro] nao existe pasta data/ — rode uma coleta antes.", file=sys.stderr)
        return 2

    r = Relatorio()
    print(f"CHECAGEM  —  {date.today().isoformat()}")
    for numero in escolhidas:
        if 1 <= numero <= len(CHECAGENS):
            try:
                CHECAGENS[numero - 1][2](r)
            except Exception as exc:  # noqa: BLE001
                r.secao(numero, CHECAGENS[numero - 1][0])
                r.ok(False, "a checagem rodou sem erro", f"{type(exc).__name__}: {exc}")

    print("\n" + "=" * 62)
    print(f"{r.testes} verificacoes  |  {len(r.falhas)} falhas")
    for falha in r.falhas:
        print(f"  x {falha}")
    if not r.falhas:
        print("  tudo certo.")
    return 1 if r.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
