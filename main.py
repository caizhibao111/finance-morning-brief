"""
财经早报自动生成系统
数据源：AKShare（A股+港股）/ feedparser（Reuters/CNBC/WSJ）/
        国家统计局官方数据 / 发改委 / 公司公告
AI生成：Claude API（模型由 CLAUDE_MODEL 环境变量控制）
"""
import os
import json
import time
from datetime import datetime, timedelta
import requests

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL      = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
WXPUSHER_TOKEN    = os.environ.get('WXPUSHER_TOKEN', '')
GITHUB_PAGES_URL  = os.environ.get('GITHUB_PAGES_URL', '')
ANTHROPIC_URL     = 'https://api.anthropic.com/v1/messages'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


# ══════════════════════════════════════════════
#  A股行情
# ══════════════════════════════════════════════

def get_a_stock_data() -> dict:
    """采集A股主要指数（上证/深证/创业板/科创50）"""
    data = {}
    try:
        import akshare as ak
        indices = {
            '上证指数': 'sh000001',
            '深证成指': 'sz399001',
            '创业板指': 'sz399006',
            '科创50':   'sh000688',
        }
        for name, symbol in indices.items():
            try:
                df = ak.stock_zh_index_daily(symbol=symbol).tail(2)
                if not df.empty:
                    close = float(df['close'].iloc[-1])
                    prev  = float(df['close'].iloc[-2]) if len(df) > 1 else close
                    data[name] = {
                        'price':      close,
                        'change_pct': round((close - prev) / prev * 100, 2)
                    }
            except Exception:
                pass
    except ImportError:
        pass
    return data


# ══════════════════════════════════════════════
#  港股行情（新增）
# ══════════════════════════════════════════════

def get_hk_stock_data() -> dict:
    """
    采集港股主要指数及龙头个股
    接口策略：
      1. 优先用 stock_hk_index_spot_em（实时，东方财富）
      2. 备用 stock_hk_index_daily_em（历史K线）
      3. 个股用 stock_hk_hist（历史）
    """
    data = {}
    try:
        import akshare as ak

        # ── 指数 ──
        index_map = {
            '恒生指数':    '恒生指数',
            '恒生科技':    '恒生科技指数',
            '恒生中国企业':'恒生中国企业指数',
        }
        # 方法1：实时行情
        try:
            spot = ak.stock_hk_index_spot_em()
            for cn_name, index_name in index_map.items():
                row = spot[spot['名称'].str.contains(index_name[:4], na=False)]
                if not row.empty:
                    r = row.iloc[0]
                    data[cn_name] = {
                        'price':      float(r.get('最新', r.get('收盘', 0))),
                        'change_pct': float(str(r.get('涨跌幅', '0')).replace('%', ''))
                    }
        except Exception:
            pass

        # 方法2：历史K线（备用）
        if not data:
            for cn_name, index_name in index_map.items():
                try:
                    df = ak.stock_hk_index_daily_em(symbol=index_name).tail(2)
                    if not df.empty:
                        close = float(df['收盘'].iloc[-1])
                        prev  = float(df['收盘'].iloc[-2]) if len(df) > 1 else close
                        data[cn_name] = {
                            'price':      close,
                            'change_pct': round((close - prev) / prev * 100, 2)
                        }
                except Exception:
                    pass

        # ── 港股龙头个股 ──
        hk_stocks = {
            '腾讯控股':   '00700',
            '阿里巴巴':   '09988',
            '美团':       '03690',
            '汇丰控股':   '00005',
            '中国移动港': '00941',
            '小米集团':   '01810',
            '京东集团':   '09618',
            '百度港股':   '09888',
        }
        for cn_name, code in hk_stocks.items():
            try:
                today     = datetime.now().strftime('%Y%m%d')
                week_ago  = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
                df = ak.stock_hk_hist(
                    symbol=code, period='daily',
                    start_date=week_ago, end_date=today, adjust=''
                )
                if not df.empty:
                    close = float(df['收盘'].iloc[-1])
                    prev  = float(df['收盘'].iloc[-2]) if len(df) > 1 else close
                    data[cn_name] = {
                        'price':      close,
                        'change_pct': round((close - prev) / prev * 100, 2),
                        'type':       'stock'
                    }
            except Exception:
                pass
            time.sleep(0.1)   # 礼貌延迟，避免频率限制

    except ImportError:
        pass

    return data


def get_southbound_flow() -> dict:
    """南向资金（港股通）净流入数据"""
    flow = {}
    try:
        import akshare as ak
        # 沪港通+深港通南向资金
        try:
            df = ak.stock_hsgt_sh_hk_spot_em()
            if not df.empty:
                flow['南向净买入'] = df.to_dict('records')[0]
        except Exception:
            pass
    except ImportError:
        pass
    return flow


# ══════════════════════════════════════════════
#  国内要闻
# ══════════════════════════════════════════════

def get_domestic_news() -> list:
    """采集国内财经要闻（东方财富公告电报）"""
    news = []
    try:
        import akshare as ak
        try:
            df = ak.stock_news_em(symbol='全球')
            for _, row in df.head(20).iterrows():
                title = str(row.get('标题', ''))
                if title:
                    news.append({
                        'title':   title,
                        'content': str(row.get('内容', ''))[:200],
                        'source':  '东方财富',
                        'tier':    'domestic'
                    })
        except Exception:
            pass
    except ImportError:
        pass
    return news


