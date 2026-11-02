"""Uygulamanın Türkiye faunası kataloğunu üretir.

Girdiler (bu klasörde):
  species_keep.json   GBIF tür listesi ve sınıflandırma
  gbif_lists.json     tür kayıt sayıları, illere ve aylara göre kayıtlar
  gadm2plaka.json     GBIF il numarası → plaka
  wiki/wiki.json, wiki/credits.json, wiki/img/*.webp   (GitHub Actions'tan: Vikiveri, Vikipedi, Commons)
  inat_tr.json, inat_en.json  iNaturalist Türkçe/İngilizce adlar
  gbif_media.json     iNaturalist fotoğrafları (CC0 / CC BY), Commons'ta foto yoksa
Çıktılar (uygulamaya):
  assets/fauna/katalog.json.gz, assets/fauna/aciklama.json.gz, assets/fauna/img/<anahtar>.webp
"""
import concurrent.futures as cf, gzip, io, json, os, shutil, time, urllib.request
from PIL import Image

APP = '/home/claude/kamp_defteri/assets/fauna'
OMURGALI = {'memeli', 'kus', 'surungen', 'amfibi', 'balik'}
UA = 'KampDefteri/1.9 (github.com/MuzafferAbdullahOrtakaya/kamp-defteri-haritalar)'

K = json.load(open('species_keep.json'))
L = json.load(open('gbif_lists.json'))
G2P = json.load(open('gadm2plaka.json'))
W = json.load(open('wiki/wiki.json')) if os.path.exists('wiki/wiki.json') else {}
WC = json.load(open('wiki/credits.json')) if os.path.exists('wiki/credits.json') else {}
ITR = json.load(open('inat_tr.json'))
IEN = json.load(open('inat_en.json'))
GM = json.load(open('gbif_media.json')) if os.path.exists('gbif_media.json') else {}
# Vikipedi metninde açıkça "Türkiye'ye endemik / endemic to Turkey" yazan türler (Vikiveri'de çok az tür işaretli)
END_TXT = set(json.load(open('endemic_text.json'))) if os.path.exists('endemic_text.json') else set()

# İl ve ay kayıtları
prov = {}
for g, keys in L['il'].items():
    p = G2P.get(str(g))
    if p is None: continue
    for k in keys:
        prov.setdefault(int(k), set()).add(p)
months = {}
for m, d in L['ay'].items():
    for k, c in d.items():
        months.setdefault(int(k), [0] * 12)[int(m) - 1] = c

def cap(s):
    s = (s or '').strip()
    return s[:1].upper() + s[1:] if s else ''

def good_name(n, sci):
    """Vikiveri etiketi çoğu zaman bilimsel adın aynısıdır: o zaman ad sayılmaz"""
    if not n: return ''
    if n.strip().lower() == sci.lower(): return ''
    if n.split(' ')[0].lower() == sci.split(' ')[0].lower() and len(n.split(' ')) == 2: return ''
    return cap(n)

# Fotoğraflar: önce Commons (Actions'tan), yoksa iNaturalist (burada indir)
os.makedirs(f'{APP}/img', exist_ok=True)
credit = {}
for k, c in WC.items():
    src = f'wiki/img/{k}.webp'
    if os.path.exists(src):
        shutil.copy(src, f'{APP}/img/{k}.webp')
        credit[int(k)] = [c['a'] or 'Wikimedia Commons', c['l'] or 'CC BY-SA', 'c']
need = [(int(k), v) for k, v in GM.items() if int(k) not in credit]
print('Commons foto', len(credit), 'iNaturalist ile tamamlanacak', len(need), flush=True)
grp = {d['k']: d['grp'] for d in K}

