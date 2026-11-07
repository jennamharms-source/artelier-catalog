# Daily artist shards for Artelier: turns commons_sync.py output into a catalog shard in the house
# format, checks it, and queues it in catalog/index-daily.json, which the app's importDailyArtists
# function imports (Base44 workflow "Daily Artist Import", 22:00 UTC; shards queued in the last 7 days).
#
# usage: daily_shard.py lock                              take the daily-run lock (exit 3 if another run holds it)
#        daily_shard.py unlock                            release it
#        daily_shard.py aliases <QID>                     the artist's other names, as a regex for query_entities
#        daily_shard.py build <artists/slug.json> [existing.json] [--galleries galleries.json]
#             -> catalog/<slug>-0000.json. existing.json = the artist's works already in Artelier, as
#                [{"title", "year", "image_url"}] from query_entities (a temp file; never commit it).
#                Works matching one of them (title + year rules of commons_sync.py) are left out.
#        daily_shard.py check <catalog/slug-0000.json>  validate a shard; prints what the app should show
#        daily_shard.py holders <catalog/slug-0000.json> [galleries.json]
#             where each work is (Wikidata P195 collection / P276 location), grouped per museum: the backfill plan
#             for works already imported without a gallery. galleries.json = [{"name", "city"}] of every Artelier
#             Gallery from query_entities (temp file; never commit it); without it, daily_finish.py's museum list.
#        daily_shard.py queue <artists/slug.json>       append today's entry (UTC date) with life dates,
#             nationality, movement, description and a PD/CC0 portrait; refuses if the shard or the artist
#             is already queued, or if 3 artists are already queued today
#
# Rules (the owner's standing rules): Commons files licensed Public domain / CC0 only; no copies
# (after / studio of / workshop / follower / Nachfolger / Werkstatt ...); nudes flagged whole-word;
# never re-add a work Artelier has; titles unique; the public repo never gets Artelier record IDs,
# WikiArt links or Artelier uploads.
import json, os, re, sys, glob, time, shutil, datetime, subprocess, tempfile, unicodedata, html
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, 'catalog', 'index-daily.json')
PORTRAITS = os.path.join(ROOT, 'rights', 'artist_portraits.json')
LOCK = os.path.join(ROOT, '.git', 'daily-artists.lock')          # inside .git: can never be committed
UA = {'User-Agent': 'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)', 'Accept': 'application/sparql-results+json'}
PER_DAY = int(os.environ.get("ARTELIER_PER_DAY", "3"))   # owner can raise it for one day (2026-11-07: "do all the women")
OK = {'Public domain': 'Public domain', 'CC0': 'CC0', 'PDM-owner': 'Public domain', 'No restrictions': 'Public domain'}
BANNED = re.compile(r'wikiart\.org|base44|harvard\.edu|supabase|cloudinary', re.I)
GENERIC_COPY = (r'kopie nach|copy after|copy of|workshop of|studio of|circle of|follower of|imitator of|manner of|style of|'
                r'werkstatt|schule des|nachfolger|nachahmer|umkreis|\((after|studio of|workshop|follower)')


def copy_re(artist):
    """Copies by followers, workshops and imitators. "after" and "school of" only count with the artist's surname
    ("After the Meeting" is a title; "after Turner" is a copy)."""
    sur = re.escape(str(artist or '').split()[-1]) if str(artist or '').split() else 'zzzz'
    return re.compile(GENERIC_COPY + r'|\bafter ' + sur + r'\b|\bnach ' + sur[:5] + r'|school of ' + sur, re.I)


LANGS = ['en', 'fr', 'de', 'it', 'es', 'nl', 'pt', 'sv', 'da', 'nb', 'pl', 'ru', 'ca', 'cs', 'fi', 'ja', 'zh']
SHARD_RE = re.compile(r'^[a-z]+-\d{4}$')


def get_json(url, data=None, headers=UA, tries=6):
    last = None
    for t in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=180))
        except urllib.error.HTTPError as e:
            last = e; time.sleep(65 if e.code == 429 else 4 * (t + 1))     # 429: rate limited, back off
        except Exception as e:
            last = e; time.sleep(4 * (t + 1))
    raise last


