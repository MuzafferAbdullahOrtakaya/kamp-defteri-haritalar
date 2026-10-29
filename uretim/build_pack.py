#!/usr/bin/env python3
"""Kamp Defteri internetsiz arazi paketi üretir.

Çıktı (out/<id>/):
  <id>_harita.pmtiles  OSM vektör (Protomaps şeması), z0-15
  <id>_egri.pmtiles    Eş yükselti çizgileri (vektör, katman "contour", alan "ele", "idx"), z10-13
  <id>_golge.pmtiles   Dağ gölgelendirmesi (RGBA webp, siyah/beyaz saydam), z7-12
  <id>_dem.pmtiles     Yükseklik (terrarium webp, kayıpsız), z7-10 (3B görünüm ve internetsiz yükseklik)

Kaynaklar: Protomaps günlük derlemesi (ODbL), Mapterhorn (Copernicus GLO-30).
"""
import io, json, math, os, subprocess, sys, gzip, time
import numpy as np
from PIL import Image
from pmtiles.reader import Reader, MmapSource
from pmtiles.writer import Writer
from pmtiles.tile import zxy_to_tileid, TileType, Compression

ROOT = os.path.dirname(os.path.abspath(__file__))
PM = os.path.join(ROOT, 'bin', 'go-pmtiles')
PROTOMAPS = os.environ.get('PROTOMAPS', 'https://build.protomaps.com/20261028.pmtiles')
TERRAIN = 'https://download.mapterhorn.com/planet.pmtiles'
DEM_Z = 11      # Mapterhorn z11 512px ≈ Copernicus 30 m çözünürlüğü
R = 6378137.0
ORIGIN = math.pi * R


def run(*cmd):
    t = time.time()
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return time.time() - t


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_bounds_merc(x, y, z):
    size = 2 * ORIGIN / 2 ** z
    minx = -ORIGIN + x * size
    maxy = ORIGIN - y * size
    return minx, maxy - size, minx + size, maxy


def decode_terrarium(png_bytes):
    a = np.asarray(Image.open(io.BytesIO(png_bytes)).convert('RGB')).astype(np.float32)
    return a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768


def encode_terrarium(elev):
    v = np.clip(elev + 32768, 0, 65535.99)
    r = np.floor(v / 256)
    g = np.floor(v - r * 256)
    b = np.floor((v - r * 256 - g) * 256)
    return np.stack([r, g, b], -1).astype(np.uint8)


