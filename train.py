"""Deterministic five-fold cross-validation and offline model fitting."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import collections
import hashlib
import json
import math
import time
from core import Processor, load_jsonl, norm, tokens, valid_dates, confidence, FIELDS

ROOT=Path(__file__).resolve().parent
SOURCES=['web','mobile','mobile_v2']
def bucket(doc_id):return int(hashlib.sha256(doc_id.encode()).hexdigest()[:8],16)%5

def make_model(labels):
    labels=list(labels)
    org_by_code=collections.defaultdict(set)
    for g in labels:org_by_code[g['Issue_organisation_code']].add(norm(g['Issue_organization_ru']))
    return {'schema_version':1,'place_threshold':.99,
            'org_by_code':{k:sorted(v) for k,v in sorted(org_by_code.items())}}

def wrong(answer,label):
    return any(norm(answer['fields'].get(k))!=norm(label[k]) for k in FIELDS) or not valid_dates(label)

def fit(records,labels):
    model=make_model(labels[r['doc_id']] for r in records)
    p=Processor(ROOT,model)
    candidates=[]
    for r in records:
        a,_=p.process(r)
        if a['decision']=='accept':
            candidates.append((r['source'],confidence(r['viz']['Birth_place_ru']),p.uncertainty(r),wrong(a,labels[r['doc_id']])))
    policies={}
    for source in SOURCES:
        options=[]
        for threshold in [.995,.996,.9985]:
            if source=='web' and threshold<.9985:continue
            rows=[x for x in candidates if x[0]==source and x[1]>=threshold]
            good=[x[2] for x in rows if not x[3]];bad=[x[2] for x in rows if x[3]]
            cutoff=math.nextafter(.8*min(bad),-math.inf) if bad else max(good,default=-1)+1e-9
            cutoff=min(cutoff,{'web':.15,'mobile':2.0,'mobile_v2':.8}[source])
            assert not any(x<=cutoff for x in bad), 'fitted cutoff admits a known error'
            count=sum(x<=cutoff for x in good)
            options.append((count,-threshold,cutoff))
        count,negthreshold,cutoff=max(options)
        policies[source]={'place_threshold':-negthreshold,'risk_cutoff':cutoff,'fit_accepted':count}
    model['policies']=policies
    model['training_documents']=len(records)
    return model

def evaluate(records,labels,p):
    result={'total':len(records),'accept':0,'correct':0,'wrong_fields':0,'invalid_accept':0,'reasons':collections.Counter(),'by_source':{}}
    for r in records:
        ans,reason=p.process(r);result['reasons'][reason]+=1
        src=result['by_source'].setdefault(r['source'],{'total':0,'accept':0,'bad':0});src['total']+=1
        if ans['decision']=='reject':continue
        result['accept']+=1;src['accept']+=1
        g=labels[r['doc_id']]
        fields_wrong=[k for k in FIELDS if norm(ans['fields'].get(k))!=norm(g[k])]
        invalid=not valid_dates(g)
        result['wrong_fields']+=bool(fields_wrong);result['invalid_accept']+=invalid
        if not fields_wrong and not invalid:result['correct']+=1
        else:src['bad']+=1;print('ERROR',r['doc_id'],fields_wrong,'invalid',invalid)
    result['reasons']=dict(result['reasons'])
    return result

def main():
    start=time.perf_counter()
    records=list(load_jsonl(ROOT/'data/train_predictions.jsonl'))
    labels={r['doc_id']:r['fields'] for r in load_jsonl(ROOT/'data/train_labels.jsonl')}
    folds=[]
    validation_answers={}
    for fold in range(5):
        training=[r for r in records if bucket(r['doc_id'])!=fold]
        heldout=[r for r in records if bucket(r['doc_id'])==fold]
        model=fit(training,labels)
        processor=Processor(ROOT,model)
        metrics=evaluate(heldout,labels,processor)
        for record in heldout:
            assert record['doc_id'] not in validation_answers
            validation_answers[record['doc_id']]=processor.process(record)[0]
        folds.append(metrics)
        print('FOLD',fold,json.dumps({'policies':model['policies'],'metrics':metrics},ensure_ascii=False))
    (ROOT/'validation_answers.jsonl').write_text(''.join(json.dumps(validation_answers[r['doc_id']],ensure_ascii=False)+'\n' for r in records))
    model=fit(records,labels)
    (ROOT/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
    p=Processor(ROOT,model)
    train_metrics=evaluate(records,labels,p)
    (ROOT/'train_answers.jsonl').write_text(''.join(json.dumps(p.process(r)[0],ensure_ascii=False)+'\n' for r in records))
    test=list(load_jsonl(ROOT/'data/test_predictions.jsonl'))
    answers=[p.process(r)[0] for r in test]
    (ROOT/'answers.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in answers))
    test_metrics={'total':len(test),'accept':sum(a['decision']=='accept' for a in answers),
                  'by_source':{s:{'total':sum(r['source']==s for r in test),
                                 'accept':sum(r['source']==s and a['decision']=='accept' for r,a in zip(test,answers))} for s in SOURCES}}
    details={'folds':folds,'train':train_metrics,'test':test_metrics,'policies':model['policies'],
             'seconds':round(time.perf_counter()-start,3),
             'validation_limitation':'Exploratory data analysis preceded cross-validation; this is internal validation, not an untouched external test.'}
    (ROOT/'metrics.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    print('FINAL',json.dumps(details,ensure_ascii=False))

if __name__=='__main__':main()
