import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from greensight.heatmap import make_heatmap
from greensight.pending import separate_pending
from greensight.scene import analyse_scene,write_json
from greensight.audit import audit_scene

class PendingTests(unittest.TestCase):
    def policy(self,grid):
        ring=[grid*p for p in ((10,5),(30,5),(30,25),(10,25),(10,5))]
        return {'purpose':'pending_review_areas','features':[{'geometry':transform_geom('EPSG:32647','EPSG:4326',{'type':'Polygon','coordinates':[ring]}),'properties':{'scene_id':'s','decision':'withhold_from_main_total'}}]}

    def test_partition_conserves_pixels_and_never_counts_pending_as_main(self):
        grid=from_origin(670000,1540000,1,1)
        mask=np.zeros((40,70),dtype='uint8');mask[5:25,10:50]=1;mask[0,:]=255
        original=mask.copy()
        result,pending,rgba,report=separate_pending(make_heatmap(mask,1),self.policy(grid),grid,'EPSG:32647',scene_id='s',pixel_m=1)
        self.assertEqual(report['pending_candidate_area_m2'],400)
        self.assertEqual(report['main_candidate_area_m2'],400)
        self.assertFalse(((pending==1)&(result['mask']==1)).any())
        self.assertFalse(result['rgba'][pending==1].any())
        self.assertFalse(rgba[pending!=1].any())
        np.testing.assert_array_equal(pending==255,mask==255)
        np.testing.assert_array_equal(mask,original)
        with self.assertRaises(ValueError):separate_pending(make_heatmap(mask,1),{},grid,'EPSG:32647',scene_id='s',pixel_m=1)

    def test_full_scene_pending_roundtrip_and_exhaustive_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);grid=from_origin(670000,1540000,1,1)
            data=np.full((4,40,70),100,dtype='uint16');data[3,5:25,10:50]=300;data[:,0,:]=65535
            with rasterio.open(root/'source.tif','w',driver='GTiff',width=70,height=40,count=4,dtype='uint16',nodata=65535,crs='EPSG:32647',transform=grid) as dst:dst.write(data)
            write_json(root/'context.json',{'features':[]})
            write_json(root/'pending.json',self.policy(grid))
            result=analyse_scene(root/'source.tif',root/'run'/'s',scene_id='s',red_band=3,nir_band=4,context_path=root/'context.json',pending_areas=root/'pending.json')
            self.assertEqual(result['stats']['retainedCandidateAreaM2'],400)
            self.assertEqual(result['pending_review']['pending_candidate_area_m2'],400)
            report=audit_scene(root/'run'/'s',root/'source.tif',context_path=root/'context.json',pending_path=root/'pending.json')
            self.assertEqual(report['source_pixels_checked'],2800)
            self.assertEqual(report['separate_pending_pixels'],400)
