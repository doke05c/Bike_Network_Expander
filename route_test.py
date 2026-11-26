import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import xml.etree.ElementTree as ET #process and build XML documents (parent class of KML)

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

import shapely
from shapely.geometry import Point, LineString, MultiLineString #import both types of Lines, multi and single
                                                                #import Point
#MUST PIP INSTALL SHAPELY IN TERMINAL

import zipfile #unzip KMZ into KML

import os #access system environment

import folium
from folium.plugins import PolyLineTextPath #create visuals/map for directional streets
#MUST PIP INSTALL FOLIUM, MATPLOTLIB, MAPCLASSIFY IN TERMINAL

import math #calculate angles/trig

import pydeck as pdk #switched to pydeck to render arrows/line objects to html, should be more space-efficient
#MUST PIP INSTALL PYDECK

import pandas as pd #manip and edit tabular data
#MUST PIP INSTALL PANDAS

#create layer for LION database with projected coordinate system
#reads geometry, attributes, and crs of gpkg
gdf = gpd.read_file("NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_23_2026.gpkg")

print("CRS:", gdf.crs)
print("EPSG:", gdf.crs.to_epsg())
print("Units:", gdf.crs.axis_info[0].unit_name)
#EPSG:2263 - NAD83 / New York Long Island (ftUS)

#ensure geometries are strictly single LineStrings (explode MultiLineStrings)
gdf = gdf[gdf.geometry.type.isin(['LineString', 'MultiLineString'])].explode(index_parts=False)

#restrict columns to only necessary 
keep_cols = [
    'Street', 'SegmentID', 'NodeIDFrom', 'NodeIDTo',
    'TrafDir', 'BikeLane', 'BIKE_TRAFDIR',
    'POSTED_SPEED', 'Number_Travel_Lanes', 'StreetWidth_Min',
    'RW_TYPE', 'SegmentTyp', 'LBoro',
    'geometry'
]
gdf = gdf[keep_cols]

#SET BASE WEIGHTS, SUBJECT TO CHANGE
class_1_weight = 1.0 #class I bike lanes (full PBLs) are 'weight-free': they do not carry any added "difficulty" in moving thru the network
class_2_weight = 2.0 #class II bike lanes (painted lanes) will be considered 'twice as hard' to move thru compared to class I
class_3_weight = 5.0 #class III bike lanes (sharrows) will be considered '5x harder' to move thru compared to class I
class_4_weight = 8.0 #class IV is just a label used for internal consistency here.
                        #in this context, it refers to streets with NO signage of bike use at all. they will be considered
                        #'8x harder' to move thru compared to class I


#see documentation on how bike lane sub-classes convert to weight multipliers
lane_class_multipliers = {
    ' 1': class_1_weight, #C I
    ' 2': class_2_weight, #C II
    ' 3': class_3_weight, #C III
    ' 4': class_2_weight, #ped bridge
    ' 5': class_1_weight * 0.5 + class_2_weight * 0.5, #combo class I and II
    ' 6': class_2_weight * 0.5 + class_3_weight * 0.5, #combo class II and III
    # NO SEGMENTS OF SUB-CLASS 7, NO WEIGHT SYSTEM ASSIGNED
    ' 8': class_1_weight * 0.75 + class_3_weight * 0.25, #combo class I and III
    ' 9': class_1_weight * 0.5 + class_2_weight * 0.5, #combo class II and I
    '10': class_1_weight * 0.75 + class_3_weight * 0.25, #combo class III and I
    '11': class_2_weight * 0.5 + class_3_weight * 0.5, #combo class III and II
}

#map multipliers (default to default street if missing) and calculate final edge weight using length attribute
gdf['length_ft'] = gdf.geometry.length

#bike and road weights are separate
gdf['bike_mult'] = gdf['BikeLane'].map(lane_class_multipliers).fillna(class_4_weight)
gdf['bike_weight'] = gdf['length_ft'] * gdf['bike_mult']
gdf['road_weight'] = gdf['length_ft'] * class_4_weight

#make graph with NetworkX
G = nx.DiGraph()

for idx, row in gdf.iterrows():
    u, v = row['NodeIDFrom'], row['NodeIDTo']
    
    #accounting for directionality

    bike_dir = str(row.get('BIKE_TRAFDIR') or '').strip().upper()
    road_dir = str(row.get('TrafDir') or '').strip().upper()
    
    base_attrs = {
        'length': row['length_ft'],
        'segment_id': row.get('SegmentID'),
        'geometry': row.geometry
    }

    #direction 1: forward (from -> to segments) 
    if bike_dir in ('FT', 'TW'):
        G.add_edge(u, v, reversed=False, streetname=row.get('Street'), weight=row['bike_weight'], facility=row.get('BikeLane'), mode='bike_network', **base_attrs)
    elif road_dir in ('W', 'T', 'P'):
        G.add_edge(u, v, reversed=False, streetname=row.get('Street'), weight=row['road_weight'], facility='none', mode='mixed_traffic', **base_attrs)

    #direction 2: reverse (to -> from segments) 
    if bike_dir in ('TF', 'TW'):
        G.add_edge(v, u, reversed=True, streetname=row.get('Street'), weight=row['bike_weight'], facility=row.get('BikeLane'), mode='bike_network', **base_attrs)
    elif road_dir in ('A', 'T', 'P'):
        G.add_edge(v, u, reversed=True, streetname=row.get('Street'), weight=row['road_weight'], facility='none', mode='mixed_traffic', **base_attrs)

