"""Tests for validity boundaries, checksum protection and OCR rejection."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import copy
import json
import math
import tempfile
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
        r=self.fixture()
        self.assertEqual(Processor('.').process(r),({'doc_id':'fixture','decision':'accept','fields':self.labels()},'accept'))

    def labels(self):
        return dict(next(load_jsonl('data/train_labels.jsonl'))['fields'])

    def test_checksum_tampering_without_visual_support(self):
        r=self.fixture();s=r['mrz']['lines'][1]['text']
        r['mrz']['lines'][1]['text']=str((int(s[0])+1)%10)+s[1:]
        line=r['viz']['Licence_number']['lines'][0];line['text']='7'+line['text'][1:]
        self.assertEqual(Processor('.').process(r)[1],'mrz_unverified')

    def test_failed_segment_restored_only_when_check_digits_agree(self):
        r=self.fixture();s=r['mrz']['lines'][1]['text']
        r['mrz']['lines'][1]['text']=str((int(s[0])+1)%10)+s[1:]
        answer,reason=Processor('.').process(r)
        self.assertEqual(reason,'accept');self.assertEqual(answer['fields'],self.labels())

    def test_mrz_constants_are_restored(self):
        r=self.fixture();s=r['mrz']['lines'][1]['text']
        r['mrz']['lines'][1]['text']=s[:10]+'RVS'+s[13:21]+'<<K<<<<'+s[28:]
        self.assertEqual(Processor('.').process(r)[1],'accept')

    def test_verified_mrz_overrides_visual_dates(self):
        r=self.fixture();line=r['viz']['Birth_date']['lines'][0]
        line['text']='10.06.2016'
        answer,reason=Processor('.').process(r)
        self.assertEqual(reason,'accept');self.assertEqual(answer['fields']['Birth_date'],'10.06.2010')

    def test_confident_name_disagreement(self):
        r=self.fixture();s=r['viz']['First_name_ru']['lines'][0]['text']
        r['viz']['First_name_ru']['lines'][0]['text']='А'+s[1:]
        self.assertEqual(Processor('.').process(r)[1],'name_disagreement')

    def test_doubtful_visual_letter_is_overruled_by_mrz(self):
        r=self.fixture();line=r['viz']['First_name_ru']['lines'][0]
        line['text']='А'+line['text'][1:];line['char_conf'][0]=.4
        answer,reason=Processor('.').process(r)
        self.assertEqual(reason,'accept');self.assertEqual(answer['fields']['First_name_ru'],self.labels()['First_name_ru'])

    def test_doubtful_mrz_letter_is_overruled_by_visual_zone(self):
        r=self.fixture();line=r['mrz']['lines'][0]
        line['text']=line['text'][:6]+'X'+line['text'][7:];line['char_conf'][6]=.4
        self.assertEqual(Processor('.').process(r)[1],'accept')
        line['char_conf'][6]=.999
        self.assertEqual(Processor('.').process(r)[1],'name_disagreement')

    def test_low_confidence_place_and_issuer(self):
        for key in ['Birth_place_ru','Issue_organization_ru']:
            r=self.fixture();r['viz'][key]['lines'][0]['char_conf'][3]=.9
            self.assertEqual(Processor('.',self.model(issuers={})).process(r)[1],'low_confidence_'+key)

    def test_mobile_v2_requires_saturated_confidence(self):
        r=self.fixture();r['source']='mobile_v2'
        self.assertEqual(Processor('.').process(r)[1],'low_confidence_Birth_place_ru')

    def test_grace_period_is_not_accepted(self):
        f={'Birth_date':'10.07.2006','Issue_date':'10.02.2021'}
        self.assertTrue(valid_dates(f));self.assertTrue(replacement_pending(f))
        self.assertFalse(replacement_pending({'Birth_date':'10.07.2006','Issue_date':'11.07.2026'}))

    def model(self,**changes):
        m={'schema_version':2,'policies':{s:{'min_conf':.95} for s in SOURCES},'names':{'trusted':.99,'doubtful':.9},'issuers':{}}
        m.update(changes);return m

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

    def test_nan_confidence_is_rejected(self):
        r=self.fixture();r['viz']['Last_name_ru']['conf']=float('nan')
        self.assertEqual(Processor('.').process(r)[1],'malformed_record')

    def test_invalid_character_probabilities(self):
        for value in [float('nan'),float('inf'),-0.1,1.1,True,'1']:
            with self.subTest(value=value):
                r=self.fixture();r['viz']['First_name_ru']['lines'][0]['char_conf'][0]=value
                self.assertEqual(Processor('.').process(r)[1],'malformed_record')

    def test_missing_name_and_mrz_confidences(self):
        for zone in ['viz','mrz']:
            r=self.fixture()
            line=r['viz']['Last_name_ru']['lines'][0] if zone=='viz' else r['mrz']['lines'][0]
            line['char_conf']=[]
            self.assertEqual(Processor('.').process(r)[1],'malformed_record')

    def test_bad_shapes_and_quality(self):
        for mutation in ['quality_nan','missing_viz','line_not_object','zero_height']:
            r=self.fixture()
            if mutation=='quality_nan':r['quality']['glare']=float('nan')
            if mutation=='missing_viz':r['viz']=None
            if mutation=='line_not_object':r['viz']['Last_name_ru']['lines']=['text']
            if mutation=='zero_height':r['viz']['Last_name_ru']['box'][3]=0
            self.assertEqual(Processor('.').process(r)[1],'malformed_record')

    def test_known_vector_not_generated_by_parser(self):
        f=self.labels()
        self.assertEqual(line1(f),'PNRUSZAINTINOV<<ZAKERIQ<NAZIFULOVI3<<<<<<<<<')
        self.assertEqual(line2(f),'6122839687RUS1006102M<<<<<<<4250911620004<28')
        self.assertEqual(checkdigit('612283968'),'7')
        self.assertEqual(translit('ЁЙЧШЩЪЬЭЮЯ'),'2Q34WX9678')

    def test_truncated_name_is_not_confirmed(self):
        r=self.fixture();name='А'*40
        r['viz']['Last_name_ru']['lines'][0]['text']=name
        r['viz']['Last_name_ru']['lines'][0]['char_conf']=[.999]*len(name)
        f={k:text(v) for k,v in r['viz'].items()}
        r['mrz']['lines'][0]['text']=line1(f)
        self.assertEqual(Processor('.').process(r)[1],'mrz_names_unreadable')

    def test_known_issuer_is_scoped_to_code(self):
        r=self.fixture();field=r['viz']['Issue_organization_ru'];line=field['lines'][0]
        line['char_conf']=[.5]*len(line['text'])
        org=self.labels()['Issue_organization_ru']
        self.assertEqual(Processor('.',self.model(issuers={'111-111':[org]})).process(r)[1],'low_confidence_Issue_organization_ru')
        self.assertEqual(Processor('.',self.model(issuers={'620-004':[org]})).process(r)[1],'accept')

    def test_known_issuer_corrects_only_doubtful_letters(self):
        p=Processor('.',self.model(issuers={'620-004':['ОВД АБВ']}))
        field={'box':[0,0,100,30],'conf':.9,'lines':[{'box':[0,0,100,30],'text':'ОВД АБГ','char_conf':[.99]*6+[.5]}]}
        self.assertEqual(p.known_issuer('620-004',field),'ОВД АБВ')
        field['lines'][0]['char_conf']=[.99]*7
        self.assertIsNone(p.known_issuer('620-004',field))

    def test_unknown_letters_not_silently_removed_from_numbers(self):
        self.assertNotEqual(normalize_field('Licence_number','61 24 283968XYZ'),'61 24 283968')
        self.assertNotEqual(normalize_field('Birth_date','10.06.2010XYZ'),'10.06.2010')
        self.assertEqual(normalize_field('Licence_number','61-24-283968'),'61 24 283968')

    def test_incomplete_model_fails_closed(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp:
            Path(tmp,'model.json').write_text('{"schema_version":2}')
            with self.assertRaises(ValueError):Processor(tmp)

    def test_invalid_model_probability_fails_closed(self):
        with self.assertRaises(ValueError):
            Processor('.',self.model(policies={s:{'min_conf':float('nan')} for s in SOURCES}))

if __name__=='__main__':unittest.main()
