/* Embedded in the report so that file:// viewing needs no fetch or build. */
(() => {
  'use strict';
  const D=JSON.parse(document.getElementById('chart-data').textContent);
  if (!D.lanes?.length) return;
  const svg=document.getElementById('work-chart'), select=document.getElementById('work-range');
  const NS='http://www.w3.org/2000/svg', L=232, R=1138, W=1160;
  const stages=D.stages.map((s,i)=>({...s,kind:'stage',number:i+1,segments:[{start:s.start,end:s.end}],seconds:s.end-s.start}));
  const items=[...stages,...D.lanes.flatMap(l=>l.items)];
  let range=[0,D.scope.seconds], selected=stages[0];
  function node(tag,attrs={},value) {
    const n=document.createElementNS(NS,tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v);
    if (value!==undefined) n.textContent=value;
    return n;
  }
  function elapsed(s) {const n=Math.round(s);return `${Math.floor(n/60)}m ${String(n%60).padStart(2,'0')}s`;}
  function clock(s) {
    return new Date(D.start_epoch_ms+s*1000).toLocaleTimeString('en-GB',{timeZone:D.timezone_name,hour12:false});
  }
  function visible(i) {return i.segments.some(s=>s.end>range[0]&&s.start<range[1]);}
  function show(item) {
    selected=item;
    document.getElementById('work-detail-title').textContent=(item.kind==='stage'?`${item.number}. `:'')+item.title;
    document.getElementById('work-detail-description').textContent=item.summary;
    const fields=[['Time range',`${clock(item.start)}–${clock(item.end)}`],
      [item.unconfirmed?'Displayed interval (duration unconfirmed)':'Duration',`${elapsed(item.seconds)} (${item.seconds.toFixed(3)}s)`]];
    if (item.kind==='stage') fields.push(['Share of total',`${(item.seconds/D.scope.seconds*100).toFixed(1)}%`]);
    else {
      fields.push(['Time interpretation',item.basis]);
      if(item.segments.length>1) fields.push(['Intervals',`${item.segments.length} intervals. Duration sums these intervals and excludes gaps.`]);
      if(item.files.length) fields.push(['Created or modified files',item.files.join(', ')]);
      if(item.results.length) fields.push(['Execution results',item.results.join('. ')]);
    }
    const dl=document.getElementById('work-detail-values');dl.replaceChildren();
    for(const [key,value] of fields) {const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;dl.append(dt,dd);}
    const evidence=document.getElementById('work-detail-evidence');evidence.replaceChildren();
    for(const ref of item.evidence||[]) {
      const a=document.createElement('a');a.href='#'+ref.target;a.textContent=ref.id+' '+ref.title;
      a.addEventListener('click',e=>{e.preventDefault();reveal(ref.target);});evidence.append(a,document.createTextNode(' | '));
    }
    document.getElementById('work-open-detail').textContent=item.kind==='stage'?'Open this stage breakdown':'Open activity commands and output';
    svg.querySelectorAll('[data-work-id]').forEach(n=>{const active=String(n.dataset.workId===item.id);n.setAttribute('data-selected',active);n.setAttribute('aria-pressed',active);});
  }
  function setRange(start,end) {
    range=[Math.max(0,start),Math.min(D.scope.seconds,end)];
    if(range[1]<=range[0])range=[0,D.scope.seconds];
    render();show(selected);
  }
  function render() {
    svg.querySelector('.generated')?.remove();
    const root=node('g',{class:'generated'}), span=range[1]-range[0];
    const x=t=>L+(t-range[0])/span*(R-L);
    const rows=[{title:'Major stages',description:`${stages.length} stages`,items:stages,top:64,height:64}];
    for(const lane of D.lanes) {
      const ends=[], layout=[];
      for(const item of lane.items.filter(visible).sort((a,b)=>a.start-b.start)) {
        let slot=ends.findIndex(end=>end<=item.start);
        if(slot<0)slot=ends.length;
        ends[slot]=item.end;layout.push({...item,slot});
      }
      const last=rows[rows.length-1];
      rows.push({...lane,items:layout,top:last.top+last.height,height:Math.max(64,24+ends.length*30)});
    }
    const height=rows[rows.length-1].top+rows[rows.length-1].height+20;
    svg.setAttribute('viewBox',`0 0 ${W} ${height}`);
    for(let i=0;i<=6;i++) {
      const t=range[0]+span*i/6, px=x(t);
      root.append(node('line',{x1:px,x2:px,y1:51,y2:height-20,stroke:'#DFDFDF'}));
      root.append(node('text',{x:px,y:29,'font-size':12,'text-anchor':i===0?'start':i===6?'end':'middle'},clock(t)));
    }
    function fits(value,width) {return Array.from(value).reduce((n,c)=>n+(/[\u0000-\u00ff]/.test(c)?6.5:12.5),0)<=width-10;}
    for(const row of rows) {
      root.append(node('text',{x:12,y:row.top+21,'font-size':15,'font-weight':700},row.title));
      root.append(node('text',{x:12,y:row.top+41,'font-size':11,fill:'#595959'},row.description||''));
      root.append(node('line',{x1:12,x2:R,y1:row.top+row.height-5,y2:row.top+row.height-5,stroke:'#DFDFDF'}));
      for(const item of row.items.filter(visible)) {
        const label=`${item.title}, ${item.unconfirmed?'Duration unconfirmed; displayed interval ':''}${elapsed(item.seconds)}`;
        const g=node('g',{role:'button',tabindex:0,'data-work-id':item.id,'data-kind':item.kind,'aria-label':label,'aria-pressed':String(selected?.id===item.id)});
        g.append(node('title',{},`${label}\n${clock(item.start)}–${clock(item.end)}`));
        const y=row.top+10+(item.slot||0)*30;
        for(const segment of item.segments) {
          if(segment.end<range[0]||segment.start>range[1])continue;
          const left=x(Math.max(range[0],segment.start)),right=x(Math.min(range[1],segment.end));
          const fill=['implementation','documentation'].includes(item.kind)?'#A5A5A5':item.kind==='stage'?(item.number%2?'#FFFFFF':'#DFDFDF'):'#FFFFFF';
          const rect=node('rect',{x:left,y,width:Math.max(2,right-left),height:25,rx:3,fill,stroke:'#111110','stroke-width':1.2});
          if(item.unconfirmed)rect.setAttribute('stroke-dasharray','1 3');
          else if(item.kind==='fix'||item.failed)rect.setAttribute('stroke-dasharray','5 3');
          g.append(rect);
          if(item.kind==='stage'||right-left>90) {
            // No title truncation: full text appears in the selection card and tooltip.
            const value=item.kind==='stage'?`${item.number}. ${item.short_title||item.title}`:item.title;
            const t=node('text',{x:left+5,y:y+17,'font-size':12,'pointer-events':'none'},value);
            // Fit only when the complete label will fit; otherwise keep its stage number.
            if(item.kind==='stage'&&!fits(value,right-left))t.textContent=String(item.number);
            else if(item.kind!=='stage'&&!fits(value,right-left))t.textContent='';
            g.append(t);
          }
        }
        g.addEventListener('click',()=>show(item));
        g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(item);}});
        root.append(g);
      }
    }
    svg.append(root);
    document.getElementById('work-range-label').textContent=`${clock(range[0])}–${clock(range[1])} / ${elapsed(span)} / ${D.timezone_name}`;
  }
  for(const stage of stages) {const o=document.createElement('option');o.value=stage.id;o.textContent=`${stage.number}. ${stage.title}`;select.append(o);}
  select.addEventListener('change',()=>{
    const stage=stages.find(s=>s.id===select.value);
    if(stage){selected=stage;setRange(stage.start,stage.end);}else setRange(0,D.scope.seconds);
  });
  document.getElementById('work-reset').addEventListener('click',()=>{select.value='all';setRange(0,D.scope.seconds);});
  document.getElementById('work-zoom').addEventListener('click',()=>{
    const padding=selected.kind==='stage'?0:Math.max(5,(selected.end-selected.start)*.1);
    select.value=selected.kind==='stage'?selected.id:'all';setRange(selected.start-padding,selected.end+padding);
  });
  document.getElementById('work-open-detail').addEventListener('click',()=>reveal(selected.kind==='stage'?selected.id:selected.evidence[0].target));
  render();show(selected);window.workTimelineReady=true;
})();
