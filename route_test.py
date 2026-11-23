import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import xml.etree.ElementTree as ET #process and build XML documents (parent class of KML)

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

from shapely.geometry import LineString, MultiLineString #import both types of Lines, multi and single
#MUST PIP INSTALL SHAPELY IN TERMINAL

import zipfile #unzip KMZ into KML

import os #access system environment

import folium
from folium.plugins import PolyLineTextPath #create visuals/map for directional streets
#MUST PIP INSTALL FOLIUM, MATPLOTLIB, MAPCLASSIFY IN TERMINAL

import math #calculate angles/trig

#create layer for LION database with projected coordinate system
#reads geometry, attributes, and crs of gpkg
gdf = gpd.read_file("NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_22_2026.gpkg")

print("CRS:", gdf.crs)
print("EPSG:", gdf.crs.to_epsg())
print("Units:", gdf.crs.axis_info[0].unit_name)
#EPSG:2263 - NAD83 / New York Long Island (ftUS)

#ensure geometries are strictly single LineStrings (explode MultiLineStrings)
gdf = gdf[gdf.geometry.type.isin(['LineString', 'MultiLineString'])].explode(index_parts=False)

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
    ' 10': class_1_weight * 0.75 + class_2_weight * 0.25, #combo class III and I
    ' 11': class_2_weight * 0.5 + class_3_weight * 0.5, #combo class III and II
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

#simplify geometry slightly (0.00001 deg ≈ 1 meter) to shrink HTML size
summary_edges['geometry'] = summary_edges['geometry'].simplify(0.00001)

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

# Assign distinct colors to each subclass present in the bounding box
subclass_palette = {
    'Class I (Protected)': '#006d2c',        #dark green
    'Combo I + II': '#2ca25f',               #medium green
    'Combo II + I': '#2ca25f',               #medium green
    'Combo I + III': '#2d8421',              #medium-dark green !
    'Combo III + I': '#2d8421',              #medium-dark green !
    'Class II (Painted Lane)': '#00ee5f',    #light green
    'Class II (Ped Bridge)': '#00ee5f',      #light green
    'Combo II + III': '#6feea1',             #sickly pale green
    'Combo III + II': '#6feea1',             #sickly pale green
    'Class III (Sharrow)': '#d95f02',        # orange
    'Mixed Traffic': '#969696' # gray
}

# Build ordered category list and matching color list for explore() legend
present_classes = sorted(summary_edges['subclass'].unique())
colors = [subclass_palette.get(c, '#000000') for c in present_classes]

#render the base map (1 polyline per street instead of 2)
m = summary_edges.explore(
    column='subclass',
    categories=present_classes,
    cmap=colors,
    legend=True,
    style_kwds={'weight': 3.5, 'opacity': 0.9},
    tooltip=['streetname', 'segment_id', 'subclass', 'flow_type', 'facility', 'weight'],
    tiles='OpenStreetMap',
    prefer_canvas=True
)

# mute colors of bg
mute_osm_css = """
<style>
.leaflet-tile-pane {
    filter: grayscale(75%) opacity(75%) contrast(55%);
}
</style>
"""
m.get_root().html.add_child(folium.Element(mute_osm_css))

#helper to compute bearing angle (in degrees) for a directional triangle marker
def get_midpoint_and_angle(geom, reverse=False):
    coords = list(geom.coords)
    if reverse:
        coords = coords[::-1]
    #find midpoint along the line
    mid_pt = geom.interpolate(0.5, normalized=True)
    #use start -> end vector for clean arrow orientation
    lon1, lat1 = coords[0]
    lon2, lat2 = coords[-1]
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    dy = lat2 - lat1
    #leaflet RegularPolygonMarker rotation: 0 deg points East, 90 points South
    angle = -math.degrees(math.atan2(dy, dx))
    return (mid_pt.y, mid_pt.x), angle

#add HTML/CSS rotated arrow markers for one-way segments
one_way_count = 0
for _, row in summary_edges.iterrows():
    if row['flow_type'] == 'One-Way':
        one_way_count += 1
        (lat, lon), angle = get_midpoint_and_angle(row.geometry, reverse=bool(row['reversed']))
        icon_html = f'''
            <div style="
                transform: rotate({angle:.1f}deg);
                color: #000000;
                font-size: 12px;
                font-weight: bold;
                line-height: 12px;
                text-align: center;
                text-shadow: -.75px -.75px 0 #fff, .75px -.75px 0 #fff, -.75px .75px 0 #fff, .75px .75px 0 #fff;
            ">➤</div>
        '''
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                icon_size=(12, 12),
                icon_anchor=(6, 6),
                html=icon_html
            )
        ).add_to(m)

m.save("directed_network_map.html")
print(f"Saved {len(bbox_edges)} directed edges to directed_network_map.html")