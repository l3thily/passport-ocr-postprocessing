"""Tests for validity boundaries, checksum protection and OCR rejection."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import copy
import datetime as dt
import unittest
from core import *

class Rules(unittest.TestCase):
    def test_validity_and_grace_boundaries(self):
        f={'Birth_date':'01.01.2000','Issue_date':'01.02.2014'}
        birthday=dt.date(2020,1,1)
        self.assertTrue(valid_dates(f,birthday+dt.timedelta(days=90)))
        self.assertFalse(valid_dates(f,birthday+dt.timedelta(days=91)))
        f['Issue_date']='01.01.2020'
        self.assertTrue(valid_dates(f,dt.date(2026,10,1)))
        f['Issue_date']='01.01.2013'
        self.assertFalse(valid_dates(f))
        f['Issue_date']='02.10.2026'
        self.assertFalse(valid_dates(f))
        f={'Birth_date':'01.01.1980','Issue_date':'01.02.2000'}
        self.assertFalse(valid_dates(f))
        f['Issue_date']='01.01.2025'
        self.assertTrue(valid_dates(f))

    def test_date_parser_and_leap_day(self):
        self.assertIsNone(parse_date('31.02.2020'))
        self.assertIsNone(parse_date('1.2.2020'))
        self.assertEqual(anniversary(dt.date(2000,2,29),45),dt.date(2045,3,1))

    def fixture(self):
        f=next(load_jsonl('data/train_labels.jsonl'))['fields']
        r={'doc_id':'fixture','source':'mobile','quality':{'doc_px':1800,'sharpness':200,'glare':0},'viz':{}}
        for k in FIELDS:
            s=f[k]
            r['viz'][k]={'box':[0,0,500,30],'conf':.999,'lines':[{'box':[0,0,500,30],'text':s,'char_conf':[.999]*len(s)}]}
        r['mrz']={'lines':[{'text':s,'char_conf':[.999]*44} for s in [line1(f),line2(f)]]}
        return r

    def test_valid_document(self):
        r=self.fixture();self.assertIsNotNone(mrz_lines(r))
        self.assertEqual(Processor('.').process(r)[0]['decision'],'accept')

    def test_checksum_tampering(self):
        r=self.fixture();s=r['mrz']['lines'][1]['text']
        r['mrz']['lines'][1]['text']=str((int(s[0])+1)%10)+s[1:]
        self.assertIsNone(mrz_lines(r))
        self.assertEqual(Processor('.').process(r)[0]['decision'],'reject')

    def test_name_disagreement(self):
        r=self.fixture();s=r['viz']['First_name_ru']['lines'][0]['text']
        r['viz']['First_name_ru']['lines'][0]['text']='А'+s[1:]
        self.assertEqual(Processor('.').process(r)[1],'mrz_disagreement')

    def test_missing_rows(self):
        v={'box':[0,0,500,60],'conf':1,'lines':[{'box':[0,30,400,30],'text':'tail','char_conf':[1]*4}]}
        self.assertFalse(complete(v))
        v['lines'].append({'box':[0,0,400,30],'text':'head','char_conf':[1]*4})
        self.assertTrue(complete(v));self.assertEqual(text(v),'HEAD TAIL')

    def test_confidence_alignment(self):
        r=self.fixture();r['viz']['Birth_place_ru']['lines'][0]['char_conf'].pop()
        self.assertEqual(Processor('.').process(r)[0]['decision'],'reject')

    def test_preserve_foreign_places(self):
        self.assertEqual(normalize_field('Birth_place_ru','Г. DIMITROVO'),'Г. DIMITROVO')

    def test_unknown_source(self):
        r=self.fixture();r['source']='unseen_scanner'
        self.assertEqual(Processor('.').process(r)[1],'unknown_source')

if __name__=='__main__':unittest.main()
