import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from greensight.exclusions import exclude_context
from greensight.scene import analyse_scene,write_json,read_json
from greensight.cleanup import clean_saved_results

class CleanupTests(unittest.TestCase):
    def test_cached_cleanup_preserves_grid_unknowns_and_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); registry=root/'registry.json'
            write_json(registry,{'type':'FeatureCollection','features':[]})
            data=np.full((4,70,100),100,dtype='uint16')
            data[3,10:40,5:35]=300
            data[3,20:30,70:80]=300
            data[3,25,35:70]=300
            data[:,:3,:]=65535
            with rasterio.open(root/'source.tif','w',driver='GTiff',width=100,height=70,count=4,dtype='uint16',nodata=65535,crs='EPSG:32647',transform=from_origin(670000,1540000,1,1)) as dst:dst.write(data)
            context=root/'context.json'
            geom={'type':'Polygon','coordinates':[[[670040,1539960],[670043,1539960],[670043,1539957],[670040,1539957],[670040,1539960]]]}
            write_json(context,{'features':[{'geometry':transform_geom('EPSG:32647','EPSG:4326',geom),'properties':{'tags':{'building':'house'}}}]})
            old=analyse_scene(root/'source.tif',root/'old'/'s',scene_id='s',red_band=3,nir_band=4,registry_path=registry,context_path=context)
            write_json(root/'old'/'summary-all.json',[old])
            summary_bytes=(root/'old/s/summary.json').read_bytes()
            result=clean_saved_results(root/'old',root/'new',clean_radius_m=2,registry_path=registry,contexts={'s':context},house_buffer_m=20)[0]
            self.assertLess(result['stats']['retainedCandidateAreaM2'],old['stats']['retainedCandidateAreaM2'])
            with rasterio.open(root/'old/s/candidate-mask.tif') as a,rasterio.open(root/'new/s/candidate-mask.tif') as b:
                self.assertEqual((a.crs,a.transform,a.shape),(b.crs,b.transform,b.shape))
                self.assertFalse(((b.read(1)==1)&(a.read(1)!=1)).any())
                np.testing.assert_array_equal(a.read(1)==255,b.read(1)==255)
            with rasterio.open(root/'old/s/candidate-mask.tif') as src:
                _,_,blocked=exclude_context(src.read(1),read_json(context),src.transform,src.crs,house_buffer_m=20,return_exclusion_mask=True)
            with rasterio.open(root/'new/s/heatmap.tif') as src:
                self.assertTrue((src.read(4)[blocked]==0).all())
            self.assertEqual(summary_bytes,(root/'old/s/summary.json').read_bytes())
            with self.assertRaises(FileExistsError):clean_saved_results(root/'old',root/'new',registry_path=registry)
