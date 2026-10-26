import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom

from greensight.scene import analyse_scene, windows
from greensight.exclusions import exclude_context


class SceneTests(unittest.TestCase):
    def make_source(self, path, empty=False):
        data = np.full((4,53,71),100,dtype='uint16')
        data[3,10:30,10:30] = 300  # One 400 m2 patch crossing many windows.
        data[:,:3,:] = 65535
        if empty:
            data[:] = 65535
        grid = from_origin(670000,1540000,1,1)
        with rasterio.open(path,'w',driver='GTiff',width=71,height=53,count=4,dtype='uint16',crs='EPSG:32647',transform=grid,nodata=65535) as dst:
            dst.write(data)
        return grid

    def test_windows_cover_partial_edges_exactly_once(self):
        counts = np.zeros((53,71),dtype=int)
        for w in windows(71,53,16):
            counts[int(w.row_off):int(w.row_off+w.height),int(w.col_off):int(w.col_off+w.width)] += 1
        np.testing.assert_array_equal(counts,np.ones_like(counts))
        for invalid in (0,-1,True,1.5):
            with self.assertRaises(ValueError):
                list(windows(10,10,invalid))

    def test_global_filter_has_no_seams_and_preserves_all_valid_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            grid=self.make_source(root/'source.tif')
            args=dict(scene_id='test',red_band=3,nir_band=4)
            small=analyse_scene(root/'source.tif',root/'small',window_size=8,**args)
            large=analyse_scene(root/'source.tif',root/'large',window_size=64,**args)
            self.assertEqual(small['stats'],large['stats'])
            self.assertEqual(small['stats']['retainedCandidateAreaM2'],400)
            self.assertEqual(small['valid_area_m2'],50*71)
            self.assertEqual(small['crop_window'],[0,3,71,50])
            with rasterio.open(root/'small/raw-mask.tif') as src:
                mask=src.read(1)
                self.assertEqual(src.transform,grid)
                self.assertTrue((mask[:3,:]==255).all())
            with rasterio.open(root/'small/candidate-mask.tif') as first, rasterio.open(root/'large/candidate-mask.tif') as second:
                np.testing.assert_array_equal(first.read(),second.read())
                self.assertEqual(first.transform.f,grid.f-3)
            self.assertIsNone(small['real_accuracy'])
            self.assertEqual(json.loads((root/'small/status.json').read_text())['status'],'complete')

    def test_empty_scene_never_creates_fake_valid_pixels_or_halos(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.make_source(root/'source.tif',empty=True)
            result=analyse_scene(root/'source.tif',root/'out',scene_id='empty',red_band=3,nir_band=4,window_size=16)
            self.assertEqual(result['valid_area_m2'],0)
            self.assertEqual(result['stats']['retainedCandidateAreaM2'],0)
            with rasterio.open(root/'out/candidate-mask.tif') as src:
                self.assertEqual(int(src.read(1)[0,0]),255)
            with rasterio.open(root/'out/heatmap.tif') as src:
                self.assertFalse(src.read(4).any())

    def test_context_excludes_mapped_polygons_preserves_unknown_and_counts_once(self):
        grid=from_origin(670000,1540000,1,1)
        geometry={'type':'Polygon','coordinates':[[[670005,1539995],[670010,1539995],[670010,1539990],[670005,1539990],[670005,1539995]]]}
        wgs=transform_geom('EPSG:32647','EPSG:4326',geometry)
        mask=np.ones((20,20),dtype='uint8')
        mask[0,0]=255
        context={'features':[{'geometry':wgs,'properties':{'tags':{'building':'yes','landuse':'residential','access':'private'}}},
                             {'geometry':{'type':'Point','coordinates':[100,13]},'properties':{'tags':{'building':'yes'}}}]}
        result,report=exclude_context(mask,context,grid,'EPSG:32647',building_buffer_m=2)
        self.assertEqual(result[0,0],255)
        self.assertEqual(report['removed_candidate_m2']['residential'],0)
        self.assertEqual(report['removed_candidate_m2']['private_access'],0)
        self.assertGreater(report['removed_candidate_m2']['buildings'],25)
        self.assertEqual(report['skipped_non_polygon_or_invalid'],1)
        self.assertEqual(int((mask==1).sum())-int((result==1).sum()),sum(report['removed_candidate_m2'].values()))

    def test_house_context_removes_yard_and_returns_halo_clip(self):
        grid=from_origin(670000,1540000,1,1)
        geom={'type':'Polygon','coordinates':[[[670040,1539960],[670045,1539960],[670045,1539955],[670040,1539955],[670040,1539960]]]}
        context={'features':[{'geometry':transform_geom('EPSG:32647','EPSG:4326',geom),'properties':{'tags':{'building':'house'}}}]}
        mask=np.ones((100,100),dtype='uint8');mask[0,0]=255
        normal,_=exclude_context(mask,context,grid,'EPSG:32647')
        strict,report,blocked=exclude_context(mask,context,grid,'EPSG:32647',building_buffer_m=8,house_buffer_m=20,return_exclusion_mask=True)
        self.assertEqual(normal[42,58],1)
        self.assertEqual(strict[42,58],0)
        self.assertTrue(blocked[42,58])
        self.assertEqual(strict[90,90],1)
        self.assertEqual(strict[0,0],255)
        self.assertGreater(report['removed_candidate_m2']['house_context'],0)
        self.assertEqual(int((mask==1).sum())-int((strict==1).sum()),sum(report['removed_candidate_m2'].values()))

    def test_visual_area_policy_is_scene_specific_and_preserves_nodata(self):
        from greensight.exclusions import exclude_policy_areas
        grid=from_origin(670000,1540000,1,1)
        g={'type':'Polygon','coordinates':[[[670002,1539998],[670006,1539998],[670006,1539994],[670002,1539994],[670002,1539998]]]}
        policy={'target':'eligible_green','purpose':'area_exclusion','features':[{'geometry':transform_geom('EPSG:32647','EPSG:4326',g),'properties':{'scene_id':'a','class':'negative','policy_decision':'exclude_residential_context'}}]}
        mask=np.ones((10,10),dtype='uint8');mask[3,3]=255
        result,blocked=exclude_policy_areas(mask,policy,grid,'EPSG:32647',scene_id='a')
        self.assertTrue(blocked[4,4]);self.assertEqual(result[4,4],0)
        self.assertEqual(result[3,3],255);self.assertEqual(mask[4,4],1)
        other,none=exclude_policy_areas(mask,policy,grid,'EPSG:32647',scene_id='b')
        np.testing.assert_array_equal(other,mask);self.assertFalse(none.any())
        with self.assertRaises(ValueError):
            exclude_policy_areas(mask,{'target':'vegetation'},grid,'EPSG:32647',scene_id='a')


if __name__=='__main__':
    unittest.main()
