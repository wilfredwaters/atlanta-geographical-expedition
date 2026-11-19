"""Build trams.js: historical streetcar networks for Atlanta and Detroit.

Sources, in one folder (SRC):
  ohm_atl.json  OpenHistoricalMap (CC0) Atlanta railway=tram ways,
                Overpass JSON with tags and geometry, from
                overpass-api.openhistoricalmap.org, bbox
                33.55,-84.65,34.05,-84.05. 1928 lines are traced from
                the 1928 Atlas of Atlanta and vicinity (Emory); dated
                1871-1920 lines from "The Trolley Titans".
  osm_det.json  OpenStreetMap streets for Detroit (fetched on first run,
                ODbL), used to trace tools/dsr_1941.csv.

Not used: Georgia DOT's HISTORIC_TROLLEY.gdb and the Georgia GIS
Clearinghouse ATLANTA_STREETCAR_1928 layer derived from it. GDOT's terms
forbid altering or transforming them without written consent.

Detroit has no historical vector data. tools/dsr_1941.csv lists the
streets with track on the December 1941 DSR rail map (Schramm
Collection, detroittransithistory.info), read by eye: each row is one
street and the cross streets it ran between. Each row is traced along
that street's own OSM ways, so the line cannot jump to another road.

Usage:
  python3 tools/build_trams.py SRC

Output: trams.js with TRAMS, a GeoJSON of lines; properties
  c city, y '1928' | '1941' | 'early', n line or street name,
  s/e start and end year (early lines), o operator, note.
"""

import csv
import heapq
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

OVERPASS = 'https://overpass-api.de/api/interpreter'
DET_BBOX = '42.25,-83.36,42.48,-82.90'

# Not tram streets: freeways, alleys, paths.
# Freeways stay: some old car streets (Davison) are freeways now.
SKIP_HW = {'motorway_link', 'service', 'footway', 'cycleway',
           'path', 'steps', 'track', 'construction', 'proposed', 'pedestrian'}

DIRS = {'east', 'west', 'north', 'south', 'e', 'w', 'n', 's'}
SUFFIX = {'avenue', 'ave', 'street', 'st', 'road', 'rd', 'boulevard', 'blvd',
          'highway', 'hwy', 'drive', 'dr', 'parkway', 'place', 'court'}
ALIAS = {'eight mile': '8 mile', 'seven mile': '7 mile', 'fourteenth': '14th'}

# Two streets "meet" without a shared OSM node if this close (metres).
NEAR = 150

# Breaks in today's street (rebuilt blocks, freeway crossings) up to this
# long are bridged with a straight line (Kercheval: ~650 m at the old
# Chrysler Jefferson plant).
GAP = 800
PREC = 5


def key(name):
    """Street name to a match key: 'West Grand Boulevard' -> 'grand'."""
    w = re.sub(r'[^a-z0-9 ]', ' ', name.lower()).split()
    if len(w) > 1 and w[0] in DIRS:
        w = w[1:]
    if len(w) > 1 and w[-1] in DIRS:
        w = w[:-1]
    if len(w) > 1 and w[-1] in SUFFIX:
        w = w[:-1]
    k = ' '.join(w)
    return ALIAS.get(k, k)


def dist(a, b):
    """Metres between two (lon, lat) points."""
    x = (b[0] - a[0]) * 111320 * math.cos(math.radians(a[1]))
    y = (b[1] - a[1]) * 110570
    return math.hypot(x, y)


def rnd(pts):
    return [[round(x, PREC), round(y, PREC)] for x, y in pts]


# --- Atlanta ----------------------------------------------------------

def atl_1928(path):
    """OHM lines traced from the 1928 atlas (no end date, start 1928)."""
    feats = []
    for e in json.load(open(path))['elements']:
        t = e.get('tags', {})
        if t.get('end_date') or not t.get('start_date', '').startswith('1928'):
            continue
        pts = rnd([(p['lon'], p['lat']) for p in e['geometry']])
        feats.append(feat({'c': 'Atlanta', 'y': '1928', 'n': t.get('name', '')}, [pts]))
    return feats


def atl_early(path):
    feats = []
    for e in json.load(open(path))['elements']:
        t = e.get('tags', {})
        if not t.get('end_date'):
            continue
        pts = rnd([(p['lon'], p['lat']) for p in e['geometry']])
        feats.append(feat({'c': 'Atlanta', 'y': 'early',
                           's': t.get('start_date', '')[:4],
                           'e': t['end_date'][:4],
                           'o': t.get('operator', '')}, [pts]))
    return feats


def feat(props, lines):
    return {'type': 'Feature', 'properties': props,
            'geometry': {'type': 'MultiLineString', 'coordinates': lines}}


# --- Detroit ----------------------------------------------------------

def read_spec(path):
    rows = []
    for r in csv.DictReader(open(path)):
        via = [v.strip() for v in r['via'].split(';') if v.strip()]
        rows.append((r['line'].strip(), r['street'].strip(), via, r['note'].strip()))
    return rows


def fetch_osm(path, names):
    """Named Detroit streets from Overpass, cached in path."""
    if os.path.exists(path):
        return json.load(open(path))

    words = sorted({key(n).split()[-1] for n in names})
    rx = '|'.join(re.escape(w) for w in words)
    q = ('[out:json][timeout:180];way[highway][name~"(%s)",i](%s);out body geom;'
         % (rx, DET_BBOX))
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({'data': q}).encode(),
                                 headers={'User-Agent': 'svi-map-build'})
    data = json.load(urllib.request.urlopen(req, timeout=240))
    json.dump(data, open(path, 'w'))
    return data


