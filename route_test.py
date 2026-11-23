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
        'weight': round(d['weight'], 1),
        'length': round(d['length'], 1),
        'mode': d['mode'],
        'facility': str(d['facility']).strip() if d['facility'] is not None else 'none',
        'geometry': d['geometry']
    }
    for u, v, d in G.edges(data=True)
]
edges_gdf = gpd.GeoDataFrame(edges_data, crs=gdf.crs)

# HANDLE DIRECTIONALITY
#classify each physical segment as one way vs two way in the graph
#counts how many directed edges exist per segment_id
dir_counts = edges_gdf.groupby('segment_id')['u'].transform('count')
edges_gdf['flow_type'] = dir_counts.map({1: 'One-Way', 2: 'Two-Way'}).fillna('Other')

#restrict to local area (box)
#reproject to WGS84 (EPSG:4326) for Leaflet/Folium
edges_wgs84 = edges_gdf.to_crs(epsg=4326)
bbox_edges = edges_wgs84.cx[-73.988:-73.972, 40.685:40.697].copy()

#create base explore map colored by mode or flow_type
map = bbox_edges.explore(
    column='mode',
    cmap=['#1f77b4', '#999999'],  # Blue = bike_network, Gray = mixed_traffic
    style_kwds={'weight': 3, 'opacity': 0.85},
    tooltip=['segment_id', 'u', 'v', 'flow_type', 'mode', 'facility', 'weight'],
    tiles='CartoDB positron'
)

#overlay directional arrows (►) following the u -> v traversal order
for _, row in bbox_edges.iterrows():
    coords = [(lat, lon) for lon, lat in row.geometry.coords]
    
    is_rev = bool(row['reversed'])
    if is_rev:
        coords = coords[::-1]

    line = folium.PolyLine(coords, weight=0, opacity=0).add_to(map)
    PolyLineTextPath(
        line,
        '   ►   ',
        repeat=True,
        offset=-4 if is_rev else 6,
        attributes={
            'fill': '#d62728' if row['flow_type'] == 'One-Way' else '#2ca02c',
            'font-weight': 'bold',
            'font-size': '12'
        }
    ).add_to(map)

map.save("directed_network_map.html")
print(f"Saved {len(bbox_edges)} directed edges to directed_network_map.html")