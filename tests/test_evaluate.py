import unittest
import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from greensight import evaluate_mask


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.grid=from_origin(670000,1540000,1,1)
        self.mask=np.array([[1,2],[0,0]],dtype='uint8')
        self.refs={'type':'FeatureCollection','target':'vegetation','features':[]}
        for row,category in ((0,'positive'),(1,'negative')):
            y=1540000-row
            geometry={'type':'Polygon','coordinates':[[[670000,y],[670002,y],[670002,y-1],[670000,y-1],[670000,y]]]}
            self.refs['features'].append({'type':'Feature','geometry':transform_geom('EPSG:32647','EPSG:4326',geometry),
                'properties':{'origin':'human','review_status':'reviewed','reviewer':'Synthetic test fixture',
                              'observed_on':'2026-10-25','region_id':f'fixture-{row}','split':'test','class':category}})

    def test_empty_real_references_never_return_fake_accuracy(self):
        result=evaluate_mask(self.mask,{'target':'vegetation','features':[]},self.grid,'EPSG:32647',target='vegetation')
        self.assertEqual(result['status'],'reviewed_labels_required')
        self.assertIsNone(result['metrics'])

    def test_abstentions_remain_visible_in_accuracy_and_recall(self):
        metrics=evaluate_mask(self.mask,self.refs,self.grid,'EPSG:32647',target='vegetation')['metrics']
        self.assertEqual(metrics['accuracy_including_abstentions'],0.75)
        self.assertEqual(metrics['classified_coverage'],0.75)
        self.assertEqual(metrics['positive_recall_including_abstentions'],0.5)
        self.assertEqual(metrics['abstained_reference_pixels'],1)

    def test_wrong_target_weak_labels_and_overlap_cannot_score(self):
        with self.assertRaises(ValueError):
            evaluate_mask(self.mask,self.refs,self.grid,'EPSG:32647',target='eligible_green')
        self.refs['features'][0]['properties']['origin']='weak_osm'
        with self.assertRaises(ValueError):
            evaluate_mask(self.mask,self.refs,self.grid,'EPSG:32647',target='vegetation')
        self.refs['features'][0]['properties']['origin']='human'
        self.refs['features'].append(self.refs['features'][0])
        with self.assertRaises(ValueError):
            evaluate_mask(self.mask,self.refs,self.grid,'EPSG:32647',target='vegetation')


if __name__=='__main__':
    unittest.main()
