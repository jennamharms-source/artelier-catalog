# Artelier Catalog

The public, rights-clean artwork dataset behind [Artelier](https://artelierapp.com).

Every record here is a **public-domain or CC0 artwork image** from a museum open-access program
or from Wikimedia Commons. Each one carries its license, attribution, and a link back to its
source. This repo is the provenance record for Artelier's editorial catalog: what's in the app,
where it came from, and under what rights.

## Disclosures

**What's included**
- Museum open-access records (Art Institute of Chicago, National Gallery of Art, The Met, Cleveland
  Museum of Art, SMK – National Gallery of Denmark, Rijksmuseum), limited to works the museum
  itself marks as public domain / CC0.
- Wikimedia Commons files that Commons licenses as **Public domain** or **CC0**, matched to the
  artwork through Wikidata.
- Images are not copied into this repo. Each record links to the image on Wikimedia Commons or on
  the museum's own server, plus the page it came from (`source_url`).

**What's never included**
- WikiArt images.
- Images uploaded to Artelier, including artists' own uploads. Artists who post their work on
  Artelier keep their rights, and that work is never part of this dataset.
- Harvard Art Museums images. Their API terms allow non-commercial use only.
- Files under CC BY, CC BY-SA, or any other license that restricts reuse.
- Copies by an artist's followers, workshop, school, or imitators ("after Turner", "studio of",
  "Nachfolger", …), even when Wikidata lists them under the artist.
- `scripts/build_commons_index.py` refuses to publish if a WikiArt, Artelier-upload, or Harvard link,
  or a non-PD/CC0 license, ever slips in.

**Rights notes**
- Commons treats faithful photographs of public-domain paintings and drawings as public domain
  (PD-Art). For photographs of sculptures and other 3D objects, the photographer can hold rights, so
  only photos Commons itself licenses as PD or CC0 are used.
- Copyright terms differ by country. `rights/copyright_rules.json` records the term for each
  country. Artelier uses it to hide an image wherever the work may still be protected.
- `rights/artist_dates.json` lists birth and death years (from Wikidata) for artists whose dates the
  app didn't have, so it can apply those country rules. Artists marked `living` are treated as
  protected everywhere.
- This is a good-faith research compilation, not legal advice.

**Sensitive content**
- `is_age_restricted` marks nudity. It is set automatically from Wikidata (genre / depicts), Commons
  categories, and whole-word title matches ("nude", "Akt", "baigneuse", …), so it can be wrong in
  either direction.

**Corrections and removal requests**
- If you think a record shouldn't be here, or the credit is wrong, email
  **artelier@artelierapp.co** with the record's `source_url` or `source_key`. We'll review it and
  remove it if it shouldn't be here.

## Sources

| Source | License | Records | Status |
|---|---|---|---|
| Art Institute of Chicago | CC0 / public domain works (`is_public_domain`) | 38,227 | active: monthly (`catalog/aic-*.json`) |
| National Gallery of Art | CC0 / open-access images only | 53,138 | active: monthly (`catalog/nga-*.json`) |
| The Met | CC0; public-domain works per the official Met dataset, restricted images excluded | 82,954 | active: monthly (`catalog/met-*.json`) |
| Wikidata + Wikimedia Commons | Public domain / CC0 files only (CC BY and BY-SA skipped); 1930 cutoff for artists who died after 1930 | 15,407 works by 32 artists (see `catalog/commons/index.json`) | active: monthly (`catalog/commons/*.json`) |
| Cleveland Museum of Art | CC0 works with images (`share_license_status`) | see `catalog/index-cma.json` | active: monthly (`catalog/cma-*.json`) |
| SMK – National Gallery of Denmark | Public Domain Mark / CC0 (`public_domain=true`) | see `catalog/index-smk.json` | active: monthly (`catalog/smk-*.json`) |
| Rijksmuseum | CC0 / Public Domain Mark; paintings for now | see `catalog/index-rijks.json` | active: monthly (`catalog/rijks-*.json`) |
| Europeana | Public domain / CC0 only | — | planned (API key pending) |
| Harvard Art Museums | API terms: non-commercial use only | — | **not used** |
| WikiArt | no license granted to third parties | — | **not used** |

