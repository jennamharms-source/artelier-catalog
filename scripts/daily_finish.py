# Turns a raw commons_sync.py catalog for one artist into a daily shard (catalog/<slug>-0000.json) in the
# gonzales-0000 format, plus where each work is now: `gallery` = the work's current collection on Wikidata
# (P195 statements without an end date), using Artelier's own museum names where one exists so the work
# links to that museum page. Also keeps medium and genre, which importDailyArtists stores.
#
# usage: daily_finish.py <raw.json> <slug> <artist_death_year> <country> [--drop QID_or_source_key ...]
# Drops: non PD/CC0 files, copies / "after" / workshop / attributed, the same image twice, anything in --drop
# (works Artelier already has). Titles are made unique with the year, then the location.
import json, re, sys, time, collections, urllib.request, urllib.parse

ROOT = __file__.rsplit('/scripts/', 1)[0] + '/catalog/'
UA = {'User-Agent': 'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)', 'Accept': 'application/sparql-results+json'}
# Museum names as Artelier spells them (Gallery.name); a work shows on a museum page only on an exact match.
ARTELIER_MUSEUMS = {
    'Prado Museum', 'Rijksmuseum', 'Tate Modern', 'National Gallery', "Musée d'Orsay", 'Louvre Museum', 'Art Institute of Chicago',
    'The Metropolitan Museum of Art', 'National Gallery of Art', 'Getty Center', 'Los Angeles County Museum of Art',
    'Minneapolis Institute of Art', 'Nelson-Atkins Museum of Art', 'Brooklyn Museum', 'The Walters Art Museum', 'Saint Louis Art Museum',
    'The Frick Collection', 'The Morgan Library & Museum', 'Tate Britain', 'The British Museum', 'Ashmolean Museum', 'Dulwich Picture Gallery',
    'The Wallace Collection', 'The Courtauld Gallery', 'Royal Academy of Arts', 'National Portrait Gallery',
    'Victoria and Albert Museum - Cromwell Road, London', 'Montreal Museum of Fine Arts', 'Norton Simon Museum',
    'The Huntington Library, Art Museum, and Botanical Gardens', 'Musée Marmottan Monet', 'Petit Palais', 'Musée Jacquemart-André',
    "Musée de l'Orangerie", 'Fondation Beyeler', 'Neue Galerie New York', 'Van Gogh Museum', 'Peabody Essex Museum', 'Georgia Museum of Art',
    'Hispanic Society Museum & Library', 'Museo Nacional de Arte', 'Museo Soumaya', 'Museo Nacional de Antropología', 'Natural History Museum - London', 'Getty Villa'}
ALIAS = {'Louvre': 'Louvre Museum', 'Musée du Louvre': 'Louvre Museum', 'Museo del Prado': 'Prado Museum',
         'Metropolitan Museum of Art': 'The Metropolitan Museum of Art', 'National Gallery, London': 'National Gallery',
         'The National Gallery': 'National Gallery', 'J. Paul Getty Museum': 'Getty Center', 'National Gallery of Art, Washington': 'National Gallery of Art',
         'Museum of Fine Arts, Montreal': 'Montreal Museum of Fine Arts', 'Walters Art Museum': 'The Walters Art Museum',
         'Wallace Collection': 'The Wallace Collection', 'Huntington Library': 'The Huntington Library, Art Museum, and Botanical Gardens',
         'Victoria and Albert Museum': 'Victoria and Albert Museum - Cromwell Road, London', 'British Museum': 'The British Museum',
         'Frick Collection': 'The Frick Collection', 'Courtauld Gallery': 'The Courtauld Gallery', 'Natural History Museum': 'Natural History Museum - London',
         'Royal Botanic Gardens, Kew': 'Royal Botanic Gardens, Kew'}
# Former owners, wartime depots and provenance funds that Wikidata lists as collections but are not where a work is.
NOT_PLACE = re.compile(r'Führermuseum|Central Collecting Point|NEPIP|Kress Collection|Pieter Smidt van Gelder|^private collection$', re.I)
COPY = re.compile(r'\b(after|studio of|circle of|workshop of|follower of|nachfolger|werkstatt|kopie nach|copy after|imitator of|attributed to|manner of)\b', re.I)


def place(c):
    c = re.sub(r'^Department of .* of the Louvre$', 'Louvre', c.strip())
    c = re.sub(r'^(drawings|prints|paintings) in the National Gallery of Art$', 'National Gallery of Art', c, flags=re.I)
    return c if c in ARTELIER_MUSEUMS else ALIAS.get(c, c)


def choose(cs):
    cs = sorted({place(c) for c in cs if c and not c.startswith('http') and not NOT_PLACE.search(c)},     # http...genid = 'unknown value'
                key=lambda c: (c not in ARTELIER_MUSEUMS, not re.search(r'museum|gallery|galerie|castle|collection|national|foundation|kunst|art|gardens', c, re.I), c))
    return cs[0] if cs else None


