#!/usr/bin/env python3
"""Inspect, snapshot/extract and render Codex telemetry; no model/network calls."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

from otlp import analyze, inventory, iso_ns, read
from report_html import render

def write_json(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')

def snapshot(paths,out,kind):
    result=[]
    for i,p in enumerate(paths,1):
        source=Path(p).resolve();before=source.stat();target=out/f'{kind}-{i}.jsonl'
        digest=hashlib.sha256();remaining=before.st_size
        with source.open('rb') as src,target.open('xb') as dst:
            while remaining:
                chunk=src.read(min(1024*1024,remaining))
                if not chunk:raise ValueError(f'Input shrank while copying: {source}')
                dst.write(chunk);digest.update(chunk);remaining-=len(chunk)
        after=source.stat()
        result.append({'original':str(source),'snapshot':str(target),'bytes':before.st_size,
          'sha256':digest.hexdigest(),'changed_during_copy':before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns})
    return result

def extract(args):
    out=Path(args.out).resolve()
    if out.exists():raise ValueError('Analysis output requires an unused directory')
    out.mkdir(parents=True)
    snapshots=out/'inputs';snapshots.mkdir()
    entries=snapshot(args.logs,snapshots,'logs')+snapshot(args.traces,snapshots,'traces')
    logs=[e['snapshot'] for e in entries if Path(e['snapshot']).name.startswith('logs-')]
    traces=[e['snapshot'] for e in entries if Path(e['snapshot']).name.startswith('traces-')]
    data=read(logs,traces)
    if any(e['changed_during_copy'] for e in entries):data['warnings'].append('Input changed while copying the snapshot; collection may still be active')
    analysis=analyze(data,args.conversation,args.turn_span_id,iso_ns(args.start) if args.start else None,iso_ns(args.end) if args.end else None)
    analysis['analysis_id']=hashlib.sha256((analysis['analysis_id']+':'+':'.join(e['sha256'] for e in entries)).encode()).hexdigest()[:20]
    analysis['sources']=entries
    write_json(out/'source-manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'files':entries})
    write_json(out/'analysis.json',analysis)
    with (out/'actions.csv').open('x',newline='') as stream:
        keys=['id','kind','start_seconds','end_seconds','seconds','title_candidate','files_written','tool_ids']
        writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(analysis['actions'])
    review={'analysis_id':analysis['analysis_id'],'semantic_review_complete':False,
      'title':'Enter a title describing the work','objective':'Describe what the loop implemented and verified.','conclusion':'Explain the outcome and supported improvement candidates.',
      'action_labels':{a['id']:{'title':a['title_candidate'],'summary':'Review and explain the captured operations and results.','files':a['files_written']} for a in analysis['actions']},
      'stages':[{'id':'stage-1','title':'Review the work and define meaningful stages','summary':'Initial grouping awaiting semantic review.',
        'start_seconds':0,'end_seconds':analysis['scope']['seconds'],
        'groups':[{'title':'Activities to review and classify','action_ids':[a['id'] for a in analysis['actions']]}]}],
      'timeline':{'lanes':[]},
      'improvement_status':'no_supported_proposals','improvement_note':'Check the evidence for suggestions, or explain why none is supported.','findings':[]}
    write_json(out/'review.template.json',review)
    return {'out':str(out),'analysis_id':analysis['analysis_id'],'scope':analysis['scope'],'counts':analysis['counts'],'warnings':analysis['warnings']}

def render_command(args):
    analysis_path=Path(args.analysis).resolve();review_path=Path(args.review).resolve();out=Path(args.out).resolve()
    if out.exists() or out.with_suffix('.verification.json').exists():raise ValueError('Do not overwrite existing HTML or verification results; choose an unused filename')
    # Export links are relative to the analysis directory; a separate site can be
    # created by copying the analysis bundle first.
    if out.parent!=analysis_path.parent or review_path.parent!=analysis_path.parent:
        raise ValueError('HTML and review.json must share the output directory with analysis.json')
    data=json.loads(analysis_path.read_text());review=json.loads(review_path.read_text())
    html,verification=render(data,review,args.timezone)
    skill=Path(args.html_skill).expanduser().resolve()
    assets=out.parent/'design-system'
    for name in ['document.css','math-copy.js']:
        source=skill/'design-system'/name;target=assets/name
        if not source.is_file():raise ValueError('Missing shared html skill asset: '+str(source))
        if target.exists() and target.read_bytes()!=source.read_bytes():raise ValueError('Do not overwrite a different existing shared asset: '+str(target))
    assets.mkdir(exist_ok=True)
    for name in ['document.css','math-copy.js']:
        if not (assets/name).exists():shutil.copy2(skill/'design-system'/name,assets/name)
    with out.open('x') as stream:stream.write(html)
    verification.update(html_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest())
    write_json(out.with_suffix('.verification.json'),verification)
    return {'html':str(out),'verification':str(out.with_suffix('.verification.json')),
            'stages':len(verification['stages']),'actions':verification['actions'],'findings':verification['findings']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True)
    for name in ['inspect','extract']:
        p=subs.add_parser(name);p.add_argument('--logs',nargs='+',required=True);p.add_argument('--traces',nargs='*',default=[])
        if name=='extract':
            p.add_argument('--conversation');p.add_argument('--turn-span-id');p.add_argument('--start');p.add_argument('--end');p.add_argument('--out',required=True)
    p=subs.add_parser('render');p.add_argument('--analysis',required=True);p.add_argument('--review',required=True)
    p.add_argument('--html-skill',required=True);p.add_argument('--timezone',default='UTC');p.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        if args.command=='inspect':result=inventory(read(args.logs,args.traces))
        elif args.command=='extract':result=extract(args)
        else:result=render_command(args)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':sys.exit(main())