#apprx 183k linestrings
print(gdf.geom_type.value_counts())
print("Columns:", gdf.columns.tolist())
print(gdf.head(2).T)

#count nodes and edges
print(f"Nodes: {G.number_of_nodes()}, Directed Edges: {G.number_of_edges()}")

#check how many directed edges were created under each mode
from collections import Counter
modes = Counter(data['mode'] for _, _, data in G.edges(data=True))
print("Edge modes:", modes)


#print 5 sample bike_network edges and 5 mixed_traffic edges, and 5 sample protected bike network edges

print("--------STANDARD BIKE EDGES--------")

bike_edges = [(u, v, d) for u, v, d in G.edges(data=True) if d['mode'] == 'bike_network'][:5]
for u, v, d in bike_edges:
    print(f"{u} -> {v} | name: {repr(d['streetname'])} | facility: {repr(d['facility'])} | length: {d['length']:.1f} | weight: {d['weight']:.1f}")

print("--------MIXED TRAFFIC EDGES--------")

mixed_traffic_edges = [(u, v, d) for u, v, d in G.edges(data=True) if d['mode'] == 'mixed_traffic'][:5]
for u, v, d in mixed_traffic_edges:
    print(f"{u} -> {v} | name: {repr(d['streetname'])} | facility: {repr(d['facility'])} | length: {d['length']:.1f} | weight: {d['weight']:.1f}")

print("--------PROTECTED BIKE EDGES--------")

protected_bike_edges = [(u, v, d) for u, v, d in G.edges(data=True) if (d['mode'] == 'bike_network' and d['facility'] == ' 1')][:5]
for u, v, d in protected_bike_edges:
    print(f"{u} -> {v} | name: {repr(d['streetname'])} | facility: {repr(d['facility'])} | length: {d['length']:.1f} | weight: {d['weight']:.1f}")

print("--------BOND ST EDGES--------")

bond_check = [(u, v, d) for u, v, d in G.edges(data=True) if ('BOND' in d['streetname'].upper())][:200]
for u, v, d in bond_check:
    print(f"{u} -> {v} | name: {repr(d['streetname'])} | facility: {repr(d['facility'])} | length: {d['length']:.1f} | weight: {d['weight']:.1f}")

print("--------BIKE BLVD EDGES--------")

protected_bike_edges = [(u, v, d) for u, v, d in G.edges(data=True) if (d['mode'] == 'bike_network' and ((d['facility'] == ' 8') or (d['facility'] == '10')))]
for u, v, d in protected_bike_edges:
    print(f"{u} -> {v} | name: {repr(d['streetname'])} | facility: {repr(d['facility'])} | length: {d['length']:.1f} | weight: {d['weight']:.1f}")


#CREATE WEB VISUAL

#extract directed edges from NetworkX back into GeoDataFrame
edges_data = [
    {
        'u': u,
        'v': v,
        'reversed': d['reversed'],
        'segment_id': d.get('segment_id'),
        'streetname': d.get('streetname'),
        'weight': round(d['weight'], 1),
        'length': round(d['length'], 1),
        'mode': d['mode'],
        'facility': str(d['facility']).strip() if d['facility'] is not None else 'none',
        'geometry': d['geometry']
    }
    for u, v, d in G.edges(data=True)
]
edges_gdf = gpd.GeoDataFrame(edges_data, crs=gdf.crs)

#classify each physical segment as One-Way vs Two-Way in the graph
dir_counts = edges_gdf.groupby('segment_id')['u'].transform('count')
edges_gdf['flow_type'] = dir_counts.map({1: 'One-Way', 2: 'Two-Way'}).fillna('Other')

#restrict to local area (box) and reproject to WGS84 (EPSG:4326) for Leaflet/Folium
edges_wgs84 = edges_gdf.to_crs(epsg=4326)
bbox_edges = edges_wgs84.cx[-74.267937:-73.696085, 40.490691:40.920841].copy()

#collapse two-way segments into 1 line per physical street for fast rendering
summary_edges = (
    bbox_edges.sort_values('reversed')
    .groupby('segment_id', as_index=False)
    .agg({
        'geometry': 'first',
        'flow_type': 'first',
        'streetname': 'first',
        'mode': lambda x: ' / '.join(dict.fromkeys(x)),
        'facility': lambda x: ' / '.join(dict.fromkeys(x)),
        'weight': lambda x: ' | '.join(map(str, x)),
        'reversed': 'first',
        'u': 'first',
        'v': 'first'
    })
)
summary_edges = gpd.GeoDataFrame(summary_edges, geometry='geometry', crs="EPSG:4326")

#remove edges without geometry
summary_edges = summary_edges[~summary_edges.geometry.is_empty].copy()

#simplify geometry slightly (0.00001 deg ≈ 1 meter) to shrink HTML size
summary_edges['geometry'] = summary_edges['geometry'].simplify(0.00001)

#simplify precision to reduce decimal counts
summary_edges['geometry'] = shapely.set_precision(summary_edges['geometry'], grid_size=0.00001)

def label_subclass(fac_str):
    #extract the primary bike facility code if present (ignore 'none' unless both directions are 'none')
    parts = [p.strip() for p in fac_str.split('/') if p.strip() != 'none'] #remove silly spacing
    code = parts[0] if parts else 'none'
    
    subclass_names = {
        '1': 'Class I (Protected)',
        '2': 'Class II (Painted Lane)',
        '3': 'Class III (Sharrow)',
        '4': 'Class II (Ped Bridge)',
        '5': 'Combo I + II',
        '6': 'Combo II + III',
        '8': 'Combo I + III',
        '9': 'Combo II + I',
        '10': 'Combo III + I',
        '11': 'Combo III + II',
        'none': 'Mixed Traffic'
    }
    return subclass_names.get(code, f'Other ({code})')

