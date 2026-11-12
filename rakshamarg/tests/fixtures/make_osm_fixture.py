"""Write the synthetic Overpass-format fixture used for dry runs (NOT real OSM data; never ship it as a snapshot)."""
import json, math, sys
els, ids, nid = [], {}, 1
def node(i, lat, lon): els.append({"type": "node", "id": i, "lat": lat, "lon": lon}); return i
for i in range(7):
    for j in range(14): ids[i, j] = node(nid, 25.32 + i * 0.04 + 0.004 * math.sin(j), 81.62 + j * 0.04); nid += 1
w = [1]
def way(nodes, tags): els.append({"type": "way", "id": w[0], "nodes": nodes, "tags": tags}); w[0] += 1
for i in range(7):
    if i != 3: way([ids[i, j] for j in range(14)], {"highway": "secondary" if i % 2 else "tertiary"})
way([ids[3, j] for j in range(14)], {"highway": "trunk", "ref": "NH19", "oneway": "yes", "lit": "no"})
wb = [node(9000 + j, 25.4415 + 0.004 * math.sin(j), 81.62 + j * 0.04) for j in range(14)]
way(wb[::-1], {"highway": "trunk", "ref": "NH19", "oneway": "yes"}); way([wb[0], ids[3, 0]], {"highway": "trunk_link", "ref": "NH19"}); way([wb[13], ids[3, 13]], {"highway": "trunk_link", "ref": "NH19"})
west, east = node(9100, 25.44, 81.57), node(9101, 25.44, 82.17)
way([ids[3, 0], west], {"highway": "trunk", "ref": "NH19", "oneway": "yes"}); way([ids[3, 13], east], {"highway": "trunk", "ref": "NH19", "oneway": "yes"})
for j in range(14): way([ids[i, j] for i in range(7)], {"highway": "tertiary" if j % 3 else "primary", **({"hgv": "no"} if j == 4 else {})})
json.dump({"version": 0.6, "osm3s": {"timestamp_osm_base": "SYNTHETIC-FIXTURE"}, "elements": els}, open(sys.argv[1], "w"))
