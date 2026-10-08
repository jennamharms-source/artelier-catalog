# Wikidata / Wikimedia Commons pipeline for one artist (see artists/<slug>.json).
# Only files Commons licenses as Public domain / CC0 are used; CC BY / BY-SA are skipped.
# usage: commons_sync.py catalog <artists/x.json> <out.json>                -> every rights-clean work for the artist
#        commons_sync.py plan    <artists/x.json> <db.json>                 -> match against an Artelier DB snapshot; writes <slug>_create.txt / <slug>_upd.txt
#        commons_sync.py build   <artists/x.json> <create.txt> <upd.txt> <out.json> -> rebuild a plan from live data and print its md5
import json,re,html,urllib.request,urllib.error,urllib.parse,hashlib,sys,time,difflib,os
from urllib.parse import quote,unquote
UA={'User-Agent':'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)','Accept':'application/sparql-results+json'}
def get(u):
    for t in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=180))
        except urllib.error.HTTPError as e: last=e; time.sleep(65 if e.code==429 else 4*(t+1))  # 429: Wikidata rate limit
        except Exception as e: last=e; time.sleep(4*(t+1))
    raise last
def nice(t):
    t=t.strip()
    return t[:1]+t[1:].lower() if t.upper()==t and any(ch.isalpha() for ch in t) else t
mode=sys.argv[1]; cfg=json.load(open(sys.argv[2]))
Q0='?item wdt:P170 wd:%s ; wdt:P18 ?image . MINUS { ?item wdt:P31 wd:Q15727816 }' % cfg['qid']
def sq(sel,body): return get('https://query.wikidata.org/sparql?format=json&query='+urllib.parse.quote('SELECT %s WHERE { %s %s SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de,it,es,nl,pt,sv,da,nb,pl,ru,ca,cs,fi,ja". } }'%(sel,Q0,body)))['results']['bindings']
items={}
for x in sq('?item ?itemLabel ?image ?inception ?typeLabel ?collLabel','OPTIONAL { ?item wdt:P571 ?inception } OPTIONAL { ?item wdt:P31 ?type } OPTIONAL { ?item wdt:P195 ?coll }'):
    qid=x['item']['value'].rsplit('/',1)[1]
    it=items.setdefault(qid,dict(qid=qid,label=x['itemLabel']['value'],images=set(),inception=set(),types=set(),colls=set(),gd=set(),gl=set()))
    it['images'].add(unquote(x['image']['value'].split('/')[-1]))
    if 'inception' in x: it['inception'].add(x['inception']['value'][:4])
    if 'typeLabel' in x: it['types'].add(x['typeLabel']['value'])
    if 'collLabel' in x: it['colls'].add(x['collLabel']['value'])
for x in sq('DISTINCT ?item ?genre ?genreLabel','?item wdt:P136 ?genre .'):
    it=items.get(x['item']['value'].rsplit('/',1)[1])
    if it: it['gd'].add(x['genre']['value'].rsplit('/',1)[1]); it['gl'].add(x['genreLabel']['value'])
for x in sq('DISTINCT ?item ?depicts','?item wdt:P180 ?depicts .'):
    it=items.get(x['item']['value'].rsplit('/',1)[1])
    if it: it['gd'].add(x['depicts']['value'].rsplit('/',1)[1])
for it in items.values():
    for k in ('images','inception','types','colls','gd','gl'): it[k]=sorted(it[k])
