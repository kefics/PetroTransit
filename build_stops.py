#!/usr/bin/env python3
"""Собирает stops.json для PetroTransit из OpenStreetMap.

Запуск (нужен интернет, ~5-10 минут):   python3 build_stops.py
Опции:
  --dry            только показать число уникальных остановок
  --osm FILE       взять остановки из сохранённого файла (по умолчанию osm_stops.json, если он есть)
  --no-geocode     не использовать Nominatim/Photon для остановок, которых нет в OSM
Результат: stops.json (положить рядом с index.html), stops_report.csv, not_found.txt
Как работает: скачивает все автобусные остановки Петропавловска из OSM (Overpass),
сопоставляет их с названиями из app.js (с учётом порядка остановок на маршруте,
чтобы выбрать нужную сторону улицы), остальное ищет через геокодеры."""
import csv, difflib, json, math, os, re, sys, time, urllib.parse, urllib.request
A = sys.argv[1:]
src = open('app.js', encoding='utf-8').read()
routes = json.loads(re.search(r'let routeData=(\{.*?\});\s*\nconst colors', src, re.S).group(1))
COORD = re.compile(r'\s*@\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$')
BBOX = (54.60, 68.60, 55.20, 69.60)  # юг, запад, север, восток
UA = {'User-Agent': 'PetroTransit-stops-builder/2.0', 'Accept': 'application/json'}

def variants(x):
    x = COORD.sub('', x); v = [x]; m = re.search(r'\(([^)]*)\)', x)
    t = re.sub(r'\([^)]*\)', '', re.sub(r'^По требованию\s*\((.*)\)$', r'\1', x, flags=re.I)).strip()
    t = re.sub(r'^ул\.\s*', 'улица ', t, flags=re.I)
    if m: v.append(re.sub(r'^ул\.\s*', 'улица ', m.group(1), flags=re.I))
    u = re.sub(r'^(пос\.|с\.|микрорайон|мкр\.?)\s*', '', t, flags=re.I).strip()
    v += [t, u]
    if re.search('ж/д вокзал', x, re.I): v.append('железнодорожный вокзал')
    return list(dict.fromkeys(i for i in v if i))

def norm(x):
    x = x.lower().replace('ё', 'е').replace('ж/д', 'железнодорожный')
    x = re.sub(r'[«»"“”\'.,()\-–—]', ' ', x)
    x = re.sub(r'\b(улица|ул|остановка|мкр|пос|поселок|село|им|имени)\b', ' ', x)
    return re.sub(r'\s+', ' ', x).strip()

def dist(p, q):
    la = math.radians((p[0] + q[0]) / 2)
    return math.hypot((p[0] - q[0]) * 111.2, (p[1] - q[1]) * 111.2 * math.cos(la))  # км

def http(url, data=None, wait=0):
    time.sleep(wait)
    req = urllib.request.Request(url, data=data, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=90) as r: return json.load(r)
    except Exception as e:
        print('  ошибка запроса:', str(e)[:80]); return None

