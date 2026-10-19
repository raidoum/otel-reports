"""Behavioral checks for selection, overlap, incomplete input and rendering."""
import json
from pathlib import Path
import tempfile
import unittest
import re
from xml.etree import ElementTree

from otlp import analyze, read
from report_html import partition, render, validate

BASE=1700000000000000000
def ns(s):return BASE+round(s*1e9)
def attrs(d):
    return [{'key':k,'value':{'boolValue':v} if isinstance(v,bool) else {'stringValue':str(v)}} for k,v in d.items()]
def event(cid,when,name='exec_command',call='c1',output='',arguments=None):
    return {'observedTimeUnixNano':str(ns(when)), 'traceId':'trace-'+cid,'spanId':'tool-'+call,
      'attributes':attrs({'conversation.id':cid,'event.name':'codex.tool_result','tool_name':name,
       'call_id':call,'duration_ms':'100','arguments':json.dumps(arguments or {}),'output':output,'success':'true','output_truncated':False})}
def span(cid,name,start,end,ident,extra=None):
    return {'traceId':'trace-'+cid,'spanId':ident,'name':name,'startTimeUnixNano':str(ns(start)),
      'endTimeUnixNano':str(ns(end)),'attributes':attrs({'conversation.id':cid,**(extra or {})})}
def files(root,events,spans):
    lp=root/'logs.jsonl';tp=root/'traces.jsonl'
    lp.write_text(json.dumps({'resourceLogs':[{'scopeLogs':[{'logRecords':events}]}]})+'\n')
    tp.write_text(json.dumps({'resourceSpans':[{'scopeSpans':[{'spans':spans}]}]})+'\n')
    return lp,tp
def review(data):
    return {'analysis_id':data['analysis_id'],'semantic_review_complete':True,'title':'CSV aggregation work analysis',
      'objective':'The work implemented CSV aggregation.','conclusion':'The recorded operations were reviewed.',
      'improvement_status':'no_supported_proposals','improvement_note':'This small capture does not establish improvement effects.',
      'action_labels':{a['id']:{'title':'Inspect aggregation','summary':'An inspection of the captured command.'} for a in data['actions']},
      'stages':[{'id':'stage-1','title':'Implementation and verification','summary':'The implementation was created and checked.','start_seconds':0,
         'end_seconds':data['scope']['seconds'],'groups':[{'title':'Implementation','action_ids':[a['id'] for a in data['actions']]}]}], 'findings':[]}

