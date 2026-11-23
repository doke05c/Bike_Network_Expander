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

print(gdf.geom_type.value_counts())
