import copy
import unittest
from scripts.ocr_region_review import row_groups, visual_candidates
from PIL import Image, ImageDraw


class RegionReviewTests(unittest.TestCase):
    def test_grouping_preserves_source(self):
        lines=[{'line_id':1,'polygon':[[2,2],[20,2],[20,12],[2,12]],'text':'부당'},
               {'line_id':2,'polygon':[[30,2],[50,2],[50,12],[30,12]],'text':'월'},
               {'line_id':3,'polygon':[[2,30],[20,30],[20,40],[2,40]],'text':'다음'}]
        original=copy.deepcopy(lines)
        groups=row_groups(lines)
        self.assertEqual(groups[0]['ids'],[1,2])
        self.assertEqual(groups[1]['ids'],[3])
        self.assertEqual(lines,original)

    def test_shapes_do_not_infer_checked_state_or_text(self):
        image=Image.new('RGB',(120,60),'white');d=ImageDraw.Draw(image)
        d.rectangle((10,10,25,25),outline='black',width=2)
        d.line((40,40,100,40),fill='black',width=2)
        result=visual_candidates(image)
        self.assertTrue(result['square_candidates'])
        self.assertTrue(result['horizontal_candidates'])
        self.assertTrue(all(x['checked'] is None for x in result['square_candidates']))
        self.assertNotIn('text',result)
