import networkx as nx #backbone of graph/network analysis uses NetworkX
#MUST PIP INSTALL NETWORKX IN TERMINAL

import xml.etree.ElementTree as ET #process and build XML documents (parent class of KML)

import geopandas as gpd #works out geometry of kml file, loads data
#MUST PIP INSTALL GEOPANDAS IN TERMINAL

from shapely.geometry import LineString, MultiLineString #import both types of Lines, multi and single
#MUST PIP INSTALL SHAPELY IN TERMINAL

import zipfile #unzip KMZ into KML

import os #access system environment

os.environ["OGR_KML_MAX_XML_SIZE"] = "0" #remove KML/KMZ max size

#extract KML from KMZ, load into geopandas
kmz_path = "NYC_Bike_Lanes_in_Full_LION_Network_edited_for_URBP7873D_Nov_22_2026.kmz"
with zipfile.ZipFile(kmz_path, 'r') as zipped:
    kml_filename = [file for file in zipped.namelist() if file.endswith('.kml')][0]
    extracted_kml = zipped.extract(kml_filename) #extract KML into direct file into directory


#convert KML records to GPKG, line by line to not overwhelm memory limit
records = []
for event, elem in ET.iterparse(extracted_kml, events=("end",)):
    if elem.tag.endswith("Placemark"):
        row = {}
        name_el = elem.find(".//{*}name")
        if name_el is not None:
            row["Name"] = name_el.text

        # Grab all attribute fields from ExtendedData / SimpleData
        for sd in elem.findall(".//{*}SimpleData"):
            row[sd.attrib.get("name")] = sd.text
        for d in elem.findall(".//{*}Data"):
            val_el = d.find("{*}value")
            if val_el is not None:
                row[d.attrib.get("name")] = val_el.text

        lines = []
        for coords_el in elem.findall(".//{*}LineString/{*}coordinates"):
            if coords_el.text:
                pts = [
                    tuple(map(float, c.split(",")[:2]))
                    for c in coords_el.text.strip().split()
                ]
                if len(pts) >= 2:
                    lines.append(LineString(pts))

        if len(lines) == 1:
            row["geometry"] = lines
            records.append(row)
        elif len(lines) > 1:
            row["geometry"] = MultiLineString(lines)
            records.append(row)

        elem.clear()

#create layer for LION database with projected coordinate system
gdf = gpd.GeoDataFrame(geometry=records, crs="EPSG:3857") #use web-mercator projection (3857), not wgs84 (4326)

gdf.to_file("lion_bike_lanes.gpkg", driver="GPKG") #make geopackage file, this will be used now
print(gdf.geom_type.value_counts())
