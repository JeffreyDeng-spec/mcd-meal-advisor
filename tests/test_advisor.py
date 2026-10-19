import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'skills/mcd-meal-advisor/scripts'), str(ROOT/'examples')]
import advisor as a
from demo import fixture, synthetic_quote, demo_run

NOW = '2026-10-19T13:00:00+08:00'


class MoneyAndAdapter(unittest.TestCase):
    def test_decimal_conversion(self):
        self.assertEqual(a.yuan('0.29'), 29)
        self.assertEqual(a.yuan('25.50'), 2550)

    def test_bad_money(self):
        for n in ['NaN', 'Infinity', '-1', '0.001', None]:
            with self.subTest(n=n), self.assertRaises(a.Invalid): a.yuan(n)

    def test_cents_are_integers(self):
        for n in [True, 12.5, '1200', -1]:
            with self.subTest(n=n), self.assertRaises(a.Invalid): a.integer(n)

    def test_business_failure_even_when_iserror_false(self):
        with self.assertRaises(a.Invalid): a.envelope({'isError':False,'structuredContent':{'success':False,'code':600022,'data':{}}})

    def test_structured_precedence(self):
        self.assertEqual(a.envelope({'structuredContent':{'success':True,'data':{'price':1}},'content':[{'type':'text','text':'{"success":true,"data":{"price":999}}'}]}), {'price':1})

    def test_text_json_and_ambiguity(self):
        response={'content':[{'type':'text','text':'说明\n{"success":true,"code":200,"data":{"price":123}}'}]}
        self.assertEqual(a.envelope(response)['price'],123)
        response['content'][0]['text']+='\n{"success":true,"data":{"price":456}}'
        with self.assertRaises(a.Invalid):a.envelope(response)

    def test_missing_success_not_trusted(self):
        with self.assertRaises(a.Invalid):a.envelope({'data':{'price':1}})

    def test_scope_rejects_other_channels(self):
        for field,value in [('people',2),('order_type',2),('be_type',5)]:
            b=fixture(NOW);b['request'][field]=value
            with self.subTest(field=field),self.assertRaises(a.Invalid):a.prepare(b)

    def test_detail_cannot_change_product_identity(self):
        b=fixture(NOW);b['details']['A']['data']['code']='OTHER'
        with self.assertRaises(a.Invalid):a.prepare(b)


class Planning(unittest.TestCase):
    def setUp(self):
        self.bundle=fixture(NOW);self.run=a.prepare(self.bundle);self.s=self.run['snapshot'];self.r=self.run['request']

    def test_at_most_twenty_distinct_probe_requests(self):
        self.assertLessEqual(len(self.run['candidates']),20)
        self.assertEqual(len({c['fingerprint'] for c in self.run['candidates']}),len(self.run['candidates']))

    def test_early_combo_probe_covers_known_preference(self):
        combo=next(c for c in self.run['candidates'] if c['arguments']['items'][0]['productCode']=='SET')
        self.assertTrue(any('香烤' in x['name'] for x in combo['contents']))
        b=fixture(NOW);b['request']['preferred']=[]
        plain=a.prepare(b)
        combo=next(c for c in plain['candidates'] if c['arguments']['items'][0]['productCode']=='SET')
        self.assertEqual(combo['arguments']['items'],[a.variants(plain['snapshot']['products']['SET'])[0]])

    def test_no_drinks_hidden_inside_combo(self):
        detail=self.s['products']['SET']['detail'];detail['rounds'][1]['choices'][0]['name']='可乐'
        detail['rounds'][1]['name']='饮料'
        item=a.variants(self.s['products']['SET'])[0]
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,[item])

    def test_one_unit_cannot_satisfy_two_required_groups(self):
        self.r['required']=[{'terms':['汉堡'],'codes':[],'quantity':1}]*2
        leaves=[{'code':'A','name':'经典鸡肉汉堡','labels':['汉堡'],'quantity':1}]
        self.assertFalse(a.demand_ok(leaves,self.r))
        leaves[0]['quantity']=2
        self.assertTrue(a.demand_ok(leaves,self.r))

    def test_missing_combo_round_fails(self):
        item=a.variants(self.s['products']['SET'])[0];item['roundList'].pop()
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,[item])

    def test_unknown_combo_choice_fails(self):
        item=a.variants(self.s['products']['SET'])[0];item['roundList'][0]['comboItemList'][0]['code']='NO'
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,[item])

    def test_negative_choice_limit_uses_round_limit(self):
        p=self.s['products']['SET']
        p['detail']['rounds'][0]['choices'][0]['maxQuantity']=-1
        item=a.variants(p)[0]
        self.assertTrue(a.candidate(self.s,self.r,[item]))
        item['roundList'][0]['comboItemList'][0]['quantity']=2
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,[item])

    def test_missing_details_not_assumed_single_item(self):
        self.s['products']['A']['detail']=None
        with self.assertRaises(a.Invalid):a.inspect_items(self.s,[{'productCode':'A','quantity':1}])

    def test_multiple_coupons_rejected(self):
        items=[{'productCode':'A','quantity':1,'couponId':'x','couponCode':'x'},{'productCode':'S','quantity':1,'couponId':'y','couponCode':'y'}]
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,items)

    def test_coupon_identity_and_product_required(self):
        items=[{'productCode':'A','quantity':1,'couponId':'invented','couponCode':'invented'},{'productCode':'S','quantity':1}]
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,items)

    def test_expired_coupon_not_generated(self):
        self.s['store_coupons'][0]['tradeDateTime']='2026-01-01 00:00:00-2026-01-02 23:59:59'
        self.assertTrue(all(c['coupon'] is None for c in a.generate(self.s,self.r)))

    def test_no_unsupported_parameters(self):
        items=[{'productCode':'A','quantity':1,'withOrder':{'cardId':'paid-membership'}},{'productCode':'S','quantity':1}]
        with self.assertRaises(a.Invalid):a.candidate(self.s,self.r,items)

    def test_allow_extras_changes_generated_baskets(self):
        original={c['fingerprint'] for c in self.run['candidates']}
        self.r['allow_extras']=True
        with_extras=a.generate(self.s,self.r)
        self.assertTrue(any(c['fingerprint'] not in original for c in with_extras))


