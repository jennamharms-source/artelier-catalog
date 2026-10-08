"""Shared helpers for the museum open-access transforms (Cleveland, SMK, Rijksmuseum).

Every record these scripts write uses the same Artelier catalog schema as the AIC / NGA / Met
shards, plus three optional fields:
  same_as            other keys for the same artwork (e.g. "wikidata:Q123"), so an import can
                     skip a work Artelier already holds from Wikimedia Commons
  artist_death_year  the artist's death year when the museum records it (feeds region gating)
  is_age_restricted  true when the title names nudity (whole-word match, several languages)
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

SHARD_SIZE = 5000
UA = {"User-Agent": "ArtelierCatalog/1.0 (https://github.com/jennamharms-source/artelier-catalog; artelier@artelierapp.co)"}
BANNED = ("wikiart.org", "base44", "harvard.edu")

# Same word list as commons_sync.py, plus Dutch (naakt) and Danish (nøgen, badende).
NUDE_W = re.compile(
    r"\b(nudes?|nus?|nues?|naked|odalisques?|bathers?|baigneuses?|nudo|nudi|venus|amor|cupid|"
    r"masturbat\w*|erotic\w*|akt|nackt\w*|halbakt|dana[eë]|leda|lovers|liebespaar|"
    r"naakte?|naaktfiguur|naaktstudie|n[øo]gne?|n[øo]genstudie|badende)\b",
    re.I,
)


def get_json(url, params=None, headers=None, tries=6, timeout=60):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — retry on any network/HTTP error
            code = getattr(e, "code", None)
            if code == 404:
                return None
            time.sleep(65 if code == 429 else 2 * (i + 1))
    raise RuntimeError(f"giving up on {url}")


def wikidata_inventory_map(collection_qid):
    """inventory number -> Wikidata item, for works Wikidata files under this collection."""
    q = (
        "SELECT ?item ?inv WHERE { ?st pq:P195 wd:%s . ?item p:P217 ?st . ?st ps:P217 ?inv . }"
        % collection_qid
    )
    for i in range(6):
        try:
            d = get_json(
                "https://query.wikidata.org/sparql",
                {"query": q},
                headers={"Accept": "application/sparql-results+json"},
                tries=1,
                timeout=180,
            )
            out = {}
            for b in d["results"]["bindings"]:
                out.setdefault(b["inv"]["value"].strip(), b["item"]["value"].rsplit("/", 1)[-1])
            return out
        except Exception:  # noqa: BLE001
            time.sleep(65)
    print(f"warning: Wikidata inventory map for {collection_qid} unavailable; no same_as keys")
    return {}


def is_nude(*texts):
    return any(NUDE_W.search(t or "") for t in texts)


def check_record(r):
    for k in ("image_url", "source_url"):
        v = (r.get(k) or "").lower()
        if any(b in v for b in BANNED):
            raise SystemExit(f"refusing to publish banned host in {k}: {v}")


def write_shards(records, out_dir, prefix, index_meta):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}-*.json"):
        old.unlink()
    files = []
    for n, i in enumerate(range(0, len(records), SHARD_SIZE)):
        name = f"{prefix}-{n:04d}.json"
        (out_dir / name).write_text(json.dumps(records[i : i + SHARD_SIZE], ensure_ascii=False))
        files.append(name)
    meta = {
        **index_meta,
        "records": len(records),
        "artists": len({r["artist"] for r in records}),
        "sensitive": sum(1 for r in records if r.get("is_age_restricted")),
        "with_wikidata_match": sum(1 for r in records if r.get("same_as")),
        "shards": len(files),
        "shard_files": files,
    }
    (out_dir / f"index-{prefix}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"Wrote {len(records)} {prefix} records across {len(files)} shards "
          f"({meta['artists']} artists, {meta['sensitive']} flagged sensitive, "
          f"{meta['with_wikidata_match']} matched to Wikidata)")


def dedupe(records):
    seen, out = set(), []
    for r in records:
        keys = (r["source_key"], r["image_url"], f"{r['title'].lower()}|{r['artist'].lower()}|{r.get('year','')}")
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        check_record(r)
        out.append(r)
    return out
