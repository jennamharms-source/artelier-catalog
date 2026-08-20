#!/usr/bin/env python3
"""Transform the Art Institute of Chicago open-data dump into Artelier catalog shards.

Input:  artic-api-data.tar.bz2 (https://github.com/art-institute-of-chicago/api-data)
Output: catalog/aic-####.json shards (5,000 records each) + catalog/index.json

Only public-domain works with an image are included. Every record carries the
license, attribution, and source link expected by Artelier's Artwork schema
(license / attribution / source_url fields), plus a stable `source_key` for
idempotent re-imports.

Usage: python3 transform_aic.py <tarball> <output_dir>
"""
import json
import sys
import tarfile
from pathlib import Path

SHARD_SIZE = 5000
IIIF = "https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
PAGE = "https://www.artic.edu/artworks/{id}"


def records(tar_path):
    """Stream artwork JSONs out of the tarball without extracting to disk."""
    with tarfile.open(tar_path, "r:bz2") as tar:
        for member in tar:
            name = member.name
            # artwork records live under .../json/artworks/{id}.json
            if "/artworks/" not in name or not name.endswith(".json"):
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            try:
                yield json.load(f)
            except Exception:
                continue


def transform(a):
    if not a.get("is_public_domain"):
        return None
    image_id = a.get("image_id")
    if not image_id:
        return None
    title = (a.get("title") or "").strip()
    artist = (a.get("artist_title") or "").strip()
    if not title or not artist:
        return None
    info = a.get("info") or {}
    license_text = "CC0 / Public Domain"
    lt = info.get("license_text")
    if lt:
        license_text = lt if len(lt) < 120 else "CC0 / Public Domain"
    return {
        "source_key": f"aic-{a['id']}",
        "title": title,
        "artist": artist,
        "year": str(a.get("date_display") or a.get("date_start") or ""),
        "period": a.get("style_title"),
        "medium": a.get("medium_display"),
        "image_url": IIIF.format(image_id=image_id),
        "source_url": PAGE.format(id=a["id"]),
        "license": license_text,
        "attribution": "Art Institute of Chicago",
        "gallery": "Art Institute of Chicago",
        "city": "Chicago",
        "country": "United States",
    }


def main():
    tar_path, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("aic-*.json"):
        old.unlink()

    shard, shard_no, total, seen = [], 0, 0, set()
    artists = set()

    def flush():
        nonlocal shard, shard_no
        if not shard:
            return
        path = out_dir / f"aic-{shard_no:04d}.json"
        path.write_text(json.dumps(shard, ensure_ascii=False))
        shard, shard_no = [], shard_no + 1

    for raw in records(tar_path):
        rec = transform(raw)
        if rec is None:
            continue
        # dedupe within the dump by image and by normalized title|artist
        key = rec["image_url"]
        tkey = f"{rec['title'].lower()}|{rec['artist'].lower()}"
        if key in seen or tkey in seen:
            continue
        seen.add(key)
        seen.add(tkey)
        artists.add(rec["artist"])
        shard.append(rec)
        total += 1
        if len(shard) >= SHARD_SIZE:
            flush()
    flush()

    index = {
        "source": "Art Institute of Chicago open data",
        "source_repo": "https://github.com/art-institute-of-chicago/api-data",
        "license": "CC0 / Public Domain works only (is_public_domain=true)",
        "records": total,
        "artists": len(artists),
        "shards": shard_no,
        "shard_files": [f"aic-{i:04d}.json" for i in range(shard_no)],
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    print(f"Wrote {total} records across {shard_no} shards from {len(artists)} artists")


if __name__ == "__main__":
    main()
