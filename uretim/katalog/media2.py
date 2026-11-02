"""Commons'ta fotoğrafı olmayan türler için ticari kullanıma uygun (CC0, CC BY, CC BY-SA) iNaturalist fotoğrafı bulur.
A) iNaturalist taksonu varsa varsayılan fotoğrafı (30'arlı toplu sorgu)
B) Kalanlar için GBIF'teki iNaturalist gözlemleri (önce Türkiye, sonra her yer)
Ara sonuçlar gbif_media.json'a yazılır; yeniden çalışınca kaldığı yerden devam eder."""
import json, urllib.request, urllib.parse, concurrent.futures as cf, time, os, threading
K = json.load(open('species_keep.json'))
W = json.load(open('wiki/wiki.json'))
C = json.load(open('wiki/credits.json'))
ITR = json.load(open('inat_tr.json')); IEN = json.load(open('inat_en.json'))
OUT = 'gbif_media.json'
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
done = set(json.load(open('media_done.json'))) if os.path.exists('media_done.json') else set()
lock = threading.Lock()
UA = {'User-Agent': 'KampDefteri/1.9 (github.com/MuzafferAbdullahOrtakaya/kamp-defteri-haritalar)'}
def get(u, tries=5):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25))
        except Exception: time.sleep(1 + 2 * i)
    return None
def fix(s):
    try: return s.encode('latin-1').decode('utf-8')
    except Exception: return s
def save():
    with lock:
        json.dump(res, open(OUT + '.tmp', 'w'), ensure_ascii=False); os.replace(OUT + '.tmp', OUT)
        json.dump(sorted(done), open('media_done.json', 'w'))
need = [d for d in K if str(d['k']) not in C and str(d['k']) not in res and d['k'] not in done]
print('gerekli', len(need), flush=True)
OK = {'cc0': 'CC0', 'cc-by': 'CC BY 4.0', 'cc-by-sa': 'CC BY-SA 4.0'}
# A) iNaturalist toplu
idmap = {}
for d in need:
    i = (W.get(str(d['k'])) or {}).get('inat') or (ITR.get(d['sci']) or {}).get('id') or (IEN.get(d['sci']) or {}).get('id')
    if i: idmap[int(i)] = d['k']
ids = list(idmap) if not os.path.exists('media_a.ok') else []
t0 = time.time()
for j in range(0, len(ids), 30):
    r = get('https://api.inaturalist.org/v1/taxa/' + ','.join(map(str, ids[j:j + 30])))
    for t in (r or {}).get('results', []):
        p = t.get('default_photo') or {}
        lc = p.get('license_code')
        k = idmap.get(t.get('id'))
        if k and lc in OK and p.get('medium_url') and 'inaturalist-open-data' in p['medium_url']:
            a = fix(p.get('attribution') or '')
            a = a.replace('(c) ', '').split(', some rights')[0].split(', no rights')[0][:100]
            res[str(k)] = {'u': p['medium_url'], 'a': a, 'l': OK[lc], 'tr': 0}
    time.sleep(1.0)
    if j % 600 == 0: print('A', j, len(ids), len(res), int(time.time() - t0), 's', flush=True)
save()
open('media_a.ok', 'w').write('1')
print('A bitti', len(res), flush=True)
# B) GBIF
INAT = '50c9509d-22c7-4a22-a47d-8c48425ef4a7'
def one(d):
    k = d['k']
    for extra in ({},):
        p = {'speciesKey': k, 'mediaType': 'StillImage', 'datasetKey': INAT, 'license': ['CC0_1_0', 'CC_BY_4_0'], 'limit': 5, **extra}
        r = get('https://api.gbif.org/v1/occurrence/search?' + urllib.parse.urlencode(p, doseq=True), tries=2)
        for occ in (r or {}).get('results', []):
            for m in occ.get('media', []):
                u = m.get('identifier', '')
                lic = m.get('license', '') or occ.get('license', '')
                if 'inaturalist-open-data' in u and ('by/4.0' in lic or 'zero' in lic or 'CC0' in lic or 'CC_BY_4_0' in lic):
                    return k, {'u': u.replace('/original.', '/medium.'), 'a': fix(m.get('creator') or m.get('rightsHolder') or occ.get('recordedBy') or '')[:100],
                               'l': 'CC0' if ('zero' in lic or 'CC0' in lic) else 'CC BY 4.0', 'tr': 1 if extra else 0}
    return k, None
rest = [d for d in need if str(d['k']) not in res]
print('B', len(rest), flush=True)
t0 = time.time()
with cf.ThreadPoolExecutor(24) as ex:
    for i, (k, v) in enumerate(ex.map(one, rest)):
        with lock:
            if v: res[str(k)] = v
            done.add(k)
        if i % 500 == 0:
            print('B', i, len(rest), len(res), int(time.time() - t0), 's', flush=True)
            save()
save()
print('bitti: fotoğrafı bulunan', len(res), flush=True)
