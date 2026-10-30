"""Türkiye OSM verisinden Kamp Defteri'nin topluluk yerleri ve yürüyüş rotaları.

Girdi: Geofabrik turkey-latest.osm.pbf. Çıktı:
  yerler.json.gz  : kamp, sığınak, su, zirve, köy, göl... (arama ve harita işaretleri)
  rotalar.json.gz : işaretli yürüyüş yolları (route=hiking/foot ilişkileri)
Veri © OpenStreetMap katkıcıları, ODbL 1.0.
"""
import gzip, json, sys, math, datetime
import osmium
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

KINDS = ["camp", "caravan", "hut", "shelter", "picnic", "spring", "water", "viewpoint", "waterfall", "cave",
         "peak", "saddle", "city", "town", "village", "hamlet", "locality", "lake", "park", "beach", "ruins"]
KI = {k: i for i, k in enumerate(KINDS)}
EXTRA = {"fee", "drinking_water", "toilets", "shower", "power_supply", "internet_access", "tents", "caravans", "capacity",
         "website", "contact:website", "phone", "contact:phone", "opening_hours", "operator", "description", "backcountry",
         "access", "dog", "bbq", "fireplace", "openfire", "ele", "intermittent", "seasonal", "wikipedia", "stars", "reservation",
         "shelter_type", "potable", "drinking_water:legal", "height", "fee:conditional", "beds", "check_date"}

def kind_of(t):
    g = t.get
    if g("tourism") == "camp_site": return "camp"
    if g("tourism") == "caravan_site": return "caravan"
    if g("tourism") in ("alpine_hut", "wilderness_hut"): return "hut"
    if g("amenity") == "shelter" and g("shelter_type") not in ("public_transport", "changing_rooms", "sun_shelter", "smoking_shelter", "parking", "field_shelter"):
        return "shelter"
    if g("tourism") == "picnic_site" or g("leisure") == "picnic_site": return "picnic"
    if g("natural") == "spring": return "spring"
    if g("amenity") in ("drinking_water", "water_point") or g("man_made") == "water_tap" or \
       (g("amenity") == "fountain" and g("drinking_water") == "yes"): return "water"
    if g("tourism") == "viewpoint": return "viewpoint"
    if g("waterway") == "waterfall" or g("natural") == "waterfall": return "waterfall"
    if g("natural") == "cave_entrance": return "cave"
    if g("natural") in ("peak", "volcano") and g("name"): return "peak"
    if g("mountain_pass") == "yes" and g("name"): return "saddle"
    if g("natural") == "saddle" and g("name"): return "saddle"
    p = g("place")
    if p in ("city", "town", "village", "hamlet", "locality") and g("name"): return p
    if g("natural") == "water" and g("name") and g("water") not in ("river", "canal", "stream", "wastewater"): return "lake"
    if (g("leisure") == "nature_reserve" or g("boundary") in ("national_park", "protected_area")) and g("name"): return "park"
    if g("natural") == "beach" and g("name"): return "beach"
    if g("historic") in ("ruins", "archaeological_site", "castle") and g("name"): return "ruins"
    return None

def name_of(t):
    return t.get("name:tr") or t.get("name") or ""

def ele_of(t):
    try:
        return int(round(float(str(t.get("ele", "")).replace(",", ".").split()[0])))
    except Exception:
        return 0

