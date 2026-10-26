import copy
import unittest
from greensight.label_review import prepare_label_review,apply_label_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.labels={'target':'vegetation','features':[{'id':'a','geometry':{'type':'Polygon','coordinates':[]},
            'properties':{'scene_id':'s','source_window':[1,1,2,2],'source_crop':'s-01','class':'positive','split':'test','origin':'assistant_visual'}}]}

    def test_blank_queue_cannot_create_human_references(self):
        queue=prepare_label_review(self.labels)
        reviewed=apply_label_review(self.labels,queue)
        self.assertTrue(all(not v['features'] for v in reviewed.values()))

    def test_explicit_correction_keeps_original_and_test_split(self):
        original=copy.deepcopy(self.labels)
        queue=prepare_label_review(self.labels)
        queue['decisions'][0].update({'class':'negative','reviewer':'Test reviewer','reviewed_on':'2026-10-25','notes':'Fixture correction'})
        result=apply_label_review(self.labels,queue)
        self.assertEqual(self.labels,original)
        feature=result['test']['features'][0]
        self.assertEqual(feature['properties']['class'],'negative')
        self.assertEqual(feature['properties']['origin'],'human')
        self.assertEqual(feature['properties']['assistant_source']['class'],'positive')
        self.assertFalse(result['train']['features'])

    def test_missing_evidence_duplicate_unknown_and_uncertain(self):
        queue=prepare_label_review(self.labels)
        queue['decisions'][0]['class']='negative'
        with self.assertRaises(ValueError): apply_label_review(self.labels,queue)
        queue=prepare_label_review(self.labels)
        queue['decisions'].append(copy.deepcopy(queue['decisions'][0]))
        with self.assertRaises(ValueError): apply_label_review(self.labels,queue)
        queue['decisions']=[{'label_id':'unknown','class':None}]
        with self.assertRaises(ValueError): apply_label_review(self.labels,queue)
        queue=prepare_label_review(self.labels)
        queue['decisions'][0].update({'class':'uncertain','reviewer':'Test reviewer','reviewed_on':'2026-10-25','notes':'Unresolved'})
        self.assertFalse(apply_label_review(self.labels,queue)['test']['features'])