summary_edges['subclass'] = summary_edges['facility'].apply(label_subclass)

#NOTE: PDK MAY NOT LIKE HEX CODES, TRY RGB IF HEX FAILS
# Assign distinct colors to each subclass present in the bounding box
subclass_palette = {
    'Class I (Protected)': [0, 109, 44],        # dark green
    'Combo I + II': [44, 162, 95],              # medium green
    'Combo II + I': [44, 162, 95],              # medium green
    'Combo I + III': [45, 132, 33],             # medium-dark green
    'Combo III + I': [45, 132, 33],             # medium-dark green
    'Class II (Painted Lane)': [0, 238, 95],    # light green
    'Class II (Ped Bridge)': [0, 238, 95],      # light green
    'Combo II + III': [111, 238, 161],          # sickly pale green
    'Combo III + II': [111, 238, 161],          # sickly pale green
    'Class III (Sharrow)': [217, 95, 2],        # orange
    'Mixed Traffic': [150, 150, 150],           # gray
}

#build colors for summary edges, gray defaults
summary_edges['color'] = summary_edges['subclass'].map(subclass_palette).apply(
    lambda c: c if isinstance(c, list) else [100, 100, 100]
)

class_1_thickness = 35 #set anchor thickness to class I lanes

#create width map for each lane type
width_map = {
    'Class I (Protected)': class_1_thickness,     #thickest highlight for protected bike lanes
    'Combo I + II': class_1_thickness * 0.67,
    'Combo II + I': class_1_thickness * 0.67,
    'Combo I + III': class_1_thickness * 0.76,
    'Combo III + I': class_1_thickness * 0.76,
    'Class II (Painted Lane)': class_1_thickness * 0.43,
    'Class II (Ped Bridge)': class_1_thickness * 0.43,
    'Combo II + III': class_1_thickness * 0.33,
    'Combo III + II': class_1_thickness * 0.33,
    'Class III (Sharrow)': class_1_thickness * 0.26,
    'Mixed Traffic': class_1_thickness * 0.15
}

#create width based on mapping above
summary_edges['width'] = summary_edges['subclass'].map(width_map).fillna(2)

#build path edges with restricted precision for PDK
decimal_count = 5
summary_edges['path'] = summary_edges.geometry.apply(
    lambda g: [[round(x, decimal_count), round(y, decimal_count)] for x, y in g.coords]
)

#extract midpoint & bearing angle for one-way directional arrows citywide
one_way = summary_edges[summary_edges['flow_type'] == 'One-Way'].copy()

def get_arrow_data(row):
    coords = row['path']
    if len(coords) < 2:
        return None
    if row['reversed']:
        coords = coords[::-1]
    mid_idx = len(coords) // 2
    mx, my = coords[mid_idx]
    lon1, lat1 = coords[0]
    lon2, lat2 = coords[-1]
    dx = (lon2 - lon1) * math.cos(math.radians(my))
    dy = lat2 - lat1
    #deck.gl TextLayer angle: counter-clockwise degrees from east
    angle = math.degrees(math.atan2(dy, dx))
    return {'pos': [mx, my], 'angle': round(angle, 1)}

arrow_records = [r for r in one_way.apply(get_arrow_data, axis=1) if r is not None]
arrows_df = pd.DataFrame(arrow_records)

#--------------------------------------------------------------------------
#INTERACTIVE WEIGHT-RADIUS MAP
#replaces the old pydeck output. Writes a standalone HTML file (MapLibre GL from a CDN) that also carries
#the routing graph, so pins, snapping, and the weight-radius search all run in the browser with no server.
#--------------------------------------------------------------------------
import json

#draw thinner mixed-traffic streets underneath and thick protected lanes on top
summary_edges = summary_edges.sort_values('width', ascending=True).reset_index(drop=True)

#---- graph data for the browser ----
#every physical segment gets: node it starts at (NodeIDFrom), node it ends at (NodeIDTo), and the weight of travelling
#forward (From -> To, same direction the geometry is drawn) and in reverse (To -> From). null = not allowed that way.
fwd = bbox_edges[~bbox_edges['reversed']].drop_duplicates('segment_id').set_index('segment_id')
rev = bbox_edges[bbox_edges['reversed']].drop_duplicates('segment_id').set_index('segment_id')
seg_ids = summary_edges['segment_id']

node_from = seg_ids.map(fwd['u']).fillna(seg_ids.map(rev['v']))  #reverse edges were stored as (To, From), so swap back
node_to   = seg_ids.map(fwd['v']).fillna(seg_ids.map(rev['u']))
w_fwd = seg_ids.map(fwd['weight'])
w_rev = seg_ids.map(rev['weight'])

#node ids -> small integers so the browser can use typed arrays
n_seg = len(summary_edges)
node_codes, _ = pd.factorize(pd.concat([node_from, node_to], ignore_index=True))
nf_idx, nt_idx = node_codes[:n_seg], node_codes[n_seg:]

name_codes, name_labels = pd.factorize(summary_edges['streetname'].fillna('').astype(str))
sub_codes, sub_labels = pd.factorize(summary_edges['subclass'])

def nan_to_none(series):
    return [None if pd.isna(x) else round(float(x), 1) for x in series]

