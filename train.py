"""Five-fold cross-validation, threshold curve and final model fitting."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import collections
import hashlib
import json
import time
from core import FIELDS, NAMES, SOURCES, Processor, confidence, load_jsonl, norm, valid_dates

ROOT=Path(__file__).resolve().parent
# Character confidence floors for birth place and issuing authority. Across
# all train documents, web and mobile OCR errors in these fields never read
# above 0.93, while about 4000 readings at 0.95 or more are all correct.
# mobile_v2 confidences are saturated: its wrong readings still reach 0.9996,
# so only practically perfect confidence is trusted there.
POLICIES={'web':{'min_conf':.95},'mobile':{'min_conf':.95},'mobile_v2':{'min_conf':.9999}}
# A name zone at or above `trusted` may overrule the other zone only where the
# latter reads below `doubtful`.
NAME_POLICY={'trusted':.99,'doubtful':.9}
CURVE=[.9,.93,.95,.96,.97,.98,.99]

def bucket(doc_id):return int(hashlib.sha256(doc_id.encode()).hexdigest()[:8],16)%5

def make_model(labels,policies=POLICIES):
    issuers=collections.defaultdict(set)
    for g in labels:issuers[g['Issue_organisation_code']].add(norm(g['Issue_organization_ru']))
    return {'schema_version':2,'policies':policies,'names':NAME_POLICY,
            'issuers':{k:sorted(v) for k,v in sorted(issuers.items())}}

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

def cross_validate(records,labels,policies=POLICIES,log=True):
    folds=[];answers={}
    for fold in range(5):
        training=[labels[r['doc_id']] for r in records if bucket(r['doc_id'])!=fold]
        heldout=[r for r in records if bucket(r['doc_id'])==fold]
        processor=Processor(ROOT,make_model(training,policies))
        folds.append(evaluate(heldout,labels,processor,log))
        for record in heldout:answers[record['doc_id']]=processor.process(record)[0]
    summary={'accept':sum(f['accept'] for f in folds),'wrong':sum(f['wrong'] for f in folds),
             'wrong_zones_agree':sum(f['wrong_zones_agree'] for f in folds),
             'by_source':{s:{k:sum(f['by_source'][s][k] for f in folds) for k in ['total','accept','wrong']} for s in SOURCES}}
    return summary,folds,answers

def main():
    start=time.perf_counter()
    records=list(load_jsonl(ROOT/'data/train_predictions.jsonl'))
    labels={r['doc_id']:r['fields'] for r in load_jsonl(ROOT/'data/train_labels.jsonl')}
    cv,folds,validation_answers=cross_validate(records,labels)
    (ROOT/'validation_answers.jsonl').write_text(''.join(json.dumps(validation_answers[r['doc_id']],ensure_ascii=False)+'\n' for r in records))
    curve=[]
    for floor in CURVE:
        policies={s:({'min_conf':floor} if s!='mobile_v2' else POLICIES[s]) for s in SOURCES}
        summary=cross_validate(records,labels,policies,log=False)[0]
        curve.append({'web_mobile_floor':floor,**{k:summary[k] for k in ['accept','wrong','wrong_zones_agree']}})
    model=make_model(labels.values())
    (ROOT/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=1)+'\n')
    p=Processor(ROOT)
    train_metrics=evaluate(records,labels,p,log=False)
    (ROOT/'train_answers.jsonl').write_text(''.join(json.dumps(p.process(r)[0],ensure_ascii=False)+'\n' for r in records))
    test=list(load_jsonl(ROOT/'data/test_predictions.jsonl'))
    answers=[p.process(r)[0] for r in test]
    (ROOT/'answers.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in answers))
    test_metrics={'total':len(test),'accept':sum(a['decision']=='accept' for a in answers),
                  'by_source':{s:{'total':sum(r['source']==s for r in test),
                                 'accept':sum(r['source']==s and a['decision']=='accept' for r,a in zip(test,answers))} for s in SOURCES}}
    details={'cross_validation':cv,'folds':folds,'train':train_metrics,'threshold_curve':curve,'test':test_metrics,
             'policies':POLICIES,'names':NAME_POLICY,'seconds':round(time.perf_counter()-start,3)}
    (ROOT/'metrics.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    print('FINAL',json.dumps({k:details[k] for k in ['cross_validation','threshold_curve','test']},ensure_ascii=False))

if __name__=='__main__':main()