items=list(items.values())
wt=get('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(dict(action='parse',page=cfg['gallery'],prop='wikitext',format='json')))['parse']['wikitext']['*']
gal=[]; section=''
for line in wt.split('\n'):
    m=re.match(r'==+\s*(.*?)\s*==+',line)
    if m: section=m.group(1); continue
    if '|' in line and not line.lstrip().startswith(('{{','|','!','[[')) and re.search(r'\.(jpe?g|png|tiff?|gif|webp)\s*\|',line,re.I):
        f,cap=line.split('|',1); f=re.sub(r'^\s*(File|Image):','',f).strip().replace('_',' ')
        gal.append(dict(file=f,cap=cap.strip(),section=section))
files=sorted({f for it in items for f in it['images']}|{g['file'] for g in gal}); meta={}
for i in range(0,len(files),50):
    batch=['File:'+f for f in files[i:i+50]]; cont={}
    while True:
        r=get('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(dict(action='query',titles='|'.join(batch),prop='categories|imageinfo',iiprop='extmetadata|size|url',iiextmetadatafilter='LicenseShortName|DateTimeOriginal',cllimit=500,format='json',**cont)))
        for p in r['query']['pages'].values():
            c=meta.setdefault(p['title'][5:],dict(cats=[],lic=None,w=None,h=None,page=None,date=''))
            c['cats']+=[x['title'][9:] for x in p.get('categories',[])]
            ii=(p.get('imageinfo') or [None])[0]
            if ii:
                mm=ii.get('extmetadata',{})
                c.update(lic=mm.get('LicenseShortName',{}).get('value'),w=ii.get('width'),h=ii.get('height'),page=ii.get('descriptionurl'),date=re.sub('<[^>]+>','',mm.get('DateTimeOriginal',{}).get('value',''))[:40])
        if 'continue' in r: cont=dict(r['continue'])
        else: break
print(cfg['artist'],'wd',len(items),'gallery',len(gal),'files',len(meta),flush=True)
OK={'Public domain':'Public domain','CC0':'CC0','PDM-owner':'Public domain'}
SKIP_TYPES={'artwork series','chapel','group of paintings','cycle of paintings'}
NUDEQ={'Q40446','Q10791','Q114548070','Q9103'}
NUDE_CAT=('nude','naked','odalisque','bathers','erotic')
# whole words only: 'nue' must not fire on 'Emmanuel', 'nu' not on 'reconnu'
NUDE_W=re.compile(r'\b(nudes?|nus?|nues?|naked|odalisques?|bathers?|baigneuses?|nudo|nudi|venus|amor|cupid|masturbat\w*|erotic\w*|akt|nackt\w*|halbakt|dana[eë]|leda|lovers|liebespaar)\b',re.I)
Y0,Y1=cfg['years']
def yrs(s):
    ys=[int(y) for y in re.findall(r'(1[0-9]\d\d)',str(s or '')) if Y0<=int(y)<=Y1]; return (min(ys),max(ys)) if ys else None
def ystr(y): return '' if not y else (str(y[0]) if y[0]==y[1] else f"{y[0]}–{y[1]}")
def medium(types):
    s=' '.join(types)
    for k,v in (('photograph','Photograph'),('watercolor','Watercolor'),('drawing','Drawing'),('etching','Etching'),('engraving','Engraving'),('lithograph','Lithograph'),('print','Print'),('sculpture','Sculpture'),('painting','Painting')):
        if k in s: return v
    return 'Painting'
GENRE_MAP={'portrait':'Portrait','self-portrait':'Self-portrait','landscape painting':'Landscape','landscape art':'Landscape','landscape':'Landscape','still life':'Still life','genre art':'Genre scene','genre painting':'Genre scene','religious art':'Religious','religious painting':'Religious','christian art':'Religious','history painting':'History','mythological painting':'Mythological','nude':'Nude','marine art':'Marine','seascape':'Marine','cityscape':'Cityscape','veduta':'Cityscape','flower painting':'Flowers','animal art':'Animal','allegory':'Allegory','figure painting':'Figure','interior view':'Interior','tronie':'Portrait study','group portrait':'Portrait','equestrian portrait':'Portrait','abstract art':'Abstract','sketch':'Study'}
PRIORITY=['Self-portrait','Portrait','Nude','Religious','Mythological','History','Allegory','Still life','Flowers','Landscape','Marine','Cityscape','Interior','Genre scene','Animal','Figure','Portrait study','Abstract','Study']
def genre_of(labels):
    g=[GENRE_MAP.get(l.lower()) for l in labels if l and not re.fullmatch(r'Q\d+',l)]
    g=[x for x in g if x]
    if not g: return ''
    return sorted(set(g),key=lambda x:PRIORITY.index(x) if x in PRIORITY else 99)[0]
def license_basis(cats,lic,year=None):
    # The specific Commons license category behind "Public domain" (see each file's Licensing box).
    T=' | '.join(cats)
    for pat,name in ((r'Not[- ]PD[- ]US[^|]*','Not-PD-US'),(r'PD[- ]US[- ]no notice','PD-US-no notice'),(r'PD[- ]US[- ]not renewed','PD-US-not renewed'),
                     (r'PD[- ]US[- ]expired','PD-US-expired'),(r'PD[- ]US[- ]unpublished','PD-US-unpublished'),(r'PD[- ]1996','PD-1996'),
                     (r'PD[- ]old[- ]100','PD-old-100'),(r'PD[- ]old[- ]80','PD-old-80'),(r'PD[- ]old[- ]70','PD-old-70'),(r'PD[- ]old','PD-old'),
                     (r'PD[- ]Art','PD-Art'),(r'CC[- ]Zero','CC0'),(r'\bPD[- ]US\b','PD-US')):
        if re.search(pat,T,re.I): return name
    return 'CC0' if lic=='CC0' else ('PD' if lic else None)
def isnude(lab,cats,q=()):
    return bool(NUDEQ&set(q)) or any(w in c.lower() for c in cats for w in NUDE_CAT) or bool(NUDE_W.search(lab or ''))
cands=[]; used=set()
for it in sorted(items,key=lambda i:('painting' not in i['types'],i['qid'])):
    if set(it['types'])&SKIP_TYPES and not set(it['types'])-SKIP_TYPES: continue
    good=[f for f in it['images'] if OK.get(meta.get(f,{}).get('lic'))]
    if not good: continue
    f=max(good,key=lambda f:(meta[f]['w'] or 0)*(meta[f]['h'] or 0))
    if f in used: continue
    if cfg.get('pd_cutoff') and (not it['inception'] or max((int(x[:4]) for x in it['inception'] if x[:4].isdigit()),default=9999)>cfg['pd_cutoff']): continue
    used.add(f); y=yrs(' '.join(it['inception'])); g=(it['colls'] or [''])[0]
    if re.fullmatch(r'Q\d+',it['label'].strip(),re.I):
        # No label in any requested language: fall back to the Commons file name.
        fl=re.sub(r'\.[a-z0-9]+$','',f,flags=re.I); fl=re.sub(re.escape(cfg['artist'].split()[-1])+r'\s*[-–,]?\s*','',fl,flags=re.I)
        fl=re.sub(r'\b(1[0-9]\d\d)\b.*$','',fl).strip(' -–,_')
        it['label']=fl or it['label']
    if re.fullmatch(r'Q\d+|\s*\d{4}\s*|untitled|sans titre',it['label'].strip(),re.I) or it['qid'] in cfg.get('exclude',[]): continue
    cands.append(dict(qid=it['qid'],title=it['label'],yr=y,year=ystr(y),file=f,license=OK[meta[f]['lic']],medium=medium(it['types']),
        gallery='' if g.startswith('http') else g,nude=isnude(it['label'],meta[f]['cats'],it['gd']),page=meta[f]['page'],genre=genre_of(it['gl']),lb=license_basis(meta[f]['cats'],meta[f]['lic'])))
wd_files={f for it in items for f in it['images']}
def unlink(s): return re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]',r'\1',re.sub(r'\{\{c\|([^}]*)\}\}',r'\1',s))
for g in gal:
    f=g['file']
    if f in wd_files or f in used or re.search(r'photo|portrait of|signature|grave|tomb|house of|museum',g['section'],re.I): continue
    if not OK.get(meta.get(f,{}).get('lic')): continue
    if '{{' in g['cap']: continue
    cap=unlink(g['cap']); it=re.findall(r"''+(.+?)''+",cap)
    title=re.sub(r"''+","",it[0]).strip() if it else re.split(r',\s*(?:c\.\s*)?1[0-9]\d\d',cap)[0].strip()
    if not title or len(title)>150: continue
    y=yrs(cap) or yrs(meta[f]['date'])
    if cfg.get('pd_cutoff') and (not y or y[1]>cfg['pd_cutoff'] or re.search(r'19[3-9]\d',cap+' '+meta[f]['date'])): continue
    used.add(f)
    cands.append(dict(qid='',title=title,yr=y,year=ystr(y),file=f,license=OK[meta[f]['lic']],medium='Painting',gallery='',nude=isnude(title,meta[f]['cats']),page=meta[f]['page'],genre='',lb=license_basis(meta[f]['cats'],meta[f]['lic'])))
