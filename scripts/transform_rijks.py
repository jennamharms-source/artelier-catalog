#!/usr/bin/env python3
"""Rijksmuseum (Linked Art data services) -> Artelier catalog shards (catalog/rijks-####.json).

Source: https://data.rijksmuseum.nl (no API key). The search returns object ids only; each
object's title, maker and rights live on its record, and the image sits two hops away
(object -> VisualItem -> DigitalObject). Only objects whose record carries a CC0 or Public
Domain Mark statement are kept.

Scope: paintings (type=painting). Prints and drawings run to hundreds of thousands of objects
at three requests each, so they are left for a later pass.

Usage: python3 scripts/transform_rijks.py catalog
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from museum_common import dedupe, get_json, is_nude, wikidata_inventory_map, write_shards

SEARCH = "https://data.rijksmuseum.nl/search/collection?type=painting&imageAvailable=true"
LD = {"Accept": "application/ld+json"}
EN = "http://vocab.getty.edu/aat/300388277"          # English
PREFERRED = "http://vocab.getty.edu/aat/300404670"   # preferred term
CREDIT = "http://vocab.getty.edu/aat/300435416"      # creator credit line
INVENTORY = "http://vocab.getty.edu/aat/300312355"   # accession number
OK_RIGHTS = ("creativecommons.org/publicdomain/zero", "creativecommons.org/publicdomain/mark")
WORKERS = 8


def ld(url):
    return get_json(url, headers=LD)


def ids(x):
    if isinstance(x, dict):
        x = [x]
    return [c.get("id") for c in (x or []) if isinstance(c, dict)]


def langs(x):
    return [l.get("id") for l in (x.get("language") or [])]


def english_text(items, cls=None):
    best = None
    for it in items or []:
        if cls and cls not in ids(it.get("classified_as")):
            continue
        if not it.get("content"):
            continue
        if EN in langs(it):
            if PREFERRED in ids(it.get("classified_as")):
                return it["content"]
            best = best or it["content"]
    if best:
        return best
    return next((it["content"] for it in items or [] if it.get("content") and (not cls or cls in ids(it.get("classified_as")))), "")


def notation_en(x):
    notes = x.get("notation") if isinstance(x, dict) else None
    if isinstance(notes, (str, dict)):
        notes = [notes]
    for n in notes or []:
        if isinstance(n, dict) and n.get("@language") == "en":
            return n.get("@value")
    return None


def first_year(text):
    m = re.search(r"\b(1[0-9]\d\d|20[0-2]\d)\b", text or "")
    return int(m.group(1)) if m else None


def object_ids():
    url, out = SEARCH, []
    while url:
        d = ld(url)
        out += [i["id"] for i in d.get("orderedItems") or []]
        url = (d.get("next") or {}).get("id")
    return out


def fetch(oid):
    try:
        return _fetch(oid)
    except Exception as e:  # noqa: BLE001 — one malformed record must not stop the build
        print(f"skip {oid}: {e!r}", flush=True)
        return None


def _fetch(oid):
    o = ld(oid)
    if not o or not any(r in json.dumps(o.get("subject_of") or []) for r in OK_RIGHTS):
        return None
    title = english_text([i for i in o.get("identified_by") or [] if i.get("type") == "Name"])
    inv = next((i.get("content") for i in o.get("identified_by") or []
                if i.get("type") == "Identifier" and INVENTORY in ids(i.get("classified_as"))), None)
    prod = o.get("produced_by") or {}
    credit = english_text(prod.get("referred_to_by"), CREDIT)
    agent = None
    for part in prod.get("part") or []:
        for who in part.get("carried_out_by") or []:
            agent = agent or who.get("id")
    year = english_text((prod.get("timespan") or {}).get("identified_by"))
    kind = next((notation_en(c) for c in o.get("classified_as") or [] if notation_en(c)), "painting")
    page = None
    for s in o.get("subject_of") or []:
        for carrier in s.get("digitally_carried_by") or []:
            if carrier.get("format") == "text/html" and carrier.get("access_point"):
                page = page or carrier["access_point"][0].get("id")
    # image: object -> VisualItem -> DigitalObject -> IIIF access point
    image = None
    for v in ids(o.get("shows")):
        vis = ld(v) or {}
        for dig in ids(vis.get("digitally_shown_by")):
            dobj = ld(dig) or {}
            ap = ids(dobj.get("access_point"))
            if ap:
                image = ap[0].replace("/full/max/", "/full/1280,/")
                break
        if image:
            break
    if not (title and credit and image) or re.match(r"(anonymous|unknown)\b", credit, re.I):
        return None
    return {"oid": oid, "title": title, "credit": credit, "agent": agent, "year": year, "kind": kind,
            "inv": inv, "page": page, "image": image}


def agent_death(aid):
    try:
        a = ld(aid) or {}
    except Exception:  # noqa: BLE001
        return aid, None
    died = (a.get("died") or {}).get("timespan") or {}
    text = english_text(died.get("identified_by")) or died.get("end_of_the_end") or ""
    return aid, first_year(text)


def main():
    out_dir = sys.argv[1]
    wd = wikidata_inventory_map("Q190804")
    oids = object_ids()
    print(f"{len(oids)} painting ids", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        rows = [r for r in ex.map(fetch, oids) if r]
    agents = sorted({r["agent"] for r in rows if r["agent"]})
    with ThreadPoolExecutor(WORKERS) as ex:
        deaths = dict(ex.map(agent_death, agents))
    records = []
    for r in rows:
        rec = {
            "source_key": "rijks-" + r["oid"].rsplit("/", 1)[-1],
            "title": r["title"],
            "artist": re.sub(r"\s*\([^)]*\)\s*$", "", r["credit"]).strip(),
            "year": r["year"] or "",
            "period": (r["kind"] or "painting").capitalize(),
            "medium": None,
            "image_url": r["image"],
            "source_url": f"https://www.rijksmuseum.nl/en/collection/{r['inv']}" if r["inv"] else (r["page"] or r["oid"]),
            "license": "CC0 (Rijksmuseum)",
            "attribution": "Rijksmuseum",
            "gallery": "Rijksmuseum",
            "city": "Amsterdam",
            "country": "Netherlands",
        }
        if r["inv"] and r["inv"] in wd:
            rec["same_as"] = [f"wikidata:{wd[r['inv']]}"]
        if deaths.get(r["agent"]):
            rec["artist_death_year"] = deaths[r["agent"]]
        if is_nude(r["title"]):
            rec["is_age_restricted"] = True
        records.append(rec)
    write_shards(dedupe(records), out_dir, "rijks", {
        "source": "Rijksmuseum data services (Linked Art)",
        "source_api": SEARCH,
        "license": "CC0 / Public Domain Mark; paintings only for now",
    })


if __name__ == "__main__":
    main()
