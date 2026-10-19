"""Validate semantic review and render a local, inspectable work report."""
from collections import defaultdict
from datetime import datetime, timezone
from html import escape as h
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

def duration(s):
    minutes,seconds=divmod(s,60)
    return f'{int(minutes)}m {seconds:04.1f}s' if minutes else f'{seconds:.3f}s'

def text(value):return h(str(value))

def work_timeline_data(data,review,stages):
    """Use reviewed semantic lanes, with intervals derived only from OTel evidence."""
    actions={a['id']:a for a in data['actions']};jobs={j['id']:j for j in data['jobs']}
    origin=data['scope']['start_ns'];seen={s['id'] for s in stages};used_actions=set();used_jobs=set();lanes=[]
    if 'timeline' in review and actions and not review['timeline'].get('lanes'):
        raise ValueError('timeline requires lanes grouped by the meaning of the work')
    def interval(source):
        return {'start':(source['start_ns']-origin)/1e9,'end':(source['end_ns']-origin)/1e9}
    def ident(value):
        if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',value) or value in seen:raise ValueError('Timeline IDs must be unique and contain letters, digits, underscores, or hyphens')
        seen.add(value)
    for lane in review.get('timeline',{}).get('lanes',[]):
        ident(lane.get('id',''))
        if not lane.get('title') or lane.get('kind') not in ['implementation','fix','execution','documentation','investigation']:
            raise ValueError('Each timeline lane requires a title and valid kind')
        items=[]
        for item in lane.get('items',[]):
            ident(item.get('id',''));aids=item.get('action_ids',[]);jids=item.get('job_ids',[])
            if not item.get('title') or not item.get('summary'):raise ValueError('Each timeline activity requires a title and summary')
            if bool(aids)==bool(jids):raise ValueError('Time evidence must use either action_ids or job_ids, exclusively')
            if set(aids)-actions.keys() or set(jids)-jobs.keys():raise ValueError('A timeline evidence ID does not exist')
            if used_actions.intersection(aids) or used_jobs.intersection(jids) or len(set(aids))!=len(aids) or len(set(jids))!=len(jids):
                raise ValueError('Do not assign the same time evidence to multiple timeline activities')
            used_actions.update(aids);used_jobs.update(jids)
            sources=[actions[a] for a in aids]+[jobs[j] for j in jids]
            # Merge overlaps, but retain real gaps instead of painting them as work.
            segments=[]
            for source in sorted(sources,key=lambda s:s['start_ns']):
                segment=interval(source)
                if segments and segment['start']<=segments[-1]['end']:
                    segments[-1]['end']=max(segments[-1]['end'],segment['end'])
                else:segments.append(segment)
            files=sorted({f for aid in aids for f in review['action_labels'][aid].get('files',actions[aid]['files_written'])})
            results=[f'{jid}: '+('Exit code '+str(jobs[jid]['exit_code']) if jobs[jid]['end_observed'] else 'Completion unconfirmed; the endpoint is the capture boundary') for jid in jids]
            items.append({**item,'segments':segments,'start':segments[0]['start'],'end':segments[-1]['end'],
                'seconds':sum(s['end']-s['start'] for s in segments),'files':files,
                'kind':lane['kind'],'results':results,
                'failed':any(jobs[j]['end_observed'] and jobs[j]['exit_code']!=0 for j in jids),
                'unconfirmed':any(not jobs[j]['end_observed'] for j in jids),
                'basis':'Recorded response or tool-operation intervals, including communication, generation, and reception. Gaps are excluded and overlaps merged.' if aids else 'From command launch to observed completion. An unconfirmed job is dotted through the capture boundary; continuous execution across that interval is not established.',
                'evidence':[{'id':a,'target':a,'title':review['action_labels'][a]['title']} for a in aids]+
                  [{'id':j,'target':jobs[j]['start_tool_id'],'title':j+' launch command and output'} for j in jids]})
        if not items:raise ValueError('Each timeline lane requires evidence-backed activities')
        lanes.append({**lane,'items':items})
    return {'stages':[{**s,'groups':[],**interval(s)} for s in stages],
      'lanes':lanes,'scope':data['scope'],
      'start_epoch_ms':origin/1e6}

