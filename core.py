"""Offline OCR postprocessing. Standard library only; no network or subprocesses.

Decision logic in one paragraph: the MRZ second line carries four check digits,
so whenever they verify, it is the source of truth for the number, both dates,
the subdivision code and sex. The MRZ first line has no checksum, so names are
accepted only when the visual zone and the MRZ agree, or when exactly one
channel is confidently right and the other is visibly unsure. Birth place and
issuing authority exist only in the visual zone; they are accepted when the
field is complete and every character clears a per-source confidence floor.
"""
import datetime as dt
import json
import math
import re
import statistics
from pathlib import Path

FIELDS = ['Last_name_ru', 'First_name_ru', 'Middle_name_ru', 'Sex_ru',
          'Birth_date', 'Birth_place_ru', 'Issue_date', 'Issue_organisation_code',
          'Licence_number', 'Issue_organization_ru']
NAMES = ['Last_name_ru', 'First_name_ru', 'Middle_name_ru']
SOURCES = ['web', 'mobile', 'mobile_v2']
AS_OF = dt.date(2026, 10, 1)
TRANSLIT = dict(zip('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                    ['A','B','V','G','D','E','2','J','Z','I','Q','K','L','M','N','O','P','R','S','T','U','F','H','C','3','4','W','X','Y','9','6','7','8']))
UNTRANSLIT = {v: k for k, v in TRANSLIT.items()}
DIGITS = str.maketrans({'О':'0','O':'0','З':'3','Ч':'4','Б':'6','В':'8','B':'8','S':'5','I':'1','L':'1'})
# MRZ line 2 layout: (data slice, check digit position). The last entry is
# the composite check over number, birth date and optional data.
MRZ_SEGMENTS = [(slice(0, 9), 9), (slice(13, 19), 19), (slice(28, 42), 42)]

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
    """Lowest per-character probability: a single doubtful glyph is enough."""
    cs=[c for l in lines(field) for c in l.get('char_conf',[])]
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

def replacement_pending(fields, as_of=AS_OF):
    """Holder already reached 20 or 45 and relies on the 90-day grace period.

    Such a passport is still valid, but only by a rule that is easy to read
    differently, so it is not worth accepting automatically."""
    birth=parse_date(fields['Birth_date']);issue=parse_date(fields['Issue_date'])
    return any(issue<anniversary(birth,age)<=as_of for age in (20,45))

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
    if not re.fullmatch(r'\d{3}-\d{3}',fields['Issue_organisation_code']):return None
    serial=num[:3]+num[4:]
    optional=num[3]+i.strftime('%y%m%d')+fields['Issue_organisation_code'].replace('-','')+'<'
    s=serial+checkdigit(serial)+'RUS'+b.strftime('%y%m%d')+checkdigit(b.strftime('%y%m%d'))
    s+=('M' if fields['Sex_ru']=='МУЖ.' else 'F')+'<'*7+optional+checkdigit(optional)
    return s+checkdigit(s[:10]+s[13:20]+s[21:43])

def checksums_ok(b):
    return (all(b[d].isdigit() and checkdigit(b[s])==b[d] for s,d in MRZ_SEGMENTS)
            and b[43].isdigit() and checkdigit(b[:10]+b[13:20]+b[21:43])==b[43])

def mrz_fields(record, viz_fields):
    """Fields recovered from a checksum-verified MRZ line 2.

    Constant positions (RUS and fillers) carry no data and are restored before
    verification. When exactly one data segment fails its check digit, the
    visual-zone value for that segment is accepted only if it satisfies both
    the MRZ segment check digit and the composite check digit."""
    raw=(record.get('mrz') or {}).get('lines',[])
    if len(raw)!=2:return None
    b=norm(raw[1].get('text',''))
    if len(b)!=44 or not re.fullmatch('[A-Z0-9<]{44}',b):return None
    b=b[:10]+'RUS'+b[13:21]+'<'*7+b[28:41]+'<'+b[42:]
    if not checksums_ok(b):
        viz_line=line2(viz_fields)
        failed=[s for s,d in MRZ_SEGMENTS if not (b[d].isdigit() and checkdigit(b[s])==b[d])]
        if viz_line is None or len(failed)>1:return None
        if failed:
            s=failed[0]
            b=b[:s.start]+viz_line[s]+b[s.stop:]
        # With every segment verified, only the composite digit itself can be
        # misread; the visual zone must then reproduce all data exactly.
        elif b[:20]+b[21:43]==viz_line[:20]+viz_line[21:43]:b=b[:43]+viz_line[43]
        if not checksums_ok(b):return None
    if not (b[:9].isdigit() and b[13:19].isdigit() and b[28:41].isdigit()):return None
    if b[20] in 'MF':sex='МУЖ.' if b[20]=='M' else 'ЖЕН.'
    elif viz_fields['Sex_ru'] in ('МУЖ.','ЖЕН.'):sex=viz_fields['Sex_ru']
    else:return None
    opt=b[28:42]
    digits=b[:3]+opt[0]+b[3:9]
    issue_year=2000+int(opt[1:3])
    if issue_year>AS_OF.year:issue_year-=100
    issue=f'{opt[5:7]}.{opt[3:5]}.{issue_year}'
    birth_year=2000+int(b[13:15])
    if birth_year+14>issue_year:birth_year-=100
    birth=f'{b[17:19]}.{b[15:17]}.{birth_year}'
    if not parse_date(issue) or not parse_date(birth):return None
    return {'Licence_number':digits[:2]+' '+digits[2:4]+' '+digits[4:],'Birth_date':birth,'Issue_date':issue,
            'Issue_organisation_code':opt[7:10]+'-'+opt[10:13],'Sex_ru':sex}

def mrz_name_line(record):
    """Name payload of MRZ line 1 and the minimal confidence over it."""
    raw=(record.get('mrz') or {}).get('lines',[])
    if len(raw)!=2:return None
    a=raw[0].get('text','');conf=raw[0].get('char_conf',[])
    # A lost or doubled filler does not touch the name; the document type and
    # country prefix is constant.
    if not 43<=len(a)<=45 or not re.fullmatch('[A-Z0-9<]+',a):return None
    a='PNRUS'+a[5:]
    end=len(a.rstrip('<'))
    # A clipped line cannot prove where the name ends.
    if end>=42 or end>len(a)-2:return None
    return a[:end],min(conf[5:end])

def names_from_mrz(payload,viz):
    """Read names from the MRZ payload, keeping the visual-zone layout.

    Spaces and hyphens both become '<' in the MRZ, so separators are taken from
    the visual zone and only letters are taken from the MRZ. Without a matching
    layout the split between first name and patronymic is ambiguous."""
    body=payload[5:]
    if any(c!='<' and c not in UNTRANSLIT for c in body):return None
    parts=[translit(viz['Last_name_ru']),translit(viz['First_name_ru'])]
    layout=parts[0]+'<<'+parts[1]
    if viz['Middle_name_ru']:layout+='<'+translit(viz['Middle_name_ru'])
    if len(layout)!=len(body):
        # Same structure, different lengths: only unambiguous when no name
        # contains an inner separator.
        surname,sep,given=body.partition('<<')
        tokens=given.split('<')
        if not sep or '<' in surname or len(tokens)!=1+bool(viz['Middle_name_ru']) or '' in tokens:return None
        if any('<' in translit(viz[k]) for k in NAMES):return None
        decode=lambda s:''.join(UNTRANSLIT[c] for c in s)
        return {'Last_name_ru':decode(surname),'First_name_ru':decode(tokens[0]),
                'Middle_name_ru':decode(tokens[1]) if len(tokens)>1 else ''}
    out={};i=0
    for k in NAMES:
        value=viz[k]
        if k=='Middle_name_ru' and not value:out[k]='';continue
        if k!='Last_name_ru':
            if body[i:i+(2 if k=='First_name_ru' else 1)]!='<'*(2 if k=='First_name_ru' else 1):return None
            i+=2 if k=='First_name_ru' else 1
        chars=[]
        for v in value:
            c=body[i];i+=1
            if c=='<':
                if v not in ' -':return None
                chars.append(v)
            else:chars.append(UNTRANSLIT[c])
        out[k]=''.join(chars)
    return out

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

def char_confidences(field):
    """Per-character confidences aligned with text(field), or None."""
    out=[]
    for i,l in enumerate(lines(field)):
        if i:out.append(1.0)
        out.extend(l.get('char_conf',[]))
    return out if field and len(out)==len(text(field)) else None

def doubted(field,read,other,doubtful):
    """True when every difference between read and other sits on a glyph the
    visual zone itself was unsure about."""
    if read==other:return True
    if not field:return not read
    conf=char_confidences(field)
    if conf is None:return False
    if len(read)==len(other):return all(c<doubtful for a,b,c in zip(read,other,conf) if a!=b)
    return min(conf)<doubtful

def valid_name(value):
    return bool(re.fullmatch('[А-ЯЁ]+([ -][А-ЯЁ]+)*',value))

class Processor:
    def __init__(self, root, model=None):
        self.root=Path(root)
        self.model=model if model is not None else json.loads((self.root/'model.json').read_text())
        policies=self.model.get('policies',{})
        names=self.model.get('names',{})
        if self.model.get('schema_version')!=2 or set(policies)!=set(SOURCES):
            raise ValueError('model must contain a complete acceptance policy')
        for value in [p.get('min_conf') for p in policies.values()]+[names.get('trusted'),names.get('doubtful')]:
            if not finite_number(value) or not 0<=value<=1:
                raise ValueError('invalid acceptance policy')
        self.issuers={code:set(names) for code,names in self.model.get('issuers',{}).items()}

    def resolve_names(self,record,fields):
        """Pick names confirmed by both zones, or by one confident zone when
        every disagreement falls on characters the other zone doubts."""
        line=mrz_name_line(record)
        if not line:return None,'mrz_names_unreadable'
        payload,mrz_conf=line
        viz={k:fields[k] for k in NAMES}
        if name_payload(viz)==payload:return viz,'agree'
        p=self.model['names']
        if mrz_conf>=p['trusted']:
            mrz=names_from_mrz(payload,viz)
            if mrz and name_payload(mrz)==payload and all(
                    doubted(record['viz'].get(k),viz[k],mrz[k],p['doubtful']) for k in NAMES):
                return mrz,'mrz_over_doubtful_viz'
        viz_conf=min(confidence(record['viz'][k]) for k in NAMES if record['viz'].get(k))
        if viz_conf>=p['trusted']:
            mine=name_payload(viz);conf=record['mrz']['lines'][0]['char_conf']
            if len(mine)==len(payload) and all(conf[i]<p['doubtful'] for i,(a,b) in enumerate(zip(mine,payload)) if a!=b):
                return viz,'viz_over_doubtful_mrz'
        return None,'name_disagreement'

    def known_issuer(self,code,field):
        """Spelling of the issuing authority already seen for this code, when
        the OCR text matches it except on characters the OCR doubted."""
        read=text(field);conf=char_confidences(field)
        known=self.issuers.get(code,set())
        if read in known:return read
        if conf is None:return None
        doubtful=self.model['names']['doubtful']
        hits=[k for k in known if len(k)==len(read) and all(c<doubtful for a,b,c in zip(read,k,conf) if a!=b)]
        return hits[0] if len(hits)==1 else None

    def process(self,record):
        def reject(reason):return {'doc_id':record['doc_id'],'decision':'reject'},reason
        if not valid_record(record):return reject('malformed_record')
        source=record.get('source')
        if source not in SOURCES:return reject('unknown_source')
        viz=record['viz']
        fields={k:normalize_field(k,text(viz.get(k))) for k in FIELDS}
        # Number, dates, code and sex come from the verified MRZ, so only the
        # fields read from the visual zone must be complete there.
        for k in NAMES+['Birth_place_ru','Issue_organization_ru']:
            if k=='Middle_name_ru' and not viz.get(k):continue
            if not complete(viz.get(k)):return reject('missing_or_incomplete_field')
        trusted=mrz_fields(record,fields)
        if not trusted:return reject('mrz_unverified')
        fields.update(trusted)
        names,how=self.resolve_names(record,fields)
        if names is None:return reject(how)
        if not all(valid_name(names[k]) for k in NAMES if k!='Middle_name_ru' or names[k]):return reject('name_format')
        fields.update(names)
        if not valid_dates(fields) or parse_date(fields['Birth_date'])<anniversary(AS_OF,-120):return reject('invalid_dates_or_expired')
        if replacement_pending(fields):return reject('replacement_grace_period')
        floor=self.model['policies'][source]['min_conf']
        if not fields['Birth_place_ru'] or confidence(viz['Birth_place_ru'])<floor:return reject('low_confidence_Birth_place_ru')
        org=fields['Issue_organization_ru']
        if not org or confidence(viz['Issue_organization_ru'])<floor:
            org=self.known_issuer(fields['Issue_organisation_code'],viz['Issue_organization_ru'])
            if not org:return reject('low_confidence_Issue_organization_ru')
        fields['Issue_organization_ru']=org
        return {'doc_id':record['doc_id'],'decision':'accept','fields':fields},'accept'

def load_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        for n,line in enumerate(f,1):
            if line.strip():
                try:yield json.loads(line)
                except json.JSONDecodeError as e:raise ValueError(f'{path}:{n}: invalid JSON') from e