key=lambda c:(c['qid'] if c['qid'] else 'G:'+c['file'])
ck={key(c):c for c in cands}
img=lambda f:'https://commons.wikimedia.org/wiki/Special:FilePath/'+quote(f.replace(' ','_'))+'?width=1200'
def rec(c): return dict(title=nice(c['title']),artist=cfg['artist'],year=c['year'],medium=c['medium'],gallery=c['gallery'],country=cfg['country'],image_url=img(c['file']),
        source_url=c['page'],attribution='Wikimedia Commons',license=c['license'],is_age_restricted=c['nude'],source_key=('wikidata:'+c['qid']) if c['qid'] else 'commons:'+c['file'],**({'genre':c['genre']} if c.get('genre') else {}),**({'license_basis':c['lb']} if c.get('lb') else {}))
def sigs(creates,updates):
    s=sorted(f"{c['title']}|{c['year']}|{c['image_url']}|{c['source_url']}|{int(c['is_age_restricted'])}|{c.get('genre','')}" for c in creates)+sorted(f"{u['id']}|{u.get('swap',{}).get('image_url','')}|{u.get('is_age_restricted','')}|{u.get('title','')}|{u.get('genre','')}" for u in updates)
    return hashlib.md5('\n'.join(s).encode()).hexdigest()