def sparql(q):
    q = ('PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> '
         'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX schema: <http://schema.org/> '
         'PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> '
         'PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX wikibase: <http://wikiba.se/ontology#> '
         'PREFIX skos: <http://www.w3.org/2004/02/skos/core#> ') + q
    body = urllib.parse.urlencode({'query': q}).encode()
    try:
        return get_json('https://qlever.dev/api/wikidata', data=body, tries=3)['results']['bindings']
    except Exception:
        return get_json('https://query.wikidata.org/sparql', data=body)['results']['bindings']


def commons_info(files):
    """License, author and credit of Commons files (POST: long title lists hit HTTP 414 as GET)."""
    out = {}
    for i in range(0, len(files), 50):
        r = get_json('https://commons.wikimedia.org/w/api.php', data=urllib.parse.urlencode(dict(
            action='query', titles='|'.join('File:' + f for f in files[i:i + 50]), prop='imageinfo', iiprop='extmetadata',
            iiextmetadatafilter='LicenseShortName|Artist|Credit', format='json')).encode(), headers={'User-Agent': UA['User-Agent']})
        back = {x['to']: x['from'] for x in r['query'].get('normalized', [])}
        for p in r['query']['pages'].values():
            mm = ((p.get('imageinfo') or [{}])[0]).get('extmetadata', {})
            txt = lambda k: re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', mm.get(k, {}).get('value', '')))).strip()
            info = dict(license=mm.get('LicenseShortName', {}).get('value'), artist=txt('Artist'), credit=txt('Credit'))
            out[back.get(p['title'], p['title'])[5:]] = info
            out[p['title'][5:]] = info
        time.sleep(0.5)
    return out


def normalize(s):
    """The app importer's title key (shared/catalogImport.ts normalize)."""
    s = unicodedata.normalize('NFD', str(s or '').lower())
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'[.,/#!$%^&*;:{}=\-_`~()"\'?]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ---- which museum holds a work: Wikidata P195 (collection), P276 (location) -> Artelier Gallery.name ----
# A work shows on a museum page only when Artwork.gallery equals Gallery.name exactly. Gallery names follow the
# owner's rule: one location "Name"; several cities "Name - City"; several in one city "Name - Street, City".
# galleries.json = [{"name", "city"}] from query_entities on Gallery (a temp file; never commit it).
PRIVATE = {'Q768717', 'Q475667'}                        # "private collection"; the never-built Führermuseum
NOT_HOLDER_TYPES = {'Q5', 'Q768717', 'Q811683', 'Q33837', 'Q23442', 'Q6256', 'Q3624078'}   # person (a private collector),
#   private collection, proposed / never-built building, archipelago, island, country, sovereign state
NOT_A_HOLDER = re.compile(r'private collection|privately held|private ownership|unknown|art market|auction|art dealer|'
                          r'collecting point|f\u00fchrermuseum|sonderauftrag|nepip|kress collection', re.I)   # wartime / looted-art depots are history, not holders
CITY_TYPES = {'Q515', 'Q1549591', 'Q5119', 'Q1637706', 'Q200250', 'Q1093829', 'Q3957', 'Q484170', 'Q747074', 'Q2074737',
              'Q42744322', 'Q22865', 'Q15284', 'Q262166', 'Q5153359', 'Q493522', 'Q2039348', 'Q755707', 'Q127448',
              'Q856076', 'Q7930989', 'Q1763214', 'Q15127012', 'Q1906268', 'Q2264924', 'Q1187811', 'Q1115575', 'Q532'}
# Wikidata names (normalized) that Artelier spells differently beyond case, accents, "the" and "&"
HOLDER_ALIASES = {
    'louvre': 'Louvre Museum', 'musee du louvre': 'Louvre Museum', 'louvre museum': 'Louvre Museum',
    'museo del prado': 'Prado Museum', 'museo nacional del prado': 'Prado Museum', 'prado museum': 'Prado Museum',
    'national gallery london': 'National Gallery', 'national gallery': 'National Gallery',
    'j paul getty museum': 'Getty Center', 'getty museum': 'Getty Center', 'getty center': 'Getty Center',
    'museum of modern art': 'The Museum of Modern Art (MoMA)', 'moma': 'The Museum of Modern Art (MoMA)',
    'victoria and albert museum': 'Victoria and Albert Museum - Cromwell Road, London',
    'courtauld institute of art': 'The Courtauld Gallery', 'courtauld gallery': 'The Courtauld Gallery',
    'huntington library': 'The Huntington Library, Art Museum, and Botanical Gardens',
    'national gallery of art washington': 'National Gallery of Art', 'national gallery of art': 'National Gallery of Art',
    'metropolitan museum of art': 'The Metropolitan Museum of Art', 'met': 'The Metropolitan Museum of Art',
}


