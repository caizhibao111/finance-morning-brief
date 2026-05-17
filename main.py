"""
财经早报自动生成系统
数据源：AKShare（A股+港股）/ feedparser（Reuters/CNBC/WSJ）/
        国家统计局官方数据 / 发改委 / 公司公告
AI生成：Claude
"""
import os
import json
import time
from datetime import datetime, timedelta
import requests

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
GITHUB_PAGES_URL = os.environ.get('GITHUB_PAGES_URL', '')
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'

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
