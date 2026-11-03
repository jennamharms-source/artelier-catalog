# Ranks artists to add to Artelier: real individual artists who died before 1956, with a large body
# of public-domain / CC0 work on Wikimedia Commons, who are missing from Artelier or have only a few
# works there. Results are cached in artists/candidates.json (names, Wikidata IDs, life dates,
# country, gender, movements and counts only - never Artelier record IDs).
#
# usage: artist_candidates.py refresh                  monthly: Wikidata counts -> artists/candidates.json
#        artist_candidates.py shortlist [N]            next N unchecked candidates (JSON) to look up in Artelier
#        artist_candidates.py record <counts.json>     store Artelier counts: {"Q123": 4, "Q456": 0, ...}
#        artist_candidates.py commons <QID> [QID ...]  count rights-clean (PD/CC0) Commons works per artist (cached)
#        artist_candidates.py pick [N]                 choose today's N (default 3), varied by country/period/gender
#        artist_candidates.py config <QID>             write artists/<slug>.json for commons_sync.py
#
# Heavy aggregate queries go to QLever (qlever.dev, a fast Wikidata mirror) and fall back to the
# Wikidata Query Service; both back off on 429. Artelier itself is checked by the caller with the
# Base44 query_entities tool (this script has no database access) and fed back with `record`.
import json, os, re, sys, time, glob, datetime, unicodedata, urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'artists', 'candidates.json')
UA = {'User-Agent': 'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)', 'Accept': 'application/sparql-results+json'}
QLEVER = 'https://qlever.dev/api/wikidata'
WDQS = 'https://query.wikidata.org/sparql'
DEATH_BEFORE = 1956          # died before this year: public domain in most regions (EU life+70 etc.)
MIN_WORKS = 40               # "large": at least this many works with an image
SMALL_IN_ARTELIER = 10       # "small portfolio": fewer than this many works with a picture in Artelier
TYPES = {                    # Wikidata P31 values counted, by group
    'painting': ['Q3305213', 'Q18761202', 'Q12043905'],                       # painting, watercolor, pastel
    'print': ['Q11060274', 'Q11835431', 'Q18218093', 'Q15123870', 'Q18219090',
              'Q21647744', 'Q18396864', 'Q89503149'],                          # print, engraving, etching, litho, woodcut, mezzotint, aquatint, chromolitho
    'drawing': ['Q93184'],
}
PREFIX = ('PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> '
          'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX schema: <http://schema.org/> ')
# Not individual artists, or names Artelier never makes a profile for (see the import rules).
NOT_A_PERSON = re.compile(r'^(master of|meister de[rs]|maestro d|ma[iî]tre d|monogrammist|workshop|atelier|studio of|circle of|'
                          r'school of|follower|anonymous|unknown|attributed)|\bworkshop\b|\(workshop\)', re.I)
MUSEUM_SHARDS = re.compile(r'^(aic|nga|met|cma|smk|rijks|core|prado|exhibitions|nglondon|vam|moma|guggenheim|whitney)-')
OK_LICENSES = {'Public domain', 'CC0', 'PDM-owner', 'No restrictions'}


def get_json(url, data=None, headers=UA, tries=6):
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            return json.load(urllib.request.urlopen(req, timeout=300))
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(65 if e.code == 429 else 4 * (t + 1))      # 429: rate limited - back off
        except Exception as e:
            last = e
            time.sleep(4 * (t + 1))
    raise last


def sparql(q):
    body = urllib.parse.urlencode({'query': PREFIX + q}).encode()
    try:
        return get_json(QLEVER, data=body, tries=3)['results']['bindings']
    except Exception as e:
        print('  QLever failed (%s), using the Wikidata Query Service' % e, file=sys.stderr)
        return get_json(WDQS, data=body)['results']['bindings']


qid_of = lambda b, k: b[k]['value'].rsplit('/', 1)[1]


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def load():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {'candidates': []}


def save(d):
    d['candidates'].sort(key=lambda c: -c['wd_works']['total'])
    json.dump(d, open(OUT, 'w'), ensure_ascii=False, indent=1)


