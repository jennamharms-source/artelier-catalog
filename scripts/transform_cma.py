#!/usr/bin/env python3
"""Cleveland Museum of Art open access -> Artelier catalog shards (catalog/cma-####.json).

Source: https://openaccess-api.clevelandart.org (CC0 data; images of works the museum marks
share_license_status = CC0). Only CC0 works with an image are kept.

Usage: python3 scripts/transform_cma.py catalog
"""
import re
import sys

from museum_common import dedupe, get_json, is_nude, wikidata_inventory_map, write_shards

API = "https://openaccess-api.clevelandart.org/api/artworks/"
PAGE = 1000
# Books and portfolio covers are library items, not single artworks.
SKIP_TYPES = {"Bound Volume", "Portfolio", "Book Binding"}
QUALIFIER_OK = re.compile(r"^(attributed to|workshop of|studio of|circle of|follower of|school of|after|manner of|copy after)$", re.I)


def artist_of(work):
    for c in work.get("creators") or []:
        if (c.get("role") or "artist").lower() not in ("artist", "painter", "maker", "sculptor", "photographer", "printmaker", "draftsman"):
            continue
        name = re.sub(r"\s*\([^)]*\)\s*$", "", c.get("description") or "").strip()
        if not name:
            continue
        q = (c.get("qualifier") or "").strip()
        if q and QUALIFIER_OK.match(q):
            name = f"{q[0].upper()}{q[1:]} {name}"
        death = c.get("death_year")
        return name, int(death) if str(death or "").isdigit() else None
    return None, None


def main():
    out_dir = sys.argv[1]
    wd = wikidata_inventory_map("Q657415")
    records, skip = [], 0
    while True:
        d = get_json(API, {"cc0": 1, "has_image": 1, "limit": PAGE, "skip": skip})
        rows = d.get("data") or []
        for w in rows:
            if (w.get("share_license_status") or "").upper() != "CC0":
                continue
            if (w.get("type") or "") in SKIP_TYPES:
                continue
            web = ((w.get("images") or {}).get("web") or {}).get("url")
            title = (w.get("title") or "").strip()
            artist, death = artist_of(w)
            if not (web and title and artist):
                continue
            acc = w.get("accession_number") or str(w.get("id"))
            rec = {
                "source_key": f"cma-{w['id']}",
                "title": title,
                "artist": artist,
                "year": w.get("creation_date") or "",
                "period": w.get("type"),
                "medium": w.get("technique"),
                "image_url": web,
                "source_url": w.get("url") or f"https://clevelandart.org/art/{acc}",
                "license": "CC0 (Cleveland Museum of Art open access)",
                "attribution": "Cleveland Museum of Art",
                "gallery": "Cleveland Museum of Art",
                "city": "Cleveland",
                "country": "United States",
            }
            if acc in wd:
                rec["same_as"] = [f"wikidata:{wd[acc]}"]
            if death:
                rec["artist_death_year"] = death
            if is_nude(title):
                rec["is_age_restricted"] = True
            records.append(rec)
        skip += PAGE
        if len(rows) < PAGE:
            break
    write_shards(dedupe(records), out_dir, "cma", {
        "source": "Cleveland Museum of Art open access",
        "source_api": API,
        "license": "CC0; only works marked share_license_status=CC0 with an image",
    })


if __name__ == "__main__":
    main()