def current_collections(qids):
    out, qids = {}, sorted(qids)
    for i in range(0, len(qids), 150):
        q = ('SELECT ?item ?collLabel ?end WHERE { VALUES ?item { %s } ?item p:P195 ?st . ?st ps:P195 ?coll . OPTIONAL { ?st pq:P582 ?end } '
             'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul,de,fr,it,pl,fi,sv,nb". } }' % ' '.join('wd:' + x for x in qids[i:i + 150]))
        req = urllib.request.Request('https://query.wikidata.org/sparql', data=urllib.parse.urlencode({'query': q, 'format': 'json'}).encode(), headers=UA)
        for t in range(5):
            try:
                rows = json.load(urllib.request.urlopen(req, timeout=120))['results']['bindings']; break
            except Exception as e:
                rows = []; time.sleep(65 if '429' in str(e) else 5)       # 429: rate limited - back off
        for b in rows:
            if 'end' not in b:
                out.setdefault(b['item']['value'].rsplit('/', 1)[1], []).append(b['collLabel']['value'])
        time.sleep(1)
    return out


def lang(t):
    tl = t.lower()
    if re.search(r'\b(the|of|with|view|portrait)\b', tl): return 'en'
    if re.search(r'[ąęłńśźż]|\b(widok|portret|kościoła)\b', tl): return 'pl'
    if re.search(r'[æøå]|\b(fransk|havn|ved|og|vinter|norsk|kveld\w*)\b', tl): return 'no'
    if re.search(r'\b(der|die|das|und|mit|von|ansicht|bildnis)\b', tl): return 'de'
    if re.search(r'\b(veduta|ritratto|della|dello|degli|con)\b', tl): return 'it'
    if re.search(r'\b(le|la|les|du|des|au|effet|portrait de)\b', tl): return 'fr'
    if re.search(r'\b(orillas|del|retrato)\b', tl): return 'es'
    return 'en'


def main():
    raw, slug, dy, country = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    drop = set(sys.argv[sys.argv.index('--drop') + 1:]) if '--drop' in sys.argv else set()
    d = json.load(open(raw)); why = collections.Counter(); seen = set(); out = []
    sur = re.escape(d[0]['artist'].split()[-1]) if d else 'x'
    for r in d:
        q = r.get('qid') or ''; f = r['source_url'].rsplit('File:', 1)[-1].replace('_', ' ')
        if q in drop or r['source_key'] in drop: why['already in Artelier']+= 1; continue
        if r['license'] not in ('Public domain', 'CC0') or not re.match(r'^(PD|CC0)', r.get('license_basis') or ''): why['license']+= 1; continue
        if COPY.search(r['title']) or re.match(r'after ' + sur, urllib.parse.unquote(f), re.I): why['copy']+= 1; continue
        if r['image_url'] in seen: why['same image twice']+= 1; continue
        seen.add(r['image_url'])
        t = re.sub(r'(?<![A-Z])\.\s*$', '', r['title'].strip())
        n = dict(title=t, artist=r['artist'], year=r.get('year') or '', image_url=r['image_url'], source_url=r['source_url'], source_key=r['source_key'],
                 is_age_restricted=bool(r.get('is_age_restricted')), license=r['license'], license_basis=r['license_basis'], attribution='Wikimedia Commons',
                 country=country, artist_death_year=dy, title_language=lang(t))
        if q: n['same_as'] = ['wikidata:' + q]
        for k in ('medium', 'genre'):
            if r.get(k): n[k] = r[k]
        n['_q'], n['_coll'] = q, r.get('collection') or r.get('gallery') or ''
        out.append(n)
    cur = current_collections({x['_q'] for x in out if x['_q']})
    for x in out:
        g = choose(cur.get(x['_q'], []) if x['_q'] else [x['_coll']])
        if g: x['gallery'] = g
    for key in ('year', 'gallery'):
        c = collections.Counter(x['title'] for x in out)
        for x in out:
            if c[x['title']] > 1 and x.get(key): x['title'] += (' (%s)' if key == 'year' else ', %s') % x[key]
    c = collections.Counter(x['title'] for x in out); k = collections.Counter()
    for x in out:
        if c[x['title']] > 1:
            k[x['title']] += 1
            if k[x['title']] > 1: x['title'] += ' (%d)' % k[x['title']]
    for x in out: x.pop('_q'); x.pop('_coll')
    assert len({x['title'] for x in out}) == len(out)
    json.dump(out, open(ROOT + slug + '-0000.json', 'w'), ensure_ascii=False, indent=1)
    print(slug, len(d), '->', len(out), dict(why), 'nudes', sum(x['is_age_restricted'] for x in out), 'located', sum(1 for x in out if x.get('gallery')),
          'museum page', sum(1 for x in out if x.get('gallery') in ARTELIER_MUSEUMS))


if __name__ == '__main__':
    main()
