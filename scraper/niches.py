"""Classifica cada criativo num nicho.

E casamento de palavra-chave, nao entendimento do texto. A vantagem e que voce
ve exatamente por que um anuncio caiu num nicho e pode corrigir a regra; a
desvantagem e que headline criativa demais escapa. A taxonomia nao foi
inventada: saiu dos termos que mais aparecem na sua propria base.

A ORDEM IMPORTA. As regras sao testadas de cima para baixo e a primeira que
casa vence, entao o especifico vem antes do generico: "blood sugar" e testado
antes de "blood", senao diabetes viraria pressao alta.

Cuidado com forma de palavra. Escrever `hotel` nao pega "hotels", e
`men over \\d` nao pega "Men Over 40" (o \\b depois do \\d quebra no segundo
digito). Erros assim custaram varios pontos de cobertura — por isso os padroes
abaixo carregam plural e flexao explicitos.

Para ver o efeito de uma mudanca:
    .venv/Scripts/python niches.py --amostra perda-de-peso
    .venv/Scripts/python niches.py --fora
"""

from __future__ import annotations

import re

SEM_NICHO = "outros"

# (slug, rotulo legivel, regex na headline, regex no dominio de destino)
NICHOS: list[tuple[str, str, str, str]] = [
    # ---------------- saude: do mais especifico ao mais generico ----------
    ("memoria-cognicao", "Memória e cognição",
     r"\b(memor(y|ies)|alzheimer'?s?|dementia|cognitive|cognition|brain(\s|-)?(fog|health)?|"
     r"mental decline|forgetful|misplacing|neurolog(y|ist|ists)|sharp mind|senior moments?)\b",
     r"(memor|brain|neuro|cognit|mind)"),

    ("diabetes-glicemia", "Diabetes e glicemia",
     r"\b(blood sugar|diabet(es|ic)|a1c|insulin|glucose|glycemic|dexcom|neuropathy)\b",
     r"(diabet|glucose|a1c|dexcom|sugar)"),

    ("pressao-coracao", "Pressão e coração",
     r"\b(blood pressure|hypertension|cardiolog(y|ist|ists)|cardiac|"
     r"heart (health|disease|attack|failure)|cholesterol|arter(y|ies)|clogged|circulation)\b",
     r"(heart|cardio|pressure|cholesterol)"),

    ("pulmao-respiratorio", "Pulmão e respiração",
     r"\b(lungs?|pulmonar(y|ist|ists)|pulmonolog(y|ist|ists)|copd|"
     r"emphysema|bronchit(is|ic)|bronchial|asthma|wheez(e|ing)|"
     r"breathless(ness)?|shortness of breath|breathing|respirator(y|ies)|"
     r"mucus|phlegm|congestion|smokers?|quit smoking|smoking-related|"
     r"cigarettes?|nicotine|vap(e|es|ing)|oxygen levels?)\b",
     r"(lung|pulmo|copd|breath|respir)"),

    ("perda-de-peso", "Perda de peso",
     r"\b(weight loss|los(e|ing) weight|belly fat|body fat|slim(ming|mer)?|"
     r"shed(ding)? pounds|dropping weight|metabolism|ozempic|glp-?1|appetite|"
     r"bloat(ing|ed)?|waistline|fat burn)\b",
     r"(weight|slim|keto|fatburn|leanb)"),

    ("prostata-masculino", "Saúde masculina",
     r"\b(erectile|prostate|testosterone|libido|men over \d+|bedroom performance|"
     r"male enhancement|\bed\b (relief|product|treatment))\b",
     r"(prostate|testo|mensreport|themens)"),

    ("articulacoes-dor", "Dores e articulações",
     r"\b(joints?|knees?|back pain|arthrit(is|ic)|nerve pain|sciatica|"
     r"poor balance|mobility|inflammation|swollen|leg strength|chronic pain)\b",
     r"(joint|knee|pain|nerve|arthrit|mobility)"),

    ("dental", "Dental",
     r"\b(teeth|tooth|dental|dentists?|gums?|dentures?|implants?|smile)\b",
     r"(dental|teeth|gum|smile|denta|nuvia)"),

    ("audicao-visao", "Audição e visão",
     r"\b(hearing aids?|hearing loss|tinnitus|eyesight|vision loss|macular|"
     r"reading glasses|cataracts?|blurry vision)\b",
     r"(hearing|vision|eyes?|glasses|optic)"),

    ("sono", "Sono",
     r"\b(sleep(ing)?|apnea|snor(e|ing)|insomnia|mattress(es)?|pillows?|"
     r"tired in the morning|before bed)\b",
     r"(sleep|apnea|mattress|pillow|rest)"),

    ("pele-cabelo", "Pele e cabelo",
     r"\b(wrinkles?|skin tags?|collagen|anti-?aging|dark spots?|thinning hair|"
     r"hair (growth|loss)|bald(ing|ness)?|complexion|dermatolog(y|ist|ists)|skin)\b",
     r"(skin|hair|derma|collagen|beauty|renewal)"),

    ("dieta-alimentos", "Dieta e alimentos",
     r"\b(eat(s|ing)? (daily|this|these)|foods?|breakfast|diets?|nutrition|"
     r"vitamins?|supplements?|superfoods?|gut health|probiotics?|recipes?|"
     r"grocer(y|ies)|salmon|coffee)\b",
     r"(nutri|vitamin|supplement|wellness|food|recipe)"),

    # ---------------- financeiro ----------------
    ("seguro-auto", "Seguro de carro",
     r"\b(car insurance|auto insurance|overcharg(e|es|ing)|zip codes?|"
     r"insurance compan(y|ies)|senior drivers?|drivers? in)\b",
     r"(insurance|ottoins|carins|autoins)"),

    ("seguro-saude-vida", "Seguro saúde e vida",
     r"\b(medicare|medicaid|life insurance|health plans?|final expense|burial)\b",
     r"(medicare|lifeins|healthplan)"),

    ("dividas-impostos", "Dívidas e impostos",
     r"\b(debts?|tax(es|payer)?|\birs\b|forgiv(e|es|en|ing|eness)|credit card|"
     r"owes?|settlements?|collections|bankrupt(cy)?|relief program)\b",
     r"(debt|tax|irs|credit|relief|freshstart)"),

    ("investimento-aposentadoria", "Investimento e aposentadoria",
     r"\b(retir(e|es|ed|ing|ee|ees|ement)|401\s?\(?k\)?|\bira\b|roth|annuit(y|ies)|"
     r"dividends?|stocks?|portfolio|invest(s|ing|ment|ments|or|ors)?|"
     r"financial advisor|net worth|savings|wall street|market outlook|"
     r"\$\d+(\.\d+)?\s?(m|k|million|thousand)\b)",
     r"(invest|retire|finance|wealth|capital|asset|trading|money|schwab|"
     r"smartasset|fisher|myfinance)"),

    ("imoveis", "Imóveis",
     r"\b(homes?'? value|house value|mortgages?|refinanc(e|ing)|real estate|"
     r"zillow|property value|sell(ing)? your home|housing market|home equity|"
     r"borrow from the bank)\b",
     r"(homes?\.|realt|mortgage|zillow|propert|kelleybluebookhomes)"),

    # ---------------- casa e consumo ----------------
    ("casa-reforma", "Casa e reforma",
     r"\b(gutters?|roofs?|roofing|walk-?in (shower|tub)|showers?|hvac|"
     r"air conditioner|windows?|siding|water (heater|system)|remodel(ing)?|"
     r"renovation|generators?|heat pumps?|office pods?|backyard|bathrooms?|kitchens?|patios?|enclosures?|flooring|driveway|fence|deck|tubs?)\b",
     r"(shower|roof|gutter|hvac|remodel|acunits|leaffilter|kohler)"),

    ("energia-solar", "Energia solar",
     r"\b(solar[- ]?panels?|solar[- ]?power(ed)?|solar[- ]?energy|off the grid)\b",
     r"solar"),

    ("seguranca-casa", "Segurança residencial",
     r"\b(security (system|camera)s?|home security|\badt\b|alarm systems?|"
     r"doorbell cam(era)?s?)\b",
     r"(security|alarm|\badt\b|covesmart)"),

    ("automoveis", "Automóveis",
     r"\b(suvs?|pickup trucks?|new cars?|car deals?|dealerships?|leas(e|ing) a|"
     r"electric vehicles?|surplus auctions?|cars? (used|owners?)|vehicles?|mileage|drivers? license)\b",
     r"(autotrader|cars?\.|vehicle|truck|motors)"),

    ("viagem", "Viagem",
     r"\b(cruises?|flights?|airfare|private jets?|vacations?|resorts?|"
     r"all-?inclusive|hotels?|beachfront|airlines?|travel(ing)?|getaways?|"
     r"business class|destinations?|room rates?|suites?|stay at|tourism)\b",
     r"(travel|cruise|flight|trip|vacation|hotel)"),

    ("pets", "Pets",
     r"\b(dogs?|cats?|pupp(y|ies)|kittens?|pet (food|owners?|parents?)|"
     r"veterinar(y|ian))\b",
     r"(\bpet|dog|cat|vet)"),

    ("calcados-moda", "Calçados e moda",
     r"\b(shoes?|sneakers?|sandals?|boots?|sweatshirts?|jackets?|wardrobe|"
     r"outfits?|jeans|polos?|apparel|clothing|dress(es)?)\b",
     r"(shoes|wear|fashion|apparel|clothing|outlet|ralph)"),

    ("produtos-gadgets", "Produtos e gadgets",
     r"\b(gadgets?|projectors?|flashlights?|power banks?|gifts?|devices?|drones?|"
     r"air fry(er|ers)|cookware|kniv(e|es)|knife|vacuums?|pans?|cushions?|"
     r"lights?|lamps?)\b",
     r"(gadget|gift|topsseek|hombler|dornanco|sakura)"),

    ("compras-varejo", "Compras e varejo",
     r"\b(amazon|prime|costco|walmart|target|kirkland|shoppers?|deals?|"
     r"discounts?|coupons?|sale|black friday|clearance)\b",
     r"(shop|store|deals?|outlet|cos-rd)"),

    # ---------------- outros verticais ----------------
    ("software-b2b", "Software e B2B",
     r"\b(software|saas|\bcrm\b|\berp\b|\bhcm\b|payroll|workforce|"
     r"business (tool|owner|platform)s?|small business|productivity|"
     r"sourcing platform|3d printing|injection molding|\bai\b (bot|tool|model)|enterprises?|\bit\b (leaders?|teams?)|network strategy|cybersecurity|data (center|strategy)|cloud|automation)\b",
     r"(software|saas|cloud|workday|grammarly|xometry|hcm)"),

    ("namoro", "Relacionamento",
     r"\b(dating|singles|soulmate|find love|eharmony|match(\.com)?)\b",
     r"(dating|eharmony|match|meet)"),

    ("emprego-renda", "Emprego e renda extra",
     r"\b(work from home|side hustle|extra income|mak(e|ing) money|earn \$|"
     r"hiring|jobs? (that|paying))\b",
     r"(jobs?|career|hiring|income)"),

    # Arbitragem de conteudo: a "landing" e um portal de noticia cheio de ads.
    # Fica por ultimo entre os identificaveis porque e o menos especifico.
    ("conteudo-noticia", "Conteúdo e notícia",
     r"\b(dies?|died|dead|sentenced|arrested|court|trial|verdict|celebrit(y|ies)|"
     r"actress|actors?|singers?|\bnba\b|\bnfl\b|scandal|divorce|royal|meghan|"
     r"harry|stories|ranked|remember when|this is what|ties the knot|wedding|recall(ed|s)?|movies?|series|show|more to explore|what happened)\b",
     r"(blavity|afrotech|novelodge|outdoorrevival|tastingtable|prevention|"
     r"magazine|buzz|journal)"),
]

