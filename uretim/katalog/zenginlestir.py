"""Türkiye faunası kataloğu: Vikiveri, Vikipedi ve Wikimedia Commons'tan zenginleştirme.

Girdi: turler.json  [[gbif_anahtarı, bilimsel_ad, grup], ...]
Çıktı: out/wiki.json  {anahtar: {q, tr, en, trn, iucn, end, inat, trw, enw, trx, enx, img}}
       out/img/<anahtar>.webp  (Commons fotoğrafları, küçültülmüş)
       out/credits.json  {anahtar: {a: yazar, l: lisans, f: dosya}}
"""
import concurrent.futures as cf, io, json, os, re, time, urllib.parse, urllib.request
from PIL import Image

UA = 'KampDefteriKatalog/1.9 (https://github.com/MuzafferAbdullahOrtakaya/kamp-defteri-haritalar; offline camping guide for Turkey)'
TURLER = json.load(open('turler.json'))
GRP = {str(k): g for k, _, g in TURLER}
os.makedirs('out/img', exist_ok=True)
IUCN = {'Q211005': 'LC', 'Q719675': 'NT', 'Q278113': 'VU', 'Q11394': 'EN', 'Q219127': 'CR', 'Q239509': 'EW', 'Q237350': 'EX', 'Q3245245': 'DD'}
OMURGALI = {'memeli', 'kus', 'surungen', 'amfibi', 'balik'}