print('cands',len(cands),flush=True)
# copies by followers, workshops and imitators are not the artist's work: the label or the Commons file name says so
_sur=re.escape(cfg['artist'].split()[-1])
COPY_RE=re.compile(r'kopie nach|copy after '+_sur+r'|copy of|\bafter '+_sur+r'|nach '+_sur[:5]+r'|workshop of|school of '+_sur+r'|circle of|follower of|imitator of|werkstatt|schule des|nachfolger',re.I)
FILE_COPY_RE=re.compile(r'^after '+_sur+r'\b|\((after|studio of|school of|follower of|imitator of|circle of|workshop of|manner of|style of)\)|\b(nachahmer|nachfolger|werkstatt|umkreis)\b',re.I)
def is_copy(c): return bool(COPY_RE.search(c['title']) or FILE_COPY_RE.search(c['file']) or FILE_COPY_RE.search(c['title']))
if mode=='catalog':
    out=[dict(rec(c),qid=c['qid'],collection=c['gallery']) for c in cands if not is_copy(c)]
    os.makedirs(os.path.dirname(sys.argv[3]) or '.',exist_ok=True)
    json.dump(sorted(out,key=lambda r:(r['year'] or '9999',r['title'])),open(sys.argv[3],'w'),ensure_ascii=False,indent=1); print('catalog',len(out)); sys.exit()
if mode=='build':
    creates=[rec(ck[k]) for k in open(sys.argv[3]).read().strip('\n').split('\n') if k]
    updates=[]
    for line in open(sys.argv[4]).read().strip('\n').split('\n'):
        if not line: continue
        aid,k,n,t=(line.split('\t')+[''])[:4]; u={'id':aid}; c=ck.get(k)
        fl=n if cfg.get('v2') else ('s' if k!='-' else '')+('n' if n=='n' else '')
        if 's' in fl: u['swap']=dict(image_url=img(c['file']),source_url=c['page'],attribution='Wikimedia Commons',license=c['license'])
        if 'n' in fl: u['is_age_restricted']=True
        if 'g' in fl and c and c.get('genre'): u['genre']=c['genre']
        if 't' in fl and c: u['title']=nice(c['title'])
        if t: u['title']=t
        updates.append(u)
    print('creates',len(creates),'updates',len(updates),'md5',sigs(creates,updates))
    json.dump(dict(creates=creates,updates=updates),open(sys.argv[5],'w'),ensure_ascii=False); sys.exit()
# ---- plan mode (local, needs DB snapshot) ----
db=[e for e in json.load(open(sys.argv[3])) if re.search(cfg['artist_re'],e.get('artist') or '',re.I)]
STOP=r'\b(the|le|la|les|l|a|an|de|du|des|d|il|lo|di|del|della|with|avec|au|aux|à|in|of|and|et|e|at|on)\b'
def norm(t):
    t=html.unescape(str(t or '')).lower().replace('&',' and ')
    t=re.sub(r"[^\w\s]",' ',t); t=re.sub(STOP,' ',t); return re.sub(r'\s+',' ',t).strip()
def core(t): return re.sub(r'(\s+(\d+|[ivx]+))+$','',norm(t)).strip()
def variants(t):
    v={str(t)}; m=re.match(r'(.*?)\s*\((.*)\)\s*$',str(t))
    if m: v|={m.group(1),m.group(2)}
    return {norm(x) for x in v if norm(x)}|{core(x) for x in v if core(x)}
