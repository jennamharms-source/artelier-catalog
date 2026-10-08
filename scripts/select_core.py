#!/usr/bin/env python3
"""Core selection: paintings, sculpture and museum highlights from the Cleveland, SMK and
Rijksmuseum shards -> catalog/core-####.json + catalog/index-core.json.

Prints and drawings (and works on paper such as gouache, pastel, watercolour) are left out for
now; a Cleveland work the museum flags as a highlight is kept whatever its type, except prints and
drawings. Records keep their original source_key, so importing core and the full shards never
duplicates.

Usage: python3 scripts/select_core.py catalog
"""
import glob
import json
import sys

from museum_common import write_shards

PAPER = {"print", "drawing", "photograph", "gouache", "pastel", "watercolour", "watercolor", "monotype",
         "engraving", "copper engraving", "etching", "woodcut", "lithograph", "pen", "collage",
         "preparatory study", "sketch", "study", "album", "calligraphy", "manuscript"}
CORE = {
    "cma": {"Painting", "Sculpture", "Portrait Miniature"},
    "smk": {"Painting", "Miniature", "Bust", "Statuette", "Relief", "Statue", "Group of statuettes", "Head",
            "Sculpture in the round", "Herma", "Group of statues", "Sculpture", "Half-length figure",
            "Equestrian statuette", "Overdoor", "Alterpiece", "Mural painting", "Predella", "Icon", "Cassone"},
    "rijks": None,  # paintings already; drop non-paintings below
}
RIJKS_DROP = {"Drawing", "Coin", "Thaler", "Box taler", "Pier glass", "Family arms", "Album"}


def keep(prefix, r):
    kind = (r.get("period") or "").strip()
    if kind.lower() in PAPER:
        return False
    if prefix == "rijks":
        return kind not in RIJKS_DROP
    return kind in CORE[prefix] or bool(r.get("is_highlight"))


def main():
    out_dir = sys.argv[1]
    records = []
    for prefix in ("cma", "smk", "rijks"):
        for f in sorted(glob.glob(f"{out_dir}/{prefix}-*.json")):
            records += [r for r in json.load(open(f)) if keep(prefix, r)]
    write_shards(records, out_dir, "core", {
        "source": "Core selection from Cleveland Museum of Art, SMK and Rijksmuseum shards",
        "license": "same as each record (CC0 / Public Domain Mark)",
        "selection": "paintings, sculpture and Cleveland highlights; no prints, drawings or works on paper",
    })


if __name__ == "__main__":
    main()
