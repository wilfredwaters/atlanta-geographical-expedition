"""Build holc.js: 1930s HOLC redlining areas and their overlap with tracts.

Source: Mapping Inequality (Nelson, Winling et al., University of
Richmond Digital Scholarship Lab). Rasters and spatial data CC BY-NC;
maps and area descriptions public domain.

Inputs, downloaded into one folder (SRC):
  <CITY>.json                 static/citiesData/<CITY>/geojson.json
  ads/<CITY>/<label>.json     static/citiesData/<CITY>/areaDescriptions/<label>.json
  where CITY is GAAtlanta1938, MIDetroit1939, MIPontiac1937, under
  https://dsl.richmond.edu/panorama/redlining/
Plus Census cb_2022_13_tract_500k.shp and cb_2022_26_tract_500k.shp and
SVI_2022_US.csv (same sources as build_counties.py). Needs the duckdb CLI.

Usage:
  python3 tools/build_holc.py SRC SVI_2022_US.csv GA_TRACTS.shp MI_TRACTS.shp

Output: holc.js with
  HOLC_AREAS  GeoJSON of graded areas; properties hold the grade, label,
              name and the main area-description fields (see FIELDS)
  HOLC_TRACT  {GEOID: [covered share, HRS, A, B, C, D shares]}
  HOLC_STATS  per metro: tract count, Spearman rho of HRS against SVI and
              its four themes, mean SVI by dominant grade
"""

import csv
import json
import os
import subprocess
import sys
import tempfile

CITIES = {
    'GAAtlanta1938': ('Atlanta', 'GA', 'Atlanta', 19371001),
    'MIDetroit1939': ('Detroit', 'MI', 'Detroit', 1939),
    'MIPontiac1937': ('Detroit', 'MI', 'Pontiac', 19370203),
}
MI_URL = 'https://dsl.richmond.edu/panorama/redlining/map/{st}/{city}/area_descriptions/{lab}'

GRADES = ['A', 'B', 'C', 'D']
SCORE = {'A': 1, 'B': 2, 'C': 3, 'D': 4}

# A tract counts as graded once a fifth of it was graded (the NCRC /
# Mitchell & Franco "historic redlining score" convention).
MIN_COVER = 0.2

THEMES = ['RPL_THEMES', 'RPL_THEME1', 'RPL_THEME2', 'RPL_THEME3', 'RPL_THEME4']
MISSING = -999.0

# Area-description fields kept for popups, as paths into each form's JSON.
# Form numbers are Mapping Inequality's form_id.
FIELDS = {
    1939: {'name': '9.1', 'date': '9.4', 'occ': '1.b', 'foreign': '1.c',
           'negro': '1.d', 'infil': '1.e', 'mort': '6', 'remarks': '8'},
    19371001: {'name': '6.1', 'fav': '1.b', 'det': '1.c', 'trend': '1.e',
               'occ': '2.a', 'income': '2.b', 'foreign': '2.c',
               'negro': '2.d', 'infil': '2.e', 'relief': '2.f',
               'mort': '4.a', 'remarks': '5'},
    19370203: {'fav': '3', 'det': '4', 'occ': '5.a', 'income': '5.b',
               'foreign': '5.c', 'negro': '5.d', 'infil': '5.e',
               'relief': '5.f', 'mort': '12.a', 'trend': '13',
               'remarks': '14', 'date': '15'},
}

SQL = os.path.join(os.path.dirname(__file__), 'holc_overlap.sql')


def text(v):
    """Form value as one string: nested parts joined, blanks dropped."""
    if isinstance(v, dict):
        v = [text(x) for x in v.values()]
    if isinstance(v, list):
        return ', '.join(x for x in (text(x) for x in v) if x)
    return ' '.join(str(v).split())


def field(ad, path):
    """Value at a dotted path such as '2.d', or ''."""
    v = ad
    for k in path.split('.'):
        if not isinstance(v, dict) or k not in v:
            return ''
        v = v[k]
    return text(v)


