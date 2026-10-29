#!/usr/bin/env python3
"""Tüm illerin bilgi dosyalarından uygulamanın okuduğu iller.json kataloğunu üretir."""
import json, os, sys
iller = json.load(open(os.path.join(os.path.dirname(__file__), 'iller.json')))
d = sys.argv[1]
out = []
for il in iller:
    f = os.path.join(d, f"{il['id']}_info.json")
    if not os.path.exists(f):
        continue
    info = json.load(open(f))
    out.append({'id': il['id'], 'name': il['name'], 'plate': il['plate'], 'bbox': info['bbox'], 'files': info['files']})
out.sort(key=lambda x: x['plate'])
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False)
print(len(out), 'il')
