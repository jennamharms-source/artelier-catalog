# One museum's paintings from Wikidata + Wikimedia Commons -> catalog/<slug>-0000.json (gonzales-0000 format).
# Only works the museum holds NOW (P195 statement without an end date) that have an image (P18) whose own Commons
# file is Public domain / CC0. Copies are left out: a creator statement qualified as attributed / workshop /
# follower / circle / after / school-of, and titles or file names that say so. Anonymous works stay, credited to
# "Unknown artist" (Artelier never makes a profile for that name). Nudes get is_age_restricted from Wikidata
# genre/depicts, Commons categories and whole-word title matches.
#
# usage: museum_wikidata.py <museum QID> <slug> "<gallery name as Artelier spells it>" [--types painting,watercolor,pastel] [--inv REGEX]
#   --inv: keep only works whose inventory number (P217) matches, e.g. '^NG' for the National Gallery, whose Wikidata
#          collection still lists ~1,500 works transferred to Tate (inventory N0…) without an end date.
import json, re, sys, time, collections, urllib.request, urllib.parse

ROOT = __file__.rsplit('/scripts/', 1)[0]
UA = {'User-Agent': 'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)', 'Accept': 'application/sparql-results+json'}
TYPES = {'painting': 'Q3305213', 'watercolor': 'Q18761202', 'pastel': 'Q12043905', 'panel painting': 'Q15711026'}
MEDIUM = {'Q3305213': 'Painting', 'Q15711026': 'Painting', 'Q18761202': 'Watercolor', 'Q12043905': 'Pastel'}
ANON = {'Q4233718'}
TITLE_LANGS = ['en', 'fr', 'mul', 'de', 'it', 'es', 'nl', 'ru', 'pl', 'sv', 'da', 'nb', 'fi', 'pt', 'ca', 'cs']   # English first, else the work's own language                                       # "anonymous"
# creator qualifiers that make the work not simply by that artist
COPY_QUAL = {'P1773', 'P1774', 'P1775', 'P1776', 'P1777', 'P1780', 'P1877', 'P1778'}  # attributed, workshop, follower, circle, manner, school, after, forgery
NATURE_BAD = {'Q230768', 'Q18603603', 'Q56644435', 'Q5727902', 'Q100349848'}  # attribution, hypothetically, probably, circa-attr, disputed
NUDEQ = {'Q40446', 'Q10791', 'Q114548070', 'Q9103'}
NUDE_CAT = ('nude', 'naked', 'odalisque', 'bathers', 'erotic')
NUDE_W = re.compile(r'\b(nudes?|nus?|nues?|naked|odalisques?|bathers?|baigneuses?|nudo|nudi|venus|cupid|erotic\w*|akt|nackt\w*|dana[eë]|leda)\b', re.I)
COPY_T = re.compile(r'\b(after|studio of|circle of|workshop of|follower of|followers of|imitator of|manner of|style of|attributed to|copy after|copy of|nachfolger|werkstatt)\b', re.I)
OK = {'Public domain': 'Public domain', 'CC0': 'CC0', 'PDM-owner': 'Public domain', 'No restrictions': 'Public domain'}
COUNTRY = {'Republic of Venice': 'Italy', 'Papal States': 'Italy', 'Grand Duchy of Tuscany': 'Italy', 'Duchy of Milan': 'Italy', 'Republic of Florence': 'Italy',
           'Republic of Genoa': 'Italy', 'Kingdom of Naples': 'Italy', 'Duchy of Ferrara': 'Italy', 'Duchy of Mantua': 'Italy', 'Republic of Siena': 'Italy',
           'Duchy of Savoy': 'Italy', 'Kingdom of Sardinia': 'Italy', 'Kingdom of Italy': 'Italy', 'Duchy of Urbino': 'Italy', 'Duchy of Parma': 'Italy',
           'Dutch Republic': 'Netherlands', 'Kingdom of the Netherlands': 'Netherlands', 'Spanish Netherlands': 'Belgium', 'Habsburg Netherlands': 'Belgium',
           'Austrian Netherlands': 'Belgium', 'Burgundian Netherlands': 'Belgium', 'Duchy of Brabant': 'Belgium', 'County of Flanders': 'Belgium',
           'Holy Roman Empire': 'Germany', 'Kingdom of Prussia': 'Germany', 'Kingdom of Bavaria': 'Germany', 'German Empire': 'Germany', 'Kingdom of Saxony': 'Germany',
           'Kingdom of France': 'France', 'French First Republic': 'France', 'First French Empire': 'France', 'Second French Empire': 'France',
           'French Third Republic': 'France', 'Kingdom of England': 'United Kingdom', 'Kingdom of Great Britain': 'United Kingdom',
           'United Kingdom of Great Britain and Ireland': 'United Kingdom', 'Crown of Castile': 'Spain', 'Crown of Aragon': 'Spain', 'Spanish Empire': 'Spain',
           'Kingdom of Spain': 'Spain', 'Russian Empire': 'Russia', 'Austrian Empire': 'Austria', 'Austria-Hungary': 'Austria', 'Archduchy of Austria': 'Austria',
           'Swiss Confederation': 'Switzerland', 'Old Swiss Confederacy': 'Switzerland', 'Denmark–Norway': 'Denmark', 'Kingdom of Denmark': 'Denmark',
           'Kingdom of Portugal': 'Portugal', 'Swedish Empire': 'Sweden', 'Kingdom of Bohemia': 'Czech Republic', 'Kingdom of Hungary': 'Hungary',
           'Polish–Lithuanian Commonwealth': 'Poland', 'Kingdom of Poland': 'Poland', 'Belgium': 'Belgium'}


