'use strict';
const $ = id => document.getElementById(id);
const modes = {xbloom:'机磨机冲',grind_own:'外磨粉机冲',manual:'手冲'};
const statuses = {ordered:'待接单',accepted:'已接单',cancelled:'已取消',fulfilled:'已交付'};
let state, guest, view='menu', scope='daily', search='', mode='xbloom';
const recommendations=new Map();
const pendingJobs=new Set();

function el(tag, text, cls) {
  const node=document.createElement(tag);
  if(text!=null) node.textContent=text;
  if(cls) node.className=cls;
  return node;
}
function button(label, action, cls='') {
  const b=el('button',label,cls);
  b.onclick=async () => {
    b.disabled=true;
    try {await action();} catch(error) {showError(error);}
    finally {if(b.isConnected) b.disabled=false;}
  };
  return b;
}
function showError(error) {
  const dialog=document.querySelector('dialog[open] [role=alert]');
  (dialog || $('notice')).textContent=error.message;
}
function select(items, value) {
  const s=el('select');
  for(const [key,name] of items) s.add(new Option(name,key));
  s.value=value;
  return s;
}
function field(name,input) {
  const label=el('label',name);
  input.setAttribute('aria-label',name);
  label.append(input);return label;
}
function dialog(title) {
  document.querySelector('dialog')?.close();
  const d=el('dialog');
  const err=el('p');err.setAttribute('role','alert');
  d.append(el('h2',title),err);
  d.onclose=()=>d.remove();document.body.append(d);d.showModal();return d;
}
async function api(path, data) {
  const response=await fetch('/api/'+path,data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)} : {cache:'no-store'});
  const value=await response.json();
  if(!response.ok) {const err=new Error(value.error || '请求失败');err.status=response.status;throw err;}
  return value;
}
async function write(key,path,data) {
  // A lost response reuses the request ID for the very same payload after reload.
  const slot='brewflow.order.'+location.host+'.'+key;
  const saved=JSON.parse(localStorage.getItem(slot) || 'null');
  if(saved && JSON.stringify(saved.data)!==JSON.stringify(data)) throw new Error('上次请求尚未确认，请先刷新并核对订单。');
  const entry=saved || {data,id:crypto.randomUUID()};
  localStorage.setItem(slot,JSON.stringify(entry));
  try {
    const result=await api(path,{...data,request_id:entry.id});
    localStorage.removeItem(slot);return result;
  } catch(error) {
    if(error.status>=400 && error.status<500) localStorage.removeItem(slot);
    throw error;
  }
}
async function refresh() {
  state=await api('state');
  if(!state.people.some(p=>p.id===guest)) guest=state.people[0]?.id;
  $('guest').replaceChildren(...state.people.map(p=>new Option(p.name,p.id)));
  if(guest) $('guest').value=guest;
  render();
}
const snapshot=o=>Object.fromEntries(['bean_id','person_id','mode','note','status'].map(k=>[k,o[k]]));
const beanName=id=>state.beans.find(b=>b.id===id)?.name || '未知豆子';
const personName=id=>state.people.find(p=>p.id===id)?.name || '未知品饮人';
function rememberOrder(order) {
  state.orders=[order,...state.orders.filter(o=>o.id!==order.id)].filter(o=>o.status!=='deleted');
}
function receipt(order) {
  const d=dialog('点单已收到');
  d.append(el('p','#'+order.id+' · '+personName(order.person_id)+' · '+beanName(order.bean_id)),
    button('查看我的订单',()=>{d.close();view='mine';render();},'primary'),button('继续选豆',()=>d.close()));
}
function renderMenu(host) {
  const tools=el('div',null,'actions'),searchBox=el('input');
  searchBox.type='search';searchBox.placeholder='豆名、烘焙商、产地、风味';searchBox.value=search;
  const preferences=el('div'),cards=el('div',null,'cards'),count=el('small');
  const scopes=[['daily','今日轮换'],['all','全部在库'],['taste','按我的口味']];
  for(const [key,name] of scopes) {
    const control=button(name,()=>{scope=key;search='';render();});
    control.dataset.scope=key;tools.append(control);
  }
  function draw() {
    const selected=search.trim()?'all':scope;
    for(const b of tools.children) b.setAttribute('aria-pressed',String(b.dataset.scope===selected));
    preferences.hidden=selected!=='taste';
    const items=recommendations.get(guest)?.items || [];
    const beans=selected==='daily'?state.menu:selected==='taste'?items.map(i=>state.beans.find(b=>b.id===i.bean_id)).filter(b=>b?.net_weight>=15):state.beans.filter(b=>b.net_weight>0);
    const terms=search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const filtered=beans.filter(b=>terms.every(t=>[b.name,b.roaster,b.country,b.process,b.variety_name,b.source_flavor,b.source_notes].join(' ').toLowerCase().includes(t)));
    count.textContent=filtered.length+' 款';
    cards.replaceChildren(...filtered.map(bean=>{
      const card=el('article');
      card.append(el('small',bean.roaster),el('h2',bean.name),el('p',[bean.country,bean.process,bean.variety_name].filter(Boolean).join(' · ')),
        el('p',bean.source_flavor),el('p',bean.source_notes),el('small',bean.net_weight+' g'));
      const item=selected==='taste' && items.find(i=>i.bean_id===bean.id);
      if(item) {
        const refs=el('details');refs.append(el('summary','推荐依据'),...item.evidence.map(e=>el('p',e.title+' · '+e.excerpt)));
        card.append(el('p',item.reason),el('p',item.story),refs);
      }
      const queued=state.orders.find(o=>o.bean_id===bean.id && o.person_id===guest && o.mode===mode && ['ordered','accepted'].includes(o.status));
      const b=button(queued?'已点单 #'+queued.id:bean.net_weight<15?'不足 15 g':'就喝这款',async()=>{
        const id=guest;
        const order=await write('new.'+id+'.'+bean.id+'.'+mode,'orders',{person_id:id,bean_id:bean.id,mode,note:''});
        rememberOrder(order);render();receipt(order);
      },'primary');
      b.disabled=Boolean(queued) || !guest || bean.net_weight<15;
      const actions=el('div',null,'actions');actions.append(b);card.append(actions);return card;
    }));
    if(!filtered.length) cards.append(el('p',state.beans.length?'暂无匹配的豆子。':'豆单为空。请先按模块说明录入自己的豆子和品饮人。'));
  }
  searchBox.oninput=()=>{search=searchBox.value;draw();};
  const pref=state.preferences.find(p=>p.person_id===guest);
  const note=el('textarea');note.value=pref?.preference_text || '';
  const save=button('保存偏好',async()=>{
    await write('pref.'+guest,'preferences',{person_id:guest,preference_text:note.value.trim(),expected_revision:pref?.revision || 0});
    recommendations.delete(guest);await refresh();$('notice').textContent='偏好已保存';
  });
  save.disabled=!guest;
  const recommend=button(pendingJobs.has(guest)?'正在生成推荐…':'生成口味推荐',async()=>{
    const id=guest;pendingJobs.add(id);render();
    try {recommendations.set(id,await api('recommend',{person_id:id}));}
    finally {pendingJobs.delete(id);render();}
  });
  recommend.disabled=!guest || !state.provider || pendingJobs.has(guest);
  preferences.append(field('我的口味',note),save,recommend);
  if(!state.provider) preferences.append(el('small','管理员可在启动时启用 AI 推荐。'));
  const method=select(Object.entries(modes),mode);
  method.onchange=()=>{mode=method.value;draw();};
  host.append(tools,field('搜索全部在库',searchBox),field('制作方式',method),preferences,count,cards);draw();
}
async function change(order,action,extra={}) {
  const result=await write('order.'+order.id+'.'+action,'orders/'+order.id+'/'+action,{expected:snapshot(order),...extra});
  rememberOrder(result);document.querySelector('dialog')?.close();render();
  $('notice').textContent='订单 #'+order.id+' 已更新';
}
function edit(order) {
  const d=dialog('编辑订单 #'+order.id);
  const bean=select(state.beans.filter(b=>b.net_weight>=15 || b.id===order.bean_id).map(b=>[b.id,b.name]),order.bean_id);
  const person=select(state.people.map(p=>[p.id,p.name]),order.person_id);
  const mode=select(Object.entries(modes),order.mode);
  const note=el('textarea');note.value=order.note;
  d.append(field('豆子',bean),field('品饮人',person),field('制作方式',mode),field('备注',note),
    button('保存修改',()=>change(order,'update',{bean_id:Number(bean.value),person_id:Number(person.value),mode:mode.value,note:note.value.trim()}),'primary'),button('返回',()=>d.close()));
}
function renderOrders(host) {
  const orders=state.orders.filter(o=>view==='mine'?o.person_id===guest:['ordered','accepted'].includes(o.status));
  if(!orders.length) host.append(el('p','当前没有订单。'));
  for(const order of orders) {
    const card=el('article'),actions=el('div',null,'actions');
    card.append(el('h2','#'+order.id+' · '+beanName(order.bean_id)),el('p',[personName(order.person_id),modes[order.mode],statuses[order.status]].join(' · ')));
    if(order.note) card.append(el('p',order.note));
    if(view==='queue') {
      if(order.status==='ordered') actions.append(button('接这杯',()=>change(order,'accept'),'primary'));
      if(order.status==='accepted') actions.append(button('标记已交付',()=>change(order,'finish'),'primary'));
    }
    if(order.status==='ordered') actions.append(button('编辑',()=>edit(order)));
    for(const [key,name] of [['cancel','取消订单'],['delete','删除订单']]) {
      if(order.status==='ordered' || (key==='delete' && order.status==='cancelled')) actions.append(button(name,()=>{
        const d=dialog(name+' #'+order.id+'？');
        d.append(el('p',beanName(order.bean_id)),button('返回',()=>d.close()),button('确认'+name,()=>change(order,key),'primary'));
      }));
    }
    card.append(actions);host.append(card);
  }
}
function render() {
  document.querySelector('h1').textContent={menu:'今日豆单',mine:'我的订单',queue:'接单台'}[view];
  document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-pressed',String(b.id===view)));
  const content=$('content');content.replaceChildren();
  if(view==='menu') renderMenu(content);else renderOrders(content);
}
$('guest').onchange=()=>{guest=Number($('guest').value);render();};
for(const id of ['menu','mine','queue']) $(id).onclick=async()=>{view=id;try {await refresh();}catch(error){showError(error);}};
refresh().catch(showError);
