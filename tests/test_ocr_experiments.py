import unittest
from scripts.ocr_experiments import assign_lines, regions_for_page, error_analysis, preprocess, save_json


def line(number,text,x0,y0,x1,y1):
    return {'line_id':number,'text':text,'confidence':0.5,'needs_review':True,
            'polygon':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]}


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.regions=[{'clause_id':'C004','bbox':[0,10,100,30]},
                      {'clause_id':'C005','bbox':[0,50,100,70]}]

    def test_page_scope_and_verified(self):
        cs=[{'clause_id':'C001','page':1,'verification_status':'verified','source_blocks':[{'bbox':[1,2,3,4]}]},
            {'clause_id':'C004','page':2,'verification_status':'verified','source_blocks':[{'bbox':[1,2,3,4]}]}]
        self.assertEqual([r['clause_id'] for r in regions_for_page(cs,2)],['C004'])
        cs[1]['verification_status']='needs_review'
        with self.assertRaises(ValueError):regions_for_page(cs,2)

    def test_no_text_correction_or_confidence_filter(self):
        r=assign_lines([line(0,'부당 Ÿ',0,12,100,20)],self.regions,(100,100),(100,100))
        self.assertEqual(r['texts']['C004'],'부당 Ÿ\n')
        self.assertEqual(r['texts']['C005'],'')

    def test_coordinate_scaling(self):
        r=assign_lines([line(0,'가',0,24,200,40)],self.regions,(200,200),(100,100))
        self.assertEqual(r['texts']['C004'],'가\n')

    def test_scope_exclusions_recorded(self):
        r=assign_lines([line(0,'footer',0,90,100,98)],self.regions,(100,100),(100,100))
        self.assertEqual(len(r['excluded']),1)
        self.assertEqual(r['texts']['C004'],'')

    def test_table_left_label_before_right_text(self):
        r=assign_lines([line(0,'비용',40,12,90,20),line(1,'임대인',0,13,30,21)],self.regions,(100,100),(100,100))
        self.assertEqual(r['texts']['C004'],'임대인\n비용\n')

    def test_vertically_centered_table_label(self):
        # Real layout: label centered over two lines in the adjacent value cell.
        lines=[line(0,'first',40,103.5,90,113.5),line(1,'label',0,108,30,120),
               line(2,'second',40,116.5,90,125)]
        regions=[{'clause_id':'C004','bbox':[0,100,100,130]}]
        r=assign_lines(lines,regions,(100,150),(100,150))
        self.assertEqual(r['texts']['C004'],'label\nfirst\nsecond\n')

    def test_duplicates_not_silently_removed(self):
        r=assign_lines([line(0,'가',0,12,100,20),line(1,'가',0,12,100,20)],self.regions,(100,100),(100,100))
        self.assertEqual(r['texts']['C004'],'가\n가\n')

    def test_ambiguity_reported(self):
        regions=self.regions+[{'clause_id':'C006','bbox':[0,10,100,30]}]
        r=assign_lines([line(0,'가',0,12,100,20)],regions,(100,100),(100,100))
        self.assertEqual(len(r['ambiguous']),1)

    def test_preprocessing_does_not_modify_source(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow not installed')
        image=Image.new('RGB',(20,20),'white')
        image.putpixel((10,10),(100,100,100))
        before=image.tobytes()
        for method in ['baseline','resize_1.5','contrast_1.5','unsharp','grayscale','median_3']:
            with self.subTest(method=method):
                output=preprocess(image,method)
                self.assertIsNot(output,image)
                self.assertEqual(image.tobytes(),before)
                self.assertEqual(output.size,(30,30) if method=='resize_1.5' else (20,20))

    def test_output_overwrite_refused(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'result.json'
            save_json(p,{'original':True})
            before=p.read_bytes()
            with self.assertRaises(FileExistsError):save_json(p,{'original':False})
            self.assertEqual(p.read_bytes(),before)

    def test_critical_number_and_negation(self):
        refs={'C004':'2기 할 수 없다'};texts={'C004':'3기 할 수 있다'}
        a=error_analysis(refs,texts,{'C004':[]})
        self.assertTrue(any(d['term']=='numeric_tokens' for d in a['critical_differences']))
        self.assertTrue(any(d['term']=='할수없다' for d in a['critical_differences']))
        self.assertEqual(texts['C004'],'3기 할 수 있다')


if __name__=='__main__':unittest.main()
