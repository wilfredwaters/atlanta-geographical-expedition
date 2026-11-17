# Atlanta Geographical Expedition

Leaflet map of social vulnerability using CDC/ATSDR SVI 2022: DeKalb
County, GA (201 tracts with scores, 203 total), Fulton (325/327) and
Clayton (69/70), GA, and Metro Detroit's Wayne (582/625; Detroit, site of
Bunge's 1968 expedition), Oakland (343/350) and Macomb (236/243), MI. Served by GitHub Pages from `main`: https://wilfredwaters.github.io/atlanta-geographical-expedition/

## Files

- `index.html` — the whole app (~1.5MB). Too big to read in one go: use
  grep, or read by line range.
- `SUMMARY.md` — method and findings, in plain language.
- `README.md` — project and Meetup context.
- `counties.js` — generated non-DeKalb data (`EXTRA_GEO`,
  `EXTRA_DATA`). Don't edit; rerun `tools/build_counties.py` (usage in
  its docstring). `--check` compares its output with DeKalb's `DATA`:
  199/201 match; 2 differ only in the order of exactly tied measures.

No build step, no package manager. Libraries load from CDNs.

## How index.html is built

Folium generated the base page; the generator script is not in the repo.
Folium variable names are hashed and must be used exactly:

| Name | What it is |
|---|---|
| `map_81f614882c315cc8a20dc059629ce4e3` | the Leaflet map |
| `layer_control_097befece45624d0ea761f79e99176c6` | layer control |
| `geo_json_bf9a23d19065cc6d2d806ecafd7be546` | SVI GeoJSON; per-tract properties live here |
| `choropleth_16a573e410c3036aa9f5ae79511ce959` | "Overall SVI" overlay |
| `geo_json_cbd8c3b3a785c6e242ed10f7b457e624` | "#1 structural driver" overlay |
| `geo_json_61cc50ef9183145099fdb1e3ebcef135` | "Click for details" overlay |

Hand-written code sits in the last `<script>` blocks:

- `var DATA={...}` — per-tract popup data keyed by 11-digit GEOID:
  `n` name, `r` score, `t` top 5 `[code, share%]`, `s` top 3 structural,
  `s3`, `ss` structural share, `q` measures reaching 25%, rates
  `[value, moe]` for MINRTY, POV150, UNINSUR, HBURD.
- GeoJSON properties hold `RPL_THEMES`, `share_<MEASURE>` (fractions),
  `struct1..3`, `top1..5`, `half` (north/south), `pop`.
- `popupHtml`, `explainText`, `aiUrl` build popups (`AI` lists the
  ChatGPT, Claude and Grok links); hover popups bind to
  every overlay in the layer control.
- The About panel is static HTML in `<div id="about">`.
- Non-DeKalb features are added to every overlay except
  `noHsGroup` in the block just above `NOHS_PRI`; `DATA` is extended with
  `EXTRA_DATA`. `CTY` maps the 5-digit county FIPS to name, state and
  mean structural share (DeKalb 70.5, Fulton 71.1, Wayne 66.5, Oakland
  62.6, Macomb 64.6, Clayton 74.7) for
  popups, explanations and the AI question. `CITY` groups the county
  buttons (top right) by city; each fits that county's bounds.
- `countyLayer` ("County boundaries" overlay, on by default):
  `COUNTY_LINES` outlines (black, weight 3.5) and names (`.cty-lbl`,
  white halo) in panes `ctyLines`/`ctyLabels`, which ignore the mouse. The legend (`#lg`) sits bottom right so
  the About panel doesn't cover it.

## No-diploma layer (`noHsGroup`)

DeKalb only. On by default and first in the layer list. Outlines only,
weight 4.

- Magenta `#e6007e`: `NOHS_PRI`, 11 tracts meeting all three tests —
  NOHSDP in top 3 structural drivers; `share_NOHSDP` ≥ county 75th
  percentile (0.073); `RPL_THEMES` above county median (0.582).
- Blue `#08519c`: `NOHS_CLU`, tracts holding Dunwoody cluster schools —
  212.10, 212.24, 212.29.

Both lists are hard-coded. Recompute them if the data changes.

Overall SVI ramp: `#ffffcc`, `#c2e699`, `#78c679`, `#238443`.

## Data limits

- The repo has no diploma rate; the share of the score is a proxy.
- Seat figures (673 unused, four of five cluster elementary schools) come
  from an undated DeKalb planning table.
- Assigning children to seats by tract could sort them partly by race,
  since the score includes minority status. Flag this; don't build it.

## Working rules

- Work on a branch. Send the changed `index.html` for review. Merge to
  `main` only on approval; merging publishes the site.
- After editing a script block, extract it and run `node --check`.
- Fewest words in replies, comments and commits. No praise.
- Don't touch code unrelated to the change. Minimize changed lines.
- Commits: subject ≤50 chars, capitalized, imperative, no period; blank
  line; body wrapped at 72, says what and why.
