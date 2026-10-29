import json, urllib.request, urllib.parse, re, os, time, sys, io
UA = "KampDefteriBuild/1.4 (https://github.com/MuzafferAbdullahOrtakaya/kamp-defteri-haritalar)"
API = "https://commons.wikimedia.org/w/api.php?"
def get(url, raw=False, tries=12):
    for i in range(tries):
        try:
            time.sleep(1.5)
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()
            return r if raw else json.loads(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                time.sleep(min(90, int(ra) if ra and ra.isdigit() else 8 * (i + 1))); continue
            raise
    raise RuntimeError("429 " + url)
OK = re.compile(r'^(cc0|public domain|pd|cc by(-sa)? ?[0-9.]*( [a-z]+)?|cc-by(-sa)?-[0-9.]+)', re.I)
def info(files, width=None):
    out = {}
    for i in range(0, len(files), 40):
        p = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size|duration",
             "titles": "|".join("File:" + f for f in files[i:i+40])}
        if width: p["iiurlwidth"] = width
        d = get(API + urllib.parse.urlencode(p))
        norm = {n["to"]: n["from"] for n in d["query"].get("normalized", [])}
        for pg in d["query"]["pages"].values():
            if "imageinfo" not in pg: continue
            ii = pg["imageinfo"][0]; m = ii.get("extmetadata", {})
            lic = m.get("LicenseShortName", {}).get("value", "")
            art = re.sub(r'<[^>]+>', '', m.get("Artist", {}).get("value", "")).strip()
            art = re.sub(r'\s+', ' ', art)[:80]
            out[pg["title"][5:]] = {"url": ii["url"], "thumb": ii.get("thumburl"), "lic": lic, "artist": art or "bilinmiyor",
                                     "page": ii.get("descriptionurl"), "mime": ii.get("mime"), "dur": ii.get("duration"), "ok": bool(OK.match(lic.strip()))}
    return out
def search(q, n=8):
    d = get(API + urllib.parse.urlencode({"action": "query", "format": "json", "list": "search", "srnamespace": 6, "srsearch": q, "srlimit": n}))
    return [s["title"][5:] for s in d["query"]["search"]]