def work_timeline_html():
    return '''<h3 id="work-timeline">Stage and activity timeline</h3>
<p>Major stages appear on the top row, followed by semantic lanes for implementation, fixes, execution, and other work. Bars at the same time show concurrent activities. Select a stage to zoom in, then select an activity to inspect its content, files, and evidence.</p>
<div class="timeline-toolbar"><label for="work-range">View range <select id="work-range"><option value="all">Entire run</option></select></label><button id="work-zoom" type="button">Zoom to selection</button><button id="work-reset" type="button">Reset view</button></div>
<p class="mb-meta-line" id="work-range-label"></p>
<figure class="mb-figure"><div class="mb-figure-frame chart-frame"><svg xmlns="http://www.w3.org/2000/svg" class="work-chart" id="work-chart" viewBox="0 0 1160 620" role="group" aria-labelledby="work-title work-description"><title id="work-title">Timeline of major stages and activities</title><desc id="work-description">Major stages and semantic implementation and execution lanes share a time axis. Select a bar to inspect details.</desc></svg></div><figcaption>Figure 1. Stages with implementation and execution. Implementation bars represent recorded response or operation intervals; execution bars run from launch to observed completion. These intervals overlap and must not be added. Dotted bars indicate unconfirmed completion. Scroll within the chart on narrow screens.</figcaption></figure>
<div class="timeline-legend"><span>Gray: implementation or documentation</span><span>White: investigation or execution</span><span>Dashed: fixes or failed executions</span><span>Dotted: unconfirmed completion</span></div>
<section class="mb-card" aria-live="polite"><div class="mb-card-label">Selected stage or activity</div><h3 id="work-detail-title">Entire run</h3><p id="work-detail-description">Select a bar to display its description and evidence.</p><dl id="work-detail-values" class="detail-grid"></dl><p id="work-detail-evidence"></p><button id="work-open-detail" type="button">Open stage breakdown</button></section>'''

def stage_timeline(data,stages,clock):
    """Show one semantic stage per row; operation detail stays below the overview."""
    total=data['scope']['seconds'];origin=data['scope']['start_ns']
    if total<=0:
        return '<svg class="work-chart" id="work-chart" viewBox="0 0 1160 100" role="img" aria-label="Major-stage timeline"><text x="16" y="55">The records do not establish stages and durations.</text></svg>'
    def wrap_title(value,limit=48):
        lines=[];line='';width=0
        for char in value:
            cells=2 if unicodedata.east_asian_width(char) in 'WF' else 1
            if line and width+cells>limit:lines.append(line);line='';width=0
            line+=char;width+=cells
        if line:lines.append(line)
        return lines or ['']
    rows=[];y=64
    for index,stage in enumerate(stages,1):
        lines=wrap_title(f'{index}. {stage["title"]}')
        height=max(82,len(lines)*21+36)
        rows.append((stage,y,height,lines));y+=height
    height=y+18;left=440;right=1138
    x=lambda seconds:left+seconds/total*(right-left)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" class="work-chart" id="work-chart" viewBox="0 0 1160 {height}" role="group" aria-label="Timeline of the major work stages">',
      '<title>Work overview: stage time ranges and durations</title>',
      '<text x="16" y="23" font-size="14">Stage, time range, and duration</text>',
      f'<text x="{left}" y="23" font-size="13">Elapsed time from start</text>']
    for i in range(6):
        seconds=round(total*i/5);px=x(total*i/5);minutes,seconds=divmod(seconds,60)
        anchor='start' if i==0 else 'end' if i==5 else 'middle'
        parts.append(f'<line x1="{px:.3f}" x2="{px:.3f}" y1="59" y2="{y}" stroke="#DFDFDF"/>')
        parts.append(f'<text x="{px:.3f}" y="47" font-size="12" text-anchor="{anchor}">{minutes}m {seconds:02d}s</text>')
    for stage,top,row_height,lines in rows:
        sid=text(stage['id']);seconds=(stage['end_ns']-stage['start_ns'])/1e9
        start=(stage['start_ns']-origin)/1e9;end=(stage['end_ns']-origin)/1e9
        label=f'{stage["title"]}, {duration(seconds)}, {seconds/total*100:.1f}% of total. Open breakdown'
        parts.append(f'<g class="stage-chart-row" role="button" tabindex="0" data-stage-id="{sid}" data-reveal="{sid}" aria-controls="{sid}" aria-label="{text(label)}">')
        parts.append(f'<title>{text(label)}</title><line x1="16" x2="{right}" y1="{top+row_height}" y2="{top+row_height}" stroke="#DFDFDF"/>')
        parts.append('<text x="16" y="'+str(top+22)+'" font-size="15">'+''.join(f'<tspan x="16" dy="{0 if i==0 else 21}">{text(line)}</tspan>' for i,line in enumerate(lines))+'</text>')
        meta=f'{clock(stage["start_ns"])[11:19]}–{clock(stage["end_ns"])[11:19]} / {duration(seconds)} / {seconds/total*100:.1f}%'
        parts.append(f'<text x="16" y="{top+len(lines)*21+23}" font-size="12" class="mono">{text(meta)}</text>')
        bar_y=top+row_height/2-14
        parts.append(f'<rect x="{x(start):.3f}" y="{bar_y:.3f}" width="{max(2,x(end)-x(start)):.3f}" height="28" rx="3" fill="#FFFFFF" stroke="#111110"/>')
        parts.append('</g>')
    return ''.join(parts)+'</svg>'

