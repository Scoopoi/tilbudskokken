"""Henter ugens rigtige tilbud fra eTilbudsavis (Tjek) og gemmer dem i offers.json.

Kør:  python hent_tilbud.py
Appen (index.html) læser offers.json og regner opskrifternes pris ud fra tilbuddene.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://squid-api.tjek.com/v2/offers/search"
# Område der søges i (København). Kædernes tilbud er stort set ens i hele landet.
LAT, LNG, RADIUS = 55.6761, 12.5683, 30000

STORES = {  # Tjeks butiksnavn -> navn i appen
    "Netto": "Netto", "REMA 1000": "Rema 1000", "føtex": "Føtex", "Lidl": "Lidl",
    "Bilka": "Bilka", "365discount": "Coop 365", "SuperBrugsen": "SuperBrugsen",
    "Kvickly": "Kvickly", "Brugsen": "Brugsen", "MENY": "Meny", "Spar": "Spar", "Løvbjerg": "Løvbjerg",
}

# Hver ingrediens: søgeord, ord der SKAL stå i overskriften, ord der IKKE må, og vægt pr. stk.
# max_kg = højeste fornuftige kilopris (filtrerer forkerte match fra).
INGREDIENTS = {
    "kylling":  dict(q=["kyllingebryst", "kyllingebrystfilet"], must=r"kyllingebryst|kyllingbryst", ex=r"pålæg|skiver|nuggets|panere|røget|grillet|pålægs", max_kg=160),
    "okse":     dict(q=["hakket oksekød"], must=r"hakket oksekød|hakket okse", ex=r"kylling|gris|grøntsager", max_kg=150),
    "laks":     dict(q=["laksefilet", "laks"], must=r"laks", ex=r"røget|gravad|varmrøget|rejer|pålæg|salat|indbagt|fars|sauce", max_kg=300),
    "aeg":      dict(q=["æg", "fritgående æg", "økologiske æg"], must=r"\bæg\b", ex=r"påske|chokolade|nudler|pasta|kinder|salat", piece_g=60, max_kg=90),
    "havre":    dict(q=["havregryn"], must=r"havregryn", ex=r"bar|drik", max_kg=40),
    "ris":      dict(q=["ris", "jasminris"], must=r"\bris\b|jasminris|basmati", ex=r"riskiks|risalamande|risengrød|chips|kage|nudler", max_kg=50),
    "pasta":    dict(q=["pasta", "spaghetti"], must=r"pasta|spaghetti|penne|fusilli", ex=r"sauce|pesto|salat|færdig|ret|dej", max_kg=50),
    "kartofler":dict(q=["kartofler"], must=r"kartofler", ex=r"chips|pommes|mos|både|fritter|bagekartofler|salat", max_kg=30),
    "broccoli": dict(q=["broccoli"], must=r"broccoli", ex=r"frikadelle|suppe", piece_g=400, max_kg=60),
    "peber":    dict(q=["peberfrugt", "rød peber"], must=r"peberfrugt|rød peber|peberfrugter", ex=r"snack|mini|pesto|sauce", piece_g=170, max_kg=60),
    "log":      dict(q=["løg"], must=r"\bløg\b", ex=r"forårsløg|ristede|chips|purløg|hvidløg", max_kg=30),
    "tomat":    dict(q=["hakkede tomater", "flåede tomater"], must=r"hakkede tomater|flåede tomater", ex=r"", max_kg=40),
    "skyr":     dict(q=["skyr"], must=r"skyr", ex=r"drik|drikke|is\b|bar", max_kg=45),
    "banan":    dict(q=["bananer"], must=r"banan", ex=r"chips|kage|is\b", piece_g=120, max_kg=40),
    "baer":     dict(q=["frosne bær", "bær frost"], must=r"bær|blåbær|hindbær|jordbær", ex=r"is\b|yoghurt|marmelade|kage|syltetøj|juice|sauce", frozen=True, max_kg=90),
    "tortilla": dict(q=["tortilla"], must=r"tortilla", ex=r"chips", max_kg=70),
    "ost":      dict(q=["revet ost"], must=r"revet ost|revet mozzarella|ost revet", ex=r"", max_kg=160),
    "kikaert":  dict(q=["kikærter"], must=r"kikærter", ex=r"snack|hummus|chips", max_kg=50),
    "kokos":    dict(q=["kokosmælk"], must=r"kokosmælk", ex=r"drik", max_kg=60),
    "spinat":   dict(q=["spinat"], must=r"spinat", ex=r"tærte|pizza|pasta|lasagne", max_kg=60),
    "feta":     dict(q=["feta"], must=r"feta", ex=r"salat|pizza", max_kg=140),
    "gulerod":  dict(q=["gulerødder"], must=r"gulerødder|gulerod", ex=r"kage|juice|salat", max_kg=30),
}


def search(query):
    params = urllib.parse.urlencode({"query": query, "r_lat": LAT, "r_lng": LNG,
                                     "r_radius": RADIUS, "limit": 100})
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": "Tilbudskokken/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def grams_of(offer, piece_g):
    """Hvor mange gram man får for prisen. None hvis det ikke kan regnes ud."""
    q = offer.get("quantity") or {}
    unit = (q.get("unit") or {}).get("symbol")
    size = q.get("size") or {}
    pieces = (q.get("pieces") or {}).get("from") or 1
    amount = size.get("to") or size.get("from")
    if not amount:
        return None
    factor = {"g": 1, "kg": 1000, "ml": 1, "cl": 10, "l": 1000, "dl": 100}.get(unit)
    if factor:
        return amount * factor * pieces
    if unit == "pcs" and piece_g:
        return amount * piece_g * pieces
    return None


def size_text(offer):
    q = offer.get("quantity") or {}
    unit = (q.get("unit") or {}).get("symbol") or ""
    s = q.get("size") or {}
    f, t = s.get("from"), s.get("to")
    if not f:
        return ""
    unit = {"pcs": "stk"}.get(unit, unit)
    n = lambda x: f"{x:g}".replace(".", ",")
    return f"{n(f)}–{n(t)} {unit}" if t and t != f else f"{n(f)} {unit}"


def main():
    now = datetime.now(timezone.utc)
    found = {}  # (ingrediens, butik) -> billigste tilbud
    for key, cfg in INGREDIENTS.items():
        seen = set()
        for query in cfg["q"]:
            for o in search(query):
                if o["id"] in seen:
                    continue
                seen.add(o["id"])
                store = STORES.get(o["dealer"]["name"])
                head = o["heading"].replace("\n", " ").strip()
                low = (head + " " + (o.get("description") or "")).lower()
                if not store or not re.search(cfg["must"], head.lower()):
                    continue
                if cfg["ex"] and re.search(cfg["ex"], head.lower()):
                    continue
                if cfg.get("frozen") is True and "frost" not in low and "frosne" not in low and "frys" not in low:
                    continue
                run_from = datetime.fromisoformat(o["run_from"].replace("+0000", "+00:00"))
                run_till = datetime.fromisoformat(o["run_till"].replace("+0000", "+00:00"))
                if run_till < now or run_from > now:
                    continue
                price = o["pricing"]["price"]
                g = grams_of(o, cfg.get("piece_g"))
                if not price or not g:
                    continue
                per_kg = price / g * 1000
                if per_kg > cfg["max_kg"]:
                    continue
                item = {"i": key, "s": store, "title": head, "price": price, "grams": round(g),
                        "perKg": round(per_kg, 2), "size": size_text(o),
                        "till": o["run_till"][:10], "id": o["id"]}
                old = found.get((key, store))
                if not old or per_kg < old["perKg"]:
                    found[(key, store)] = item
        print(f"{key:10s} {sum(1 for k in found if k[0] == key)} tilbud")

    offers = sorted(found.values(), key=lambda x: (x["s"], x["i"]))
    out = {"fetched": now.isoformat(timespec="minutes"), "source": "eTilbudsavis (Tjek)",
           "stores": sorted({o["s"] for o in offers}), "offers": offers}
    path = Path(__file__).with_name("offers.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(offers)} tilbud gemt i {path}")


if __name__ == "__main__":
    main()
