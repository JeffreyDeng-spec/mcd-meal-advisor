'use strict';
const assert=require('node:assert/strict');
const report=require('../skills/mcd-meal-advisor/assets/report.js');
const now=Date.parse('2026-10-19T13:00:00+08:00');
function meal(id,cost,extras={}) {
  return {id,contents_key:id,payable_cents:cost,preference_score:0,coupon_name:null,coupon_expiry:null,
    quoted_at:'2026-10-19T13:00:00+08:00',expires_at:'2026-10-19T13:15:00+08:00',items:[{name:'汉堡',quantity:1}],...extras};
}
const a=meal('a',2000), b=meal('b',2500,{preference_score:1,items:[{name:'汉堡',quantity:1},{name:'薯条',quantity:1}]}),
  c=meal('c',2200,{coupon_name:'明天到期券',coupon_expiry:'2026-10-20T00:00:00+08:00'});
assert.deepEqual(report.pickPlans([a,b,c],3000,now).map(x=>x.plan.id),['a','b','c']);
assert.deepEqual(report.pickPlans([a,b,c],2000,now).map(x=>x.plan.id),['a']);
assert.deepEqual(report.pickPlans([a,b,c],100,now),[]);
assert.equal(report.view({plans:[a,b,c]},1900,now).shortfall,100);
assert.equal(report.view({plans:[a,b,c]},9000,now+16*60000).expired,3);
assert.equal(report.pickPlans([a,b,c],9000,now+16*60000).length,0);
assert.equal(report.pickPlans([a],2000,now+15*60000).length,1);
assert.equal(report.pickPlans([a],2000,now-1).length,0);
assert.deepEqual(report.difference(a,b),{added:[{name:'薯条',quantity:1}],removed:[],unchanged:[{name:'汉堡',quantity:1}],delta_cents:500});
const dup=meal('duplicate',2200,{contents_key:'a',coupon_name:'无意义优惠券'});
assert.equal(report.pickPlans([a,dup],3000,now)[0].plan.id,'a');
assert.equal(report.pickPlans([a,dup],3000,now).length,1);
assert.equal(report.money(29),'¥0.29');
assert.equal(report.pickPlans([a,b,c],2200,now).some(x=>x.plan.id==='b'),false);
assert.equal(report.pickPlans([a,b,c],10000,now).length,3); // Raising budget cannot invent new quotes.
assert.deepEqual(report.pickPlans([a],3000,now)[0].labels,['最低实付']);
const other=meal('other',2100);
assert.equal(report.view({plans:[a,other]},3000,now).chosen.length,1);
assert.equal(report.view({plans:[a,other]},3000,now).comparable.length,2);
assert.equal(report.comparablePlans([a,dup,other],3000,now).length,2);
assert.equal(report.comparablePlans([a,other],3000,now+16*60000).length,0);
assert.equal(report.auditStale({verification_expires_at:a.expires_at},now),false);
assert.equal(report.auditStale({verification_expires_at:a.expires_at},now+16*60000),true);
assert.equal(report.auditStale({},now),false);

(async()=>{
  let removed=false,selected=false,focused=false;
  const area={value:'',setAttribute(){},select(){selected=true;},remove(){removed=true;},focus(){focused=true;},scrollIntoView(){}};
  const doc={body:{appendChild(){}},createElement(){return area;},execCommand(){return true;}};
  assert.equal(await report.copyText('换掉薯条',doc,{}),'copied');
  assert.equal(area.value,'换掉薯条');assert.equal(selected,true);assert.equal(removed,true);
  doc.execCommand=()=>false;removed=false;
  assert.equal(await report.copyText('人工复制',doc,{}),'manual');assert.equal(focused,true);assert.equal(removed,false);
  global.isSecureContext=true;
  let copied='';assert.equal(await report.copyText('新查询',doc,{clipboard:{async writeText(s){copied=s;}}}),'copied');
  assert.equal(copied,'新查询');
  doc.execCommand=()=>true;
  assert.equal(await report.copyText('回退',doc,{clipboard:{async writeText(){throw Error('denied');}}}),'copied');
  console.log('Report logic passed: budget, expiry, differences, preference labels, comparisons and clipboard fallbacks.');
})().catch(e=>{console.error(e);process.exitCode=1;});
