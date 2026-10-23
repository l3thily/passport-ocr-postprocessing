"""Usage: python postprocess.py input.jsonl answers.jsonl. CPU, offline."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import FIELDS, Processor, load_jsonl

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--variant',choices=['zero','balanced','max50','max53'],help='acceptance policy (default: balanced, see REPORT.md)')
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():parser.error('input and output must differ')
    p=Processor(Path(__file__).resolve().parent,variant=args.variant)
    seen=set();accepted=0
    fd,tmp=tempfile.mkstemp(prefix='.answers-',suffix='.jsonl',dir=args.output.resolve().parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            for record in load_jsonl(args.input):
                if not isinstance(record,dict):raise ValueError('each JSONL record must be an object')
                doc_id=record.get('doc_id')
                if not isinstance(doc_id,str) or not doc_id or doc_id in seen:raise ValueError('missing or duplicate doc_id')
                seen.add(doc_id)
                answer,_=p.process(record)
                if answer['decision']=='accept':
                    assert set(answer['fields'])==set(FIELDS)
                    accepted+=1
                out.write(json.dumps(answer,ensure_ascii=False)+'\n')
        os.replace(tmp,args.output)
    except BaseException:
        os.unlink(tmp)
        raise
    print(f'documents={len(seen)} accepted={accepted} rejected={len(seen)-accepted}',file=sys.stderr)

if __name__=='__main__':main()
