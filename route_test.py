import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import xml.etree.ElementTree as ET #process and build XML documents (parent class of KML)

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

import shapely
from shapely.geometry import LineString, MultiLineString #import both types of Lines, multi and single
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

#build WebGL Layers

#line layer
#draw thinner mixed-traffic streets underneath and thick protected lanes on top
summary_edges = summary_edges.sort_values('width', ascending=True)

path_layer = pdk.Layer(
    "PathLayer",
    data=summary_edges[['path', 'color', 'width', 'streetname', 'subclass', 'flow_type', 'weight']],
    get_path="path",
    get_color="color",
    get_width="width",  #uses info above from width map
    width_min_pixels=1.2,
    width_max_pixels=10,
    pickable=True,
    auto_highlight=True
)

#arrow layer
arrow_layer = pdk.Layer(
    "TextLayer",
    data=arrows_df,
    get_position="pos",
    get_text="'➤'",
    get_angle="angle",
    get_size=12,
    get_color=[20, 20, 20, 220],
    size_units="'pixels'",
    billboard=False  #keeps arrows flat on the map plane so they rotate with streets
)

#render citywide map with muted Carto Positron basemap (built into pydeck w/o key needed)
view_state = pdk.ViewState(latitude=40.7128, longitude=-73.9600, zoom=11, pitch=0)
deck = pdk.Deck(
    layers=[path_layer, arrow_layer],
    initial_view_state=view_state,
    map_style="light",
    tooltip={
        #muted, greyed out, low opacity background
        "html": "<b>{streetname}</b><br/>Class: {subclass}<br/>Flow: {flow_type}<br/>Weight: {weight}",
        "style": {"backgroundColor": "white", "color": "black", "fontSize": "12px"}
    }
)

output_file = "nyc_directed_network.html"

deck.to_html(output_file)
print(f"Saved citywide WebGL map with {len(summary_edges)} segments and {len(arrows_df)} arrows.")

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
    <div style="border-top: 1px solid #ddd; margin-top: 7px; padding-top: 6px; display:flex; align-items:center;">
        <span style="font-weight:bold; margin-right:8px; font-size:13px;">➤</span>
        <span>One-Way Travel Direction</span>
    </div>
</div>
"""

# Inject the legend right before </body> in the generated HTML file
with open(output_file, "r", encoding="utf-8") as f:
    html_content = f.read()

html_content = html_content.replace("</body>", f"{legend_html}\n</body>")

with open(output_file, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Added corner legend to {output_file}")