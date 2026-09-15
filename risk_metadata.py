"""Read explicitly published RR ratings; never infer a rating from fund type."""
import re
import subprocess
import requests
from lxml import html
from fund_analysis import moneydj_fund_id, moneydj_fund_route


def parse_risk(text):
    match=re.search(r'風險(?:報酬)?等級\s*[：:]?\s*(RR[1-5])\b',text,re.I)
    return match[1].upper() if match else '未確認'


def load_risk(url):
    code=moneydj_fund_id(url)
    if not code: return '未確認',''
    if moneydj_fund_route(url) == 'wr':
        target='https://www.moneydj.com/funddj/yp/yp011000.djhtm?a='+code.split('-')[0]
    else:
        target='https://tcbbankfund.moneydj.com/w/wb/wb01.djhtm?a='+code
    try:
        r=requests.get(target,timeout=15);r.raise_for_status();raw=r.content
    except requests.exceptions.SSLError:
        # System curl uses its own certificate trust store, with verification on.
        raw=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','20',target],check=True,capture_output=True).stdout
    root=html.fromstring(raw)
    text=' '.join(root.itertext())
    return parse_risk(text),target