def ovl(a,b,t=1): return bool(a and b and a[0]-t<=b[1] and b[0]-t<=a[1])
LEX={'eichhörnchen':'squirrel','eichhornchen':'squirrel','eichhörnchens':'squirrel','landschaft':'landscape','haus':'house','hund':'dog','hunde':'dogs','rind':'cattle','rinder':'cattle','füchse':'fox','fuchse':'fox','fuchs':'fox','foxes':'fox','fohlen':'foal','foals':'foal','blaue':'blue','blauer':'blue','blaues':'blue','blau':'blue','pferd':'horse','pferde':'horse','pferdchen':'little horse','katzen':'cat','katze':'cat','kätzchen':'kitten','katzchen':'kitten','rote':'red','roter':'red','rotes':'red','rot':'red','gelbe':'yellow','gelb':'yellow','gelber':'yellow','kuh':'cow','kühe':'cow','kuhe':'cow','reh':'deer','rehe':'deer','tiere':'animal','tier':'animal','schafe':'sheep','schaf':'sheep','stier':'bull','affe':'monkey','grüne':'green','grune':'green','grünes':'green','grun':'green','grün':'green','weiße':'white','weisse':'white','weiß':'white','schwarze':'black','zwei':'two','drei':'three','vier':'four','liegender':'lying','liegende':'lying','liegendes':'lying','sitzender':'seated','springender':'leaping','badende':'bathing','frauen':'women','mädchen':'girl','tiger':'tiger','elefant':'elephant','turm':'tower','bild':'picture','wölfe':'wolves','wolfe':'wolves','weidende':'grazing','stallungen':'stables','kampfende':'fighting','kämpfende':'fighting','formen':'forms','schlafende':'sleeping','träumendes':'dreaming','traumendes':'dreaming','pferdes':'horse','hirsch':'deer','hirsche':'deer','wald':'forest','im':'in','st':'saint','ste':'saint','san':'saint','santa':'saint','santo':'saint','sankt':'saint','sainte':'saint','madonna':'virgin','madone':'virgin','younger':'less','elder':'great','greater':'great','evangelist':'evangelist','apostle':'apostle','sv':'saint','railroad':'railway','cutting':'cut','tranchée':'cut','tranchee':'cut','alley':'avenue','afternoon':'after noon','midi':'noon','blooming':'blossom','bloom':'blossom','fleur':'flower','fleuri':'blossom','marronniers':'chestnut trees','marronnier':'chestnut tree','buveur':'drinker','delft':'delft','petit':'little','petite':'little','petits':'little','small':'little','jeu':'game','étude':'study','etude':'study','études':'study','esquisse':'sketch','tête':'head','tete':'head','fillette':'little girl','fillettes':'little girls','mère':'mother','mere':'mother','fils':'son','soeur':'sister','sœur':'sister','frère':'brother','frere':'brother','épouse':'wife','epouse':'wife','ami':'friend','amie':'friend','amis':'friends','deux':'two','trois':'three','quatre':'four','cinq':'five','grand':'large','grande':'large','big':'large','fruits':'fruit','pommes':'apples','pomme':'apple','poires':'pears','raisins':'grapes','cerises':'cherries','oignons':'onions','verger':'orchard','arbres':'trees','arbre':'tree','bois':'wood','woods':'wood','forêt':'forest','foret':'forest','colline':'hill','collines':'hills','montagne':'mountain','rue':'street','maisons':'houses','bords':'banks','baie':'bay','port':'harbor','harbour':'harbor','voile':'sail','voiles':'sails','laveuse':'washerwoman','laveuses':'washerwomen','couseuse':'seamstress','lisant':'reading','cousant':'sewing','jouant':'playing','buste':'bust','profil':'profile','nu':'nude','nue':'nude','nues':'nudes','dos':'back','rouge':'red','bleu':'blue','bleue':'blue','blanc':'white','blanche':'white','vert':'green','verte':'green','jaune':'yellow','noire':'black','cheveux':'hair','ruban':'ribbon','collier':'necklace','fichu':'scarf','plume':'feather','panier':'basket','guitare':'guitar','mandoline':'mandolin','joueur':'player','joueurs':'players','cartes':'cards','fumeur':'smoker','baigneurs':'bathers','pendu':'hanged','crâne':'skull','crane':'skull','crânes':'skulls','cranes':'skulls','rideau':'curtain','cruche':'jug','pichet':'jug','pitcher':'jug','bouteille':'bottle','assiette':'plate','nappe':'tablecloth','tapis':'carpet','toilette':'toilet','theatre':'theater','théâtre':'theater','autoportrait':'self portrait','artiste':'artist','peintre':'painter','vieux':'old','vieille':'old','enfants':'children','berger':'shepherd','bergère':'shepherdess','bergere':'shepherdess','vache':'cow','vaches':'cows','cheval':'horse','chevaux':'horses','moutons':'sheep','oiseaux':'birds','oiseau':'bird','rivage':'shore','vagues':'waves','vague':'wave','bouquet':'bouquet','corbeille':'basket','jatte':'bowl','compotier':'fruit bowl','sucrier':'sugar bowl','pot':'pot','gingembre':'ginger','bassin':'basin','ferme':'farm','chaumière':'cottage','chaumiere':'cottage','sentier':'path','allée':'avenue','allee':'avenue','jas':'jas','buffon':'buffon','lac':'lake','madone':'madonna','vierge':'virgin','christ':'christ','saint':'saint','sainte':'saint','apôtre':'apostle','philosophe':'philosopher','vieillard':'old man','juive':'jewish','fiancée':'bride','fiancee':'bride','juif':'jewish','bethsabée':'bathsheba','bethsabee':'bathsheba','bathsheba':'bathsheba','leçon':'lesson','lecon':'lesson','anatomie':'anatomy','ronde':'watch','syndics':'syndics','drapiers':'drapers','flora':'flora','titus':'titus','descente':'descent','croix':'cross','résurrection':'resurrection','ascension':'ascension','prophète':'prophet','prophete':'prophet','festin':'feast','balthazar':'belshazzar','belshazzar':'belshazzar','paysage':'landscape','paysages':'landscapes','tambourin':'tambourine','danseuse':'dancer','baigneuse':'bather','baigneuses':'bathers','bain':'bath','avant':'before','après':'after','apres':'after','seins':'breasts','nus':'bare','enfant':'child','enfants':'children','lilas':'lilacs','chapeau':'hat','paille':'straw','robe':'dress','parapluies':'umbrellas','canotiers':'boating','danse':'dance','moulin':'mill','loge':'box','pianiste':'pianist','jeunes':'young','filles':'girls','allongée':'reclining','allongee':'reclining','couché':'reclining','couche':'reclining','assise':'seated','assis':'seated','tenant':'holding','glaïeuls':'gladioli','glaieuls':'gladioli','liseuse':'reader','capuchon':'hood','pivoines':'peonies','pivoine':'peony','sécateur':'secateurs','secateur':'secateurs','tige':'branch','branche':'branch','lecture':'reading','partie':'game','chien':'dog','chat':'cat','buveur':'drinker','absinthe':'absinthe','chanteur':'singer','chanteuse':'singer','jeune':'young','fille':'girl','homme':'man','barbe':'beard','blonde':'blond','balcon':'balcony','déjeuner':'luncheon','dejeuner':'luncheon','herbe':'grass','bar':'bar','courses':'races','combat':'battle','exécution':'execution','execution':'execution','fifre':'fifer','marée':'tide','maree':'tide','basse':'low','voiliers':'sailboats','asperge':'asparagus','botte':'bunch','citron':'lemon','pêches':'peaches','peches':'peaches','prunes':'plums','chapeau':'hat','noir':'black','gants':'gloves','éventail':'fan','eventail':'fan','mit':'with','haupt':'head','kopf':'head','bildnis':'portrait','porträt':'portrait','portrat':'portrait','damenbildnis':'portrait lady','dame':'lady','frau':'woman','frauen':'women','mädchen':'girl','madchen':'girl','garten':'garden','bauerngarten':'farm garden','wald':'forest','buchenwald':'beech forest','birkenwald':'birch forest','tannenwald':'fir forest','kirche':'church','schloss':'castle','see':'lake','wasserschlangen':'water serpents','freundinnen':'friends','erwartung':'expectation','kuss':'kiss','liebe':'love','tod':'death','leben':'life','jungfrau':'maiden','hoffnung':'hope','musik':'music','medizin':'medicine','philosophie':'philosophy','jurisprudenz':'jurisprudence','goldfische':'goldfish','sonnenblumen':'sunflowers','sonnenblume':'sunflower','apfelbaum':'apple tree','bäume':'trees','baume':'trees','rosen':'roses','insel':'island','hühnern':'chickens','huhnern':'chickens','studie':'study','alter':'old','mann':'man','allegorie':'allegory','skulptur':'sculpture','bildnis':'portrait','akt':'nude','liegende':'reclining','sitzende':'seated','stehende':'standing','nymphéas':'water lilies','nympheas':'water lilies','pont':'bridge','japonais':'japanese','bras':'arm','près':'near','pres':'near','neige':'snow','effet':'effect','soleil':'sun','couchant':'sunset','levant':'rising','église':'church','eglise':'church','gare':'station','falaise':'cliff','falaises':'cliffs','rochers':'rocks','rocher':'rock','barque':'boat','barques':'boats','bateau':'boat','bateaux':'boats','pêche':'fishing','peche':'fishing','matin':'morning','brouillard':'fog','glaçons':'ice','glacons':'ice','débâcle':'ice breakup','peupliers':'poplars','meules':'haystacks','meule':'haystack','cathédrale':'cathedral','cathedrale':'cathedral','jardin':'garden','maison':'house','femme':'woman','femmes':'women','ombrelle':'parasol','mer':'sea','plage':'beach','prairie':'meadow','champ':'field','coquelicots':'poppies','route':'road','chemin':'path','vue':'view','printemps':'spring','été':'summer','ete':'summer','hiver':'winter','automne':'autumn','nuit':'night','temps':'weather','gris':'grey','gelée':'frost','gelee':'frost','fleurs':'flowers','pommiers':'apple trees','saules':'willows','saule':'willow','pleureur':'weeping','reflets':'reflections','nature':'still','morte':'life','portrait':'portrait','enfant':'child','dame':'lady','canal':'canal','palais':'palace','tamise':'thames','parlement':'parliament','londres':'london','venise':'venice','étang':'pond','etang':'pond','île':'island','ile':'island','vallée':'valley','vallee':'valley','rivière':'river','riviere':'river','côte':'coast','cote':'coast','ciel':'sky','nuages':'clouds','bord':'bank','eau':'water'}
SW=set('the a an of and at in on with by from near to le la les l de du des d un une et au aux à en sur par pour il lo di del della e'.split())
import unicodedata
def toks(t):
    t=html.unescape(str(t or '')).lower(); t=re.sub(r"[^\w\s]",' ',t)
    t=''.join(ch for ch in unicodedata.normalize('NFKD',t) if not unicodedata.combining(ch))
    out=[]
    for w in t.split():
        w=LEX.get(w,w)
        for x in w.split():
            if x not in SW and not x.isdigit():
                x=re.sub(r'(ing|ed)$','',x) if len(x)>5 else x
                out.append(x[:-1] if x.endswith('s') and len(x)>3 else x)
    return set(out)