def validate(data,review):
    if review.get('analysis_id')!=data['analysis_id']:raise ValueError('The review and analysis IDs do not match')
    if review.get('semantic_review_complete') is not True:raise ValueError('Review activity labels, stages, and suggestions, then set semantic_review_complete to true')
    for key in ['title','objective','conclusion','improvement_note']:
        if not isinstance(review.get(key),str) or not review[key].strip():raise ValueError(f'review requires {key}')
    if review.get('improvement_status') not in ['supported_proposals','no_supported_proposals']:raise ValueError('Invalid improvement_status')
    actions={a['id']:a for a in data['actions']};jobs={j['id']:j for j in data['jobs']}
    labels=review.get('action_labels',{})
    if set(labels)!=set(actions):raise ValueError('Every action requires an action_labels entry')
    for label in labels.values():
        if not label.get('title') or not isinstance(label.get('summary'),str):raise ValueError('Every activity requires a title and summary')
        if 'files' in label and (not isinstance(label['files'],list) or not all(isinstance(f,str) for f in label['files'])):raise ValueError('files must be an array of created or modified path strings')
    cursor=data['scope']['start_ns'];stages=[];owners={};stage_ids=set()
    for s in review.get('stages',[]):
        sid=s.get('id','')
        if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]*',sid) or sid in stage_ids:raise ValueError('Stage IDs must be unique and contain letters, digits, underscores, or hyphens')
        stage_ids.add(sid)
        lo=data['scope']['start_ns']+round(float(s['start_seconds'])*1e9)
        hi=data['scope']['start_ns']+round(float(s['end_seconds'])*1e9)
        if abs(lo-cursor)>1000 or hi<lo or (hi==lo and data['scope']['seconds']>0):raise ValueError('Stage ranges contain a gap, overlap, or reversed interval')
        lo=cursor
        for i,g in enumerate(s.get('groups',[])):
            if not g.get('title'):raise ValueError('Each breakdown group requires a title')
            for aid in g['action_ids']:
                if aid not in actions or aid in owners:raise ValueError('Unknown or multiply assigned action: '+aid)
                a=actions[aid]
                if a['end_ns']<lo or a['start_ns']>hi:raise ValueError('The action does not overlap its assigned stage: '+aid)
                owners[aid]=(sid,str(i))
        stages.append({**s,'start_ns':lo,'end_ns':hi});cursor=hi
    if not stages or abs(cursor-data['scope']['end_ns'])>1000:raise ValueError('Stages must cover the entire selected period')
    stages[-1]['end_ns']=data['scope']['end_ns']
    if set(owners)!=set(actions):raise ValueError('Assign every action to exactly one breakdown group')
    proposals=0
    for finding in review.get('findings',[]):
        aids=finding.get('action_ids',[]);jids=finding.get('job_ids',[])
        if not aids and not jids:raise ValueError('Each finding requires action or job evidence')
        if set(aids)-set(actions) or set(jids)-set(jobs):raise ValueError('A finding evidence ID does not exist')
        for key in ['title','observation','impact','confidence']:
            if not finding.get(key):raise ValueError('A finding requires '+key)
        if finding.get('proposal'):
            for key in ['instruction_area','text','expected_effect','tradeoff','validation']:
                if not finding['proposal'].get(key):raise ValueError('A proposal requires '+key)
            proposals+=1
    if (review['improvement_status']=='supported_proposals')!=(proposals>0):raise ValueError('The presence of proposals does not match improvement_status')
    work_timeline_data(data,review,stages)
    return stages,owners