_COMPILADOS = [
    (slug, rotulo, re.compile(rx_head, re.IGNORECASE), re.compile(rx_dom, re.IGNORECASE))
    for slug, rotulo, rx_head, rx_dom in NICHOS
]

ROTULOS = {slug: rotulo for slug, rotulo, _, _ in NICHOS}
ROTULOS[SEM_NICHO] = "Outros"


def classify(headline: str, landing_domain: str = "") -> str:
    """Devolve o slug do nicho. A headline manda; o dominio desempata.

    Duas passadas de proposito: primeiro tentamos casar pela copy, que e o
    sinal forte. So se nenhuma regra casar e que olhamos o dominio, porque
    dominio sozinho erra feio — "track.hombler.com" nao diz nada sozinho.
    """
    texto = headline or ""
    for slug, _, rx_head, _ in _COMPILADOS:
        if rx_head.search(texto):
            return slug

    dominio = (landing_domain or "").lower()
    if dominio:
        for slug, _, _, rx_dom in _COMPILADOS:
            if rx_dom.search(dominio):
                return slug
    return SEM_NICHO


def label(slug: str) -> str:
    return ROTULOS.get(slug, slug)


def explain(headline: str, landing_domain: str = "") -> tuple[str, str]:
    """Mesmo que classify, mas diz qual trecho casou — util pra depurar regra."""
    texto = headline or ""
    for slug, _, rx_head, _ in _COMPILADOS:
        achou = rx_head.search(texto)
        if achou:
            return slug, f"headline: '{achou.group(0)}'"
    dominio = (landing_domain or "").lower()
    if dominio:
        for slug, _, _, rx_dom in _COMPILADOS:
            achou = rx_dom.search(dominio)
            if achou:
                return slug, f"dominio: '{achou.group(0)}'"
    return SEM_NICHO, "nada casou"


