"""Find registry points on actual valid image pixels; never auto-verify access."""
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.warp import transform
from rasterio.windows import Window
from .scene import read_json,digest

REFERENCE_PAGE = 'https://greener.bangkok.go.th/en/map-15-minute-garden/'
DON_MUEANG = '\u0e40\u0e02\u0e15\u0e14\u0e2d\u0e19\u0e40\u0e21\u0e37\u0e2d\u0e07'


def find_parks_in_image(tif_path, registry_path='data/registry/parks15.geojson', *, district=None):
    """Return WGS84 registry points inside valid pixels of ALL source bands.

    district='don-mueang' filters registry district metadata; it does not
    establish a district boundary or confirm park ownership/public access.
    """
    tif_path=Path(tif_path);registry=read_json(registry_path)
    if registry.get('type')!='FeatureCollection':raise ValueError('Registry GeoJSON required')
    district_name=DON_MUEANG if district=='don-mueang' else district
    features=[];excluded={'other_district':0,'invalid_point':0,'outside_image':0,'nodata':0};seen=set()
    with rasterio.open(tif_path) as src:
        if src.crs is None:raise ValueError('Source CRS is required')
        for original in registry['features']:
            props=original.get('properties') or {};geometry=original.get('geometry') or {}
            if district_name and district_name not in props.get('districts',[]):
                excluded['other_district']+=1;continue
            identity=str(original.get('id') or props.get('id') or '')
            if not identity or identity in seen:raise ValueError('Unique registry IDs required')
            seen.add(identity)
            try:
                if geometry.get('type')!='Point' or len(geometry.get('coordinates',[]))!=2:raise ValueError()
                lon,lat=map(float,geometry['coordinates'])
                if not (math.isfinite(lon) and math.isfinite(lat) and -180<=lon<=180 and -90<=lat<=90):raise ValueError()
                xs,ys=transform('EPSG:4326',src.crs,[lon],[lat]);row,col=src.index(xs[0],ys[0])
            except (ValueError,TypeError,OverflowError):
                excluded['invalid_point']+=1;continue
            if not (0<=row<src.height and 0<=col<src.width):
                excluded['outside_image']+=1;continue
            window=Window(col,row,1,1);values=src.read(window=window)
            if not (src.read_masks(window=window)!=0).all() or not np.isfinite(values).all():
                excluded['nodata']+=1;continue
            feature=deepcopy(original)
            feature['properties'].update(scene_id=tif_path.stem,registry_presence_confirmed=True,
                review_status='needs_review',verified_park=False,position_confirmed=False,public_access_confirmed=False,
                source_pixel=[col,row],reference_page=REFERENCE_PAGE)
            features.append(feature)
    return {'type':'FeatureCollection','scene_id':tif_path.stem,'source':registry.get('source',{}),
            'reference_page':REFERENCE_PAGE,'district_filter':district,'registry_sha256':digest(registry_path),
            'status':'registry_points_found_needing_review' if features else 'no_matching_registry_points_not_proof_no_parks',
            'excluded_counts':excluded,'features':features,
            'limitations':['District filter uses registry metadata, not a surveyed boundary.',
                           'Registry snapshot presence does not verify current location, entrance or public access.']}
