"""Read Codex OTLP exports without executing captured content."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

NAMES={'session_task.turn','codex.sampling','code_mode.handler.execute',
       'handle_tool_call_with_source','unified_exec.exec_command'}

def field(d,name,default=None):
    snake=re.sub(r'(?<!^)([A-Z])',r'_\1',name).lower()
    return d.get(name,d.get(snake,default))

def value(v):
    if not isinstance(v,dict):return v
    for key in ['stringValue','boolValue','intValue','doubleValue','bytesValue']:
        result=field(v,key)
        if result is not None:return int(result) if key=='intValue' else result
    array=field(v,'arrayValue')
    if array is not None:return [value(x) for x in array.get('values',[])]
    kv=field(v,'kvlistValue')
    if kv is not None:return attributes(kv.get('values',[]))
    return None

def attributes(items):
    return {a['key']:value(a.get('value')) for a in items}

def iso_ns(text):
    if str(text).isdigit():return int(text)
    dt=datetime.fromisoformat(str(text).replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('Timestamps must include a timezone')
    epoch=datetime(1970,1,1,tzinfo=timezone.utc)
    delta=dt.astimezone(timezone.utc)-epoch
    return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000

def conversation(a,known):
    for key in ['conversation.id','conversation_id','thread_id','thread.id']:
        candidate=a.get(key)
        if isinstance(candidate,str) and (candidate in known or key!='thread.id' or re.fullmatch(r'[0-9a-fA-F-]{32,36}',candidate)):
            return candidate
    return None

def documents(path,warnings):
    with Path(path).open() as stream:
        first=True;line_number=0
        while True:
            line=stream.readline()
            if not line:break
            line_number+=1
            number=stream.tell()
            if not line.strip():continue
            try:
                obj=json.loads(line)
            except json.JSONDecodeError:
                if first and line.strip() in ['{','[']:
                    try:obj=json.loads(line+stream.read())
                    except json.JSONDecodeError as exc:raise ValueError(f'{path}: Cannot parse JSON: {exc}') from exc
                    yield 1,obj
                    return
                if not stream.read(1):
                    warnings.append(f'{Path(path).name}: Ignored an incomplete trailing record')
                    return
                raise ValueError(f'{path}: Invalid record inside JSONL near byte {number}')
            first=False
            yield line_number,obj

def records(path,resource_key,scope_key,item_key,warnings):
    for line_number,obj in documents(path,warnings):
        if isinstance(obj,list):objects=obj
        else:objects=[obj]
        for document in objects:
            for resource in field(document,resource_key,[]):
                common=attributes(resource.get('resource',{}).get('attributes',[]))
                for scope in field(resource,scope_key,[]):
                    for item in field(scope,item_key,[]):yield line_number,item,common

def read(log_paths,trace_paths):
    events=[];spans=[];warnings=[];known=set();names=Counter()
    for path in log_paths:
        for line,item,common in records(path,'resourceLogs','scopeLogs','logRecords',warnings):
            a={**common,**attributes(item.get('attributes',[]))}
            cid=conversation(a,known)
            if cid:known.add(cid)
            observed=int(field(item,'observedTimeUnixNano',0) or 0)
            when=int(field(item,'timeUnixNano',0) or 0)
            if not when and a.get('event.timestamp'):
                try:when=iso_ns(a['event.timestamp'])
                except (ValueError,TypeError):pass
            when=when or observed
            if not observed:observed=when
            events.append({'attrs':a,'conversation':cid,'time_ns':when,'observed_ns':observed,
                           'span_id':field(item,'spanId'),'trace_id':field(item,'traceId'),
                           'source':{'file':str(Path(path).resolve()),'line':line}})
    wanted={(e['trace_id'],e['span_id']) for e in events}
    seen_spans=set()
    for path in trace_paths:
        for line,item,common in records(path,'resourceSpans','scopeSpans','spans',warnings):
            name=item.get('name','');names[name]+=1
            key=(field(item,'traceId'),field(item,'spanId'))
            if name not in NAMES and key not in wanted:continue
            if all(key) and key in seen_spans:continue
            seen_spans.add(key)
            a={**common,**attributes(item.get('attributes',[]))}
            correlations=[attributes(e.get('attributes',[])) for e in item.get('events',[])]
            for attribute in ['conversation.id','call_id','turn_id']:
                candidates={c[attribute] for c in correlations if isinstance(c.get(attribute),str)}
                if attribute not in a and len(candidates)==1:a[attribute]=candidates.pop()
            lo=int(field(item,'startTimeUnixNano',0) or 0);hi=int(field(item,'endTimeUnixNano',0) or 0)
            if lo<=0 or hi<lo:
                warnings.append(f'{Path(path).name}:{line}: Invalid span timestamps');continue
            cid=conversation(a,known)
            if cid:known.add(cid)
            spans.append({'name':name,'start_ns':lo,'end_ns':hi,'attrs':a,'conversation':cid,
                          'span_id':key[1],'trace_id':key[0],
                          'source':{'file':str(Path(path).resolve()),'line':line}})
    index={(s['trace_id'],s['span_id']):s for s in spans}
    for e in events:
        if not e['conversation']:
            e['conversation']=index.get((e['trace_id'],e['span_id']),{}).get('conversation')
    return {'events':events,'spans':spans,'warnings':warnings,'span_names':dict(names)}

def inventory(data):
    ids=sorted({e['conversation'] for e in data['events'] if e['conversation']}|{s['conversation'] for s in data['spans'] if s['conversation']})
    result=[]
    for cid in ids:
        events=[e for e in data['events'] if e['conversation']==cid]
        turns=[s for s in data['spans'] if s['conversation']==cid and s['name']=='session_task.turn']
        result.append({'conversation_id':cid,'event_count':len(events),
          'event_names':dict(Counter(e['attrs'].get('event.name','unknown') for e in events)),
          'turns':[{'span_id':s['span_id'],'turn_id':s['attrs'].get('turn.id',s['attrs'].get('turn_id')),
                    'start_ns':s['start_ns'],'end_ns':s['end_ns'],'seconds':(s['end_ns']-s['start_ns'])/1e9} for s in sorted(turns,key=lambda s:s['start_ns'])]})
    return {'conversations':result,'warnings':data['warnings'],
            'analysis_span_names':{k:v for k,v in data['span_names'].items() if k in NAMES},
            'other_span_name_count':len(set(data['span_names'])-NAMES)}

def union(intervals):
    merged=[]
    for lo,hi in sorted((a,b) for a,b in intervals if b>a):
        if merged and lo<=merged[-1][1]:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:merged.append((lo,hi))
    return merged

def length(intervals):return sum(b-a for a,b in union(intervals))

def parse_arguments(raw):
    if isinstance(raw,dict):return raw
    try:return json.loads(raw or '{}')
    except (ValueError,TypeError):return {'unparsed_arguments':str(raw)}

def files_in(arguments):
    text=arguments.get('cmd','')
    written=re.findall(r'cat\s+>{1,2}\s+[\"\']?([^\s\"\']+)',text)
    patch=arguments.get('patch',arguments.get('input',''))
    if not isinstance(patch,str):patch=''
    written+=re.findall(r'^\*\*\* (?:Add|Update) File: (.+)$',patch,re.M)
    related=re.findall(r'(?:[\w.\-\u4e00-\u9fa0\u3041-\u3093\u30a1-\u30f6]+/)+[\w.\-\u4e00-\u9fa0\u3041-\u3093\u30a1-\u30f6]+',text)
    return list(dict.fromkeys(written)),list(dict.fromkeys(related))[:30]

def analyze(data,cid,turn_id=None,start=None,end=None):
    ids=[x['conversation_id'] for x in inventory(data)['conversations']]
    if cid is None:
        if len(ids)!=1:raise ValueError('Select a conversation explicitly; use inspect to list candidates: '+', '.join(ids))
        cid=ids[0]
    if cid not in ids:raise ValueError('No records exist for the selected conversation')
    spans=[s for s in data['spans'] if s['conversation']==cid]
    events=[e for e in data['events'] if e['conversation']==cid]
    turns=[s for s in spans if s['name']=='session_task.turn']
    if turn_id:
        selected=[s for s in turns if s['span_id']==turn_id]
        if len(selected)!=1:raise ValueError('No completed span exists for the selected turn; select a period using explicit bounds or event timestamps')
        left,right=selected[0]['start_ns'],selected[0]['end_ns']
    else:
        bounds=[e['observed_ns'] for e in events if e['observed_ns']]+[n for s in spans for n in [s['start_ns'],s['end_ns']]]
        if not spans:
            bounds += [e['observed_ns']-int(e['attrs'].get('duration_ms',0) or 0)*10**6 for e in events if e['attrs'].get('event.name')=='codex.tool_result']
        if not bounds:raise ValueError('No timestamped events exist')
        left,right=min(bounds),max(bounds)
    if start is not None:left=start
    if end is not None:right=end
    if right<left:raise ValueError('The end time must be at or after the start time')
    warnings=list(data['warnings'])
    if right==left:warnings.append('Only one timestamp is recorded; work duration is unconfirmed')
    if not turns:warnings.append('No completed turn span exists for the selected conversation; the range uses recorded event timestamps')
    selected_events=[e for e in events if left<=e['observed_ns']<=right]
    selected_spans=[s for s in spans if s['end_ns']>left and s['start_ns']<right]
    samples=sorted([s for s in selected_spans if s['name']=='codex.sampling'],key=lambda s:s['start_ns'])
    cells=[s for s in selected_spans if s['name']=='code_mode.handler.execute']
    wrappers={s['attrs'].get('call_id') for s in cells}
    trace_index={(s['trace_id'],s['span_id']):s for s in data['spans']}
    exec_spans={s['attrs'].get('call_id'):s for s in spans if s['name']=='unified_exec.exec_command'}
    tool_events=[e for e in selected_events if e['attrs'].get('event.name')=='codex.tool_result']
    if not cells:
        inferred=0
        for e in tool_events:
            a=e['attrs'];raw=a.get('arguments','')
            if a.get('tool_name')!='exec' or not isinstance(raw,str) or not re.search(r'\btools\.',raw):continue
            begin=e['observed_ns']-int(a.get('duration_ms',0) or 0)*10**6
            if any(x['attrs'].get('tool_name')!='exec' and begin<=x['observed_ns']<=e['observed_ns'] for x in tool_events):
                wrappers.add(a.get('call_id'));inferred+=1
        if inferred:warnings.append(f'{inferred} outer exec wrappers were inferred from arguments and inner-event timing to avoid double counting')
    tools=[];seen=set()
    for e in tool_events:
        a=e['attrs'];call_id=a.get('call_id')
        dedup=(call_id,e['observed_ns'],a.get('tool_result_seq'))
        if dedup in seen:continue
        seen.add(dedup)
        if call_id in wrappers and a.get('tool_name')=='exec':continue
        arguments=parse_arguments(a.get('arguments'))
        output=str(a.get('output',''))
        trace=trace_index.get((e['trace_id'],e['span_id']))
        duration=int(a.get('duration_ms',0) or 0)
        lo=trace['start_ns'] if trace else e['observed_ns']-duration*10**6
        hi=trace['end_ns'] if trace else e['observed_ns']
        code=re.search(r'Process exited with code (-?\d+)',output)
        running=re.search(r'Process running with session ID (\d+)',output)
        written,related=files_in(arguments)
        tools.append({'id':f't{len(tools)+1:04d}','name':str(a.get('tool_name','unknown')),
          'call_id':call_id,'sequence':a.get('tool_result_seq'),'arguments':arguments,'output':output,
          'output_truncated':a.get('output_truncated') in [True,'true','True'],
          'tool_success':a.get('success') in [True,'true','True'],
          'shell_exit_code':int(code[1]) if code else None,'running_session_id':int(running[1]) if running else None,
          'start_ns':lo,'end_ns':hi,'observed_ns':e['observed_ns'],'duration_ms':duration,
          'timing_source':'trace' if trace else 'event_duration_and_observed_end',
          'files_written':written,'files_referenced':related,'source':e['source']})
    actions=[];assigned=set()
    completions=[e for e in selected_events if e['attrs'].get('ttft_ms') is not None]
    for sample in samples:
        matching=[c for c in cells if sample['start_ns']<=c['start_ns']<=sample['end_ns']]
        owned=[]
        for t in tools:
            possible=[c for c in cells if c['start_ns']<=t['observed_ns']<=c['end_ns']]
            if len(possible)==1 and possible[0] in matching and t['id'] not in assigned:owned.append(t)
        # For direct tools, containment is only used when the complete call fits.
        if not matching:
            owned=[t for t in tools if t['id'] not in assigned and sample['start_ns']<=t['start_ns'] and t['end_ns']<=sample['end_ns']]
        assigned.update(t['id'] for t in owned)
        completion=min(completions,key=lambda e:abs(e['time_ns']-sample['end_ns'])) if completions else None
        if completion and abs(completion['time_ns']-sample['end_ns'])>200_000_000:completion=None
        written=list(dict.fromkeys(f for t in owned for f in t['files_written']))
        actions.append({'id':'','kind':'response','start_ns':max(left,sample['start_ns']),'end_ns':min(right,sample['end_ns']),
          'title_candidate':('Created or modified: '+', '.join(written[:3])) if written else 'Response and associated operations',
          'tool_ids':[t['id'] for t in owned],'files_written':written,
          'ttft_seconds':int(completion['attrs']['ttft_ms'])/1000 if completion else None,
          'source':sample['source'],'span_id':sample['span_id']})
    for t in tools:
        if t['id'] in assigned:continue
        title=t['arguments'].get('cmd','').strip().splitlines()
        actions.append({'id':'','kind':'tool','start_ns':max(left,t['start_ns']),
          'end_ns':min(right,max(t['end_ns'],t['observed_ns'])),
          'title_candidate':title[0][:140] if title else t['name'],'tool_ids':[t['id']],
          'files_written':t['files_written'],'source':t['source']})
    actions=sorted(actions,key=lambda a:(a['start_ns'],a['end_ns']))
    for i,a in enumerate(actions,1):
        a['id']=f'a{i:04d}';a['seconds']=(a['end_ns']-a['start_ns'])/1e9
        a['start_seconds']=(a['start_ns']-left)/1e9;a['end_seconds']=(a['end_ns']-left)/1e9
    jobs=[];pending={}
    for t in sorted(tools,key=lambda t:t['observed_ns']):
        if t['name']=='exec_command' and t['running_session_id'] is not None:
            sid=t['running_session_id']
            if sid in pending:warnings.append(f'Duplicate start records for session {sid}')
            span=exec_spans.get(t['call_id'])
            job={'id':f'j{len(jobs)+1:04d}','session_id':sid,'start_ns':span['start_ns'] if span else t['start_ns'],
                 'end_ns':right,'end_observed':False,'exit_code':None,'start_tool_id':t['id'],'end_tool_id':None,
                 'command':t['arguments'].get('cmd',''),'source':t['source']}
            jobs.append(job);pending[sid]=job
        elif t['name']=='write_stdin' and t['shell_exit_code'] is not None:
            sid=t['arguments'].get('session_id')
            if sid in pending:
                job=pending.pop(sid);job.update(end_ns=t['observed_ns'],end_observed=True,
                  exit_code=t['shell_exit_code'],end_tool_id=t['id'])
    for job in jobs:
        job['seconds']=(job['end_ns']-job['start_ns'])/1e9
    if pending:warnings.append(f'{len(pending)} background jobs have no observed completion')
    if not samples:warnings.append('No codex.sampling spans exist; response interval durations are unconfirmed')
    if not actions:warnings.append('No records support an activity or tool breakdown')
    ranges=[(max(left,s['start_ns']),min(right,s['end_ns'])) for s in selected_spans if s['name']=='handle_tool_call_with_source']
    models=[(a['start_ns'],a['end_ns']) for a in actions if a['kind']=='response']
    mn,tn=length(models),length(ranges);overlap=mn+tn-length(models+ranges)
    return {'schema_version':1,'analysis_id':hashlib.sha256(f'{cid}:{left}:{right}'.encode()).hexdigest()[:20],
      'scope':{'conversation_id':cid,'turn_span_id':turn_id,'start_ns':left,'end_ns':right,'seconds':(right-left)/1e9,
               'elapsed_status':'observed_window' if right>left else 'unconfirmed'},
      'actions':actions,'tools':tools,'jobs':jobs,'warnings':list(dict.fromkeys(warnings)),
      'counts':{'actions':len(actions),'response_intervals':len(samples),'inner_tools':len(tools),
        'background_jobs':len(jobs),'truncated_outputs':sum(t['output_truncated'] for t in tools)},
      'technical_seconds':{'response_union':mn/1e9 if samples else None,
        'tool_union':tn/1e9 if ranges else None,
        'overlap':overlap/1e9 if samples and ranges else None,
        'outside_response_and_tools':((right-left)-length(models+ranges))/1e9 if samples and ranges else None}}