def fetch(item):
    k, v = item
    out = f'{APP}/img/{k}.webp'
    if os.path.exists(out) and os.path.getsize(out) > 500:
        return k, v
    for t in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(v['u'], headers={'User-Agent': UA}), timeout=60).read()
            im = Image.open(io.BytesIO(b)).convert('RGB')
            big = grp.get(k) in OMURGALI
            side = 480 if big else 320
            im.thumbnail((side, side), Image.LANCZOS)
            im.save(out, 'WEBP', quality=60 if big else 55, method=6)
            return k, v
        except Exception:
            time.sleep(2 + 3 * t)
    return k, None

with cf.ThreadPoolExecutor(12) as ex:
    for i, (k, v) in enumerate(ex.map(fetch, need)):
        if v: credit[k] = [v['a'] or 'iNaturalist', v['l'], 'i']
        if i % 2000 == 0: print('indirilen', i, flush=True)

orders, families = [], []
oi, fi = {}, {}
def idx(name, lst, d):
    if not name: return -1
    if name not in d:
        d[name] = len(lst); lst.append(name)
    return d[name]

rows, texts = [], {}
for d in K:
    k, sci = d['k'], d['sci']
    w = W.get(str(k), {})
    it, ie = ITR.get(sci, {}), IEN.get(sci, {})
    tr = cap((w.get('trn') or [None])[0]) or cap(it.get('tr')) or good_name(w.get('tr'), sci)
    en = cap(ie.get('tr')) or good_name(w.get('en'), sci)
    if tr and en and tr == en: tr = ''  # iNat Türkçe ad yoksa İngilizcesini verir
    flags = 0
    if w.get('end') or str(k) in END_TXT: flags |= 1
    if k in credit and os.path.exists(f'{APP}/img/{k}.webp'): flags |= 2
    if w.get('trx'): flags |= 4
    if w.get('enx'): flags |= 8
    ms = months.get(k)
    mstr = ''
    if ms and max(ms) > 0:
        top = max(ms)
        mstr = ''.join(str(min(9, round(c / top * 9))) if c else '0' for c in ms)
    rows.append([k, sci, tr, en, d['grp'], idx(d.get('order'), orders, oi), idx(d.get('family'), families, fi),
                 w.get('iucn') or '', flags, L['all'].get(str(k), 0), sorted(prov.get(k, ())), mstr,
                 credit.get(k) if flags & 2 else None])
    if w.get('trx') or w.get('enx'):
        texts[str(k)] = [w.get('trx', ''), w.get('enx', ''), w.get('trw', ''), w.get('enw', '')]

# Fotoğrafı kullanılmayanları sil (önceki denemelerden kalmış olabilir)
keep = {r[0] for r in rows if r[8] & 2}
for f in os.listdir(f'{APP}/img'):
    if int(f.split('.')[0]) not in keep: os.remove(f'{APP}/img/{f}')

data = {'v': 1, 'tarih': time.strftime('%Y-%m-%d'),
        'kaynak': 'GBIF (Türkiye kayıtları), Vikiveri, Vikipedi (CC BY-SA), Wikimedia Commons, iNaturalist',
        'takimlar': orders, 'aileler': families, 'turler': rows}
raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
open(f'{APP}/katalog.json.gz', 'wb').write(gzip.compress(raw, 9))
rawt = json.dumps(texts, ensure_ascii=False, separators=(',', ':')).encode()
open(f'{APP}/aciklama.json.gz', 'wb').write(gzip.compress(rawt, 9))
imgs = os.listdir(f'{APP}/img')
size = sum(os.path.getsize(f'{APP}/img/{f}') for f in imgs)
print('tür', len(rows), 'Türkçe adlı', sum(1 for r in rows if r[2]), 'İngilizce adlı', sum(1 for r in rows if r[3]),
      'foto', len(imgs), f'{size / 1e6:.0f} MB', 'açıklama', len(texts),
      'katalog', len(raw) // 1024, 'KB ->', os.path.getsize(f'{APP}/katalog.json.gz') // 1024, 'KB gz',
      'açıklama', len(rawt) // 1024, 'KB ->', os.path.getsize(f'{APP}/aciklama.json.gz') // 1024, 'KB gz')
