#!/usr/bin/env python3
"""Paralel işler için illeri gruplara böler. Kullanım: grup.py <grup_no> <grup_sayısı> [il1,il2,...]"""
import json, os, sys
iller = json.load(open(os.path.join(os.path.dirname(__file__), 'iller.json')))
secim = sys.argv[3] if len(sys.argv) > 3 else 'hepsi'
if secim not in ('', 'hepsi'):
    isim = set(secim.split(','))
    iller = [i for i in iller if i['id'] in isim]
g, n = int(sys.argv[1]), int(sys.argv[2])
for i, il in enumerate(sorted(iller, key=lambda x: -(x['bbox'][2]-x['bbox'][0])*(x['bbox'][3]-x['bbox'][1]))):
    if i % n == g:
        print(il['id'], il['name'], ','.join(str(v) for v in il['bbox']), sep='\t')