class QuotesAndRevision(unittest.TestCase):
    def setUp(self):self.run=a.prepare(fixture(NOW))

    def attempt(self,response=None,error=None):
        task=a.reserve(self.run,NOW)
        status=a.record(self.run,task['candidate_id'],response or synthetic_quote(task['arguments']),error,task['fingerprint'],NOW)
        return task,status

    def test_price_only_from_response(self):
        task=a.reserve(self.run,NOW);response=synthetic_quote(task['arguments']);response['structuredContent']['data']['price']=1
        a.record(self.run,task['candidate_id'],response,fingerprint=task['fingerprint'],now=NOW)
        self.assertEqual(self.run['candidates'][0]['quote']['payable_cents'],1)

    def test_fingerprint_mismatch_not_accepted(self):
        task=a.reserve(self.run,NOW)
        with self.assertRaises(a.Invalid):a.record(self.run,task['candidate_id'],synthetic_quote(task['arguments']),fingerprint='wrong',now=NOW)

    def test_official_basket_mismatch_fails(self):
        task=a.reserve(self.run,NOW);r=synthetic_quote(task['arguments']);r['structuredContent']['data']['productList'][0]['quantity']+=1
        self.assertEqual(a.record(self.run,task['candidate_id'],r,fingerprint=task['fingerprint'],now=NOW),'failed')

    def test_missing_price_not_zero(self):
        task=a.reserve(self.run,NOW);r=synthetic_quote(task['arguments']);del r['structuredContent']['data']['price']
        self.assertEqual(a.record(self.run,task['candidate_id'],r,fingerprint=task['fingerprint'],now=NOW),'failed')

    def test_store_switch_invalidates_quote(self):
        task=a.reserve(self.run,NOW);self.run['snapshot']['store']['code']='777'
        self.assertEqual(a.record(self.run,task['candidate_id'],synthetic_quote(task['arguments']),fingerprint=task['fingerprint'],now=NOW),'failed')

    def test_partial_failure_keeps_previous_success(self):
        self.attempt();self.attempt(error='transport_failure')
        report=a.public_report(self.run,NOW)
        self.assertEqual(len(report['plans']),1);self.assertEqual(report['failures'],1)

    def test_no_automatic_retry(self):
        first,_=self.attempt(error='transport_failure');second=a.reserve(self.run,NOW)
        self.assertNotEqual(first['candidate_id'],second['candidate_id'])

    def test_inflight_cannot_be_reissued(self):
        a.reserve(self.run,NOW)
        with self.assertRaises(a.Invalid):a.reserve(self.run,NOW)

    def test_cap_counts_failures(self):
        self.run['attempts']=20
        with self.assertRaises(a.Invalid):a.reserve(self.run,NOW)

    def test_stale_snapshot_requires_refresh(self):
        with self.assertRaises(a.Invalid):a.reserve(self.run,a.instant(NOW)+timedelta(minutes=16))

    def test_revision_preserves_constraints_and_other_items(self):
        original=next(c for c in self.run['candidates'] if not c['coupon'] and {x['productCode'] for x in c['arguments']['items']}=={'A','S'})
        original['quote']={'payable_cents':1};original['status']='success'
        revised=a.revise(self.run,original['id'],[{'from_code':'S','to_code':'C'}],NOW)
        self.assertEqual(revised['request'],self.run['request'])
        self.assertEqual(revised['candidates'][0]['arguments']['items'],[{'productCode':'A','quantity':1},{'productCode':'C','quantity':1}])
        self.assertTrue(all(c['quote'] is None for c in revised['candidates']))

    def test_revision_cannot_break_exclusion(self):
        original=next(c for c in self.run['candidates'] if {x['productCode'] for x in c['arguments']['items']}=={'A','S'})
        with self.assertRaises(a.Invalid):a.revise(self.run,original['id'],[{'from_code':'S','to_code':'D'}],NOW)

    def test_combo_replacement_requires_real_choice(self):
        original=next(c for c in self.run['candidates'] if c['arguments']['items'][0]['productCode']=='SET')
        with self.assertRaises(a.Invalid):a.revise(self.run,original['id'],[{'from_code':'C','to_code':'D'}],NOW)


