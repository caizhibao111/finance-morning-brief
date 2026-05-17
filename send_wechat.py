import glob
import json
import os
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

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


def wechat_robot_key(webhook_url: str) -> str:
    query = parse_qs(urlparse(webhook_url).query)
    key = query.get('key', [''])[0]
    if not key:
        raise ValueError('企业微信机器人 webhook 中缺少 key 参数')
    return key


def upload_wechat_file(file_path: str) -> str:
    key = wechat_robot_key(WECHAT_WEBHOOK_URL)
    upload_url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file'
    with open(file_path, 'rb') as f:
        files = {
            'media': (
                os.path.basename(file_path),
                f,
                'text/html',
            )
        }
        r = requests.post(upload_url, files=files, timeout=30)
    r.raise_for_status()
    result = r.json()
    if result.get('errcode') != 0:
        raise Exception(f"企业微信文件上传失败: {result}")
    media_id = result.get('media_id')
    if not media_id:
        raise Exception(f"企业微信文件上传未返回 media_id: {result}")
    return media_id


def send_wechat_markdown(title: str, content: str, url: str = '') -> None:
    message = f'## {title}\n\n{content}'
    if url:
        message += f'\n\n[备用网页链接]({url})'
    payload = {
        'msgtype': 'markdown',
        'markdown': {'content': message},
    }
    r = requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()
    if result.get('errcode') != 0:
        raise Exception(f"企业微信 Markdown 推送失败: {result}")


def send_wechat_file(media_id: str) -> None:
    payload = {
        'msgtype': 'file',
        'file': {'media_id': media_id},
    }
    r = requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()
    if result.get('errcode') != 0:
        raise Exception(f"企业微信文件推送失败: {result}")


def send_wxpusher(title: str, content: str, url: str) -> None:
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
        raise Exception(f"WxPusher推送失败: {result.get('msg')}")


def main():
    print('等待GitHub Pages部署...')
    time.sleep(20)

    filename = resolve_brief_filename()
    pdf_file = os.path.join('docs', 'brief.pdf')
    local_file = pdf_file if os.path.exists(pdf_file) else os.path.join('docs', filename)
    today = datetime.now()
    weekday_cn = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'][today.weekday()]
    url = f"{GITHUB_PAGES_URL.rstrip('/')}/{filename}" if GITHUB_PAGES_URL else ''
    title = f'财经早报 {today.strftime("%m月%d日")}'
    file_type = 'PDF' if local_file.endswith('.pdf') else 'HTML'
    content = f'财经早报 · {today.strftime("%m月%d日")}（{weekday_cn}）已更新。已随消息附上 {file_type} 文件，企业微信内可直接预览，无需 VPN。'

    if WECHAT_WEBHOOK_URL:
        # 先发一条说明，再发 HTML 文件。链接仅作为备用，不依赖 GitHub Pages。
        send_wechat_markdown(title, content, url='')
        media_id = upload_wechat_file(local_file)
        send_wechat_file(media_id)
        print('企业微信群机器人推送成功：已发送说明消息和 HTML 文件')
        return

    send_wxpusher(title, content, url)


if __name__ == '__main__':
    main()
