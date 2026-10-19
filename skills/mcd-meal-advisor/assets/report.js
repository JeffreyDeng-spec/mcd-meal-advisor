/* Pure report logic is shared by the standalone page and Node tests. No network. */
(function (root) {
  'use strict';
  const money = n => '¥' + (n / 100).toFixed(2);
  const fresh = (p, now) => Date.parse(p.quoted_at) <= now && now <= Date.parse(p.expires_at);
  const auditStale = (coupon,now=Date.now()) => !!coupon.verification_expires_at && now>Date.parse(coupon.verification_expires_at);
  function comparablePlans(plans, budget, now = Date.now()) {
    const groups = new Map();
    for (const p of plans.filter(p => p.payable_cents <= budget && fresh(p, now))) {
      const old = groups.get(p.contents_key);
      if (!old || p.payable_cents < old.payable_cents ||
          (p.payable_cents === old.payable_cents && ((p.coupon_expiry || '9999') < (old.coupon_expiry || '9999') ||
          ((p.coupon_expiry || '9999') === (old.coupon_expiry || '9999') && p.id.localeCompare(old.id)<0)))) groups.set(p.contents_key, p);
    }
    return [...groups.values()].sort((a,b)=>a.payable_cents-b.payable_cents || a.id.localeCompare(b.id));
  }
  function pickPlans(plans, budget, now = Date.now()) {
    const pool = comparablePlans(plans,budget,now), chosen = new Map();
    function add(list, label, compare) {
      const p = [...list].sort(compare)[0];
      if (!p) return;
      if (!chosen.has(p.id)) chosen.set(p.id, {plan:p, labels:[]});
      chosen.get(p.id).labels.push(label);
    }
    const cost = (a,b) => a.payable_cents-b.payable_cents || b.preference_score-a.preference_score ||
      (a.coupon_expiry || '9999').localeCompare(b.coupon_expiry || '9999') || a.id.localeCompare(b.id);
    add(pool,'最低实付',cost);
    add(pool.filter(p=>p.preference_score>0),'更合口味',(a,b) => b.preference_score-a.preference_score || cost(a,b));
    add(pool.filter(p => p.coupon_name),'用券参考',(a,b) => a.payable_cents-b.payable_cents ||
      (a.coupon_expiry || '9999').localeCompare(b.coupon_expiry || '9999') || a.id.localeCompare(b.id));
    return [...chosen.values()];
  }
  function difference(a,b) {
    const counts = p => { const m = new Map(); for(const x of p.items) m.set(x.name,(m.get(x.name)||0)+x.quantity); return m; };
    const x=counts(a), y=counts(b), added=[], removed=[], unchanged=[];
    for(const name of new Set([...x.keys(),...y.keys()])) {
      const n=x.get(name)||0, m=y.get(name)||0;
      if(m>n) added.push({name,quantity:m-n});
      if(n>m) removed.push({name,quantity:n-m});
      if(Math.min(n,m)>0) unchanged.push({name,quantity:Math.min(n,m)});
    }
    return {added,removed,unchanged,delta_cents:b.payable_cents-a.payable_cents};
  }
  function view(data,budget,now=Date.now()) {
    const current=data.plans.filter(p=>fresh(p,now));
    return {chosen:pickPlans(data.plans,budget,now),
      comparable:comparablePlans(data.plans,budget,now),
      shortfall:current.length?Math.max(0,Math.min(...current.map(p=>p.payable_cents))-budget):null,
      expired:data.plans.filter(p=>!fresh(p,now)).length};
  }
  async function copyText(text, doc = typeof document==='undefined'?null:document, nav = typeof navigator==='undefined'?null:navigator) {
    if(nav && nav.clipboard && root.isSecureContext) {
      try { await nav.clipboard.writeText(text); return 'copied'; } catch (_) { /* file:// fallback */ }
    }
    if(!doc) return 'manual';
    const area=doc.createElement('textarea'); area.value=text; area.setAttribute('aria-label','可手动复制的修改请求');
    doc.body.appendChild(area); area.select();
    let copied=false; try { copied=doc.execCommand('copy'); } catch (_) {}
    if(copied) area.remove(); else { area.focus(); area.scrollIntoView({block:'center'}); }
    return copied?'copied':'manual';
  }
  const api={money,fresh,auditStale,comparablePlans,pickPlans,difference,view,copyText};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  root.MealReport=api;
  if(typeof document==='undefined') return;

  const data=JSON.parse(document.getElementById('report-data').textContent);
  const byId=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const time=t=>new Date(t).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  const initialBudget=data.request.budget_cents;
  let budget=initialBudget;
  const req=data.request.required.map(g=>(g.terms.length?g.terms.join(' / '):'已指定餐品')+' ×'+g.quantity).join('、');
  byId('source').textContent=data.mode==='demo'?'合成数据演示 · 不代表实际售价':'官方 MCP 核价 · 历史结果按时间标注';
  byId('store').textContent=data.store.name+' · 到店自取';
  byId('address').textContent=data.store.address;
  byId('request').textContent=req+(data.request.excluded.length?'；不要：'+data.request.excluded.join('、'):'')+
    (data.request.preferred.length?'；偏好：'+data.request.preferred.join('、'):'');
  byId('budget').value=(initialBudget/100).toFixed(2);
  byId('original-budget').textContent='原预算 '+money(initialBudget)+' · 当前筛选只使用已有报价';
  byId('run').textContent='本轮 '+data.run_id+' · 已核价 '+data.attempts+' 次'+
    (data.failures?' · '+data.failures+' 份失败未报价':'')+(data.pending?' · '+data.pending+' 份尚未核价':'');
  function renderAudit(now) {
  const audit=byId('audit-list');audit.replaceChildren();
  if(!data.coupon_audit.length) audit.append(node('p',data.stock_status==='unavailable'?'券包未成功读取，本轮不判断账户持券情况。':'当前券包为空。仍可比较不带券的真实报价。','muted'));
  for(const c of data.coupon_audit) {
    const stale=auditStale(c,now);
    const row=node('article',undefined,'coupon'); row.append(node('h3',c.name),node('span',stale?'本轮核验已过期，需重新核价':c.state,'pill'));
    row.append(node('p',(c.held?'账户持有':'账户持有未确认')+' · '+(c.store_available?'本店可用':'本店适用性未确认')+' · '+(c.basket_verified?'本轮餐单已核验':'本轮餐单尚未核验'),'muted'));
    row.append(node('p',c.restrictions||'使用限制尚未完整确认','muted'));
    row.append(node('p',stale?'已验证金额仅供回看，请回到聊天重新核价':c.saving_cents===null?'本轮净节省：未知':c.saving_cents>=0?
      '同内容对照，少付 '+money(c.saving_cents):'同内容对照，反而多付 '+money(-c.saving_cents)));
    if(c.expires_at) row.append(node('small','有效期至 '+time(c.expires_at)));
    audit.append(row);
  }
  if(!data.stock_complete) audit.append(node('p','当前券包未完整获取；以上仅涵盖已读取部分。','notice'));
  }

  function render() {
    const now=Date.now(), result=view(data,budget,now), cards=byId('cards'); cards.replaceChildren();
    renderAudit(now);
    byId('budget-value').textContent=money(budget);
    byId('count').textContent=result.chosen.length+' 份可选';
    byId('status').textContent=result.chosen.length?'先看总价，再看你更想吃什么。':
      result.shortfall===null?'本轮暂无新鲜有效报价，请回到聊天重新核价。':
      '当前预算内没有已核价方案，最近一份还差 '+money(result.shortfall)+'。';
    const floor=result.chosen.length?Math.min(...result.chosen.map(x=>x.plan.payable_cents)):null;
    for(const [i,entry] of result.chosen.entries()) {
      const p=entry.plan, card=node('article',undefined,'meal-card');
      const head=node('div',undefined,'card-head'); head.append(node('span','0'+(i+1),'number'),node('span',entry.labels.join(' · '),'pill'));card.append(head);
      const plate=node('div',undefined,'plate');plate.setAttribute('aria-hidden','true');plate.append(node('span',String(p.items.reduce((n,x)=>n+x.quantity,0)),'plate-number'),node('span','份餐品','plate-label'));card.append(plate);
      card.append(node('h3',p.name));
      const list=node('ul');for(const item of p.items)list.append(node('li',item.name+' ×'+item.quantity));card.append(list);
      const price=node('div',undefined,'price');price.append(node('strong',money(p.payable_cents)),node('span','整单应付'));card.append(price);
      card.append(node('p','预算剩余 '+money(budget-p.payable_cents),'remaining'));
      card.append(node('p',p.payable_cents===floor?'本轮推荐中实付最低':'比最低实付多 '+money(p.payable_cents-floor),'comparison'));
      card.append(node('p',p.coupon_name?'使用：'+p.coupon_name:'不使用优惠券','muted'));
      if(p.coupon_name)card.append(node('p',p.coupon_comparison_expires_at && now>Date.parse(p.coupon_comparison_expires_at)?'同内容对照已过期，需重新核价':p.coupon_saving_cents===null?'同内容不带券对照尚未验证':
        p.coupon_saving_cents>=0?'同内容用券少付 '+money(p.coupon_saving_cents):'同内容用券多付 '+money(-p.coupon_saving_cents),'muted'));
      card.append(node('small','核价 '+time(p.quoted_at)));
      const button=node('button','复制修改请求','primary');button.type='button';
      button.addEventListener('click',async()=>{const result=await copyText(p.request_text);byId('copy-status').textContent=result==='copied'?'已复制。回到聊天粘贴后说明想换什么。':'自动复制不可用，页面底部已展开文本，请手动复制。';});card.append(button);
      cards.append(card);
    }
    const selects=[byId('compare-a'),byId('compare-b')], available=result.comparable;
    selects.forEach((select,i)=>{const previous=select.value;select.replaceChildren();for(const p of available){const option=node('option',p.name+' · '+money(p.payable_cents));option.value=p.id;select.append(option);}select.value=available.some(p=>p.id===previous)?previous:(available[i]||available[0]||{}).id||'';});
    byId('compare').hidden=available.length<2;
    renderDiff();
    const history=byId('history');history.replaceChildren();history.hidden=!result.expired;
    if(result.expired) {
      history.append(node('h3','过期报价 · 仅供回看'));
      for(const p of data.plans.filter(p=>!fresh(p,now))) history.append(node('p',p.name+' · '+money(p.payable_cents)+' · 核价 '+time(p.quoted_at)));
    }
    const renewal='使用麦麦点餐参谋，参考本轮 '+data.run_id+'，预算 '+(budget/100).toFixed(2)+' 元，保留原有必选和排除项，请重新查询菜单并核价。';
    byId('renew').onclick=async()=>{const r=await copyText(renewal);byId('copy-status').textContent=r==='copied'?'已复制重新查询请求。':'请手动复制页面底部文本。';};
  }
  function renderDiff() {
    const a=data.plans.find(p=>p.id===byId('compare-a').value),b=data.plans.find(p=>p.id===byId('compare-b').value),out=byId('diff');out.replaceChildren();if(!a||!b)return;
    const d=difference(a,b),format=xs=>xs.length?xs.map(x=>x.name+' ×'+x.quantity).join('、'):'无';
    out.append(node('p','增加：'+format(d.added)),node('p','减少：'+format(d.removed)),node('p','保持：'+format(d.unchanged)));
    out.append(node('strong','整单差价 '+(d.delta_cents>=0?'+':'−')+money(Math.abs(d.delta_cents))),node('p','整单差价不代表新增餐品的单独售价。','muted'));
    const button=node('button','复制右侧方案的修改请求');button.type='button';
    button.addEventListener('click',async()=>{const r=await copyText(b.request_text);byId('copy-status').textContent=r==='copied'?'已复制。回到聊天粘贴后说明想换什么。':'请手动复制页面底部文本。';});out.append(button);
  }
  byId('budget-form').addEventListener('submit',event=>{event.preventDefault();const s=byId('budget').value.trim();if(!/^\d+(\.\d{1,2})?$/.test(s)||Number(s)>1000){byId('budget-error').textContent='请输入 0–1000 元，最多两位小数。';return;}budget=Math.round(Number(s)*100);byId('budget-error').textContent='';render();});
  byId('compare-a').addEventListener('change',renderDiff);byId('compare-b').addEventListener('change',renderDiff);
  render();setInterval(render,30000);
})(typeof globalThis==='undefined'?this:globalThis);