class TelemetryTests(unittest.TestCase):
    def test_semantic_timeline_preserves_gaps_and_background_parallelism(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[event('one',1,output='Process running with session ID 12',arguments={'cmd':'make build'}),
              event('one',2,call='edit',arguments={'cmd':'printf ok'}),
              event('one',4,'write_stdin','poll',output='Process exited with code 0',arguments={'session_id':12})]
            lp,tp=files(Path(folder),events,[]);data=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(5));r=review(data)
            ids=[a['id'] for a in data['actions'][:2]]
            r['action_labels'][ids[0]]['files']=['src/aggregate.py']
            r['timeline']={'lanes':[
              {'id':'lane-code','title':'Implement aggregation','kind':'implementation','items':[
                {'id':'work-code','title':'Build aggregation <check>','summary':'The implementation was verified.','action_ids':ids}]},
              {'id':'lane-build','title':'Run the build','kind':'execution','items':[
                {'id':'work-build','title':'Verify the build','summary':'Exit code 0 was observed.','job_ids':[data['jobs'][0]['id']]}]}]}
            html,check=render(data,r,'Asia/Tokyo')
            payload=json.loads(re.search(r'<script id="chart-data" type="application/json">(.*?)</script>',html,re.S)[1])
            code=payload['lanes'][0]['items'][0];job=payload['lanes'][1]['items'][0]
            self.assertEqual(len(code['segments']),2)
            self.assertAlmostEqual(code['seconds'],.2)
            self.assertLess(code['seconds'],code['end']-code['start'])
            self.assertEqual(code['files'],['src/aggregate.py'])
            self.assertEqual(code['title'],'Build aggregation <check>')
            self.assertLess(job['start'],code['end']);self.assertGreater(job['end'],code['end'])
            self.assertEqual(job['evidence'][0]['target'],data['jobs'][0]['start_tool_id'])
            self.assertEqual(check['timeline_lanes'],2);self.assertEqual(check['timeline_items'],2)
            self.assertIn('id="work-range"',html);self.assertIn('id="work-open-detail"',html)
            r['timeline']['lanes'][1]['items'][0]['job_ids']=['missing']
            with self.assertRaises(ValueError):validate(data,r)
            r['timeline']['lanes'][1]['items'][0].pop('job_ids')
            r['timeline']['lanes'][1]['items'][0]['action_ids']=ids
            with self.assertRaises(ValueError):validate(data,r)
            r['timeline']['lanes']=[]
            with self.assertRaises(ValueError):validate(data,r)

    def test_timeline_does_not_claim_an_unconfirmed_job_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1,output='Process running with session ID 12',arguments={'cmd':'make build'})],[])
            data=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(5));r=review(data)
            r['timeline']={'lanes':[{'id':'lane-build','title':'Build','kind':'execution','items':[
              {'id':'work-build','title':'Start the build','summary':'Completion is unconfirmed.','job_ids':[data['jobs'][0]['id']]}]}]}
            html,_=render(data,r,'UTC');payload=json.loads(re.search(r'<script id="chart-data" type="application/json">(.*?)</script>',html,re.S)[1])
            item=payload['lanes'][0]['items'][0]
            self.assertTrue(item['unconfirmed']);self.assertFalse(item['failed'])
            self.assertIn('Completion unconfirmed',item['results'][0])
            self.assertIn('continuous execution across that interval is not established',item['basis'])

    def test_overview_uses_stage_rows_and_retains_operation_details(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[event('one',i,call=f'c{i}',arguments={'cmd':f'printf {i}'}) for i in range(1,5)]
            lp,tp=files(Path(folder),events,[span('one','session_task.turn',0,5,'root')])
            data=analyze(read([lp],[tp]),'one');r=review(data)
            titles=['Review measurement conditions and implement TCP and UDP transmission and reception with a long stage title <check> \U0001f9ea',
                    'Verify feature startup and measurement results']
            r['stages']=[{'id':f'stage-{i+1}','title':title,'summary':'The stage outcome.',
              'start_seconds':i*2.5,'end_seconds':(i+1)*2.5,
              'groups':[{'title':'Implementation details','action_ids':[a['id'] for a in data['actions'][i*2:(i+1)*2]]}]}
              for i,title in enumerate(titles)]
            html,check=render(data,r,'UTC')
            svg=ElementTree.fromstring(re.search(r'<svg\b.*?</svg>',html,re.S)[0])
            rows=[node for node in svg if 'data-stage-id' in node.attrib]
            self.assertEqual([node.attrib['data-stage-id'] for node in rows],['stage-1','stage-2'])
            self.assertEqual(check['overview_stage_rows'],2)
            bars=[next(node for node in row if node.tag.endswith('rect')) for row in rows]
            self.assertLess(float(bars[0].attrib['y']),float(bars[1].attrib['y']))
            self.assertEqual(bars[0].attrib['width'],bars[1].attrib['width'])
            self.assertAlmostEqual(float(bars[0].attrib['x'])+float(bars[0].attrib['width']),float(bars[1].attrib['x']),places=2)
            for row,title in zip(rows,titles):
                wrapped=''.join(node.text or '' for node in row.iter() if node.tag.endswith('tspan'))
                self.assertIn(title,wrapped)
                self.assertEqual(row.attrib['aria-controls'],row.attrib['data-stage-id'])
            payload=json.loads(re.search(r'<script id="chart-data" type="application/json">(.*?)</script>',html,re.S)[1])
            self.assertEqual([s['title'] for s in payload['stages']],titles)
            self.assertNotIn('actions',payload)
            self.assertNotIn('jobs',payload)
            for action in data['actions']:self.assertIn(f'id="{action["id"]}"',html)

    def test_conversation_selection_does_not_choose_longest(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1),event('two',2)],[span('one','session_task.turn',0,3,'r1'),span('two','session_task.turn',0,30,'r2')])
            d=read([lp],[tp])
            with self.assertRaises(ValueError):analyze(d,None)
            self.assertEqual(analyze(d,'one')['scope']['seconds'],3)

    def test_nested_wrappers_are_not_extra_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[event('one',1.8,arguments={'cmd':'printf ok'}),event('one',1.9,'exec','outer')]
            spans=[span('one','session_task.turn',0,3,'root'),span('one','codex.sampling',0,2,'model'),span('one','code_mode.handler.execute',1,1.95,'cell',{'call_id':'outer'})]
            lp,tp=files(Path(folder),events,spans);d=analyze(read([lp],[tp]),'one')
            self.assertEqual((len(d['actions']),len(d['tools'])),(1,1))
            self.assertEqual(d['actions'][0]['tool_ids'],['t0001'])

    def test_background_exit_is_not_tool_success(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[event('one',1,output='Process running with session ID 12',arguments={'cmd':'make build'}),
              event('one',4,'write_stdin','poll',output='Process exited with code 7',arguments={'session_id':12})]
            lp,tp=files(Path(folder),events,[]);d=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(5))
            self.assertTrue(d['tools'][1]['tool_success']);self.assertEqual(d['jobs'][0]['exit_code'],7)
            self.assertEqual(d['technical_seconds']['response_union'],None)

    def test_cutoff_keeps_unfinished_job_without_inventing_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1,output='Process running with session ID 12',arguments={'cmd':'make build'}),event('one',9,'write_stdin','p',output='Process exited with code 0',arguments={'session_id':12})],[])
            d=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(4))
            self.assertFalse(d['jobs'][0]['end_observed']);self.assertIsNone(d['jobs'][0]['exit_code'])
            self.assertEqual(d['jobs'][0]['end_ns'],ns(4))

    def test_parallel_groups_partition_elapsed_without_double_count(self):
        data={'actions':[{'id':'a1','start_ns':0,'end_ns':8},{'id':'a2','start_ns':4,'end_ns':10}]}
        parts=partition(data,{'id':'s1','start_ns':0,'end_ns':12},{'a1':('s1','0'),'a2':('s1','1')})
        self.assertEqual(parts,{'outside':2e-9,'0':4e-9,'parallel':4e-9,'1':2e-9})
        self.assertAlmostEqual(sum(parts.values()),12e-9)

    def test_unknown_evidence_and_duplicate_assignment_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1)],[]);d=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(2));r=review(d)
            r['stages'][0]['groups'][0]['action_ids']*=2
            with self.assertRaises(ValueError):validate(d,r)
            r=review(d);r['findings']=[{'action_ids':['missing'],'job_ids':[]}]
            with self.assertRaises(ValueError):validate(d,r)

    def test_captured_code_is_escaped_and_not_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1,arguments={'cmd':'echo "</code><script>EVIL</script>"'})],[])
            d=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(2));html,check=render(d,review(d),'UTC')
            self.assertNotIn('<script>EVIL</script>',html);self.assertIn('&lt;script&gt;EVIL',html)
            self.assertEqual(check['result'],'passed')

    def test_incomplete_tail_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1)],[])
            with lp.open('a') as stream:stream.write('{"resourceLogs":')
            d=read([lp],[tp]);self.assertEqual(len(d['events']),1);self.assertTrue(d['warnings'])

    def test_logs_only_wrapper_is_inferred_with_explicit_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            inner=event('one',1.01,arguments={'cmd':'printf ok'})
            outer=event('one',1.05,'exec','outer')
            for a in outer['attributes']:
                if a['key']=='arguments':a['value']={'stringValue':'const x=await tools.exec_command({cmd:"printf ok"});text(x);'}
            lp,tp=files(Path(folder),[inner,outer],[])
            d=analyze(read([lp],[tp]),'one',start=ns(0),end=ns(2))
            self.assertEqual(d['counts']['inner_tools'],1)
            self.assertTrue(any('double counting' in w for w in d['warnings']))

    def test_snake_case_and_duplicate_trace_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            lp,tp=files(Path(folder),[event('one',1)],[span('one','session_task.turn',0,2,'root')])
            text=lp.read_text().replace('resourceLogs','resource_logs').replace('scopeLogs','scope_logs').replace('logRecords','log_records').replace('observedTimeUnixNano','observed_time_unix_nano')
            lp.write_text(text);d=analyze(read([lp],[tp,tp]),'one')
            self.assertEqual(len(d['tools']),1);self.assertEqual(d['scope']['seconds'],2)

    def test_start_event_alone_produces_unknown_elapsed_report(self):
        with tempfile.TemporaryDirectory() as folder:
            e=event('one',1)
            for a in e['attributes']:
                if a['key']=='event.name':a['value']={'stringValue':'codex.conversation_starts'}
            lp,tp=files(Path(folder),[e],[]);d=analyze(read([lp],[tp]),'one')
            self.assertEqual(d['scope']['elapsed_status'],'unconfirmed');self.assertEqual(d['actions'],[])
            html,check=render(d,review(d),'UTC')
            self.assertIn('Unconfirmed (single timestamp)',html);self.assertEqual(check['result'],'passed')

if __name__=='__main__':unittest.main()