export = {
    'multipliers': [class_1_weight, class_2_weight, class_3_weight, class_4_weight],
    'subs': [str(s) for s in sub_labels],
    'sub_colors': [subclass_palette.get(s, [100, 100, 100]) for s in sub_labels],
    'sub_widths': [float(width_map.get(s, 2)) for s in sub_labels],
    'names': [str(s) for s in name_labels],
    'nf': [int(x) for x in nf_idx],
    'nt': [int(x) for x in nt_idx],
    'wf': nan_to_none(w_fwd),
    'wr': nan_to_none(w_rev),
    'name': [int(x) for x in name_codes],
    'sub': [int(x) for x in sub_codes],
    'coords': [[v for pt in p for v in pt] for p in summary_edges['path']],  #flat [lon,lat,lon,lat,...]
}
data_json = json.dumps(export, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')

#define legend items
legend_items = [
    ("#006d2c", "Class I (Protected)"),
    ("#2d8421", "Combo I + III (Bike Boulevard)"),
    ("#2ca25f", "Combo I + II (Protected w/ Painted Sections)"),
    ("#00ee5f", "Class II (Painted / Ped Bridge)"),
    ("#6feea1", "Combo II + III (Painted w/ Sharrow Sections)"),
    ("#d95f02", "Class III (Sharrow)"),
    ("#969696", "Mixed Traffic (Class IV)"),
]

rows_html = "".join(
    f'<div style="display:flex;align-items:center;margin-bottom:5px;">'
    f'<span style="display:inline-block;width:16px;height:4px;background:{hex_col};margin-right:8px;border-radius:1px;"></span>'
    f'<span>{label}</span></div>'
    for hex_col, label in legend_items
)

legend_html = f"""
<div id="map-legend" style="
    position: fixed;
    bottom: 24px;
    left: 24px;
    z-index: 1000;
    background: rgba(255, 255, 255, 0.92);
    padding: 12px 14px;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 12px;
    color: #222;
    line-height: 1.4;
    pointer-events: auto;
">
    <div style="font-weight: 600; margin-bottom: 8px; font-size: 13px;">NYC Bike Network Classes</div>
    {rows_html}
</div>
"""

#HTML + JS for the page. plain (non-f) string so the JS braces are left alone; python only fills in the two placeholders.
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bike Network Expander: The Bikeable Radius</title>
<meta name="description" content="Begin exploring how infrastructural inequities plague New York City's cycling network, by seeing how far you could comfortably ride around your area.">
<link href="https://cdn.jsdelivr.net/npm/maplibre-gl@3/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@3/dist/maplibre-gl.js"></script>
<style>
  html, body { margin: 0; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  #topbar { position: fixed; top: 0; left: 0; right: 0; height: 40px; z-index: 2000; box-sizing: border-box;
            padding: 10px 16px; font-size: 14px; background: #fff; border-bottom: 1px solid #ddd; }
  #stage { position: fixed; top: 40px; left: 0; right: 0; bottom: 0; }
  #map { position: absolute; inset: 0; }
  #panel {
    position: absolute; top: 16px; left: 16px; z-index: 1000; width: 270px;
    background: rgba(255,255,255,0.94); padding: 12px 14px; border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25); font-size: 12px; color: #222; line-height: 1.4;
  }
  #panel h3 { margin: 0 0 6px; font-size: 13px; }
  #panel .row { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; gap: 8px; }
  #panel input[type=number] { width: 90px; padding: 3px 5px; font-size: 12px; }
  #panel input[type=range] { width: 100%; margin: 0; }
  #panel button { font-size: 12px; padding: 4px 10px; cursor: pointer; }
  #panel .muted { color: #666; }
  #panel .sw { display: inline-block; width: 14px; height: 4px; margin-right: 6px; border-radius: 1px; vertical-align: middle; }
  #classes table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  #classes td { padding: 1px 0; }
  #tip { position: absolute; display: none; z-index: 1100; pointer-events: none; background: #fff; color: #000; font-size: 12px; line-height: 1.4;
         padding: 6px 8px; border-radius: 4px; box-shadow: 0 1px 6px rgba(0,0,0,0.35); }
  #stats { margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd; min-height: 16px; }
</style>
</head>
<body>
<div id="topbar"><a href="/index">&larr; Back to Blog Homepage</a></div>

<div id="stage">

  <div id="map"></div>
  <div id="tip"></div>

  <div id="panel">
    <h3>Weight-radius explorer</h3>
    <div class="muted" id="hint">Loading network...</div>

    <div class="row">
      <label for="radiusNum" id="radiusLabel"><b>Weight radius</b></label>
      <span><input type="number" id="radiusNum" min="0" step="250" value="10000"> pts</span>
    </div>
    <input type="range" id="radiusRange" min="0" max="100000" step="250" value="10000">

    <div class="row">
      <label><input type="checkbox" id="oneway" checked> Obey one-way directions</label>
    </div>
    <div class="row">
      <label for="coreMode">Lit line color</label>
      <select id="coreMode"><option value="class">Class colors</option><option value="solid">Highlight color</option></select>
    </div>
    <div class="row">
      <label for="color">Halo / highlight color</label>
      <input type="color" id="color" value="#e6007a">
    </div>
    <div class="row">
      <button id="clear">Remove pin</button>
    </div>
    <div id="stats"></div>
    <div id="classes"></div>
  </div>

  __LEGEND_HTML__
</div>

<script>
const D = __DATA_JSON__;

// ==== CORE START (pure logic, no DOM / no deck.gl) ====
const N_SEG = D.nf.length;
const COS_LAT = Math.cos(40.7128 * Math.PI / 180);   //squash longitude so distances are ~isotropic around NYC
const FT_PER_DEG_LAT = 364000;                        //approx, only used for the on-screen stats

