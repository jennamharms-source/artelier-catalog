# Converts commons_category.py output (<slug>_cat.json) into a catalog file (list of records).
import json,sys
d=json.load(open(sys.argv[1]))
json.dump(sorted(d['creates'],key=lambda r:(r['year'] or '9999',r['title'])),open(sys.argv[2],'w'),ensure_ascii=False,indent=1)
print('catalog',len(d['creates']))