def get(url, data=None, tries=8, raw=False):
    for t in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept': 'application/json' if not raw else '*/*'})
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
                return b if raw else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (404, 400): return None
            ra = e.headers.get('Retry-After') if e.headers else None
            time.sleep(int(ra) if ra and ra.isdigit() else min(90, 3 * 2 ** t))
        except Exception:
            time.sleep(min(60, 3 * 2 ** t))
    return None

out = {}
# 1) GBIF anahtarından Vikiveri ögesine
keys = [str(k) for k, _, _ in TURLER]
q2k = {}
seen = set()
def sparql(chunk):
    vals = ' '.join(f'"{x}"' for x in chunk)
    q = f'SELECT ?gbif ?item WHERE {{ VALUES ?gbif {{ {vals} }} ?item wdt:P846 ?gbif . }}'
    d = get('https://query.wikidata.org/sparql', data=urllib.parse.urlencode({'query': q, 'format': 'json'}).encode())
    return [(b['gbif']['value'], b['item']['value'].rsplit('/', 1)[1]) for b in (d or {}).get('results', {}).get('bindings', [])]
with cf.ThreadPoolExecutor(3) as ex:
    for res in ex.map(sparql, [keys[i:i + 400] for i in range(0, len(keys), 400)]):
        for g, q in res:
            if g not in seen:
                seen.add(g)
                q2k[q] = g
print('vikiveri ögesi', len(q2k), flush=True)

# 2) Ögelerin etiketleri, iddiaları, Vikipedi bağlantıları
def entities(qs):
    d = get('https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode({
        'action': 'wbgetentities', 'ids': '|'.join(qs), 'props': 'labels|claims|sitelinks', 'languages': 'tr|en',
        'sitefilter': 'trwiki|enwiki', 'format': 'json', 'maxlag': 5}))
    return (d or {}).get('entities', {})
qs = list(q2k)
def all_entities():
    got = {}
    todo = qs
    for rnd in range(4):
        batches = [todo[i:i + 50] for i in range(0, len(todo), 50)]
        with cf.ThreadPoolExecutor(2 if rnd == 0 else 1) as ex:
            for ents in ex.map(entities, batches):
                got.update(ents)
        todo = [q for q in qs if q not in got]
        print('vikiveri tur', rnd, 'eksik', len(todo), flush=True)
        if not todo: break
        time.sleep(30)
    return got
for ents in [all_entities()]:
        for q, e in ents.items():
            g = q2k.get(q)
            if not g or 'missing' in e: continue
            o = out.setdefault(g, {'q': q})
            lab = e.get('labels', {})
            if 'tr' in lab: o['tr'] = lab['tr']['value']
            if 'en' in lab: o['en'] = lab['en']['value']
            cl = e.get('claims', {})
            def vals(p):
                r = []
                for c in cl.get(p, []):
                    dv = c.get('mainsnak', {}).get('datavalue', {}).get('value')
                    if dv is not None: r.append(dv)
                return r
            img = vals('P18')
            if img: o['imgf'] = img[0]
            iu = vals('P141')
            if iu: o['iucn'] = IUCN.get(iu[0].get('id'))
            inat = vals('P3151')
            if inat: o['inat'] = inat[0]
            if any(v.get('id') == 'Q43' for v in vals('P183')): o['end'] = 1
            trn = [v['text'] for v in vals('P1843') if v.get('language') == 'tr']
            if trn: o['trn'] = trn[:4]
            sl = e.get('sitelinks', {})
            if 'trwiki' in sl: o['trw'] = sl['trwiki']['title']
            if 'enwiki' in sl: o['enw'] = sl['enwiki']['title']
print('etiket', len(out), 'tr ad', sum(1 for o in out.values() if 'tr' in o or 'trn' in o), 'foto', sum(1 for o in out.values() if 'imgf' in o),
      'trwiki', sum(1 for o in out.values() if 'trw' in o), 'enwiki', sum(1 for o in out.values() if 'enw' in o), flush=True)

# 3) Vikipedi giriş paragrafları
def kisa(t, n=900):
    t = re.sub(r'\s+', ' ', t or '').strip()
    if len(t) <= n: return t
    cut = t[:n]
    i = max(cut.rfind('. '), cut.rfind('. '))
    return cut[:i + 1] if i > 200 else cut.rsplit(' ', 1)[0] + '…'
def extracts(lang, titles):
    d = get(f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({
        'action': 'query', 'prop': 'extracts', 'exintro': 1, 'explaintext': 1, 'exlimit': 20, 'redirects': 1,
        'titles': '|'.join(titles), 'format': 'json', 'formatversion': 2, 'maxlag': 5}))
    res = {}
    if not d: return res
    norm = {n['from']: n['to'] for n in d.get('query', {}).get('normalized', [])}
    redir = {n['from']: n['to'] for n in d.get('query', {}).get('redirects', [])}
    pages = {p.get('title'): p.get('extract', '') for p in d.get('query', {}).get('pages', [])}
    for t in titles:
        tt = norm.get(t, t); tt = redir.get(tt, tt)
        if pages.get(tt): res[t] = kisa(pages[tt])
    return res
for lang, fld, ofld in (('tr', 'trw', 'trx'), ('en', 'enw', 'enx')):
    t2g = {o[fld]: g for g, o in out.items() if fld in o}
    titles = list(t2g)
    with cf.ThreadPoolExecutor(3) as ex:
        for res in ex.map(lambda c: extracts(lang, c), [titles[i:i + 20] for i in range(0, len(titles), 20)]):
            for t, x in res.items():
                out[t2g[t]][ofld] = x
    print(lang, 'açıklama', sum(1 for o in out.values() if ofld in o), flush=True)

# 4) Commons fotoğrafları: küçük boy adresi, yazar ve lisans
def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()
def imginfo(files):
    d = get('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({
        'action': 'query', 'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'iiurlwidth': 480,
        'titles': '|'.join('File:' + f for f in files), 'format': 'json', 'formatversion': 2, 'maxlag': 5}))
    res = {}
    if not d: return res
    norm = {n['to']: n['from'] for n in d.get('query', {}).get('normalized', [])}
    for p in d.get('query', {}).get('pages', []):
        ii = (p.get('imageinfo') or [None])[0]
        if not ii: continue
        md = ii.get('extmetadata', {})
        title = norm.get(p['title'], p['title'])
        res[title.split(':', 1)[1]] = {'u': ii.get('thumburl') or ii.get('url'), 'a': strip_html(md.get('Artist', {}).get('value'))[:120],
                                       'l': strip_html(md.get('LicenseShortName', {}).get('value'))}
    return res
f2g = {}
for g, o in out.items():
    if 'imgf' in o: f2g.setdefault(o['imgf'], []).append(g)
files = list(f2g)
info = {}
with cf.ThreadPoolExecutor(3) as ex:
    for res in ex.map(imginfo, [files[i:i + 40] for i in range(0, len(files), 40)]):
        info.update(res)
print('foto bilgisi', len(info), flush=True)

# 5) İndir, küçült, kaydet
credits = {}
def indir(f):
    i = info.get(f)
    if not i or not i.get('u'): return f, None
    b = get(i['u'], raw=True, tries=5)
    return f, b
done = 0
with cf.ThreadPoolExecutor(6) as ex:
    for f, b in ex.map(indir, files):
        if not b: continue
        try:
            im = Image.open(io.BytesIO(b)).convert('RGB')
        except Exception:
            continue
        for g in f2g[f]:
            big = GRP.get(g) in OMURGALI
            side = 480 if big else 320
            j = im.copy(); j.thumbnail((side, side), Image.LANCZOS)
            j.save(f'out/img/{g}.webp', 'WEBP', quality=60 if big else 55, method=6)
            credits[g] = {'a': info[f]['a'] or 'Wikimedia Commons', 'l': info[f]['l'] or '', 'f': f, 's': 'c'}
            done += 1
print('indirilen foto', done, flush=True)
for o in out.values(): o.pop('imgf', None)
json.dump(out, open('out/wiki.json', 'w'), ensure_ascii=False, separators=(',', ':'))
json.dump(credits, open('out/credits.json', 'w'), ensure_ascii=False, separators=(',', ':'))
