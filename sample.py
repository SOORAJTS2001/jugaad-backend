
import geopandas as gpd
from shapely.geometry import Point

# Load the GeoJSON file
gdf = gpd.read_file("postcode_boundaries.geojson")
# Example coordinates
lat = 9.977633
lon = 76.2929212
point = Point(lon, lat)

# Ensure same coordinate reference system (CRS)
gdf = gdf.to_crs(epsg=4326)

# Find matching pincode
match = gdf[gdf.geometry.contains(point)]

if not match.empty:
    print("Matched Pincode:", match.iloc[0]['Pincode'])
    print("Office Name:", match.iloc[0]['Office_Name'])
else:
    print("No match found for given lat/lon.")

