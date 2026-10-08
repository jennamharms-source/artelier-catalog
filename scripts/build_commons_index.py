# Writes catalog/commons/index.json: one entry per artist file with counts, so clients
# (the Artelier app, or anyone using the static API) can discover what is available.
# Guard: the public catalog may only contain public-domain / CC0 images from Wikimedia Commons
# or museum open-access hosts - never WikiArt, user uploads stored on Artelier (base44), or Harvard Art
# Museums images (their API terms allow non-commercial use only).
import json,glob,os,datetime,sys
BANNED=('wikiart.org','base44','harvard.edu')
ALLOWED_LICENSES={'Public domain','CC0'}
out=[]; bad=[]
for f in sorted(glob.glob('catalog/commons/*.json')):
    if f.endswith('index.json'): continue
    recs=json.load(open(f))
    for r in recs:
        urls=' '.join(str(r.get(k) or '') for k in ('image_url','source_url'))
        if any(b in urls for b in BANNED) or r.get('license') not in ALLOWED_LICENSES:
            bad.append((f,r.get('title'),r.get('image_url'),r.get('license')))
    out.append(dict(file=os.path.basename(f),artist=recs[0]['artist'] if recs else None,works=len(recs),
        sensitive=sum(1 for r in recs if r.get('is_age_restricted')),with_genre=sum(1 for r in recs if r.get('genre'))))
if bad:
    for b in bad[:20]: print('NOT ALLOWED:',*b)
    sys.exit(f'{len(bad)} records with a disallowed source or license - refusing to publish')
json.dump(dict(generated=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),artists=out,total=sum(a['works'] for a in out)),
          open('catalog/commons/index.json','w'),ensure_ascii=False,indent=1)
print(len(out),'artists',sum(a['works'] for a in out),'works')
