        import akshare as ak

        df = ak.stock_news_em(symbol="全球")
        if df is not None and not df.empty:
            for _, row in df.head(18).iterrows():
                title = safe_str(row.get("标题", ""), 180)
                if title:
                    news.append({
                        "title": title,
                        "summary": safe_str(row.get("内容", ""), 240),
                        "source": "东方财富",
                    })
    except Exception as exc:
        print(f"    - 国内新闻获取失败: {str(exc)[:100]}")
    return news


def collect_rss_news() -> tuple[list, list]:
    intl = []
    tech = []
    try:
        import feedparser
    except Exception as exc:
        print(f"    - feedparser不可用: {str(exc)[:100]}")
        return intl, tech

    sources = [
        ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "intl"),
        ("CNBC Markets", "https://www.cnbc.com/id/20409666/device/rss/rss.html", "intl"),
        ("CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html", "intl"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/", "intl"),
        ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "intl"),
        ("TechCrunch", "https://techcrunch.com/feed/", "tech"),
        ("VentureBeat", "https://venturebeat.com/feed/", "tech"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "tech"),
        ("MIT Tech", "https://www.technologyreview.com/feed/", "tech"),
    ]
    cutoff = datetime.utcnow() - timedelta(hours=96)
    for source_name, url, bucket in sources:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            count = 0
            for entry in feed.entries[:10]:
                title = safe_str(entry.get("title", ""), 180)
                if len(title) < 8:
                    continue
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub and datetime(*pub[:6]) < cutoff:
                    continue
                item = {
                    "title": title,
                    "summary": strip_tags(safe_str(entry.get("summary", ""), 260)),
                    "source": source_name,
                    "url": entry.get("link", ""),
                }
                if bucket == "tech":
                    tech.append(item)
                else:
                    intl.append(item)
                count += 1
            if count:
                print(f"    ✓ {source_name}: {count}条")
        except Exception as exc:
            print(f"    - {source_name} 获取失败: {str(exc)[:100]}")
        time.sleep(0.1)
    return intl[:24], tech[:12]


def collect_company_announcements() -> list:
    announcements = []
    try:
        import akshare as ak

        df = ak.stock_notice_report()
        keywords = ["定向增发", "业绩预告", "重大合同", "股权转让", "分红", "回购", "并购重组", "增持", "减持"]
        if df is not None and not df.empty:
            for _, row in df.head(35).iterrows():
                title = safe_str(row.get("公告标题", ""), 220)
                ann_type = safe_str(row.get("公告类型", ""), 80)
                company = safe_str(row.get("股票简称", ""), 80)
                code = safe_str(row.get("股票代码", ""), 40)
                if company and title and any(k in title or k in ann_type for k in keywords):
                    announcements.append({
                        "company": company,
                        "code": code,
                        "title": title,
                        "type": ann_type or "公告",
                        "date": safe_str(row.get("公告日期", ""))[:10],
                    })
    except Exception as exc:
        print(f"    - 公告获取失败，已跳过: {str(exc)[:100]}")
    return announcements[:12]


def get_ai_leaderboard() -> list:
    return [
        {"rank": 1, "model": "Claude Sonnet / Opus 系列", "org": "Anthropic", "tag": "海外"},
        {"rank": 2, "model": "GPT 系列", "org": "OpenAI", "tag": "海外"},
        {"rank": 3, "model": "Gemini 系列", "org": "Google", "tag": "海外"},
        {"rank": 4, "model": "DeepSeek / Qwen / Kimi / GLM", "org": "中国模型厂商", "tag": "国内"},
    ]


def collect_all_data() -> dict:
    print("\n━━━ 开始采集数据 ━━━")
    print("[1/6] A股行情...")
    a_stocks = collect_a_stock_data()
    print(f"      ✓ {len(a_stocks)} 项")

    print("[2/6] 国内要闻...")
    domestic = collect_domestic_news()
    print(f"      ✓ {len(domestic)} 条")

    print("[3/6] 国际和科技RSS...")
    intl, tech = collect_rss_news()
    print(f"      ✓ 国际 {len(intl)} 条，科技 {len(tech)} 条")

    print("[4/6] 官方宏观数据...")
    macro = collect_macro_data()
    print(f"      ✓ {len(macro)} 项")

    print("[5/6] A股重大公告...")
    announcements = collect_company_announcements()
    print(f"      ✓ {len(announcements)} 条")

    print("[6/6] AI模型榜单...")
    ai_ranking = get_ai_leaderboard()
    print("      ✓ 1 组")
    print("━━━ 采集完成 ━━━\n")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "a_stocks": a_stocks,
        "domestic": domestic,
        "intl": intl,
        "tech": tech,
        "macro": macro,
        "announcements": announcements,
        "ai_ranking": ai_ranking,
    }


def compact_source_text(data: dict) -> str:
    lines = [f"数据日期：{data.get('date')}"]
    if data.get("a_stocks"):
        lines.append("\n## A股主要指数")
        for item in data["a_stocks"].values():
            change = item.get("change_pct", 0)
            lines.append(f"- {item['name']}: {item.get('price')}，{change:+.2f}%")

    if data.get("macro"):
        lines.append("\n## 官方宏观数据")
        for name, item in data["macro"].items():
            lines.append(f"- {name}: {safe_json(item, 260)}")

    def add_news(title: str, items: list, limit: int):
        if not items:
            return
        lines.append(f"\n## {title}")
        for idx, item in enumerate(items[:limit], 1):
            lines.append(f"{idx}. [{item.get('source')}] {item.get('title')}")
            if item.get("summary"):
                lines.append(f"   摘要：{item.get('summary')}")

    add_news("国内财经要闻", data.get("domestic", []), 14)
    add_news("国际财经要闻", data.get("intl", []), 16)
    add_news("科技与AI动态", data.get("tech", []), 10)

    if data.get("announcements"):
        lines.append("\n## A股重大公告")
        for item in data["announcements"][:12]:
            lines.append(f"- {item.get('company')}({item.get('code')}): [{item.get('type')}] {item.get('title')}")
    return "\n".join(lines)


def default_report(data: dict) -> dict:
    today = datetime.now()
    a_stocks = list(data.get("a_stocks", {}).values())
    market_snapshot = []
    for item in a_stocks:
        change = item.get("change_pct", 0)
        market_snapshot.append({
            "name": item.get("name"),
            "value": f"{item.get('price'):,}" if isinstance(item.get("price"), (int, float)) else str(item.get("price", "")),
            "change": f"{change:+.2f}%",
            "direction": "up" if change >= 0 else "down",
            "note": "上涨" if change >= 0 else "回调",
        })
    for name, item in data.get("macro", {}).items():
        market_snapshot.append({
            "name": name,
            "value": safe_json(item, 60),
            "change": "",
            "direction": "flat",
            "note": "宏观数据",
        })

    source_items = (data.get("domestic") or []) + (data.get("intl") or []) + (data.get("tech") or [])
    digest = []
    for idx, item in enumerate(source_items[:8], 1):