_ROM={'I':1,'V':5,'X':10}
def _nums(t):
    out=set()
    for m in re.findall(r'\b(?:[IVX]{1,4}|\d{1,3})\b',str(t or '')):
        if m.isdigit(): out.add(int(m)); continue
        v=0; prev=0
        for ch in reversed(m):
            x=_ROM[ch]; v=v-x if x<prev else v+x; prev=max(prev,x)
        out.add(v)
    return out
def jac(a,b): return len(a&b)/len(a|b) if a and b else 0
GT={'portrait','still','life','painting','picture','reverend','madame','monsieur','mme','mlle','mademoiselle','mr','mrs','m'}
def cont(a,b):
    a2=a-GT; b2=b-GT
    return len(a2)>=2 and len(b2)>=2 and (a2<=b2 or b2<=a2)
for c in cands: c['v']=variants(c['title'])
for e in db: e['v']=variants(e['title']); e['yr']=yrs(e.get('year')); e['t']=toks(e['title'])
for c in cands: c['t']=toks(c['title'])
def host(u):
    u=u or ''
    return 'wikiart' if 'wikiart.org' in u else 'artelier' if 'base44' in u else 'harvard' if 'harvard.edu' in u else 'none' if not u.strip() else 'keep'
match={}; used_c=set()
for e in db:
    if e['id'] in cfg.get('force_match',{}):
        k=cfg['force_match'][e['id']]; match[e['id']]=k; used_c.add(k); continue
    hits=[c for c in cands if c['v']&e['v'] and ovl(c['yr'],e['yr'],cfg.get('ytol',1))]
    if not hits:
        hits=[c for c in cands if ovl(c['yr'],e['yr'],cfg.get('ytol',1)) and max(difflib.SequenceMatcher(None,a,b).ratio() for a in e['v'] for b in c['v'])>=0.9]
    hits=[h for h in hits if key(h) not in used_c]
    if len(hits)==1: match[e['id']]=key(hits[0]); used_c.add(key(hits[0]))
