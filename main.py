"""
财经早报自动生成系统

输出文件：
- docs/index.html
- docs/brief-YYYYMMDD.html
- summary.json
"""
import html as html_lib
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

import requests


DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
CLAUDE_MODEL = (os.environ.get("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL).strip()
GITHUB_PAGES_URL = (os.environ.get("GITHUB_PAGES_URL") or os.environ.get("PAGES_URL") or "").strip()
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def safe_str(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("\r", " ").strip()[:limit]


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return clean_value(value.item())
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {str(k): clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_value(v) for v in value]
    return value


def safe_json(value: Any, limit: int = 240) -> str:
    return json.dumps(clean_value(value), ensure_ascii=False, default=str, allow_nan=False)[:limit]


def newest_record(df):
    if df is None or df.empty:
        return None

    work = df.copy()
    for col in ["日期", "月份", "统计时间", "时间", "date"]:
        if col not in work.columns:
            continue

        scores = []
        for value in work[col].astype(str):
            match = re.search(r"(20\d{2})\D{0,3}(\d{1,2})?\D{0,3}(\d{1,2})?", value)
            if not match:
                scores.append(0)
                continue
            year = int(match.group(1))
            month = int(match.group(2) or 1)
            day = int(match.group(3) or 1)
            scores.append(year * 10000 + month * 100 + day)

        work["__date_score"] = scores
        return work.sort_values("__date_score", ascending=False).drop(columns=["__date_score"]).iloc[0].to_dict()

    return work.iloc[-1].to_dict()


def collect_a_stock_data() -> dict:
    data = {}
    try:
        import akshare as ak

        indices = {
            "上证指数": "sh000001",
            "深证成指": "sz399001",
            "创业板指": "sz399006",
            "科创50": "sh000688",
        }
        for name, symbol in indices.items():
            try:
                df = ak.stock_zh_index_daily(symbol=symbol).tail(2)
                if df is not None and not df.empty:
                    close = float(df["close"].iloc[-1])
                    prev = float(df["close"].iloc[-2]) if len(df) > 1 else close
                    data[name] = {
                        "price": round(close, 2),
                        "change_pct": round((close - prev) / prev * 100, 2) if prev else 0,
                    }
            except Exception as e:
                print(f"    - {name} 获取失败: {str(e)[:80]}")
    except Exception as e:
        print(f"    - A股依赖不可用: {str(e)[:80]}")
    return data


def collect_macro_data() -> dict:
    data = {}
    try:
        import akshare as ak

        sources = {
            "中国PMI制造业": lambda: ak.macro_china_pmi(),
            "中国CPI同比": lambda: ak.macro_china_cpi_monthly(),
            "美联储利率": lambda: ak.macro_bank_usa_interest_rate(),
        }
        for name, fn in sources.items():
            try:
                record = newest_record(fn())
                if record:
                    data[name] = clean_value(record)
            except Exception as e:
                print(f"    - {name} 获取失败: {str(e)[:80]}")
    except Exception as e:
        print(f"    - 宏观依赖不可用: {str(e)[:80]}")
    return data


def collect_domestic_news() -> list:
    news = []
    try:
        import akshare as ak

        df = ak.stock_news_em(symbol="全球")
        if df is not None and not df.empty:
            for _, row in df.head(12).iterrows():
                title = safe_str(row.get("标题", ""))
                if title:
                    news.append({
                        "title": title,
                        "summary": safe_str(row.get("内容", ""), 180),
                        "source": "东方财富",
                    })
    except Exception as e:
        print(f"    - 国内新闻获取失败: {str(e)[:80]}")
    return news


def collect_international_news() -> list:
    news = []
    try:
        import feedparser
    except Exception as e:
        print(f"    - feedparser不可用: {str(e)[:80]}")
        return news

    sources = [
        ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
        ("CNBC Markets", "https://www.cnbc.com/id/20409666/device/rss/rss.html"),
        ("CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ]
    cutoff = datetime.utcnow() - timedelta(hours=72)

    for source_name, url in sources:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            count = 0
            for entry in feed.entries[:8]:
                title = safe_str(entry.get("title", ""))
                if len(title) < 8:
                    continue

                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub and datetime(*pub[:6]) < cutoff:
                    continue

                news.append({
                    "title": title,
                    "summary": safe_str(entry.get("summary", ""), 220),
                    "source": source_name,
                    "url": entry.get("link", ""),
                })
                count += 1

            if count:
                print(f"    ✓ {source_name}: {count}条")
        except Exception as e:
            print(f"    - {source_name} 获取失败: {str(e)[:80]}")
        time.sleep(0.1)

    return news[:20]


def collect_company_announcements() -> list:
    announcements = []
    try:
        import akshare as ak

        df = ak.stock_notice_report()
        if df is not None and not df.empty:
            important = ["定向增发", "业绩预告", "重大合同", "股权转让", "分红", "回购", "并购重组", "增持", "减持"]
            for _, row in df.head(25).iterrows():
                title = safe_str(row.get("公告标题", ""))
                ann_type = safe_str(row.get("公告类型", ""))
                company = safe_str(row.get("股票简称", ""))
                code = safe_str(row.get("股票代码", ""))

                if company and title and any(k in title or k in ann_type for k in important):
                    announcements.append({
                        "company": company,
                        "code": code,
                        "title": title,
                        "type": ann_type,
                        "date": safe_str(row.get("公告日期", ""))[:10],
                    })

        print(f"    ✓ stock_notice_report: {len(announcements)}条")
    except Exception as e:
        print(f"    - 公告获取失败，已跳过: {str(e)[:80]}")

    return announcements[:12]


def collect_bigshots_news() -> list:
    news = []
    try:
        import feedparser
    except Exception:
        return news

    sources = [
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("VentureBeat", "https://venturebeat.com/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("MIT Tech", "https://www.technologyreview.com/feed/"),
    ]
    keywords = [
        "Jensen Huang", "Elon Musk", "Sam Altman", "Mark Zuckerberg", "Satya Nadella",
        "OpenAI", "Anthropic", "DeepMind", "Nvidia", "黄仁勋", "马斯克", "奥特曼",
    ]
    cutoff = datetime.utcnow() - timedelta(hours=72)

    for source_name, url in sources:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            for entry in feed.entries[:10]:
                title = safe_str(entry.get("title", ""))
                summary = safe_str(entry.get("summary", ""), 220)
                combined = (title + " " + summary).lower()
                matched = [k for k in keywords if k.lower() in combined]
                if not matched:
                    continue

                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub and datetime(*pub[:6]) < cutoff:
                    continue

                news.append({
                    "persons": matched[:3],
                    "title": title,
                    "summary": summary,
                    "source": source_name,
                })
        except Exception as e:
            print(f"    - {source_name} 大佬动向获取失败: {str(e)[:80]}")
        time.sleep(0.1)

    return news[:8]


def get_ai_leaderboard() -> dict:
    return {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "note": "静态参考榜单，用于早报版式和产业映射；正式投资判断请结合当日官方榜单。",
        "models": [
            {"rank": 1, "model": "Claude Sonnet / Opus 系列", "org": "Anthropic", "tag": "海外"},
            {"rank": 2, "model": "GPT 系列", "org": "OpenAI", "tag": "海外"},
            {"rank": 3, "model": "Gemini 系列", "org": "Google", "tag": "海外"},
            {"rank": 4, "model": "DeepSeek / Qwen / Kimi / GLM", "org": "中国模型厂商", "tag": "国内"},
        ],
    }


def collect_all_data() -> dict:
    print("\n━━━ 开始采集数据 ━━━")

    print("[1/7] A股行情...")
    a_stocks = collect_a_stock_data()
    print(f"      ✓ {len(a_stocks)} 项")

    print("[2/7] 国内要闻...")
    domestic = collect_domestic_news()
    print(f"      ✓ {len(domestic)} 条")

    print("[3/7] 国际财经要闻...")
    intl = collect_international_news()
    print(f"      ✓ {len(intl)} 条")

    print("[4/7] 官方宏观数据...")
    macro = collect_macro_data()
    print(f"      ✓ {len(macro)} 项")

    print("[5/7] A股重大公告...")
    announcements = collect_company_announcements()
    print(f"      ✓ {len(announcements)} 条")

    print("[6/7] 科技大佬动向...")
    bigshots = collect_bigshots_news()
    print(f"      ✓ {len(bigshots)} 条")

    print("[7/7] AI模型榜单...")
    ai_ranking = get_ai_leaderboard()
    print("      ✓ 1 组")

    print("━━━ 采集完成 ━━━\n")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "a_stocks": a_stocks,
        "domestic": domestic,
        "intl": intl,
        "macro": macro,
        "announcements": announcements,
        "bigshots": bigshots,
        "ai_ranking": ai_ranking,
    }


def format_data(data: dict) -> str:
    lines = [f"数据日期：{data.get('date')}"]

    if data.get("a_stocks"):
        lines.append("\n## A股主要指数")
        for name, item in data["a_stocks"].items():
            change = item.get("change_pct", 0)
            arrow = "上涨" if change >= 0 else "下跌"
            lines.append(f"- {name}: {item.get('price')}，{arrow}{abs(change):.2f}%")

    if data.get("macro"):
        lines.append("\n## 官方宏观数据")
        for name, item in data["macro"].items():
            lines.append(f"- {name}: {safe_json(item, 220)}")

    if data.get("domestic"):
        lines.append("\n## 国内财经要闻")
        for i, item in enumerate(data["domestic"][:12], 1):
            lines.append(f"{i}. [{item.get('source')}] {item.get('title')}")
            if item.get("summary"):
                lines.append(f"   摘要：{item.get('summary')}")

    if data.get("intl"):
        lines.append("\n## 国际财经要闻")
        for i, item in enumerate(data["intl"][:16], 1):
            lines.append(f"{i}. [{item.get('source')}] {item.get('title')}")
            if item.get("summary"):
                lines.append(f"   摘要：{item.get('summary')}")

    if data.get("announcements"):
        lines.append("\n## A股重大公告")
        for item in data["announcements"]:
            lines.append(f"- {item.get('company')}({item.get('code')}): [{item.get('type')}] {item.get('title')}")

    if data.get("bigshots"):
        lines.append("\n## 科技商业大佬动向")
        for item in data["bigshots"]:
            persons = "、".join(item.get("persons", []))
            lines.append(f"- [{persons}] {item.get('title')} | {item.get('source')}")
            if item.get("summary"):
                lines.append(f"  摘要：{item.get('summary')}")

    if data.get("ai_ranking"):
        lines.append("\n## AI模型能力榜单参考")
        lines.append(data["ai_ranking"].get("note", ""))
        for item in data["ai_ranking"].get("models", []):
            lines.append(f"- #{item['rank']} {item['model']} ({item['org']}, {item['tag']})")

    return "\n".join(lines)


def fallback_html(reason: str, data_text: str) -> str:
    today = datetime.now()
    escaped_data = html_lib.escape(data_text[:8000])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>财经早报 {today.strftime('%Y-%m-%d')}</title>
<style>
body {{ margin:0; background:#FAF8F3; color:#1A1A1A; font-family:'Noto Sans CJK SC','WenQuanYi Zen Hei','Microsoft YaHei',Arial,sans-serif; line-height:1.65; }}
header {{ background:#1A1A1A; color:#C9A84C; padding:28px 20px; }}
main {{ max-width:980px; margin:0 auto; padding:24px 18px 48px; }}
h1 {{ margin:0; font-size:30px; }}
h2 {{ border-left:5px solid #C9A84C; padding-left:10px; margin-top:28px; color:#1A3A6B; }}
pre {{ white-space:pre-wrap; background:#fff; border:1px solid #ddd; padding:16px; border-radius:8px; }}
.notice {{ background:#fff7d6; border:1px solid #d8bf63; padding:14px; border-radius:8px; }}
@page {{ size:A4; margin:10mm; }}
</style>
</head>
<body>
<header>
<h1>财经早报</h1>
<p>{today.strftime('%Y年%m月%d日 %H:%M')}</p>
</header>
<main>
<section class="notice">
<strong>自动模板版早报。</strong><br>
AI 润色服务暂时不可用，系统已基于已采集数据生成可读早报。
</section>
<h2>采集数据摘要</h2>
<pre>{escaped_data}</pre>
<h2>今日关注</h2>
<ul>
<li>关注国内宏观数据、政策表态与市场成交变化。</li>
<li>关注海外利率预期、科技股财报与大宗商品波动。</li>
<li>关注 AI 算力、模型迭代及相关产业链公告。</li>
</ul>
<p>免责声明：本早报由自动化程序基于公开数据生成，仅供信息参考，不构成投资建议。</p>
</main>
</body>
</html>"""


def build_prompt(data_text: str) -> str:
    today = datetime.now()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][today.weekday()]
    date_str = today.strftime("%Y年%m月%d日")

    return f"""你是一位顶级财经媒体主编，请基于下方真实数据生成 {date_str}（{weekday_cn}）的财经早报完整 HTML 页面。

要求：
- 输出完整 HTML，不要 Markdown 代码块，不要解释。
- 风格参考《陆家嘴财经早餐》和彭博晨报，专业、紧凑、适合投资团队晨会阅读。
- 国内内容占 60%-70%，国际内容占 30%-40%。
- 必须包含：报头、市场快照、今日导读、宏观脉搏、国内财经、国际财经、A股公告、科技追踪、AI模型榜单、今日关注、免责声明。
- 数据不足时可以补充近期公开知识，但必须标注“近期”。
- 不要编造具体价格和百分比；没有数据就写“暂无可靠实时数据”。
- CSS 写在 style 标签中，页面响应式，适配手机和桌面。
- 字体必须包含 Noto Sans CJK SC、WenQuanYi Zen Hei、Microsoft YaHei。
- 配色：背景 #FAF8F3，标题栏 #1A1A1A，金色 #C9A84C，涨红 #CC2929，跌绿 #0D7A4A，蓝色 #1A3A6B。

真实数据如下：
{data_text}
"""


def call_claude(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("未配置 ANTHROPIC_API_KEY")

    print(f"调用Claude生成早报: {CLAUDE_MODEL}")
    print(f"ANTHROPIC_API_KEY 已配置: {'是' if bool(ANTHROPIC_API_KEY) else '否'}")

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
            "temperature": 0.2,
        },
        timeout=180,
    )

    if resp.status_code >= 400:
        print(f"Claude API错误状态码: {resp.status_code}")
        print(resp.text[:3000])


    resp.raise_for_status()
    content = resp.json().get("content", [])
    result_html = "".join(block.get("text", "") for block in content if block.get("type") == "text").strip()

    fence = re.search(r"```(?:html)?\s*(.*?)```", result_html, flags=re.S | re.I)
    if fence:
        result_html = fence.group(1).strip()

    if "<html" not in result_html.lower():
        result_html = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>财经早报</title></head><body>' + result_html + "</body></html>"

    print(f"✓ Claude生成完成，{len(result_html)} 字符")
    return result_html


def save_outputs(result_html: str, generation_mode: str) -> str:
    os.makedirs("docs", exist_ok=True)
    filename = f"brief-{datetime.now().strftime('%Y%m%d')}.html"

    with open(os.path.join("docs", filename), "w", encoding="utf-8") as f:
        f.write(result_html)

    with open(os.path.join("docs", "index.html"), "w", encoding="utf-8") as f:
        f.write(result_html)

    with open("summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "filename": filename,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "generation_mode": generation_mode,
            },
            f,
            ensure_ascii=False,
        )

    print(f"✓ 已保存 docs/{filename}、docs/index.html、summary.json")
    return filename


def main():
    print("=" * 55)
    print(f"财经早报生成 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    data = collect_all_data()
    data_text = format_data(data)
    prompt = build_prompt(data_text)

    generation_mode = "claude"
    try:
        result_html = call_claude(prompt)
    except Exception as e:
        generation_mode = "template"
        print(f"Claude生成失败，使用自动模板版HTML: {e}")
        result_html = fallback_html(str(e), data_text)

    filename = save_outputs(result_html, generation_mode)

    print("=" * 55)
    print(f"✓ 早报生成完成: {filename} ({generation_mode})")
    print("=" * 55)


if __name__ == "__main__":
    main()