def areas(src):
    """Graded HOLC polygons with their area-description fields."""
    feats = []
    for d, (metro, st, city, form) in CITIES.items():
        for f in json.load(open(os.path.join(src, d + '.json')))['features']:
            p = f['properties']
            if p['grade'] not in GRADES:
                continue

            lab = p['label']
            props = {'g': p['grade'], 'l': lab, 'c': city,
                     'n': (p.get('name') or '').strip(),
                     'u': MI_URL.format(st=st, city=city, lab=lab)}

            ad_path = os.path.join(src, 'ads', d, lab + '.json')
            if os.path.exists(ad_path):
                ad = json.load(open(ad_path))
                for k, path in FIELDS[form].items():
                    v = field(ad, path)
                    if v:
                        props[k] = v

            # Prefer the form's own name when the polygon has none; skip
            # names that only repeat the city ("Detroit, Mich.").
            form_name = props.pop('name', '')
            if not props['n'] and not form_name.startswith(city):
                props['n'] = form_name
            feats.append({'type': 'Feature', 'properties': props,
                          'geometry': f['geometry']})
    return {'type': 'FeatureCollection', 'features': feats}


def overlap(holc_path, ga, mi):
    """Run holc_overlap.sql; return {geoid: {grade: share}}."""
    out = holc_path + '.csv'
    sql = open(SQL).read()
    for k, v in {'@GA@': ga, '@MI@': mi, '@HOLC@': holc_path, '@OUT@': out}.items():
        sql = sql.replace(k, v)
    subprocess.run(['duckdb', '-c', sql], check=True)

    res = {}
    with open(out) as f:
        for r in csv.DictReader(f):
            res.setdefault(r['geoid'], {})[r['grade']] = float(r['share'])
    return res


def tract_row(sh):
    """[covered share, HRS, A, B, C, D] for one tract's grade shares."""
    cov = sum(sh.values())
    hrs = sum(SCORE[g] * s for g, s in sh.items()) / cov
    return [round(min(cov, 1.0), 3), round(hrs, 2)] + \
        [round(sh.get(g, 0.0), 3) for g in GRADES]


def ranks(xs):
    """Average ranks, ties shared."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(xs, ys):
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / (vx * vy) ** 0.5


def stats(tracts, svi):
    """Per metro: how HRS lines up with SVI in tracts that were graded."""
    res = {}
    for metro, st in [('Atlanta', '13'), ('Detroit', '26')]:
        rows = []
        for g, t in tracts.items():
            if not g.startswith(st) or t[0] < MIN_COVER or g not in svi:
                continue
            vals = [float(svi[g][k]) for k in THEMES]
            if MISSING in vals:
                continue
            rows.append((t, vals))

        hrs = [t[1] for t, _ in rows]
        rho = {k: round(spearman(hrs, [v[i] for _, v in rows]), 2)
               for i, k in enumerate(THEMES)}

        # Mean SVI by dominant grade: the grade covering most of the tract.
        by = {g: [] for g in GRADES}
        for t, v in rows:
            dom = GRADES[max(range(4), key=lambda i: t[2 + i])]
            by[dom].append(v[0])
        mean = {g: [len(x), round(sum(x) / len(x), 3) if x else None]
                for g, x in by.items()}

        res[metro] = {'n': len(rows), 'rho': rho, 'byGrade': mean}
    return res


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    src, svi_path, ga, mi = argv

    geo = areas(src)
    with open(svi_path, encoding='utf-8-sig') as f:
        svi = {r['FIPS']: r for r in csv.DictReader(f)}

    with tempfile.TemporaryDirectory() as tmp:
        holc_path = os.path.join(tmp, 'holc.geojson')
        json.dump(geo, open(holc_path, 'w'))
        shares = overlap(holc_path, ga, mi)

    tracts = {g: tract_row(sh) for g, sh in shares.items()}
    st = stats(tracts, svi)

    sep = (',', ':')
    with open('holc.js', 'w') as out:
        out.write('// Generated by tools/build_holc.py. Do not edit.\n')
        out.write('var HOLC_AREAS=' + json.dumps(geo, separators=sep) + ';\n')
        out.write('var HOLC_TRACT=' + json.dumps(tracts, separators=sep) + ';\n')
        out.write('var HOLC_STATS=' + json.dumps(st, separators=sep) + ';\n')
    print(len(geo['features']), 'areas,', len(tracts), 'tracts touched')
    print(json.dumps(st, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