# ══════════════════════════════════════════════
#  国际财报要闻（Reuters/CNBC/WSJ）
# ══════════════════════════════════════════════

def get_intl_news() -> list:
    """
    国际权威财经新闻RSS
    数据源：Reuters / CNBC / WSJ / Barrons / MarketWatch / Economist
    剔除新浪财经等偏主观来源
    """
    news = []
    try:
        import feedparser
    except ImportError:
        return news

    sources = [
        ('Reuters Markets',   'https://feeds.reuters.com/reuters/marketsNews'),
        ('Reuters Business',  'https://feeds.reuters.com/reuters/businessNews'),
        ('Reuters Asia',      'https://feeds.reuters.com/reuters/AsiaTopNews'),
        ('CNBC Finance',      'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
        ('CNBC Markets',      'https://www.cnbc.com/id/20409666/device/rss/rss.html'),
        ('CNBC Asia',         'https://www.cnbc.com/id/19832390/device/rss/rss.html'),
        ('MarketWatch',       'https://feeds.marketwatch.com/marketwatch/topstories/'),
        ('Barrons',           'https://www.barrons.com/xml/rss/3_7510.xml'),
        ('WSJ Markets',       'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'),
        ('Economist Finance', 'https://www.economist.com/finance-and-economics/rss.xml'),
    ]

    # 修复：系统在北京08:15（UTC 00:15）运行
    # 美股收盘约为UTC 20:00，距运行时约4小时
    # 原18小时窗口受RSS延迟+时区标注差异影响，可能漏掉昨晚美股收盘后的新闻
    # 改为36小时窗口并使用utcnow()，确保完整覆盖前一美股交易日
    cutoff = datetime.utcnow() - timedelta(hours=36)
    for source_name, url in sources:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            count = 0
            no_time_entries = []
            for entry in feed.entries[:8]:
                title = entry.get('title', '').strip()
                if len(title) <= 10:
                    continue
                pub = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub:
                    pub_dt = datetime(*pub[:6])  # UTC naive datetime
                    if pub_dt < cutoff:
                        continue
                    news.append({
                        'title':   title,
                        'summary': entry.get('summary', '')[:250],
                        'source':  source_name,
                        'url':     entry.get('link', ''),
                        'tier':    'international'
                    })
                    count += 1
                else:
                    # 无时间戳：RSS通常按时间降序，取前2条作为补充
                    no_time_entries.append({
                        'title':   title,
                        'summary': entry.get('summary', '')[:250],
                        'source':  source_name,
                        'url':     entry.get('link', ''),
                        'tier':    'international'
                    })
            for e in no_time_entries[:2]:
                news.append(e)
                count += 1
            if count:
                print(f'    ✓ {source_name}: {count}条')
        except Exception as e:
            print(f'    ✗ {source_name}: {str(e)[:50]}')
        time.sleep(0.2)

    return news


# ══════════════════════════════════════════════
#  官方宏观数据
# ══════════════════════════════════════════════

def get_macro_data() -> dict:
    """采集官方宏观数据（国家统计局/央行）"""
    macro = {}
    try:
        import akshare as ak
        indicators = {
            '中国PMI制造业': lambda: ak.macro_china_pmi().tail(1),
            '中国CPI同比':   lambda: ak.macro_china_cpi_monthly().tail(1),
            '美联储利率':    lambda: ak.macro_bank_usa_interest_rate().tail(1),
        }
        for name, fn in indicators.items():
            try:
                df = fn()
                if not df.empty:
                    macro[name] = df.to_dict('records')[0]
            except Exception:
                pass
    except ImportError:
        pass
    return macro


# ══════════════════════════════════════════════
#  主采集入口
# ══════════════════════════════════════════════

def get_new_energy_data() -> dict:
    """
    采集新能源板块关键数据
    覆盖：锂电池/碳酸锂/光伏/储能/新能源汽车/风电
    数据源：AKShare期货价格 + 行业新闻
    """
    data = {}
    try:
        import akshare as ak

        # 碳酸锂期货价格（大商所）
        try:
            df = ak.futures_main_sina(symbol='LC0')  # 碳酸锂主力合约
            if not df.empty:
                r = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else r
                close = float(r['close'])
                chg = (close - float(prev['close'])) / float(prev['close']) * 100
                data['碳酸锂期货'] = {'price': close, 'change_pct': round(chg, 2), 'unit': '元/吨'}
        except Exception:
            pass

        # 动力煤期货（郑商所）
        try:
            df = ak.futures_main_sina(symbol='ZC0')
            if not df.empty:
                r = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else r
                close = float(r['close'])
                chg = (close - float(prev['close'])) / float(prev['close']) * 100
                data['动力煤期货'] = {'price': close, 'change_pct': round(chg, 2), 'unit': '元/吨'}
        except Exception:
            pass

        # 硅料/多晶硅现货（AKShare光伏价格）
        try:
            df = ak.energy_solar_daily_em()
            if not df.empty:
                r = df.iloc[-1]
                data['多晶硅现货'] = {
                    'price': float(r.get('多晶硅', r.iloc[1])),
                    'date':  str(r.iloc[0])[:10]
                }
        except Exception:
            pass

        # 新能源汽车月度销量（工信部/乘联会）
        try:
            df = ak.car_market_total_cn()
            if not df.empty:
                r = df.iloc[-1]
                data['新能源汽车销量'] = {
                    'value': str(r.get('新能源汽车', '')),
                    'date':  str(r.iloc[0])[:7]
                }
        except Exception:
            pass

    except ImportError:
        pass

    return data


def get_company_announcements() -> list:
    """
    采集A股重大公告
    优先级：
      1. AKShare stock_notice_report（全市场公告，含定增/分红/业绩预告/股权变动）
      2. AKShare stock_yjyg_em（业绩预告专项）
      3. 以上失败则返回空列表，Prompt中会提示"暂无公告数据"
    关注类型：定向增发、业绩预告、重大合同、股权转让、分红方案、回购计划
    """
    announcements = []
    try:
        import akshare as ak

        # 方法1：全市场公告（东方财富）
        try:
            df = ak.stock_notice_report()
            IMPORTANT_TYPES = ['定向增发', '业绩预告', '重大合同', '股权转让',
                                '分红', '回购', '重大资产', '并购重组', '可转债',
                                '战略合作', '增持', '减持', '股权激励']
            for _, row in df.head(30).iterrows():
                title = str(row.get('公告标题', ''))
                ann_type = str(row.get('公告类型', ''))
                company = str(row.get('股票简称', ''))
                code = str(row.get('股票代码', ''))
                date = str(row.get('公告日期', ''))[:10]
                # 优先展示重要类型
                is_important = any(k in title or k in ann_type for k in IMPORTANT_TYPES)
                if company and title:
                    announcements.append({
                        'company':    company,
                        'code':       code,
                        'title':      title,
                        'type':       ann_type,
                        'date':       date,
                        'important':  is_important,
                    })
            # 重要公告优先排序
            announcements.sort(key=lambda x: x['important'], reverse=True)
            print(f'    ✓ stock_notice_report: {len(announcements)}条')
        except Exception as e:
            print(f'    ✗ stock_notice_report: {str(e)[:60]}')

        # 方法2：业绩预告专项（补充）
        if len(announcements) < 5:
            try:
                from datetime import datetime
                df2 = ak.stock_yjyg_em(date=datetime.now().strftime('%Y%m%d'))
                for _, row in df2.head(10).iterrows():
                    company = str(row.get('股票简称', ''))
                    code = str(row.get('股票代码', ''))
                    ytype = str(row.get('业绩预告类型', ''))
                    reason = str(row.get('业绩变动原因', ''))[:80]
                    if company:
                        announcements.append({
                            'company':   company,
                            'code':      code,
                            'title':     f'业绩预告：{ytype}',
                            'type':      '业绩预告',
                            'date':      datetime.now().strftime('%Y-%m-%d'),
                            'detail':    reason,
                            'important': True,
                        })
                print(f'    ✓ stock_yjyg_em补充: {min(10,len(df2))}条')
            except Exception as e:
                print(f'    ✗ stock_yjyg_em: {str(e)[:60]}')

    except ImportError:
        pass

    return announcements[:15]  # 最多取15条


def get_bigshots_news() -> list:
    """
    采集科技/商业大佬最新动向（前瞻性指标）
    数据源：RSS + 关键词搜索
    覆盖人物：黄仁勋、马斯克、奥特曼、扎克伯格、Altman、黄仁勋
              贝索斯、库克、纳德拉、李彦宏、马云、任正非、雷军等
    覆盖类型：战略表态、公司融资、重大合作、持仓变动、公开演讲观点
    """
    news = []
    try:
        import feedparser

        # 科技大佬动向RSS源
        sources = [
            ('TechCrunch',    'https://techcrunch.com/feed/'),
            ('VentureBeat',   'https://venturebeat.com/feed/'),
            ('The Verge AI',  'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml'),
            ('Wired AI',      'https://www.wired.com/feed/tag/artificial-intelligence/rss'),
            ('MIT Tech',      'https://www.technologyreview.com/feed/'),
        ]

        # 大佬关键词（中英文）
        BIGSHOTS = [
            'Jensen Huang', 'Elon Musk', 'Sam Altman', 'Mark Zuckerberg',
            'Jeff Bezos', 'Tim Cook', 'Satya Nadella', 'Sundar Pichai',
            'Demis Hassabis', 'Dario Amodei', 'Yann LeCun',
            '黄仁勋', '马斯克', '奥特曼', '扎克伯格', '贝索斯',
            '李彦宏', '马云', '任正非', '雷军', '梁文锋',
            'OpenAI', 'Anthropic', 'Google DeepMind',
        ]

        cutoff = datetime.utcnow() - timedelta(hours=48)

        for source_name, url in sources:
            try:
                feed = feedparser.parse(url, request_headers=HEADERS)
                for entry in feed.entries[:12]:
                    title   = entry.get('title', '').strip()
                    summary = entry.get('summary', '')[:300]
                    combined = (title + ' ' + summary).lower()

                    # 检查是否包含大佬关键词
                    matched = [p for p in BIGSHOTS if p.lower() in combined]
                    if not matched:
                        continue

                    pub = entry.get('published_parsed') or entry.get('updated_parsed')
                    if pub:
                        pub_dt = datetime(*pub[:6])
                        if pub_dt < cutoff:
                            continue

                    news.append({
                        'title':    title,
                        'summary':  summary[:250],
                        'source':   source_name,
                        'url':      entry.get('link', ''),
                        'persons':  matched[:3],   # 涉及人物
                        'tier':     'bigshot'
                    })
                time.sleep(0.2)
            except Exception as e:
                print(f'    ✗ {source_name}: {str(e)[:50]}')

        print(f'    ✓ 大佬动向: {len(news)}条')
    except ImportError:
        pass

    return news[:12]


def get_ai_leaderboard() -> dict:
    """
    AI模型能力榜单（精选4个，满足：高频更新、国内模型参与、直接影响公司股价）
    选榜标准：
      ① 更新频率高（实时/周级） ② 国内模型（DeepSeek/Kimi/GLM/Qwen）有参与
      ③ 直接影响开发者选型→影响AI公司收入→影响股价
    4个精选榜单：
      A. Artificial Analysis综合智能指数 — 速度/成本/能力三维，周级，国内模型最全
      B. LMArena Elo（arena.ai） — 实时，6M+人类盲测，DeepSeek/GLM/Kimi均参与
      C. SWE-bench Pro — 月级，防数据污染，GLM-5.1领跑开源，直接影响编程AI产品竞争
      D. GPQA Diamond科学推理 — 月级，体现模型真实智力上限，Kimi K2.6领跑开源

    ✗ 已弃用：SWE-bench Verified（OpenAI已放弃报告，数据污染严重）
    ✗ 已弃用：Coding Agent单独榜（与SWE-bench Pro高度重叠，scaffold差异大）
    """
    leaderboard = {
        'updated': datetime.now().strftime('%Y-%m-%d'),
        # A. Artificial Analysis综合智能指数 Top6（含国内模型）
        'aa_index': [],
        # B. LMArena Elo Top6（含国内模型）
        'lmarena_elo': [],
        # C. SWE-bench Pro Top5（防污染编程基准）
        'swe_bench_pro': [],
        # D. GPQA Diamond Top5（科学推理）
        'gpqa_diamond': [],
        # 本周变动摘要
        'recent_changes': [],
    }

    # ── A. Artificial Analysis 综合智能指数 ──────────────────────────
    # 源：artificialanalysis.ai  更新：周级  含国内：DeepSeek/Qwen/GLM/Kimi
    leaderboard['aa_index'] = [
        {'rank':1, 'model':'Claude Mythos Preview', 'org':'Anthropic', 'tag':'🇺🇸', 'score':'97'},
        {'rank':2, 'model':'GPT-5.5',               'org':'OpenAI',   'tag':'🇺🇸', 'score':'95'},
        {'rank':3, 'model':'Gemini 3.1 Pro',         'org':'Google',   'tag':'🇺🇸', 'score':'93'},
        {'rank':4, 'model':'DeepSeek V4 Pro',        'org':'DeepSeek', 'tag':'🇨🇳', 'score':'87'},
        {'rank':5, 'model':'Kimi K2.6',              'org':'Moonshot', 'tag':'🇨🇳', 'score':'84'},
        {'rank':6, 'model':'GLM-5 / GLM-5.1',        'org':'智谱AI',   'tag':'🇨🇳', 'score':'83'},
    ]

    # ── B. LMArena Elo（人类盲测偏好） ───────────────────────────────
    # 源：arena.ai  更新：实时（6M+投票）  含国内：DeepSeek/GLM/Kimi
    leaderboard['lmarena_elo'] = [
        {'rank':1, 'model':'Claude Opus 4.6 Thinking','org':'Anthropic', 'tag':'🇺🇸', 'elo':'1561'},
        {'rank':2, 'model':'GPT-5',                   'org':'OpenAI',   'tag':'🇺🇸', 'elo':'1540'},
        {'rank':3, 'model':'Gemini 3.1 Pro',           'org':'Google',   'tag':'🇺🇸', 'elo':'1521'},
        {'rank':4, 'model':'Grok 4',                   'org':'xAI',      'tag':'🇺🇸', 'elo':'1508'},
        {'rank':5, 'model':'DeepSeek V3.2',            'org':'DeepSeek', 'tag':'🇨🇳', 'elo':'1480'},
        {'rank':6, 'model':'GLM-5（开源领跑）',         'org':'智谱AI',   'tag':'🇨🇳', 'elo':'1451'},
    ]

    # ── C. SWE-bench Pro（防污染编程基准） ───────────────────────────
    # 源：labs.scale.com/leaderboard  更新：月级  国内：GLM-5.1领跑开源
    leaderboard['swe_bench_pro'] = [
        {'rank':1, 'model':'Claude Opus 4.7',  'org':'Anthropic', 'tag':'🇺🇸', 'score':'64.3%'},
        {'rank':2, 'model':'GPT-5.5',          'org':'OpenAI',   'tag':'🇺🇸', 'score':'58.6%'},
        {'rank':3, 'model':'GLM-5.1',          'org':'智谱AI',   'tag':'🇨🇳', 'score':'58.4%（开源#1）'},
        {'rank':4, 'model':'DeepSeek V4 Pro',  'org':'DeepSeek', 'tag':'🇨🇳', 'score':'~55%'},
        {'rank':5, 'model':'Gemini 3.1 Pro',   'org':'Google',   'tag':'🇺🇸', 'score':'~48%'},
    ]

    # ── D. GPQA Diamond（科学推理） ──────────────────────────────────
    # 源：llm-stats.com  更新：月级  国内：Kimi K2.6领跑开源（90.5%）
    leaderboard['gpqa_diamond'] = [
        {'rank':1, 'model':'Claude Mythos Preview', 'org':'Anthropic', 'tag':'🇺🇸', 'score':'94.6%'},
        {'rank':2, 'model':'Gemini 3.1 Pro',         'org':'Google',   'tag':'🇺🇸', 'score':'94.3%'},
        {'rank':3, 'model':'GPT-5.5',                'org':'OpenAI',   'tag':'🇺🇸', 'score':'~92%'},
        {'rank':4, 'model':'Kimi K2.6（开源#1）',    'org':'Moonshot', 'tag':'🇨🇳', 'score':'90.5%'},
        {'rank':5, 'model':'DeepSeek V4 Pro',        'org':'DeepSeek', 'tag':'🇨🇳', 'score':'~87%'},
    ]

    # 尝试RSS捕获本周最新榜单变动
    try:
        import feedparser
        lb_sources = [
            ('HuggingFace', 'https://huggingface.co/blog/feed.xml'),
            ('AI News',     'https://buttondown.com/ainews/rss'),
        ]
        cutoff = datetime.utcnow() - timedelta(hours=72)
        lb_kws  = ['leaderboard','benchmark','SWE-bench','arena','GPQA','beats',
                   'outperforms','new model','tops','leads','surpasses','榜单','超越']
        for src, url in lb_sources:
            try:
                feed = feedparser.parse(url, request_headers=HEADERS)
                for entry in feed.entries[:10]:
                    title = entry.get('title', '').strip()
                    if not any(k.lower() in title.lower() for k in lb_kws):
                        continue
                    pub = entry.get('published_parsed') or entry.get('updated_parsed')
                    if pub and datetime(*pub[:6]) < cutoff:
                        continue
                    leaderboard['recent_changes'].append({
                        'title':  title,
                        'source': src,
                    })
            except Exception:
                pass
        time.sleep(0.2)
    except ImportError:
        pass

    return leaderboard


def collect_all_data() -> dict:
    print('\n━━━ 开始采集数据 ━━━')

    print('[1/8] A股行情...')
    a_stocks = get_a_stock_data()
    print(f'      ✓ {len(a_stocks)} 项')

    print('[2/8] 港股行情（指数+龙头个股+南向资金）...')
    hk_stocks  = get_hk_stock_data()
    hk_flow    = get_southbound_flow()
    print(f'      ✓ 行情{len(hk_stocks)}项 南向资金{len(hk_flow)}项')

    print('[3/8] 国内要闻...')
    domestic = get_domestic_news()
    print(f'      ✓ {len(domestic)} 条')

    print('[4/8] 国际财报要闻（Reuters/CNBC/WSJ）...')
    intl = get_intl_news()
    print(f'      ✓ {len(intl)} 条')

    print('[5/8] 官方宏观数据...')
    macro = get_macro_data()
    print(f'      ✓ {len(macro)} 项')

    print('[6/8] 新能源板块数据（锂电/光伏/储能/新能源车）...')
    new_energy = get_new_energy_data()
    print(f'      ✓ {len(new_energy)} 项')

    print('[7/8] A股重大公告（定增/分红/业绩预告/重大合同）...')
    announcements = get_company_announcements()
    print(f'      ✓ {len(announcements)} 条')

    print('[8/8] 科技大佬动向 + AI模型榜单...')
    bigshots    = get_bigshots_news()
    ai_ranking  = get_ai_leaderboard()
    print(f'      ✓ 大佬动向{len(bigshots)}条 榜单数据{len(ai_ranking)}组')

    print('━━━ 采集完成 ━━━\n')

    return {
        'date':          datetime.now().strftime('%Y-%m-%d'),
        'a_stocks':      a_stocks,
        'hk_stocks':     hk_stocks,
        'hk_flow':       hk_flow,
        'domestic':      domestic,
        'intl':          intl,
        'macro':         macro,
        'new_energy':    new_energy,
        'announcements': announcements,
        'bigshots':      bigshots,
        'ai_ranking':    ai_ranking,
    }


def format_data(data: dict) -> str:
    """将采集数据格式化为Prompt文本"""
    lines = []

    # A股
    if data.get('a_stocks'):
        lines.append('## 【A股主要指数】')
        for k, v in data['a_stocks'].items():
            arrow = '▲' if v['change_pct'] >= 0 else '▼'
            lines.append(f"- {k}: {v['price']:,.2f}  {arrow}{abs(v['change_pct']):.2f}%")

    # 港股指数
    hk = data.get('hk_stocks', {})
    hk_indices = {k: v for k, v in hk.items() if v.get('type') != 'stock'}
    hk_stocks  = {k: v for k, v in hk.items() if v.get('type') == 'stock'}

    if hk_indices:
        lines.append('\n## 【港股主要指数】')
        for k, v in hk_indices.items():
            arrow = '▲' if v['change_pct'] >= 0 else '▼'
            lines.append(f"- {k}: {v['price']:,.2f}  {arrow}{abs(v['change_pct']):.2f}%")

    if hk_stocks:
        lines.append('\n## 【港股龙头个股】')
        for k, v in hk_stocks.items():
            arrow = '▲' if v['change_pct'] >= 0 else '▼'
            lines.append(f"- {k}: {v['price']:.2f} HKD  {arrow}{abs(v['change_pct']):.2f}%")

    if data.get('hk_flow'):
        lines.append('\n## 【南向资金（港股通净流入）】')
        lines.append(json.dumps(data['hk_flow'], ensure_ascii=False, default=str)[:200])

    # 宏观
    if data.get('macro'):
        lines.append('\n## 【官方宏观数据（国家统计局/央行）】')
        for k, v in data['macro'].items():
            lines.append(f"- {k}: {json.dumps(v, ensure_ascii=False, default=str)[:80]}")

    # 国际要闻
    if data.get('intl'):
        lines.append('\n## 【国际财报要闻（Reuters/CNBC/WSJ/Barrons）】')
        for i, n in enumerate(data['intl'][:20], 1):
            lines.append(f"{i}. [{n['source']}] {n['title']}")
            if n.get('summary'):
                lines.append(f"   {n['summary'][:150]}")

    # 国内要闻
    if data.get('domestic'):
        lines.append('\n## 【国内财经要闻（财联社/东方财富公告）】')
        for i, n in enumerate(data['domestic'][:15], 1):
            lines.append(f"{i}. [{n['source']}] {n['title']}")

    if data.get('new_energy'):
        lines.append('\n## 【新能源板块数据（锂电/光伏/储能/新能源车）】')
        for k, v in data['new_energy'].items():
            if isinstance(v, dict):
                price = v.get('price', '')
                chg = v.get('change_pct', '')
                unit = v.get('unit', '')
                arrow = '▲' if isinstance(chg, float) and chg >= 0 else '▼'
                chg_str = f'{arrow}{abs(chg):.2f}%' if isinstance(chg, float) else ''
                lines.append(f'- {k}: {price} {unit}  {chg_str}')
            else:
                lines.append(f'- {k}: {v}')

    if data.get('announcements'):
        lines.append('\n## 【A股重大公告（定增/分红/业绩预告/重大合同）】')
        for ann in data['announcements'][:12]:
            co = ann.get('company', '')
            code = ann.get('code', '')
            title = ann.get('title', '')
            ann_type = ann.get('type', '')
            detail = ann.get('detail', '')
            tag = f'[{ann_type}] ' if ann_type else ''
            lines.append(f"- {co}({code}): {tag}{title}" + (f" — {detail}" if detail else ''))

    # 科技大佬动向
    if data.get('bigshots'):
        lines.append('\n## 【科技商业大佬最新动向（前瞻性指标）】')
        lines.append('说明：大佬言行是AI/科技产业的前瞻信号，覆盖：战略表态、融资动向、重大合作、持仓变动')
        for item in data['bigshots'][:8]:
            persons = '、'.join(item.get('persons', []))
            title   = item.get('title', '')
            summary = item.get('summary', '')[:120]
            source  = item.get('source', '')
            lines.append(f'- [{persons}] {title}')
            if summary:
                lines.append(f'  摘要：{summary}')
            lines.append(f'  来源：{source}')

    # AI模型榜单
    if data.get('ai_ranking'):
        r = data['ai_ranking']
        lines.append(f'\n## 【AI模型能力榜单（更新：{r.get("updated","")}）】')
        lines.append('选榜标准：高频更新 + 国内模型参与 + 对AI公司股价有直接冲击')
        lines.append('🇨🇳=国内模型  🇺🇸=海外模型')

        lines.append('\n### A. Artificial Analysis综合智能指数（周级更新·速度/成本/能力三维）')
        for m in r.get('aa_index', []):
            lines.append(f'  #{m["rank"]} {m["tag"]} {m["model"]} ({m["org"]})  得分 {m["score"]}')

        lines.append('\n### B. LMArena Elo人类偏好（实时·6M+真人盲测）')
        for m in r.get('lmarena_elo', []):
            lines.append(f'  #{m["rank"]} {m["tag"]} {m["model"]} ({m["org"]})  Elo {m["elo"]}')

        lines.append('\n### C. SWE-bench Pro编程能力（月级·防数据污染·1865真实任务）')
        for m in r.get('swe_bench_pro', []):
            lines.append(f'  #{m["rank"]} {m["tag"]} {m["model"]} ({m["org"]})  {m["score"]}')

        lines.append('\n### D. GPQA Diamond科学推理（月级·专家级科学题·难以过拟合）')
        for m in r.get('gpqa_diamond', []):
            lines.append(f'  #{m["rank"]} {m["tag"]} {m["model"]} ({m["org"]})  {m["score"]}')

        if r.get('recent_changes'):
            lines.append('\n### 本周榜单动态')
            for item in r['recent_changes'][:3]:
                lines.append(f'  - {item["title"]} （{item["source"]}）')

    return '\n'.join(lines) if lines else '暂无实时数据，请基于近期公开财经事件生成早报。'


# ══════════════════════════════════════════════
#  AI生成早报
# ══════════════════════════════════════════════

def build_prompt(data_text: str) -> str:
    today = datetime.now()
    weekday_cn = ['星期一','星期二','星期三','星期四','星期五','星期六','星期日'][today.weekday()]
    date_str = today.strftime('%Y年%m月%d日')

    return f"""你是一位顶级财经媒体主编，请生成{date_str}（{weekday_cn}）的财经早报完整HTML页面。
参考风格：《陆家嘴财经早餐》+ 彭博社晨报。

【数据时间归属说明——非常重要】
- A股/港股数据：指昨日（{date_str}前一交易日）收盘数据
- 美股数据：指{date_str}凌晨收盘的美股数据（即美东时间昨日16:00收盘 = 北京时间{date_str}凌晨4-5点）
- 不得把前天晚上的美股数据当作"最新"数据使用——早报的美股数据应是距今最近的美股收盘
- 例：{date_str}早报应包含"北京时间{date_str}凌晨"的美股收盘数据，而非更早的数据

━━ 真实数据源 ━━
{data_text}
━━ 数据源结束 ━━

【内容原则】
- 【内容比例严格要求】国内（A股/港股/国内政策/宏观数据）占比60%-70%，国际（美股财报/海外宏观）占比30%-40%，比例为6:4至7:3，不得倒置
- 以国内财经、政策、A股为主线（约60%）
- 港股行情、港股龙头及南向资金作为独立板块（约15%）
- 国际财报聚焦有A/港股映射价值的内容（约25%）
- 宏观政治、地缘等作为背景（约10%）
- 数据必须来自上方数据源，不要编造；数据不足时补充近期公开知识并标注"近期"
- 剔除PR软文，只保留数据、政策节点、量产指标、机构级观点

【防重复铁律——最高优先级，不得违反】
- 每一个具体事件/数据/公司动态，在全篇早报中只允许出现一次，不得在不同板块重复描述
- 判断标准：同一家公司的同一条消息（如"寒武纪Q1净利+185%"），无论换了多少说法，都算重复，只能出现在最合适的一个板块
- 允许"简短提及"规则：某事件在A板块详细展开后，其他板块可以用不超过10个字的极简标注引用（如"→见科技追踪02"或"（详见公告板块）"），但不得重复完整描述
- 各板块的"A股映射"段落，只写该板块独有的映射逻辑，不得重复其他板块已写过的标的或逻辑
- 公告矩阵的条目，必须是全篇其他板块尚未详细展开的内容，或从新角度补充；已在重大公告板块完整描述的，矩阵中只需一行极简摘要
- 今日导读的5条，每条概括一个独立信号，不得与宏观脉搏、科技追踪等板块的详细内容完全雷同
- 内容总量不得因此减少：防重复后，每个板块应用原有字数深挖该板块独有的分析角度、数据、背景和投资建议，而不是简单删减

【页面结构（严格按此顺序）】
注意：每个板块只写该板块"独占"的内容视角，其他板块已覆盖的事件不重复展开。

1. 报头：黑底金色LOGO"财经早报"，日期{date_str}（{weekday_cn}），副标题"昨日A股15:00收盘—美股{date_str}凌晨收盘—今日08:30"，注明数据来源"CNBC · Reuters · 财联社 · 国家统计局"

2. 静态Ticker：黑底，display:flex;flex-wrap:wrap（绝对不要animation，PDF友好），展示美股/A股/港股/油价/黄金/人民币，涨红跌绿

3. 今日导读（TL;DR）：3-5条最重要市场信号，每条是独立信号的"标题级摘要"，不展开详细分析（详细分析留给后续板块），左侧01-05编号

4. 隔夜市场快照：10格grid纯数据（标普/纳指/道指/恒生/恒生科技/韩国KOSPI/WTI/布伦特/黄金/美债10Y），只放数字和涨跌幅，不写分析文字

5. 宏观脉搏：聚焦宏观政策、经济数据、地缘政治；不重复科技追踪已写的产业细节，不重复港股专栏已写的港股数据；分"国内财经政策"（4条）和"国际地缘"（2条）

6. 港股专栏：聚焦港股独有视角——三大指数、南向资金、港股独有标的（非A股双挂牌的纯港股）、港A联动分析；不重复宏观脉搏已写的政策内容

7. A股重大公告：聚焦当日上市公司公告原文——定增/分红/中标/业绩预告/股权变动；不展开产业链分析（产业分析留给科技追踪）

8. 国际公司财报速报：仅限3张，聚焦与A/港股有直接映射价值的海外财报；每张卡片写该公司独有的数据和A股映射，不重复宏观脉搏已写的地缘内容

9. 硬核科技追踪（5张）：每张聚焦该子领域的深度产业分析，引用其他板块的事件时只做极简引用（≤10字），展开的是该事件对产业链的深层影响、配置建议、竞争格局，而非重复事件本身
   ① AI产业链 ② 半导体 ③ 商业航天 ④ 人形机器人（宇树科技=A股科创板，拟募资42.02亿，估值420亿，不得写成港股）⑤ 新能源

10. 大佬动向（商业前瞻信号）：独立板块，深蓝色标题栏
    - 覆盖人物：黄仁勋、马斯克、奥特曼、扎克伯格、纳德拉、李彦宏、梁文锋（DeepSeek）等
    - 每条格式：【人物/机构】核心动作 + 投资前瞻意义（对A股/港股/产业链的影响）
    - 聚焦「前瞻性信号」：大佬的战略押注、公开表态、重大合作、持仓方向代表产业趋势的早期指标
    - 3-5条，每条约50-80字，独立视角不重复其他板块已展开的内容
    - 若当日数据有大佬动向，优先使用；若不足，可补充近期（一周内）重要言论

11. AI模型能力榜单（精选4维）：独立板块，黑底金色标题
    设计原则：极简紧凑，2x2 grid布局，一眼读完，🇨🇳=国内模型 🇺🇸=海外模型
    四个榜单：
      A. Artificial Analysis综合指数 — 速度/成本/能力三维，Top6（含DeepSeek/Kimi/GLM）
      B. LMArena Elo人类盲测 — 实时6M+真人投票，Top6（含DeepSeek/GLM，标注Elo分）
      C. SWE-bench Pro编程能力 — 防数据污染，Top5（GLM-5.1开源第1=58.4%）
      D. GPQA Diamond科学推理 — 专家级科学题，Top5（Kimi K2.6开源第1=90.5%）
    底部：「本周变动」1-2条 + 「投资映射」1句（榜单变化对A股AI链的影响）
    数据来源标注：Artificial Analysis / arena.ai / labs.scale.com / llm-stats.com
    ✗ 禁止出现：SWE-bench Verified（OpenAI已放弃、数据污染）、Coding Agent单独榜

12. 公告矩阵：表格，至少10行，每行是对其他板块内容的"一行极简汇总"或"其他板块未覆盖的补充条目"；已在重大公告板块详细展开的，矩阵只需：公司名|一句核心数字|涨跌|一句解读

13. 今日关注：4-5条，每条聚焦一个具体的待发生事件（财报时间/数据发布/会议）及其影响方向，不重复已发生事件的描述

14. 底部页脚：黑底，数据来源+免责声明+国内:国际比例标注

【设计规范（PDF优化版）】
- 配色：背景#FAF8F3 / 标题栏#1A1A1A / 金色#C9A84C / 涨红#CC2929 / 跌绿#0D7A4A / 蓝#1A3A6B / 港股专栏标题用深紫#4A1A6B
- 字体：'PingFang SC','Microsoft YaHei','Hiragino Sans GB',sans-serif；标题用'STSong','SimSun','Georgia',serif
- 不要引入Google Fonts（PDF环境无法加载）
- Ticker：display:flex;flex-wrap:wrap（不要animation）
- 完整HTML含DOCTYPE，CSS全内联在style标签
- 响应式，600px断点
- 所有emoji改为文字标签（[要闻][行情][港股][宏观][科技]等），避免PDF方块问题

请直接输出完整HTML代码，不要任何前缀说明和代码块标记。"""


def call_claude(prompt: str) -> str:
    print(f'调用Claude生成早报... 模型: {CLAUDE_MODEL}')
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            'x-api-key':         ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type':      'application/json',
        },
        json={
            'model':      CLAUDE_MODEL,
            'max_tokens': 16000,
            'messages':   [{'role': 'user', 'content': prompt}],
        },
        timeout=300,
    )
    resp.raise_for_status()
    html = resp.json()['content'][0]['text']
    for marker in ['```html', '```']:
        if marker in html:
            parts = html.split(marker)
            if len(parts) >= 3:
                html = parts[1]
            break
    print(f'✓ 生成完成，{len(html)} 字符')
    return html.strip()