const NF = Int32Array.from(D.nf), NT = Int32Array.from(D.nt);
let N_NODE = 0;
for (let i = 0; i < N_SEG; i++) N_NODE = Math.max(N_NODE, NF[i] + 1, NT[i] + 1);

//weights: Infinity = can't travel that way
const RAW_WF = Float64Array.from(D.wf, x => x === null ? Infinity : x);
const RAW_WR = Float64Array.from(D.wr, x => x === null ? Infinity : x);
const WF = new Float64Array(N_SEG), WR = new Float64Array(N_SEG);
function setOneWay(obey) {
  for (let i = 0; i < N_SEG; i++) {
    const f = RAW_WF[i], r = RAW_WR[i];
    if (obey) { WF[i] = f; WR[i] = r; }
    else { WF[i] = f !== Infinity ? f : r; WR[i] = r !== Infinity ? r : f; }  //ignore one-ways: use the only weight we have both ways
  }
}
setOneWay(true);

//flat coordinate storage: segment i owns XY[COFF[i] .. COFF[i+1])  as lon,lat,lon,lat,...
const COFF = new Uint32Array(N_SEG + 1);
{ let tot = 0; for (let i = 0; i < N_SEG; i++) { COFF[i] = tot; tot += D.coords[i].length; } COFF[N_SEG] = tot; }
const XY = new Float64Array(COFF[N_SEG]);
for (let i = 0; i < N_SEG; i++) XY.set(D.coords[i], COFF[i]);
D.coords = null;

//cumulative length along a segment (in "degrees of latitude" units); L = total
function segCum(i) {
  const s = COFF[i], n = (COFF[i + 1] - s) >> 1;
  const cum = new Float64Array(n);
  for (let k = 1; k < n; k++) {
    const dx = (XY[s + 2 * k] - XY[s + 2 * k - 2]) * COS_LAT, dy = XY[s + 2 * k + 1] - XY[s + 2 * k - 1];
    cum[k] = cum[k - 1] + Math.hypot(dx, dy);
  }
  return cum;
}
const SEG_LEN = new Float64Array(N_SEG);
for (let i = 0; i < N_SEG; i++) { const c = segCum(i); SEG_LEN[i] = c.length ? c[c.length - 1] : 0; }

//adjacency (CSR). arc code = segment*2 + dir.  dir 0: leaves NF going forward, dir 1: leaves NT going in reverse
const HEAD = new Uint32Array(N_NODE + 1);
for (let i = 0; i < N_SEG; i++) { HEAD[NF[i] + 1]++; HEAD[NT[i] + 1]++; }
for (let n = 0; n < N_NODE; n++) HEAD[n + 1] += HEAD[n];
const ARCS = new Uint32Array(2 * N_SEG);
{
  const cur = HEAD.slice(0, N_NODE);
  for (let i = 0; i < N_SEG; i++) { ARCS[cur[NF[i]]++] = i * 2; ARCS[cur[NT[i]]++] = i * 2 + 1; }
}

class MinHeap {
  constructor() { this.k = []; this.v = []; this.topKey = 0; }
  get size() { return this.k.length; }
  push(key, val) {
    const k = this.k, v = this.v; let i = k.length; k.push(key); v.push(val);
    while (i > 0) { const p = (i - 1) >> 1; if (k[p] <= key) break; k[i] = k[p]; v[i] = v[p]; i = p; }
    k[i] = key; v[i] = val;
  }
  pop() {
    const k = this.k, v = this.v; const topK = k[0], topV = v[0];
    const lastK = k.pop(), lastV = v.pop(); const n = k.length;
    if (n > 0) {
      let i = 0;
      while (true) {
        let c = 2 * i + 1; if (c >= n) break;
        if (c + 1 < n && k[c + 1] < k[c]) c++;
        if (k[c] >= lastK) break;
        k[i] = k[c]; v[i] = v[c]; i = c;
      }
      k[i] = lastK; v[i] = lastV;
    }
    this.topKey = topK; return topV;
  }
}

//nearest point on any segment to (lon, lat). returns segment, t (0..1 along it), snapped lon/lat, distance in ft
function snap(lon, lat) {
  const px = lon * COS_LAT, py = lat;
  let bestD2 = Infinity, bi = -1, bk = 0, bu = 0, bqx = 0, bqy = 0;
  for (let i = 0; i < N_SEG; i++) {
    const s = COFF[i], e = COFF[i + 1];
    if (e - s < 4) continue;
    let ax = XY[s] * COS_LAT, ay = XY[s + 1];
    for (let j = s + 2; j < e; j += 2) {
      const bx = XY[j] * COS_LAT, by = XY[j + 1];
      const abx = bx - ax, aby = by - ay, len2 = abx * abx + aby * aby;
      let u = len2 > 0 ? ((px - ax) * abx + (py - ay) * aby) / len2 : 0;
      u = u < 0 ? 0 : (u > 1 ? 1 : u);
      const qx = ax + u * abx, qy = ay + u * aby;
      const d2 = (px - qx) * (px - qx) + (py - qy) * (py - qy);
      if (d2 < bestD2) { bestD2 = d2; bi = i; bk = (j - s) >> 1; bu = u; bqx = qx; bqy = qy; }
      ax = bx; ay = by;
    }
  }
  if (bi < 0) return null;
  const cum = segCum(bi), L = cum[cum.length - 1];
  const t = L > 0 ? (cum[bk - 1] + bu * (cum[bk] - cum[bk - 1])) / L : 0;
  return { seg: bi, t, lon: bqx / COS_LAT, lat: bqy, distFt: Math.sqrt(bestD2) * FT_PER_DEG_LAT };
}

