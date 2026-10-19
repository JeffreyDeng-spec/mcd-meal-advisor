/* Browser-local synthetic demo. This file never contacts an API. */
(function(root){
  'use strict';
  const SITE='https://jeffreydeng-spec.github.io/mcd-meal-advisor/';
  function resetClock(data,now=Date.now()) {
    if(!data || data.mode!=='demo')throw Error('synthetic_demo_required');
    const copy=JSON.parse(JSON.stringify(data));
    const source=Date.parse(data.generated_at);
    for(const p of copy.plans) {
      const shift=t=>t?new Date(now+Date.parse(t)-source).toISOString():null;
      p.quoted_at=shift(p.quoted_at);p.expires_at=shift(p.expires_at);
      p.coupon_comparison_expires_at=shift(p.coupon_comparison_expires_at);
      p.coupon_expiry=shift(p.coupon_expiry);
    }
    copy.generated_at=new Date(now).toISOString();return copy;
  }
  function parseBudget(text) {
    if(!/^\d+(\.\d{1,2})?$/.test(text)||Number(text)>1000)throw Error('请输入0–1000元，最多两位小数。');
    return Math.round(Number(text)*100);
  }
  function requestText(budget,roast,side) {
    return '使用麦麦点餐参谋。一个人，上海人民广场附近，现在到店自取，预算'+(budget/100).toFixed(2)+
      '元，要一个鸡肉汉堡和一份'+(side==='fries'?'薯条':side==='corn'?'玉米杯':'小食')+'，不要饮料，不额外加购。'+
      (roast?'偏好香烤。':'')+'请先让我选择真实营业门店，再查询真实菜单和当前券包，对完整餐单官方核价。只提供建议，不下单、不领券。';
  }
  function revisionTarget(plans,base,side) {
    const sideName=side==='fries'?'小份薯条':'小份玉米杯';
    const burger=base.items.find(x=>x.name.includes('汉堡'));
    return plans.filter(p=>p.items.some(x=>x.name===sideName)&&p.items.some(x=>x.name===burger.name&&x.quantity===burger.quantity))
      .sort((a,b)=>a.payable_cents-b.payable_cents||a.id.localeCompare(b.id))[0]||null;
  }
  const api={resetClock,parseBudget,requestText,revisionTarget};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.MealDemo=api;
  if(typeof document==='undefined')return;
  const by=id=>document.getElementById(id),engine=root.MealReport;
  let data=resetClock(root.MEAL_DEMO_DATA),started=false,budget=3000,revisionSide=null,expired=false;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const storeName=()=>by('store').value==='square'?'示例人民广场店':'示例步行街店';
  function currentPlans(){return data.plans.map(p=>({...p,preference_score:by('taste').value==='roast'?p.preference_score:0}));}
  function now(){return expired?Date.parse(data.generated_at)+16*60000:Date.now();}
  function options(select,plans){
    const previous=select.value;select.replaceChildren();
    for(const p of plans){const option=el('option',p.name+' · '+engine.money(p.payable_cents));option.value=p.id;select.append(option);}
    if(plans.some(p=>p.id===previous))select.value=previous;
  }
  async function copy(text){
    by('manual-copy').replaceChildren();
    const outcome=await engine.copyText(text);
    by('copy-status').textContent=outcome==='copied'?'已复制。粘贴到你的聊天客户端继续。':'自动复制不可用，请在页面底部手动复制。';
  }
  function compare(){
    const a=data.plans.find(p=>p.id===by('compare-a').value),b=data.plans.find(p=>p.id===by('compare-b').value),out=by('diff');out.replaceChildren();
    if(!a||!b)return;
    const d=engine.difference(a,b),format=xs=>xs.length?xs.map(x=>x.name+' ×'+x.quantity).join('、'):'无';
    out.append(el('p','增加：'+format(d.added)),el('p','减少：'+format(d.removed)),el('p','保持：'+format(d.unchanged)),el('strong','示例整单差价 '+(d.delta_cents>=0?'+':'−')+engine.money(Math.abs(d.delta_cents))),el('p','整单差价与同餐用券收益分别比较。','fine'));
  }
  function render(){
    if(!started)return;
    const plans=currentPlans(),view=engine.view({plans},budget,now()),cards=by('cards');cards.replaceChildren();
    const isOld=view.expired===plans.length;
    by('clock').textContent=isOld?'演示报价已过期':'演示时钟 · 15分钟有效';
    by('result-title').textContent=storeName()+' · '+engine.money(budget)+'预算';
    by('result-status').textContent=isOld?'报价已过期，需重新核价。点击“重置演示”体验新一轮合成场景。':view.chosen.length?'本轮示例有'+view.chosen.length+'种推荐。最低实付只指已比较的候选。':'预算内没有示例方案，最近一份还差'+engine.money(view.shortfall||0)+'。';
    const floor=view.chosen.length?Math.min(...view.chosen.map(x=>x.plan.payable_cents)):0;
    for(const entry of view.chosen){
      const p=entry.plan,card=el('article',undefined,'meal');card.append(el('p',entry.labels.join(' · '),'tags'),el('h4',p.name));
      const list=el('ul');for(const item of p.items)list.append(el('li',item.name+' ×'+item.quantity));card.append(list);
      card.append(el('strong',engine.money(p.payable_cents),'price'),el('p','示例整单价 · 预算剩余 '+engine.money(budget-p.payable_cents),'remaining'),el('p',p.payable_cents===floor?'本轮示例实付最低':'比最低实付多 '+engine.money(p.payable_cents-floor),'detail'));
      card.append(el('p',p.coupon_name?'使用示例优惠券；同餐少付 '+engine.money(p.coupon_saving_cents||0):'不使用优惠券','detail'));
      const button=el('button','选这份，试试换小食');button.type='button';button.addEventListener('click',()=>{by('revise-plan').value=p.id;by('revision-panel').scrollIntoView({behavior:'smooth',block:'center'});});card.append(button);cards.append(card);
    }
    by('compare-panel').hidden=view.comparable.length<2;
    const oldB=by('compare-b').value;options(by('compare-a'),view.comparable);options(by('compare-b'),view.comparable);
    if(!oldB&&view.comparable.length>1)by('compare-b').value=view.comparable[1].id;
    compare();
    by('revision-panel').hidden=!view.comparable.length;options(by('revise-plan'),view.comparable);
    by('coupon-panel').hidden=false;by('demo-tools').hidden=false;
    const applicable=view.comparable.filter(p=>p.coupon_name&&p.coupon_saving_cents!==null);
    by('coupon-saving').textContent=isOld?'本轮券收益核验已过期，请重新核价。':applicable.length?'示例同餐对照：用券最多少付 '+engine.money(Math.max(...applicable.map(p=>p.coupon_saving_cents)))+'。':'当前预算内餐单没有已验证的用券收益，不为用券提高预算。';
    by('copy-request').textContent=isOld?'复制需求，回聊天重新核价':'复制需求，去聊天查真实价格';
  }
  function generate(){
    try{budget=parseBudget(by('budget').value.trim());if(!by('store').value)throw Error('请先选择一家演示门店。');}
    catch(e){by('error').textContent=e.message;return;}
    by('error').textContent='';started=true;revisionSide=null;by('revision-status').textContent='';render();
  }
  by('generate').addEventListener('click',generate);
  for(const button of document.querySelectorAll('[data-budget]'))button.addEventListener('click',()=>{by('budget').value=button.dataset.budget;if(started)generate();});
  by('taste').addEventListener('change',()=>{if(started)generate();});
  by('store').addEventListener('change',()=>{by('error').textContent='';if(started){by('clock').textContent='等待重新生成';by('cards').replaceChildren();started=false;by('result-title').textContent='门店已改变，请重新生成示例。';by('result-status').textContent='上一家门店的餐单不再展示。';for(const id of ['compare-panel','revision-panel','coupon-panel','demo-tools'])by(id).hidden=true;}});
  by('compare-a').addEventListener('change',compare);by('compare-b').addEventListener('change',compare);
  by('revise').addEventListener('click',()=>{
    const base=data.plans.find(p=>p.id===by('revise-plan').value);if(!base)return;
    if(!engine.fresh(base,now())){by('revision-status').textContent='原报价已过期，请重置演示再试。';return;}
    const side=by('side').value,target=revisionTarget(data.plans,base,side);
    if(!target){by('revision-status').textContent='当前合成场景没有这个替换，请在真实聊天中查询。';return;}
    if(!engine.fresh(target,now())){by('revision-status').textContent='替换方案的示例报价已过期，请重置演示。';return;}
    revisionSide=side;by('revision-status').textContent='模拟重算完成：'+target.name+'，示例整单 '+engine.money(target.payable_cents)+'，'+(target.payable_cents<=budget?'预算剩余 '+engine.money(budget-target.payable_cents):'超预算 '+engine.money(target.payable_cents-budget))+'。汉堡、原预算和排除项保留。真实换餐需回聊天重新核价。';
  });
  by('reset').addEventListener('click',()=>{data=resetClock(root.MEAL_DEMO_DATA);expired=false;by('copy-status').textContent='';by('revision-status').textContent='';if(started)generate();else by('clock').textContent='等待开始';});
  by('expire').addEventListener('click',()=>{expired=true;by('revision-status').textContent='';render();});
  by('copy-request').addEventListener('click',()=>copy(requestText(budget,by('taste').value==='roast',revisionSide)));
  by('share').addEventListener('click',()=>copy(SITE));
  setInterval(render,30000);
})(typeof globalThis==='undefined'?this:globalThis);
