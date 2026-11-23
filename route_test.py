import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import xml.etree.ElementTree as ET #process and build XML documents (parent class of KML)

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

from shapely.geometry import LineString, MultiLineString #import both types of Lines, multi and single
#MUST PIP INSTALL SHAPELY IN TERMINAL

import zipfile #unzip KMZ into KML

import os #access system environment

#create layer for LION database with projected coordinate system
#reads geometry, attributes, and crs of gpkg
gdf = gpd.read_file("NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_22_2026.gpkg")

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
gdf['multiplier'] = gdf['BikeLane'].map(lane_class_multipliers).fillna(class_4_weight)
gdf['length_m'] = gdf.geometry.length
gdf['weight'] = gdf['length_m'] * gdf['multiplier']

#apprx 183k linestrings
print(gdf.geom_type.value_counts())
print("Columns:", gdf.columns.tolist())
print(gdf.head(2).T)


#DONT FORGET DIRECTIONALITY!!!