//weighted shortest path from the snapped point. returns dist[] per node (Infinity = outside the radius B)
function dijkstra(start, B) {
  const dist = new Float64Array(N_NODE).fill(Infinity);
  const h = new MinHeap();
  const relax = (n, d) => { if (d <= B && d < dist[n]) { dist[n] = d; h.push(d, n); } };
  const s = start.seg, t = start.t;
  if (WF[s] !== Infinity) relax(NT[s], (1 - t) * WF[s]);   //leave the pin's segment out its far end
  if (WR[s] !== Infinity) relax(NF[s], t * WR[s]);         //...or out its near end
  while (h.size) {
    const u = h.pop(), d = h.topKey;
    if (d > dist[u]) continue;
    for (let a = HEAD[u]; a < HEAD[u + 1]; a++) {
      const arc = ARCS[a], i = arc >> 1, rev = arc & 1;
      const w = rev ? WR[i] : WF[i];
      if (w === Infinity) continue;
      relax(rev ? NF[i] : NT[i], d + w);
    }
  }
  return dist;
}

function mergeIntervals(iv) {
  const pairs = [];
  for (let j = 0; j < iv.length; j += 2) if (iv[j + 1] - iv[j] > 1e-9) pairs.push([iv[j], iv[j + 1]]);
  pairs.sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const p of pairs) {
    const last = out[out.length - 1];
    if (last && p[0] <= last[1] + 1e-9) last[1] = Math.max(last[1], p[1]);
    else out.push([p[0], p[1]]);
  }
  return out;
}

//which stretches of which segments are within budget B. returns [{i, a, b}] with a,b = fractions along the segment (0 = NodeIDFrom end)
function litSegments(dist, B, start) {
  const out = [];
  for (let i = 0; i < N_SEG; i++) {
    const iv = [];
    const wf = WF[i], wr = WR[i];
    if (wf !== Infinity) { const d = dist[NF[i]]; if (d < B) iv.push(0, Math.min(1, wf > 0 ? (B - d) / wf : 1)); }
    if (wr !== Infinity) { const d = dist[NT[i]]; if (d < B) iv.push(1 - Math.min(1, wr > 0 ? (B - d) / wr : 1), 1); }
    if (start && i === start.seg) {
      if (wf !== Infinity) iv.push(start.t, Math.min(1, start.t + (wf > 0 ? B / wf : 1)));
      if (wr !== Infinity) iv.push(Math.max(0, start.t - (wr > 0 ? B / wr : 1)), start.t);
    }
    if (!iv.length) continue;
    for (const [a, b] of mergeIntervals(iv)) out.push({ i, a, b });
  }
  return out;
}

//full polyline of segment i as [[lon,lat],...]
function segPath(i) {
  const s = COFF[i], e = COFF[i + 1], p = [];
  for (let k = s; k < e; k += 2) p.push([XY[k], XY[k + 1]]);
  return p;
}

//polyline of segment i between fractions a..b of its length
function clipPath(i, a, b) {
  if (a <= 1e-9 && b >= 1 - 1e-9) return segPath(i);
  const s = COFF[i], cum = segCum(i), n = cum.length, L = cum[n - 1];
  if (n < 2 || L === 0) return null;
  const da = a * L, db = b * L;
  const pointAt = d => {
    for (let k = 0; k < n - 1; k++) {
      if (d <= cum[k + 1] || k === n - 2) {
        const len = cum[k + 1] - cum[k];
        let f = len > 0 ? (d - cum[k]) / len : 0; f = f < 0 ? 0 : (f > 1 ? 1 : f);
        const x0 = XY[s + 2 * k], y0 = XY[s + 2 * k + 1], x1 = XY[s + 2 * k + 2], y1 = XY[s + 2 * k + 3];
        return [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f];
      }
    }
  };
  const out = [pointAt(da)];
  for (let k = 1; k < n - 1; k++) if (cum[k] > da && cum[k] < db) out.push([XY[s + 2 * k], XY[s + 2 * k + 1]]);
  out.push(pointAt(db));
  return out;
}
// ==== CORE END ====


// ==== MAP / UI ====
//everything is drawn with MapLibre's own line layers (no deck.gl), so the class colors can't get lost
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (x, d = 0) => x.toLocaleString(undefined, { maximumFractionDigits: d });
const rgbStr = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const EMPTY = { type: 'FeatureCollection', features: [] };

//only draw segments that still have 2+ points after simplification
const drawable = [];
for (let i = 0; i < N_SEG; i++) if (COFF[i + 1] - COFF[i] >= 4) drawable.push(i);

//line widths in pixels by zoom. class I is the thickest; the other classes are scaled down from it but never thinner than PX_MIN
const ZOOMS  = [9, 12, 14, 16, 18];
const PX_C1  = [1.4, 2.4, 3.8, 6.5, 10];
const PX_MIN = [0.8, 1.0, 1.3, 1.8, 2.4];
const MAX_W = Math.max(...D.sub_widths);
const widthExpr = (k, mult) => {
  const f = D.sub_widths[k] / MAX_W, e = ['interpolate', ['linear'], ['zoom']];
  ZOOMS.forEach((z, j) => e.push(z, Math.max(PX_MIN[j], PX_C1[j] * f) * mult));
  return e;
};
const CLASS_ORDER = D.subs.map((_, k) => k).sort((a, b) => D.sub_widths[a] - D.sub_widths[b]);   //thin first, thick drawn on top

function tipHtml(i) {
  const wf = RAW_WF[i], wr = RAW_WR[i];
  const w = x => x === Infinity ? '&ndash;' : fmt(x, 1);
  return `<b>${esc(D.names[D.name[i]])}</b><br/>Class: ${esc(D.subs[D.sub[i]])}<br/>Flow: ${wf !== Infinity && wr !== Infinity ? 'Two-Way' : 'One-Way'}<br/>Weight (fwd / rev): ${w(wf)} / ${w(wr)}`;
}

const map = new maplibregl.Map({
  container: 'map', style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  center: [-73.96, 40.7128], zoom: 11
});
map.addControl(new maplibregl.NavigationControl(), 'top-right');
new ResizeObserver(() => map.resize()).observe($('stage'));

let ready = false, pin = null, marker = null, queued = false, dragging = false, hoverSeg = -1, hoverQueued = false, lastMouse = null;
const budget = () => Math.max(0, parseFloat($('radiusNum').value) || 0);
const schedule = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; update(); }); };

map.on('load', () => {
  //insert our layers above ALL of the basemap's roads/fills/lines but still under its labels. (a label layer such as water names can sit
  //*before* the road layers in the style, so "under the first label" would leave the basemap streets painted on top of the bike lanes)
  const styleLayers = map.getStyle().layers;
  let lastGeometry = -1;
  styleLayers.forEach((l, j) => { if (l.type !== 'symbol') lastGeometry = j; });
  const sym = styleLayers.slice(lastGeometry + 1).find(l => l.type === 'symbol');
  const before = sym ? sym.id : undefined;
  console.log('bike layers inserted below basemap layer:', before || '(top of stack)');
  const hl = $('color').value;

  //one MultiLineString per bike class: the whole network is only a handful of features
  const feats = D.subs.map((_, k) => ({ type: 'Feature', properties: { k }, geometry: { type: 'MultiLineString', coordinates: [] } }));
  for (const i of drawable) feats[D.sub[i]].geometry.coordinates.push(segPath(i));
  map.addSource('net', { type: 'geojson', data: { type: 'FeatureCollection', features: feats.filter(f => f.geometry.coordinates.length) }, maxzoom: 15, tolerance: 0.5 });
  for (const id of ['lit', 'hover', 'snap']) map.addSource(id, { type: 'geojson', data: EMPTY, maxzoom: 15, tolerance: 0.5 });

  const addLine = (id, source, paint, filter) => {
    const layer = { id, type: 'line', source, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint };
    if (filter) layer.filter = filter;
    map.addLayer(layer, before);
  };
  //draw order, bottom to top: halo, network (class colors), lit lines, hovered street, pin link + snap point
  addLine('glow-outer', 'lit', { 'line-color': hl, 'line-width': 30, 'line-blur': 18, 'line-opacity': 0.35 });
  addLine('glow-mid',   'lit', { 'line-color': hl, 'line-width': 12, 'line-blur': 6,  'line-opacity': 0.6 });
  for (const k of CLASS_ORDER) addLine(`net-${k}`, 'net', { 'line-color': rgbStr(D.sub_colors[k]), 'line-width': widthExpr(k, 1) }, ['==', ['get', 'k'], k]);
  for (const k of CLASS_ORDER) addLine(`lit-${k}`, 'lit', { 'line-color': rgbStr(D.sub_colors[k]), 'line-width': widthExpr(k, 1.7) }, ['==', ['get', 'k'], k]);
  addLine('hover', 'hover', { 'line-color': '#000000', 'line-width': 5, 'line-opacity': 0.7 });
  addLine('snap-link', 'snap', { 'line-color': '#3c3c3c', 'line-width': 2 }, ['==', ['geometry-type'], 'LineString']);
  map.addLayer({ id: 'snap-pt', type: 'circle', source: 'snap', filter: ['==', ['geometry-type'], 'Point'],
    paint: { 'circle-radius': 7, 'circle-color': '#ffffff', 'circle-stroke-width': 3, 'circle-stroke-color': hl } }, before);

  ready = true;
  $('hint').textContent = 'Click the map to drop a pin. Drag the pin, or click somewhere else, to move it.';
  update();
});

//halo color / lit-line color mode (cheap: no re-search)
function applyColors() {
  if (!ready) return;
  const hl = $('color').value, solid = $('coreMode').value === 'solid';
  map.setPaintProperty('glow-outer', 'line-color', hl);
  map.setPaintProperty('glow-mid', 'line-color', hl);
  map.setPaintProperty('snap-pt', 'circle-stroke-color', hl);
  for (const k of CLASS_ORDER) map.setPaintProperty(`lit-${k}`, 'line-color', solid ? hl : rgbStr(D.sub_colors[k]));
}

function updateReach() {   //unit helper: shown as a hover tip on the "Weight radius" label
  const B = budget(), m = D.multipliers;
  $('radiusLabel').title = `${fmt(B)} pts buys a straight run of about ${fmt(B / m[0] / 5280, 2)} mi on Class I, ${fmt(B / m[1] / 5280, 2)} mi Class II, ${fmt(B / m[2] / 5280, 2)} mi Class III, or ${fmt(B / m[3] / 5280, 2)} mi unmarked street`;
}

