#!/usr/bin/env python3
"""Transform National Gallery of Art open data CSVs into Artelier catalog shards.

Input:  a directory containing objects.csv, published_images.csv,
        constituents.csv, objects_constituents.csv
        (https://github.com/NationalGalleryOfArt/opendata — CC0)
Output: catalog/nga-####.json shards + entry in catalog/index-nga.json

Join path (per NGA's data dictionary):
  objects -> objects_constituents (roleType='artist') -> constituents.preferredDisplayName
  objects <- published_images.depictstmsobjectid (keep openaccess images only)

Usage: python3 transform_nga.py <csv_dir> <output_dir>
"""
import csv
import json
import sys
from pathlib import Path

SHARD_SIZE = 5000
TRUTHY = {"1", "true", "yes", "y", "t"}


def lower_keys(row):
    return {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            yield lower_keys(row)


def main():
    csv_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("nga-*.json"):
        old.unlink()

    # constituentID -> display name
    names = {}
    for r in read_csv(csv_dir / "constituents.csv"):
        cid = r.get("constituentid")
        if cid:
            names[cid] = r.get("preferreddisplayname") or r.get("forwarddisplayname") or ""

    # objectID -> artist name (first 'artist' roleType)
    artist_of = {}
    for r in read_csv(csv_dir / "objects_constituents.csv"):
        if (r.get("roletype") or "").lower() != "artist":
            continue
        oid = r.get("objectid")
        if oid and oid not in artist_of:
            nm = names.get(r.get("constituentid"), "")
            if nm:
                artist_of[oid] = nm

    # objectID -> best open-access image (lowest sequence wins)
    image_of = {}
    for r in read_csv(csv_dir / "published_images.csv"):
        oid = r.get("depictstmsobjectid")
        if not oid:
            continue
        if (r.get("openaccess") or "").lower() not in TRUTHY:
            continue
        iiif = r.get("iiifurl")
        if not iiif:
            continue
        try:
            seq = float(r.get("sequence") or 0)
        except ValueError:
            seq = 0
        cur = image_of.get(oid)
        if cur is None or seq < cur[0]:
            image_of[oid] = (seq, iiif)

    shard, shard_no, total, seen = [], 0, 0, set()
    artists = set()

    def flush():
        nonlocal shard, shard_no
        if not shard:
            return
        (out_dir / f"nga-{shard_no:04d}.json").write_text(json.dumps(shard, ensure_ascii=False))
        shard, shard_no = [], shard_no + 1

    for r in read_csv(csv_dir / "objects.csv"):
        oid = r.get("objectid")
        title = r.get("title") or ""
        artist = artist_of.get(oid, "")
        img = image_of.get(oid)
        if not (oid and title and artist and img):
            continue
        image_url = f"{img[1].rstrip('/')}/full/!843,843/0/default.jpg"
        key = image_url
        tkey = f"{title.lower()}|{artist.lower()}"
        if key in seen or tkey in seen:
            continue
        seen.add(key)
        seen.add(tkey)
        artists.add(artist)
        shard.append({
            "source_key": f"nga-{oid}",
            "title": title,
            "artist": artist,
            "year": r.get("displaydate") or r.get("beginyear") or "",
            "period": r.get("classification"),
            "medium": r.get("medium"),
            "image_url": image_url,
            "source_url": f"https://www.nga.gov/collection/art-object-page.{oid}.html",
            "license": "CC0 / Public Domain (NGA open access image)",
            "attribution": "National Gallery of Art",
            "gallery": "National Gallery of Art",
            "city": "Washington, D.C.",
            "country": "United States",
        })
        total += 1
        if len(shard) >= SHARD_SIZE:
            flush()
    flush()

    (out_dir / "index-nga.json").write_text(json.dumps({
        "source": "National Gallery of Art open data",
        "source_repo": "https://github.com/NationalGalleryOfArt/opendata",
        "license": "CC0; open-access images only (published_images.openaccess)",
        "records": total,
        "artists": len(artists),
        "shards": shard_no,
        "shard_files": [f"nga-{i:04d}.json" for i in range(shard_no)],
    }, indent=2))
    print(f"Wrote {total} NGA records across {shard_no} shards from {len(artists)} artists")


if __name__ == "__main__":
    main()
