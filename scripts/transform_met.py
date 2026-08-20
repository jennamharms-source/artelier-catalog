#!/usr/bin/env python3
"""Transform Met Museum open access data into Artelier catalog shards.

The Met's CSV (via Git LFS) is metadata-only — images come from their
per-object API. So this transform imports the intersection of
"Is Public Domain" and "Is Highlight" (the Met's own masterpiece
designation, a few thousand works), fetching each object's web-size image
from the API at a polite pace.

Input:  MetObjects.csv (download via LFS media URL)
Output: catalog/met-####.json shards + catalog/index-met.json

Usage: python3 transform_met.py <MetObjects.csv> <output_dir>
"""
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

SHARD_SIZE = 5000
API = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{id}"
PACE_SECONDS = 0.08  # ~12 req/s, well under the Met's documented limits


def fetch_image(object_id):
    try:
        req = urllib.request.Request(
            API.format(id=object_id),
            headers={"User-Agent": "artelier-catalog-build (open access ingestion)"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        return data.get("primaryImageSmall") or data.get("primaryImage") or ""
    except Exception:
        return ""


def main():
    csv_path, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("met-*.json"):
        old.unlink()

    picks = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("Is Public Domain") or "").strip().lower() != "true":
                continue
            if (row.get("Is Highlight") or "").strip().lower() != "true":
                continue
            oid = (row.get("Object ID") or "").strip()
            title = (row.get("Title") or "").strip()
            artist = (row.get("Artist Display Name") or "").strip()
            if not (oid and title and artist):
                continue
            picks.append({
                "oid": oid,
                "title": title,
                "artist": artist,
                "year": (row.get("Object Date") or "").strip(),
                "period": (row.get("Classification") or "").strip() or None,
                "medium": (row.get("Medium") or "").strip() or None,
                "source_url": (row.get("Link Resource") or "").strip()
                    or f"https://www.metmuseum.org/art/collection/search/{oid}",
            })

    print(f"{len(picks)} public-domain highlights to fetch images for")

    shard, shard_no, total, seen = [], 0, 0, set()
    artists = set()

    def flush():
        nonlocal shard, shard_no
        if not shard:
            return
        (out_dir / f"met-{shard_no:04d}.json").write_text(json.dumps(shard, ensure_ascii=False))
        shard, shard_no = [], shard_no + 1

    for i, p in enumerate(picks):
        image_url = fetch_image(p["oid"])
        time.sleep(PACE_SECONDS)
        if not image_url:
            continue
        tkey = f"{p['title'].lower()}|{p['artist'].lower()}"
        if image_url in seen or tkey in seen:
            continue
        seen.add(image_url)
        seen.add(tkey)
        artists.add(p["artist"])
        shard.append({
            "source_key": f"met-{p['oid']}",
            "title": p["title"],
            "artist": p["artist"],
            "year": p["year"],
            "period": p["period"],
            "medium": p["medium"],
            "image_url": image_url,
            "source_url": p["source_url"],
            "license": "CC0 / Public Domain",
            "attribution": "The Metropolitan Museum of Art",
            "gallery": "The Metropolitan Museum of Art",
            "city": "New York",
            "country": "United States",
        })
        total += 1
        if len(shard) >= SHARD_SIZE:
            flush()
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(picks)} fetched, {total} kept")
    flush()

    (out_dir / "index-met.json").write_text(json.dumps({
        "source": "The Metropolitan Museum of Art open access (highlights)",
        "source_repo": "https://github.com/metmuseum/openaccess",
        "license": "CC0; public-domain highlights with images",
        "records": total,
        "artists": len(artists),
        "shards": shard_no,
        "shard_files": [f"met-{i:04d}.json" for i in range(shard_no)],
    }, indent=2))
    print(f"Wrote {total} Met records across {shard_no} shards from {len(artists)} artists")


if __name__ == "__main__":
    main()
