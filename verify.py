"""Independent output checks and CLI regression tests; standard library only."""
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parent
FIELDS={'Last_name_ru','First_name_ru','Middle_name_ru','Sex_ru','Birth_date',
        'Birth_place_ru','Issue_date','Issue_organisation_code','Licence_number','Issue_organization_ru'}
AS_OF=dt.date(2026,10,1)

def read(path):
    with Path(path).open(encoding='utf-8') as f:return [json.loads(line) for line in f if line.strip()]

def normalized(s):return ' '.join(str(s or '').upper().split())

def date_valid(fields):
    # Independent formulation: compute the age when this passport was issued,
    # then its next expiry birthday, rather than reuse core.valid_dates.
    try:
        born=dt.datetime.strptime(fields['Birth_date'],'%d.%m.%Y').date()
        issued=dt.datetime.strptime(fields['Issue_date'],'%d.%m.%Y').date()
    except (ValueError,KeyError,TypeError):return False
    age=issued.year-born.year-((issued.month,issued.day)<(born.month,born.day))
    if age<14 or issued>AS_OF or issued<dt.date(1997,10,1):return False
    if age>=45:return True
    expiry_year=born.year+(20 if age<20 else 45)
    try:expiry=dt.date(expiry_year,born.month,born.day)
    except ValueError:expiry=dt.date(expiry_year,3,1)
    return AS_OF<=expiry+dt.timedelta(days=90)

def check_output(predictions,answers,labels=None):
    assert len(answers)==len(predictions)
    ids=[a['doc_id'] for a in answers]
    assert ids==[r['doc_id'] for r in predictions] and len(set(ids))==len(ids)
    accepted=wrong=invalid=0
    for a in answers:
        assert a['decision'] in ('accept','reject')
        if a['decision']=='reject':
            assert set(a)=={'doc_id','decision'}
            continue
        assert set(a)=={'doc_id','decision','fields'} and set(a['fields'])==FIELDS
        assert all(isinstance(v,str) for v in a['fields'].values())
        accepted+=1
        assert date_valid(a['fields'])
        if labels is not None:
            target=labels[a['doc_id']]['fields']
            wrong+=any(normalized(a['fields'][k])!=normalized(target[k]) for k in FIELDS)
            invalid+=not date_valid(target)
    return {'rows':len(answers),'accepted':accepted,'wrong_fields':wrong if labels is not None else None,
            'invalid_accepted':invalid if labels is not None else None}

def run_cli(source,output,cwd=ROOT,script=None):
    return subprocess.run([sys.executable,'-I','-S',str(script or ROOT/'postprocess.py'),str(source),str(output)],
                          cwd=cwd,capture_output=True,text=True)

def main():
    results={}
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='tests.py',top_level_dir=str(ROOT))
    unit_result=unittest.TextTestRunner(stream=stream).run(suite)
    assert unit_result.wasSuccessful(),stream.getvalue()
    train=read(ROOT/'data/train_predictions.jsonl');test=read(ROOT/'data/test_predictions.jsonl')
    labels={r['doc_id']:r for r in read(ROOT/'data/train_labels.jsonl')}
    for name,rs,label_map in [('train_answers.jsonl',train,labels),('validation_answers.jsonl',train,labels),('answers.jsonl',test,None)]:
        results[name]=check_output(rs,read(ROOT/name),label_map)
    metrics=json.loads((ROOT/'metrics.json').read_text())
    assert results['train_answers.jsonl']['accepted']==metrics['train']['accept']
    assert results['validation_answers.jsonl']['accepted']==sum(f['accept'] for f in metrics['folds'])
    assert results['answers.jsonl']['accepted']==metrics['test']['accept']
    assert results['train_answers.jsonl']['wrong_fields']==0
    assert results['validation_answers.jsonl']['wrong_fields']==0
    checks={}
    (ROOT/'.tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='verification-',dir=ROOT/'.tmp') as temp:
        temp=Path(temp)
        start=time.perf_counter()
        child=run_cli(ROOT/'data/test_predictions.jsonl',temp/'answers.jsonl')
        assert child.returncode==0,child.stderr
        results['inference_seconds']=round(time.perf_counter()-start,4)
        assert (temp/'answers.jsonl').read_bytes()==(ROOT/'answers.jsonl').read_bytes()
        checks['byte_identical_inference']=True
        item=json.dumps(test[0],ensure_ascii=False)+'\n'
        for name,payload in [('duplicate',item+item),('bad_json','{broken}\n'),('not_object','[]\n')]:
            inp=temp/(name+'.jsonl');inp.write_text(payload)
            out=temp/(name+'-out.jsonl');out.write_text('existing output must survive')
            child=run_cli(inp,out)
            assert child.returncode!=0
            assert out.read_text()=='existing output must survive'
            assert not list(temp.glob('.answers-*'))
            checks[name+'_atomic_failure']=True
        inp=temp/'inplace.jsonl';inp.write_text(item)
        child=run_cli(inp,inp)
        assert child.returncode!=0 and inp.read_text()==item
        checks['inplace_guard']=True
        # Deploy only inference code, the fitted artifact and its reference.
        # Training data and labels are deliberately absent from this directory.
        runtime=temp/'runtime';(runtime/'reference').mkdir(parents=True)
        for name in ['core.py','postprocess.py','model.json','reference/subdivisions.csv']:
            (runtime/name).write_bytes((ROOT/name).read_bytes())
        (runtime/'input.jsonl').write_bytes((ROOT/'data/test_predictions.jsonl').read_bytes())
        child=run_cli('input.jsonl','output.jsonl',runtime,runtime/'postprocess.py')
        assert child.returncode==0,child.stderr
        assert (runtime/'output.jsonl').read_bytes()==(ROOT/'answers.jsonl').read_bytes()
        checks['inference_without_training_files']=True
    results['cli_checks']=checks
    results['answers_sha256']=hashlib.sha256((ROOT/'answers.jsonl').read_bytes()).hexdigest()
    results['schema_valid_on_all_2000_rows']=True
    results['unit_tests_passed']=unit_result.testsRun
    results['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                             for name in ['core.py','postprocess.py','train.py','tests.py','model.json','run-isolated.sh']}
    results['security_checks']=json.loads((ROOT/'security_checks.json').read_text())
    (ROOT/'verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
