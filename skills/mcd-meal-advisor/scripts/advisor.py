#!/usr/bin/env python3
"""Deterministic, offline meal planning. Network and credentials stay in the host MCP client."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
from collections import Counter

TZ = timezone(timedelta(hours=8))
MAX_QUOTES = 20
TTL_SECONDS = 900
READ_TOOLS = frozenset({'now-time-info', 'query-nearby-stores', 'query-meals',
                        'query-meal-detail', 'query-my-coupons', 'query-store-coupons',
                        'calculate-price'})


class Invalid(ValueError):
    pass


def instant(value=None):
    if value is None:
        return datetime.now(TZ)
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except (ValueError, TypeError):
        raise Invalid('invalid_timestamp')


def stamp(value=None):
    return instant(value).isoformat(timespec='seconds')


def integer(value, minimum=0, maximum=100000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Invalid('invalid_integer')
    return value


def yuan(value):
    try:
        n = Decimal(str(value)) * 100
        if not n.is_finite() or n < 0 or n != n.to_integral_value():
            raise Invalid('invalid_money')
        return integer(int(n))
    except (InvalidOperation, ValueError):
        raise Invalid('invalid_money')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def envelope(response):
    """Prefer structuredContent; accept only an unambiguous successful JSON envelope."""
    if not isinstance(response, dict) or response.get('isError'):
        raise Invalid('mcp_tool_error')
    if 'structuredContent' in response:
        obj = response['structuredContent']
    elif 'content' in response:
        choices = []
        for part in response.get('content', []):
            if part.get('type') != 'text':
                continue
            text = part.get('text', '')
            decoder = json.JSONDecoder()
            for match in re.finditer(r'\{', text):
                try:
                    value, _ = decoder.raw_decode(text[match.start():])
                except ValueError:
                    continue
                if isinstance(value, dict) and 'data' in value and ('success' in value or 'code' in value):
                    if value not in choices:
                        choices.append(value)
        if len(choices) != 1:
            raise Invalid('ambiguous_mcp_response')
        obj = choices[0]
    else:
        obj = response
    if not isinstance(obj, dict) or obj.get('success') is False:
        raise Invalid('mcp_business_error')
    if not (obj.get('success') is True or obj.get('code') == 200):
        raise Invalid('unverified_mcp_response')
    if obj.get('code', 200) != 200 or 'data' not in obj:
        raise Invalid('mcp_business_error')
    return obj['data']


def text_list(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise Invalid('invalid_terms')
    return list(dict.fromkeys(x.strip() for x in value))


def requirement(raw):
    if not isinstance(raw, dict):
        raise Invalid('invalid_requirement')
    if raw.get('order_type', 1) != 1 or raw.get('be_type', 1) != 1 or raw.get('people', 1) != 1:
        raise Invalid('v1_pickup_one_person_only')
    groups = []
    for group in raw.get('required', []):
        terms = text_list(group.get('terms', []))
        codes = text_list(group.get('codes', []))
        if not terms and not codes:
            raise Invalid('empty_required_group')
        groups.append({'terms': terms, 'codes': codes,
                       'quantity': integer(group.get('quantity', 1), 1, 10)})
    if not groups or sum(g['quantity'] for g in groups) > 10:
        raise Invalid('confirm_at_least_one_requirement')
    if type(raw.get('allow_extras', False)) is not bool:
        raise Invalid('invalid_allow_extras')
    result = {'budget_cents': integer(raw.get('budget_cents'), 0, 100000),
              'required': groups, 'excluded': text_list(raw.get('excluded', [])),
              'preferred': text_list(raw.get('preferred', [])),
              'pinned_codes': text_list(raw.get('pinned_codes', [])),
              'allow_extras': raw.get('allow_extras', False)}
    if 'need_tableware' in raw:
        if type(raw['need_tableware']) is not bool:
            raise Invalid('invalid_tableware')
        result['need_tableware'] = raw['need_tableware']
    return result


def normalize(bundle):
    request = requirement(bundle['request'])
    store = bundle['store']
    if not re.fullmatch(r'\d+', str(store.get('storeCode', ''))):
        raise Invalid('invalid_store')
    if store.get('businessStatus') is False:
        raise Invalid('store_closed')
    data = envelope(bundle['menu'])
    categories = {}
    for category in data.get('categories', []):
        for item in category.get('meals', []):
            code = str(item.get('code', ''))
            categories.setdefault(code, []).append(category.get('name', ''))
    products = {}
    details = bundle.get('details', {})
    for code, item in data.get('meals', {}).items():
        if not isinstance(item, dict) or not item.get('name'):
            continue
        # Conditional membership prices are not unconditional candidate prices.
        try:
            estimate = yuan(item.get('originalPrice') if item.get('withOrder') else item.get('currentPrice'))
        except Invalid:
            estimate = 10000000
        products[str(code)] = {'code': str(code), 'name': item['name'],
                               'labels': categories.get(str(code), []), 'estimate_cents': estimate,
                               'detail': None}
    for code, response in details.items():
        detail = envelope(response)
        if code in products:
            if str(detail.get('code', code)) != str(code):
                raise Invalid('detail_product_mismatch')
            products[code]['detail'] = detail
    store_coupons = envelope(bundle['store_coupons']) if 'store_coupons' in bundle else []
    stock_data = envelope(bundle['stock']) if 'stock' in bundle else {'coupons': []}
    stock = stock_data.get('coupons', [])
    return {'store': {'code': str(store['storeCode']), 'name': store.get('storeName', ''),
                      'address': store.get('address', '')},
            'captured_at': stamp(bundle.get('captured_at')),
            'products': products, 'store_coupons': store_coupons, 'stock': stock,
            'stock_complete': 'stock' in bundle and stock_data.get('totalPages', 1) <= stock_data.get('currentPage', 1),
            'stock_status': 'loaded' if 'stock' in bundle else 'unavailable',
            'store_coupons_status': 'loaded' if 'store_coupons' in bundle else 'unavailable'}, request


def matches(leaf, group):
    if leaf['code'] in group.get('codes', []):
        return True
    haystack = leaf['name'] + ' ' + ' '.join(leaf.get('labels', []))
    return any(term.casefold() in haystack.casefold() for term in group.get('terms', []))


def exclusions(leaves, request):
    return any(matches(leaf, {'terms': request['excluded']}) for leaf in leaves)


def demand_ok(leaves, request):
    """Assign physical units to requirements: one burger cannot count as two units."""
    units = [leaf for leaf in leaves for _ in range(integer(leaf['quantity'], 1, 20))]
    if len(units) > 30 or exclusions(leaves, request):
        return False
    if any(not any(leaf['code'] == code for leaf in leaves) for code in request['pinned_codes']):
        return False
    needs = [g for g in request['required'] for _ in range(g['quantity'])]
    choices = sorted([[i for i, unit in enumerate(units) if matches(unit, g)] for g in needs], key=len)

    def assign(index, used):
        if index == len(choices):
            return True
        return any(i not in used and assign(index + 1, used | {i}) for i in choices[index])

    return assign(0, set())


def contents_key(leaves):
    counts = Counter()
    for leaf in leaves:
        counts[leaf['code']] += leaf['quantity']
    return digest(sorted(counts.items()))


def basket_key(arguments):
    """Isolate coupon effect using exactly the same purchase structure, not another bundle."""
    plain = copy.deepcopy(arguments)
    for item in plain['items']:
        item.pop('couponId', None)
        item.pop('couponCode', None)
    return digest(plain)


def inspect_items(snapshot, items):
    leaves = []
    if not isinstance(items, list) or not items:
        raise Invalid('empty_items')
    for item in items:
        if set(item) - {'productCode', 'quantity', 'roundList', 'couponId', 'couponCode'}:
            raise Invalid('unsupported_item_fields')
        code = str(item.get('productCode', ''))
        product = snapshot['products'].get(code)
        if not product or product['detail'] is None:
            raise Invalid('missing_product_detail')
        count = integer(item.get('quantity'), 1, 10)
        detail = product['detail']
        rounds = detail.get('rounds', [])
        selected = item.get('roundList', [])
        if rounds:
            if len(selected) != len(rounds) or len({str(r.get('round')) for r in selected}) != len(selected):
                raise Invalid('incomplete_combo')
            round_map = {str(r['round']): r.get('comboItemList', []) for r in selected}
            if set(round_map) != {str(r['id']) for r in rounds}:
                raise Invalid('unknown_combo_round')
            for r in rounds:
                picked = round_map[str(r['id'])]
                options = {str(c['code']): c for c in r.get('choices', [])}
                if len({str(c.get('code')) for c in picked}) != len(picked):
                    raise Invalid('duplicate_combo_choice')
                total = 0
                for c in picked:
                    if set(c) - {'code', 'quantity'} or str(c.get('code')) not in options:
                        raise Invalid('invalid_combo_choice')
                    n = integer(c.get('quantity'), 1, 10)
                    choice = options[str(c['code'])]
                    limit = choice.get('maxQuantity', -1)
                    # Real MCP returns -1 for no per-choice limit; the round's
                    # min/max below still bounds the total selection.
                    if type(limit) is int and limit >= 0 and n > limit:
                        raise Invalid('combo_choice_quantity')
                    total += n
                    leaf_product = snapshot['products'].get(str(c['code']), {})
                    leaves.append({'code': str(c['code']), 'name': choice['name'],
                                   'quantity': n * count,
                                   'labels': list(dict.fromkeys(leaf_product.get('labels', []) + [r.get('name', '')]))})
                if not r.get('minQuantity', 1) <= total <= r.get('maxQuantity', 1):
                    raise Invalid('combo_round_quantity')
        else:
            if selected:
                raise Invalid('rounds_on_single_product')
            leaves.append({'code': code, 'name': detail.get('name', product['name']),
                           'quantity': count, 'labels': product['labels']})
    return leaves


def coupon_valid(coupon, now):
    value = coupon.get('tradeDateTime', '')
    dates = re.findall(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value)
    if len(dates) != 2:
        return False
    return instant(dates[0]) <= instant(now) <= instant(dates[1])


def candidate(snapshot, request, items, now=None):
    items = copy.deepcopy(items)
    leaves = inspect_items(snapshot, items)
    if not demand_ok(leaves, request):
        raise Invalid('requirements_not_met')
    attached = [i for i in items if i.get('couponId') or i.get('couponCode')]
    if len(attached) > 1:
        raise Invalid('single_coupon_only')
    coupon = None
    if attached:
        item = attached[0]
        coupon = next((c for c in snapshot['store_coupons']
                       if c.get('couponId') == item.get('couponId') and c.get('couponCode') == item.get('couponCode')
                       and item['productCode'] in [str(p.get('productCode')) for p in c.get('products', [])]), None)
        if not coupon or not coupon_valid(coupon, now or snapshot['captured_at']):
            raise Invalid('coupon_not_verified_for_store')
    args = {'storeCode': snapshot['store']['code'], 'orderType': 1, 'beType': 1, 'items': items}
    if 'need_tableware' in request:
        args['needTableware'] = request['need_tableware']
    key = digest(args)
    return {'id': key[:16], 'fingerprint': key, 'arguments': args, 'contents': leaves,
            'contents_key': contents_key(leaves), 'coupon': copy.deepcopy(coupon),
            'status': 'pending', 'quote': None}


def variants(product):
    detail = product['detail']
    if detail is None:
        return []
    rounds = detail.get('rounds', [])
    if not rounds:
        return [{'productCode': product['code'], 'quantity': 1}]
    base = []
    for r in rounds:
        chosen = [{'code': str(c['code']), 'quantity': c.get('quantity') or 1}
                  for c in r.get('choices', []) if c.get('isDefault') == 1]
        if not chosen:
            return []
        base.append({'round': str(r['id']), 'comboItemList': chosen})
    options = [base]
    # Each variant changes one round; no combinatorial/cartesian explosion.
    for index, r in enumerate(rounds):
        if r.get('minQuantity', 1) != 1 or r.get('maxQuantity', 1) != 1:
            continue
        for choice in r.get('choices', []):
            if choice.get('isDefault') == 1:
                continue
            v = copy.deepcopy(base)
            v[index]['comboItemList'] = [{'code': str(choice['code']), 'quantity': 1}]
            options.append(v)
    return [{'productCode': product['code'], 'quantity': 1, 'roundList': v} for v in options[:16]]


def generate(snapshot, request):
    products = sorted(snapshot['products'].values(), key=lambda p: (p['estimate_cents'], p['code']))
    bases = []
    for p in products:
        for item in variants(p):
            try:
                candidate(snapshot, request, [item])
                bases.append([item])
            except Invalid:
                pass
    # Construct single-item combinations per confirmed requirement group.
    pools = []
    for group in request['required']:
        singles = [p for p in products if p['detail'] is not None and not p['detail'].get('rounds')
                   and matches({'code': p['code'], 'name': p['detail'].get('name', p['name']), 'labels': p['labels']}, group)]
        pools.extend([singles[:5]] * group['quantity'])
    if all(pools):
        for chosen in itertools.islice(itertools.product(*pools), 150):
            counts = Counter(p['code'] for p in chosen)
            bases.append([{'productCode': code, 'quantity': n} for code, n in sorted(counts.items())])
    valid = {}
    if request['allow_extras']:
        extras = [p for p in products if p['detail'] is not None and not p['detail'].get('rounds')]
        bases += [copy.deepcopy(items) + [{'productCode': p['code'], 'quantity': 1}]
                  for items in bases[:20] for p in extras[:5]]
    for items in bases:
        try:
            c = candidate(snapshot, request, items)
            valid[c['fingerprint']] = c
        except Invalid:
            pass
    # Cheap estimates prioritize probes, never become displayed quotes.
    def estimate(c):
        return sum(snapshot['products'][i['productCode']]['estimate_cents'] * i['quantity'] for i in c['arguments']['items'])
    def preference(c):
        return sum(x['quantity'] for x in c['contents'] if matches(x, {'terms': request['preferred']}))
    # Stable ties preserve the official default variant; known preferences get
    # an early probe instead of being buried behind arbitrary hash order.
    ordered = sorted(valid.values(), key=lambda c: (estimate(c), -preference(c)))
    # Spread the limited probes across different purchase structures before trying
    # many variants of one cheap-looking combo. An estimate is not a quote.
    families = {}
    for c in ordered:
        family = tuple(sorted((i['productCode'], i['quantity']) for i in c['arguments']['items']))
        families.setdefault(family, []).append(c)
    ordered = []
    for index in range(max((len(v) for v in families.values()), default=0)):
        ordered.extend(v[index] for v in families.values() if index < len(v))
    tasks = []
    seen = set()
    for base in ordered:
        proposed = [base]
        for coupon in snapshot['store_coupons']:
            if not coupon_valid(coupon, snapshot['captured_at']):
                continue
            eligible = {str(p.get('productCode')) for p in coupon.get('products', [])}
            for idx, item in enumerate(base['arguments']['items']):
                if item['productCode'] in eligible and coupon.get('couponId') and coupon.get('couponCode'):
                    items = copy.deepcopy(base['arguments']['items'])
                    items[idx].update(couponId=coupon['couponId'], couponCode=coupon['couponCode'])
                    proposed.append(candidate(snapshot, request, items))
        for c in proposed:
            if c['fingerprint'] not in seen and len(tasks) < MAX_QUOTES:
                tasks.append(c)
                seen.add(c['fingerprint'])
    return tasks


def prepare(bundle):
    snapshot, request = normalize(bundle)
    mode = bundle.get('mode', 'live')
    if mode not in ('live', 'demo'):
        raise Invalid('invalid_mode')
    candidates = generate(snapshot, request)
    run = {'schema_version': 1, 'mode': mode, 'request': request, 'snapshot': snapshot,
           'candidates': candidates, 'attempts': 0, 'created_at': stamp(), 'revision': 0}
    run['run_id'] = digest({'request': request, 'snapshot': snapshot['captured_at'], 'store': snapshot['store']})[:20]
    return run


def reserve(run, now=None):
    if (instant(now) - instant(run['snapshot']['captured_at'])).total_seconds() > TTL_SECONDS:
        raise Invalid('refresh_menu_snapshot_before_quoting')
    if any(c['status'] == 'inflight' for c in run['candidates']):
        raise Invalid('record_previous_attempt_first')
    c = next((c for c in run['candidates'] if c['status'] == 'pending'), None)
    if c is None:
        return None
    if run['attempts'] >= MAX_QUOTES:
        raise Invalid('quote_budget_exhausted')
    checked = candidate(run['snapshot'], run['request'], c['arguments']['items'], now)
    if checked['fingerprint'] != c['fingerprint'] or checked['arguments'] != c['arguments']:
        raise Invalid('candidate_changed')
    c['status'] = 'inflight'
    c['started_at'] = stamp(now)
    run['attempts'] += 1
    return {'candidate_id': c['id'], 'fingerprint': c['fingerprint'],
            'tool': 'calculate-price', 'arguments': copy.deepcopy(c['arguments'])}


def record(run, candidate_id, response=None, error=None, fingerprint=None, now=None):
    c = next((c for c in run['candidates'] if c['id'] == candidate_id), None)
    if c is None or c['status'] != 'inflight':
        raise Invalid('candidate_not_inflight')
    if fingerprint != c['fingerprint'] or digest(c['arguments']) != c['fingerprint']:
        raise Invalid('response_request_mismatch')
    try:
        checked = candidate(run['snapshot'], run['request'], c['arguments']['items'], now)
        if checked['arguments'] != c['arguments']:
            raise Invalid('store_or_request_changed')
        if error:
            raise Invalid('transport_failure')
        data = envelope(response)
        payable = integer(data.get('price'))
        if not isinstance(data.get('productList'), list) or not data['productList']:
            raise Invalid('missing_official_product_list')
        actual = Counter()
        for line in data['productList']:
            actual[str(line.get('productCode', ''))] += integer(line.get('quantity'), 1, 30)
        expected = Counter()
        for line in c['arguments']['items']:
            expected[line['productCode']] += line['quantity']
        if actual != expected:
            raise Invalid('official_basket_mismatch')
        c['quote'] = {'payable_cents': payable, 'quoted_at': stamp(now),
                      'fingerprint': c['fingerprint'], 'source': 'synthetic' if run['mode'] == 'demo' else 'mcp',
                      'discount_cents': integer(data.get('discount', 0))}
        c['status'] = 'success'
    except Invalid as exc:
        c['status'] = 'failed'
        c['error'] = str(exc)
        c['quote'] = None
    return c['status']


def revise(run, candidate_id, replacements, now=None):
    original = next((c for c in run['candidates'] if c['id'] == candidate_id), None)
    if not original or not replacements:
        raise Invalid('missing_revision')
    items = copy.deepcopy(original['arguments']['items'])
    for item in items:
        item.pop('couponId', None)
        item.pop('couponCode', None)
    for change in replacements:
        old, new = str(change['from_code']), str(change['to_code'])
        hits = []
        for i, item in enumerate(items):
            for r in item.get('roundList', []):
                for selected in r['comboItemList']:
                    if selected['code'] == old:
                        hits.append(selected)
            if item['productCode'] == old and not item.get('roundList'):
                hits.append(item)
        if len(hits) != 1:
            raise Invalid('ambiguous_replacement')
        hit = hits[0]
        hit['productCode' if 'productCode' in hit else 'code'] = new
    c = candidate(run['snapshot'], run['request'], items, now)
    result = copy.deepcopy(run)
    result['revision'] += 1
    result['parent_run_id'] = run['run_id']
    result['run_id'] = digest({'parent': run['run_id'], 'candidate': c['fingerprint'], 'revision': result['revision']})[:20]
    result['attempts'] = 0
    result['candidates'] = [c]
    # Probe the same revised basket with eligible coupons, preserving its contents.
    for coupon in result['snapshot']['store_coupons']:
        for i, item in enumerate(items):
            if item['productCode'] in {str(p.get('productCode')) for p in coupon.get('products', [])}:
                test = copy.deepcopy(items)
                test[i].update(couponId=coupon.get('couponId'), couponCode=coupon.get('couponCode'))
                try:
                    with_coupon = candidate(result['snapshot'], result['request'], test, now)
                    if with_coupon['fingerprint'] not in {x['fingerprint'] for x in result['candidates']}:
                        result['candidates'].append(with_coupon)
                except Invalid:
                    pass
    result['candidates'] = result['candidates'][:MAX_QUOTES]
    return result


def fresh(quote, now):
    age = (instant(now) - instant(quote['quoted_at'])).total_seconds()
    return 0 <= age <= TTL_SECONDS


def public_report(run, now=None):
    now = stamp(now)
    valid = []
    for c in run['candidates']:
        q = c.get('quote')
        if c['status'] != 'success' or not q:
            continue
        if q['fingerprint'] != digest(c['arguments']):
            continue
        try:
            checked = candidate(run['snapshot'], run['request'], c['arguments']['items'], q['quoted_at'])
        except Invalid:
            continue
        if checked['contents'] != c['contents'] or checked['fingerprint'] != c['fingerprint']:
            continue
        verified = copy.deepcopy(c)
        verified['coupon'] = checked['coupon']
        valid.append(verified)
    baselines = {}
    for c in valid:
        if c['coupon'] is None:
            key = basket_key(c['arguments'])
            if key not in baselines or c['quote']['payable_cents'] < baselines[key]['quote']['payable_cents']:
                baselines[key] = c
    plans = []
    for c in valid:
        q = c['quote']
        b = baselines.get(basket_key(c['arguments']))
        comparable = b is not None and fresh(b['quote'], now) and fresh(q, now)
        saving = b['quote']['payable_cents'] - q['payable_cents'] if c['coupon'] and comparable else None
        score = sum(leaf['quantity'] for leaf in c['contents'] if matches(leaf, {'terms': run['request']['preferred']}))
        expiry = None
        if c['coupon']:
            dates = re.findall(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', c['coupon'].get('tradeDateTime', ''))
            expiry = stamp(dates[-1]) if len(dates) == 2 else None
        expires = instant(q['quoted_at']) + timedelta(seconds=TTL_SECONDS)
        if expiry:
            expires = min(expires, instant(expiry))
        plans.append({'id': c['id'], 'name': ' + '.join(leaf['name'] + ' ×' + str(leaf['quantity']) for leaf in c['contents']),
                      'items': [{'name': x['name'], 'quantity': x['quantity']} for x in c['contents']],
                      'contents_key': c['contents_key'], 'payable_cents': q['payable_cents'],
                      'quoted_at': q['quoted_at'], 'expires_at': stamp(expires),
                      'fresh': fresh(q, now) and instant(now) <= expires, 'preference_score': score,
                      'coupon_name': c['coupon'].get('title') if c['coupon'] else None,
                      'coupon_expiry': expiry, 'coupon_saving_cents': saving,
                      'coupon_comparison_expires_at': stamp(min(expires, instant(b['quote']['quoted_at']) + timedelta(seconds=TTL_SECONDS))) if saving is not None else None,
                      'request_text': '使用麦麦点餐参谋，基于本轮 ' + run['run_id'] + ' 的方案 ' + c['id'] +
                                      ' 修改餐品。保留预算和原有要求，请先问我具体换什么，再对完整餐单重新核价。'})
    audits = []
    available = run['snapshot']['store_coupons']
    # No fuzzy/name joins: match only actual coupon IDs/codes.
    for stock in run['snapshot']['stock']:
        sid, scode = stock.get('id'), stock.get('code')
        linked = [c for c in available if (sid and c.get('couponId') == sid) or (scode and c.get('couponCode') == scode)]
        matched = [p for c in valid for p in plans if p['id'] == c['id'] and c['coupon'] and
                   any(c['coupon'].get('couponId') == a.get('couponId') and c['coupon'].get('couponCode') == a.get('couponCode') for a in linked)]
        known = [p['coupon_saving_cents'] for p in matched if p['coupon_saving_cents'] is not None and p['fresh']]
        verified_until = min((p['coupon_comparison_expires_at'] or p['expires_at'] for p in matched), default=None)
        end = stock.get('tradeEndDateTime') or stock.get('tradeEndDate')
        end_at = None
        if end:
            try:
                end_at = stamp(str(end) + 'T23:59:59' if len(str(end)) == 10 else end)
            except Invalid:
                pass
        state = '本次适用' if matched else ('当前门店可用，尚未验证本餐单' if linked else '当前门店适用性未确认')
        if end_at and instant(end_at) < instant(now):
            state = '已过期'
        elif stock.get('enable') == 0:
            state = '账户当前不可用'
        audits.append({'name': stock.get('title', '未命名优惠券'), 'state': state,
                       'held': True, 'store_available': True if linked else None, 'basket_verified': bool(matched),
                       'expires_at': end_at, 'restrictions': stock.get('datetimeText', ''),
                       'saving_cents': max(known) if known else None, 'verification_expires_at': verified_until})
    # Store-only coupons may not be present in the paginated asset inventory.
    known_ids = {s.get('id') for s in run['snapshot']['stock'] if s.get('id')}
    known_codes = {s.get('code') for s in run['snapshot']['stock'] if s.get('code')}
    for c in available:
        if c.get('couponId') in known_ids or c.get('couponCode') in known_codes:
            continue
        ps = [p for x in valid for p in plans if p['id'] == x['id'] and x['coupon'] == c]
        savings = [p['coupon_saving_cents'] for p in ps if p['coupon_saving_cents'] is not None and p['fresh']]
        audits.append({'name': c.get('title', '门店优惠券'), 'state': '本次适用' if ps else '当前门店可用，尚未验证本餐单',
                       'held': None, 'store_available': True, 'basket_verified': bool(ps),
                       'expires_at': None, 'restrictions': c.get('tradeDateTime', ''),
                       'saving_cents': max(savings) if savings else None,
                       'verification_expires_at': min((p['coupon_comparison_expires_at'] or p['expires_at'] for p in ps), default=None)})
    return {'schema_version': 1, 'run_id': run['run_id'], 'mode': run['mode'],
            'generated_at': now, 'store': run['snapshot']['store'],
            'request': run['request'], 'plans': plans, 'coupon_audit': audits,
            'stock_complete': run['snapshot']['stock_complete'], 'stock_status': run['snapshot'].get('stock_status', 'loaded'),
            'attempts': run['attempts'],
            'failures': sum(c['status'] == 'failed' for c in run['candidates']),
            'pending': sum(c['status'] in ('pending', 'inflight') for c in run['candidates'])}


def recommend(plans, budget_cents, now=None):
    grouped = {}
    for p in plans:
        if p['payable_cents'] > budget_cents or not instant(p['quoted_at']) <= instant(now) <= instant(p['expires_at']):
            continue
        old = grouped.get(p['contents_key'])
        if old is None or (p['payable_cents'], p['coupon_expiry'] or '9999', p['id']) < (old['payable_cents'], old['coupon_expiry'] or '9999', old['id']):
            grouped[p['contents_key']] = p
    candidates = list(grouped.values())
    selected = {}
    def add(pool, label, key):
        if not pool:
            return
        plan = sorted(pool, key=key)[0]
        content = plan['contents_key']
        if content not in selected:
            selected[content] = {'plan': plan, 'labels': []}
        selected[content]['labels'].append(label)
    add(candidates, '最低实付', lambda p: (p['payable_cents'], -p['preference_score'], p['coupon_expiry'] or '9999', p['id']))
    add([p for p in candidates if p['preference_score'] > 0], '更合口味', lambda p: (-p['preference_score'], p['payable_cents'], p['coupon_expiry'] or '9999', p['id']))
    add([p for p in candidates if p['coupon_name']], '用券参考', lambda p: (p['payable_cents'], p['coupon_expiry'] or '9999', p['id']))
    return list(selected.values())


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(p))
    p.chmod(0o600)


def render(run, output, now=None):
    payload = public_report(run, now)
    template = (Path(__file__).resolve().parent.parent / 'assets/report.html').read_text(encoding='utf-8')
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    script = (Path(__file__).resolve().parent.parent / 'assets/report.js').read_text(encoding='utf-8')
    page = template.replace('__REPORT_JS__', script).replace('__REPORT_DATA__', data)
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding='utf-8')
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description='麦麦点餐参谋：本地计算与报告，不联网、不读凭证')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--input', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('next'); p.add_argument('--run', required=True)
    p = sub.add_parser('record'); p.add_argument('--run', required=True); p.add_argument('--candidate', required=True); p.add_argument('--fingerprint', required=True)
    p.add_argument('--response'); p.add_argument('--error', choices=['transport_failure'])
    p = sub.add_parser('report'); p.add_argument('--run', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('revise'); p.add_argument('--run', required=True); p.add_argument('--candidate', required=True); p.add_argument('--patch', required=True); p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            run = prepare(read_json(args.input)); save_json(args.output, run)
            result = {'run_id': run['run_id'], 'candidates': len(run['candidates']), 'max_quotes': MAX_QUOTES}
        elif args.command == 'next':
            run = read_json(args.run); result = reserve(run); save_json(args.run, run)
        elif args.command == 'record':
            if bool(args.response) == bool(args.error):
                raise Invalid('provide_response_or_error')
            run = read_json(args.run)
            status = record(run, args.candidate, read_json(args.response) if args.response else None,
                            args.error, args.fingerprint)
            save_json(args.run, run); result = {'candidate_id': args.candidate, 'status': status}
        elif args.command == 'revise':
            result_run = revise(read_json(args.run), args.candidate, read_json(args.patch)['replacements'])
            save_json(args.output, result_run); result = {'run_id': result_run['run_id'], 'needs_requote': True}
        else:
            data = render(read_json(args.run), args.output)
            result = {'report': str(Path(args.output).resolve()), 'valid_quotes': len(data['plans']),
                      'recommended': len(recommend(data['plans'], data['request']['budget_cents']))}
        print(json.dumps({'ok': True, 'data': result}, ensure_ascii=False))
        return 0
    except (Invalid, KeyError, TypeError, ValueError, OSError) as exc:
        code = str(exc) if isinstance(exc, Invalid) else 'invalid_input_or_file'
        print(json.dumps({'ok': False, 'error': code}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