def done_artists():
    """QIDs and normalized names already handled: per-artist configs, shards, Commons files, the daily queue."""
    qids, names = set(), set()
    for f in glob.glob(os.path.join(ROOT, 'artists', '*.json')):
        if os.path.basename(f) in ('candidates.json', 'artist_profiles_wikidata.json'):
            continue
        try:
            c = json.load(open(f))
        except Exception:
            continue
        if isinstance(c, dict):
            if re.fullmatch(r'Q\d+', str(c.get('qid', ''))): qids.add(c['qid'])
            if c.get('artist'): names.add(norm(c['artist']))
    for f in glob.glob(os.path.join(ROOT, 'catalog', '*-0000.json')) + glob.glob(os.path.join(ROOT, 'catalog', 'commons', '*.json')):
        b = os.path.basename(f)
        if MUSEUM_SHARDS.match(b) or b.startswith('index'):
            continue
        try:
            recs = json.load(open(f))
        except Exception:
            continue
        for r in (recs[:3] if isinstance(recs, list) else []):
            if r.get('artist'): names.add(norm(r['artist']))
    q = os.path.join(ROOT, 'catalog', 'index-daily.json')
    if os.path.exists(q):
        for e in json.load(open(q)):
            if e.get('qid'): qids.add(e['qid'])
            if e.get('artist'): names.add(norm(e['artist']))
    return qids, names


