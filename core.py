"""Offline OCR postprocessing. Standard library only; no network or subprocesses."""
import csv
import datetime as dt
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

FIELDS = ['Last_name_ru', 'First_name_ru', 'Middle_name_ru', 'Sex_ru',
          'Birth_date', 'Birth_place_ru', 'Issue_date', 'Issue_organisation_code',
          'Licence_number', 'Issue_organization_ru']
AS_OF = dt.date(2026, 10, 1)
TRANSLIT = dict(zip('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                    ['A','B','V','G','D','E','2','J','Z','I','Q','K','L','M','N','O','P','R','S','T','U','F','H','C','3','4','W','X','Y','9','6','7','8']))
DIGITS = str.maketrans({'О':'0','O':'0','З':'3','Ч':'4','Б':'6','В':'8','B':'8','S':'5','I':'1','L':'1'})

def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

def valid_box(box):
    return (isinstance(box, list) and len(box) == 4
            and all(finite_number(x) for x in box)
            and box[2] > 0 and box[3] > 0)

def valid_line(line, require_box):
    if not isinstance(line, dict):
        return False
    value, probs = line.get('text'), line.get('char_conf')
    return (isinstance(value, str) and bool(value.strip())
            and isinstance(probs, list) and len(probs) == len(value)
            and all(finite_number(p) and 0 <= p <= 1 for p in probs)
            and (not require_box or valid_box(line.get('box'))))

def valid_record(record):
    """Fail closed on missing, misaligned or non-finite model outputs."""
    if not isinstance(record, dict):
        return False
    viz, quality = record.get('viz'), record.get('quality')
    if not isinstance(viz, dict) or not isinstance(quality, dict):
        return False
    if not all(k in viz for k in FIELDS):
        return False
    if not all(finite_number(quality.get(k)) for k in ['doc_px','sharpness','glare']):
        return False
    if quality['doc_px'] <= 0 or quality['sharpness'] < 0 or not 0 <= quality['glare'] <= 1:
        return False
    for field in viz.values():
        if field is None:
            continue
        if not isinstance(field, dict) or not valid_box(field.get('box')):
            return False
        conf = field.get('conf')
        if not finite_number(conf) or not 0 <= conf <= 1:
            return False
        ls = field.get('lines')
        if not isinstance(ls, list) or not ls or not all(valid_line(line, True) for line in ls):
            return False
    mrz = record.get('mrz')
    if mrz is not None:
        if not isinstance(mrz, dict) or not isinstance(mrz.get('lines'), list):
            return False
        if not all(valid_line(line, False) for line in mrz['lines']):
            return False
    return True

def norm(value):
    return ' '.join(str(value or '').split()).upper()

def tokens(value):
    return re.findall('[А-ЯЁ]+', norm(value))

def translit(value):
    return ''.join(TRANSLIT.get(c, '<' if c in ' -' else c) for c in norm(value))

def lines(field):
    return sorted(field.get('lines', []), key=lambda x: (x.get('box',[0,0,0,0])[1],x.get('box',[0,0,0,0])[0])) if field else []

def text(field):
    return norm(' '.join(x.get('text','') for x in lines(field)))

def complete(field):
    """A field box taller than its detected lines indicates missing OCR rows."""
    ls=lines(field)
    if not ls:return False
    heights=[x.get('box',[0,0,0,0])[3] for x in ls]
    if min(heights)<=0:return False
    h=statistics.median(heights)
    if field.get('box',[0,0,0,0])[3] > h*(len(ls)+.25):return False
    ys=[x['box'][1] for x in ls]
    if len(ls)>1 and any(b-a>1.65*h or b-a<.4*h for a,b in zip(ys,ys[1:])):return False
    return True

def confidence(field):
    ls=lines(field)
    if not ls:return 0.0
    cs=[]
    for l in ls:
        s=l.get('text','');c=l.get('char_conf',[])
        if len(s)!=len(c) or any(not isinstance(x,(int,float)) or not 0<=x<=1 for x in c):return 0.0
        cs.extend(c)
    return min(cs) if cs else 0.0

def checkdigit(s):
    vals=[0 if c=='<' else int(c) if c.isdigit() else ord(c)-55 for c in s]
    return str(sum(v*(7,3,1)[i%3] for i,v in enumerate(vals))%10)

def parse_date(s):
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}',s):return None
    try:return dt.datetime.strptime(s,'%d.%m.%Y').date()
    except ValueError:return None

def anniversary(birth,years):
    try:return birth.replace(year=birth.year+years)
    except ValueError:return dt.date(birth.year+years,3,1)

def valid_dates(fields, as_of=AS_OF):
    birth=parse_date(fields.get('Birth_date',''));issue=parse_date(fields.get('Issue_date',''))
    if not birth or not issue or issue>as_of or birth>issue or issue<anniversary(birth,14):return False
    if issue<dt.date(1997,10,1):return False
    for age in (20,45):
        birthday=anniversary(birth,age)
        if issue<birthday and as_of>birthday+dt.timedelta(days=90):return False
    return True

def name_payload(fields):
    name=translit(fields['Last_name_ru'])+'<<'+translit(fields['First_name_ru'])
    if fields['Middle_name_ru']:name+='<'+translit(fields['Middle_name_ru'])
    return 'PNRUS'+name

def line1(fields):
    return name_payload(fields).ljust(44,'<')[:44]

def line2(fields):
    num=re.sub(r'\s','',fields['Licence_number'])
    b=parse_date(fields['Birth_date']);i=parse_date(fields['Issue_date'])
    if not b or not i or not re.fullmatch(r'\d{10}',num):return None
    serial=num[:3]+num[4:]
    optional=num[3]+i.strftime('%y%m%d')+fields['Issue_organisation_code'].replace('-','')+'<'
    if len(optional)!=14:return None
    s=serial+checkdigit(serial)+'RUS'+b.strftime('%y%m%d')+checkdigit(b.strftime('%y%m%d'))
    s+=('M' if fields['Sex_ru']=='МУЖ.' else 'F')+'<'*7+optional+checkdigit(optional)
    return s+checkdigit(s[:10]+s[13:20]+s[21:43])

def mrz_lines(record):
    raw=(record.get('mrz') or {}).get('lines',[])
    if len(raw)!=2:return None
    a,b=[norm(x.get('text','')) for x in raw]
    if len(a)!=44 or len(b)!=44 or not a.startswith('PNRUS') or b[10:13]!='RUS':return None
    if not re.fullmatch('[A-Z0-9<]{44}',a) or not re.fullmatch('[A-Z0-9<]{44}',b):return None
    if not (b[:9].isdigit() and b[13:19].isdigit() and b[28:41].isdigit() and b[20] in 'MF'):return None
    # Check all four available checksums, including the composite checksum.
    if any(checkdigit(s)!=cd for s,cd in [(b[:9],b[9]),(b[13:19],b[19]),(b[28:42],b[42]),(b[:10]+b[13:20]+b[21:43],b[43])]):return None
    if b[21:28]!='<'*7 or b[41]!='<':return None
    return a,b

def edit_distance(a,b,limit=3):
    if abs(len(a)-len(b))>limit:return limit+1
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        if min(row)>limit:return limit+1
        prev=row
    return prev[-1]

def normalize_field(key,s):
    s=norm(s)
    if key in ['Birth_date','Issue_date']:
        s=s.translate(DIGITS)
        if not re.fullmatch(r'[0-9 .-]+',s):return s
        digits=re.sub(r'\D','',s)
        if len(digits)==8:s=digits[:2]+'.'+digits[2:4]+'.'+digits[4:]
    elif key=='Issue_organisation_code':
        s=s.translate(DIGITS)
        if not re.fullmatch(r'[0-9 -]+',s):return s
        digits=re.sub(r'\D','',s)
        if len(digits)==6:s=digits[:3]+'-'+digits[3:]
    elif key=='Licence_number':
        s=s.translate(DIGITS)
        if not re.fullmatch(r'[0-9 -]+',s):return s
        digits=re.sub(r'\D','',s)
        if len(digits)==10:s=digits[:2]+' '+digits[2:4]+' '+digits[4:]
    # Keep textual spelling (including Latin names) verbatim. A homoglyph
    # substitution can corrupt a legitimate foreign place name.
    return s

class Processor:
    def __init__(self, root, model=None):
        self.root=Path(root)
        self.model=model if model is not None else json.loads((self.root/'model.json').read_text())
        if model is None:
            policies=self.model.get('policies',{})
            if self.model.get('schema_version')!=1 or set(policies)!={'web','mobile','mobile_v2'}:
                raise ValueError('model must contain a complete acceptance policy')
            for policy in policies.values():
                if (not finite_number(policy.get('place_threshold'))
                        or not 0<=policy['place_threshold']<=1
                        or not finite_number(policy.get('risk_cutoff'))):
                    raise ValueError('invalid acceptance policy')
        self.org_by_code={k:set(v) for k,v in self.model.get('org_by_code',{}).items()}
        self.orgs=defaultdict(set)
        with (self.root/'reference/subdivisions.csv').open(encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):self.orgs[row['code']].add(norm(row['name']))

    def issuer(self,code,value,field):
        # The reference uses different grammatical forms and punctuation. Its
        # canonical strings must never replace verbatim passport wording.
        names=self.org_by_code.get(code,set())
        if value in names:return value,'exact_for_code'
        # Never invent an agency based on code alone: preserve >=95% of OCR text.
        candidates=[]
        for target in names:
            if abs(len(target)-len(value))>2:continue
            d=edit_distance(value,target,2)
            if d<=2 and d/max(len(target),1)<=.05:candidates.append((d,target))
        candidates.sort()
        if candidates and (len(candidates)==1 or candidates[0][0]+1<candidates[1][0]):return candidates[0][1],'corrected'
        if code in self.orgs and confidence(field)>=.99:return value,'high_confidence_verbatim'
        return None,'issuer_ambiguous'

    def process(self,record,threshold=None):
        threshold=threshold if threshold is not None else self.model.get('place_threshold',.99)
        def reject(reason):return {'doc_id':record['doc_id'],'decision':'reject'},reason
        if not valid_record(record):return reject('malformed_record')
        fields={k:normalize_field(k,text(record.get('viz',{}).get(k))) for k in FIELDS}
        viz=record.get('viz',{})
        if record.get('source') not in ['web','mobile','mobile_v2']:return reject('unknown_source')
        q=record.get('quality',{})
        if q.get('doc_px',0)<750 or q.get('sharpness',0)<35 or q.get('glare',1)>.35:return reject('image_quality')
        for k in FIELDS:
            if k=='Middle_name_ru' and not viz.get(k):continue
            if not complete(viz.get(k)):return reject('missing_or_incomplete_field')
        if not re.fullmatch('[А-ЯЁ -]+',fields['Last_name_ru']) or not re.fullmatch('[А-ЯЁ -]+',fields['First_name_ru']):return reject('name_format')
        if fields['Middle_name_ru'] and not re.fullmatch('[А-ЯЁ -]+',fields['Middle_name_ru']):return reject('name_format')
        if fields['Sex_ru'] not in ['МУЖ.','ЖЕН.']:return reject('sex_format')
        if not re.fullmatch(r'\d{3}-\d{3}',fields['Issue_organisation_code']):return reject('code_format')
        if not re.fullmatch(r'\d{2} \d{2} \d{6}',fields['Licence_number']):return reject('number_format')
        if not valid_dates(fields) or parse_date(fields['Birth_date'])<anniversary(AS_OF,-120):return reject('invalid_dates_or_expired')
        mrz=mrz_lines(record)
        if not mrz:return reject('mrz_missing_or_invalid')
        # A clipped name line cannot corroborate the unseen suffix or prove
        # that a missing patronymic is truly absent.
        payload_length=len(name_payload(fields))
        if payload_length>=44 or (not fields['Middle_name_ru'] and payload_length>=43):
            return reject('name_evidence_truncated')
        if line1(fields)!=mrz[0] or line2(fields)!=mrz[1]:return reject('mrz_disagreement')
        org,method=self.issuer(fields['Issue_organisation_code'],fields['Issue_organization_ru'],viz['Issue_organization_ru'])
        if org is None:return reject(method)
        fields['Issue_organization_ru']=org
        place=fields['Birth_place_ru']
        if not place or confidence(viz['Birth_place_ru'])<threshold:return reject('place_confidence')
        # A ranking score, not an independently calibrated probability. Tune
        # the acceptance cutoff only against document-level errors.
        score=self.uncertainty(record,fields)
        policy=self.model.get('policies',{}).get(record.get('source'))
        if policy and confidence(viz['Birth_place_ru'])<policy['place_threshold']:return reject('source_place_confidence')
        cutoff=policy['risk_cutoff'] if policy else self.model.get('risk_cutoff')
        if cutoff is not None and score>cutoff:return reject('risk_cutoff')
        return {'doc_id':record['doc_id'],'decision':'accept','fields':fields},'accept'

    def uncertainty(self,record,fields=None):
        total=0.0
        all_cs=[]
        for k in FIELDS:
            v=record['viz'].get(k)
            if v:
                cs=[c for l in lines(v) for c in l.get('char_conf',[])]
                all_cs.extend(cs)
                total+=sum(1-c for c in cs)
                total+=1-float(v.get('conf',0))
        mrz_cs=[c for l in (record.get('mrz') or {}).get('lines',[]) for c in l.get('char_conf',[])]
        all_cs.extend(mrz_cs)
        total+=sum(1-c for c in mrz_cs)
        # Both OCR channels can be wrong with almost all confidences saturated.
        if all_cs and sum(c>=.9999 for c in all_cs)/len(all_cs)>.9:total+=1.0
        return total+self.model.get('source_penalties',{}).get(record.get('source',''),0.0)

def load_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        for n,line in enumerate(f,1):
            if line.strip():
                try:yield json.loads(line)
                except json.JSONDecodeError as e:raise ValueError(f'{path}:{n}: invalid JSON') from e