class Poi(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.out = []
        self.seen = set()

    def add(self, t, lat, lon, osm):
        k = kind_of(t)
        if not k: return
        key = (k, round(lat, 4), round(lon, 4))
        if key in self.seen: return
        self.seen.add(key)
        row = [KI[k], round(lat * 1e5), round(lon * 1e5), name_of(t), ele_of(t)]
        ex = {x: t[x] for x in EXTRA if x in t and x != "ele"}
        if t.get("name:en") and t.get("name:en") != row[3] and k in ("city", "town", "lake", "park", "peak", "ruins", "beach"):
            ex["en"] = t["name:en"]
        if k in ("camp", "caravan", "hut", "shelter", "picnic", "spring", "water", "viewpoint", "waterfall", "cave", "peak", "lake", "park", "ruins"):
            ex["osm"] = osm
        if ex: row.append(ex)
        self.out.append(row)

    def node(self, n):
        if not n.tags: return
        t = {tag.k: tag.v for tag in n.tags}
        if kind_of(t): self.add(t, n.location.lat, n.location.lon, f"n{n.id}")

    def area(self, a):
        t = {tag.k: tag.v for tag in a.tags}
        k = kind_of(t)
        if not k: return
        # alan merkezi: dış halkaların ağırlık merkezi (basit)
        sx = sy = n = 0
        try:
            for ring in a.outer_rings():
                for nd in ring:
                    sx += nd.lon; sy += nd.lat; n += 1
        except Exception:
            return
        if n == 0: return
        if k == "lake" or k == "park":
            # çok küçük göletleri de al ama adsızları zaten almadık
            pass
        osm = f"w{a.orig_id()}" if a.from_way() else f"r{a.orig_id()}"
        self.add(t, sy / n, sx / n, osm)

class RouteRels(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.rels = {}
        self.ways = set()

    def relation(self, r):
        t = {tag.k: tag.v for tag in r.tags}
        if t.get("type") != "route" or t.get("route") not in ("hiking", "foot"): return
        ws = [m.ref for m in r.members if m.type == "w"]
        if not ws: return
        self.rels[r.id] = (t, ws)
        self.ways.update(ws)

class WayGeom(osmium.SimpleHandler):
    def __init__(self, need):
        super().__init__()
        self.need = need
        self.geom = {}

    def way(self, w):
        if w.id not in self.need: return
        try:
            self.geom[w.id] = [(nd.location.lon, nd.location.lat) for nd in w.nodes]
        except osmium.InvalidLocationError:
            pass

def enc(coords):
    """[(lon,lat)] -> düz liste, 1e5 ölçekli, farkla kodlanmış [lat0,lon0,dlat,dlon,...]"""
    out = []
    plat = plon = 0
    for lon, lat in coords:
        a, b = round(lat * 1e5), round(lon * 1e5)
        out += [a - plat, b - plon]
        plat, plon = a, b
    return out

def length_km(ml):
    tot = 0
    for line in ml:
        for (x1, y1), (x2, y2) in zip(line, line[1:]):
            dx = (x2 - x1) * math.cos(math.radians((y1 + y2) / 2)) * 111.32
            dy = (y2 - y1) * 110.57
            tot += math.hypot(dx, dy)
    return tot

def main(pbf, outdir):
    today = datetime.date.today().isoformat()
    h = Poi()
    h.apply_file(pbf, locations=True, idx="flex_mem")
    pois = h.out
    print("yer:", len(pois), file=sys.stderr)
    with gzip.open(f"{outdir}/yerler.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"v": 1, "t": today, "k": KINDS, "p": pois}, f, ensure_ascii=False, separators=(",", ":"))

    rr = RouteRels(); rr.apply_file(pbf)
    wg = WayGeom(rr.ways); wg.apply_file(pbf, locations=True, idx="flex_mem")
    routes = []
    for rid, (t, ws) in rr.rels.items():
        lines = [wg.geom[w] for w in ws if w in wg.geom and len(wg.geom[w]) > 1]
        if not lines: continue
        merged = linemerge(MultiLineString(lines))
        parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        simp = [list(p.simplify(0.00004).coords) for p in parts]
        simp = [s for s in simp if len(s) > 1]
        if not simp: continue
        km = length_km(simp)
        name = t.get("name:tr") or t.get("name") or t.get("ref") or ""
        if not name and km < 1: continue
        meta = {"id": rid, "name": name, "km": round(km, 1)}
        for k in ("ref", "network", "osmc:symbol", "colour", "website", "from", "to", "description", "operator", "symbol", "distance", "roundtrip"):
            if k in t: meta[k] = t[k]
        if t.get("name:en") and t.get("name:en") != name: meta["en"] = t["name:en"]
        routes.append({"m": meta, "g": [enc(s) for s in simp]})
    routes.sort(key=lambda r: -r["m"]["km"])
    print("rota:", len(routes), file=sys.stderr)
    with gzip.open(f"{outdir}/rotalar.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"v": 1, "t": today, "r": routes}, f, ensure_ascii=False, separators=(",", ":"))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
