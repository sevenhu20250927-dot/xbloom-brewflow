'use strict';

const BrewChart = (() => {
  const svgNS = 'http://www.w3.org/2000/svg';
  const colors = ['#276e90', '#8b4b26', '#41775c'];
  const sampleTimeouts = new WeakMap();
  const clock = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  function element(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function svgNode(tag, attrs, text) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function create(id) {
    const panel = element('section', 'live-chart');
    panel.dataset.brew = id;
    const head = element('div', 'live-chart-head'), icon = svgNode('svg', {viewBox:'0 0 44 52',width:38,height:46,'aria-hidden':'true'});
    icon.append(svgNode('path',{d:'M8 4h22v6h-8',fill:'none',stroke:'currentColor','stroke-width':2.4}),
      svgNode('circle',{class:'brew-droplet',cx:22,cy:16,r:2.5,fill:'currentColor'}),
      svgNode('path',{d:'M6 25h32L26 39h-8z M13 44h18',fill:'none',stroke:'currentColor','stroke-width':2.3,'stroke-linejoin':'round'}));
    const label = element('div'); label.append(element('strong','live-stage','等待注水信号'),element('small','live-stage-volume'));
    const timer = element('span','live-clock','—');
    timer.title = '从首段注水信号到最近一次机器回报的时间';
    head.append(icon,label,timer);
    const metrics = element('div','live-metrics');
    for (const name of ['累计注水','杯中液重','暂存水估算']) {
      const cell = element('div'); cell.append(element('span','',name),element('strong','','—')); metrics.append(cell);
    }
    const plot = svgNode('svg',{class:'brew-plot',viewBox:'0 0 600 174',role:'img','aria-label':'累计注水、杯中液重和暂存水估算随时间变化'});
    const flowHead = element('div', 'cup-flow-heading');
    flowHead.append(element('strong', '', '出杯流速（g/s）'), element('span', 'cup-flow-value'));
    const flowPlot = svgNode('svg', {class:'brew-plot cup-flow-plot', viewBox:'0 0 600 174', role:'img',
      'aria-label':'按相邻两秒杯中液重变化计算的出杯流速，与上图共用时间轴'});
    const flowNote = element('small', 'live-chart-note cup-flow-note', '等待连续两秒的杯秤读数。');
    panel.append(head,metrics,plot,element('small','live-chart-note','收到机器的注水和称重数据后开始绘图。'),flowHead,flowPlot,flowNote);
    return panel;
  }
  function plotChart(node, points, marks, end, target, flow = false) {
    const xmax = Math.max(30, Math.ceil(end / 30) * 30);
    const unit = flow ? 1 : 50;
    let ymin = 0, ymax = Math.max(unit, target);
    for (const row of points) for (const v of row.slice(1)) if (v !== null) {
      ymin = Math.min(ymin, v);
      ymax = Math.max(ymax, v);
    }
    ymin = Math.floor(ymin / unit) * unit;
    ymax = Math.ceil(ymax / unit) * unit;
    const x = t => 37 + 545 * t / xmax, y = v => 145 - 122 * (v-ymin) / (ymax-ymin);
    const out = document.createDocumentFragment();
    for (const v of [ymin, ymin < 0 ? 0 : ymax/2, ymax]) {
      out.append(svgNode('path',{d:`M37 ${y(v)}h545`,stroke:'#d7cec0'}),svgNode('text',{x:30,y:y(v)+4,'text-anchor':'end'},v));
    }
    const step = Math.max(15, Math.ceil(xmax/5/15)*15);
    for (let t=0;t<=xmax;t+=step) out.append(svgNode('text',{x:x(t),y:166,'text-anchor':'middle'},clock(t)));
    for (const [t, index] of marks) {
      out.append(svgNode('path',{d:`M${x(t)} 23v122`,stroke:'#afa18d','stroke-dasharray':'2 4'}),
        svgNode('text',{x:x(t)+3,y:16},`段${index}`));
    }
    const palette = flow ? ['#995524'] : colors;
    for (let key=1;key<=palette.length;key++) {
      let path='',previous=null,last=null,segmentLength=0;
      const dot = row => svgNode('circle',{cx:x(row[0]),cy:y(row[key]),r:2,fill:palette[key-1]});
      for (const row of points) {
        if (row[key]===null) continue;
        const continuous=previous!==null && row[0]-previous<=1;
        if (!continuous && segmentLength===1) out.append(dot(last));
        segmentLength=continuous?segmentLength+1:1;
        path+=(continuous?'L':'M')+x(row[0]).toFixed(1)+' '+y(row[key]).toFixed(1);
        previous=row[0];last=row;
      }
      if (last) out.append(svgNode('path',{d:path,fill:'none',stroke:palette[key-1],'stroke-width':2.4,'stroke-dasharray':key===3?'4 3':'none'}),
        svgNode('circle',{cx:x(last[0]),cy:y(last[key]),r:2.7,fill:palette[key-1]}));
    }
    node.replaceChildren(out);
  }
  function cupFlow(points) {
    const rates = [];
    for (let i = 1; i < points.length; i++) {
      const [second, , grams] = points[i];
      const [previousSecond, , previousGrams] = points[i - 1];
      if (second - previousSecond === 1 && Number.isFinite(grams) && Number.isFinite(previousGrams)) {
        rates.push([second, Number((grams - previousGrams).toFixed(1))]);
      }
    }
    return rates;
  }
  function lastValue(points, column, since) {
    for (let index = points.length - 1; index >= 0 && points[index][0] >= since; index--) {
      if (points[index][column] !== null) return points[index][column];
    }
    return null;
  }
  function update(panel, data, archived=false) {
    if (!data || data.elapsed_s===null) {
      panel.dataset.flow='false';
      panel.querySelector('.live-stage').textContent=data?.stop_reason==='no_update'?'30 秒无有效更新，未采集到注水':archived?'本次没有注水采样':'等待注水信号';
      panel.querySelector('.cup-flow-note').textContent=archived?'本杯缺少可计算流速的连续杯秤读数。':'等待连续两秒的杯秤读数。';
      return;
    }
    const marks=data.stages, last=marks.at(-1), idx=last?.[1], points=data.points;
    const target=data.volumes.reduce((a,b)=>a+b,0);
    const finished=archived || data.closed;
    if (finished) clearTimeout(sampleTimeouts.get(panel));
    if (!finished && panel.dataset.elapsed!==String(data.elapsed_s)) {
      panel.dataset.elapsed=String(data.elapsed_s);
      panel.dataset.updated=String(Date.now());
      clearTimeout(sampleTimeouts.get(panel));
      sampleTimeouts.set(panel, setTimeout(() => {
        panel.dataset.flow='false';
        panel.querySelector('.live-stage').textContent='等待新采样';
        panel.querySelector('.cup-flow-value').textContent='';
      }, 2500));
    }
    const stale=!finished && Date.now()-Number(panel.dataset.updated)>=2500;
    panel.dataset.flow=String(!stale && data.flowing && !finished);
    const since=finished ? 0 : data.elapsed_s-2;
    const water=lastValue(points,1,since), cup=lastValue(points,2,since);
    const pastBed=data.bypass_ml>0 && water!==null && water>=target;
    panel.querySelector('.live-clock').textContent=clock(data.elapsed_s);
    panel.querySelector('.live-stage').textContent=stale?'等待新采样':finished?'本次注水与滴滤记录':pastBed?'已达过粉设定水量':idx?`第 ${idx} / ${data.volumes.length} 段`:'已收到注水信号';
    const ending = {program_end:'已收到机器程序结束信号，曲线已封存', no_update:'30 秒无有效更新，曲线已封存，出杯待核对', machine_idle:'机器已回待机，曲线已封存'};
    panel.querySelector('.live-stage-volume').textContent=finished?(ending[data.stop_reason] || '显示末次有效读数'):pastBed?`配方旁通 ${data.bypass_ml} ml`:idx
      ? `本段 ${clock(data.elapsed_s-last[0])} · 目标 ${data.volumes[idx-1]} ml${data.stage_ml===null?'':` · 已注约 ${data.stage_ml.toFixed(1)} ml`}` : '';
    const pair=points.at(-1);
    const held=!pastBed && !data.counter_reset && pair && pair[0]>=data.elapsed_s-2 ? pair[3] : null;
    const values=panel.querySelectorAll('.live-metrics strong');
    values[0].textContent=water===null || (!finished && data.counter_reset)?'—':`≈${water.toFixed(1)} ml`;
    values[1].textContent=cup===null?'—':`${cup.toFixed(1)} g`;
    values[2].textContent=held==null?'—':`≈${held.toFixed(1)} g`;
    plotChart(panel.querySelector('.brew-plot'),points,marks,data.elapsed_s,target+data.bypass_ml);
    const rates = cupFlow(points);
    plotChart(panel.querySelector('.cup-flow-plot'),rates,marks,data.elapsed_s,0,true);
    const latest = rates.at(-1);
    panel.querySelector('.cup-flow-value').textContent = latest && !stale && (finished || latest[0] >= since)
      ? `${clock(latest[0])} · ${latest[1].toFixed(1)} g/s` : '';
    panel.querySelector('.cup-flow-note').textContent = rates.length
      ? '逐秒杯中液重差。缺测处断线，负值表示秤读数回落。' + (data.bypass_ml ? '旁通进杯的水也会计入。' : '')
      : finished ? '本杯缺少可计算流速的连续杯秤读数。' : '等待连续两秒的杯秤读数。';
    panel.querySelector('.live-chart-note').textContent=`从首段注水信号计时 · 配方共 ${target+data.bypass_ml} ml。机器注水计数按近似毫升显示，单位待校准。暂存水按同秒注水量（约 1 g/ml）减杯重估算，含粉床吸水。${data.bypass_ml?'达到过粉设定后暂停暂存水估算。':''}`;
  }
  function offline(panel) {
    clearTimeout(sampleTimeouts.get(panel));
    panel.dataset.flow='false';panel.querySelector('.live-stage').textContent='暂时读不到采样';
    panel.querySelector('.cup-flow-value').textContent='';
  }
  return {create, update, offline};
})();
