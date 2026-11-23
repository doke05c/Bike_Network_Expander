import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

from shapely.geometry import LineString
#MUST PIP INSTALL SHAPELY IN TERMINAL

import zipfile #unzip KMZ into KML

import os #access system environment

os.environ["OGR_KML_MAX_XML_SIZE"] = "0" #remove KML/KMZ max size

#extract KML from KMZ, load into geopandas
kmz_path = "NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_22_2026.kmz"
with zipfile.ZipFile(kmz_path, 'r') as zipped:
    kml_filename = [file for file in zipped.namelist() if file.endswith('.kml')][0]
    extracted_kml = zipped.extract(kml_filename) #extract KML into direct file into directory

gdf = gpd.read_file(extracted_kml, use_arrow=True)
print(gdf.geom_type.value_counts())