def load_osm():
    f = A[A.index('--osm') + 1] if '--osm' in A else 'osm_stops.json'
    if os.path.exists(f): return json.load(open(f, encoding='utf-8'))
    s, w, n, e = BBOX
    q = f'[out:json][timeout:80];(node["highway"="bus_stop"]({s},{w},{n},{e});node["public_transport"~"platform|stop_position"]["bus"="yes"]({s},{w},{n},{e}););out body;'
    print('Скачиваю остановки из OpenStreetMap…')
    j = None
    for url in ('https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'):
        j = http(url, urllib.parse.urlencode({'data': q}).encode())
        if j: break
    if not j: print('Overpass недоступен; будут использованы только геокодеры.'); return []
    out = []
    for el in j.get('elements', []):
        t = el.get('tags', {})
        names = {t.get(k) for k in ('name', 'name:ru', 'name:kk', 'alt_name', 'official_name', 'int_name') if t.get(k)}
        if names: out.append({'p': [el['lat'], el['lon']], 'names': sorted(names)})
    json.dump(out, open('osm_stops.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'Получено именованных остановок: {len(out)} (сохранено в osm_stops.json)')
    return out

def score(a, b):
    if not a or not b: return 0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if min(len(a), len(b)) >= 5 and (a in b or b in a): r = max(r, .9)
    return r

def candidates(name, osm):
    best, res = 0, []
    for v in variants(name):
        nv = norm(v)
        for s in osm:
            sc = max(score(nv, s['_n'][i]) for i in range(len(s['_n'])))
            if sc > best + .03: best, res = sc, [s]
            elif sc >= best - .03 and sc >= .82 and s not in res: res.append(s)
            if sc > best: best = sc
        if best >= .95: break
    return (best, res) if best >= .82 else (best, [])

def geocode(name, sub):
    for q in variants(name)[:3]:
        j = http('https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&bounded=1&viewbox=69.00,54.95,69.30,54.78&q=' + urllib.parse.quote(q + ', Петропавловск, Казахстан'), wait=1.1)
        for h in j or []:
            la, lo = float(h['lat']), float(h['lon'])
            if abs(la - 54.873) < .2 and abs(lo - 69.151) < .25: return [la, lo]
    if sub:
        j = http('https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=' + urllib.parse.quote(COORD.sub('', name) + ', Северо-Казахстанская область, Казахстан'), wait=1.1)
        for h in j or []:
            la, lo = float(h['lat']), float(h['lon'])
            if 54 < la < 55.8 and 68 < lo < 70.8: return [la, lo]
    return None

def match_route(names, osm, cache):
    """Для каждой остановки: список вариантов-точек; затем выбор по порядку маршрута."""
    cand = []
    for n in names:
        if COORD.search(n):
            m = re.search(r'@\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)', n); cand.append(([[float(m.group(1)), float(m.group(2))]], 'manual')); continue
        if n not in cache: cache[n] = candidates(n, osm)
        sc, res = cache[n]
        cand.append(([s['p'] for s in res], 'osm') if res else ([], 'none'))
    chosen, prev = [None] * len(names), None
    for i, (pts, _) in enumerate(cand):  # первая остановка: ближайшая к вариантам следующей найденной
        if not pts: continue
        if prev is None:
            nxt = next((c[0] for c in cand[i + 1:] if c[0]), [])
            prev = min(pts, key=lambda p: min((dist(p, q) for q in nxt), default=0)) if len(pts) > 1 else pts[0]
        else:
            prev = min(pts, key=lambda p: dist(p, prev))
        chosen[i] = prev
    return chosen, [c[1] for c in cand]

osm = [] if '--dry' in A else load_osm()
for s in osm: s['_n'] = [norm(x) for x in s['names']]
todo = {}
for k, r in routes.items():
    for x in r['stops']:
        if not COORD.search(x): todo.setdefault(x.lower(), (x, bool(re.match(r'\d{3}', k))))
print(len(todo), 'уникальных остановок;', len(osm), 'остановок OSM')
if '--dry' in A: sys.exit()
out, rep, bad, cache, geo = {}, [], [], {}, {}
for k, r in routes.items():
    chosen, src_ = match_route(r['stops'], osm, cache)
    for i, (name, p) in enumerate(zip(r['stops'], chosen)):
        how = src_[i]
        if p is None and '--no-geocode' not in A and not COORD.search(name):
            key = name.lower()
            if key not in geo: print(f'геокодер: {name}'); geo[key] = geocode(name, bool(re.match(r'\d{3}', k)))
            p = geo[key]; how = 'geocoder' if p else 'none'
        if p:
            if not COORD.search(name): out[f'{k}|{name}'.lower()] = [round(p[0], 6), round(p[1], 6)]; out.setdefault(name.lower(), [round(p[0], 6), round(p[1], 6)])
        else: bad.append(f'{k}: {name}')
        rep.append([k, i + 1, name, how, p[0] if p else '', p[1] if p else ''])
    pts = [p for p in chosen if p]
    for a, b in zip(pts, pts[1:]):
        if dist(a, b) > 4: print(f'  ⚠ маршрут {k}: перегон {dist(a,b):.1f} км — проверьте остановки рядом'); break
json.dump(out, open('stops.json', 'w', encoding='utf-8'), ensure_ascii=False)
csv.writer(open('stops_report.csv', 'w', newline='', encoding='utf-8-sig')).writerows([['маршрут', '№', 'остановка', 'источник', 'lat', 'lon']] + rep)
open('not_found.txt', 'w', encoding='utf-8').write('\n'.join(bad))
n_osm = sum(1 for r in rep if r[3] == 'osm'); n_g = sum(1 for r in rep if r[3] == 'geocoder')
print(f'Готово: из OSM {n_osm}, геокодером {n_g}, не найдено {len(bad)} из {len(rep)} (см. stops_report.csv, not_found.txt)')
