import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from greensight.labels import validate_labels
from greensight.evaluate import evaluate_mask


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.grid=from_origin(670000,1540000,1,1)
        with rasterio.open(self.root/'scene.tif','w',driver='GTiff',width=150,height=100,count=4,dtype='uint16',crs='EPSG:32647',transform=self.grid,nodata=65535) as dst:
            dst.write(np.ones((4,100,150),dtype='uint16'))
        self.labels={'target':'vegetation','features':[self.feature('a',1,'train','positive'),self.feature('b',100,'test','uncertain')]}

    def tearDown(self):
        self.temp.cleanup()

    def feature(self,identifier,col,split,category):
        corners=[self.grid*xy for xy in ((col,1),(col+2,1),(col+2,3),(col,3),(col,1))]
        return {'type':'Feature','id':identifier,'geometry':transform_geom('EPSG:32647','EPSG:4326',{'type':'Polygon','coordinates':[corners]}),
                'properties':dict(scene_id='scene',region_id=identifier,split=split,**{'class':category},origin='assistant_visual',human_review_status='pending',
                    review_status='uncertain' if category=='uncertain' else 'assistant_reviewed',certainty='uncertain' if category=='uncertain' else 'high',
                    reviewer='assistant',interpretation='source core',observed_on='2026-10-25',source_window=[col,1,2,2],core_pixels=4,area_m2=4)}

    def test_uncertain_is_withheld_and_no_real_accuracy(self):
        result=validate_labels(self.labels,self.root)
        self.assertEqual((result['usable_assistant_labels'],result['withheld_uncertain']),(1,1))
        self.assertIsNone(result['real_accuracy'])

    def test_geometry_mismatch_rejected(self):
        self.labels['features'][0]['properties']['source_window'][0]=2
        with self.assertRaisesRegex(ValueError,'Geometry'):
            validate_labels(self.labels,self.root)

    def test_overlap_and_split_leakage_rejected(self):
        for col,split,message in ((1,'train','Overlapping'),(10,'test','too close')):
            with self.subTest(col=col):
                labels=copy.deepcopy(self.labels)
                labels['features'][1]=self.feature('b',col,split,'negative')
                with self.assertRaisesRegex(ValueError,message):
                    validate_labels(labels,self.root)

    def test_invalid_source_pixels_rejected(self):
        with rasterio.open(self.root/'scene.tif','r+') as dst:
            dst.write(np.full((1,1),65535,dtype='uint16'),indexes=2,window=rasterio.windows.Window(1,1,1,1))
        with self.assertRaisesRegex(ValueError,'Invalid source'):
            validate_labels(self.labels,self.root)

    def test_duplicate_ids_and_region_cross_split_rejected(self):
        for key in ('id','region_id'):
            labels=copy.deepcopy(self.labels)
            if key=='id': labels['features'][1]['id']='a'
            else: labels['features'][1]['properties']['region_id']='a'
            with self.assertRaises(ValueError):
                validate_labels(labels,self.root)

    def test_assistant_labels_cannot_be_used_as_human_accuracy(self):
        with self.assertRaisesRegex(ValueError,'human-reviewed'):
            evaluate_mask(np.zeros((100,150),dtype='uint8'),self.labels,self.grid,'EPSG:32647',target='vegetation')

    def test_empty_collection_and_nonfinite_gap_rejected(self):
        with self.assertRaises(ValueError):
            validate_labels({'target':'vegetation','features':[]},self.root)
        with self.assertRaises(ValueError):
            validate_labels(self.labels,self.root,minimum_split_gap_m=float('nan'))
