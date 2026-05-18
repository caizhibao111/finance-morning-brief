import html
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514").strip()
GITHUB_PAGES_URL = os.getenv("GITHUB_PAGES_URL", "").strip()
OUT_DIR = Path("docs")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def u(text):
    return text


ZH = {
    "finance": "\u8d22\u7ecf",
    "stock": "\u80a1\u7968",
    "global": "\u5168\u7403",
    "title": "\u6807\u9898",
    "news_title": "\u65b0\u95fb\u6807\u9898",
    "content": "\u5185\u5bb9",
    "news_content": "\u65b0\u95fb\u5185\u5bb9",
    "link": "\u94fe\u63a5",
    "news_link": "\u65b0\u95fb\u94fe\u63a5",
    "eastmoney": "\u4e1c\u65b9\u8d22\u5bcc",
    "notice_title": "\u516c\u544a\u6807\u9898",
    "stock_name": "\u80a1\u7968\u7b80\u79f0",
    "notice_type": "\u516c\u544a\u7c7b\u578b",
    "a_notice": "A\u80a1\u516c\u544a",
    "name": "\u540d\u79f0",
    "latest": "\u6700\u65b0\u4ef7",
    "change_pct": "\u6da8\u8dcc\u5e45",
    "board_name": "\u677f\u5757\u540d\u79f0",
    "up_count": "\u4e0a\u6da8\u5bb6\u6570",
}


def safe_str(value, limit=300):
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return safe_str(html.unescape(text), 800)


def esc(value):
    return html.escape(str(value or ""), quote=True)


def clean_json_text(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        return text[first : last + 1]
    return text


def dedupe_items(items, key_fields=("title",)):
    seen = set()
    result = []
    for item in items:
        key = " ".join(safe_str(item.get(k, ""), 120) for k in key_fields).lower()
        key = re.sub(r"\W+", "", key)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def collect_china_news():
    news = []
    try:
        import akshare as ak

        for symbol in [ZH["finance"], ZH["stock"], ZH["global"]]:
            try:
