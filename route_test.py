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

import argparse #command line options

from web_export import export_web #writes the map data (network + vector tiles) into UrbanBlogs, see web_export/

#parse options first so a missing/wrong UrbanBlogs path fails right away, not after the slow network build
parser = argparse.ArgumentParser(description="Build the weighted NYC bike network and write the Bikeable Radius map data into an UrbanBlogs checkout.")
parser.add_argument("--urbanblogs", required=True, metavar="DIR",
                    help="path to your UrbanBlogs checkout (differs per machine). the map data is written to DIR/src/bike_network/")
parser.add_argument("--gpkg", default="NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_23_2026.gpkg",
                    help="LION GeoPackage to build the network from (default: %(default)s)")
args = parser.parse_args()

urbanblogs_dir = os.path.abspath(os.path.expanduser(args.urbanblogs))
if not os.path.isfile(os.path.join(urbanblogs_dir, ".eleventy.js")) or not os.path.isdir(os.path.join(urbanblogs_dir, "posts")):
    parser.error(f"--urbanblogs {args.urbanblogs!r} doesn't look like an UrbanBlogs checkout (no .eleventy.js and posts/ in {urbanblogs_dir})")
if not os.path.isfile(args.gpkg):
    parser.error(f"--gpkg {args.gpkg!r} not found")

#create layer for LION database with projected coordinate system
#reads geometry, attributes, and crs of gpkg
gdf = gpd.read_file(args.gpkg)

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
#replaces the old pydeck output. Exports the routing graph for the map page in UrbanBlogs
#(posts/nyc_directed_network.html), so pins, snapping, and the weight-radius search all run in the browser with no server.
#web_export packs it into a compact binary and draws it as vector tiles; the page's HTML/JS lives in UrbanBlogs.
#--------------------------------------------------------------------------

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
    'legend': [[hex_col, label] for hex_col, label in legend_items],  #legend rows on the map page, in order
}

#write the map data (packed network + vector tiles) into the UrbanBlogs checkout. the page itself
#(posts/nyc_directed_network.html) lives in UrbanBlogs and is edited there; this only replaces src/bike_network/
export_web(export, urbanblogs_dir, source=os.path.basename(args.gpkg))
