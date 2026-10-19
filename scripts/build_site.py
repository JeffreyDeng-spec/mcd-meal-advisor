#!/usr/bin/env python3
"""Build only synthetic public assets; never accept a live bundle or credentials."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/mcd-meal-advisor/scripts'))
from demo import demo_run
from advisor import public_report

ASSETS=('index.html','app.css','app.js','icon.svg','security.html','share.html','share.css','404.html')
MEDIA=('social-card.png','meal-advisor-demo.mp4','demo-captions.vtt')

def build(output):
    target=Path(output).resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError('output_must_be_empty')
    target.mkdir(parents=True,exist_ok=True)
    for name in ASSETS:shutil.copy2(ROOT/'site'/name,target/name)
    shutil.copy2(ROOT/'skills/mcd-meal-advisor/assets/report.js',target/'engine.js')
    data=public_report(demo_run('2026-10-19T12:00:00+08:00'),'2026-10-19T12:00:00+08:00')
    assert data['mode']=='demo'
    payload={'mode':'demo','generated_at':data['generated_at'],'plans':data['plans']}
    for p in payload['plans']:p.pop('request_text',None)
    encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (target/'data.js').write_text('window.MEAL_DEMO_DATA = '+encoded+';\n',encoding='utf-8')
    for name in MEDIA:
        source=ROOT/'site/public'/name
        if source.exists():shutil.copy2(source,target/name)
    (target/'.nojekyll').write_text('')
    (target/'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: https://jeffreydeng-spec.github.io/mcd-meal-advisor/sitemap.xml\n')
    (target/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://jeffreydeng-spec.github.io/mcd-meal-advisor/</loc></url></urlset>')
    return sorted(p.name for p in target.iterdir())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps({'public_assets':build(args.output)}))
