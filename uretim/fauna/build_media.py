from fetch import *
import subprocess, numpy as np
from PIL import Image, ImageOps
sp = json.load(open('species.json')); cand = json.load(open('cand.json'))
I = json.load(open('img_info.json')); A = json.load(open('aud_info.json'))
for fn in ('extra.json', 'extra2.json', 'extra3.json'):
    for k, d in json.load(open(fn)).items():
        for f, v in d.items():
            (I if v.get('thumb') else A)[f] = v
img_override = {"kesebocegi": "Thaumetopoea Pityocampa - Procession.jpg", "puhu": "Bubo bubo 1 (Martin Mecnarowski).jpg", "hazer": "Dolichophis jugularis-2015.jpg", "susamuru": "European otter 01.jpg", "alabalik": "Salmo trutta fario-1.jpg",
                "coban_kopegi": "Anatolian Shepherd Dog - Kangal köpeği 01.jpg"}
aud_override = {"ayi": "Yellowstone sound library - Grizzly Bears Roar - 001.mp3", "puhu": "BuboBuboMariankaSlovakia2012.ogg",
                "agackakan": "Buntspecht Trommeln.ogv", "yalicapkini": "Ijsvogel in Nieuwegein - SoundCloud - luc de bruijn.ogg",
                "agac_kurbagasi": "Laubfrosch Balzruf.OGG", "flamingo": "Phoenicopterus roseus (Rosaflamingo - Greater Flamingo) — Weltvogelpark Walsrode 2013.ogg",
                "guguk": "Cuculus canorus.ogg", "alacabaykus": "Tawny Owl (Strix aluco) (W1CDR0001427 BD9).ogg"}
skip_aud = {"balarisi"}  # 15 dk'lık laboratuvar kaydı, uygun değil
ids = list(sp) + ["coban_kopegi"]
credits = json.load(open('credits.json')) if os.path.exists('credits.json') else {}
def dl(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return
    open(path, 'wb').write(get(url, raw=True))
def one(k):
    lat = sp.get(k)
    c = cand.get(lat, {"img": [], "audio": []}) if lat else {"img": [], "audio": []}
    cr = credits.setdefault(k, {})
    # ---- görsel
    f = img_override.get(k) or next((x for x in c["img"] if I.get(x, {}).get("ok")), None)
    if f and not os.path.exists(f"out/img/{k}.webp"):
        v = I[f]
        raw = f"raw/{k}_img"
        dl(v["thumb"] or v["url"], raw)
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")
        im = ImageOps.fit(im, (480, 360), Image.LANCZOS, centering=(0.5, 0.45))
        im.save(f"out/img/{k}.webp", "WEBP", quality=72, method=6)
        cr["img"] = {"file": f, "artist": v["artist"], "lic": v["lic"], "page": v["page"]}
        print(k, "img", os.path.getsize(f"out/img/{k}.webp"), flush=True)
    # ---- ses
    if k in skip_aud: return
    f = aud_override.get(k) or next((x for x in c["audio"] if A.get(x, {}).get("ok")), None)
    if f and not os.path.exists(f"out/snd/{k}.m4a"):
        v = A[f]
        raw = f"raw/{k}_snd"
        dl(v["url"], raw)
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", raw, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
        x = np.frombuffer(pcm, np.int16).astype(np.float32)
        sr = 16000; L = 9 * sr
        start = 0.0
        if len(x) > L:
            win = sr // 4
            e = np.convolve(x ** 2, np.ones(win), 'valid')[::win]
            n = L // win
            cs = np.concatenate([[0], np.cumsum(e)])
            sums = cs[n:] - cs[:-n] if len(e) > n else np.array([cs[-1]])
            start = float(np.argmax(sums) * win / sr)
        dur = min(9.0, len(x) / sr - start)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", raw, "-vn", "-ac", "1", "-ar", "32000",
                        "-af", f"afade=t=in:d=0.25,afade=t=out:st={max(0, dur-0.5):.2f}:d=0.5,loudnorm=I=-18:TP=-2",
                        "-c:a", "aac", "-b:a", "48k", f"out/snd/{k}.m4a"], check=True)
        cr["snd"] = {"file": f, "artist": v["artist"], "lic": v["lic"], "page": v["page"]}
        print(k, "snd", round(dur, 1), os.path.getsize(f"out/snd/{k}.m4a"), flush=True)

fails = []
for k in ids:
    try:
        one(k)
    except Exception as e:
        print("HATA", k, e, flush=True); fails.append(k)
    json.dump(credits, open('credits.json', 'w'), ensure_ascii=False, indent=1)
print("eksik:", fails)