if cfg.get('fuzzy'):
    def fs(c,e):
        if not (c['yr'] and e['yr'] and ovl(c['yr'],e['yr'],cfg.get('ytol',1))): return 0
        j=jac(c['t'],e['t']); r=max(difflib.SequenceMatcher(None,a,b).ratio() for a in e['v'] for b in c['v'])
        return max(j if j>=cfg.get('fjac',0.6) else 0, 0.55 if cont(c['t'],e['t']) else 0, r if r>=0.85 else 0)
    def best(sc):
        sc=sorted([x for x in sc if x[0]>0],key=lambda x:-x[0])
        return sc[0][1] if sc and (len(sc)==1 or sc[0][0]>=sc[1][0]+0.1) else None
    fzl=[]
    for e in db:
        if e['id'] in match or e['id'] in cfg.get('no_fuzzy',[]): continue
        c=best([(fs(c,e),c) for c in cands if key(c) not in used_c])
        if not c: continue
        e2=best([(fs(c,x),x) for x in db if x['id'] not in match])
        if e2 is e:
            match[e['id']]=key(c); used_c.add(key(c)); fzl.append(f"{e['title']} ({e.get('year')})  <=>  {c['title']} ({c['year']})")
    open(cfg['slug']+'_fuzzy.txt','w',encoding='utf-8').write('\n'.join(fzl)+'\n'); print('fuzzy matches',len(fzl),flush=True)
present=set(match.values())
for c in cands:
    if key(c) in present: continue
    for e in db:
        if cfg.get('exact_any_year') and (c['v']&e['v']): present.add(key(c)); break
        _na=_nums(c['title']); _nb=_nums(e.get('title'))
        if _na!=_nb and _na and _nb: continue
        if _na and not _nb and not (c['v']&e['v']): continue
        if (ovl(c['yr'],e['yr'],cfg.get('stol',1)) or not e['yr'] or not c['yr']) and (c['v']&e['v'] or jac(c['t'],e['t'])>=cfg.get('jac',0.6) or (cfg.get('jac',0.6)<=1 and cont(c['t'],e['t'])) or max(difflib.SequenceMatcher(None,a,b).ratio() for a in e['v'] for b in c['v'])>=0.85):
            present.add(key(c)); break
    if not c['yr']:  # undated: only add if no record anywhere shares its title
        if any(c['v']&e['v'] for e in db): present.add(key(c))
