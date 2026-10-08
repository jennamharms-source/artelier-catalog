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

## Wikimedia Commons artist catalog (`catalog/commons/`)

Per-artist catalogs built from **Wikidata + Wikimedia Commons**, for artists whose
work is better covered there than in museum dumps (Renoir, Rembrandt, Cézanne,
Van Gogh, Gauguin, …).

- `artists/<artist>.json`: one config per artist (Wikidata ID, Commons page, date range,
  optional `pd_cutoff` year for artists who died after 1930).
- `scripts/commons_sync.py catalog artists/<artist>.json catalog/commons/<artist>.json`
  builds the catalog. Only files Commons licenses as **Public domain or CC0** are
  kept (CC BY / BY-SA are skipped). Each record carries `license`, `attribution`,
  `source_url` (Commons file page), `source_key` (`wikidata:Q…`), `genre` (Wikidata P136),
  `collection`, and `is_age_restricted` (nudity, from Wikidata genre/depicts + Commons categories).
- `scripts/commons_category.py` covers artists that Wikidata barely covers, such as
  Stieglitz's photographs, by reading a Commons category directly. It keeps only files
  whose creator is the artist.
- `.github/workflows/build-commons.yml` rebuilds everything monthly (5th, 06:00 UTC) or on demand.

## Rights rules (`rights/copyright_rules.json`)

Copyright terms for 219 jurisdictions, each cited to Wikipedia and the Wikimedia Commons
"Copyright rules by territory" pages, grouped into regions (`US`, `EU_EEA_UK_CH`,
`LIFE80`, `MX`, `LIFE50`, …). A work by an artist who died in year D is public domain in
group G in year Y when `D <= max(Y - pma - 1, cutoff)`. The US is decided by publication
year instead: published before Y − 95 means public domain. Artelier uses this to hide images
in regions where a work is still protected. This is a research compilation, not legal advice.

## Static API

The repo is public, so every file is directly fetchable as JSON:

| What | URL |
|---|---|
| Commons catalog index | `https://raw.githubusercontent.com/jennamharms-source/artelier-catalog/main/catalog/commons/index.json` |
| One artist | `https://raw.githubusercontent.com/jennamharms-source/artelier-catalog/main/catalog/commons/renoir.json` |
| Rights rules | `https://raw.githubusercontent.com/jennamharms-source/artelier-catalog/main/rights/copyright_rules.json` |
| Museum shards | `https://raw.githubusercontent.com/jennamharms-source/artelier-catalog/main/catalog/index.json` |

With GitHub Pages turned on (Settings → Pages → Deploy from branch `main`, folder `/`), the same files are also
served at `https://jennamharms-source.github.io/artelier-catalog/…`.

## Sources

| Source | License | Records | Status |
|---|---|---|---|
| Art Institute of Chicago | CC0 / public domain works (`is_public_domain`) | 38,227 | active: monthly (`catalog/aic-*.json`) |
| National Gallery of Art | CC0 / open-access images only | 53,138 | active: monthly (`catalog/nga-*.json`) |
| The Met | CC0; public-domain works per the official Met dataset, restricted images excluded | 82,954 | active: monthly (`catalog/met-*.json`) |
| Wikidata + Wikimedia Commons | Public domain / CC0 files only (CC BY and BY-SA skipped); 1930 cutoff for artists who died after 1930 | per artist, see `catalog/commons/index.json` | active: monthly (`catalog/commons/*.json`) |
| Cleveland Museum of Art | CC0 | — | planned (some CMA images already arrive through Commons) |
| Europeana | Public domain / CC0 only | — | planned (API key pending) |

**Never included:** WikiArt images, images uploaded to Artelier, and any file under CC BY, BY-SA or
another license that restricts reuse. `scripts/build_commons_index.py` refuses to publish the catalog if one slips in.

## Setup (one time)

1. Create this repo on GitHub (private is fine).
2. Upload these files (or push them).
3. Actions tab → "Build Artelier catalog from AIC open data" → Run workflow.
4. ~10 minutes later, `catalog/` contains the dataset.