function update() {
  updateReach();
  if (!ready) return;
  if (!pin) {
    map.getSource('lit').setData(EMPTY); map.getSource('snap').setData(EMPTY);
    $('stats').textContent = ''; $('classes').innerHTML = ''; return;
  }
  const t0 = performance.now();
  const B = budget();
  const sn = snap(pin.lng, pin.lat);
  if (!sn) return;
  const dist = dijkstra(sn, B);
  const lit = litSegments(dist, B, sn);

  const miles = new Float64Array(D.subs.length);
  const byClass = D.subs.map(() => []);
  for (const { i, a, b } of lit) {
    const k = D.sub[i];
    miles[k] += (b - a) * SEG_LEN[i] * FT_PER_DEG_LAT / 5280;
    const p = clipPath(i, a, b);
    if (p && p.length >= 2) byClass[k].push(p);
  }
  let nodes = 0; for (let n = 0; n < N_NODE; n++) if (dist[n] !== Infinity) nodes++;

  map.getSource('lit').setData({ type: 'FeatureCollection',
    features: byClass.map((coords, k) => ({ type: 'Feature', properties: { k }, geometry: { type: 'MultiLineString', coordinates: coords } })).filter(f => f.geometry.coordinates.length) });
  map.getSource('snap').setData({ type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[pin.lng, pin.lat], [sn.lon, sn.lat]] } },
    { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [sn.lon, sn.lat] } } ] });

  //per-class mileage inside the radius (fixed order, thickest class first, so rows stay put between pin drops)
  const order = [...CLASS_ORDER].reverse();
  let total = 0; for (const m of miles) total += m;
  const rows = order.map(k => `<tr style="opacity:${miles[k] > 0.005 ? 1 : 0.4}"><td><span class="sw" style="background:${rgbStr(D.sub_colors[k])}"></span>${esc(D.subs[k])}</td><td style="text-align:right">${fmt(miles[k], 2)} mi</td></tr>`).join('');
  $('classes').innerHTML = `<table>${rows}<tr style="border-top:1px solid #ddd"><td><b>Total in radius</b></td><td style="text-align:right"><b>${fmt(total, 2)} mi</b></td></tr></table>`;
  $('stats').innerHTML =
    `Pin snapped <b>${fmt(sn.distFt)} ft</b> onto <b>${esc(D.names[D.name[sn.seg]])}</b> (${esc(D.subs[D.sub[sn.seg]])})<br>` +
    `${fmt(lit.length)} street pieces lit, ${fmt(nodes)} intersections reached <span class="muted">(${fmt(performance.now() - t0)} ms)</span>`;
}

//hover: find the street nearest the cursor ourselves (same snap() as the pin), so thin lines are easy to hit
const HOVER_PX = 8;
function setHover(i) {
  hoverSeg = i;
  map.getSource('hover').setData(i < 0 ? EMPTY : { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: segPath(i) } });
}
function hideTip() {
  $('tip').style.display = 'none';
  if (ready && hoverSeg >= 0) setHover(-1);
}
function onHover() {
  hoverQueued = false;
  if (!ready || !lastMouse || dragging) return;
  const { lngLat, point } = lastMouse;
  const s = snap(lngLat.lng, lngLat.lat);
  const ftPerPx = 78271.517 * Math.cos(lngLat.lat * Math.PI / 180) / Math.pow(2, map.getZoom()) * 3.28084;   //MapLibre: 512px tiles
  if (!s || s.distFt > HOVER_PX * ftPerPx) { hideTip(); return; }
  const tip = $('tip');
  tip.innerHTML = tipHtml(s.seg);
  tip.style.display = 'block';
  tip.style.left = Math.min(point.x + 14, window.innerWidth - 260) + 'px';
  tip.style.top = (point.y + 14) + 'px';
  if (hoverSeg !== s.seg) setHover(s.seg);
}
map.on('mousemove', e => { lastMouse = e; if (!hoverQueued) { hoverQueued = true; requestAnimationFrame(onHover); } });
map.on('movestart', hideTip);
map.getCanvas().addEventListener('mouseleave', () => { lastMouse = null; hideTip(); });

function placePin(ll) {
  pin = { lng: ll.lng, lat: ll.lat };
  if (!marker) {
    marker = new maplibregl.Marker({ draggable: true }).setLngLat(ll).addTo(map);
    const moved = () => { const p = marker.getLngLat(); pin = { lng: p.lng, lat: p.lat }; schedule(); };
    marker.on('dragstart', () => { dragging = true; hideTip(); });
    marker.on('drag', moved); marker.on('dragend', () => { dragging = false; moved(); });
  } else marker.setLngLat(ll);
  $('hint').textContent = 'Drag the pin, or click somewhere else, to move it.';
  schedule();
}

map.on('click', e => {
  if (e.originalEvent.target.closest('.maplibregl-marker')) return;
  placePin(e.lngLat);
});

$('radiusNum').addEventListener('input', () => { $('radiusRange').value = Math.min(budget(), +$('radiusRange').max); schedule(); });
$('radiusRange').addEventListener('input', () => { $('radiusNum').value = $('radiusRange').value; schedule(); });
$('oneway').addEventListener('change', () => { setOneWay($('oneway').checked); schedule(); });
$('color').addEventListener('input', applyColors);
$('coreMode').addEventListener('change', applyColors);
$('clear').addEventListener('click', () => { if (marker) marker.remove(); marker = null; pin = null; schedule(); });
updateReach();
</script>
</body>
</html>
'''

output_file_path = "/home/doke30/urban_blogs/UrbanBlogs/posts/nyc_directed_network.html"
page = HTML_TEMPLATE.replace('__LEGEND_HTML__', legend_html).replace('__DATA_JSON__', data_json)
with open(output_file_path, "w", encoding="utf-8") as f:
    f.write(page)

print(f"Saved interactive map with {n_seg} segments to {output_file_path}")