GENERIC=re.compile(r'^(paysage|landscape|portrait|nature morte|still life|fleurs|flowers|étude|etude|study|esquisse|sketch|femme|woman|tête|tete|head|baigneuse|bather|nu|nude)\b',re.I)
def vague(c): return c['title'].upper()==c['title'] or bool(GENERIC.match(c['title']) and len(c['title'].split())<=4)
creates=[] if cfg.get('no_creates') else [c for c in cands if key(c) not in present and c['medium'] not in cfg.get('skip_media',[]) and not (cfg.get('quality') and vague(c) and not c['gallery'])]
if cfg.get('no_gallery'): creates=[c for c in creates if c['qid']]
creates=[c for c in creates if not is_copy(c)]
def _dup(a,b):
    if not ((a['yr'] and b['yr'] and ovl(a['yr'],b['yr'],cfg.get('ytol',1))) or (not a['yr'] and not b['yr'])): return False
    na=_nums(a['title']); nb=_nums(b['title'])
    if na!=nb: return False
    if a['gallery'] and b['gallery'] and a['gallery']!=b['gallery']: return False
    if ' '.join(a['title'].lower().split())==' '.join(b['title'].lower().split()): return not (a['gallery'] and b['gallery']) and bool(a['yr'] and b['yr'])
    st=re.compile(r'\b(study|studie|sketch|esquisse|[eé]tude|skizze|detail)\b',re.I)
    if bool(st.search(a['title']))!=bool(st.search(b['title'])): return False
    return jac(a['t'],b['t'])>=0.75
kept=[]; idup=[]
for c in ([] if cfg.get('no_idup') else sorted(creates,key=lambda c:(not c['gallery'],c['qid']=='',c['qid']))):
    d=next((k for k in kept if _dup(c,k)),None)
    if d: idup.append(f"{c['title']} ({c['year']})  ==  {d['title']} ({d['year']})")
    else: kept.append(c)
creates=creates if cfg.get('no_idup') else [c for c in creates if c in kept]
open(cfg['slug']+'_idup.txt','w',encoding='utf-8').write('\n'.join(idup)+'\n'); print('internal dups dropped',len(idup),flush=True)
ul=[]; st={'swap':0,'nude':0}
for e in db:
    k=match.get(e['id']); 
    if not k: continue
    c=ck[k]; sw=host(e.get('image_url')) in ('wikiart','artelier','harvard','none'); nd=c['nude'] and not e.get('is_age_restricted')
    t=cfg.get('title_fix',{}).get(e['id'],'')
    if cfg.get('v2'):
        gf=bool(c.get('genre')) and not e.get('genre')
        tf=cfg.get('copy_title') and not t and c['title'].strip()!=str(e.get('title') or '').strip()
        fl=('s' if sw else '')+('n' if nd else '')+('g' if gf else '')+('t' if tf else '')
        if fl or t: ul.append(f"{e['id']}\t{k}\t{fl or '-'}"+(f"\t{t}" if t else '')); st['swap']+=sw; st['nude']+=nd
    elif sw or nd or t: ul.append(f"{e['id']}\t{k if sw else '-'}\t{'n' if nd else '-'}"+(f"\t{t}" if t else '')); st['swap']+=sw; st['nude']+=nd
slug=cfg['slug']
open(slug+'_create.txt','w').write('\n'.join(key(c) for c in creates)+'\n'); open(slug+'_upd.txt','w').write('\n'.join(ul)+'\n')
from collections import Counter
print('db',len(db),Counter(host(e.get('image_url')) for e in db),'| matched',len(match),'| swaps',st['swap'],'nude flags',st['nude'],'| creates',len(creates),'(nude',sum(c['nude'] for c in creates),')')
cr=[rec(c) for c in creates]; up=[]
for line in ul:
    aid,k,n,t=(line.split('\t')+[''])[:4]; u={'id':aid}; c=ck.get(k)
    fl=n if cfg.get('v2') else ('s' if k!='-' else '')+('n' if n=='n' else '')
    if 's' in fl: u['swap']=dict(image_url=img(c['file']),source_url=c['page'],attribution='Wikimedia Commons',license=c['license'])
    if 'n' in fl: u['is_age_restricted']=True
    if 'g' in fl and c and c.get('genre'): u['genre']=c['genre']
    if 't' in fl and c: u['title']=nice(c['title'])
    if t: u['title']=t
    up.append(u)
print('md5',sigs(cr,up))
json.dump(dict(match={k:ck[v]['title']+' | '+ck[v]['year'] for k,v in match.items()},dbt={e['id']:e['title']+' | '+str(e.get('year')) for e in db}),open(slug+'_review.json','w'),ensure_ascii=False)
