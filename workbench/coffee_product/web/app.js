(() => {
  'use strict';

  const API = '/api/product';
  const defaultBrewer = '平底滤杯';
  const brewerOverrides = new Map();
  const PENDING_KEY = 'coffee-product.pending.v1';
  const AI_JOB_KEY = 'coffee-product.ai-job.v1';
  const RECOMMEND_JOB_KEY = 'coffee-product.recommend-jobs.v1';
  const MODES = { xbloom: '全机器 · xBloom', manual: '全手冲', grind_own: '自磨 · 机冲' };
  const STATUSES = { ordered: '待制作', prepared: '已备方，未开始', starting: '开始请求已登记', running: '已提交启动，正在采集', needs_review: '等待人工核对', completed: '人工确认完成', failed: '失败', unconfirmed: '完成状态未确认', pending: '待制作', fulfilled: '已交付', cancelled: '已取消' };
  const VERDICTS = { support: '支持', counterexample: '反例', insufficient: '证据不足' };
  function locationView() { const view = new URLSearchParams(location.search).get('view'); return location.pathname === '/menu' ? 'menu' : location.pathname === '/experiences' ? 'experiences' : ['records', 'ai'].includes(view) ? view : 'studio'; }
  const app = { data: null, view: locationView(), recordBrew: new URLSearchParams(location.search).get('brew') || '', person: '', studioPerson: '', bean: '', order: '', brew: new URLSearchParams(location.search).get('cup') || '', menuBrew: '', menuScope: 'recommended', menuSearch: '', mode: 'xbloom', dose: 15, goal: '', search: '', draft: null, draftText: '', dirty: false, busy: new Set(), pending: {}, storageReady: true, aiJob: null, aiPolling: false, aiSettings: null, recommendJobs: {}, menuUpdate: null };
  const $ = id => document.getElementById(id);
  const text = value => value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const sameId = (a, b) => a != null && b != null && String(a) === String(b);
  const getBean = id => app.data.beans.find(item => sameId(item.id, id));
  const getRecipe = id => app.data.recipes.find(item => sameId(item.id, id));
  const getBrew = id => app.data.brews.find(item => sameId(item.id, id));
  const getPerson = id => app.data.people.find(item => sameId(item.id, id));
  const getOrder = id => app.data.orders.find(item => sameId(item.id, id));
  const personName = id => getPerson(id)?.name || '未关联品饮者';
  const beanName = id => getBean(id)?.name || `豆子 #${id}`;
  const feedbackFor = (brewId, personId) => app.data.feedback.find(item => item.cup === `brew-${brewId}` && sameId(item.person_id, personId));
  const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '时间未记录';
  const showValue = (value, unit = '') => value == null || value === '' ? '未记录' : `${value}${unit}`;
  const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
  const newest = items => items.slice().sort((a, b) => Number(b.id) - Number(a.id));
  const closedOrder = order => ['completed', 'failed', 'fulfilled', 'cancelled', 'deleted'].includes(order.status);
  const orderBrew = order => newest(app.data.brews.filter(brew => sameId(brew.order_id, order.id)))[0];
  const activeOrder = (beanId, personId, mode) => newest(app.data.orders).find(order => sameId(order.bean_id, beanId) && sameId(order.person_id, personId) && order.mode === mode && !closedOrder(order));
  const orderSnapshot = order => Object.fromEntries(['bean_id', 'person_id', 'mode', 'note', 'status'].map(key => [key, order[key]]));
  const getPreference = personId => app.data.preferences.find(item => sameId(item.person_id, personId)) || { person_id: Number(personId), preference_text: '', revision: 0 };
  const anyAIRunning = () => app.aiJob?.status === 'running' || Object.values(app.recommendJobs).some(job => job.status === 'running');

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value == null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key in node && !key.startsWith('aria-')) node[key] = value;
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    children.flat(Infinity).forEach(child => {
      if (child != null && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return node;
  }
  const button = (label, action, style = '', disabled = false) => el('button', { type: 'button', class: `button ${style}`, disabled, onclick: action }, label);
  const pill = (label, style = '') => el('span', { class: `pill ${style}` }, label);
  function statusPill(item, kind) {
    const status = item.status;
    const style = status === 'completed' ? 'green' : ['failed', 'unconfirmed'].includes(status) ? 'red' : ['running', 'starting', 'needs_review'].includes(status) ? 'warn' : '';
    const rinseStage = status === 'prepared' && item.rinse && brewStage(item);
    const node = pill(rinseStage || STATUSES[status] || status || '状态未知', rinseStage ? 'warn' : style);
    node.dataset.statusKind = kind;
    node.dataset.itemId = item.id;
    node.dataset.status = status || '';
    node.dataset.rinse = item.rinse?.state || '';
    return node;
  }
  function field(label, control, hint) {
    return el('label', { class: 'field' }, el('span', { class: 'field-label' }, label), control, hint && el('span', { class: 'field-help' }, hint));
  }
  function select(options, value, change, placeholder) {
    const node = el('select', { onchange: change }, placeholder && el('option', { value: '' }, placeholder), options.map(item => el('option', { value: item.value }, item.label)));
    node.value = value == null ? '' : String(value);
    return node;
  }
  function input(value = '', props = {}) { return el('input', { type: 'text', value: value ?? '', ...props }); }
  function textarea(value = '', props = {}) { return el('textarea', { value: value ?? '', ...props }); }
  function number(value, props = {}) { return input(value, { type: 'number', min: '0', step: 'any', ...props }); }
  function empty(title, detail) { return el('div', { class: 'empty' }, el('strong', {}, title), detail); }
  function panel(title, ...contents) { return el('section', { class: 'panel' }, el('div', { class: 'section-title' }, el('h2', {}, title)), ...contents); }
  function numeric(control, label) {
    if (control.value.trim() === '') return null;
    const value = Number(control.value);
    if (!Number.isFinite(value) || value < 0) throw new Error(`${label}请填写非负数字，未知请留空。`);
    return value;
  }
  function announce(message, error = false) {
    const host = $('notice');
    host.className = `notice${error ? ' error' : ''}`;
    host.hidden = false;
    host.replaceChildren(el('span', {}, message), button('关闭', () => { host.hidden = true; }, 'quiet'));
    host.setAttribute('role', error ? 'alert' : 'status');
  }
  function openDialog(title, ...content) {
    document.querySelector('.product-dialog')?.close();
    const errors = el('p', { class: 'dialog-error', role: 'alert', hidden: true });
    const dialog = el('dialog', { class: 'product-dialog', 'aria-label': title }, el('div', { class: 'section-title' }, el('h2', {}, title), button('关闭', () => dialog.close(), 'quiet')), errors, ...content);
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
    return { dialog, error: error => { errors.textContent = error.message || String(error); errors.hidden = false; } };
  }
  function orderReceipt(order, repeated = false) {
    const body = el('div', { class: 'order-receipt' }, pill(`订单 #${order.id}`, 'green'), el('h3', {}, beanName(order.bean_id)), el('p', {}, `这杯给 ${personName(order.person_id)}`), el('p', { class: 'muted small' }, repeated ? '这份订单已经在队列中，无需再点一次。' : '订单已保存。制作人审核配方后开始，无需再次点击点单。'));
    const view = openDialog(repeated ? '这杯已经点好了' : '点单成功', body);
    view.dialog.append(el('div', { class: 'actions' }, button('知道了', () => view.dialog.close())));
  }
  function applyOrderResult(order, action = '') {
    if (!order?.id) return;
    app.data.orders = app.data.orders.filter(item => !sameId(item.id, order.id));
    if (order.status !== 'deleted') app.data.orders.push(order);
    if (sameId(app.order, order.id)) {
      app.bean = action === 'update' ? order.bean_id : '';
      app.mode = order.mode;
      app.order = action === 'update' ? order.id : '';
      app.brew = ''; app.draft = null; app.draftText = ''; app.dirty = false; app.goal = '';
    }
  }
  async function refreshAfterSaved(message) {
    try { await refresh(); return true; }
    catch (error) { renderApp(); announce(`${message}，但列表同步失败：${error.message}`, true); return false; }
  }
  function syncMenuOrderButtons() {
    if (!app.data) return;
    document.querySelectorAll('[data-order-bean]').forEach(control => {
      const bean = getBean(control.dataset.orderBean);
      const person = control.dataset.orderPerson;
      const existing = activeOrder(bean?.id, person, 'xbloom');
      const key = `order:${bean?.id}:${person}`;
      const busy = app.busy.has(key);
      const enough = Number(bean?.net_weight) >= 15;
      control.textContent = busy ? '正在点单…' : existing ? `已点单 #${existing.id}` : !enough ? '不足 15 g' : app.pending[key] ? '核对原点单' : '就喝这款';
      control.disabled = busy || !!existing || !person || !enough;
    });
  }
  function planningPerson() { return getOrder(app.order)?.person_id || (app.studioPerson ? Number(app.studioPerson) : null); }
  const providerName = value => ({ codex: 'Codex', ollama: 'Ollama', deepseek: 'DeepSeek' }[value] || value || 'AI');
  const tokenCount = n => n == null ? '未知' : n.toLocaleString('zh-CN');
  function usageText(usage) {
    if (!usage) return '未收到用量回执，费用未知';
    let cost = '费用待核价';
    if (usage.min_cny != null) {
      const money = n => '¥' + (n > 0 && n < 0.0001 ? n.toFixed(8) : n.toFixed(4));
      cost = '约 ' + money(usage.min_cny);
      if (usage.min_cny !== usage.max_cny) cost += ' – ' + money(usage.max_cny);
    }
    return `${tokenCount(usage.total_tokens)} token · ${cost}`;
  }
  function usageDetails(usage) {
    const period = {peak:'高峰', off_peak:'空闲'}[usage.period];
    return el('small', {class:'muted'}, [
      `输入 ${tokenCount(usage.prompt_tokens)}（缓存命中 ${tokenCount(usage.cache_hit_tokens)}，未命中 ${tokenCount(usage.cache_miss_tokens)}）`,
      `输出 ${tokenCount(usage.completion_tokens)}`, period && `北京时段 · ${period}`,
      usage.price_date && `价格表 ${usage.price_date}`].filter(Boolean).join(' · '));
  }
  function callUsage(job) {
    const attempt = job?.attempts?.find(a => a.provider === 'deepseek');
    if (!attempt || (attempt.status === 'running' && job.status === 'running')) return null;
    return el('details', {class:'flow-extra'}, el('summary', {}, 'DeepSeek 用量 · ' + usageText(attempt.usage)),
      attempt.usage && usageDetails(attempt.usage));
  }
  function usageHistory() {
    const list = el('div', {class:'section-gap'});
    const panel = el('details', {class:'panel'}, el('summary', {}, 'DeepSeek 调用用量与费用'), list);
    panel.addEventListener('toggle', async () => {
      if (!panel.open) return;
      list.textContent = '正在读取调用记录…';
      try {
        const {calls} = await api(`${API}/ai/deepseek/usage`);
        const statusLabel = {completed:'已返回', failed:'失败', running:'进行中', interrupted:'已中断'};
        list.replaceChildren(el('p', {class:'small muted'}, '按 DeepSeek 回执的 token 和公开人民币价格估算，实际扣费以平台账单为准。 ',
          el('a', {href:'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/', target:'_blank', rel:'noopener'}, '官方价格')),
          calls.length ? el('ul', {class:'evidence-list'}, calls.map(row => {
            const time = row.usage?.created ? new Date(row.usage.created * 1000) : new Date(row.created_at);
            const title = row.kind === 'recommendation' ? '豆单推荐' : (row.revision ? '修方' : '拟方') + ' · ' + beanName(row.bean_id);
            return el('li', {}, el('strong', {}, `${title} · ${row.status === 'running' ? '等待回执' : usageText(row.usage)}`),
              el('p', {class:'small'}, `${time.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false})} · ${row.model} · ${statusLabel[row.status] || row.status}`),
              row.usage && usageDetails(row.usage));
          })) : el('p', {}, '还没有 DeepSeek 调用。'));
      } catch (error) { list.textContent = '读取调用记录失败：' + error.message; }
    });
    return panel;
  }
  const aiSettingsSignal = 'coffee-product.ai-settings-changed';
  let aiSettingsRead = 0;
  function primaryLabel(settings) {
    if (!settings) return '型号待同步';
    const options = settings[settings.primary];
    const parts = [providerName(settings.primary), options?.model];
    if (settings.primary === 'codex') parts.push(options?.reasoning_effort, options?.service_tier === 'priority' ? 'Fast' : null);
    return parts.filter(Boolean).join(' · ');
  }
  function aiButtonLabel() { return app.aiSettings ? `让 ${primaryLabel(app.aiSettings)} 根据历史与经验拟方` : '等待 AI 设置'; }
  async function syncAISettings() {
    const read = ++aiSettingsRead;
    let settings;
    try { settings = await api(`${API}/ai/settings`); }
    catch (_) { settings = null; }
    if (read !== aiSettingsRead) return;
    app.aiSettings = settings;
    document.querySelectorAll('.ai-entry').forEach(item => item.replaceWith(renderAISettings()));
    updateAIJobView();
  }
  function expectedAI() {
    if (!app.aiSettings) throw new Error('尚未读到主用 AI 设置，请刷新工作台。');
    const provider = app.aiSettings.primary;
    const options = app.aiSettings[provider];
    const route = {provider, model: options.model};
    if (provider === 'codex' && options.service_tier) {
      route.reasoning_effort = options.reasoning_effort;
      route.service_tier = options.service_tier;
    }
    return app.data.capabilities?.ai_recipe?.checks_expected_ai ? {expected_ai:route} : {};
  }
  function markDraftDirty() {
    if (!app.draft) return;
    app.dirty = true;
    if ($('draft-state')) $('draft-state').textContent = '已修改 · 必须保存新版本';
    if ($('create-brew')) $('create-brew').disabled = true;
    if ($('save-recipe')) $('save-recipe').hidden = false;
  }
  function aiContext(request) {
    const context = { request, draftText: app.draftText, draftId: app.draft?.id || null, database_label: app.data.database_label };
    if (request.revision && app.draft) {
      const { reviewBase, ...previous } = app.draft;
      context.previous = { ...previous, payload: JSON.parse(app.draftText) };
    }
    return context;
  }
  function saveAIJob() {
    if (!app.aiJob) { localStorage.removeItem(AI_JOB_KEY); return; }
    localStorage.setItem(AI_JOB_KEY, JSON.stringify({ id: app.aiJob.id, status: app.aiJob.status, context: app.aiJob.context }));
  }
  function aiMatchesCurrent(job) {
    const request = job.context?.request;
    return request && sameId(request.bean_id, app.bean) && request.mode === app.mode && request.goal === app.goal && (request.dose_grams ?? 15) === app.dose && (request.person_id || null) === planningPerson() && job.context.draftText === app.draftText && job.context.draftId === (app.draft?.id || null)
      && (!job.context.previous || (app.draft?.title === job.context.previous.title && app.draft?.reviewInput === job.context.previous.reviewInput));
  }
  function loadAIResult(job) {
    if (!job.result || job.kind === 'recommendation') return;
    const request = job.context.request;
    if (app.order && (!sameId(getOrder(app.order)?.bean_id, request.bean_id) || getOrder(app.order)?.mode !== request.mode || !sameId(getOrder(app.order)?.person_id, request.person_id))) app.order = '';
    app.studioPerson = request.person_id || '';
    app.brew = '';
    loadDraft({ ...job.result, id: null, bean_id: request.bean_id, mode: request.mode, goal: request.goal,
      parent_id: request.base_recipe_id || null, jobId: job.id, personId: request.person_id || null,
      reviewNotes: job.review_notes || [], reviewBase: job.context.previous });
    job.applied = true;
    if (app.view !== 'studio') navigate('studio'); else {
      if (new URLSearchParams(location.search).has('cup')) history.replaceState(null, '', '/studio');
      renderApp();
    }
    announce(`${providerName(job.provider)}方案已载入审核区，尚未保存、开杯或启动机器。`);
    $('recipe-review')?.scrollIntoView({ block: 'start' });
  }
  function confirmLoadAIResult(job) {
    if (!app.draft || (!app.dirty && aiMatchesCurrent(job))) { loadAIResult(job); return; }
    const view = openDialog('载入这次 AI 方案？', el('p', {}, '这会替换审核区当前显示的草稿。已经保存的配方版本保持原样。'));
    view.dialog.append(el('div', { class: 'actions' }, button('载入方案', () => { view.dialog.close(); loadAIResult(job); }), button('保留当前草稿', () => view.dialog.close(), 'secondary')));
  }
  function renderAIJob() {
    if (!app.aiJob || app.brew || app.draft?.jobId === app.aiJob.id) return null;
    const owner = app.aiJob.context?.request?.bean_id;
    if (app.bean && !sameId(app.bean, owner)) return null;
    const job = app.aiJob;
    const request = job.context?.request || job;
    const labels = { running: '拟方中', completed: '方案已生成', failed: '拟方失败', interrupted: '任务已中断' };
    const content = el('section', { class: 'panel', id: 'ai-job' }, el('div', { class: 'section-title' }, el('h2', {}, 'AI 拟方'), pill(labels[job.status] || '读取任务状态', job.status === 'completed' ? 'green' : ['failed', 'interrupted'].includes(job.status) ? 'red' : 'warn')), el('p', { class: 'small' }, `${beanName(request.bean_id)} · ${MODES[request.mode] || request.mode} · ${request.person_id ? personName(request.person_id) : '品饮者未指定'}`));
    if (job.provider || job.model) content.append(el('p', { class: 'inline-note' }, `实际提供方：${providerName(job.provider)}${job.model ? ` · ${job.model}` : ''}`));
    if (job.status === 'running') content.append(el('p', { class: 'inline-note' }, `${providerName(job.provider)} 正在结合库存、历史与一一经验拟方…可能需要几分钟。刷新页面后会取回同一次任务。`));
    if (job.status === 'completed') content.append(button('查看配方与提出修改', () => {
      if (app.draft?.jobId === job.id) $('recipe-review')?.scrollIntoView({ block: 'start' });
      else confirmLoadAIResult(job);
    }, 'secondary', !job.result));
    if (['failed', 'interrupted'].includes(job.status)) content.append(el('p', { class: 'dialog-error' }, job.error || '本次拟方未生成可用方案。'), el('p', { class: 'inline-note' }, '没有自动改用规则草案，也没有保存或执行配方。'));
    if (job.pollError) content.append(el('p', { class: 'dialog-error' }, `任务状态暂未读到：${job.pollError}`), button('重试读取状态', () => { job.pollStopped = false; pollAIJob(); }, 'secondary'));
    if (['failed', 'interrupted'].includes(job.status) && !app.draft && job.context?.previous) {
      content.append(button('查看修改前的配方', () => { app.studioPerson = job.person_id || ''; loadDraft(job.context.previous); renderApp(); $('recipe-review')?.scrollIntoView(); }, 'secondary'));
    }
    if (job.pollStopped) content.append(button('放弃取回这次结果', () => {
      app.aiJob = null;
      try { saveAIJob(); } catch (error) { announce(`未能清除浏览器里的任务编号：${error.message}`, true); }
      updateAIJobView();
    }, 'quiet'), el('p', { class: 'inline-note' }, '只清除本页跟踪记录，不向模型发送中止指令。'));
    const usage = callUsage(job);
    if (usage) content.append(usage);
    if (Array.isArray(job.attempts) && job.attempts.length) content.append(el('details', { open: job.attempts.some(attempt => attempt.error) }, el('summary', {}, '实际调用过程与回退原因'), el('ul', { class: 'evidence-list' }, job.attempts.map(attempt => el('li', {}, typeof attempt === 'object' ? [providerName(attempt.provider), attempt.model, attempt.status, attempt.error].filter(Boolean).join(' · ') || text(attempt) : text(attempt))))));
    return content;
  }
  function showingRecipeJob() {
    return !app.brew && app.aiJob?.status === 'running' && !app.aiJob.pollStopped &&
      (!app.bean || sameId(app.bean, app.aiJob.context?.request?.bean_id));
  }
  function updateAIJobView() {
    if (app.data && app.view === 'studio' && showingRecipeJob() !== Boolean($('recipe-wait'))) {
      renderApp();
      return;
    }
    const host = $('ai-job');
    if (host) { const replacement = renderAIJob(); if (replacement) host.replaceWith(replacement); else host.remove(); }
    else if ($('ai-job-holder')) { const job = renderAIJob(); if (job) $('ai-job-holder').replaceChildren(job); }
    const start = $('ai-suggest');
    if (start) { start.disabled = !app.aiSettings || anyAIRunning() || app.busy.has('ai-submit'); start.textContent = aiButtonLabel(); }
    const revise = $('ai-revise');
    if (revise) revise.disabled = !app.aiSettings || anyAIRunning() || app.busy.has('ai-submit');
    updateRecipeProgress();
  }
  function updateRecipeProgress() {
    const job = app.aiJob;
    const host = $('recipe-progress');
    if (!host) return;
    const submitting = Boolean(app.submittingAt);
    host.hidden = app.view !== 'studio' || (!submitting && !showingRecipeJob());
    if (host.hidden) return;
    const message = submitting ? '正在提交拟方请求' : job.pollError ? '正在重新获取任务状态'
      : job.provider ? `${providerName(job.provider)} · ${job.model || ''} 正在拟方` : '请求已收到，等待模型响应';
    if ($('progress-label').textContent !== message) $('progress-label').textContent = message;
    const started = submitting ? app.submittingAt : Date.parse(job.created_at);
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    $('progress-elapsed').textContent = Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : '';
  }
  const brewPhases = {
    registered: '后台已收到启动请求，等待蓝牙连接。',
    connecting: '正在连接 xBloom。',
    connected: '蓝牙已连接，等待机器确认配方。',
    loaded: '机器已装载配方，等待启动回报。',
    started: '机器已回报启动。',
    grinding: '机器已回报研磨。',
    pouring: '机器已回报注水。',
    stopped: '已收到停止信号，继续采集。',
    end_signal: '机器已发出程序结束提示，液重与流速已封存。可以写品饮反馈了。',
    reporting: '采集时段已结束，正在整理记录。',
    unavailable: '暂时读不到执行日志，机器状态待核对。'
  };
  function waterHeading(brew) {
    if (brew.capture_phase === 'no_water') return brew.capture_state === 'running' ? '水箱缺水，请加水' : '本次机器曾报缺水';
    if (brew.capture_phase === 'handshake_timeout') return '请先检查水箱';
    return '';
  }
  function brewAlert(brew) {
    if (brew.capture_phase === 'no_water') {
      return brew.capture_state === 'running'
        ? '机器已报告缺水。请给水箱加水并装回，再看面板是否恢复。'
        : '本次机器报告过缺水。请检查水箱并补足水，再核对面板上的冲煮结果。';
    }
    if (brew.capture_phase === 'handshake_timeout') {
      return '请先检查水箱，水少就加满并装回。本次连接超时，未收到水位回报，也未发送启动指令。';
    }
    if (brew.capture_phase === 'no_update') return '连续 30 秒无有效更新，已停止采集。请按机器面板核对出杯，可以先写品饮反馈。';
    if (brew.capture_error) {
      if (brew.capture_error.includes("No module named 'bleak'")) return '蓝牙组件未加载，本次未连接机器。请检查制作台的蓝牙环境。';
      return `执行出错：${brew.capture_error}。请查看面板，核对是否已经研磨或出水。`;
    }
    return '';
  }
  let brewNotice = null;
  function showBrewProgress(id, reveal = false) {
    brewNotice = { id, collapsed: !reveal && sameId(brewNotice?.id, id) && brewNotice.collapsed };
    updateBrewProgress();
    if (reveal) requestAnimationFrame(() => {
      const host = $('brew-progress');
      if (!host.hidden && getComputedStyle(host).position !== 'sticky') host.scrollIntoView({block:'nearest'});
    });
  }
  function updateBrewProgress() {
    if (!app.data) return;
    const active = app.data.brews.find(brew => brew.capture_state === 'running');
    const pending = Object.entries(app.pending).find(([key, item]) => key.startsWith('start:') && item.database_label === app.data.database_label && getBrew(key.slice(6))?.status === 'prepared');
    if (active && (!brewNotice || (!sameId(active.id, brewNotice.id) && !brewNotice.error && !app.busy.has(`start:${brewNotice.id}`)))) {
      brewNotice = { id: active.id };
    } else if (!brewNotice && pending) {
      brewNotice = { id: pending[0].slice(6) };
    }
    const host = $('brew-progress');
    const brew = brewNotice && getBrew(brewNotice.id);
    if (brew && brew.status === 'completed' && brew.capture_state !== 'running') brewNotice = null;
    host.hidden = !brewNotice || !brew;
    if (host.hidden) return;
    const selected = app.view === 'records' ? app.recordBrew : app.view === 'studio' ? app.brew : '';
    const alert = brewAlert(brew);
    if (!alert && brew.capture_state === 'finished' && sameId(selected, brew.id)) {
      host.hidden = true;
      return;
    }
    let tone = 'active', message;
    if (alert) {
      tone = 'attention';
      message = alert;
    } else if (brew.capture_state === 'finished' || brew.capture_state === 'needs_review') {
      tone = 'attention';
      message = brew.capture_error ? `采集异常：${brew.capture_error}` : brew.capture_state === 'finished'
        ? '采集已结束，可查看当杯报告。出杯结果请按实际情况记录。' : '采集已中断，请核对机器和本杯记录。';
    } else if (brewNotice.syncError) {
      tone = 'attention';
      message = '暂时无法同步机器状态，连接恢复后将继续查询。';
    } else if (brew.capture_state === 'running') {
      message = brewPhases[brew.capture_phase] || brewPhases.registered;
      if (brew.capture_phase === 'unavailable') tone = 'attention';
    } else if (brewNotice.error) {
      tone = 'attention';
      message = brewNotice.error;
    } else if (app.busy.has(`start:${brew.id}`) || app.busy.has(`retry:start:${brew.id}`)) {
      message = '正在提交本杯启动请求…';
    } else {
      tone = 'attention';
      message = '启动请求的结果待核对，请查看机器和本杯记录。';
    }
    if (tone === 'attention' && (tone !== brewNotice.tone || alert !== brewNotice.alert)) brewNotice.collapsed = false;
    brewNotice.alert = alert;
    brewNotice.tone = tone;
    host.dataset.tone = tone;
    host.dataset.collapsed = String(Boolean(brewNotice.collapsed));
    $('brew-progress-title').textContent = `第 ${brew.id} 杯 · ${waterHeading(brew) || (alert ? '请查看机器' : '冲煮进度')}`;
    if ($('brew-progress-message').textContent !== message) $('brew-progress-message').textContent = message;
    $('brew-progress-body').hidden = Boolean(brewNotice.collapsed);
    const toggle = $('brew-progress-toggle');
    const dismiss = tone !== 'active' && brew.capture_state !== 'running' && (brew.capture_state || !app.pending[`start:${brew.id}`]);
    toggle.textContent = dismiss ? '关闭' : brewNotice.collapsed ? '展开' : '收起';
    toggle.setAttribute('aria-expanded', String(!brewNotice.collapsed));
    toggle.onclick = () => {
      if (dismiss) brewNotice = null;
      else brewNotice.collapsed = !brewNotice.collapsed;
      updateBrewProgress();
    };
    const recordLink = $('brew-progress-record');
    const quickFeedback = sameId(selected, brew.id) && brew.capture_phase === 'end_signal';
    recordLink.textContent = quickFeedback ? '现在写品饮反馈' : '查看这杯记录';
    recordLink.href = quickFeedback ? '#brew-feedback' : `/studio?view=records&brew=${brew.id}`;
    recordLink.onclick = quickFeedback ? event => {
      const feedback = $('brew-feedback');
      if (!feedback) return;
      event.preventDefault();
      if (feedback.tagName === 'DETAILS') feedback.open = true;
      feedback.scrollIntoView({block:'start'});
      feedback.querySelector('.feedback-card summary')?.focus({preventScroll:true});
    } : null;
  }
  function brewSyncFailed(error) {
    $('updated').textContent = `状态同步失败：${error.message}`;
    if (brewNotice) { brewNotice.syncError = true; updateBrewProgress(); }
  }
  function acceptAIJob(job, context) {
    if (job.kind === 'recommendation') throw new Error('接口返回了豆单推荐，不能作为冲煮配方载入。');
    app.aiJob = { ...job, context: context || app.aiJob?.context };
    saveAIJob();
    const url = new URL(location.href);
    if (app.view === 'studio' && url.searchParams.has('proposal')) {
      url.searchParams.set('proposal', job.id);
      history.replaceState(history.state, '', url);
    }
    updateAIJobView();
    finishAIJob();
  }
  function finishAIJob() {
    const job = app.aiJob;
    const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    const reopening = app.resumeProposal === job?.id && !app.brew && !app.bean && !app.draft;
    if (job?.status === 'completed' && job.result && !job.applied && !app.brew && (reopening || aiMatchesCurrent(job)) && !editing && app.view === 'studio') loadAIResult(job);
    else updateAIJobView();
  }
  async function pollAIJob() {
    const job = app.aiJob;
    if (!job?.id || app.aiPolling || job.pollStopped || job.context?.database_label !== app.data?.database_label) return;
    app.aiPolling = true;
    try {
      const updated = await api(`${API}/ai/jobs/${encodeURIComponent(job.id)}`);
      if (app.aiJob?.id !== job.id) return;
      app.aiJob = { ...updated, context: job.context, applied: job.applied };
      saveAIJob();
      finishAIJob();
      if (job.status === 'running' && updated.status !== 'running' && !app.aiJob.applied && !app.brew && app.view === 'studio') {
        const ready = updated.status === 'completed';
        announce(ready ? '新配方已准备好，可以查看。' : (updated.error || '拟方任务已中断。'), !ready);
        $('notice').append(button(ready ? '查看配方' : '查看任务', () => {
          $('notice').hidden = true;
          if (ready) confirmLoadAIResult(app.aiJob);
          else $('ai-job')?.scrollIntoView({ block: 'center' });
        }, 'quiet'));
      }
    } catch (error) {
      if (app.aiJob?.id === job.id) { app.aiJob.pollError = error.message; app.aiJob.pollStopped = error.status === 404; }
      updateAIJobView();
    } finally { app.aiPolling = false; }
  }
  async function resumeAIJob() {
    try {
      const proposal = new URLSearchParams(location.search).get('proposal');
      const saved = JSON.parse(localStorage.getItem(AI_JOB_KEY) || 'null');
      if (proposal && !(proposal === saved?.id && saved.context?.database_label === app.data.database_label)) {
        const job = await api(`${API}/ai/jobs/${encodeURIComponent(proposal)}`);
        if (job.kind !== 'recipe') throw new Error('这份记录不是冲煮配方');
        const request = { bean_id: job.bean_id, mode: job.mode, goal: job.goal, dose_grams: job.dose_grams ?? job.result?.payload?.doseGrams, person_id: job.person_id, base_recipe_id: job.base_recipe_id };
        app.aiJob = { ...job, context: aiContext(request) };
        app.resumeProposal = job.id;
      } else if (saved?.id && saved.context?.request && saved.context.database_label === app.data.database_label) {
        app.aiJob = saved;
        app.resumeProposal = proposal || (saved.status === 'running' ? saved.id : null);
        await pollAIJob();
      }
      if (app.resumeProposal && app.aiJob?.result && app.aiJob.status === 'completed' && !app.brew && !app.bean && !app.draft && app.view === 'studio') loadAIResult(app.aiJob);
      else updateAIJobView();
    } catch (error) { announce(`未能取回上次拟方任务：${error.message}`, true); }
    try {
      const saved = JSON.parse(localStorage.getItem(RECOMMEND_JOB_KEY) || '{}');
      for (const [person, job] of Object.entries(saved)) {
        if (job?.id && job.context?.database_label === app.data.database_label) { app.recommendJobs[person] = job; pollRecommendation(person); }
      }
      app.menuUpdate?.();
    } catch (error) { announce(`未能取回上次口味推荐：${error.message}`, true); }
  }
  function saveRecommendations() {
    const saved = Object.fromEntries(Object.entries(app.recommendJobs).map(([person, job]) => [person, { id: job.id, status: job.status, kind: 'recommendation', context: job.context }]));
    localStorage.setItem(RECOMMEND_JOB_KEY, JSON.stringify(saved));
  }
  function acceptRecommendation(job, context) {
    const person = context.person_id;
    if (job.kind && job.kind !== 'recommendation') throw new Error('接口未返回豆单推荐任务。');
    app.recommendJobs[person] = { ...job, context };
    saveRecommendations();
    finishRecommendation(person);
  }
  function finishRecommendation(person) {
    const job = app.recommendJobs[person];
    const result = job.result;
    if (job.status === 'completed' && result && (!sameId(result.person_id, person) || !Array.isArray(result.items))) {
      job.status = 'failed'; job.error = '推荐结果的品饮者不匹配，没有使用这份推荐。'; job.result = null;
    }
    if (job.status === 'completed' && job.result && !job.displayed && sameId(app.person, person) && app.view === 'menu' && app.menuSearch === job.context.menuSearch && app.menuScope === job.context.menuScope && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
      app.menuScope = 'taste'; job.displayed = true;
    }
    if (app.view === 'menu') app.menuUpdate?.();
    updateAIJobView();
  }
  async function pollRecommendation(person) {
    const job = app.recommendJobs[person];
    if (!job?.id || job.polling || job.pollStopped || job.context?.database_label !== app.data?.database_label) return;
    job.polling = true;
    try {
      const updated = await api(`${API}/ai/jobs/${encodeURIComponent(job.id)}`);
      if (app.recommendJobs[person]?.id !== job.id) return;
      app.recommendJobs[person] = { ...updated, context: job.context, displayed: job.displayed };
      if (updated.status === 'completed') await refresh(false);
      saveRecommendations();
      finishRecommendation(person);
    } catch (error) {
      if (app.recommendJobs[person]?.id === job.id) { app.recommendJobs[person].pollError = error.message; app.recommendJobs[person].pollStopped = error.status === 404; }
      if (app.view === 'menu') app.menuUpdate?.();
    } finally { if (app.recommendJobs[person]) app.recommendJobs[person].polling = false; }
  }
  function renderPreference() {
    if (!app.person) return null;
    const person = app.person;
    const previous = getPreference(person);
    const preference = textarea(previous.preference_text, { placeholder: '喜欢的口感、浓淡，以及不喜欢什么，直接写自己的话。' });
    const message = el('p', { class: 'inline-note', role: 'status' });
    return el('details', { class: 'preference-editor' }, el('summary', {}, `${personName(person)}的口味偏好`), el('div', {}, field('我的偏好', preference), message, button('保存偏好', event => run(`preference:${person}`, event.currentTarget, async () => {
      const result = await write(`preference:${person}`, `${API}/preferences`, { person_id: Number(person), preference_text: preference.value.trim(), expected_revision: previous.revision }, `保存${personName(person)}的偏好`);
      app.data.preferences = app.data.preferences.filter(item => !sameId(item.person_id, person));
      app.data.preferences.push(result);
      previous.revision = result.revision;
      message.textContent = '偏好已保存，可以重新按口味推荐。';
      message.className = 'inline-note';
      app.menuUpdate?.();
    }, error => { message.textContent = error.message; message.className = 'dialog-error'; }), 'secondary')));
  }
  function renderRecommendationStatus() {
    const job = app.recommendJobs[app.person];
    if (!job) return el('p', { class: 'inline-note' }, '按个人偏好与已有反馈推荐，今日轮换不代表口味匹配。');
    const state = el('div', { class: 'recommendation-status' });
    if (job.status === 'running') state.append(el('p', {}, `${providerName(job.provider)} 正在为${personName(app.person)}挑选豆子…`));
    else if (job.status === 'completed' && job.result) {
      const changed = job.context.preference_revision != null && job.context.preference_revision !== getPreference(app.person).revision;
      state.append(el('p', {}, changed ? '偏好已更新，可以重新推荐。下方保留上一份结果。' : '口味推荐已生成，理由与介绍显示在豆卡上。'), button('查看口味推荐', () => { app.menuScope = 'taste'; app.menuSearch = ''; if ($('menu-search')) $('menu-search').value = ''; app.menuUpdate?.(); }, 'secondary'));
    } else if (['failed', 'interrupted'].includes(job.status)) state.append(el('p', { class: 'dialog-error' }, job.error || '本次口味推荐未完成，请重试。'));
    if (job.provider || job.model) state.append(el('p', { class: 'inline-note' }, `实际提供方：${providerName(job.provider)}${job.model ? ` · ${job.model}` : ''}`));
    const usage = callUsage(job);
    if (usage) state.append(usage);
    if (Array.isArray(job.attempts) && job.attempts.some(attempt => attempt.error)) state.append(el('details', { open: true }, el('summary', {}, '调用与回退原因'), listContent(job.attempts.map(attempt => [providerName(attempt.provider), attempt.model, attempt.error || attempt.status].filter(Boolean).join(' · ')))));
    if (job.pollError) state.append(el('p', { class: 'dialog-error' }, `状态读取失败：${job.pollError}`), button('重试读取', () => { job.pollStopped = false; pollRecommendation(app.person); }, 'secondary'));
    if (job.pollStopped) state.append(button('放弃取回这次推荐', () => { delete app.recommendJobs[app.person]; saveRecommendations(); app.menuUpdate?.(); updateAIJobView(); }, 'quiet'));
    return state;
  }

  try {
    app.pending = JSON.parse(localStorage.getItem(PENDING_KEY) || '{}');
    if (!app.pending || typeof app.pending !== 'object' || Array.isArray(app.pending)) throw new Error('invalid');
    localStorage.setItem(PENDING_KEY, JSON.stringify(app.pending));
  } catch (_) {
    app.pending = {};
    app.storageReady = false;
  }
  function savePending() {
    try { localStorage.setItem(PENDING_KEY, JSON.stringify(app.pending)); }
    catch (_) { app.storageReady = false; throw new Error('浏览器无法保存请求编号。请允许本站本地存储后再写入，避免刷新或重试产生重复记录。'); }
  }
  async function api(path, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(path, { method: payload ? 'POST' : 'GET', credentials: 'same-origin', headers: payload ? { 'Content-Type': 'application/json' } : {}, body: payload ? JSON.stringify(payload) : undefined, signal: controller.signal, cache: 'no-store' });
      const raw = await response.text();
      let data;
      try { data = JSON.parse(raw); } catch (_) { throw new Error(`服务返回了无法读取的内容（HTTP ${response.status}）。`); }
      if (!response.ok) {
        const error = new Error(typeof data.error === 'string' ? data.error : data.message || text(data.error) || `请求失败（HTTP ${response.status}）`);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      const configuration = [`${API}/ai/settings`, `${API}/ai/status`, `${API}/ai/credentials/deepseek`].includes(path);
      if (configuration && error.name === 'AbortError') throw new Error('配置请求超时，保存结果尚未确认。请重新检查配置状态或读取本页设置。');
      if (configuration && error instanceof TypeError) throw new Error('无法连接本机服务，请恢复服务后重新读取 AI 设置。');
      if (error.name === 'AbortError') throw new Error('请求超时，服务端可能已保存。下方保留了原请求，可使用同一编号重试核对。');
      if (error instanceof TypeError) throw new Error('无法连接本机服务。结果尚未确认；请检查服务后重试原请求。');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  async function write(scope, path, payload, label) {
    if (!app.data) throw new Error('请先成功读取当前工作台，再保存记录。');
    if (!app.storageReady) throw new Error('本站本地存储不可用，暂不能保存业务记录。请允许浏览器保存本站数据并重新加载。');
    const original = app.pending[scope];
    const signature = JSON.stringify(payload);
    if (original && original.database_label !== app.data.database_label) throw new Error('这条未确认请求来自另一份库存。请回到原库存服务核对，不能重放到当前库存。');
    if (original && JSON.stringify(original.payload) !== signature) throw new Error(`“${original.label}”还有结果未确认。请先重试下方原请求，再提交改动后的内容。`);
    if (!original) {
      app.pending[scope] = { path, payload, label, database_label: app.data.database_label, request_id: crypto.randomUUID(), created_at: new Date().toISOString() };
      savePending();
    }
    renderPending();
    try {
      const item = app.pending[scope];
      if (scope.startsWith('start:')) showBrewProgress(scope.slice(6), true);
      const result = await api(item.path, { ...item.payload, request_id: item.request_id });
      delete app.pending[scope];
      savePending();
      renderPending();
      return result;
    } catch (error) {
      if ([400, 401, 403, 404, 405, 409, 422].includes(error.status)) {
        delete app.pending[scope];
        savePending();
      }
      if (error.status === 409 && payload.expected_ai) await syncAISettings();
      renderPending();
      throw error;
    }
  }
  async function run(key, sourceButton, action, onError) {
    if (app.busy.has(key)) return;
    app.busy.add(key);
    const original = sourceButton?.textContent;
    if (sourceButton) { sourceButton.disabled = true; sourceButton.textContent = '处理中…'; }
    try { await action(); }
    catch (error) { if (onError) onError(error); else announce(error.message || String(error), true); }
    finally {
      app.busy.delete(key);
      if (sourceButton?.isConnected) { sourceButton.disabled = false; sourceButton.textContent = original; }
      if (key.startsWith('start:') || key.startsWith('retry:start:')) {
        renderPending();
        const start = $('start-brew');
        if (start) start.disabled = !app.data.capabilities?.bluetooth_start || getBrew(app.brew)?.status !== 'prepared' || Boolean(app.pending[`start:${app.brew}`]);
        updateBrewProgress();
      }
      syncMenuOrderButtons();
      if (key === 'ai-submit') updateAIJobView();
      if (key.startsWith('recommend:') && app.view === 'menu') app.menuUpdate?.();
    }
  }
  function renderPending() {
    const host = $('pending');
    host.replaceChildren();
    const entries = Object.entries(app.pending);
    if (!entries.length) return;
    host.append(el('div', { class: 'pending-box' }, el('strong', {}, '有请求等待核对结果'), el('p', {}, '重试沿用原编号和原内容。刷新页面后仍会保留，避免重复点单、开杯或扣豆。'), entries.map(([scope, item]) => el('div', { class: 'pending-row' }, el('span', {}, `${item.label} · ${formatTime(item.created_at)}`), button(item.path.endsWith('/start') ? '重试同一开始请求' : '重试原请求', event => run(`retry:${scope}`, event.currentTarget, async () => {
      const result = await write(scope, item.path, item.payload, item.label);
      adoptResult(item.path, result, item.payload);
      if (!item.path.endsWith('/start')) await refresh();
      announce(`${item.label}的结果已核对。`);
      if (item.path === `${API}/orders`) orderReceipt(result);
    }), 'secondary', scope.startsWith('start:') && (app.busy.has(scope) || app.busy.has(`retry:${scope}`)))))));
  }
  function adoptResult(path, result, request) {
    if (/^\/api\/product\/brews\/\d+\/start$/.test(path) && result.id) {
      app.data.brews = app.data.brews.map(b => sameId(b.id, result.id) ? result : b);
      const order = getOrder(result.order_id);
      if (order) order.status = result.status;
      showBrewProgress(result.id);
      updateBrewStatus();
      pollBrew();
    }
    if (/^\/api\/product\/brews\/\d+\/rinse$/.test(path) && result.id) {
      app.data.brews = app.data.brews.map(b => sameId(b.id, result.id) ? result : b);
      updateBrewStatus();
      pollBrew();
    }
    if (path === `${API}/recipes`) loadDraft(result);
    if (path === `${API}/brews` && result.id) {
      app.brew = result.id;
      if (app.view === 'studio') history.replaceState(null, '', `/studio?cup=${result.id}`);
    }
    if (path === `${API}/orders` || /^\/api\/product\/orders\/\d+\/(update|cancel|delete)$/.test(path)) applyOrderResult(result, path.split('/').pop());
    if (path === `${API}/ai/suggest`) acceptAIJob(result, { ...aiContext(request), draftText: null });
    if (path === `${API}/ai/recommend`) acceptRecommendation(result, { person_id: request.person_id, preference_revision: null, database_label: app.data.database_label });
  }
  async function refresh(render = true) {
    const [data] = await Promise.all([api(`${API}/state`), syncAISettings()]);
    for (const key of ['beans', 'people', 'recipes', 'orders', 'brews', 'experiences', 'feedback']) {
      if (!Array.isArray(data[key])) throw new Error(`服务缺少 ${key} 列表，暂不能显示完整工作台。`);
    }
    app.data = data;
    if (brewNotice) brewNotice.syncError = false;
    updateBrewProgress();
    if (!Array.isArray(app.data.preferences)) app.data.preferences = [];
    $('database-label').textContent = `${data.database_label || '本机'}工作台`;
    if (!app.person || !getPerson(app.person)) app.person = data.people[0]?.id || '';
    $('updated').textContent = `最近同步 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
    if (render) renderApp();
    else updateBrewStatus();
  }
  function navigate(view, brewId) {
    app.view = view;
    if (view === 'records') app.recordBrew = brewId || '';
    const path = view === 'menu' ? '/menu' : view === 'experiences' ? '/experiences' : view === 'ai' ? '/studio?view=ai' : view === 'records' ? `/studio?view=records${brewId ? `&brew=${encodeURIComponent(brewId)}` : ''}` : app.brew ? `/studio?cup=${encodeURIComponent(app.brew)}` : '/studio';
    if (location.pathname + location.search !== path) history.pushState({ view }, '', path);
    renderApp();
    if (view === 'studio' || view === 'menu') syncAISettings();
  }
  function renderApp() {
    document.querySelectorAll('[data-view]').forEach(link => {
      if (link.dataset.view === app.view) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    document.title = `${app.view === 'menu' ? '今日豆单' : app.view === 'studio' ? '制作台' : app.view === 'records' ? '冲煮记录' : app.view === 'ai' ? '全局设置' : '经验'} · 日常咖啡`;
    if (!app.data) return;
    $('main').replaceChildren(app.view === 'menu' ? renderMenu() : app.view === 'studio' ? renderStudio() : app.view === 'records' ? renderRecords() : app.view === 'ai' ? renderAISettingsPage() : renderExperiences());
    updateRecipeProgress();
    updateBrewProgress();
    syncMenuOrderButtons();
    renderPending();
  }
  function intro(eyebrow, title, description, side) {
    return el('div', { class: 'page-intro' }, el('div', {}, el('div', { class: 'eyebrow' }, eyebrow), el('h1', {}, title), el('p', { class: 'intro-copy' }, description)), side && el('div', { class: 'intro-side' }, side));
  }
  function dailyBeans() {
    if (Array.isArray(app.data.menu)) return app.data.menu.filter(bean => Number(bean.net_weight) >= 15).slice(0, 5);
    const beans = app.data.beans.filter(bean => Number(bean.net_weight) >= 15).sort((a, b) => Number(a.id) - Number(b.id));
    if (!beans.length) return [];
    const offset = Array.from(today()).reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 0) % beans.length;
    const rotated = beans.slice(offset).concat(beans.slice(0, offset));
    const chosen = [], profiles = new Set();
    for (const bean of rotated) {
      const profile = `${bean.country || ''}/${bean.process || ''}/${text(bean.source_flavor)}`;
      if (!profiles.has(profile)) { chosen.push(bean); profiles.add(profile); }
      if (chosen.length === 5) break;
    }
    for (const bean of rotated) { if (chosen.length >= 5) break; if (!chosen.includes(bean)) chosen.push(bean); }
    return chosen;
  }
  function renderMenu() {
    const selection = select(app.data.people.map(person => ({ value: person.id, label: person.name })), app.person, event => { app.person = event.target.value; app.menuBrew = ''; app.menuOrders = false; if (app.menuScope === 'taste') app.menuScope = 'recommended'; renderApp(); });
    const recommended = dailyBeans();
    const inStock = app.data.beans.filter(bean => Number(bean.net_weight) > 0).sort((a, b) => `${a.roaster || ''} ${a.name}`.localeCompare(`${b.roaster || ''} ${b.name}`, 'zh-CN'));
    const results = el('div');
    const resultCount = el('p', { class: 'menu-result-count', role: 'status', 'aria-live': 'polite' });
    const search = input(app.menuSearch, { type: 'search', placeholder: '烘焙商 / 豆名 / 产地 / 处理法 / 风味', oninput: event => { app.menuSearch = event.target.value; updateResults(); } });
    search.id = 'menu-search';
    const recommendationStatus = el('div');
    const recommendButton = button('按我的口味推荐', event => run(`recommend:${app.person}`, event.currentTarget, async () => {
      if (anyAIRunning()) throw new Error('已有 AI 任务进行中，请等待当前结果。');
      const person = Number(app.person);
      const context = { person_id: person, preference_revision: getPreference(person).revision, database_label: app.data.database_label, menuScope: app.menuScope, menuSearch: app.menuSearch };
      const job = await write(`recommend:${person}`, `${API}/ai/recommend`, { person_id: person, ...expectedAI() }, `为${personName(person)}推荐咖啡`);
      acceptRecommendation(job, context);
    }), '', !app.person || anyAIRunning());
    const scopes = [['recommended', `今日轮换 · ${recommended.length}`], ['all', `全部在库 · ${inStock.length}`], ['taste', '我的口味推荐']].map(([value, label]) => {
      const control = button(label, () => { app.menuScope = value; app.menuSearch = ''; search.value = ''; updateResults(); }, 'secondary');
      control.dataset.scope = value;
      return control;
    });
    function renderCard(bean, recommendation) {
      const note = bean.story || bean.source_notes;
      const flavor = Array.isArray(bean.source_flavor) ? bean.source_flavor.join(' · ') : text(bean.source_flavor);
      const enoughStock = Number(bean.net_weight) >= 15;
      const existing = activeOrder(bean.id, app.person, 'xbloom');
      const orderButton = button(existing ? `已点单 #${existing.id}` : enoughStock ? '就喝这款' : '不足 15 g', event => run(`order:${bean.id}:${app.person}`, event.currentTarget, async () => {
        const person = app.person;
        const queued = activeOrder(bean.id, person, 'xbloom');
        if (queued) { orderReceipt(queued, true); return; }
        const result = await write(`order:${bean.id}:${person}`, `${API}/orders`, { bean_id: bean.id, person_id: Number(person), mode: 'xbloom', note: '' }, `${personName(person)}点单：${bean.name}`);
        applyOrderResult(result);
        renderApp();
        orderReceipt(result);
        if (await refreshAfterSaved(`订单 #${result.id} 已保存`)) announce(`已为${personName(person)}点好「${bean.name}」，订单 #${result.id}。制作人会审核配方后开始。`);
      }), '', !app.person || !enoughStock || !!existing || app.busy.has(`order:${bean.id}:${app.person}`));
      orderButton.dataset.orderBean = bean.id;
      orderButton.dataset.orderPerson = app.person;
      const personal = recommendation && el('div', { class: 'personal-recommendation' }, el('span', { class: 'field-caption' }, `AI 为${personName(app.person)}推荐`), el('p', {}, recommendation.reason), recommendation.story && el('p', { class: 'small muted' }, recommendation.story), recommendation.evidence?.length > 0 && el('details', {}, el('summary', {}, '推荐依据'), listContent(recommendation.evidence.map(item => typeof item === 'object' ? [item.title, item.excerpt].filter(Boolean).join('：') || text(item) : item))));
      return el('article', { class: 'bean-card' }, el('p', { class: 'card-roaster' }, bean.roaster || '烘焙商未记录'), el('h2', {}, bean.name), el('p', { class: 'bean-meta' }, [bean.country, bean.process, bean.variety_name].filter(Boolean).join(' · ') || '产地与处理信息待补充'), el('div', { class: 'flavor' }, el('span', { class: 'field-caption' }, `${bean.source_label || '来源标注风味'} · 非个人品鉴`), flavor || '风味尚未收录，留待这一杯记录。'), personal || (note && el('p', { class: 'story', title: text(note) }, text(note))), el('div', { class: 'bean-bottom' }, el('div', { class: 'stock' }, el('span', {}, `余量 ${showValue(bean.net_weight, ' g')}`), el('br'), bean.storage_state || '储存方式未记录'), orderButton));
    }
    const tasteTools = el('section', { class: 'recommendation-tools' }, renderPreference(), recommendButton, recommendationStatus);
    function updateResults() {
      const query = app.menuSearch.trim().toLowerCase();
      const scope = query ? 'all' : app.menuScope;
      const terms = query.split(/\s+/).filter(Boolean);
      const job = app.recommendJobs[app.person];
      const items = job?.status === 'completed' && sameId(job.result?.person_id, app.person) && Array.isArray(job.result?.items) ? job.result.items : [];
      const recommendations = new Map(items.map(item => [String(item.bean_id), item]));
      const source = scope === 'taste' ? items.map(item => getBean(item.bean_id)).filter(Boolean) : scope === 'all' ? inStock : recommended;
      const beans = source.filter(bean => {
        const searchable = [bean.roaster, bean.name, bean.country, bean.process, bean.variety_name, bean.roast_date, text(bean.source_flavor), bean.source_notes].join(' ').toLowerCase();
        return terms.every(term => searchable.includes(term));
      });
      scopes.forEach(control => control.setAttribute('aria-pressed', String(control.dataset.scope === scope)));
      tasteTools.hidden = scope !== 'taste';
      resultCount.textContent = query ? `在全部 ${inStock.length} 款在库豆子中，找到 ${beans.length} 款` : scope === 'taste' ? `为${personName(app.person)}推荐 ${beans.length} 款 · 按当前库存余量显示` : scope === 'all' ? `全部在库 ${beans.length} 款 · 余量不足 15 g 暂不可点单` : `今日轮换 ${beans.length} 款 · 可切换全部在库，或直接搜索`;
      results.replaceChildren(beans.length ? el('div', { class: 'menu-grid' }, beans.map(bean => renderCard(bean, scope === 'taste' ? recommendations.get(String(bean.id)) : null))) : empty(query ? '没有找到匹配的豆子' : '暂时没有可选的豆子', query ? '试试烘焙商、豆名、产地或风味，搜索范围包含全部在库豆子。' : '可以查看全部在库，或到库存页核对余量。'));
      recommendationStatus.replaceChildren(renderRecommendationStatus());
      recommendButton.disabled = !app.person || anyAIRunning() || app.busy.has(`recommend:${app.person}`);
      recommendButton.textContent = job?.status === 'running' ? '正在按口味推荐…' : items.length ? '重新按我的口味推荐' : '按我的口味推荐';
      syncMenuOrderButtons();
    }
    app.menuUpdate = updateResults;
    updateResults();
    const myOrders = newest(app.data.orders.filter(order => sameId(order.person_id, app.person)));
    const recentOrders = myOrders.map(order => {
      const brew = orderBrew(order);
      return el('div', { class: 'order-row order-managed' }, el('div', { class: 'order-copy' }, el('strong', {}, beanName(order.bean_id)), el('p', {}, `订单 #${order.id} · ${MODES[order.mode] || order.mode} · ${formatTime(order.created_at)}`), order.note && el('p', {}, order.note), statusPill(order, 'order')), el('div', { class: 'order-controls' }, brew && brew.status !== 'cancelled' && button('写下感受', () => { app.menuBrew = brew.id; renderApp(); $('guest-feedback')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 'secondary'), renderOrderActions(order)));
    });
    const selectedBrew = getBrew(app.menuBrew);
    const feedback = selectedBrew && myOrders.some(order => sameId(order.id, selectedBrew.order_id)) ? el('section', { class: 'panel section-gap', id: 'guest-feedback' }, el('div', { class: 'section-title' }, el('h2', {}, `这杯「${beanName(selectedBrew.bean_id)}」喝起来如何？`)), brewParameters(selectedBrew), renderFeedback(selectedBrew, app.person)) : null;
    if (feedback) return el('div', { class: 'flow-page' }, button('返回我的订单', () => { app.menuBrew = ''; renderApp(); }, 'quiet'), feedback);
    if (app.menuOrders) return el('div', { class: 'flow-page' }, el('header', { class: 'flow-heading' }, el('h1', {}, `${personName(app.person)}的订单`),
      button('返回选豆', () => { app.menuOrders = false; renderApp(); }, 'secondary')), el('div', { class: 'order-list', id: 'my-orders' }, recentOrders));
    return el('div', {}, el('header', { class: 'flow-heading' }, el('h1', {}, '今日豆单'),
      el('div', { class: 'actions' }, field('这杯给谁', selection), myOrders.length > 0 && button('我的订单', () => { app.menuOrders = true; renderApp(); }, 'secondary'))),
      el('div', { class: 'menu-toolbar' }, el('div', { class: 'menu-switch', role: 'group', 'aria-label': '豆单范围' }, scopes), field('搜索全部在库', search)),
      tasteTools, resultCount, results);
  }
  function orderPermissions(order) {
    const brew = orderBrew(order);
    const untouched = !brew && order.status === 'ordered';
    const prepared = brew && order.status === 'prepared' && brew.status === 'prepared' && brew.capture_state == null && brew.machine_completion == null && brew.consumption_g == null && !brew.journal && Object.keys(brew.observations || {}).length === 0;
    return { brew, edit: untouched, cancel: untouched || !!prepared, remove: !brew && ['ordered', 'cancelled'].includes(order.status) };
  }
  function renderOrderActions(order) {
    const allowed = orderPermissions(order);
    const actions = [allowed.edit && button('编辑', () => editOrder(order), 'quiet'), allowed.cancel && button('取消订单', () => confirmOrderAction(order, 'cancel'), 'quiet'), allowed.remove && button('删除', () => confirmOrderAction(order, 'delete'), 'quiet')].filter(Boolean);

    return actions.length ? el('details', { class: 'flow-extra' }, el('summary', {}, '管理订单'), el('div', { class: 'order-actions' }, actions)) : null;
  }
  function editOrder(order) {
    const beans = app.data.beans.filter(bean => Number(bean.net_weight) >= 15 || sameId(bean.id, order.bean_id));
    const bean = select(beans.map(item => ({ value: item.id, label: `${item.roaster || '烘焙商未记录'} · ${item.name} · ${showValue(item.net_weight, ' g')}` })), order.bean_id);
    const person = select(app.data.people.map(item => ({ value: item.id, label: item.name })), order.person_id);
    const mode = select(Object.entries(MODES).map(([value, label]) => ({ value, label })), order.mode);
    const note = textarea(order.note, { placeholder: '想喝的感觉或其他说明，可留空。' });
    const view = openDialog(`编辑订单 #${order.id}`, field('豆子', bean), el('div', { class: 'two-fields' }, field('这杯给谁', person), field('制作方式', mode)), field('点单备注', note));
    view.dialog.append(el('div', { class: 'actions' }, button('保存修改', event => run(`order-update:${order.id}`, event.currentTarget, async () => {
      const result = await write(`order-update:${order.id}`, `${API}/orders/${order.id}/update`, { expected: orderSnapshot(order), bean_id: Number(bean.value), person_id: Number(person.value), mode: mode.value, note: note.value.trim() }, `修改订单 #${order.id}`);
      applyOrderResult(result, 'update');
      view.dialog.close();
      renderApp();
      if (await refreshAfterSaved(`订单 #${order.id} 已修改`)) announce(`订单 #${order.id} 已修改。`);
    }, view.error)), button('不修改', () => view.dialog.close(), 'secondary')));
  }
  function confirmOrderAction(order, action) {
    const allowed = orderPermissions(order);
    const deleting = action === 'delete';
    const title = `${deleting ? '删除' : '取消'}订单 #${order.id}`;
    const notStarted = input('', { type: 'checkbox', checked: false });
    const view = openDialog(title, el('p', {}, `${personName(order.person_id)} · ${beanName(order.bean_id)}`), el('p', { class: 'inline-note' }, deleting ? '这张未开杯订单将从列表移除，不改库存、配方或机器状态。' : allowed.brew ? `同时取消当杯 #${allowed.brew.id} 尚未开始的准备。此操作不发送机器停止命令。` : '取消后不再进入待制作队列，也不会扣豆。'), !deleting && allowed.brew && el('label', { class: 'confirmation' }, notStarted, el('span', {}, '我确认这一杯尚未实际制作，未研磨、未出水，也未消耗豆子。')));
    view.dialog.append(el('div', { class: 'actions' }, button(deleting ? '删除这张订单' : '确认取消订单', event => run(`order-${action}:${order.id}`, event.currentTarget, async () => {
      if (!deleting && allowed.brew && !notStarted.checked) throw new Error('请确认这杯尚未实际开始；已经开始或情况不明时，不能按取消准备处理。');
      const result = await write(`order-${action}:${order.id}`, `${API}/orders/${order.id}/${action}`, { expected: orderSnapshot(order) }, `${deleting ? '删除' : '取消'}订单 #${order.id}`);
      applyOrderResult(result, action);
      view.dialog.close();
      renderApp();
      if (await refreshAfterSaved(`订单 #${order.id} 已${deleting ? '删除' : '取消'}`)) announce(`订单 #${order.id} 已${deleting ? '删除' : '取消'}。`);
    }, view.error), deleting ? 'danger' : ''), button('保留订单', () => view.dialog.close(), 'secondary')));
  }
  function abandonSelection() {
    app.resumeProposal = null;
    history.replaceState(null, '', '/studio');
    app.bean = ''; app.order = ''; app.brew = ''; app.draft = null; app.draftText = ''; app.dirty = false; app.goal = '';
    renderApp();
    announce('已放弃当前选择。订单和制作记录仍保留，设备状态没有改变。');
  }
  function selectBean(beanId, order = null) {
    app.bean = beanId;
    app.dose = 15;
    app.order = order?.id || '';
    app.mode = order?.mode || app.mode;
    app.draft = null; app.draftText = ''; app.dirty = false; app.brew = '';
    if (order?.recipe_id && getRecipe(order.recipe_id)) loadDraft(getRecipe(order.recipe_id));
    if (order) app.brew = orderBrew(order)?.id || '';
    if (app.brew) history.replaceState(null, '', `/studio?cup=${app.brew}`);
    renderApp();
    $('main').scrollIntoView({ block:'start' });
  }
  function loadDraft(recipe) {
    app.draft = { ...recipe };
    app.draftText = JSON.stringify(recipe.payload, null, 2);
    app.dirty = false;
    app.bean = recipe.bean_id || app.bean;
    app.mode = recipe.mode || app.mode;
    app.dose = recipe.payload.doseGrams;
    app.goal = recipe.goal || '';
  }
  function renderInventory() {
    const host = el('div', { class: 'inventory-list' });
    function updateList() {
      const query = app.search.trim().toLowerCase();
      const beans = app.data.beans.filter(bean => Number(bean.net_weight) >= 15 && (!query || [bean.name, bean.roaster, bean.country, bean.process, text(bean.source_flavor)].join(' ').toLowerCase().includes(query)));
      host.replaceChildren(...beans.map(bean => el('button', { type: 'button', class: `inventory-item${sameId(app.bean, bean.id) ? ' active' : ''}`, onclick: () => selectBean(bean.id) }, el('span', { class: 'roaster' }, bean.roaster || '烘焙商未记录'), el('strong', {}, bean.name), el('small', {}, [bean.country, bean.process, `${bean.net_weight} g`].filter(Boolean).join(' · ')))));
      if (!beans.length) host.append(el('p', { class: 'list-empty' }, '没有匹配的可用豆子。'));
    }
    updateList();
    return panel('选豆', field('筛选可用库存', input(app.search, { type: 'search', placeholder: '豆名 / 烘焙商 / 产地 / 风味', oninput: event => { app.search = event.target.value; updateList(); } })), host);
  }
  function renderOrders() {
    const orders = newest(app.data.orders.filter(order => !closedOrder(order)));
    return panel(`待制作订单 · ${orders.length}`, orders.length ? el('div', { class: 'order-list' }, orders.map(order => el('div', { class: 'order-row order-managed' }, el('div', { class: 'order-copy' }, el('strong', {}, `${personName(order.person_id)} · ${beanName(order.bean_id)}`), el('p', {}, `#${order.id} · ${MODES[order.mode] || order.mode}`), order.note && el('p', {}, order.note), statusPill(order, 'order')), el('div', { class: 'order-controls' }, button(sameId(app.order, order.id) ? '已选' : orderBrew(order) ? '查看这杯' : '接这杯', () => selectBean(order.bean_id, order), 'secondary', sameId(app.order, order.id)), renderOrderActions(order))))) : el('p', { class: 'muted small' }, '暂时没有待制作订单，也可以直接选豆为自己做一杯。'));
  }
  function renderStudio() {
    const brew = getBrew(app.brew);
    const bean = getBean(app.bean);
    const job = el('div', { id: 'ai-job-holder' }, renderAIJob());
    let heading, content;
    if (app.brew && !brew) {
      return panel('未找到这次冲煮', button('返回制作台', abandonSelection, 'secondary'));
    }
    if (brew) {
      heading = beanName(brew.bean_id);
      content = renderBrew(brew.id);
    } else if (showingRecipeJob()) {
      heading = '正在拟定配方';
      content = el('div', { id: 'recipe-wait' }, job);
    } else if (app.draft) {
      heading = beanName(app.draft.bean_id);
      const changePlan = () => {
        app.draft = null; app.draftText = ''; app.dirty = false;
        renderApp();
      };
      const back = button('重新选择冲煮方案', () => {
        if (!app.dirty && app.draft.id) { changePlan(); return; }
        const view = openDialog('离开当前草稿？', el('p', {}, '重新选择方案会舍弃这份未保存的草稿。'));
        view.dialog.append(button('重新选择', () => { view.dialog.close(); changePlan(); }));
      }, 'quiet');
      content = el('div', { class: 'stack' }, job, renderRecipe(), back);
    } else if (bean) {
      heading = '选择冲煮方案';
      content = el('div', { class: 'stack' }, job, renderPlanning(bean));
    } else {
      heading = '开始制作';
      const openBrews = newest(app.data.brews.filter(b => !b.order_id && ['prepared', 'running', 'needs_review'].includes(b.status)));
      const resume = openBrews.length && el('details', { class: 'flow-extra' }, el('summary', {}, '继续已有杯次'), openBrews.map(b =>
        button(`#${b.id} · ${beanName(b.bean_id)} · ${STATUSES[b.status]}`, () => {
          app.brew = b.id; navigate('studio');
        }, 'secondary')));
      const hasOrders = app.data.orders.some(o => !closedOrder(o));
      const ordersFirst = hasOrders && app.pickFrom !== 'inventory';
      const switcher = hasOrders && el('div', { class: 'actions' },
        button('待制作订单', () => { app.pickFrom = 'orders'; renderApp(); }, ordersFirst ? '' : 'secondary'),
        button('从库存选豆', () => { app.pickFrom = 'inventory'; renderApp(); }, ordersFirst ? 'secondary' : ''));
      const pastJob = app.aiJob && !['running', 'interrupted', 'failed'].includes(app.aiJob.status)
        ? el('details', { class: 'flow-extra' }, el('summary', {}, '上次拟方'), job) : job;
      content = el('div', { class: 'stack' }, switcher, ordersFirst ? renderOrders() : renderInventory(), resume || null, pastJob);
    }
    return el('div', { class: 'flow-page' }, el('header', { class: 'flow-heading' }, el('h1', {}, heading),
      !showingRecipeJob() && (bean || brew || app.draft) && button('返回选豆 / 接单', abandonSelection, 'quiet')), content);
  }
  function renderAISettings() {
    const settings = app.aiSettings;
    const draft = app.aiSettingsDraft;
    const pendingModel = draft?.[`${draft.primary}Model`];
    const pending = draft && settings && (draft.primary !== settings.primary ||
      (pendingModel && pendingModel !== settings[settings.primary]?.model));
    return el('div', { class: 'ai-entry' }, el('div', {}, el('strong', {}, `当前 AI：${primaryLabel(settings)}`),
      el('p', {}, settings ? settings.fallback ? `调用失败时使用 ${providerName(settings.fallback)}。` : '未启用备用模型。' : '请刷新工作台读取模型设置。'),
      pending && el('p', { class: 'inline-note' }, `另有未保存的选择 ${[providerName(draft.primary), pendingModel].filter(Boolean).join(' · ')}。在 AI 设置中保存后生效。`)),
      button('管理 AI', () => navigate('ai'), 'secondary'));
  }
  function renderAISettingsPage() {
    const body = el('div', { class: 'ai-settings-page' }, el('p', {}, '正在读取 AI 设置…'));
    const volume = input(app.data.rinse_ml, {type:'number', min:1, max:500, step:1, required:true});
    const rinseSettings = panel('预热与润纸', field('92 ℃ 润纸水量 / ml', volume),
      button('保存水量', event => run('rinse-setting', event.currentTarget, async () => {
        if (!volume.reportValidity()) return;
        const result = await write('rinse-setting', `${API}/settings/rinse`, {volume_ml:volume.valueAsNumber}, '保存润纸水量');
        app.data.rinse_ml = result.volume_ml;
        announce(`润纸水量已保存为 ${result.volume_ml} ml。`);
      }), 'secondary'));
    const root = el('div', {}, intro('SETTINGS', '全局设置', '在制作前选择是否润纸。AI 配置用于拟方与推荐。'), rinseSettings, app.data.database_label?.includes('临时') && el('p', { class: 'inline-note ai-preview-note' }, '你正在使用临时预览。这里保存的模型选择与密钥只属于预览环境，正式工作台需单独配置。'), body);
    async function load() {
      try {
        const settings = await api(`${API}/ai/settings`);
        if (!body.isConnected) return;
        ++aiSettingsRead;
        app.aiSettings = settings;
        const deepseekSupported = !!settings.deepseek;
        const providers = [{ value: 'codex', label: 'Codex' }, ...(deepseekSupported ? [{ value: 'deepseek', label: 'DeepSeek' }] : [])];
        const primary = select(providers, providers.some(p => p.value === settings.primary) ? settings.primary : 'codex');
        const fallback = select([{ value: '', label: '不使用备用' }, ...providers], providers.some(p => p.value === settings.fallback) ? settings.fallback : '');
        let previousPrimary = primary.value;
        primary.addEventListener('change', () => {
          if (fallback.value === primary.value) fallback.value = previousPrimary;
          previousPrimary = primary.value;
          rememberDraft();
        });
        primary.setAttribute('aria-label', '优先使用');
        fallback.setAttribute('aria-label', '调用失败时使用');
        const codexModel = input(settings.codex.model, { 'aria-label': 'Codex 模型' });
        const models = el('datalist', {id:'codex-model-choices'}, ['gpt-6.1-terra','gpt-6.2-sol','gpt-6.2-astra'].map(value => el('option', {value})));
        codexModel.setAttribute('list', models.id);
        const speed = select([{value:'priority',label:'Fast（优先处理）'},{value:'default',label:'标准'}], settings.codex.service_tier || 'default');
        const reasoning = select(['low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(value => ({ value, label: value })), settings.codex.reasoning_effort);
        if (!reasoning.value) { reasoning.append(el('option', { value: settings.codex.reasoning_effort }, settings.codex.reasoning_effort)); reasoning.value = settings.codex.reasoning_effort; }
        const codexTimeout = number(settings.codex.timeout_seconds, { min: '1', step: '1' });
        const deepseekModel = input(settings.deepseek?.model || '', { 'aria-label': 'DeepSeek 模型' });
        const deepseekURL = input(settings.deepseek?.base_url || '', { placeholder: 'https://api.deepseek.com' });
        const deepseekKeyEnv = input(settings.deepseek?.api_key_env || '', { placeholder: 'DEEPSEEK_API_KEY' });
        const deepseekTimeout = number(settings.deepseek?.timeout_seconds, { min: '1', step: '1' });
        const deepseekTokens = number(settings.deepseek?.max_tokens, { min: '1', max: '393216', step: '1' });
        const key = input('', { type: 'password', autocomplete: 'new-password', placeholder: '粘贴你的 DeepSeek API Key', 'aria-label': 'DeepSeek API Key' });
        const codexStatus = el('div', { class: 'ai-provider-status', role: 'status' }, '尚未检查登录状态');
        const deepseekStatus = el('div', { class: 'ai-provider-status', role: 'status' }, '尚未检查配置状态');
        const modelChoices = el('div', { class: 'actions', role: 'status' });
        const listModels = button('查询账号可用模型', event => run('deepseek-models', event.currentTarget, async () => {
          if (deepseekURL.value.trim() !== savedValues.deepseekURL || deepseekKeyEnv.value.trim() !== savedValues.deepseekKeyEnv || key.value) {
            throw new Error('请先保存改动的服务地址或密钥，再查询这个账号。');
          }
          modelChoices.textContent = '正在向 DeepSeek 查询…';
          const { models } = await api(`${API}/ai/deepseek/models`, {});
          modelChoices.replaceChildren(el('span', { class: 'small' }, models.includes(deepseekModel.value.trim())
            ? '当前型号在账号列表中。' : '当前型号未列出，可选择以下型号。'), ...models.map(model =>
            button(model, () => { deepseekModel.value = model; rememberDraft(); }, 'quiet')));
        }, error => { modelChoices.textContent = error.message; }), 'secondary', true);
        const keyMessage = el('p', { class: 'inline-note', role: 'status' });
        const saveMessage = el('p', { class: 'inline-note', role: 'status' });
        const summary = el('div', { class: 'ai-current-summary', role: 'status' });
        let status = null;
        let keyBusy = false;
        const draftControls = { primary, fallback, codexModel, reasoning, speed, codexTimeout, deepseekModel, deepseekURL, deepseekKeyEnv, deepseekTimeout, deepseekTokens };
        let savedValues = Object.fromEntries(Object.entries(draftControls).map(([name, control]) => [name, control.value]));
        const unsaved = el('p', { class: 'inline-note', role: 'status', hidden: true });
        const discard = button('放弃未保存修改', () => {
          for (const [name, control] of Object.entries(draftControls)) control.value = savedValues[name];
          previousPrimary = primary.value;
          rememberDraft();
        }, 'quiet');
        function rememberDraft() {
          const values = Object.fromEntries(Object.entries(draftControls).map(([name, control]) => [name, control.value]));
          app.aiSettingsDraft = JSON.stringify(values) === JSON.stringify(savedValues) ? null : values;
          unsaved.hidden = discard.hidden = !app.aiSettingsDraft;
          unsaved.textContent = app.aiSettingsDraft ? '有未保存的模型设置。切换页面后仍会保留；点击保存后才生效。' : '';
        }
        for (const [name, control] of Object.entries(draftControls)) {
          if (app.aiSettingsDraft && Object.hasOwn(app.aiSettingsDraft, name)) control.value = app.aiSettingsDraft[name];
          control.addEventListener('input', rememberDraft);
          control.addEventListener('change', rememberDraft);
        }
        previousPrimary = primary.value;
        rememberDraft();
        function showSummary(saved) {
          summary.replaceChildren(el('span', { class: 'eyebrow' }, '当前已保存'), el('strong', {}, `主用 ${primaryLabel(saved)}${saved.fallback ? ` → 备用 ${providerName(saved.fallback)}` : ' · 不使用备用模型'}`), el('span', { class: 'small muted' }, '更换模型不会改动已有配方；新设置用于下一次推荐或拟方。'));
        }
        function showDeepseek(value) {
          const configured = value?.configured === true;
          listModels.disabled = !configured;
          modelChoices.replaceChildren();
          deepseekStatus.replaceChildren(pill(configured ? '已配置密钥' : value?.state === 'error' ? '配置需处理' : '尚未配置密钥', configured ? 'green' : 'warn'), el('p', {}, value?.message || '请先保存 API Key。'), ...(configured ? [el('p', { class: 'small muted' }, '已配置不等于调用成功；实际生成时仍会检查响应。')] : []));
          removeKey.disabled = !value?.saved_key || keyBusy;
        }
        async function checkStatus() {
          check.disabled = true;
          check.textContent = '正在检查…';
          try {
            status = await api(`${API}/ai/status`);
            app.aiStatus = status;
            const value = status.providers.codex;
            const ready = value.installed && value.logged_in === true;
            codexStatus.replaceChildren(pill(ready ? '已安装 · 已登录' : value.state === 'missing' ? '尚未安装' : value.logged_in === false ? '需要登录' : '状态待确认', ready ? 'green' : 'warn'), el('p', {}, value.message));
            showDeepseek(status.providers.deepseek);
            saveKey.disabled = !deepseekSupported || keyBusy;
          } catch (error) {
            status = null;
            codexStatus.replaceChildren(pill('状态暂不可读', 'warn'), el('p', {}, error.message));
            deepseekStatus.replaceChildren(pill('密钥管理尚未加载', 'warn'), el('p', {}, '当前服务未提供此功能；请使用加载新版后端的预览。'));
            saveKey.disabled = removeKey.disabled = true;
          } finally { check.disabled = false; check.textContent = '检查配置状态'; }
        }
        const check = button('检查配置状态', () => checkStatus(), 'secondary');
        const saveKey = button('保存 API Key', event => run('deepseek-key', event.currentTarget, async () => {
          if (!key.value.trim()) throw new Error('请粘贴 API Key，再保存。');
          keyBusy = true; removeKey.disabled = true;
          try {
            const result = await api(`${API}/ai/credentials/deepseek`, { api_key: key.value.trim() });
            key.value = '';
            showDeepseek(result);
            keyMessage.textContent = '密钥已保存到本机。保存密钥不会发起模型调用。';
            keyMessage.className = 'inline-note';
          } finally { keyBusy = false; if (status) await checkStatus(); }
        }, error => { keyMessage.textContent = error.message; keyMessage.className = 'dialog-error'; }), 'secondary', true);
        const removeKey = button('移除已保存的密钥', () => {
          const view = openDialog('移除本机保存的 DeepSeek 密钥？', el('p', {}, '这会删除通过本页保存的密钥。若服务另有环境变量密钥，删除后仍会明确显示该来源。已有配方不受影响。'));
          view.dialog.append(button('确认移除', event => run('deepseek-key', event.currentTarget, async () => {
            keyBusy = true; saveKey.disabled = true;
            try {
              const result = await api(`${API}/ai/credentials/deepseek`, { remove: true });
              key.value = ''; showDeepseek(result); view.dialog.close();
              keyMessage.textContent = result.configured ? '页面保存的密钥已移除，目前仍使用服务环境中的密钥。' : '页面保存的密钥已移除。';
              keyMessage.className = 'inline-note';
            } finally { keyBusy = false; await checkStatus(); }
          }, view.error), 'danger'));
        }, 'quiet', true);
        function positive(control, label) {
          const value = numeric(control, label);
          if (!Number.isInteger(value) || value <= 0) throw new Error(`${label}请填写正整数。`);
          return value;
        }
        const save = button('保存模型选择', event => run('ai-settings', event.currentTarget, async () => {
          if (fallback.value === primary.value) throw new Error('主用与备用不能是同一个模型服务。');
          const request = { ...settings, primary: primary.value, fallback: fallback.value || null, codex: { model: codexModel.value.trim(), reasoning_effort: reasoning.value, service_tier: speed.value, timeout_seconds: positive(codexTimeout, 'Codex 等待时间') } };
          if (deepseekSupported) request.deepseek = { model: deepseekModel.value.trim(), base_url: deepseekURL.value.trim(), api_key_env: deepseekKeyEnv.value.trim(), timeout_seconds: positive(deepseekTimeout, 'DeepSeek 等待时间'), max_tokens: positive(deepseekTokens, 'DeepSeek 输出上限') };
          app.aiSettings = await api(`${API}/ai/settings`, request);
          ++aiSettingsRead;
          try { localStorage.setItem(aiSettingsSignal, crypto.randomUUID()); } catch (_) {}
          savedValues = Object.fromEntries(Object.entries(draftControls).map(([name, control]) => [name, control.value]));
          rememberDraft();
          showSummary(app.aiSettings);
          saveMessage.className = 'inline-note';
          await checkStatus();
          const current = app.aiSettings;
          if (!status) saveMessage.textContent = '模型选择已保存，但配置状态尚未确认，请重新检查。';
          else if (current.primary === 'codex' && status.providers.codex.logged_in !== true) saveMessage.textContent = '模型选择已保存；使用 Codex 前仍需完成安装或登录，请查看上方状态。';
          else if ([current.primary, current.fallback].includes('deepseek') && !status.providers.deepseek.configured) {
            saveMessage.replaceChildren(document.createTextNode(current.primary === 'deepseek' ? '模型选择已保存；使用 DeepSeek 前还需要保存 API Key。' : '模型选择已保存；Codex 环境检查通过，DeepSeek 备用仍需配置 API Key。'), button('补充 DeepSeek 密钥', () => { key.scrollIntoView({ behavior: 'smooth', block: 'center' }); key.focus(); }, 'quiet'));
          } else saveMessage.textContent = '模型选择已保存，环境检查通过。可回到制作台提交拟方，实际结果以生成回执为准。';
        }, error => { saveMessage.textContent = error.message; saveMessage.className = 'dialog-error'; }));
        const codexCard = el('section', { class: 'panel ai-provider-card' }, el('div', { class: 'section-title' }, el('h2', {}, 'Codex'), pill('复用本机登录')), codexStatus, el('p', {}, '复用这台 Mac 的 Codex 登录，无需在这里填写 OpenAI 密钥。'), field('使用模型', codexModel), models, el('div', {class:'two-fields'}, field('Codex 推理强度', reasoning), field('Codex 速度', speed)), el('details', {}, el('summary', {}, '未登录时怎么办'), el('p', {}, '在这台 Mac 的终端运行 codex login，完成登录后回这里重新检查。这里不会读取或展示登录凭据。')));
        const deepseekCard = el('section', { class: 'panel ai-provider-card' },
          el('div', { class: 'section-title' }, el('h2', {}, 'DeepSeek'), pill('API 接入')), deepseekStatus,
          deepseekSupported ? [field('使用模型', deepseekModel), app.data.capabilities?.ai_recipe?.deepseek_model_list && [listModels, modelChoices],
            field('API Key', key, '保存后不再回显。只存本机私有文件，不进入库存、配方或日志。'),
            el('div', { class: 'actions' }, saveKey, removeKey), keyMessage] : el('p', {}, '此服务尚未加载 DeepSeek 接入。'));
        const advanced = el('details', { class: 'panel ai-advanced' }, el('summary', {}, '高级设置 · 通常无需修改'), el('div', { class: 'two-fields section-gap' }, field('Codex 最长等待 / 秒', codexTimeout)), deepseekSupported && [field('DeepSeek API 地址', deepseekURL), field('已有环境变量名（可选接入方式）', deepseekKeyEnv, '使用页面保存的密钥时，无需修改此项。'), el('div', { class: 'two-fields' }, field('DeepSeek 最长等待 / 秒', deepseekTimeout), field('DeepSeek 输出上限', deepseekTokens))]);
        body.replaceChildren(summary, el('section', { class: 'panel' }, el('div', { class: 'section-title' }, el('h2', {}, '1. 选择日常使用的 AI'), check), el('p', { class: 'inline-note' }, '检查只核对本机安装、登录和密钥配置，不发起付费生成，也不代表配方已验证。'), el('div', { class: 'two-fields section-gap' }, field('优先使用', primary), field('调用失败时使用', fallback, '主用和备用互换时会自动对调。')), unsaved, el('div', { class: 'actions' }, save, discard), saveMessage, settings.fallback === 'ollama' && el('p', { class: 'inline-note' }, '当前服务仍保存旧的 Ollama 备用。保存本页后会改用你在上方选择的服务。')), el('div', { class: 'ai-provider-grid' }, codexCard, deepseekCard), advanced, el('section', { class: 'panel ai-next-steps' }, el('h2', {}, '2. 回到咖啡流程使用'), el('p', {}, '选豆和品饮人 → 说出本杯目标 → AI 拟方 → 你审核并保存。只有你明确开始后，才执行冲煮。'), el('div', { class: 'actions' }, button('去选豆拟方', () => navigate('studio')), button('去看个人推荐', () => navigate('menu'), 'secondary'))));
        body.insertBefore(usageHistory(), advanced);
        showSummary(settings);
        checkStatus();
      } catch (error) {
        body.replaceChildren(panel('暂时无法读取 AI 设置', el('p', { class: 'dialog-error' }, error.message), button('重新读取', load, 'secondary')));
      }
    }
    load();
    return root;
  }
  async function submitRecipe(revision) {
    if (anyAIRunning()) throw new Error('已有 AI 任务进行中，请等待当前结果。');
    const request = { bean_id: Number(app.bean), mode: app.mode, goal: app.goal, dose_grams: app.dose, ...expectedAI() };
    const person = planningPerson();
    if (person) request.person_id = person;
    const base = app.draft?.id || app.draft?.parent_id;
    if (base) request.base_recipe_id = base;
    if (revision) request.revision = revision;
    const context = aiContext(request);
    app.submittingAt = Date.now();
    updateRecipeProgress();
    try {
      const job = await write('ai-suggest', `${API}/ai/suggest`, request, `AI 拟方：${beanName(app.bean)}`);
      acceptAIJob(job, context);
    } finally { app.submittingAt = null; updateRecipeProgress(); }
  }
  function doseSelector(onChange) {
    const options = Array.from({ length: 14 }, (_, i) => ({ value: i + 5, label: `${i + 5} g` }));
    return select(options, app.dose, event => {
      app.dose = Number(event.target.value);
      if (onChange) onChange();
    });
  }
  function renderPlanning(bean) {
    const modes = select(Object.entries(MODES).map(([value, label]) => ({ value, label })), app.mode, event => { app.mode = event.target.value; app.draft = null; app.draftText = ''; app.dirty = false; renderApp(); });
    const selectedOrder = getOrder(app.order);
    modes.disabled = !!selectedOrder;
    const person = select([{ value: '', label: '未指定品饮者' }, ...app.data.people.map(item => ({ value: item.id, label: item.name }))], planningPerson() || '', event => { app.studioPerson = event.target.value; });
    person.disabled = !!selectedOrder;
    const goal = textarea(app.goal, { placeholder: '写下这杯想达到的口味、想调整的问题，或需要参考的历史反馈。', oninput: event => { app.goal = event.target.value; markDraftDirty(); } });
    const saved = newest(app.data.recipes.filter(recipe => sameId(recipe.bean_id, bean.id) && recipe.mode === app.mode && recipe.payload.doseGrams === app.dose));
    const aiButton = button(aiButtonLabel(), event => run('ai-submit', event.currentTarget, () => submitRecipe()), '', !app.aiSettings || anyAIRunning() || app.busy.has('ai-submit'));
    aiButton.id = 'ai-suggest';
    const ruleButton = button('规则草案（非 AI）', event => run('suggest', event.currentTarget, async () => {
      const request = { bean_id: bean.id, mode: app.mode, goal: app.goal, dose_grams: app.dose };
      if (app.draft?.id) request.base_recipe_id = app.draft.id;
      const suggestion = await api(`${API}/suggest`, request);
      if (!sameId(app.bean, request.bean_id) || app.mode !== request.mode || app.goal !== request.goal || app.dose !== request.dose_grams) { announce('选豆、粉量、模式或目标已改变，上一个规则草案未应用。'); return; }
      loadDraft({ ...suggestion, bean_id: request.bean_id, mode: request.mode, goal: request.goal, parent_id: request.base_recipe_id || null, id: null });
      renderApp();
      announce('本地规则草案已生成，未调用 AI。请审核参数、理由与待验证项。');
    }), 'secondary');
    const versions = select(saved.map(recipe => ({ value: recipe.id, label: `v${recipe.id} · ${recipe.title || MODES[recipe.mode]}` })), '', event => {
      if (event.target.value) { loadDraft(getRecipe(event.target.value)); renderApp(); }
    }, '选择一个版本…');
    return panel(bean.name, el('p', { class: 'bean-meta' }, [bean.roaster, bean.country, bean.process, bean.roast_level].filter(Boolean).join(' · ')),
      app.order && el('p', { class: 'small' }, `订单 #${app.order}`),
      el('div', { class: 'three-fields' }, field('制作方式', modes), field('本杯粉量', doseSelector(renderApp)), field('品饮者', person)), field('这杯想喝到什么', goal), aiButton,
      el('details', { class: 'flow-extra' }, el('summary', {}, '历史配方与规则草案'), saved.length > 0 && field('使用已保存的配方', versions), ruleButton));
  }
  function listContent(value) {
    const items = Array.isArray(value) ? value : value ? [value] : [];
    return items.length ? el('ul', { class: 'evidence-list' }, items.map(item => el('li', {}, typeof item === 'object' ? text(item) : item))) : el('p', { class: 'muted small' }, '尚未记录。');
  }
  function waterSummary(payload) {
    const through = payload.recipe.grandWater;
    if (!payload.bypassMl) return `${through} ml`;
    return `过粉 ${through} ml ＋ 旁通 ${payload.bypassMl} ml（${payload.bypassTempC} ℃），合计 ${through + payload.bypassMl} ml`;
  }
  function recipeDecisions(draft, payload, sourceItems) {
    const r = payload.recipe || {}, pours = r.pours || [];
    const notes = Array.isArray(draft.rationale) ? draft.rationale : [];
    const structured = notes.map(line => String(line).match(/^依据[：:]\s*(.+?)\s*[｜|]\s*选择[：:]\s*(.+?)\s*[｜|]\s*预期[：:]\s*(.+)$/)).filter(Boolean).map(match => match.slice(1));
    const names = [...new Set((draft.evidence || []).filter(e => e?.excerpt !== draft.provenance && !e?.title?.startsWith('生成方式')).map(e => String(e.title || e.source || '').split(' · ').shift()).filter(Boolean))];
    const sourceBox = el('details', { class: 'map-sources' }, el('summary', {}, '引用资料', el('span', {}, names.slice(0, 3).join('、') || '查看原文')),
      sourceItems.length ? el('ul', { class: 'evidence-list' }, sourceItems) : el('p', {}, '这份草稿没有附引用。'));
    const ratio = payload.doseGrams && r.grandWater ? Number((r.grandWater / payload.doseGrams).toFixed(2)) : null;
    const choices = [
      [payload.bypassMl ? '过粉比例与旁通' : '粉水比', ratio ? `1:${ratio} · ${payload.doseGrams} g / ${waterSummary(payload)}` : '未记录', /粉水比|1[:：]\d|粉量|总水|水总量|旁通|bypass/i],
      ['研磨', [r.grinderSize != null && `${r.grinderSize} 档`, r.rpm != null && `${r.rpm} RPM`].filter(Boolean).join(' · '), /研磨|转速|粗磨|细磨/],
      ['分段水温', pours.length ? `${pours.map(p => p.temperature).join(' → ')} ℃` : '未记录', /温度|水温|℃|降温/],
      ['注水节奏', pours.length ? `${pours.map(p => p.volume).join(' / ')} ml` : '未记录', /骨架|闷蒸|闷煮|流速|注水|驻留|分段/],
    ];
    const cards = choices.map(([label, value, matches]) => {
      const related = notes.filter(line => matches.test(line));
      const excerpt = !structured.length && related.flatMap(line => line.split(/[。；]/)).find(part => matches.test(part) && part.trim().length >= 6);
      const title = [el('span', { class: 'map-label' }, label), el('strong', {}, value),
        excerpt && el('span', { class: 'parameter-excerpt' }, excerpt)];
      return related.length ? el('details', { class: 'parameter-node' }, el('summary', {}, title), listContent(related))
        : el('div', { class: 'parameter-node' }, title);
    });
    const node = (label, content) => el('div', { class: 'decision-node' }, el('span', { class: 'map-label' }, label), el('span', {}, content));
    const decisionRow = parts => el('div', { class: 'decision-row' }, node('依据', parts[0]),
      el('span', { class: 'flow-arrow', 'aria-hidden': 'true' }, '→'), node('参数选择', parts[1]),
      el('span', { class: 'flow-arrow', 'aria-hidden': 'true' }, '→'), node('预期杯感', parts[2]));
    return el('section', { class: 'decision-map', 'aria-label': '配方决策图' }, el('h3', {}, '配方决策图'),
      el('div', { class: 'map-inputs' }, node('本杯目标', draft.goal || '原方案未单列目标'), sourceBox),
      el('div', { class: 'map-edge', 'aria-hidden': 'true' }, '↓'),
      el('div', { class: 'map-parameters' }, cards),
      structured.length > 0 && el('div', { class: 'decision-rows' }, structured.slice(0, 2).map(decisionRow),
        structured.length > 2 && el('details', {}, el('summary', {}, `还有 ${structured.length - 2} 条参数决策`), structured.slice(2).map(decisionRow))),
      el('details', { class: 'map-footnote' }, el('summary', {}, `全部选参理由（${notes.length}）`), listContent(notes)),
      el('details', { class: 'map-footnote' }, el('summary', {}, '喝到什么需要再调整'), listContent(draft.risks)));
  }
  function recipeDiscussion(draft) {
    const feedback = textarea(draft.reviewInput || '', { id: 'revision-note', maxLength: 2000, placeholder: '例如：希望更浓一点，保留研磨和水温，只调水量。',
      oninput: event => { draft.reviewInput = event.target.value; } });
    const error = el('p', { class: 'dialog-error', role: 'alert', hidden: true });
    const revise = button('按我的意见重新拟方', event => run('ai-submit', event.currentTarget, async () => {
      const note = feedback.value.trim() || (app.dose !== draft.payload.doseGrams ? `本杯改用 ${app.dose} g 粉。` : '');
      if (!note) { feedback.focus(); throw new Error('先写下你希望调整的地方。'); }
      try { JSON.parse(app.draftText); } catch (_) { throw new Error('当前参数 JSON 不完整，请先修正后再拟方。'); }
      const revision = { note, payload_json: app.draftText };
      if (draft.jobId && draft.personId === planningPerson()) revision.prior_job_id = draft.jobId;
      error.hidden = true;
      await submitRecipe(revision);
    }, err => { error.textContent = err.message; error.hidden = false; }), 'secondary');
    revise.id = 'ai-revise';
    revise.disabled = !app.aiSettings || anyAIRunning() || app.busy.has('ai-submit');
    const before = draft.reviewBase;
    return el('section', { class: 'recipe-discussion' }, el('h3', {}, '和 AI 改这份配方'),
      draft.reviewNotes?.length > 0 && el('details', {}, el('summary', {}, `已提交的修改意见（${draft.reviewNotes.length}）`), listContent(draft.reviewNotes)),
      before && el('details', {}, el('summary', {}, '对照修改前后的参数'), compareRecipes(before.payload, draft.payload)),
      field('修订后粉量', doseSelector()), field('你希望怎么改？', feedback), revise, error);
  }
  function compareRecipes(before, after) {
    const changes = [];
    function compare(label, left, right) { if (left !== right) changes.push(`${label}　${left ?? '无'} → ${right ?? '无'}`); }
    compare('粉量（g）', before.doseGrams, after.doseGrams);
    for (const [key, label] of [['grandWater','过粉水量（ml）'],['grinderSize','研磨档位'],['rpm','转速（RPM）']]) compare(label, before.recipe[key], after.recipe[key]);
    compare('旁通水量（ml）', before.bypassMl ?? 0, after.bypassMl ?? 0);
    compare('旁通水温（℃）', before.bypassTempC || null, after.bypassTempC || null);
    const a = before.recipe.pours, b = after.recipe.pours;
    compare('注水段数', a.length, b.length);
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      for (const [key,label] of [['volume','水量（ml）'],['temperature','水温（℃）'],['flowRate','流速（ml/s）'],['pattern','轨迹'],['pausing','停顿（s）'],['vibBefore','注前振动'],['vibAfter','注后振动']]) {
        compare(`第 ${i+1} 段${label}`, a[i]?.[key], b[i]?.[key]);
      }
    }
    return changes.length ? listContent(changes) : el('p', {}, '两版设备参数相同。');
  }
  function pourTable(pours) {
    if (!pours.length) return el('p', { class: 'muted small' }, '这份配方没有分段注水记录。');
    const patterns = ['中心', '环绕', '螺旋'];
    const columns = ['分段', '水量', '水温', '注水流速', '轨迹', '停顿', '注前 / 注后振动'];
    const rows = pours.map((p, index) => [
      index + 1, `${p.volume} ml`, `${p.temperature} °C`, `${p.flowRate} ml/s`,
      patterns[p.pattern] || `模式 ${p.pattern}`, `${p.pausing} s`,
      `${p.vibBefore ? '是' : '否'} / ${p.vibAfter ? '是' : '否'}`,
    ]);
    return el('div', { class: 'table-wrap' }, el('table', {},
      el('thead', {}, el('tr', {}, columns.map(label => el('th', { scope: 'col' }, label)))),
      el('tbody', {}, rows.map(row => el('tr', {}, row.map(value => el('td', {}, value)))))));
  }

  function brewParameters(brew) {
    const recipe = getRecipe(brew.recipe_id);
    const payload = recipe?.payload;
    const settings = payload?.recipe;
    const section = el('section', { class: 'cup-parameters' }, el('h3', {}, '本杯冲煮参数'));
    function addValues(pairs) {
      const values = pairs.filter(([, value]) => value != null && value !== '');
      if (values.length) section.append(el('dl', {}, values.map(([label, value]) =>
        el('div', {}, el('dt', {}, label), el('dd', {}, value)))));
    }
    if (settings) {
      section.append(el('p', { class: 'inline-note' }, `配方设定 v${recipe.id} · ${MODES[brew.mode] || brew.mode}`));
      const ratio = Number((settings.grandWater / payload.doseGrams).toFixed(2));
      const machineGrind = brew.mode === 'xbloom' && settings.grindEnabled !== false;
      addValues([['粉量', `${payload.doseGrams} g`], ['注水量', waterSummary(payload)],
        [payload.bypassMl ? '过粉粉水比' : '粉水比', `1:${ratio}`],
        ['机磨', machineGrind ? `${settings.grinderSize} 档 · ${settings.rpm} RPM` : '免机磨']]);
      section.append(pourTable(settings.pours || []));
    } else {
      const t = brew.legacy_data?.technique || brew.legacy_data || {};
      addValues([['粉量', t.dose], ['粉水比', t.ratio], ['水温', t.water_temperature],
        ['磨豆机', t.grinder], ['研磨刻度', t.grind_size || t.used_grind], ['滤杯', t.dripper],
        ['闷蒸', t.bloom], ['注水手法', t.pour_method], ['用时', t.total_time], ['出杯量', t.yield]]);
      if (section.children.length === 1) section.append(el('p', { class: 'inline-note' }, '本杯未保存配方参数。'));
    }
    const observed = brew.observations || {};
    addValues([['实际耗豆', brew.consumption_g != null ? `${brew.consumption_g} g` : null],
      ['记录滤杯', observed.brewer], ['记录磨豆机', observed.grinder], ['记录研磨刻度', observed.grind_setting],
      ['屏显用时', observed.screen_seconds != null ? `${observed.screen_seconds} s` : null],
      ['实测液重', observed.beverage_g != null ? `${observed.beverage_g} g` : null]]);
    return section;
  }
  function renderRecipe() {
    const draft = app.draft;
    let payload;
    try { payload = JSON.parse(app.draftText); } catch (_) { payload = draft.payload || {}; }
    const recipe = payload.recipe || {};
    const title = input(draft.title || '', { placeholder: '为这个版本起个名字', oninput: event => { draft.title = event.target.value; markDirty(); } });
    const editor = textarea(app.draftText, { class: 'json-editor', spellcheck: false, 'aria-label': '完整配方 JSON 参数', oninput: event => { app.draftText = event.target.value; markDirty(); } });
    const dirtyNote = el('span', { id: 'draft-state', class: 'pill' }, draft.id && !app.dirty ? `已保存 v${draft.id}` : '草稿 · 待审核保存');
    const existingOrderBrew = app.order && app.data.brews.find(brew => sameId(brew.order_id, app.order));
    const createButton = button(existingOrderBrew ? `本订单已建立当杯 #${existingOrderBrew.id}` : '以此版本建立当杯', event => run('create-brew', event.currentTarget, async () => {
      if (!app.draft?.id || app.dirty) throw new Error('参数已有改动，请先保存为新配方版本。');
      const request = { bean_id: Number(app.bean), recipe_id: app.draft.id, mode: app.draft.mode };
      if (app.order) request.order_id = Number(app.order);
      const brew = await write('create-brew', `${API}/brews`, request, `为 ${beanName(app.bean)} 建立当杯`);
      app.data.brews = [brew, ...app.data.brews.filter(b => !sameId(b.id, brew.id))];
      const order = getOrder(brew.order_id);
      if (order) { order.status = 'prepared'; order.recipe_id = brew.recipe_id; }
      app.brew = brew.id;
      history.replaceState(null, '', `/studio?cup=${brew.id}`);
      renderApp();
      announce(`已建立当杯 #${brew.id}，尚未启动设备。`);
      $('brew-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }), 'secondary', !draft.id || app.dirty || !!existingOrderBrew);
    createButton.id = 'create-brew';
    createButton.hidden = !draft.id;
    function markDirty() { app.dirty = true; dirtyNote.textContent = '已修改 · 必须保存新版本'; createButton.disabled = true; $('save-recipe').hidden = false; }
    const evidence = Array.isArray(draft.evidence) ? draft.evidence : draft.evidence ? [draft.evidence] : [];
    const sourceItems = evidence.map(item => {
      if (!item || typeof item !== 'object') return el('li', {}, text(item));
      const source = item.source || item.source_id;
      const knownSource = typeof source === 'string' && /^[A-Za-z0-9_-]+$/.test(source);
      return el('li', {}, el('strong', {}, item.title || '参考资料'), el('p', {}, item.excerpt || text(item)), knownSource && el('a', { href: `${API}/sources/${encodeURIComponent(source)}`, target: '_blank', rel: 'noopener' }, '查看来源原文'));
    });
    const pours = Array.isArray(recipe.pours) ? recipe.pours : [];
    const save = button(draft.id ? '保存为新版本' : '审核后保存配方', event => run('save-recipe', event.currentTarget, async () => {
      try { JSON.parse(app.draftText); } catch (_) { throw new Error('参数 JSON 格式不正确，请检查括号、逗号和数字。'); }
      if (!draft.title?.trim()) throw new Error('请填写配方名称。');
      const request = { bean_id: Number(app.bean), title: draft.title.trim(), mode: draft.mode, goal: app.goal, payload_json: app.draftText, rationale: draft.rationale || [], evidence: draft.evidence || [], risks: draft.risks || [] };
      if (draft.id || draft.parent_id) request.parent_id = draft.id || draft.parent_id;
      const saved = await write('save-recipe', `${API}/recipes`, request, `保存配方：${request.title}`);
      app.data.recipes = [saved, ...app.data.recipes.filter(r => !sameId(r.id, saved.id))];
      loadDraft(saved);
      renderApp();
      announce(`配方 v${saved.id} 已保存。建立当杯后，才会出现明确的开始操作。`);
    }));
    save.id = 'save-recipe';
    save.hidden = Boolean(draft.id) && !app.dirty;
    const review = el('section', { class: 'panel', id: 'recipe-review' }, el('div', { class: 'recipe-heading' }, el('div', {}, el('h2', {}, '审核这一份参数'), el('p', { class: 'inline-note' }, `${MODES[draft.mode] || '待选模式'}${draft.parent_id ? ` · 基于 v${draft.parent_id} 修订` : ''}`)), el('div', { class: 'actions' }, dirtyNote, button('提出修改', () => { const note = $('revision-note'); if (note) { note.closest('details').open = true; note.focus(); } }, 'secondary'))), recipeDecisions(draft, payload, sourceItems), el('details', { class: 'flow-extra' }, el('summary', {}, '和 AI 修改配方'), recipeDiscussion(draft)), el('details', { class: 'flow-extra' }, el('summary', {}, draft.title || '配方名称'), field('配方名称', title)), pourTable(pours), el('details', {}, el('summary', {}, '修改完整参数'), el('p', { class: 'inline-note' }, '修改 JSON 后保存为新版本；历史版本保持原样。上方分段预览在保存后更新。'), editor), el('div', { class: 'actions' }, save, createButton, draft.id && el('a', { href: `${API}/recipes/${draft.id}/download`, class: 'text-link' }, '下载配方')), draft.id && el('p', { class: 'inline-note' }, `版本校验 ${draft.sha256 || '未返回校验值'}`));
    const usage = draft.jobId && app.aiJob?.id === draft.jobId && callUsage(app.aiJob);
    if (usage) review.firstElementChild.after(usage);
    return review;
  }
  function renderBrewStatus(brew) {
    const recipe = getRecipe(brew.recipe_id);
    const canEdit = brew.recipe_id && !(brew.status === 'prepared' && brew.rinse) && brew.status !== 'cancelled' && brew.capture_state !== 'running';
    const edit = canEdit && button('修改冲煮结果', () => {
      const form = $('brew-result-form');
      if (!form) return;
      form.open = true;
      form.scrollIntoView({ block: 'start' });
      form.querySelector('select').focus({ preventScroll: true });
    }, 'quiet');
    const scope = `record:${brew.id}`;
    const confirm = canEdit && brew.status === 'needs_review' && !brew.retry && button(brew.consumption_g == null ? `确认出杯并扣 ${recipe.payload.doseGrams} g` : '确认已出杯', event => run(scope, event.currentTarget, async () => {
      const result = await write(scope, `${API}/brews/${brew.id}/record`, { status: 'completed', consumption_g: brew.consumption_g ?? recipe.payload.doseGrams }, `确认第 ${brew.id} 杯已出杯`);
      await refresh(false);
      announce(`第 ${result.id} 杯已确认完成，本杯已扣 ${result.consumption_g} g。`);
    }), 'primary', app.busy.has(scope));
    const facts = el('details', { class: 'flow-extra' }, el('summary', {}, '配方版本与执行日志'));
    const status = el('div', { class: 'brew-status' }, el('div', { class: 'brew-status-title' }, el('strong', {}, `当杯 #${brew.id}`), statusPill(brew, 'brew'), confirm, edit), el('p', {}, `${beanName(brew.bean_id)} · ${MODES[brew.mode] || '历史记录'}${brew.recipe_id ? ` · 配方 v${brew.recipe_id}` : ''}${brew.order_id ? ` · 订单 #${brew.order_id}` : ''}`));
    if (brew.mode === 'xbloom' && brew.capture_state && !brew.capture_error) {
      facts.append(el('p', { class: 'tiny' }, '蓝牙采集 · 末滴时间未确认'));
    } else if (brew.mode !== 'xbloom') {
      status.append(el('p', {}, '本路线由人实际制作，网页不派发设备命令。'));
    }
    if (brew.rinse) facts.append(el('p', {}, `预热润纸 · 92 ℃ / ${brew.rinse.volume_ml} ml · ${{running:'执行中', done:'收到停止信号', unconfirmed:'停止信号未确认'}[brew.rinse.state]}`));
    if (recipe?.sha256) facts.append(el('p', { class: 'tiny' }, `审核版本 ${recipe.sha256.slice(0, 16)}…`));
    const alert = brewAlert(brew);
    if (alert && brew.capture_state !== 'running') status.append(el('div', { class: 'pending-box', role: 'alert' },
      waterHeading(brew) && el('strong', {}, waterHeading(brew)), el('p', {}, alert)));
    if (brew.retry && brew.status === 'needs_review' && app.data.capabilities?.bluetooth_start) {
      if (app.view === 'studio') {
        const key = `start:${brew.id}`;
        status.append(button(waterHeading(brew) ? '已检查水箱，按原配方重试' : '已检查机器，按原配方重新开始', event => run(key, event.currentTarget, async () => {
          const { token, reviewed_sha256, address, brewer } = brew.retry;
          const endpoint = `${API}/brews/${brew.id}/start`;
          const result = await write(key, endpoint, { retry_of: token, reviewed_sha256, address, brewer, confirm_start: true }, `重新开始第 ${brew.id} 杯`);
          adoptResult(endpoint, result);
        }), 'danger', app.busy.has(key) || Boolean(app.pending[key])));
      } else {
        status.append(el('a', { class: 'button secondary', href: `/studio?cup=${brew.id}` }, '去制作台重试'));
      }
    }
    if (brew.capture_error) {
      const detail = brew.capture_error === "No module named 'bleak'" ? '蓝牙依赖加载失败，本次网页执行未连接机器、未发送启动指令。' : '';
      (alert ? facts : status).append(el('p', { class: 'tiny' }, `网页执行尝试 · ${brew.capture_error}。${detail}`));
    }
    const journal = safeReport(brew.journal, 'journal');
    if (journal) facts.append(el('p', {}, el('a', { href: journal, target: '_blank', rel: 'noopener', class: 'text-link' }, '查看原始执行日志')));
    (brew.previous_journals || []).forEach((href, index) => {
      facts.append(el('p', {}, el('a', { href, target: '_blank', rel: 'noopener', class: 'text-link' }, `第 ${index + 1} 次尝试的日志`)));
    });
    const link = safeReport(brew.report);
    if (link && (brew.capture_state || ['completed', 'failed', 'unconfirmed'].includes(brew.status) || !brew.recipe_id)) status.append(el('p', {}, el('a', { href: link, target: '_blank', rel: 'noopener', class: 'text-link' }, brew.capture_error && journal ? '查看网页尝试报告' : '查看当杯过程报告')));
    if (facts.childElementCount > 1) status.append(facts);
    return status;
  }
  function safeReport(value, kind = 'report') {
    if (typeof value !== 'string') return null;
    try { const url = new URL(value, location.origin); return url.origin === location.origin && new RegExp(`^/api/product/brews/\\d+/${kind}$`).test(url.pathname) && !url.search && !url.hash ? url.href : null; }
    catch (_) { return null; }
  }
  function updateBrewStatus() {
    for (const badge of document.querySelectorAll('[data-status-kind]')) {
      const kind = badge.dataset.statusKind;
      const item = kind === 'brew' ? getBrew(badge.dataset.itemId) : getOrder(badge.dataset.itemId);
      if (item && (badge.dataset.status !== (item.status || '') || badge.dataset.rinse !== (item.rinse?.state || ''))) badge.replaceWith(statusPill(item, kind));
    }
    const host = $('brew-live');
    const brew = app.data && getBrew(app.view === 'records' ? app.recordBrew : app.brew);
    if (host && brew) {
      const panel = $('brew-panel');
      if (panel.dataset.stage !== brewStage(brew)) {
        const next = renderBrew(brew.id, app.view === 'records');
        const preserve = brew.status === 'completed' ? ['.feedback-grid'] : ['.feedback-grid', '#brew-result-form'];
        for (const selector of preserve) {
          const previous = panel.querySelector(selector);
          const replacement = next.querySelector(selector);
          if (previous && replacement) replacement.replaceWith(previous);
        }
        const watching = panel.dataset.stage === '冲煮中' && panel.querySelector('.live-chart');
        panel.replaceWith(next);
        if (watching) {
          const replay = next.querySelector('.live-chart')?.closest('details');
          if (replay) replay.open = true;
        }
      }
      else {
        const phase = $('machine-phase');
        if (phase) {
          const alert = brewAlert(brew);
          phase.className = alert ? 'pending-box' : 'inline-note';
          phase.textContent = alert || brewPhases[brew.capture_phase] || brewPhases.registered;
        }
        const feedback = panel.querySelector('details#brew-feedback');
        if (feedback && brew.capture_phase === 'end_signal' && !feedback.dataset.offered) {
          feedback.open = true;
          feedback.dataset.offered = 'yes';
        }
        const expanded = host.querySelector('details')?.open;
        host.replaceChildren(renderBrewStatus(brew));
        if (expanded && host.querySelector('details')) host.querySelector('details').open = true;
      }
    }
    const start = $('start-brew');
    if (start && brew?.status !== 'prepared') start.disabled = true;
  }
  function brewStage(brew) {
    if (brew.capture_state === 'running' || ['starting', 'running'].includes(brew.status)) return '冲煮中';
    if (brew.status === 'prepared' && brew.rinse) {
      return {running:'正在预热润纸', done:'倒掉润纸水', unconfirmed:'核对润纸结果'}[brew.rinse.state];
    }
    if (brew.status === 'prepared') return brew.mode === 'xbloom' ? '准备冲煮' : '手动制作';
    if (brew.status === 'needs_review' && waterHeading(brew)) return waterHeading(brew);
    if (brew.status === 'needs_review') return '确认出杯';
    if (brew.status === 'cancelled') return '制作已取消';
    if (['failed', 'unconfirmed'].includes(brew.status)) return '核对冲煮结果';
    return '品饮反馈';
  }
  function renderBrew(brewId = app.brew, records = false) {
    const brew = getBrew(brewId);
    if (!brew) return null;
    const recipe = getRecipe(brew.recipe_id);
    const stage = brewStage(brew);
    const live = el('div', { id: 'brew-live' }, renderBrewStatus(brew));
    const children = [el('div', { class: 'section-title' }, el('h2', {}, stage),
      stage === '品饮反馈' && el('span', { class: 'small muted' }, `第 ${brew.id} 杯`),
      stage === '冲煮中' && button('同步状态', event => run('refresh-brew', event.currentTarget, pollBrew), 'quiet'))];
    if (stage !== '品饮反馈') children.push(live);
    if (brew.status === 'cancelled') {
      children.push(el('p', { class: 'inline-note' }, '本杯尚未开始的准备已取消，关联记录保留。此操作没有发送机器停止命令。'));
      return el('section', { class: 'panel', id: 'brew-panel', 'data-stage': stage }, children);
    }
    if (!records && brew.mode === 'xbloom' && brew.status === 'prepared') {
      const capability = app.data.capabilities?.bluetooth_start === true;
      const rinse = brew.rinse;
      const rinseMl = app.data.rinse_ml;
      const address = input(rinse?.address || app.data.capabilities?.default_address || '', { placeholder: '填写本次连接的机器地址', autocomplete: 'off' });
      const currentBrewer = app.pending[`start:${brew.id}`]?.payload?.brewer || brewerOverrides.get(brew.id) || brew.rinse?.brewer || brew.observations?.brewer || defaultBrewer;
      const brewer = input(currentBrewer, { placeholder: defaultBrewer, maxLength: 200 });
      brewer.setAttribute('list', 'brew-drippers');
      const brewerSummary = el('summary', {}, `本杯滤杯 · ${currentBrewer}`);
      brewer.oninput = () => {
        const chosen = brewer.value.trim() || defaultBrewer;
        brewerOverrides.set(brew.id, chosen);
        brewerSummary.textContent = `本杯滤杯 · ${chosen}`;
      };
      const brewerDetails = el('details', { class: 'flow-extra' }, brewerSummary, field('更换本杯滤杯', brewer),
        el('datalist', { id: 'brew-drippers' }, [defaultBrewer, 'V60', 'Origami'].map(value => el('option', { value }))));
      const confirm = input('', { type: 'checkbox' });
      const optIn = input('', { type:'checkbox' });
      const settings = recipe?.payload?.recipe;
      if (settings) children.push(el('p', { class:'brew-spec' },
        `${recipe.payload.doseGrams} g · ${waterSummary(recipe.payload)} · 研磨 ${settings.grinderSize} · ${settings.rpm} RPM`));
      if (rinse?.state === 'running') {
        children.push(el('p', {class:'pending-box', role:'status'}, `正在执行 92 ℃、${rinse.volume_ml} ml 润纸。请保持接水杯就位，结束后再倒水。`));
      } else {
        if (!rinse) children.push(el('details', {class:'flow-extra', open:!address.value}, el('summary', {}, '连接的机器'), field('蓝牙地址', address)));
        children.push(brewerDetails);
        if (rinse) {
          const uncertain = rinse.state === 'unconfirmed';
          children.push(el('p', {class:'pending-box', role:'status'}, uncertain
            ? `润纸结束信号未确认。请在机器旁核对，需要时手动润纸。确认出水已停止后，倒掉润纸水并放回空杯。 ${rinse.error || ''}`
            : `92 ℃、${rinse.volume_ml} ml 润纸程序已结束。请倒掉润纸水，把空杯放回秤上。`));
        } else {
          children.push(el('label', {class:'confirmation'}, optIn, el('span', {}, `先预热滤杯并打湿滤纸 · 92 ℃ / ${rinseMl} ml`)),
            el('label', {class:'confirmation'}, confirm, el('span', {}, '我已核对本杯配方，豆子、滤杯、滤纸、接水杯与水均已就位。')));
        }
        const start = button(rinse ? '已停止出水、倒水并放回空杯，继续研磨冲煮' : '已准备，按此配方开始', event => {
          const rinsing = !rinse && optIn.checked;
          const phase = rinsing ? 'rinse' : 'start';
          const key = `${phase}:${brew.id}`;
          return run(key, event.currentTarget, async () => {
            if (!rinse && !confirm.checked) throw new Error('请先核对配方与实物准备。');
            if (!address.value.trim() || !recipe?.sha256) throw new Error('请核对机器地址与已保存配方。');
            const endpoint = `${API}/brews/${brew.id}/${phase}`;
            const payload = {reviewed_sha256:recipe.sha256, address:address.value.trim(), brewer:brewer.value.trim() || defaultBrewer};
            if (rinsing) Object.assign(payload, {volume_ml:rinseMl, confirm_rinse:true});
            else Object.assign(payload, {confirm_start:true}, rinse && {confirm_rinse_discarded:true});
            try {
              const result = await write(key, endpoint, payload, rinsing ? `第 ${brew.id} 杯预热润纸` : `开始当杯 #${brew.id}`);
              adoptResult(endpoint, result);
            } catch (error) {
              if (!rinsing && sameId(brewNotice?.id, brew.id)) {
                brewNotice.error = app.pending[key] ? '启动回执未收到，请核对当杯状态。' : error.message;
                updateBrewProgress();
              }
              throw error;
            }
          });
        }, 'danger', !capability || Boolean(app.pending[`start:${brew.id}`] || app.pending[`rinse:${brew.id}`]));
        start.id = 'start-brew';
        optIn.onchange = () => { start.textContent = optIn.checked ? '先放水润纸' : '已准备，按此配方开始'; };
        children.push(start);
        if (rinse) children.push(button('结束本次准备，不研磨', event => run(`end-prep:${brew.id}`, event.currentTarget, async () => {
          await write(`end-prep:${brew.id}`, `${API}/brews/${brew.id}/record`, {status:'failed'}, '结束本次准备');
          await refresh();
        }), 'quiet'));
        if (!capability) children.push(el('p', {class:'inline-note'}, app.data.capabilities?.bluetooth_unavailable_reason || '当前服务未开放蓝牙开始能力。'));
      }
    }
    if (records && brew.status === 'prepared' && brew.mode === 'xbloom') children.push(button('去制作台准备', () => {
      app.brew = brew.id; app.bean = brew.bean_id; app.order = brew.order_id || ''; navigate('studio');
    }));
    if (stage === '冲煮中') {
      const alert = brewAlert(brew);
      children.push(el('p', { class: alert ? 'pending-box' : 'inline-note', id: 'machine-phase', role: 'status' }, alert || brewPhases[brew.capture_phase] || brewPhases.registered));
      const offered = brew.capture_phase === 'end_signal';
      children.push(el('details', {id:'brew-feedback', class:'flow-extra', open:offered, 'data-offered':offered ? 'yes' : null},
        el('summary', {}, '已出杯？现在写品饮反馈'), brewParameters(brew), renderFeedback(brew)), BrewChart.create(brew.id));
    } else {
      if (brew.capture_state === 'finished' && brew.journal && !brew.retry) {
        const chart = BrewChart.create(brew.id);
        const historyChart = el('details', { class:'flow-extra' }, el('summary', {}, '查看注水、液重与出杯流速曲线'), chart);
        historyChart.addEventListener('toggle', async () => {
          if (!historyChart.open || chart.dataset.loaded) return;
          chart.dataset.loaded = 'pending';
          try {
            const {telemetry} = await api(`${API}/brews/${brew.id}/live`);
            BrewChart.update(chart, telemetry, true);
            chart.dataset.loaded = 'yes';
          } catch (_) {
            delete chart.dataset.loaded; BrewChart.offline(chart);
          }
        });
        children.push(historyChart);
      }
      if (stage === '品饮反馈' || ['needs_review', 'failed', 'unconfirmed'].includes(brew.status) || app.data.feedback.some(f => f.cup === `brew-${brew.id}`)) {
        const feedback = el('div', {}, brewParameters(brew), renderFeedback(brew));
        children.push(stage === '品饮反馈' || (brew.status === 'needs_review' && !brew.retry)
          ? el('div', { id: 'brew-feedback' }, el('h3', {}, '各自喝到什么'), feedback) :
          el('details', { id: 'brew-feedback', class: 'flow-extra' }, el('summary', {}, '查看或补充品饮反馈'), feedback));
      }
      const result = brew.recipe_id && !(brew.status === 'prepared' && brew.rinse) ? renderRecordForm(brew) : null;
      if (result) result.open = stage === '手动制作';
      if (stage === '品饮反馈') {
        children.push(el('details', { class: 'flow-extra' }, el('summary', {}, '冲煮详情与报告'), live, result));
      } else if (result) children.push(result);
    }
    return el('section', { class: 'panel', id: 'brew-panel', 'data-stage': stage }, children);
  }
  function renderRecordForm(brew) {
    const old = brew.observations || {};
    const state = select([{ value: 'unconfirmed', label: '完成状态未确认' }, { value: 'completed', label: '人工确认完成' }, { value: 'failed', label: '制作失败' }], ['completed', 'failed', 'unconfirmed'].includes(brew.status) ? brew.status : 'unconfirmed');
    const dose = getRecipe(brew.recipe_id)?.payload.doseGrams;
    const consumption = number(brew.consumption_g, { placeholder: '按实际用量填写' });
    state.addEventListener('change', () => {
      consumption.placeholder = state.value === 'completed' && brew.status !== 'completed' ? `默认扣 ${dose} g` : '按实际用量填写';
    });
    if (brew.consumption_g != null) consumption.disabled = true;
    const seconds = number(old.screen_seconds, { placeholder: '未知留空' });
    const beverage = number(old.beverage_g, { placeholder: '未知留空' });
    const brewer = input(old.brewer || '', { placeholder: '例如：改装 V60' });
    const grinder = input(old.grinder || '', { placeholder: '使用的磨豆机' });
    const grindSetting = input(old.grind_setting || '', { placeholder: '实际研磨刻度' });
    const note = textarea(old.note || '', { placeholder: '记录实际发生的事，例如异常、人工调整或最后一滴。' });
    return el('details', { id: 'brew-result-form', open: !['running', 'starting'].includes(brew.status) }, el('summary', {}, '冲煮结果与实际耗豆'), el('div', {}, el('div', { class: 'two-fields' }, field('本杯结果', state), field('实际耗豆 / g', consumption, brew.consumption_g != null ? '已经确认扣豆，不能在此重复扣量或退回。' : '首次确认完成时，留空按本杯配方粉量扣库存。用量不同请填写本批豆的实际克数。')), el('div', { class: 'two-fields' }, field('机器屏幕计时 / 秒', seconds, '不以电脑采集时长代替。'), field('实测杯中液重 / g', beverage)), el('div', { class: 'three-fields' }, field('滤杯 / 冲煮器具', brewer), field('磨豆机', grinder), field('研磨刻度', grindSetting)), field('过程备注', note), button('保存本杯结果', event => run(`record:${brew.id}`, event.currentTarget, async () => {
      const request = { status: state.value, observations: { note: note.value.trim(), screen_seconds: numeric(seconds, '屏幕计时'), beverage_g: numeric(beverage, '杯中液重'), brewer: brewer.value.trim() || null, grinder: grinder.value.trim() || null, grind_setting: grindSetting.value.trim() || null } };
      const grams = numeric(consumption, '耗豆量');
      if (grams != null) request.consumption_g = grams;
      else if (state.value === 'completed' && brew.status !== 'completed') request.consumption_g = dose;
      await write(`record:${brew.id}`, `${API}/brews/${brew.id}/record`, request, `记录当杯 #${brew.id} 结果`);
      await refresh();
      announce('本杯人工记录已保存。机器原始证据仍单独保留。');
    }), 'secondary')));
  }
  function renderFeedback(brew, onlyPerson) {
    if (!app.data.people.length) return empty('尚无品饮者', '请先在库存管理中建立品饮者。');
    return el('div', { class: 'feedback-grid' }, app.data.people.filter(person => !onlyPerson || sameId(person.id, onlyPerson)).map(person => {
      const previous = feedbackFor(brew.id, person.id);
      const old = previous?.feedback || {};
      const score = number(old.overall, { min: '0', max: '10', step: '0.1', placeholder: '未评分' });
      const taste = textarea(old.taste || '', { placeholder: '直接写自己的话。热、温、凉分别如何，也可一起记。' });
      const next = textarea(old.next || '', { placeholder: '下次想保留什么，想改变什么？' });
      return el('details', { class: 'feedback-card', name: `feedback-${brew.id}`, open: Boolean(onlyPerson) },
        el('summary', {}, el('strong', {}, person.name), pill(previous ? old.overall != null ? `${old.overall} / 10` : '已记录' : '写品饮反馈', previous ? 'green' : '')), field('整体评分 / 10', score, '可以不打分；不会自动填入分数。'), field('我的品饮原话', taste), field('下次想法', next), button('保存我的反馈', event => run(`feedback:${brew.id}:${person.id}`, event.currentTarget, async () => {
        const overall = numeric(score, '评分');
        if (overall != null && overall > 10) throw new Error('评分范围是 0–10。');
        if (overall == null && !taste.value.trim() && !next.value.trim()) throw new Error('请至少留下评分或一句自己的感受；没有反馈时保持未记录。');
        const feedback = { ...old, taste: taste.value.trim(), next: next.value.trim() };
        if (overall == null) delete feedback.overall; else feedback.overall = overall;
        const saved = await api(`${API}/feedback`, { person_id: person.id, cup: `brew-${brew.id}`, feedback, revision: previous?.revision || 0 });
        const index = app.data.feedback.findIndex(f => f.cup === saved.cup && sameId(f.person_id, saved.person_id));
        if (index >= 0) app.data.feedback[index] = saved; else app.data.feedback.push(saved);
        const card = event.target.closest('.feedback-card');
        if (card?.isConnected) {
          const updated = renderFeedback(brew, person.id).firstElementChild;
          updated.open = Boolean(onlyPerson);
          card.replaceWith(updated);
        }
        announce(`${person.name}的本杯反馈已保存。`);
      }), 'secondary'));
    }));
  }
  function renderRecords() {
    const brews = newest(app.data.brews);
    if (app.recordBrew) {
      const selected = getBrew(app.recordBrew);
      return el('div', { class: 'flow-page' }, el('header', { class: 'flow-heading' },
        el('h1', {}, selected ? beanName(selected.bean_id) : '未找到这杯'),
        button('返回记录列表', () => navigate('records'), 'secondary')),
        selected && renderBrew(selected.id, true));
    }
    return el('div', { class: 'flow-page' }, el('header', { class: 'flow-heading' }, el('h1', {}, '冲煮记录'), el('span', { class: 'small muted' }, `共 ${brews.length} 杯`)),
      brews.length ? el('div', { class: 'history-items' }, brews.map(brew => el('a', {
        class: 'history-link', href: `/studio?view=records&brew=${brew.id}`,
        onclick: event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate('records', brew.id); } }
      }, el('div', {}, el('strong', {}, `#${brew.id} · ${beanName(brew.bean_id)}`),
        el('small', {}, `${formatTime(brew.created_at)} · ${MODES[brew.mode] || '历史记录'}`)), statusPill(brew, 'brew'))))
      : empty('还没有冲煮记录', '制作第一杯后可以在这里查看。'));
  }
  function feedbackReferences(beanId, afterBrew) {
    return app.data.feedback.flatMap(item => {
      const match = /^brew-(\d+)$/.exec(item.cup);
      const brew = match && getBrew(match[1]);
      if (!brew || (beanId && !sameId(brew.bean_id, beanId)) || (afterBrew && Number(brew.id) <= Number(afterBrew))) return [];
      return [{ key: `${brew.id}:${item.person_id}`, brew, item, label: `#${brew.id} · ${beanName(brew.bean_id)} · ${personName(item.person_id)}` }];
    });
  }
  function sourceCitation(brewId, personId, snapshot, revision) {
    const current = feedbackFor(brewId, personId);
    const feedback = snapshot || current?.feedback;
    return el('div', { class: 'citation' }, el('strong', {}, `引用当杯 #${brewId} · ${personName(personId)}${revision ? ` · 反馈 v${revision}` : ''}`), feedback ? (feedback.taste || feedback.next || (feedback.overall != null ? `整体评分 ${feedback.overall} / 10；无文字感受` : '此条反馈未含文字感受')) : '当前未找到对应个人反馈，不作为有效品鉴证据。', snapshot && current?.revision > revision && el('p', {}, `此处保留引用时原话；该人的当前反馈已更新至 v${current.revision}。`));
  }
  function renderExperiences() {
    const refs = feedbackReferences();
    const chosen = select(refs.map(item => ({ value: item.key, label: item.label })), '', null, '选择已经有个人反馈的杯子…');
    const citation = el('div');
    chosen.addEventListener('change', () => { const ref = refs.find(item => item.key === chosen.value); citation.replaceChildren(...(ref ? [sourceCitation(ref.brew.id, ref.item.person_id)] : [])); });
    const condition = textarea('', { placeholder: '在哪款豆子、设备、温段或口味目标下观察到？' });
    const action = textarea('', { placeholder: '实际采用或建议再试的调整是什么？' });
    const expected = textarea('', { placeholder: '期待下一杯出现什么可观察的变化？' });
    const notes = textarea('', { placeholder: '哪些仍未验证，哪些条件可能影响判断？' });
    const form = panel('从一杯反馈开始', el('p', { class: 'muted small' }, '先留下候选经验，再用后续杯子的个人反馈支持、反驳，或保留不足。'), el('div', { class: 'section-gap' }, field('依据哪杯、谁的反馈', chosen), citation, field('适用条件', condition), field('动作或调整', action), field('预期变化', expected), field('补充说明 / 未知', notes), button('保存为经验候选', event => run('experience', event.currentTarget, async () => {
      const ref = refs.find(item => item.key === chosen.value);
      if (!ref) throw new Error('请选择一杯已有个人反馈的记录。');
      if (![condition, action, expected].every(control => control.value.trim())) throw new Error('请填写适用条件、动作与预期变化。');
      await write('experience', `${API}/experiences`, { bean_id: ref.brew.bean_id, condition: condition.value.trim(), action: action.value.trim(), expected: expected.value.trim(), source_brew_id: ref.brew.id, source_person_id: ref.item.person_id, notes: notes.value.trim() }, `记录 ${beanName(ref.brew.bean_id)} 的经验候选`);
      await refresh();
      announce('经验候选已保存。后续实际反馈决定它获得支持、出现反例，还是仍然不足。');
    }), '', !refs.length)), !refs.length && el('p', { class: 'inline-note' }, '目前没有可引用的个人反馈。请先在当杯记录中留下真实感受。'));
    const experiences = newest(app.data.experiences);
    return el('div', {}, intro('LEARN FROM EACH CUP', '经验，留得下，也经得起反例。', '同一款豆、具体的一杯、某个人的感受。每条判断都保留适用条件，沉默和复点不算好评。'), el('div', { class: 'experience-layout' }, form, el('section', {}, el('div', { class: 'section-title' }, el('h2', {}, '经验候选与后续观察'), el('span', { class: 'small' }, `${experiences.length} 条`)), experiences.length ? experiences.map(renderExperience) : empty('还没有经验候选', '喝过、留下原话，再从具体杯子中提炼。'))));
  }
  function renderExperience(experience) {
    const refs = feedbackReferences(experience.bean_id, experience.source_brew_id);
    const chosen = select(refs.map(item => ({ value: item.key, label: item.label })), '', null, '选择后续杯子的个人反馈…');
    const verdict = select(Object.entries(VERDICTS).map(([value, label]) => ({ value, label })), 'insufficient');
    const notes = textarea('', { placeholder: '写明这杯为什么支持、反驳，或不足以判断。' });
    const evaluations = Array.isArray(experience.evaluations) ? experience.evaluations : [];
    return el('article', { class: 'panel experience-card' }, el('div', { class: 'section-title' }, el('h2', {}, beanName(experience.bean_id)), pill('经验候选')), el('div', { class: 'claim' }, [['条件', experience.condition], ['动作', experience.action], ['预期', experience.expected]].map(([label, value]) => el('p', {}, el('strong', {}, label), value))), sourceCitation(experience.source_brew_id, experience.source_person_id, experience.feedback_snapshot, experience.feedback_revision), experience.notes && el('p', { class: 'inline-note' }, experience.notes), el('details', { open: evaluations.length > 0 }, el('summary', {}, `后续观察 · ${evaluations.length} 条`), el('div', {}, evaluations.length ? evaluations.map(item => el('div', { class: 'evaluation' }, pill(VERDICTS[item.verdict] || item.verdict, item.verdict === 'support' ? 'green' : item.verdict === 'counterexample' ? 'red' : 'warn'), el('p', {}, item.notes || '未填写判断说明'), sourceCitation(item.brew_id, item.person_id, item.feedback_snapshot, item.feedback_revision))) : el('p', { class: 'muted small' }, '尚无后续证据，不能视作规律。'))), el('details', {}, el('summary', {}, '引用后续一杯，评价这条经验'), el('div', {}, field('同一豆子的后续反馈', chosen), field('这次证据说明什么', verdict), field('判断依据', notes), button('保存观察', event => run(`evaluate:${experience.id}`, event.currentTarget, async () => {
      const ref = refs.find(item => item.key === chosen.value);
      if (!ref) throw new Error('请选择同一豆子后续杯子的个人反馈。');
      await write(`evaluate:${experience.id}`, `${API}/experiences/${experience.id}/evaluate`, { brew_id: ref.brew.id, person_id: ref.item.person_id, verdict: verdict.value, notes: notes.value.trim() }, `评价经验 #${experience.id}`);
      await refresh();
      announce('后续观察已保存，原经验与原始反馈均保留。');
    }), 'secondary', !refs.length), !refs.length && el('p', { class: 'inline-note' }, '还没有同一豆子的后续个人反馈；先做下一杯，再评价。'))));
  }

  document.querySelectorAll('[data-view]').forEach(link => link.addEventListener('click', event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(link.dataset.view); }));
  window.addEventListener('popstate', () => { app.view = locationView(); app.recordBrew = new URLSearchParams(location.search).get('brew') || '';
    if (app.view === 'studio') app.brew = new URLSearchParams(location.search).get('cup') || '';
    renderApp(); });
  window.addEventListener('beforeunload', event => { if (app.aiSettingsDraft) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('storage', event => {
    if (event.key !== aiSettingsSignal || !app.data) return;
    if (app.view === 'ai' && !app.aiSettingsDraft) renderApp();
    else syncAISettings();
  });
  window.addEventListener('focus', () => {
    if (!app.data || app.busy.size) return;
    if (['studio', 'records'].includes(app.view)) {
      refresh(false).catch(brewSyncFailed);
    } else if (app.view === 'menu') syncAISettings();
  });
  $('refresh').addEventListener('click', event => run('refresh', event.currentTarget, async () => { await refresh(); announce('已同步库存与记录。'); }));
  renderPending();
  refresh().then(resumeAIJob).catch(error => {
    $('main').replaceChildren(empty('暂时无法读取工作台', '请检查本机服务是否启动，再点击右上角刷新。'));
    announce(error.message, true);
  });
  if (!app.storageReady) announce('浏览器本地存储不可用，业务保存暂不可用。请允许本站保存数据后重新加载。', true);
  setInterval(() => {
    if (document.hidden) return;
    updateRecipeProgress();
    if (app.aiJob?.status === 'running') pollAIJob();
    for (const [person, job] of Object.entries(app.recommendJobs)) if (job.status === 'running') pollRecommendation(person);
  }, 1500);
  async function pollBrew() {
    if (document.hidden || !app.data || app.brewPolling) return;
    const selected = getBrew(app.view === 'records' ? app.recordBrew : app.brew);
    const isActive = b => b && (b.rinse?.state === 'running' || b.capture_state === 'running' || ['starting','running'].includes(b.status));
    const active = isActive(selected) ? selected : app.data.brews.find(isActive);
    const current = active || (brewNotice && app.pending[`start:${brewNotice.id}`] && getBrew(brewNotice.id));
    if (!current) return;
    app.brewPolling = true;
    try {
      const {brew, telemetry} = await api(`${API}/brews/${current.id}/live`);
      if (getBrew(current.id) !== current) return;
      const changed = brew.rinse?.state !== current.rinse?.state || brew.status !== current.status || brew.capture_phase !== current.capture_phase || brew.capture_state !== current.capture_state;
      app.data.brews = app.data.brews.map(b => sameId(b.id, brew.id) ? brew : b);
      if (brewNotice) brewNotice.syncError = false;
      updateBrewProgress();
      if (changed) {
        const order = getOrder(brew.order_id);
        if (order) order.status = brew.status;
        updateBrewStatus();
      }
      const chart = document.querySelector('#brew-panel[data-stage="冲煮中"] .live-chart');
      if (chart && sameId(chart.dataset.brew, brew.id)) BrewChart.update(chart, telemetry);
    } catch (_) {
      brewSyncFailed();
      const chart = document.querySelector('#brew-panel[data-stage="冲煮中"] .live-chart');
      if (chart) BrewChart.offline(chart);
    } finally { app.brewPolling = false; }
  }
  setInterval(pollBrew, 1000);
})();
