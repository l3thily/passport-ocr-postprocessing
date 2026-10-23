"""Five-fold cross-validation, threshold curve and final model fitting."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import collections
import hashlib
import json
import math
import random
import time
from core import FIELDS, NAMES, SOURCES, Processor, confidence, load_jsonl, norm, valid_dates

ROOT=Path(__file__).resolve().parent
# Character confidence floors for birth place and issuing authority. Across
# all train documents, web and mobile OCR errors in these fields never read
# above 0.93, while about 4000 readings at 0.95 or more are all correct.
# mobile_v2 confidences are saturated: its wrong readings still reach 0.9996,
# so only practically perfect confidence is trusted there.
FLOORS={'web':.95,'mobile':.95,'mobile_v2':.9999}
# On train, 6 of the 7 web documents where both zones confidently agree on a
# value the label contradicts have more than 28% of characters at 0.9999 or
# above; mobile and mobile_v2 show no such pattern. This was found after
# looking at the errors, so it is an operating choice, not a validated rule.
WEB_MAX_SATURATION=.28
VARIANTS={
    # Only the pool with the lowest observed error rate: unsaturated web.
    'zero':{'web':{'min_conf':FLOORS['web'],'max_saturation':WEB_MAX_SATURATION},'mobile':None,'mobile_v2':None},
    # Accept everything the checks support, except saturated web documents.
    'balanced':{s:{'min_conf':FLOORS[s],'max_saturation':WEB_MAX_SATURATION if s=='web' else 1.0} for s in SOURCES},
    # The same checks without the saturation filter.
    'max50':{s:{'min_conf':FLOORS[s],'max_saturation':1.0} for s in SOURCES},
}
DEFAULT_VARIANT='balanced'
# A name zone at or above `trusted` may overrule the other zone only where the
# latter reads below `doubtful`.
NAME_POLICY={'trusted':.99,'doubtful':.9}
CURVE=[.9,.93,.95,.96,.97,.98,.99]

def bucket(doc_id):return int(hashlib.sha256(doc_id.encode()).hexdigest()[:8],16)%5

def make_model(labels,variants=VARIANTS):
    issuers=collections.defaultdict(set)
    for g in labels:issuers[g['Issue_organisation_code']].add(norm(g['Issue_organization_ru']))
    return {'schema_version':3,'default_variant':DEFAULT_VARIANT,'variants':variants,'names':NAME_POLICY,
            'issuers':{k:sorted(v) for k,v in sorted(issuers.items())}}

def forecast(cv,test_by_source,draws=100000):
    """Expected wrong acceptances on test from per-source CV error rates, and a
    predictive interval that also accounts for the uncertainty of the rates."""
    rnd=random.Random(0);rows=[]
    used=[s for s in SOURCES if test_by_source[s]['accept']]
    for s in used:
        if not cv[s]['accept']:raise ValueError('no validation evidence for '+s)
    expected=sum(test_by_source[s]['accept']*cv[s]['wrong']/cv[s]['accept'] for s in used)
    for _ in range(draws):
        lam=sum(test_by_source[s]['accept']*rnd.gammavariate(cv[s]['wrong']+.5,1/cv[s]['accept']) for s in used)
        k,limit,prod=0,math.exp(-lam),rnd.random()
        while prod>limit:k+=1;prod*=rnd.random()
        rows.append(k)
    rows.sort()
    return {'expected':round(expected,2),'interval_90':[rows[int(.05*draws)],rows[int(.95*draws)]],
            'probability_zero':round(rows.count(0)/draws,2)}

def evaluate(records,labels,p,log=True):
    result={'total':len(records),'accept':0,'correct':0,'wrong':0,'wrong_zones_agree':0,
            'reasons':collections.Counter(),'by_source':{}}
    for r in records:
        ans,reason=p.process(r);result['reasons'][reason]+=1
        src=result['by_source'].setdefault(r['source'],{'total':0,'accept':0,'wrong':0});src['total']+=1
        if ans['decision']=='reject':continue
        result['accept']+=1;src['accept']+=1
        g=labels[r['doc_id']]
        wrong=[k for k in FIELDS if norm(ans['fields'][k])!=norm(g[k])]
        if not wrong and valid_dates(g):result['correct']+=1;continue
        result['wrong']+=1;src['wrong']+=1
        # Both OCR zones (or the zone and its confidence) agree on a value the
        # label contradicts; nothing in the input distinguishes these cases.
        result['wrong_zones_agree']+=all(k in NAMES or confidence(r['viz'][k])>=.99 for k in wrong)
        if log:print('ERROR',r['doc_id'],r['source'],[(ans['fields'][k],g[k]) for k in wrong])
    result['reasons']=dict(result['reasons'])
    return result

def cross_validate(records,labels,variant,variants=VARIANTS,log=True):
    folds=[];answers={}
    for fold in range(5):
        training=[labels[r['doc_id']] for r in records if bucket(r['doc_id'])!=fold]
        heldout=[r for r in records if bucket(r['doc_id'])==fold]
        processor=Processor(ROOT,make_model(training,variants),variant)
        folds.append(evaluate(heldout,labels,processor,log))
        for record in heldout:answers[record['doc_id']]=processor.process(record)[0]
    summary={'accept':sum(f['accept'] for f in folds),'wrong':sum(f['wrong'] for f in folds),
             'wrong_zones_agree':sum(f['wrong_zones_agree'] for f in folds),
             'reasons':dict(sum((collections.Counter(f['reasons']) for f in folds),collections.Counter())),
             'by_source':{s:{k:sum(f['by_source'][s][k] for f in folds) for k in ['total','accept','wrong']} for s in SOURCES}}
    return summary,folds,answers

def answer_file(variant):
    return f'variants/{variant}/answers.jsonl'

def main():
    start=time.perf_counter()
    records=list(load_jsonl(ROOT/'data/train_predictions.jsonl'))
    labels={r['doc_id']:r['fields'] for r in load_jsonl(ROOT/'data/train_labels.jsonl')}
    test=list(load_jsonl(ROOT/'data/test_predictions.jsonl'))
    model=make_model(labels.values())
    (ROOT/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=1)+'\n')
    details={'variants':{},'default_variant':DEFAULT_VARIANT}
    for variant in VARIANTS:
        cv,folds,validation=cross_validate(records,labels,variant,log=variant==DEFAULT_VARIANT)
        p=Processor(ROOT,variant=variant)
        answers=[p.process(r)[0] for r in test]
        content=''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in answers)
        (ROOT/answer_file(variant)).parent.mkdir(parents=True,exist_ok=True)
        (ROOT/answer_file(variant)).write_text(content)
        # The task expects answers.jsonl at the root: the recommended variant.
        if variant==DEFAULT_VARIANT:(ROOT/'answers.jsonl').write_text(content)
        test_metrics={'total':len(test),'accept':sum(a['decision']=='accept' for a in answers),
                      'reasons':dict(collections.Counter(p.process(r)[1] for r in test)),
                      'by_source':{s:{'total':sum(r['source']==s for r in test),
                                     'accept':sum(r['source']==s and a['decision']=='accept' for r,a in zip(test,answers))} for s in SOURCES}}
        details['variants'][variant]={'answers':answer_file(variant),'policy':VARIANTS[variant],'cross_validation':cv,'folds':folds,
                                      'train_in_sample':evaluate(records,labels,p,log=False),'test':test_metrics,
                                      'forecast':forecast(cv['by_source'],test_metrics['by_source'])}
        if variant==DEFAULT_VARIANT:
            (ROOT/'validation_answers.jsonl').write_text(''.join(json.dumps(validation[r['doc_id']],ensure_ascii=False)+'\n' for r in records))
            (ROOT/'train_answers.jsonl').write_text(''.join(json.dumps(p.process(r)[0],ensure_ascii=False)+'\n' for r in records))
    # Confidence floor for birth place and issuer (web and mobile), without
    # the saturation filter, to show where real OCR errors begin.
    curve=[]
    for floor in CURVE:
        variants={'curve':{s:{'min_conf':floor if s!='mobile_v2' else FLOORS[s],'max_saturation':1.0} for s in SOURCES}}
        summary=cross_validate(records,labels,'curve',variants,log=False)[0]
        curve.append({'web_mobile_floor':floor,**{k:summary[k] for k in ['accept','wrong','wrong_zones_agree']}})
    details.update({'threshold_curve':curve,'names':NAME_POLICY,'seconds':round(time.perf_counter()-start,3)})
    (ROOT/'metrics.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    print('FINAL',json.dumps({v:{k:d[k] for k in ['test','forecast']}|{'cv':{k:d['cross_validation'][k] for k in ['accept','wrong','by_source']}}
                               for v,d in details['variants'].items()},ensure_ascii=False))

if __name__=='__main__':main()