# ══════════════════════════════════════════════
#  保存文件
# ══════════════════════════════════════════════

def save(html: str) -> str:
    os.makedirs('docs', exist_ok=True)
    today    = datetime.now()
    filename = f"brief-{today.strftime('%Y%m%d')}.html"
    with open(f'docs/{filename}', 'w', encoding='utf-8') as f:
        f.write(html)
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✓ 已保存: docs/{filename}')
    return filename


# ══════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════

def main():
    print('=' * 55)
    print(f'财经早报生成 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 55)

    if not ANTHROPIC_API_KEY:
        raise ValueError('未配置 ANTHROPIC_API_KEY')
    if not GITHUB_PAGES_URL:
        raise ValueError('未配置 GITHUB_PAGES_URL')

    data      = collect_all_data()
    data_text = format_data(data)
    prompt    = build_prompt(data_text)
    html      = call_claude(prompt)
    filename  = save(html)

    with open('summary.json', 'w', encoding='utf-8') as f:
        json.dump({
            'filename': filename,
            'date':     datetime.now().strftime('%Y-%m-%d'),
            'model':    CLAUDE_MODEL
        }, f, ensure_ascii=False, default=str)

    print('=' * 55)
    print('✓ 早报生成完成')
    print('=' * 55)


if __name__ == '__main__':
    main()
