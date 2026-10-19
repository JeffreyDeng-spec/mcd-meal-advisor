#!/usr/bin/env python3
"""Offline, synthetic examples only. No credentials or network access."""
import argparse
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from advisor import instant, stamp, prepare, reserve, record, render, save_json


def fixture(now=None):
    now = instant(now)
    end = (now + timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
    start = (now - timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
    products = {
        'A': {'name': '经典鸡肉汉堡', 'currentPrice': '17.00'},
        'B': {'name': '香烤鸡肉汉堡', 'currentPrice': '20.00'},
        'S': {'name': '小份薯条', 'currentPrice': '9.00'},
        'C': {'name': '小份玉米杯', 'currentPrice': '7.00'},
        'D': {'name': '可乐', 'currentPrice': '8.00'},
        'SET': {'name': '鸡肉二件组合', 'currentPrice': '19.90'},
    }
    details = {code: {'success': True, 'code': 200, 'data': {'code': code, 'name': p['name'], 'rounds': []}}
               for code, p in products.items()}
    details['SET']['data']['rounds'] = [
        {'id': 1, 'name': '选择汉堡', 'minQuantity': 1, 'maxQuantity': 1,
         'choices': [{'code': 'A', 'name': products['A']['name'], 'isDefault': 1, 'quantity': 1, 'diffPrice': '+ ¥0', 'maxQuantity': 1},
                     {'code': 'B', 'name': products['B']['name'], 'isDefault': 0, 'quantity': 0, 'diffPrice': '+ ¥4.1', 'maxQuantity': 1}]},
        {'id': 2, 'name': '选择小食', 'minQuantity': 1, 'maxQuantity': 1,
         'choices': [{'code': 'C', 'name': products['C']['name'], 'isDefault': 1, 'quantity': 1, 'diffPrice': '+ ¥0', 'maxQuantity': 1},
                     {'code': 'S', 'name': products['S']['name'], 'isDefault': 0, 'quantity': 0, 'diffPrice': '+ ¥3', 'maxQuantity': 1}]},
    ]
    coupon = {'couponId': 'SYNTHETIC-ID-ONLY', 'couponCode': 'SYNTHETIC-CODE-NOT-FOR-USE',
              'title': '示例·经典鸡肉汉堡优惠', 'products': [{'productCode': 'A'}],
              'tradeDateTime': start + '-' + end}
    return {'mode': 'demo', 'captured_at': stamp(now),
            'store': {'storeCode': '100001', 'storeName': '演示门店 · 合成数据', 'address': '示例商圈，不是真实餐厅', 'businessStatus': True},
            'request': {'budget_cents': 3000, 'required': [{'terms': ['汉堡'], 'quantity': 1}, {'terms': ['小食'], 'quantity': 1}],
                        'excluded': ['饮料'], 'preferred': ['香烤'], 'allow_extras': False},
            'menu': {'success': True, 'code': 200, 'data': {'meals': products, 'categories': [
                {'name': '汉堡', 'meals': [{'code': 'A'}, {'code': 'B'}]},
                {'name': '小食', 'meals': [{'code': 'S'}, {'code': 'C'}]},
                {'name': '饮料', 'meals': [{'code': 'D'}]}]}},
            'details': details, 'store_coupons': {'success': True, 'code': 200, 'data': [coupon]},
            'stock': {'success': True, 'code': 200, 'data': {'coupons': [
                {'id': coupon['couponId'], 'code': coupon['couponCode'], 'title': coupon['title'],
                 'tradeEndDateTime': end, 'datetimeText': '示例限制：到店可用，以本轮合成报价演示', 'enable': 1}],
                'currentPage': 1, 'totalPages': 1}}}


def synthetic_quote(arguments):
    prices = {'A': 1700, 'B': 2000, 'S': 900, 'C': 700, 'D': 800}
    total = 0
    for item in arguments['items']:
        if item['productCode'] == 'SET':
            amount = 1990
            for r in item['roundList']:
                for p in r['comboItemList']:
                    if p['code'] == 'B': amount += 410
                    if p['code'] == 'S': amount += 300
        else:
            amount = prices[item['productCode']]
        if item.get('couponId'):
            amount -= 510
        total += amount * item['quantity']
    return {'structuredContent': {'success': True, 'code': 200, 'data': {
        'price': total, 'discount': 0,
        'productList': [{'productCode': x['productCode'], 'quantity': x['quantity']} for x in arguments['items']]}}, 'isError': False}


def demo_run(now=None):
    run = prepare(fixture(now))
    while True:
        task = reserve(run, now)
        if task is None: break
        record(run, task['candidate_id'], synthetic_quote(task['arguments']), fingerprint=task['fingerprint'], now=now)
    return run


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', default=str(Path.cwd()/'.local/meal-advisor-demo.html')); p.add_argument('--run-output')
    args = p.parse_args(); run = demo_run(); data = render(run, args.output)
    if args.run_output: save_json(args.run_output, run)
    print(json.dumps({'mode': 'synthetic_demo', 'report': str(Path(args.output).resolve()), 'quotes': len(data['plans'])}, ensure_ascii=False))


if __name__ == '__main__': main()
