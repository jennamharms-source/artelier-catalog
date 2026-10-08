#!/usr/bin/env python3
"""SMK – National Gallery of Denmark open data -> Artelier catalog shards (catalog/smk-####.json).

Source: https://api.smk.dk/api/v1 (SMK Open). Only works SMK marks public_domain=true with an
image; their image rights statement is the Public Domain Mark or CC0.

Usage: python3 scripts/transform_smk.py catalog
"""
import re
import sys

from museum_common import dedupe, get_json, is_nude, wikidata_inventory_map, wikidata_labels, write_shards

API = "https://api.smk.dk/api/v1/art/search/"
PAGE = 2000
# Production roles that name someone other than the maker of this object.
NOT_MAKER = {"after", "copy after", "publisher", "printer", "earlier ascribed to", "formerly attributed to", "manner of", "follower of"}
PREFIX = {"attributed to": "Attributed to", "workshop of": "Workshop of", "circle of": "Circle of", "school of": "School of"}
OK_RIGHTS = ("creativecommons.org/publicdomain/mark", "creativecommons.org/publicdomain/zero")


def title_of(w):
    """(title, language): SMK's English title when it has one, else its Danish title."""
    ts = w.get("titles") or []
    for want in ("engelsk", "english"):
        for t in ts:
            if (t.get("language") or "").lower() == want and t.get("title"):
                return t["title"], "en"
    for t in ts:
        if (t.get("type") or "").lower() == "museumstitel" and t.get("title"):
            return t["title"], "da"
    return next(((t["title"], "da") for t in ts if t.get("title")), ("", "da"))


def artist_of(w):
    for p in w.get("production") or []:
        role = (p.get("creator_role") or "").strip().lower()
        if role in NOT_MAKER:
            continue
        fore, sur = (p.get("creator_forename") or "").strip(), (p.get("creator_surname") or "").strip()
        name = f"{fore} {sur}".strip() or (p.get("creator") or "").strip()
        name = re.sub(r"\s*\([^)]*\)", "", name).strip()
        if "," in name and not fore:                       # "Storm Petersen, Robert" -> "Robert Storm Petersen"
            last, first = [x.strip() for x in name.split(",", 1)]
            name = f"{first} {last}".strip()
        if not name:
            continue
        if role in PREFIX:
            name = f"{PREFIX[role]} {name}"
        death = (p.get("creator_date_of_death") or "")[:4]
        return name, int(death) if death.isdigit() else None
    return None, None


def main():
    out_dir = sys.argv[1]
    wd = wikidata_inventory_map("Q671384")
    records, offset = [], 0
    filters = "[public_domain:true],[has_image:true]"
    while True:
        d = get_json(API, {"keys": "*", "filters": filters, "offset": offset, "rows": PAGE, "lang": "en"})
        items = d.get("items") or []
        for w in items:
            if not w.get("public_domain") or not any(r in (w.get("rights") or "") for r in OK_RIGHTS):
                continue
            img = w.get("image_thumbnail")
            title, lang = title_of(w)
            title = (title or "").strip()
            artist, death = artist_of(w)
            if not (img and title and artist):
                continue
            objno = w.get("object_number")
            names = [o.get("name") for o in (w.get("object_names") or []) if o.get("name")]
            dates = [p.get("period") for p in (w.get("production_date") or []) if p.get("period")]
            rec = {
                "source_key": f"smk-{objno}",
                "title": title,
                "artist": artist,
                "year": dates[0] if dates else "",
                "period": names[-1] if names else None,
                "medium": ", ".join(w.get("techniques") or []) or None,
                "image_url": img,
                "source_url": w.get("frontend_url") or f"https://open.smk.dk/artwork/image/{objno}",
                "license": "Public domain (SMK Open)",
                "attribution": "SMK – National Gallery of Denmark",
                "gallery": "SMK – National Gallery of Denmark",
                "city": "Copenhagen",
                "country": "Denmark",
            }
            if objno in wd:
                rec["same_as"] = [f"wikidata:{wd[objno]}"]
            rec["title_language"] = lang
            if death:
                rec["artist_death_year"] = death
            if is_nude(title, *names):
                rec["is_age_restricted"] = True
            records.append(rec)
        offset += PAGE
        if len(items) < PAGE:
            break
    # Danish-titled works: use Wikidata's English title when there is one, keep the Danish original.
    need = [r["same_as"][0].split(":", 1)[1] for r in records if r["title_language"] != "en" and r.get("same_as")]
    en = wikidata_labels(need)
    for r in records:
        q = r["same_as"][0].split(":", 1)[1] if r.get("same_as") else None
        if r["title_language"] != "en" and q in en and en[q].strip().lower() != r["title"].strip().lower():
            r["title_original"], r["title"], r["title_language"] = r["title"], en[q], "en"
        elif r["title_language"] != "en":
            r["title_original"] = r["title"]
    print(f"English titles from Wikidata: {sum(1 for r in records if r.get('title_original') and r['title_language'] == 'en')}; "
          f"still Danish: {sum(1 for r in records if r['title_language'] != 'en')}")
    write_shards(dedupe(records), out_dir, "smk", {
        "source": "SMK – National Gallery of Denmark (SMK Open)",
        "source_api": API,
        "license": "Public Domain Mark / CC0; only works SMK marks public_domain=true with an image",
    })


if __name__ == "__main__":
    main()
