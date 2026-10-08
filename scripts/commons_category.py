# usage: cat_import.py <cfg.json> <db.json>  -> <slug>_cat.json (creates + swaps) for review
import json,urllib.request,urllib.parse,re,sys,unicodedata,html
from urllib.parse import quote
cfg=json.load(open(sys.argv[1])); db=[e for e in json.load(open(sys.argv[2])) if re.search(cfg['artist_re'],e.get('artist') or '',re.I)]
UA={'User-Agent':'ArtelierCatalogBot/1.0 (artelier@artelierapp.co)'}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=120))
def members(cat,depth,seen):
    out=[]; cont={}
    while True:
        r=get('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(dict(action='query',list='categorymembers',cmtitle='Category:'+cat,cmlimit=500,format='json',**cont)))
        for m in r['query']['categorymembers']:
            if m['ns']==6: out.append(m['title'][5:])
            elif m['ns']==14 and depth>0 and m['title'] not in seen and not re.search(cfg.get('skip_subcats','$^'),m['title'],re.I):
                seen.add(m['title']); out+=members(m['title'][9:],depth-1,seen)
        if 'continue' in r: cont=dict(r['continue'])
        else: break
    return out
fs=sorted(set(f for c in cfg['categories'] for f in members(c,cfg.get('depth',1),set())))
meta={}
for i in range(0,len(fs),50):
    cont={}
    while True:
        r=get('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(dict(action='query',titles='|'.join('File:'+f for f in fs[i:i+50]),prop='imageinfo|categories',cllimit=500,iiprop='extmetadata|size|url',iiextmetadatafilter='LicenseShortName|DateTimeOriginal|ObjectName|Artist',format='json',**cont)))
        for p in r['query']['pages'].values():
            m=meta.setdefault(p['title'][5:],dict(cats=[]))
            m['cats']+=[c['title'][9:] for c in p.get('categories',[])]
            ii=(p.get('imageinfo') or [None])[0]
            if ii:
                mm=ii.get('extmetadata',{}); g=lambda k:html.unescape(re.sub('<[^>]+>',' ',mm.get(k,{}).get('value',''))).strip()
                m.update(lic=g('LicenseShortName'),date=g('DateTimeOriginal'),title=g('ObjectName'),artist=g('Artist'),w=ii.get('width',0),h=ii.get('height',0),page=ii.get('descriptionurl'))
        if 'continue' in r: cont=dict(r['continue'])
        else: break
OK={'Public domain':'Public domain','CC0':'CC0','No restrictions':'Public domain','PDM-owner':'Public domain'}
def norm(t):
    t=''.join(ch for ch in unicodedata.normalize('NFKD',t.lower()) if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+',' ',t).strip()
NUDE=('nude','naked','torso','erotic')
rej={}; cands={}
for f,m in meta.items():
    if 'lic' not in m: continue
    why=None
    if not OK.get(m['lic']): why='license '+m['lic']
    elif not re.search(cfg['creator_re'],m['artist'],re.I): why='creator'
    t=re.sub(r'\s+',' ',m['title'].split('\n')[0]).strip()
    t=re.sub(r'\s*(title|label) QS:.*$','',t); t=t.replace('_',' '); t=re.sub(r'^Camera Work:\s*','',t)
    t=re.sub(r'\s+by Alfred Stieglitz.*$','',t,flags=re.I); t=re.sub(r'^\[|\]$','',t).strip().rstrip('.').strip('[] ')
    t=cfg.get('title_fix',{}).get(t,t)
    ys=[int(y) for y in re.findall(r'\b(1[89]\d\d)\b',m['date'])]
    if not why and (not t or re.search(r'MET D[PT]|LCCN|\.jpe?g$|^\d{3}-|RP-F-|^File:',t,re.I) or t==f.rsplit('.',1)[0]): why='title'
    if not why and (not ys or min(ys)>cfg['pd_cutoff']): why='date '+m['date'][:20]
    if why: rej[why.split()[0]]=rej.get(why.split()[0],0)+1; continue
    t=re.sub(r'\s+,',',',t).rstrip(',').strip()
    y=min(ys); tk=norm(t).replace(' ','')
    k=next((kk for kk in cands if kk.split('|')[0]==tk and abs(int(kk.split('|')[1])-y)<=1),tk+'|'+str(y))
    c=dict(title=t,year=str(y),file=f,license=OK[m['lic']],page=m['page'],nude=any(w in (c.lower()+' '+t.lower()) for c in m['cats'] for w in NUDE),px=m['w']*m['h'],cc0=m['lic']=='CC0')
    if k not in cands or (c['cc0'],c['px'])>(cands[k]['cc0'],cands[k]['px']): 
        if k in cands: c['nude']=c['nude'] or cands[k]['nude']
        cands[k]=c
    else: cands[k]['nude']=cands[k]['nude'] or c['nude']
print('files',len(meta),'rejected',rej,'unique works',len(cands))
img=lambda f:'https://commons.wikimedia.org/wiki/Special:FilePath/'+quote(f.replace(' ','_'))+'?width=1200'
dbn={}
for e in db: dbn.setdefault(norm(e['title']).replace(' ',''),[]).append(e)
def dy(e,c):
    m=re.search(r'1[89]\d\d',str(e.get('year') or '')); return abs(int(m.group())-int(c['year'])) if m else 0
creates=[]; swaps=[]; usedid=set()
for k,c in sorted(cands.items(),key=lambda kv:kv[0]):
    hit=sorted([e for e in dbn.get(norm(c['title']).replace(' ',''),[]) if e['id'] not in usedid],key=lambda e:dy(e,c))
    if hit and dy(hit[0],c)<=2 and c['title'] not in cfg.get('no_swap',[]):
        e=hit[0]; usedid.add(e['id']); u=e.get('image_url') or ''
        if 'wikiart.org' in u or 'base44' in u or not u.strip(): swaps.append(dict(id=e['id'],db_title=e['title'],title=c['title'],image_url=img(c['file']),source_url=c['page'],license=c['license'],nude=c['nude']))
        continue
    creates.append(dict(title=c['title'],artist=cfg['artist'],year=c['year'],medium=cfg['medium'],country=cfg['country'],image_url=img(c['file']),source_url=c['page'],attribution='Wikimedia Commons',license=c['license'],is_age_restricted=c['nude'],source_key='commons:'+c['file']))
json.dump(dict(creates=creates,swaps=swaps),open(cfg['slug']+'_cat.json','w'),ensure_ascii=False,indent=0,sort_keys=True)
print('creates',len(creates),'nude',sum(c['is_age_restricted'] for c in creates),'swaps',len(swaps))
for c in creates: print(' ',c['year'],('N ' if c['is_age_restricted'] else '  ')+c['title'][:70])
for s in swaps: print(' SWAP',s['db_title'][:60])
