# Second pass over a museum_wikidata.py shard, before it is imported.
#
#   museum_finish.py check  <slug> [<slug> ...]   drop works that could never be shown, drop a second record that
#                                                 shares an image, add artist_wikidata_id (P170), print the artist QIDs
#   museum_finish.py rename <artists.json> <slug> [<slug> ...]
#                                                 rename shard artists to the spelling of the app's existing Artist
#                                                 row with the same wikidata_id (artists.json = query_entities output
#                                                 on Artist, {entities: [...]}); prints the artists that will be new
#
# Never shown: works by a living artist or one with no death date, and works dated 1931 or later by an artist who
# died in 1956 or later (US-hidden by the owner's rule and still in copyright elsewhere). Renaming matters because
# the importer only matches names ("Rembrandt" is not "Rembrandt van Rijn") and would otherwise fork a profile.
import json, re, sys, time, collections, urllib.request, urllib.parse

ROOT = __file__.rsplit('/scripts/', 1)[0] + '/catalog/'
UA = {'User-Agent': 'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)', 'Accept': 'application/sparql-results+json'}


def sparql(q):
    req = urllib.request.Request('https://query.wikidata.org/sparql', data=urllib.parse.urlencode({'query': q, 'format': 'json'}).encode(), headers=UA)
    for t in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=200))['results']['bindings']
        except Exception as e:
            last = e; time.sleep(65 if '429' in str(e) else 6 * (t + 1))
    raise last


def late(year):
    return any(int(y) >= 1931 for y in re.findall(r'\b(19\d\d|20\d\d)\b', year or ''))


def check(slugs):
    allq = set()
    for s in slugs:
        p = ROOT + s + '-0000.json'; d = json.load(open(p)); why = collections.Counter(); out = []; seen = set()
        for r in d:
            dy = r.get('artist_death_year')
            if r['artist'] != 'Unknown artist' and not dy: why['living or no death date'] += 1; continue
            if dy and dy >= 1956 and late(r.get('year')): why['1931+ by an artist who died 1956+'] += 1; continue
            if r['image_url'] in seen: why['image shared with another record'] += 1; continue
            seen.add(r['image_url']); out.append(r)
        qs = [r['source_key'][9:] for r in out]; ic = {}
        for i in range(0, len(qs), 300):
            for b in sparql('SELECT ?item ?c WHERE { VALUES ?item { %s } ?item wdt:P170 ?c }' % ' '.join('wd:' + x for x in qs[i:i + 300])):
                if '/entity/' in b['c']['value']:
                    ic.setdefault(b['item']['value'].rsplit('/', 1)[1], set()).add(b['c']['value'].rsplit('/', 1)[1])
            time.sleep(1)
        for r in out:
            cs = ic.get(r['source_key'][9:], set()) - {'Q4233718'}
            if r['artist'] != 'Unknown artist' and len(cs) == 1:
                r['artist_wikidata_id'] = next(iter(cs)); allq.add(r['artist_wikidata_id'])
        json.dump(out, open(p, 'w'), ensure_ascii=False, indent=1)
        print(s, len(d), '->', len(out), dict(why), file=sys.stderr)
        for r in out:
            if (r.get('artist_death_year') or 0) >= 1956:
                print('   check by hand:', r['artist'], r.get('artist_death_year'), '|', r['title'], r['year'], r['license_basis'], file=sys.stderr)
    print(json.dumps(sorted(allq)))


def rename(path, slugs):
    rows = json.load(open(path)).get('entities', [])
    byq = collections.defaultdict(list)
    for r in rows:
        if r.get('wikidata_id'): byq[r['wikidata_id']].append(r)
    best = lambda q: sorted(byq[q], key=lambda r: (bool(re.search(r'\(|,|\bcalled\b|\?', r['name'])), -(r.get('artwork_count') or 0), len(r['name'])))[0]['name']
    new = set()
    for s in slugs:
        p = ROOT + s + '-0000.json'; d = json.load(open(p)); n = 0
        for r in d:
            q = r.get('artist_wikidata_id')
            if q in byq:
                b = best(q)
                if b != r['artist']: r['artist'] = b; n += 1
            elif r['artist'] != 'Unknown artist':
                new.add(r['artist'])
        json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)
        print(s, 'renamed', n, 'of', len(d))
    print('QIDs with 2+ profiles:', {q: [x['name'] for x in v] for q, v in byq.items() if len(v) > 1})
    print('new artists', len(new), json.dumps(sorted(new), ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1] == 'check': check(sys.argv[2:])
    elif sys.argv[1] == 'rename': rename(sys.argv[2], sys.argv[3:])