## Static API

The repo is public, so every file can be fetched directly as JSON, from GitHub Pages or from raw GitHub:

| What | URL |
|---|---|
| Commons catalog index | `https://jennamharms-source.github.io/artelier-catalog/catalog/commons/index.json` |
| One artist | `https://jennamharms-source.github.io/artelier-catalog/catalog/commons/renoir.json` |
| Rights rules | `https://jennamharms-source.github.io/artelier-catalog/rights/copyright_rules.json` |
| Museum shards | `https://jennamharms-source.github.io/artelier-catalog/catalog/index.json` (AIC), `index-nga.json`, `index-met.json`, `index-cma.json`, `index-smk.json`, `index-rijks.json` |

The same paths also work under `https://raw.githubusercontent.com/jennamharms-source/artelier-catalog/main/…`.

## How it works

### Museum shards (`catalog/*.json`)

- `scripts/transform_aic.py` converts the Art Institute of Chicago
  [open data dump](https://github.com/art-institute-of-chicago/api-data) into Artelier-schema shards
  (`catalog/aic-####.json`, 5,000 records each). `transform_nga.py` (NGA open data) and
  `transform_met_v2.py` (the Met's official open-access CSV) produce `nga-*` and `met-*` shards in the
  same schema.
- `.github/workflows/build-catalog.yml` rebuilds the shards monthly on GitHub's servers and commits the
  result.
- `scripts/transform_cma.py`, `transform_smk.py` and `transform_rijks.py` read the Cleveland, SMK and
  Rijksmuseum open-access APIs (no keys needed) into `cma-*`, `smk-*` and `rijks-*` shards, run monthly
  by `.github/workflows/build-museums.yml`. Their records add three optional fields: `same_as`
  (e.g. `wikidata:Q…`, matched through the museum's inventory number, so an import can skip a work
  already held from Wikimedia Commons), `artist_death_year` (from the museum's own artist record),
  and `is_age_restricted` (title names nudity). Works with no named maker are left out for now.
- `catalog/index.json` lists record counts, artist counts, and shards.

The app imports shards through its `importFromCatalog` admin function. It matches on each record's
stable `source_key`, so re-imports never create duplicates.

### Wikimedia Commons artist catalog (`catalog/commons/`)

Per-artist catalogs built from **Wikidata + Wikimedia Commons**, for artists whose work Commons covers
better than museum dumps do (Renoir, Rembrandt, Canaletto, Jacques-Louis David, Van Gogh, …).

- `artists/<artist>.json`: one config per artist (Wikidata ID, Commons page, date range, and an
  optional `pd_cutoff` year for artists who died after 1930).
- `scripts/commons_sync.py catalog artists/<artist>.json catalog/commons/<artist>.json` builds one
  catalog. Each record carries `license`, `attribution`, `source_url` (Commons file page), `source_key`
  (`wikidata:Q…`), `genre` (Wikidata P136), `collection`, `license_basis`, and `is_age_restricted`.
- `scripts/commons_category.py` covers artists Wikidata barely covers (for example Stieglitz's
  photographs) by reading a Commons category directly, keeping only files whose creator is the artist.
- `.github/workflows/build-commons.yml` rebuilds everything monthly (on the 5th, 06:00 UTC), or on
  demand from the Actions tab.

### Rights rules (`rights/copyright_rules.json`)

Copyright terms for 219 jurisdictions, each cited to Wikipedia and to the Wikimedia Commons
"Copyright rules by territory" pages, grouped into regions (`US`, `EU_EEA_UK_CH`, `LIFE80`, `MX`,
`LIFE50`, …). A work by an artist who died in year D is public domain in group G in year Y when
`D <= max(Y - pma - 1, cutoff)`. The US goes by publication date instead: a work published before
Y − 95 is public domain.

## Maintenance

All three workflows run on their own schedule (AIC/NGA/Met on the 3rd, Cleveland/SMK/Rijksmuseum on
the 4th, Commons on the 5th). To refresh early, open the **Actions** tab, pick the workflow, and click
**Run workflow**.