def refresh():
    old = {c['qid']: c for c in load().get('candidates', [])}
    values = ' '.join('(wd:%s "%s")' % (t, g) for g, ts in TYPES.items() for t in ts)
    print('counting works with images per creator ...', flush=True)
    rows = sparql('SELECT ?c ?grp (COUNT(DISTINCT ?item) AS ?n) WHERE { VALUES (?type ?grp) { %s } '
                  '?item wdt:P31 ?type ; wdt:P170 ?c ; wdt:P18 ?img . ?c wdt:P31 wd:Q5 ; wdt:P570 ?d . '
                  'FILTER(YEAR(?d) < %d) } GROUP BY ?c ?grp' % (values, DEATH_BEFORE))
    counts = {}
    for b in rows:
        counts.setdefault(qid_of(b, 'c'), {})[b['grp']['value']] = int(b['n']['value'])
    big = {q: v for q, v in counts.items() if sum(v.values()) >= MIN_WORKS}
    print(len(counts), 'creators,', len(big), 'with >=%d works' % MIN_WORKS, flush=True)
    facts = {q: dict(qid=q, name=None, birth_year=None, death_year=None, gender=None, country=None, movements=[], commons_category=None) for q in big}
    qs = sorted(big)
    for i in range(0, len(qs), 400):
        vals = ' '.join('wd:' + q for q in qs[i:i + 400])
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            facts[qid_of(b, 'c')]['name'] = b['l']['value']
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c rdfs:label ?l FILTER(LANG(?l)="mul") }' % vals):
            f = facts[qid_of(b, 'c')]; f['name'] = f['name'] or b['l']['value']
        for b in sparql('SELECT ?c (MIN(YEAR(?b)) AS ?by) (MAX(YEAR(?d)) AS ?dy) WHERE { VALUES ?c { %s } OPTIONAL { ?c wdt:P569 ?b } ?c wdt:P570 ?d } GROUP BY ?c' % vals):
            f = facts[qid_of(b, 'c')]
            f['birth_year'] = int(b['by']['value']) if 'by' in b else None
            f['death_year'] = int(b['dy']['value']) if 'dy' in b else None
        for b in sparql('SELECT ?c ?g WHERE { VALUES ?c { %s } ?c wdt:P21 ?g }' % vals):
            g = qid_of(b, 'g'); facts[qid_of(b, 'c')]['gender'] = 'f' if g in ('Q6581072', 'Q1052281') else 'm' if g in ('Q6581097', 'Q2449503') else 'x'
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c wdt:P27 ?k . ?k rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            f = facts[qid_of(b, 'c')]; f['country'] = f['country'] or b['l']['value']
        for b in sparql('SELECT ?c ?l WHERE { VALUES ?c { %s } ?c wdt:P135 ?m . ?m rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            f = facts[qid_of(b, 'c')]
            if b['l']['value'] not in f['movements']: f['movements'].append(b['l']['value'])
        for b in sparql('SELECT ?c ?cat WHERE { VALUES ?c { %s } ?c wdt:P373 ?cat }' % vals):
            facts[qid_of(b, 'c')]['commons_category'] = b['cat']['value']
        print('  details', min(i + 400, len(qs)), '/', len(qs), flush=True)
    dq, dn = done_artists()
    out, dropped = [], {'done': 0, 'no name': 0, 'not a person': 0, 'no death year': 0}
    for q, f in facts.items():
        if not f['name'] or re.fullmatch(r'Q\d+', f['name']): dropped['no name'] += 1; continue
        if NOT_A_PERSON.search(f['name']): dropped['not a person'] += 1; continue
        if not f['death_year'] or f['death_year'] >= DEATH_BEFORE: dropped['no death year'] += 1; continue
        if q in dq or norm(f['name']) in dn: dropped['done'] += 1; continue
        c = big[q]
        f['wd_works'] = dict(painting=c.get('painting', 0), print=c.get('print', 0), drawing=c.get('drawing', 0), total=sum(c.values()))
        f['movements'] = f['movements'][:4]
        prev = old.get(q, {})
        for k in ('commons_clean', 'commons_checked', 'artelier_works', 'artelier_checked', 'status', 'note'):
            if k in prev: f[k] = prev[k]
        out.append(f)
    d = {'generated': datetime.date.today().isoformat(),
         'source': 'Wikidata (CC0) via QLever / WDQS: humans with a death date before %d and at least %d works (painting, '
                   'watercolor, pastel, print, drawing) that have an image (P18). Artelier counts come from the app '
                   '(works with a picture); commons_clean = works whose own Commons file is PD/CC0.' % (DEATH_BEFORE, MIN_WORKS),
         'rules': {'death_before': DEATH_BEFORE, 'min_commons_works': MIN_WORKS, 'small_in_artelier': SMALL_IN_ARTELIER},
         'candidates': out}
    save(d)
    print('candidates', len(out), 'dropped', dropped)


def period(c):
    b = c.get('birth_year') or (c['death_year'] - 60)
    return '<1500' if b < 1500 else '1500s' if b < 1600 else '1600s' if b < 1700 else '1700s' if b < 1800 else '1800-1849' if b < 1850 else '1850+'


def ckey(c):
    s = re.sub(r'^(kingdom|republic|principality|grand duchy|duchy|empire|electorate|county|state) of (the )?', '', (c.get('country') or '?').lower())
    s = re.sub(r'\b(empire|kingdom|republic|confederation)\b', '', s).strip()
    return {'dutch': 'netherlands', 'holy roman': 'germany', 'prussia': 'germany', 'bavaria': 'germany', 'austria-hungary': 'austria',
            'russian': 'russia', 'soviet union': 'russia', 'united kingdom of great britain and ireland': 'united kingdom',
            'great britain': 'united kingdom', 'french': 'france', 'french third': 'france', 'second french': 'france'}.get(s, s)


def open_candidates(d):
    dq, dn = done_artists()
    return [c for c in d['candidates'] if c.get('status') not in ('done', 'skipped') and c['qid'] not in dq and norm(c['name']) not in dn]


def shortlist(n=12):
    """Next unchecked candidates, interleaved by period and gender so a day's pick can be varied."""
    d = load()
    todo = [c for c in open_candidates(d) if c.get('artelier_works') is None]
    buckets = {}
    for c in todo:
        buckets.setdefault((period(c), c.get('gender') == 'f'), []).append(c)
    picked, women = [], [c for c in todo if c.get('gender') == 'f'][: max(2, n // 4)]
    picked += women
    keys = sorted(buckets)
    while len(picked) < n and any(buckets.values()):
        for k in keys:
            if buckets[k] and len(picked) < n:
                c = buckets[k].pop(0)
                if c not in picked: picked.append(c)
    print(json.dumps([dict(qid=c['qid'], name=c['name'], born=c.get('birth_year'), died=c['death_year'], country=c.get('country'),
                           gender=c.get('gender'), wikidata_works=c['wd_works']['total']) for c in picked], ensure_ascii=False, indent=1))


def record(path):
    d = load(); counts = json.load(open(path)); today = datetime.date.today().isoformat(); n = 0
    for c in d['candidates']:
        if c['qid'] in counts:
            c['artelier_works'] = int(counts[c['qid']]); c['artelier_checked'] = today; n += 1
    save(d); print('recorded', n)


def commons_counts(qids):
    d = load(); by = {c['qid']: c for c in d['candidates']}; today = datetime.date.today().isoformat()
    for q in qids:
        c = by.get(q)
        if not c: print(q, 'not a candidate'); continue
        rows = sparql('SELECT ?item ?image WHERE { ?item wdt:P170 wd:%s ; wdt:P18 ?image . MINUS { ?item wdt:P31 wd:Q15727816 } }' % q)
        files = {}
        for b in rows:
            files.setdefault(b['item']['value'], set()).add(urllib.parse.unquote(b['image']['value'].split('/')[-1]).replace('_', ' '))
        allf = sorted({f for s in files.values() for f in s}); lic = {}
        for i in range(0, len(allf), 50):
            r = get_json('https://commons.wikimedia.org/w/api.php', data=urllib.parse.urlencode(dict(      # POST: long titles hit 414
                action='query', titles='|'.join('File:' + f for f in allf[i:i + 50]), prop='imageinfo', iiprop='extmetadata',
                iiextmetadatafilter='LicenseShortName', format='json')).encode(), headers={'User-Agent': UA['User-Agent']})
            norm_map = {x['to']: x['from'] for x in r['query'].get('normalized', [])}
            for p in r['query']['pages'].values():
                ii = (p.get('imageinfo') or [{}])[0]
                t = norm_map.get(p['title'], p['title'])[5:]
                lic[t] = ii.get('extmetadata', {}).get('LicenseShortName', {}).get('value')
                lic[p['title'][5:]] = lic[t]
            time.sleep(0.5)
        copy = re.compile(r'\((after|studio of|school of|follower of|imitator of|circle of|workshop of|manner of|style of)\)|\b(nachfolger|werkstatt|kopie nach|copy after)\b', re.I)
        clean = sum(1 for fs in files.values() if any(lic.get(f) in OK_LICENSES and not copy.search(f) for f in fs))
        c['commons_clean'] = clean; c['commons_checked'] = today
        print(q, c['name'], 'works with an image', len(files), 'rights-clean', clean, flush=True)
    save(d)


def pick(n=3):
    d = load()
    ok = [c for c in open_candidates(d) if c.get('artelier_works') is not None and c['artelier_works'] < SMALL_IN_ARTELIER
          and (c.get('commons_clean') or 0) >= MIN_WORKS]
    # score: rights-clean works on Commons that Artelier doesn't show yet
    ok.sort(key=lambda c: -(c['commons_clean'] - c['artelier_works']))
    chosen = []

    def fits(c, strict):
        if any(ckey(c) == ckey(x) for x in chosen): return False
        if strict and any(period(c) == period(x) for x in chosen): return False
        if any(set(m.lower() for m in c.get('movements', [])) & set(m.lower() for m in x.get('movements', [])) for x in chosen): return False
        return True

    women = [c for c in ok if c.get('gender') == 'f']
    if women: chosen.append(women[0])                       # at least one woman whenever one qualifies
    for strict in (True, False):
        for c in ok:
            if len(chosen) >= n: break
            if c not in chosen and fits(c, strict): chosen.append(c)
    if len(chosen) < n:
        chosen += [c for c in ok if c not in chosen][: n - len(chosen)]
    print(json.dumps([dict(qid=c['qid'], name=c['name'], born=c.get('birth_year'), died=c['death_year'], country=c.get('country'),
                           gender=c.get('gender'), period=period(c), movements=c.get('movements'), commons_clean=c['commons_clean'],
                           artelier_works=c['artelier_works'], commons_category=c.get('commons_category')) for c in chosen],
                     ensure_ascii=False, indent=1))
    if len(chosen) < n:
        print('only %d eligible - shortlist and check more candidates' % len(chosen), file=sys.stderr)


def slugify(name):
    s = norm(name).split()
    return re.sub(r'[^a-z]', '', s[-1] if s else 'artist') or 'artist'


def config(q):
    d = load(); c = next((x for x in d['candidates'] if x['qid'] == q), None)
    if not c: sys.exit(q + ' is not in candidates.json')
    slug = slugify(c['name'])
    if os.path.exists(os.path.join(ROOT, 'artists', slug + '.json')) or os.path.exists(os.path.join(ROOT, 'catalog', slug + '-0000.json')):
        slug = re.sub(r'[^a-z]', '', norm(c['name']))     # surname taken: use the full name
    cfg = dict(qid=q, gallery=c['name'], artist=c['name'], artist_re=re.escape(c['name'].split()[-1]).lower(), country=c.get('country') or '',
               years=[(c.get('birth_year') or c['death_year'] - 80) + 10, c['death_year'] + 1], slug=slug, ytol=1, stol=2)
    p = os.path.join(ROOT, 'artists', slug + '.json')
    json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=1)
    print(p)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'refresh': refresh()
    elif cmd == 'shortlist': shortlist(int(sys.argv[2]) if len(sys.argv) > 2 else 12)
    elif cmd == 'record': record(sys.argv[2])
    elif cmd == 'commons': commons_counts(sys.argv[2:])
    elif cmd == 'pick': pick(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    elif cmd == 'config': config(sys.argv[2])
    else: sys.exit(__doc__ or open(__file__).read().split('\nimport')[0])
