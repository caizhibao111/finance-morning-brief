import glob
import json
import os
import time
from datetime import datetime

import requests


WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WECHAT_WEBHOOK_URL = os.environ.get('WECHAT_WEBHOOK_URL', '')
GITHUB_PAGES_URL = os.environ.get('GITHUB_PAGES_URL', '')


def resolve_brief_filename() -> str:
    """Return the generated brief filename, even if summary.json is missing."""
    if os.path.exists('summary.json'):
        with open('summary.json', 'r', encoding='utf-8') as f:
            summary = json.load(f)
        filename = summary.get('filename')
        if filename:
            return filename

    today_file = f"docs/brief-{datetime.now().strftime('%Y%m%d')}.html"
    if os.path.exists(today_file):
        return os.path.basename(today_file)

    brief_files = sorted(glob.glob('docs/brief-*.html'), reverse=True)
    if brief_files:
        return os.path.basename(brief_files[0])

    if os.path.exists('docs/index.html'):
        return 'index.html'

    raise FileNotFoundError('未找到 summary.json，也未找到 docs 下的早报 HTML 文件')


def main():
    print('等待GitHub Pages部署...')
    time.sleep(60)

    filename = resolve_brief_filename()

    today = datetime.now()
    weekday_cn = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'][today.weekday()]
    url = f"{GITHUB_PAGES_URL.rstrip('/')}/{filename}"
    title = f'财经早报 {today.strftime("%m月%d日")}'
    content = f'财经早报 · {today.strftime("%m月%d日")}（{weekday_cn}）已更新，点击查看完整早报'

    if WECHAT_WEBHOOK_URL:
        payload = {
            'msgtype': 'markdown',
            'markdown': {
                'content': f'## {title}\n\n{content}\n\n[查看完整早报]({url})'
            }
        }
        r = requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        if result.get('errcode') == 0:
            print('企业微信群机器人推送成功')
            return
        raise Exception(f"企业微信推送失败: {result}")

    if not WXPUSHER_TOKEN:
        raise ValueError('未配置 WECHAT_WEBHOOK_URL 或 WXPUSHER_TOKEN')

    payload = {
        'appToken': WXPUSHER_TOKEN,
        'content': content,
        'summary': title,
        'contentType': 1,
        'topicIds': [],
        'url': url,
        'verifyPay': False,
    }

    r = requests.post(
        'https://wxpusher.zjiecode.com/api/send/message',
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()

    if result.get('success'):
        count = len(result.get('data', []))
        print(f'WxPusher推送成功，已送达 {count} 位订阅用户')
    else:
        raise Exception(f"推送失败: {result.get('msg')}")


if __name__ == '__main__':
    main()