def sparql(q, tries=6):
    body = urllib.parse.urlencode({'query': q, 'format': 'json'}).encode()
    for t in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request('https://query.wikidata.org/sparql', data=body, headers=UA), timeout=300))['results']['bindings']
        except urllib.error.HTTPError as e:
            last = e; time.sleep(65 if e.code == 429 else 6 * (t + 1))     # 429: rate limited - back off
        except Exception as e:
            last = e; time.sleep(6 * (t + 1))
    raise last


def qid(b, k): return b[k]['value'].rsplit('/', 1)[1]


def year_of(v):
    m = re.match(r'([+-]?)0*(\d+)-', v)
    return -int(m.group(2)) if m.group(1) == '-' else int(m.group(2))


def year_text(v, prec):
    y = year_of(v)
    p = int(prec or 9)
    if p >= 9: return str(y)
    if p == 8: return '%ds' % (y // 10 * 10)
    if p == 7:
        c = (y - 1) // 100 + 1
        return '%d%s century' % (c, 'th' if 10 <= c % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(c % 10, 'th'))
    return ''


def main():
    mq, slug, gname = sys.argv[1], sys.argv[2], sys.argv[3]
    types = [TYPES[t.strip()] for t in (sys.argv[sys.argv.index('--types') + 1] if '--types' in sys.argv else 'painting,panel painting,watercolor,pastel').split(',')]
    vt = ' '.join('wd:' + t for t in types)
    print('works ...', flush=True)
    rows = sparql('SELECT DISTINCT ?item ?t ?img WHERE { ?item p:P195 ?st . ?st ps:P195 wd:%s . FILTER NOT EXISTS { ?st pq:P582 ?e } '
                  '?item wdt:P31 ?t . VALUES ?t { %s } ?item wdt:P18 ?img }' % (mq, vt))
    W = {}
    for b in rows:
        w = W.setdefault(qid(b, 'item'), dict(types=set(), imgs=set()))
        w['types'].add(qid(b, 't')); w['imgs'].add(urllib.parse.unquote(b['img']['value'].rsplit('/', 1)[1]).replace('_', ' '))
    items = sorted(W); print(len(items), 'works with an image', flush=True)
    for i in range(0, len(items), 250):
        vals = ' '.join('wd:' + q for q in items[i:i + 250])
        for b in sparql('SELECT ?item ?l WHERE { VALUES ?item { %s } ?item rdfs:label ?l FILTER(LANG(?l) IN (%s)) }' % (vals, ','.join('"%s"' % l for l in TITLE_LANGS))):
            W[qid(b, 'item')].setdefault('labels', {})[b['l']['xml:lang']] = b['l']['value']
        for b in sparql('SELECT ?item ?v ?p WHERE { VALUES ?item { %s } ?item p:P571/psv:P571 ?n . ?n wikibase:timeValue ?v ; wikibase:timePrecision ?p }' % vals):
            W[qid(b, 'item')].setdefault('dates', []).append((b['v']['value'], b['p']['value']))
        for b in sparql('SELECT ?item ?c ?q ?qv WHERE { VALUES ?item { %s } ?item p:P170 ?s . ?s ps:P170 ?c . OPTIONAL { ?s ?q ?qv . '
                        'FILTER(STRSTARTS(STR(?q), "http://www.wikidata.org/prop/qualifier/")) } }' % vals):
            w = W[qid(b, 'item')]; c = b['c']['value'].rsplit('/', 1)[1] if '/entity/' in b['c']['value'] else 'GENID'
            cr = w.setdefault('creators', {}).setdefault(c, set())
            if 'q' in b:
                p = b['q']['value'].rsplit('/', 1)[1]
                if p in COPY_QUAL: cr.add('copy')
                if p == 'P5102' and 'qv' in b and b['qv']['value'].rsplit('/', 1)[1] in NATURE_BAD: cr.add('attributed')
        for b in sparql('SELECT DISTINCT ?item ?g WHERE { VALUES ?item { %s } { ?item wdt:P136 ?g } UNION { ?item wdt:P180 ?g } }' % vals):
            W[qid(b, 'item')].setdefault('gd', set()).add(qid(b, 'g'))
        for b in sparql('SELECT ?item ?inv WHERE { VALUES ?item { %s } ?item wdt:P217 ?inv }' % vals):
            W[qid(b, 'item')].setdefault('inv', set()).add(b['inv']['value'])
        print('  details', min(i + 250, len(items)), '/', len(items), flush=True)
    people = sorted({c for w in W.values() for c in w.get('creators', {}) if c not in ('GENID',) and c not in ANON})
    P = {c: {} for c in people}
    for i in range(0, len(people), 250):
        vals = ' '.join('wd:' + q for q in people[i:i + 250])
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c rdfs:label ?l FILTER(LANG(?l) IN ("en","mul")) }' % vals):
            P[qid(b, 'c')].setdefault('name', b['l']['value'])
        for b in sparql('SELECT ?c (MAX(YEAR(?d)) AS ?dy) WHERE { VALUES ?c { %s } ?c wdt:P570 ?d } GROUP BY ?c' % vals):
            if 'dy' in b: P[qid(b, 'c')]['death'] = int(b['dy']['value'])
        for b in sparql('SELECT ?c ?k WHERE { VALUES ?c { %s } ?c wdt:P31 ?k }' % vals):
            P[qid(b, 'c')].setdefault('p31', set()).add(qid(b, 'k'))
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c wdt:P27 ?k . ?k rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            P[qid(b, 'c')].setdefault('country', b['l']['value'])
        print('  artists', min(i + 250, len(people)), '/', len(people), flush=True)
    # Commons: license, categories (nudes, license basis)
    files = sorted({f for w in W.values() for f in w['imgs']}); C = {}
    for i in range(0, len(files), 50):
        cont = {}
        while True:
            r = json.load(urllib.request.urlopen(urllib.request.Request('https://commons.wikimedia.org/w/api.php', data=urllib.parse.urlencode(dict(
                action='query', titles='|'.join('File:' + f for f in files[i:i + 50]), prop='imageinfo|categories', iiprop='extmetadata',
                iiextmetadatafilter='LicenseShortName', cllimit=500, format='json', **cont)).encode(), headers={'User-Agent': UA['User-Agent']}), timeout=120))
            nm = {x['to']: x['from'] for x in r['query'].get('normalized', [])}
            for p in r['query']['pages'].values():
                t = nm.get(p['title'], p['title'])[5:]
                c = C.setdefault(t, dict(lic=None, cats=[]))
                c['cats'] += [x['title'][9:] for x in p.get('categories', [])]
                ii = (p.get('imageinfo') or [None])[0]
                if ii: c['lic'] = ii.get('extmetadata', {}).get('LicenseShortName', {}).get('value')
            if 'continue' in r: cont = dict(r['continue'])
            else: break
        time.sleep(0.3)
        if i % 1000 == 0: print('  commons', i, '/', len(files), flush=True)
    out, why = [], collections.Counter()
    for q in items:
        w = W[q]; labs = w.get('labels', {})
        tlang = next((l for l in TITLE_LANGS if labs.get(l, '').strip() and not re.fullmatch(r'Q\d+', labs[l].strip())), None)
        if not tlang: why['no title'] += 1; continue
        t = labs[tlang].strip()
        cr = w.get('creators', {})
        real = {c: f for c, f in cr.items() if c not in ANON and c != 'GENID'}
        if any(f for f in real.values()): why['attributed / workshop / follower'] += 1; continue
        if len(real) > 1: why['several artists'] += 1; continue
        if COPY_T.search(t): why['copy (title)'] += 1; continue
        if real and next(iter(real)) == 'Q5593' and any(year_of(v) > 1923 for v, _ in w.get('dates', [])): why['Picasso after 1923 (owner rule)'] += 1; continue
        if real:
            c = next(iter(real)); p = P.get(c, {})
            if not p.get('name') or 'Q5' not in p.get('p31', set()): why['maker is not a person'] += 1; continue
            artist, death, country = p['name'], p.get('death'), COUNTRY.get(p.get('country'), p.get('country') or '')
        else:
            artist, death, country = 'Unknown artist', None, ''
        good = sorted(f for f in w['imgs'] if OK.get((C.get(f) or {}).get('lic')) and not re.match(r'after ', f, re.I) and not COPY_T.search(f))
        if not good: why['no PD/CC0 file'] += 1; continue
        f = good[0]; cats = C[f]['cats']
        dates = sorted(w.get('dates', []), key=lambda d: -int(d[1]))
        year = year_text(*dates[0]) if dates else ''
        if death and dates:
            y0 = year_of(dates[0][0])
            if int(dates[0][1]) >= 9 and y0 > death + 1: why['dated after the artist died'] += 1; continue
        lb = next((re.sub(r'^PD-Art \((.*)\)$', r'\1', x) for x in cats if re.match(r'^(PD-|CC-Zero|PD-Art)', x) and not re.search(r'missing|Yorck', x)), None)
        lb = 'CC0' if lb == 'CC-Zero' else lb
        lic = OK[C[f]['lic']]
        if not lb: lb = 'CC0' if lic == 'CC0' else 'PD'
        nude = bool(NUDEQ & w.get('gd', set())) or any(n in x.lower() for x in cats for n in NUDE_CAT) or bool(NUDE_W.search(t))
        u = urllib.parse.quote(f.replace(' ', '_'))
        r = dict(title=t.rstrip('.').strip(), artist=artist, year=year, medium=MEDIUM.get(sorted(w['types'])[0], 'Painting'), gallery=gname,
                 image_url='https://commons.wikimedia.org/wiki/Special:FilePath/%s?width=1200' % u, source_url='https://commons.wikimedia.org/wiki/File:%s' % u,
                 source_key='wikidata:' + q, same_as=['commons:' + f], is_age_restricted=nude, license=lic, license_basis=lb, attribution='Wikimedia Commons',
                 country=country, title_language='und' if tlang == 'mul' else tlang)
        if death: r['artist_death_year'] = death
        if '--inv' in sys.argv:
            ok = sorted(v for v in w.get('inv', ()) if re.search(sys.argv[sys.argv.index('--inv') + 1], v))
            if not ok: why['inventory number is not this museum\'s'] += 1; continue
            w['inv'] = ok
        if w.get('inv'): r['inventory_number'] = sorted(w['inv'])[0]
        out.append(r)
    # unique titles per artist (the importer dedupes on normalized title|artist): add year, then inventory number
    key = lambda r: (re.sub(r'[^a-z0-9]+', ' ', r['title'].lower()).strip(), r['artist'])
    for add in ('year', 'inventory_number'):
        c = collections.Counter(key(r) for r in out)
        for r in out:
            if c[key(r)] > 1 and r.get(add): r['title'] += (' (%s)' % r[add]) if add == 'year' else ', ' + r[add]
    c = collections.Counter(key(r) for r in out); k = collections.Counter()
    for r in out:
        if c[key(r)] > 1:
            k[key(r)] += 1
            if k[key(r)] > 1: r['title'] += ' (%d)' % k[key(r)]
    assert len({key(r) for r in out}) == len(out)
    out.sort(key=lambda r: (r['artist'], r['year'] or '9999', r['title']))
    json.dump(out, open('%s/catalog/%s-0000.json' % (ROOT, slug), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(dict(shard=slug + '-0000', works=len(out), artists=len({r['artist'] for r in out}), unknown_artist=sum(r['artist'] == 'Unknown artist' for r in out),
                          nudes=sum(r['is_age_restricted'] for r in out), left_out=dict(why)), ensure_ascii=False))


if __name__ == '__main__':
    main()