def hkey(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    return re.sub(r'^the ', '', s)


def gallery_index(path):
    """Artelier's Gallery rows from galleries.json; without one, the museum names daily_finish.py knows (no cities)."""
    if path:
        rows = json.load(open(path))
    else:
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        from daily_finish import ARTELIER_MUSEUMS
        rows = [dict(name=n, city=None) for n in sorted(ARTELIER_MUSEUMS)]
    by_name, by_base = {}, {}
    for g in rows:
        name = str(g.get('name') or '').strip()
        if not name: continue
        by_name.setdefault(hkey(name), []).append(g)
        if ' - ' in name:                                   # "Name - City" / "Name - Street, City"
            by_base.setdefault(hkey(name.split(' - ')[0]), []).append(g)
    exact = {g['name']: g for gs in by_name.values() for g in gs}
    return dict(by_name=by_name, by_base=by_base, exact=exact)


CITY_SAME = {'city of westminster': 'london', 'city of london': 'london', 'westminster': 'london', 'kensington': 'london',
             'manhattan': 'new york', 'new york city': 'new york', 'washington': 'washington d c', 'washington dc': 'washington d c',
             'district of columbia': 'washington d c', 'paris 1er arrondissement': 'paris', '1st arrondissement of paris': 'paris',
             '7th arrondissement of paris': 'paris'}


def city_key(c):
    k = hkey(c)
    return CITY_SAME.get(k, k)


def map_holder(h, idx):
    """The Artelier Gallery row for a holder, or None. Never guesses between two rows."""
    if not idx or not idx['exact']: return None
    keys = [hkey(x) for x in [h['label']] + h['aliases'] if x]
    for k in keys:
        if k in HOLDER_ALIASES and HOLDER_ALIASES[k] in idx['exact']:
            return idx['exact'][HOLDER_ALIASES[k]]
    same_city = lambda g: not (h.get('city') and g.get('city')) or city_key(g['city']) == city_key(h['city'])
    for k in keys:                                          # a name match in another city is a different place: Sweden's portrait
        rows = [g for g in idx['by_name'].get(k, []) if same_city(g)]   # gallery ("National Portrait Gallery"), Amsterdam's "Jewish Museum", NG Prague
        if len(rows) == 1: return rows[0]
    for k in keys:                                          # "Name - City": the base name plus the holder's city
        rows = [g for g in idx['by_base'].get(k, []) if h.get('city') and hkey(g.get('city')) == hkey(h['city'])]
        if len(rows) == 1: return rows[0]
    if h.get('parents') and not h.get('_parent'):          # a department or wing of a museum Artelier has
        return map_holder(dict(h, label=h['parents'][0], aliases=h['parents'][1:], parents=[], _parent=True), idx)
    return None


def holders_for(item_qids):
    """{work QID: [holder, ...]} from P195 and P276 statements that are current (no end date) and not deprecated."""
    out, hq = {}, set()
    items = sorted(set(item_qids))
    for i in range(0, len(items), 250):
        vals = ' '.join('wd:' + q for q in items[i:i + 250])
        for b in sparql('SELECT ?item ?prop ?h ?rank WHERE { VALUES ?item { %s } '
                        '{ ?item p:P195 ?st . ?st ps:P195 ?h . BIND("P195" AS ?prop) } UNION '
                        '{ ?item p:P276 ?st . ?st ps:P276 ?h . BIND("P276" AS ?prop) } '
                        '?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank) '
                        'FILTER NOT EXISTS { ?st pq:P582 ?end } }' % vals):
            h = b['h']['value']
            if not re.match(r'^http://www\.wikidata\.org/entity/Q\d+$', h): continue      # "unknown value"
            q = b['item']['value'].rsplit('/', 1)[1]; hid = h.rsplit('/', 1)[1]
            out.setdefault(q, []).append(dict(prop=b['prop']['value'], qid=hid, preferred=b['rank']['value'].endswith('PreferredRank')))
            hq.add(hid)
    facts = {q: dict(qid=q, label=None, aliases=[], parents=[], types=set(), city=None, country=None, dissolved=False) for q in hq}
    hs = sorted(hq)
    for i in range(0, len(hs), 250):
        vals = ' '.join('wd:' + q for q in hs[i:i + 250])
        for b in sparql('SELECT ?h ?l (LANG(?l) AS ?lang) WHERE { VALUES ?h { %s } ?h rdfs:label ?l FILTER(LANG(?l) IN ("en","mul")) }' % vals):
            f = facts[b['h']['value'].rsplit('/', 1)[1]]
            if b['lang']['value'] == 'en' or not f['label']: f['label'] = re.sub(r'\s+', ' ', b['l']['value']).strip()
        for b in sparql('SELECT ?h ?a WHERE { VALUES ?h { %s } ?h skos:altLabel ?a FILTER(LANG(?a)="en") }' % vals):
            facts[b['h']['value'].rsplit('/', 1)[1]]['aliases'].append(b['a']['value'])
        for b in sparql('SELECT ?h ?t WHERE { VALUES ?h { %s } ?h wdt:P31 ?t }' % vals):
            facts[b['h']['value'].rsplit('/', 1)[1]]['types'].add(b['t']['value'].rsplit('/', 1)[1])
        for b in sparql('SELECT ?h ?l WHERE { VALUES ?h { %s } ?h wdt:P361 ?pa . ?pa rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            facts[b['h']['value'].rsplit('/', 1)[1]]['parents'].append(b['l']['value'])      # "part of": Louvre department -> Louvre
        for b in sparql('SELECT DISTINCT ?h WHERE { VALUES ?h { %s } ?h wdt:P576 ?d }' % vals):
            facts[b['h']['value'].rsplit('/', 1)[1]]['dissolved'] = True
        for b in sparql('SELECT ?h ?l WHERE { VALUES ?h { %s } ?h wdt:P17 ?c . ?c rdfs:label ?l FILTER(LANG(?l)="en") }' % vals):
            facts[b['h']['value'].rsplit('/', 1)[1]]['country'] = b['l']['value']
        # city: the holder's "located in" (P131), or one level up, when that place is a city or town
        for b in sparql('SELECT ?h ?a ?al ?at ?b ?bl ?bt WHERE { VALUES ?h { %s } ?h wdt:P131 ?a . ?a rdfs:label ?al FILTER(LANG(?al)="en") '
                        'OPTIONAL { ?a wdt:P31 ?at } OPTIONAL { ?a wdt:P131 ?b . ?b rdfs:label ?bl FILTER(LANG(?bl)="en") OPTIONAL { ?b wdt:P31 ?bt } } }' % vals):
            f = facts[b['h']['value'].rsplit('/', 1)[1]]
            at = b.get('at', {}).get('value', '').rsplit('/', 1)[-1]; bt = b.get('bt', {}).get('value', '').rsplit('/', 1)[-1]
            if at in CITY_TYPES: f['city'] = b['al']['value']
            elif bt in CITY_TYPES and not f['city']: f['city'] = b['bl']['value']
            if f['city']: f['city'] = re.sub(r'\s+[Mm]unicipality$', '', f['city'])     # "Oslo Municipality" -> "Oslo"
    for q, hl in out.items():
        for h in hl: h.update({k: v for k, v in facts[h['qid']].items() if k != 'qid'})
    return out


def usable(h):
    return bool(h.get('label')) and h['qid'] not in PRIVATE and not (h['types'] & NOT_HOLDER_TYPES) and not h.get('dissolved') \
        and not NOT_A_HOLDER.search(h['label']) and not (h['types'] & CITY_TYPES and h['prop'] == 'P195') \
        and not (h['prop'] == 'P276' and h['types'] & CITY_TYPES)        # a city as "location" says nothing about the museum


def pick_holder(hl, idx):
    """(gallery, city, country, mapped, holder) for one work, or None. A holder Artelier has a Gallery page for wins
    (its location first, then its collection); otherwise the collection's English name, then the location's."""
    hl = sorted([h for h in hl or [] if usable(h)], key=lambda h: (not h['preferred'], h['prop'] != 'P195'))
    for prop in ('P276', 'P195'):
        for h in hl:
            g = map_holder(h, idx) if h['prop'] == prop else None
            if g: return g['name'], g.get('city') or h.get('city'), h.get('country'), True, h
    for prop in ('P195', 'P276'):
        for h in hl:
            if h['prop'] == prop: return h['label'], h.get('city'), h.get('country'), False, h
    return None


def items_for_files(files):
    """Wikidata items whose image (P18) is one of these Commons files: {file: QID}."""
    out = {}
    fs = sorted(set(files))
    for i in range(0, len(fs), 100):
        iris = set()
        for f in fs[i:i + 100]:
            for safe in ('', "()',!*"):
                iris.add('<http://commons.wikimedia.org/wiki/Special:FilePath/%s>' % urllib.parse.quote(f.replace('_', ' '), safe=safe))
        for b in sparql('SELECT ?item ?img WHERE { VALUES ?img { %s } ?item wdt:P18 ?img }' % ' '.join(sorted(iris))):
            out[urllib.parse.unquote(b['img']['value'].split('/')[-1])] = b['item']['value'].rsplit('/', 1)[1]
    return out


def work_qid(r):
    """The Wikidata item behind a catalog record: its source_key / same_as, else None (commons keys resolve via P18)."""
    for k in [r.get('source_key')] + list(r.get('same_as') or []):
        m = re.match(r'^wikidata:(Q\d+)$', str(k or ''))
        if m: return m.group(1)
    return None


def holder_plan(recs, galleries_path):
    """Per record: the holder to show. Returns ({source_key: (gallery, city, country, mapped, holder_qid)}, unmapped names)."""
    idx = gallery_index(galleries_path)
    q_of = {r['source_key']: work_qid(r) for r in recs}
    files = {r['source_key']: r['source_key'][8:] for r in recs if not q_of[r['source_key']] and r['source_key'].startswith('commons:')}
    found = items_for_files(files.values()) if files else {}
    for k, f in files.items(): q_of[k] = found.get(f.replace('_', ' '))
    hold = holders_for([q for q in q_of.values() if q])
    plan, unmapped = {}, {}
    for k, q in q_of.items():
        pk = pick_holder(hold.get(q), idx) if q else None
        if pk:
            plan[k] = (pk[0], pk[1], pk[2], pk[3], pk[4]['qid'])
            if not pk[3]: unmapped[pk[0]] = unmapped.get(pk[0], 0) + 1
    return plan, unmapped


def holders_cmd(shard_path, galleries_path):
    """Backfill plan for works already imported: one group per (gallery, city), with the source_keys to update."""
    recs = json.load(open(shard_path))
    plan, unmapped = holder_plan(recs, galleries_path)
    groups = {}
    for k, (g, city, country, mapped, hq) in plan.items():
        groups.setdefault((g, city or '', mapped, hq), []).append(k)
    out = [dict(gallery=g, city=c or None, mapped=m, holder=hq, works=len(ks), source_keys=sorted(ks))
           for (g, c, m, hq), ks in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    print(json.dumps(dict(shard=os.path.basename(shard_path)[:-5], works=len(recs), with_holder=len(plan),
                          no_holder=len(recs) - len(plan), groups=out), ensure_ascii=False, indent=1))


def artist_facts(qid):
    f = dict(birth_year=None, death_year=None, nationality=None, art_movement=None, description=None, portrait_files=[])
    for b in sparql('SELECT (MIN(YEAR(?b)) AS ?by) (MAX(YEAR(?d)) AS ?dy) WHERE { OPTIONAL { wd:%s wdt:P569 ?b } OPTIONAL { wd:%s wdt:P570 ?d } }' % (qid, qid)):
        f['birth_year'] = int(b['by']['value']) if 'by' in b else None
        f['death_year'] = int(b['dy']['value']) if 'dy' in b else None
    for b in sparql('SELECT ?l WHERE { wd:%s wdt:P27 ?k . ?k rdfs:label ?l FILTER(LANG(?l)="en") } LIMIT 1' % qid):
        f['nationality'] = b['l']['value']
    for b in sparql('SELECT ?l WHERE { wd:%s wdt:P135 ?k . ?k rdfs:label ?l FILTER(LANG(?l)="en") } LIMIT 1' % qid):
        f['art_movement'] = b['l']['value']
    for b in sparql('SELECT ?d WHERE { wd:%s schema:description ?d FILTER(LANG(?d)="en") } LIMIT 1' % qid):
        f['description'] = b['d']['value']
    for b in sparql('SELECT ?img WHERE { wd:%s wdt:P18 ?img }' % qid):
        f['portrait_files'].append(urllib.parse.unquote(b['img']['value'].split('/')[-1]).replace('_', ' '))
    return f


def aliases(qid):
    """Other names the artist goes by (Wikidata aliases and pseudonyms), as one regex for query_entities on
    Artwork.artist: works can sit in Artelier under a variant (Bellotto under "Canaletto")."""
    names = set()
    for b in sparql('SELECT ?n WHERE { { wd:%s rdfs:label ?n } UNION { wd:%s <http://www.w3.org/2004/02/skos/core#altLabel> ?n } '
                    'UNION { wd:%s wdt:P742 ?n } FILTER(LANG(?n) IN ("en","mul","fr","de","it","es","nl","")) }' % (qid, qid, qid)):
        names.add(b['n']['value'].strip())
    main = next((b['l']['value'] for b in sparql('SELECT ?l WHERE { wd:%s rdfs:label ?l FILTER(LANG(?l)="en") } LIMIT 1' % qid)), '')
    keep = {n for n in names if len(n) > 3} | ({main.split()[-1]} if main.split() else set())
    print(json.dumps(dict(names=sorted(names), regex='|'.join(sorted(re.escape(n) for n in keep))), ensure_ascii=False))


def lock():
    try:
        os.mkdir(LOCK)
    except FileExistsError:
        age = time.time() - os.path.getmtime(LOCK)
        if age < 3 * 3600:
            sys.exit(print('another daily run holds the lock (%d min old): stop' % (age // 60)) or 3)
        shutil.rmtree(LOCK); os.mkdir(LOCK)                     # stale lock from a crashed run
    open(os.path.join(LOCK, 'pid'), 'w').write('%d %s\n' % (os.getppid(), datetime.datetime.utcnow().isoformat()))
    print('locked')


def unlock():
    shutil.rmtree(LOCK, ignore_errors=True); print('unlocked')


def build(cfg_path, existing_path=None, galleries_path=None):
    cfg = json.load(open(cfg_path)); slug = cfg['slug']
    if not SHARD_RE.match(slug + '-0000'): sys.exit('slug must be lowercase letters only: ' + slug)
    existing = json.load(open(existing_path)) if existing_path else []
    db = [dict(id='x%d' % i, title=e.get('title') or '', year=e.get('year') or '', artist=cfg['artist'],
               image_url=e.get('image_url') or '', is_age_restricted=bool(e.get('is_age_restricted'))) for i, e in enumerate(existing)]
    tmp = tempfile.mkdtemp(prefix='daily_shard_')
    try:
        json.dump(db, open(os.path.join(tmp, 'db.json'), 'w'))
        # plan mode: drops works Artelier already has (title + year rules), copies and internal duplicates
        subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'commons_sync.py'), 'plan', os.path.abspath(cfg_path), 'db.json'],
                       cwd=tmp, check=True)
        creates = json.load(open(os.path.join(tmp, slug + '_creates.json')))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    facts = artist_facts(cfg['qid'])
    labels = {}
    qids = sorted({c['qid'] for c in creates if c.get('qid')})
    for i in range(0, len(qids), 300):
        vals = ' '.join('wd:' + q for q in qids[i:i + 300])
        for b in sparql('SELECT ?item ?l WHERE { VALUES ?item { %s } ?item rdfs:label ?l FILTER(LANG(?l) IN (%s)) }'
                        % (vals, ','.join('"%s"' % l for l in LANGS))):
            labels.setdefault(b['item']['value'].rsplit('/', 1)[1], {})[b['l']['xml:lang']] = b['l']['value']
    out, dropped = [], {}
    COPY = copy_re(cfg['artist'])
    for c in creates:
        why = None
        if c.get('license') not in ('Public domain', 'CC0'): why = 'license'
        elif COPY.search(c['title']) or COPY.search(c['source_key']): why = 'copy'
        elif BANNED.search(c['image_url'] + ' ' + str(c.get('source_url'))): why = 'host'
        if why: dropped[why] = dropped.get(why, 0) + 1; continue
        r = dict(title=c['title'].strip().rstrip('.').strip(), artist=cfg['artist'])
        if c.get('year'): r['year'] = c['year']
        if c.get('medium'): r['medium'] = c['medium']
        if c.get('gallery'): r['gallery'] = c['gallery']
        r.update(image_url=c['image_url'], source_url=c['source_url'], source_key=c['source_key'])
        if c['source_key'].startswith('wikidata:'):
            f = re.sub(r'^.*/Special:FilePath/', '', c['image_url']).split('?')[0]
            r['same_as'] = ['commons:' + urllib.parse.unquote(f).replace('_', ' ')]
        r.update(is_age_restricted=bool(c.get('is_age_restricted')), license=c['license'])
        if c.get('license_basis'): r['license_basis'] = c['license_basis']
        r.update(attribution='Wikimedia Commons', country=cfg.get('country') or facts['nationality'] or '')
        if facts['death_year']: r['artist_death_year'] = facts['death_year']
        lab = labels.get(c.get('qid') or '', {})
        lang = next((l for l in LANGS if lab.get(l, '').lower() == r['title'].lower()), None)
        if lang: r['title_language'] = lang
        if c.get('genre'): r['genre'] = c['genre']
        out.append(r)
    # gallery = where the work is now: its current Wikidata collection (P195, no end date) or location (P276), spelled
    # exactly as Artelier's Gallery.name when Artelier has that museum (the work then links to its page; city from that
    # row), else the holder's English name. Never a private collection, a person, a former owner, a wartime depot or a
    # Wikidata "unknown value". country stays the artist's country, as in every shard.
    plan, unmapped = holder_plan(out, galleries_path)
    held = 0
    for r in out:
        r.pop('gallery', None); r.pop('city', None)
        pk = plan.get(r['source_key'])
        if not pk: continue
        r['gallery'] = pk[0]; held += 1
        if pk[1]: r['city'] = pk[1]
    # unique titles under the importer's key, also against titles Artelier already has for the artist
    taken = {normalize(e.get('title')) for e in existing}
    groups = {}
    for r in out: groups.setdefault(normalize(r['title']), []).append(r)
    for k, rs in groups.items():
        if len(rs) == 1 and k not in taken: continue
        for r in rs:
            if r.get('year') and sum(1 for x in rs if x.get('year') == r['year']) == 1:
                r['title'] = '%s (%s)' % (r['title'], r['year'])
    seen = dict.fromkeys(taken, 1)
    for r in sorted(out, key=lambda r: (r.get('year') or '9999', r['source_key'])):
        k = normalize(r['title']); n = seen.get(k, 0)
        if n:
            base = r['title']
            while normalize(r['title']) in seen:
                n += 1; r['title'] = '%s (%d)' % (base, n)
        seen[normalize(r['title'])] = 1
    out.sort(key=lambda r: (r.get('year') or '9999', r['title']))
    path = os.path.join(ROOT, 'catalog', slug + '-0000.json')
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(dict(shard=slug + '-0000', works=len(out), nudes_flagged=sum(r['is_age_restricted'] for r in out),
                          left_out_existing=len(existing), dropped=dropped, death_year=facts['death_year'],
                          with_gallery=held, unmapped_holders=unmapped), ensure_ascii=False))
    return path


def check(path):
    name = os.path.basename(path)[:-5]
    recs = json.load(open(path)); errs = []
    if not SHARD_RE.match(name): errs.append('shard name must match ^[a-z]+-\\d{4}$')
    if not isinstance(recs, list) or not recs: sys.exit('not a non-empty JSON list')
    keys = [normalize(r.get('title')) for r in recs]
    if len(set(keys)) != len(keys): errs.append('titles not unique: ' + ', '.join(sorted({k for k in keys if keys.count(k) > 1})[:8]))
    if len({r.get('artist') for r in recs}) != 1: errs.append('more than one artist spelling')
    if len({r.get('source_key') for r in recs}) != len(recs): errs.append('duplicate source_key')
    line = datetime.date.today().year - 95
    COPY = copy_re(recs[0].get('artist'))
    for r in recs:
        t = r.get('title') or ''
        for k in ('title', 'artist', 'image_url', 'source_url', 'source_key', 'license', 'attribution'):
            if not r.get(k): errs.append('%s: missing %s' % (t, k))
        if r.get('license') not in ('Public domain', 'CC0'): errs.append('%s: license %s' % (t, r.get('license')))
        if not str(r.get('image_url', '')).startswith('https://commons.wikimedia.org/wiki/Special:FilePath/') or not str(r.get('image_url', '')).endswith('?width=1200'):
            errs.append('%s: image_url' % t)
        if BANNED.search(str(r.get('image_url')) + str(r.get('source_url'))): errs.append('%s: banned host' % t)
        if not re.match(r'^(wikidata:Q\d+|commons:.+)$', str(r.get('source_key'))): errs.append('%s: source_key' % t)
        if COPY.search(t): errs.append('%s: looks like a copy' % t)
        if not isinstance(r.get('is_age_restricted'), bool): errs.append('%s: is_age_restricted' % t)
        if str(r.get('gallery', '')).startswith('http'): errs.append('%s: gallery is a link, not a place' % t)
    ys = [max(map(int, re.findall(r'\b(1\d{3}|20\d\d)\b', str(r.get('year'))) or [0])) for r in recs]
    print(json.dumps(dict(shard=name, artist=recs[0].get('artist'), works=len(recs), nudes=sum(1 for r in recs if r.get('is_age_restricted')),
                          undated=sum(1 for y in ys if not y), dated_us_protected=sum(1 for y in ys if y >= line),
                          license_basis=sorted({r.get('license_basis') or '-' for r in recs})), ensure_ascii=False))
    if errs:
        print('\n'.join(errs[:40])); sys.exit(1)
    print('OK')


def queue(cfg_path):
    cfg = json.load(open(cfg_path)); shard = cfg['slug'] + '-0000'
    spath = os.path.join(ROOT, 'catalog', shard + '.json')
    if not os.path.exists(spath): sys.exit('build the shard first: ' + spath)
    q = json.load(open(QUEUE)) if os.path.exists(QUEUE) else []
    today = datetime.datetime.utcnow().date().isoformat()          # the app's 7-day window counts UTC days
    if any(e.get('shard') == shard or e.get('qid') == cfg['qid'] for e in q):
        sys.exit('%s / %s is already queued: not adding it twice' % (shard, cfg['qid']))
    if sum(1 for e in q if e.get('added') == today) >= PER_DAY:
        sys.exit('%d artists are already queued for %s: another run did today\'s batch' % (PER_DAY, today))
    facts = artist_facts(cfg['qid'])
    work_files = {urllib.parse.unquote(re.sub(r'^.*/Special:FilePath/', '', r['image_url']).split('?')[0]).replace('_', ' ')
                  for r in json.load(open(spath))}
    portrait = None
    info = commons_info(facts['portrait_files']) if facts['portrait_files'] else {}
    for f in facts['portrait_files']:
        lic = (info.get(f) or {}).get('license')
        if lic not in OK or f in work_files:          # CC BY/BY-SA skipped; one of the artist's own works is not a portrait
            continue
        credit = (info[f].get('artist') or info[f].get('credit') or 'Wikimedia Commons')[:200]
        credit = re.sub(r'^(.+?)\s+\1$', r'\1', credit)                 # "Unknown author Unknown author"
        u = urllib.parse.quote(f.replace(' ', '_'))
        portrait = dict(image_url='https://commons.wikimedia.org/wiki/Special:FilePath/%s?width=500' % u,
                        image_source_url='https://commons.wikimedia.org/wiki/File:%s' % u,
                        image_license='cc0' if lic == 'CC0' else 'public_domain', image_credit=credit)
        break
    entry = dict(shard=shard, artist=cfg['artist'], qid=cfg['qid'], added=today,
                 birth_year=facts['birth_year'], death_year=facts['death_year'], nationality=facts['nationality'],
                 art_movement=facts['art_movement'], description=facts['description'], portrait=portrait)
    q.append({k: v for k, v in entry.items() if v is not None})
    json.dump(q, open(QUEUE, 'w'), ensure_ascii=False, indent=1)
    if portrait:
        p = json.load(open(PORTRAITS)) if os.path.exists(PORTRAITS) else {}
        if cfg['qid'] not in p:
            p[cfg['qid']] = portrait
            json.dump(dict(sorted(p.items())), open(PORTRAITS, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(entry, ensure_ascii=False))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'lock': lock()
    elif cmd == 'unlock': unlock()
    elif cmd == 'aliases': aliases(sys.argv[2])
    elif cmd == 'build':
        a = sys.argv[3:]; gal = None
        if '--galleries' in a:
            i = a.index('--galleries'); gal = a[i + 1]; a = a[:i] + a[i + 2:]
        build(sys.argv[2], a[0] if a else None, gal)
    elif cmd == 'holders': holders_cmd(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == 'check': check(sys.argv[2])
    elif cmd == 'queue': queue(sys.argv[2])
    else: sys.exit(open(__file__).read().split('\nimport')[0])