def partition(data,stage,owners):
    lo,hi=stage['start_ns'],stage['end_ns'];events=defaultdict(list)
    for a in data['actions']:
        left,right=max(lo,a['start_ns']),min(hi,a['end_ns'])
        if left>=right:continue
        owner,group=owners[a['id']]
        category=group if owner==stage['id'] else 'boundary'
        events[left].append((category,1));events[right].append((category,-1))
    events[lo];events[hi];active=defaultdict(int);totals=defaultdict(int);previous=lo
    for when,changes in sorted(events.items()):
        categories=[k for k,v in active.items() if v>0]
        key=categories[0] if len(categories)==1 else 'parallel' if categories else 'outside'
        totals[key]+=when-previous
        for key,change in changes:active[key]+=change
        previous=when
    assert sum(totals.values())==hi-lo
    return {k:v/1e9 for k,v in totals.items()}

def render(data,review,timezone_name):
    stages,owners=validate(data,review);zone=ZoneInfo(timezone_name)
    elapsed=duration(data['scope']['seconds']) if data['scope']['seconds']>0 else 'Unconfirmed (single timestamp)'
    actions={a['id']:a for a in data['actions']};tools={t['id']:t for t in data['tools']}
    def clock(ns):return datetime.fromtimestamp(ns/1e9,zone).isoformat(timespec='milliseconds')
    def para(s):return '<p>'+text(s)+'</p>'
    def code(s,language='plaintext'):return f'<pre><code class="language-{language}">{text(s)}</code></pre>'
    def action_link(aid):return f'<a href="#{aid}" data-reveal="{aid}">{aid}</a>'
    def tool_html(t):
        args=t['arguments'];command=args.get('cmd');language='bash' if command is not None else 'json'
        content=command if command is not None else json.dumps(args,ensure_ascii=False,indent=2)
        status=f'Exit code {t["shell_exit_code"]}' if t['shell_exit_code'] is not None else 'Still running' if t['running_session_id'] is not None else 'No recorded exit code'
        note=para('Output was truncated during capture. Only the saved portion is shown.') if t['output_truncated'] else ''
        return f'''<details class="tool-entry" id="{t['id']}"><summary>{text(t['name'])} / Call duration {t['duration_ms']/1000:.3f}s / {text(status)}</summary>
<p class="mb-meta-line">Result observed {clock(t['observed_ns'])} / Source log {text(Path(t['source']['file']).name)}:{t['source']['line']}</p>
<p class="small-note">Call duration differs from the total duration of a background job.</p><h4>Arguments and command</h4>{code(content,language)}<h4>Captured output</h4>{note}{code(t['output'])}</details>'''
    def action_html(aid):
        a=actions[aid];label=review['action_labels'][aid]
        files=label.get('files',a['files_written'])
        file_text=', '.join('<code>'+text(f)+'</code>' for f in files) or 'No confirmed created or modified paths'
        calls=''.join(tool_html(tools[tid]) for tid in a['tool_ids']) or para('No tool calls are associated with this interval.')
        basis='Response interval, including communication, generation, and reception' if a['kind']=='response' else 'Recorded tool-operation interval'
        return f'''<details class="action-entry" id="{aid}"><summary><strong>{text(label['title'])}</strong> <span class="mono">{duration(a['seconds'])}</span></summary>
<p class="mb-meta-line">{clock(a['start_ns'])}–{clock(a['end_ns'])} / {basis}</p>{para(label['summary'])}<p>Created or modified: {file_text}</p>
<details><summary>Open commands and output ({len(a['tool_ids'])} calls)</summary>{calls}</details></details>'''
    overview=[];details=[];stage_metrics=[]
    for stage in stages:
        sid=stage['id'];seconds=(stage['end_ns']-stage['start_ns'])/1e9;totals=partition(data,stage,owners)
        stage_metrics.append({'stage_id':sid,'seconds':seconds,'partition_seconds':totals})
        stage_elapsed=duration(seconds) if data['scope']['seconds']>0 else 'Unconfirmed'
        overview.append(f'<tr><td class="mb-rowlabel"><strong>{text(stage["title"])}</strong><br><button data-reveal="{sid}">View breakdown</button></td><td><span class="mono">{clock(stage["start_ns"])[11:19]}–{clock(stage["end_ns"])[11:19]}</span><br>{stage_elapsed}</td><td>{text(stage["summary"])}</td></tr>')
        rows=[];action_ids=[]
        for i,g in enumerate(stage['groups']):
            action_ids+=g['action_ids']
            rows.append(f'<tr><td class="mb-rowlabel">{text(g["title"])}</td><td class="mono">{duration(totals.get(str(i),0))}</td><td>'+ ', '.join(action_link(aid) for aid in g['action_ids'])+'</td></tr>')
        for key,label in [('boundary','Activities crossing stage boundaries'),('parallel','Concurrent breakdown groups'),('outside','Outside associated activity intervals')]:
            if totals.get(key,0):rows.append(f'<tr><td class="mb-rowlabel">{label}</td><td class="mono">{duration(totals[key])}</td><td>Accounted separately to avoid double counting</td></tr>')
        rows.append(f'<tr><td class="mb-rowlabel"><strong>Stage total</strong></td><td class="mono">{stage_elapsed}</td><td>'+('Verified using unrounded values' if data['scope']['seconds']>0 else 'Insufficient records to reconstruct the stage')+'</td></tr>')
        job_rows=[]
        for job in data['jobs']:
            overlap=max(0,min(job['end_ns'],stage['end_ns'])-max(job['start_ns'],stage['start_ns']))/1e9
            if not overlap:continue
            status='Exit code '+str(job['exit_code']) if job['end_observed'] else 'Completion unconfirmed; shown through capture end'
            head=job['command'].strip().splitlines()
            job_rows.append(f'<tr id="{job["id"]}-{sid}"><td class="mb-rowlabel"><a href="#{job["start_tool_id"]}" data-reveal="{job["start_tool_id"]}">{job["id"]}</a></td><td>{duration(job["seconds"])}<br><span class="small-note">Overlap with this stage: {duration(overlap)}</span></td><td>{text(status)}<br>{text(head[0][:100] if head else "No recorded command")}</td></tr>')
        jobs_html=table(['Execution','Observed job interval','Result and command prefix'],job_rows) if job_rows else para('No recorded background jobs overlap this stage.')
        details.append(f'''<details class="stage-entry" id="{sid}"><summary><strong>{text(stage['title'])}</strong><span class="mono">{stage_elapsed}</span></summary>
{para(stage['summary'])}<h3>Breakdown by activity</h3><p class="small-note">Overlaps within each group are merged, while concurrency between groups is accounted for separately. These are not pure editing durations. Open an activity to inspect its full interval.</p>
{table(['Breakdown','Time within this stage','Open activities'],rows)}<h3>Concurrent executions</h3><p class="small-note">Do not add these intervals to the breakdown above. Job endpoints are completion-observation times.</p>{jobs_html}
<details><summary>Open individual activities in time order ({len(action_ids)} activities)</summary>{''.join(action_html(aid) for aid in sorted(action_ids,key=lambda aid:actions[aid]['start_ns']))}</details></details>''')
    findings=[]
    for i,f in enumerate(review.get('findings',[]),1):
        evidence=', '.join(action_link(aid) for aid in f.get('action_ids',[]))
        for jid in f.get('job_ids',[]):
            job=next(j for j in data['jobs'] if j['id']==jid)
            evidence+=f' <a href="#{job["start_tool_id"]}" data-reveal="{job["start_tool_id"]}">{jid}</a>'
        proposal=f.get('proposal');extra=''
        if proposal:
            extra=f'<h4>Proposed task-instruction changes</h4>{para(proposal["instruction_area"])}<blockquote class="mb-quote">{para(proposal["text"])}</blockquote><h4>Expected effect and conditions</h4>{para(proposal["expected_effect"])}{para(proposal["tradeoff"])}<h4>Next-run comparison metrics</h4>{para(proposal["validation"])}'
        findings.append(f'<section class="mb-card"><h3>{i}. {text(f["title"])}</h3><p class="small-note">Evidence confidence: {text(f["confidence"])}</p>{para(f["observation"])}{para(f["impact"])}<p>Evidence: {evidence}</p>{extra}</section>')
    if not findings:findings=[para('These records do not establish supported findings or suggestions.')]
    warnings=''.join('<li>'+text(w)+'</li>' for w in data['warnings']) or '<li>Extraction produced no warnings. This does not establish that unrecorded operations did not occur.</li>'
    payload=work_timeline_data(data,review,stages)
    payload['timezone_name']=timezone_name
    timeline=work_timeline_html() if payload['lanes'] else f'<figure class="mb-figure"><div class="mb-figure-frame chart-frame">{stage_timeline(data,stages,clock)}</div><figcaption>Figure 1. Stage time ranges and durations. Select a stage to inspect its breakdown.</figcaption></figure>'
    timeline_script=(Path(__file__).parent/'work_timeline.js').read_text() if payload['lanes'] else ''
    chart_data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')
    html=f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{text(review['title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Ubuntu+Sans:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700&family=Ubuntu+Mono:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="./design-system/document.css"><script src="./design-system/math-copy.js"></script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script><script async src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/highlight.min.js" onload="hljs.highlightAll()"></script>
<style>.table-scroll,.chart-frame{{overflow-x:auto}}.detail-table{{min-width:640px}}.mono{{font-family:var(--mb-font-mono);white-space:nowrap}}.stage-entry,.action-entry{{border-top:1px solid var(--mb-rule);padding:16px 0}}summary{{cursor:pointer}}.stage-entry>summary,.action-entry>summary{{display:flex;gap:12px;align-items:baseline}}summary strong{{flex:1;min-width:0;overflow-wrap:anywhere}}.stage-entry>summary,.action-entry>summary{{flex-wrap:wrap}}.mb-meta-line,.mb-main p,.mb-card p{{overflow-wrap:anywhere}}.action-entry{{margin-left:12px}}.tool-entry{{margin:14px 0}}.tool-entry pre{{max-height:30rem;overflow:auto}}.small-note{{font-size:13px;color:var(--mb-muted)}}button{{font:inherit;border:1px solid var(--mb-border);border-radius:6px;background:white;padding:6px 10px;cursor:pointer}}.work-chart{{width:100%;min-width:800px}}.work-chart [role=button]{{cursor:pointer}}.work-chart [role=button]:focus rect,.work-chart [data-selected=true] rect{{stroke:var(--mb-link);stroke-width:3}}.work-chart text{{font-family:var(--mb-font-sans)}}.timeline-toolbar,.timeline-legend{{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;margin:16px 0}}.timeline-toolbar select{{font:inherit;max-width:100%;padding:5px}}.timeline-toolbar label{{min-width:0}}.timeline-legend{{font-size:13px}}.detail-grid{{display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px 16px}}.detail-grid dt{{font-weight:700}}.detail-grid dd{{margin:0;overflow-wrap:anywhere}}@media(max-width:600px){{.detail-grid{{grid-template-columns:1fr}}}}.mb-card{{margin-bottom:20px}}</style></head><body><div class="mb-page"><div class="mb-hero"><header class="mb-header"><h1>{text(review['title'])}</h1></header>{para(review['objective'])}
<nav class="mb-toc"><ol><li><a href="#overview">Work overview</a></li><li><a href="#breakdown">Stage breakdowns</a></li><li><a href="#findings">Findings and suggestions</a></li><li><a href="#limits">Evidence and limitations</a></li></ol></nav>
<div class="mb-summary">{para(review['conclusion'])}</div><p class="mb-meta-line">{clock(data['scope']['start_ns'])}–{clock(data['scope']['end_ns'])} / Captured elapsed time: {elapsed} / {text(timezone_name)}</p></div>
<div class="mb-wrap"><main class="mb-main"><h2 id="overview">Work overview</h2>{timeline}
<h3>Major-stage durations and outcomes</h3>{table(['Stage','Time range and elapsed time','Work performed'],overview)}
<h2 id="breakdown">Stage breakdowns</h2><p>Expand a stage and select an activity ID or title to follow implementation and verification details through to commands and captured output.</p>{''.join(details)}
<h2 id="findings">Findings and suggestions</h2>{para(review['improvement_note'])}{''.join(findings)}
<h2 id="limits">Evidence and limitations</h2><p>Inputs are snapshots of captured OpenTelemetry. Recorded commands are displayed, not rerun. Suggested effects require comparative runs to verify.</p>
{para(review.get('instruction_context','The proposed insertion area for each suggestion describes the verified scope of the original task instructions and revision.'))}<ul>{warnings}</ul>
<p>Response intervals include communication, generation, and reception. They are not split into per-file, per-line, or pure reasoning time. The {data['counts']['truncated_outputs']} truncated outputs can be inspected only within their saved portions. Distinguish process exit codes from tool-call success flags.</p>
<details><summary>Open technical aggregates</summary><p>Units are seconds. A null value means the corresponding span or other evidence is missing; it does not mean zero seconds.</p>{code(json.dumps(data['technical_seconds'],ensure_ascii=False,indent=2),'json')}</details>
<p>Detailed data: <a href="./analysis.json">analysis.json</a> | <a href="./actions.csv" download>Activities CSV</a> | <a href="./review.json">Reviewed interpretation</a> | <a href="./source-manifest.json">Input snapshots and SHA256</a></p></main></div><footer class="mb-footer">Codex OpenTelemetry / Work analysis from captured records</footer></div>
<script id="chart-data" type="application/json">{chart_data}</script><script>
function reveal(id){{const n=document.getElementById(id);if(!n)return;for(let p=n;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;n.scrollIntoView({{block:'start'}});}}
document.querySelectorAll('[data-reveal]').forEach(n=>{{n.addEventListener('click',e=>{{e.preventDefault();reveal(n.dataset.reveal)}});if(n.getAttribute('role')==='button')n.addEventListener('keydown',e=>{{if(e.key==='Enter'||e.key===' '){{e.preventDefault();reveal(n.dataset.reveal)}}}});}});
{timeline_script}
window.telemetryReportReady=true;
</script></body></html>'''
    return html,{'result':'passed','analysis_id':data['analysis_id'],'stages':stage_metrics,
                 'overview_stages':len(stages),'timeline_lanes':len(payload['lanes']),'timeline_items':sum(len(l['items']) for l in payload['lanes']),'overview_stage_rows':0 if payload['lanes'] else len(stages),'actions':len(actions),'tools':len(tools),'findings':len(review.get('findings',[]))}

def table(headers,rows):
    return '<div class="table-scroll"><table class="detail-table"><thead><tr>'+''.join('<th'+(' class="mb-rowlabel"' if i==0 else '')+'>'+text(s)+'</th>' for i,s in enumerate(headers))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