# ---------------------------------------------------------------------------
# CLI pra inspecionar e ajustar as regras
# ---------------------------------------------------------------------------
def _cli() -> int:
    import argparse
    import collections
    import json
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Inspeciona a classificacao por nicho.")
    parser.add_argument("--lista", action="store_true", help="mostra os nichos e quantos ads caem em cada")
    parser.add_argument("--amostra", default="", help="mostra exemplos de um nicho, com o trecho que casou")
    parser.add_argument("--fora", action="store_true", help="mostra os que nao caem em nicho nenhum")
    parser.add_argument("--limite", type=int, default=25)
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = parser.parse_args()

    rows = json.loads((args.data / "creatives.json").read_text(encoding="utf-8"))
    contagem = collections.Counter(classify(r["headline"], r["landing_domain"]) for r in rows)
    total = len(rows)
    cobertos = total - contagem[SEM_NICHO]

    if args.amostra:
        alvo = [r for r in rows if classify(r["headline"], r["landing_domain"]) == args.amostra]
        print(f"{len(alvo)} em '{label(args.amostra)}':\n")
        for r in alvo[: args.limite]:
            _, motivo = explain(r["headline"], r["landing_domain"])
            print(f"  {r['headline'][:62]}")
            print(f"     {motivo}  |  {r['landing_domain'][:34]}")
        return 0

    if args.fora:
        alvo = [r for r in rows if classify(r["headline"], r["landing_domain"]) == SEM_NICHO]
        print(f"{len(alvo)} sem nicho (de {total}):\n")
        for r in alvo[: args.limite]:
            print(f"  [{r['landing_domain'][:24]:<24}] {r['headline'][:60]}")
        return 0

    print(f"cobertura: {cobertos}/{total} = {100 * cobertos / total:.0f}%\n")
    print(f"{'ads':>5}  {'nicho':<32} slug")
    for slug, n in contagem.most_common():
        print(f"{n:>5}  {label(slug):<32} {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
