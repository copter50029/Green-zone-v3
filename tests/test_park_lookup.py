import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform
from greensight.park_lookup import find_parks_in_image,DON_MUEANG

class ParkLookupTests(unittest.TestCase):
    def test_district_and_every_band_validity_without_auto_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);grid=from_origin(670000,1540000,1,1)
            data=np.ones((4,20,20),dtype='uint16');data[3,8,8]=65535
            with rasterio.open(root/'scene.tif','w',driver='GTiff',width=20,height=20,count=4,dtype='uint16',crs='EPSG:32647',transform=grid,nodata=65535) as dst:dst.write(data)
            features=[]
            for identifier,col,row,district in [('valid',5,5,DON_MUEANG),('other',6,6,'other'),('missing',8,8,DON_MUEANG),('outside',100,100,DON_MUEANG)]:
                x,y=grid*(col+.5,row+.5);lon,lat=transform('EPSG:32647','EPSG:4326',[x],[y])
                features.append({'type':'Feature','id':identifier,'geometry':{'type':'Point','coordinates':[lon[0],lat[0]]},'properties':{'districts':[district],'name':identifier}})
            registry=root/'parks.geojson';registry.write_text(json.dumps({'type':'FeatureCollection','features':features}))
            before=registry.read_bytes()
            result=find_parks_in_image(root/'scene.tif',registry,district='don-mueang')
            self.assertEqual([f['id'] for f in result['features']],['valid'])
            self.assertEqual(result['excluded_counts'],{'other_district':1,'invalid_point':0,'outside_image':1,'nodata':1})
            self.assertFalse(result['features'][0]['properties']['verified_park'])
            self.assertEqual(result['features'][0]['geometry'],features[0]['geometry'])
            self.assertEqual(registry.read_bytes(),before)
            self.assertEqual(len(find_parks_in_image(root/'scene.tif',registry)['features']),2)

    def test_empty_match_never_claims_no_parks_and_missing_crs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);registry=root/'parks.json'
            registry.write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            for name,crs in [('valid','EPSG:32647'),('missing',None)]:
                with rasterio.open(root/(name+'.tif'),'w',driver='GTiff',width=2,height=2,count=4,dtype='uint16',crs=crs,transform=from_origin(670000,1540000,1,1)) as dst:dst.write(np.ones((4,2,2),dtype='uint16'))
            result=find_parks_in_image(root/'valid.tif',registry)
            self.assertEqual(result['status'],'no_matching_registry_points_not_proof_no_parks')
            with self.assertRaises(ValueError):find_parks_in_image(root/'missing.tif',registry)