def index(osm):
    """{street key: [(node ids, coords)]} plus node coordinates."""
    streets, coord = {}, {}
    for w in osm['elements']:
        t = w.get('tags', {})
        if t.get('highway') in SKIP_HW or 'name' not in t:
            continue
        pts = [(p['lon'], p['lat']) for p in w['geometry']]
        for n, p in zip(w['nodes'], pts):
            coord[n] = p
        streets.setdefault(key(t['name']), []).append(w['nodes'])
    return streets, coord


def meets(a_ways, b_ways, coord):
    """Candidate nodes on street A where street B meets it."""
    a = {n for w in a_ways for n in w}
    b = {n for w in b_ways for n in w}
    shared = a & b
    if shared:
        return list(shared)

    # No shared node: the nearest A node within NEAR metres of B.
    best = None
    for n in a:
        for m in b:
            d = dist(coord[n], coord[m])
            if d < NEAR and (best is None or d < best[0]):
                best = (d, n)
    return [best[1]] if best else []


def graph(ways, coord):
    adj = {}
    for w in ways:
        for u, v in zip(w, w[1:]):
            d = dist(coord[u], coord[v])
            adj.setdefault(u, []).append((v, d))
            adj.setdefault(v, []).append((u, d))
    return adj


def reach(adj, src):
    """Dijkstra from src: (distances, predecessors)."""
    best, prev, q = {src: 0.0}, {}, [(0.0, src)]
    while q:
        d, u = heapq.heappop(q)
        if d > best[u]:
            continue
        for v, w in adj.get(u, []):
            if d + w < best.get(v, math.inf):
                best[v], prev[v] = d + w, u
                heapq.heappush(q, (d + w, v))
    return best, prev


def walk(prev, src, dst):
    out = [dst]
    while out[-1] != src:
        out.append(prev[out[-1]])
    return out[::-1]


def path(adj, coord, src, dst, hops=3):
    """Node ids along one street's own ways from src to dst.

    Where today's street is broken, jump the shortest gap (under GAP
    metres) toward dst and carry on, at most `hops` times.
    """
    best, prev = reach(adj, src)
    if dst in best:
        return walk(prev, src, dst)
    if hops == 0:
        return None

    # Closest pair between src's piece and dst's piece.
    other, _ = reach(adj, dst)
    x, y = min(((a, b) for a in best for b in other),
               key=lambda ab: dist(coord[ab[0]], coord[ab[1]]))
    if dist(coord[x], coord[y]) > GAP:
        # dst's piece is too far; try the piece nearest to dst instead.
        return None
    rest = path(adj, coord, y, dst, hops - 1)
    if rest is None:
        return None
    return walk(prev, src, x) + rest


def trace(street, via, streets, coord):
    """One spec row as a list of (lon, lat) lines, plus problems."""
    a = streets.get(key(street))
    if not a:
        return [], ['street not found: ' + street]

    # Pick, for each cross street, the meeting node nearest the last one.
    cands, probs = [], []
    for v in via:
        c = meets(a, streets.get(key(v), []), coord)
        if c:
            cands.append(c)
        else:
            probs.append('%s does not meet %s' % (v, street))
    if len(cands) < 2:
        return [], probs

    chosen = [min(cands[0], key=lambda n: min(dist(coord[n], coord[m]) for m in cands[1]))]
    for c in cands[1:]:
        chosen.append(min(c, key=lambda n: dist(coord[n], coord[chosen[-1]])))

    adj = graph(a, coord)
    lines, cur = [], []
    for u, v in zip(chosen, chosen[1:]):
        p = path(adj, coord, u, v)
        if p is None:
            probs.append('gap on %s' % street)
            if len(cur) > 1:
                lines.append(cur)
            cur = []
            continue
        seg = [coord[n] for n in p]
        cur = cur + seg[1:] if cur else seg
    if len(cur) > 1:
        lines.append(cur)
    return [rnd(l) for l in lines], probs


def detroit(spec_path, osm_path):
    rows = read_spec(spec_path)
    names = [r[1] for r in rows] + [v for r in rows for v in r[2]]
    streets, coord = index(fetch_osm(osm_path, names))

    feats = []
    for line, street, via, note in rows:
        lines, probs = trace(street, via, streets, coord)
        for p in probs:
            print('Detroit:', p)
        if not lines:
            continue
        props = {'c': 'Detroit', 'y': '1941', 'n': line, 'st': street,
                 'via': via[0] + ' to ' + via[-1]}
        if note:
            props['note'] = note
        feats.append(feat(props, lines))
    return feats


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    src = argv[0]
    here = os.path.dirname(__file__)

    feats = atl_1928(os.path.join(src, 'ohm_atl.json'))
    feats += atl_early(os.path.join(src, 'ohm_atl.json'))
    feats += detroit(os.path.join(here, 'dsr_1941.csv'), os.path.join(src, 'osm_det.json'))

    geo = {'type': 'FeatureCollection', 'features': feats}
    with open('trams.js', 'w') as out:
        out.write('// Generated by tools/build_trams.py. Do not edit.\n')
        out.write('var TRAMS=' + json.dumps(geo, separators=(',', ':')) + ';\n')

    by = {}
    for f in feats:
        k = f['properties']['c'] + ' ' + f['properties']['y']
        by[k] = by.get(k, 0) + 1
    print(by)


if __name__ == '__main__':
    main(sys.argv[1:])