class AuditAndPresentation(unittest.TestCase):
    def setUp(self):self.run=demo_run(NOW)

    def test_same_contents_coupon_savings(self):
        report=a.public_report(self.run,NOW)
        with_coupon=[p for p in report['plans'] if p['coupon_name']]
        self.assertTrue(with_coupon)
        self.assertTrue(all(p['coupon_saving_cents']==510 for p in with_coupon))

    def test_changed_contents_not_coupon_saving(self):
        self.run['candidates']=[c for c in self.run['candidates'] if c['coupon'] or c['arguments']['items'][0]['productCode']=='SET']
        report=a.public_report(self.run,NOW)
        self.assertTrue(all(p['coupon_saving_cents'] is None for p in report['plans'] if p['coupon_name']))

    def test_coupon_name_not_used_as_identity(self):
        s=self.run['snapshot']['stock'][0];s['id']='different';s['code']='different'
        audit=a.public_report(self.run,NOW)['coupon_audit']
        self.assertEqual(audit[0]['state'],'当前门店适用性未确认')
        self.assertTrue(audit[0]['held'])
        self.assertIsNone(audit[0]['store_available'])
        self.assertFalse(audit[0]['basket_verified'])
        self.assertIsNone(audit[-1]['held'])
        self.assertTrue(audit[-1]['store_available'])

    def test_unavailable_stock_not_empty_success(self):
        b=fixture(NOW);del b['stock'];r=a.prepare(b)
        self.assertEqual(a.public_report(r,NOW)['stock_status'],'unavailable')

    def test_expiry_never_overrides_budget(self):
        report=a.public_report(self.run,NOW)
        self.assertEqual(a.recommend(report['plans'],100,NOW),[])

    def test_no_duplicate_contents_in_recommendations(self):
        plans=a.public_report(self.run,NOW)['plans'];chosen=a.recommend(plans,3000,NOW)
        self.assertLessEqual(len(chosen),3)
        self.assertEqual(len({p['plan']['contents_key'] for p in chosen}),len(chosen))

    def test_no_preference_label_without_match(self):
        plans=a.public_report(self.run,NOW)['plans']
        for p in plans:p['preference_score']=0
        chosen=a.recommend(plans,3000,NOW)
        self.assertFalse(any('更合口味' in p['labels'] for p in chosen))

    def test_coupon_comparison_expires_with_earlier_control(self):
        coupon=next(c for c in self.run['candidates'] if c['coupon'])
        control=next(c for c in self.run['candidates'] if not c['coupon'] and a.basket_key(c['arguments'])==a.basket_key(coupon['arguments']))
        control['quote']['quoted_at']=a.stamp(a.instant(NOW)-timedelta(minutes=10))
        p=next(p for p in a.public_report(self.run,NOW)['plans'] if p['id']==coupon['id'])
        self.assertEqual(p['coupon_comparison_expires_at'],a.stamp(a.instant(NOW)+timedelta(minutes=5)))

    def test_expired_quotes_kept_not_recommended(self):
        later=a.instant(NOW)+timedelta(minutes=16);report=a.public_report(self.run,later)
        self.assertTrue(report['plans']);self.assertTrue(all(not p['fresh'] for p in report['plans']))
        self.assertEqual(a.recommend(report['plans'],3000,later),[])
        self.assertTrue(any(c['verification_expires_at'] for c in report['coupon_audit']))

    def test_tampered_stored_quote_dropped(self):
        c=self.run['candidates'][0];c['arguments']['items'][0]['quantity']+=1
        report=a.public_report(self.run,NOW)
        self.assertNotIn(c['id'],[p['id'] for p in report['plans']])

    def test_public_projection_removes_coupon_credentials(self):
        blob=json.dumps(a.public_report(self.run,NOW))
        self.assertNotIn('SYNTHETIC-ID-ONLY',blob)
        self.assertNotIn('SYNTHETIC-CODE-NOT-FOR-USE',blob)
        for key in ['couponCode','couponId','Authorization','structuredContent']:
            self.assertNotIn('"'+key+'"',blob)

    def test_report_self_contained_and_script_safe(self):
        self.run['snapshot']['store']['name']='</script><img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.html';a.render(self.run,p,NOW);text=p.read_text()
            self.assertNotIn('</script><img',text)
            self.assertNotIn('__REPORT_',text)
            self.assertNotIn('<script src=',text)
            self.assertIn("connect-src 'none'",text)
            self.assertNotIn('SYNTHETIC-CODE-NOT-FOR-USE',text)

    def test_quote_cannot_live_past_coupon_expiry(self):
        c=next(c for c in self.run['candidates'] if c['coupon'])
        end=a.instant(NOW)+timedelta(minutes=2)
        c['coupon']['tradeDateTime']='2026-10-18 00:00:00-'+end.strftime('%Y-%m-%d %H:%M:%S')
        # Update authoritative coupon metadata too; contents and request stay the same.
        for coupon in self.run['snapshot']['store_coupons']:coupon['tradeDateTime']=c['coupon']['tradeDateTime']
        report=a.public_report(self.run,a.instant(NOW)+timedelta(minutes=3))
        expired=[p for p in report['plans'] if p['coupon_name']]
        self.assertTrue(expired);self.assertTrue(all(not p['fresh'] for p in expired))

    def test_saved_private_run_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'run.json';a.save_json(p,self.run)
            self.assertEqual(p.stat().st_mode & 0o777,0o600)

    def test_python_javascript_recommendation_parity(self):
        report=a.public_report(self.run,NOW)
        for budget in [0,1990,2090,2400,3000,10000]:
            js="const m=require(process.argv[1]);let d=JSON.parse(process.argv[2]);console.log(JSON.stringify(m.pickPlans(d.plans,+process.argv[3],Date.parse(process.argv[4])).map(x=>[x.plan.id,x.labels])));"
            p=subprocess.run(['node','-e',js,str(ROOT/'skills/mcd-meal-advisor/assets/report.js'),json.dumps(report),str(budget),NOW],capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(p.stdout),[[x['plan']['id'],x['labels']] for x in a.recommend(report['plans'],budget,NOW)])

    def test_expiry_ties_and_duplicate_order_match_browser(self):
        base=a.public_report(self.run,NOW)['plans'][0]
        plans=[]
        for ident,content,end in [('z','same','2026-10-21'),('b','other','2026-10-20'),('a','same','2026-10-21')]:
            p=copy.deepcopy(base);p.update(id=ident,contents_key=content,payable_cents=2000,
                preference_score=1,coupon_name='test',coupon_expiry=end)
            plans.append(p)
        js="const m=require(process.argv[1]);console.log(JSON.stringify(m.pickPlans(JSON.parse(process.argv[2]),3000,Date.parse(process.argv[3])).map(x=>[x.plan.id,x.labels])));"
        p=subprocess.run(['node','-e',js,str(ROOT/'skills/mcd-meal-advisor/assets/report.js'),json.dumps(plans),NOW],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(p.stdout),[[x['plan']['id'],x['labels']] for x in a.recommend(plans,3000,NOW)])
        self.assertEqual(a.recommend(plans,3000,NOW)[0]['plan']['id'],'b')


if __name__=='__main__':unittest.main()