def build(pid, name, bbox, out_dir):
    minlon, minlat, maxlon, maxlat = bbox
    od = os.path.join(out_dir, pid)
    os.makedirs(od, exist_ok=True)
    tmp = os.path.join(od, 'tmp')
    os.makedirs(tmp, exist_ok=True)
    b = f'{minlon},{minlat},{maxlon},{maxlat}'
    info = {'id': pid, 'name': name, 'bbox': bbox}

    # 1) vektör harita
    vec = os.path.join(od, f'{pid}_harita.pmtiles')
    if not os.path.exists(vec):
        dt = run(PM, 'extract', PROTOMAPS, vec, f'--bbox={b}', '--maxzoom=15', '--download-threads=4')
        print(f'  vektör {os.path.getsize(vec)/1e6:.1f} MB ({dt:.0f} sn)')

    # 2) yükseklik (Mapterhorn z0-11)
    raw_dem = os.path.join(tmp, 'mapterhorn.pmtiles')
    if not os.path.exists(raw_dem):
        dt = run(PM, 'extract', TERRAIN, raw_dem, f'--bbox={b}', f'--maxzoom={DEM_Z}', '--download-threads=4')
        print(f'  ham yükseklik {os.path.getsize(raw_dem)/1e6:.1f} MB ({dt:.0f} sn)')

    # 3) z11 karolarını tek bir yükseklik dizisine birleştir (EPSG:3857, 512 px karolar)
    x0, y0 = lonlat_to_tile(minlon, maxlat, DEM_Z)
    x1, y1 = lonlat_to_tile(maxlon, minlat, DEM_Z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    TS = 512
    dem = np.zeros((ny * TS, nx * TS), np.float32)
    with open(raw_dem, 'rb') as f:
        rd = Reader(MmapSource(f))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                data = rd.get(DEM_Z, tx, ty)
                if data is None:
                    continue
                e = decode_terrarium(data)
                if e.shape[0] != TS:
                    e = np.asarray(Image.fromarray(e).resize((TS, TS), Image.BILINEAR))
                dem[(ty - ty0) * TS:(ty - ty0 + 1) * TS, (tx - tx0) * TS:(tx - tx0 + 1) * TS] = e
    dem[dem < -500] = 0
    mx0, _, _, my1 = tile_bounds_merc(tx0, ty0, DEM_Z)
    px = 2 * ORIGIN / 2 ** DEM_Z / TS
    lat_c = math.radians((minlat + maxlat) / 2)
    info['elev'] = [float(dem.min()), float(dem.max())]
    print(f'  yükseklik {dem.shape[1]}x{dem.shape[0]} piksel, {dem.min():.0f}–{dem.max():.0f} m')

    # 4) gölgelendirme (çok yönlü), z12 256 px karolarına doğrudan denk gelir
    golge = os.path.join(od, f'{pid}_golge.pmtiles')
    if not os.path.exists(golge):
        ground = px * math.cos(lat_c)  # gerçek piksel boyu (m)
        gy, gx = np.gradient(dem, ground)
        slope = np.arctan(np.hypot(gx, gy) * 1.6)
        aspect = np.arctan2(-gx, gy)
        shade = np.zeros_like(dem)
        for az, w in ((315, 0.55), (270, 0.2), (0, 0.15), (225, 0.10)):
            a = math.radians(az)
            alt = math.radians(45)
            shade += w * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(a - aspect))
        shade = np.clip(shade, 0, 1)
        flat = math.sin(math.radians(45))
        dark = np.clip((flat - shade) / flat, 0, 1)        # gölge
        light = np.clip((shade - flat) / (1 - flat), 0, 1)  # ışık alan yamaç
        # Sadece gölge: sabit koyu renk + saydamlık. Tek kanal bilgi olduğu için çok iyi sıkışır.
        rgba = np.zeros(dem.shape + (4,), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 28, 38, 44
        a = np.clip(dark * 210 + (1 - light) * 12 - 12, 0, 255)
        rgba[..., 3] = (np.round(a / 6) * 6).astype(np.uint8)  # basamaklandırma: daha küçük dosya
        img = Image.fromarray(rgba, 'RGBA')
        write_raster_pyramid(golge, img, tx0 * 2, ty0 * 2, 12, 7, bbox, quality=60, lossless=False,
                             name=f'{name} gölgelendirme')
        print(f'  gölge {os.path.getsize(golge)/1e6:.1f} MB')

    # 5) 3B için hafif yükseklik: z10 512 px (≈60 m), terrarium kayıpsız
    demf = os.path.join(od, f'{pid}_dem.pmtiles')
    if not os.path.exists(demf):
        small = np.asarray(Image.fromarray(dem).resize((dem.shape[1] // 2, dem.shape[0] // 2), Image.BILINEAR))
        img = Image.fromarray(encode_terrarium(small), 'RGB')
        write_raster_pyramid(demf, img, tx0, ty0, 11, 7, bbox, quality=100, lossless=True,
                             name=f'{name} yükseklik', resample=Image.NEAREST, tile_px=256)
        print(f'  3B yükseklik {os.path.getsize(demf)/1e6:.1f} MB')

    # 6) eş yükselti çizgileri
    egri = os.path.join(od, f'{pid}_egri.pmtiles')
    if not os.path.exists(egri):
        # hafif yumuşatma: tırtıklı çizgileri önler
        sm = blur(dem, 1.2)
        rawf = os.path.join(tmp, 'dem.f32')
        sm.astype('<f4').tofile(rawf)
        vrt = os.path.join(tmp, 'dem.vrt')
        with open(vrt, 'w') as f:
            f.write(f'''<VRTDataset rasterXSize="{sm.shape[1]}" rasterYSize="{sm.shape[0]}">
  <SRS>EPSG:3857</SRS>
  <GeoTransform>{mx0}, {px}, 0, {my1}, 0, {-px}</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
    <SourceFilename relativeToVRT="1">dem.f32</SourceFilename>
    <ByteOrder>LSB</ByteOrder><ImageOffset>0</ImageOffset><PixelOffset>4</PixelOffset><LineOffset>{sm.shape[1]*4}</LineOffset>
  </VRTRasterBand>
</VRTDataset>''')
        shp = os.path.join(tmp, 'egri.gpkg')
        if os.path.exists(shp):
            os.remove(shp)
        run('gdal_contour', '-i', '20', '-a', 'ele', vrt, shp)
        gj = os.path.join(tmp, 'egri.geojsonl')
        if os.path.exists(gj):
            os.remove(gj)
        run('ogr2ogr', '-f', 'GeoJSONSeq', '-t_srs', 'EPSG:4326', '-lco', 'COORDINATE_PRECISION=5',
            '-dialect', 'SQLite', '-sql', 'SELECT CAST(ele AS INTEGER) AS ele, CASE WHEN CAST(ele AS INTEGER) % 100 = 0 THEN 1 ELSE 0 END AS idx, geom FROM contour',
            '-clipdst', str(minlon), str(minlat), str(maxlon), str(maxlat), gj, shp)
        # z10-11: sadece 100 m'lik ana çizgiler; z12+: hepsi
        run('tippecanoe', '-o', egri, '-l', 'contour', '-Z10', '-z13', '--force',
            '-j', '{"contour":["any",["==","idx",1],[">=","$zoom",12]]}',
            '--simplification=4', '--no-tile-size-limit', '--detect-shared-borders',
            '-n', f'{name} eş yükselti', '-A', '© Mapterhorn, Copernicus GLO-30', gj)
        print(f'  eş yükselti {os.path.getsize(egri)/1e6:.1f} MB')

    info['files'] = {k: os.path.getsize(os.path.join(od, f'{pid}_{k}.pmtiles')) for k in ('harita', 'egri', 'golge', 'dem')}
    info['total'] = sum(info['files'].values())
    json.dump(info, open(os.path.join(od, 'info.json'), 'w'), ensure_ascii=False)
    print(f'  TOPLAM {info["total"]/1e6:.1f} MB')
    return info


def blur(a, sigma):
    r = int(sigma * 3)
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sigma * sigma))
    k /= k.sum()
    p = np.pad(a, r, mode='edge')
    p = np.apply_along_axis(lambda m: np.convolve(m, k, 'valid'), 1, p)
    p = np.apply_along_axis(lambda m: np.convolve(m, k, 'valid'), 0, p)
    return p.astype(np.float32)


def write_raster_pyramid(path, img, x_origin, y_origin, maxz, minz, bbox, quality, lossless, name,
                         resample=Image.LANCZOS, tile_px=256):
    """img: maxz seviyesinde tile_px'lik karolara hizalı tam görüntü (sol üst karo = x_origin,y_origin)."""
    entries = []
    z = maxz
    cur, ox, oy = img, x_origin, y_origin
    tiles = {}
    while z >= minz:
        w, h = cur.size
        ntx, nty = math.ceil(w / tile_px), math.ceil(h / tile_px)
        for j in range(nty):
            for i in range(ntx):
                t = cur.crop((i * tile_px, j * tile_px, (i + 1) * tile_px, (j + 1) * tile_px))
                if t.mode == 'RGBA' and t.getextrema()[3][1] == 0:
                    continue
                buf = io.BytesIO()
                t.save(buf, 'WEBP', quality=quality, lossless=lossless, method=4, alpha_quality=quality)
                tiles[zxy_to_tileid(z, ox + i, oy + j)] = buf.getvalue()
        # bir üst seviye: 2'ye böl (hizalama: ox çiftse doğrudan, tekse yarım karo kaydır)
        if z == minz:
            break
        padx, pady = ox % 2, oy % 2
        canvas = Image.new(cur.mode, (w + padx * tile_px, h + pady * tile_px))
        canvas.paste(cur, (padx * tile_px, pady * tile_px))
        w2, h2 = canvas.size
        canvas = canvas.crop((0, 0, w2 + (w2 // tile_px) % 2 * tile_px, h2 + (h2 // tile_px) % 2 * tile_px)) if False else canvas
        cur = canvas.resize((max(1, canvas.size[0] // 2), max(1, canvas.size[1] // 2)), resample)
        ox, oy = (ox - padx) // 2, (oy - pady) // 2
        z -= 1
    with open(path, 'wb') as f:
        wr = Writer(f)
        for tid in sorted(tiles):
            wr.write_tile(tid, tiles[tid])
        minlon, minlat, maxlon, maxlat = bbox
        wr.finalize({
            'tile_type': TileType.WEBP,
            'tile_compression': Compression.NONE,
            'min_zoom': minz, 'max_zoom': maxz,
            'min_lon_e7': int(minlon * 1e7), 'min_lat_e7': int(minlat * 1e7),
            'max_lon_e7': int(maxlon * 1e7), 'max_lat_e7': int(maxlat * 1e7),
            'center_zoom': minz, 'center_lon_e7': int((minlon + maxlon) / 2 * 1e7),
            'center_lat_e7': int((minlat + maxlat) / 2 * 1e7),
        }, {'name': name, 'attribution': '© Mapterhorn, Copernicus GLO-30'})


if __name__ == '__main__':
    pid, name = sys.argv[1], sys.argv[2]
    bbox = [float(v) for v in sys.argv[3].split(',')]
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(ROOT, 'out')
    t = time.time()
    build(pid, name, bbox, out)
    print(f'  süre {time.time()-t:.0f} sn')
