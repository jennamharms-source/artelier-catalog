# Artelier Catalog

The canonical, rights-clean artwork dataset for [Artelier](https://artelierapp.com).

Every record in `catalog/` comes from a museum open-access program, filtered to
**public-domain works only**, and carries its license, attribution, and a link
back to the providing institution. This repo is the provenance record for
Artelier's editorial catalog: what's in the app, where it came from, and under
what rights.

## How it works

- `scripts/transform_aic.py` — converts the Art Institute of Chicago
  [open data dump](https://github.com/art-institute-of-chicago/api-data) into
  Artelier-schema shards (`catalog/aic-####.json`, 5,000 records each).
- `.github/workflows/build-catalog.yml` — runs the transform on GitHub's
  infrastructure monthly (AIC refreshes their dump monthly) and commits the
  result. No local machine needed.
- `catalog/index.json` — record counts, artist counts, and shard list.

The app imports these shards via its `importFromCatalog` admin function, which
matches on each record's stable `source_key` so re-imports are idempotent and
duplicates are impossible.

## Sources

| Source | License | Status |
|---|---|---|
| Art Institute of Chicago | CC0 / public domain works | active |
| National Gallery of Art | CC0 / open-access images only | active |
| Cleveland Museum of Art | CC0 | planned |
| The Met | CC0 (images via API) | planned |
| Europeana | PD/CC0/CC-BY filtered | planned (API key pending) |

## Setup (one time)

1. Create this repo on GitHub (private is fine).
2. Upload these files (or push them).
3. Actions tab → "Build Artelier catalog from AIC open data" → Run workflow.
4. ~10 minutes later, `catalog/` contains the dataset.
