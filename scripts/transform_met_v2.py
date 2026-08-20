#!/usr/bin/env python3
"""Transform Met Museum open access data into Artelier catalog shards (v2).

Joins two files:
  1. MetObjects.csv        — the Met's OFFICIAL dataset (Git LFS, updated
                             regularly). Sole authority on public-domain
                             status and metadata.
  2. BetterMetObjects.csv  — community image-URL index (CC0, from
                             graslowsnail/metmuseum-api-dump-enhanced),
                             built from the Met's own public object pages.
                             Used ONLY as an object_id -> image URL lookup.

Rights hygiene:
  - A record is emitted only if the OFFICIAL CSV says Is Public Domain.
  - Image URLs containing "/restricted" are excluded — the Met serves
    those for non-open-access works and they are not CC0.

No API calls: this is a pure CSV join, so the full public-domain painting
and object corpus transforms in minutes.

Usage: python3 transform_met_v2.py <MetObjects.csv> <BetterMetObjects.csv> <output_dir>
"""
import csv
import json
import sys
from pathlib import Path

SHARD_SIZE = 5000
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))  # long description fields


def first_artist(raw):
    """Met multi-artist fields are pipe-separated; take the primary one."""
    name = (raw or "").split("|")[0].strip()
    return "" if name.lower() in ("", "unknown", "unidentified artist") else name


def main():
    official_path, enhanced_path, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("met-*.json"):
        old.unlink()

    # ---- pass 1: image lookup from the community index ----
    images = {}
    restricted = 0
    with open(enhanced_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            oid = (row.get("object_id") or "").strip()
            url = (row.get("primary_image") or "").strip() or (row.get("primary_image_small") or "").strip()
            if not (oid and url):
                continue
            if "/restricted" in url:
                restricted += 1
                continue
            images[oid] = url
    print(f"image index: {len(images)} clean URLs ({restricted} restricted excluded)")

    # ---- pass 2: walk the official CSV, join, emit ----
    pd_total = with_artist = with_image = total = 0
    seen = set()
    artists = set()
    shard, shard_no = [], 0

    def flush():
        nonlocal shard, shard_no
        if not shard:
            return
        (out_dir / f"met-{shard_no:04d}.json").write_text(json.dumps(shard, ensure_ascii=False))
        shard, shard_no = [], shard_no + 1

    with open(official_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("Is Public Domain") or "").strip().lower() != "true":
                continue
            pd_total += 1
            oid = (row.get("Object ID") or "").strip()
            title = (row.get("Title") or "").strip()
            artist = first_artist(row.get("Artist Display Name"))
            if not (oid and title and artist):
                continue
            with_artist += 1
            image_url = images.get(oid)
            if not image_url:
                continue
            with_image += 1
            tkey = f"{title.lower()}|{artist.lower()}"
            if image_url in seen or tkey in seen:
                continue
            seen.add(image_url)
            seen.add(tkey)
            artists.add(artist)
            shard.append({
                "source_key": f"met-{oid}",
                "title": title,
                "artist": artist,
                "year": (row.get("Object Date") or "").strip(),
                "period": (row.get("Classification") or "").strip() or None,
                "medium": (row.get("Medium") or "").strip() or None,
                "image_url": image_url,
                "source_url": (row.get("Link Resource") or "").strip()
                    or f"https://www.metmuseum.org/art/collection/search/{oid}",
                "license": "CC0 / Public Domain",
                "attribution": "The Metropolitan Museum of Art",
                "gallery": "The Metropolitan Museum of Art",
                "city": "New York",
                "country": "United States",
            })
            total += 1
            if len(shard) >= SHARD_SIZE:
                flush()
    flush()

    (out_dir / "index-met.json").write_text(json.dumps({
        "source": "The Metropolitan Museum of Art open access",
        "source_repo": "https://github.com/metmuseum/openaccess",
        "image_index": "https://github.com/graslowsnail/metmuseum-api-dump-enhanced (CC0)",
        "license": "CC0; public-domain works per the official Met dataset, restricted images excluded",
        "records": total,
        "artists": len(artists),
        "shards": shard_no,
        "shard_files": [f"met-{i:04d}.json" for i in range(shard_no)],
    }, indent=2))
    print(f"funnel: {pd_total} public domain -> {with_artist} named artist -> "
          f"{with_image} with clean image -> {total} kept after dedupe")
    print(f"Wrote {total} Met records across {shard_no} shards from {len(artists)} artists")


if __name__ == "__main__":
    main()
