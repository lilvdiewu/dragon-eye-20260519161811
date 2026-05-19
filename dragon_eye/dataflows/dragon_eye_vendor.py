"""
dragon_eye.dataflows.dragon_eye_vendor — 龙瞳A股数据供应商

替代 yfinance，为 TradingAgents 10-Agent 管线提供完整 A 股数据。

注册方式：在 VENDOR_METHODS 中添加 "dragon_eye" 实现
配置方式：config["data_vendors"] = {"core_stock_apis": "dragon_eye", ...}

数据源优先级：
  1. 通达信本地数据（K线/财务/行业）— 零延迟，最权威
  2. AkShare 在线补充（资金流向/板块/实时行情）
  3. 腾讯API备用（行情/换手率）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Annotated, Optional

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================================
# 伴随式资料库（懒加载，零侵入）
# ============================================================

_lk_instance = None

def _get_lk():
    """懒加载 LocalKnowledge 实例"""
    global _lk_instance
    if _lk_instance is None:
        try:
            from dragon_eye.local_knowledge import LocalKnowledge
            _lk_instance = LocalKnowledge()
        except Exception:
            pass  # 资料库不可用不影响主流程
    return _lk_instance


# ============================================================
# 辅助：从 yfinance ticker 格式提取 code6
# ============================================================

def _ticker_to_code6(ticker: str) -> str:
    """从 yfinance ticker 提取6位代码

    例: "603618.SS" → "603618", "000001.SZ" → "000001"
    如果已经是6位纯数字则直接返回
    """
    ticker = ticker.strip().upper()
    if "." in ticker:
        code = ticker.split(".")[0]
    else:
        code = ticker
    if len(code) == 6 and code.isdigit():
        return code
    return code


def _code6_to_market(code6: str) -> str:
    """从代码判断市场

    6开头→sh, 0/3开头→sz, 4/8开头→bj
    """
    if code6.startswith("6"):
        return "sh"
    elif code6.startswith(("0", "3")):
        return "sz"
    elif code6.startswith(("4", "8")):
        return "bj"
    return "sz"


# ============================================================
# 懒加载：避免 import 时触发无用的依赖
# ============================================================

_tdx_reader = None
_dbf_reader = None
_industry_reader = None
_akshare_bridge = None


def _get_tdx_reader():
    global _tdx_reader
    if _tdx_reader is None:
        from dragon_eye.tdx_reader import TdxReader
        _tdx_reader = TdxReader()
    return _tdx_reader


def _get_dbf_reader():
    global _dbf_reader
    if _dbf_reader is None:
        from dragon_eye.analysis.base_dbf_reader import BaseDbfReader
        _dbf_reader = BaseDbfReader()
    return _dbf_reader


def _get_industry_reader():
    global _industry_reader
    if _industry_reader is None:
        from dragon_eye.analysis.tdx_industry import TdxIndustryReader
        _industry_reader = TdxIndustryReader()
    return _industry_reader


def _get_akshare_bridge():
    global _akshare_bridge
    if _akshare_bridge is None:
        from dragon_eye.akshare_bridge import AkShareBridge
        _akshare_bridge = AkShareBridge()
    return _akshare_bridge


# ============================================================
# Vendor 实现函数
# 签名必须和 yfinance 版本完全一致
# ============================================================

def get_stock_data_dragon_eye(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """龙瞳版：从通达信本地读取K线数据（替代 yfinance）

    返回格式与 yfinance 一致（CSV），Agent无需感知差异。
    """
    code6 = _ticker_to_code6(symbol)
    market = _code6_to_market(code6)

    try:
        from dragon_eye.data_models import Market
        mkt = Market.SH if market == "sh" else (Market.BJ if market == "bj" else Market.SZ)
    except ImportError:
        mkt = None

    reader = _get_tdx_reader()

    if mkt is not None:
        klines = reader.get_day_klines(code6, mkt)
    else:
        # fallback: 尝试所有市场
        klines = []
        for mk in ["sh", "sz", "bj"]:
            try:
                from dragon_eye.data_models import Market as M
                m = {"sh": M.SH, "sz": M.SZ, "bj": M.BJ}[mk]
                klines = reader.get_day_klines(code6, m)
                if klines:
                    break
            except Exception:
                continue

    if not klines:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date} (dragon_eye: 通达信本地无数据)"

    # 过滤日期范围
    start_dt = start_date
    end_dt = end_date
    filtered = [k for k in klines if start_dt <= k.date <= end_dt]

    if not filtered:
        # 如果指定范围内没有数据，返回最近的数据
        filtered = klines[-60:]  # 最近60个交易日

    # 转成 CSV 格式（与 yfinance 输出格式一致）
    lines = ["Date,Open,High,Low,Close,Volume"]
    for k in filtered:
        lines.append(f"{k.date},{k.open:.2f},{k.high:.2f},{k.low:.2f},{k.close:.2f},{k.volume}")

    csv_string = "\n".join(lines)

    header = f"# Stock data for {symbol} from {start_date} to {end_date} (dragon_eye/TDX)\n"
    header += f"# Total records: {len(filtered)}\n"
    header += f"# Data source: 通达信本地数据 (A股专用)\n"
    header += f"# Note: 涨跌停/停复牌数据完整，优于yfinance\n\n"

    return header + csv_string


def get_indicators_dragon_eye(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """龙瞳版：技术指标分析（替代 yfinance + stockstats）

    使用龙瞳信号引擎（MA排列/MACD/RSI/突破/量价），比 yfinance 更全面。
    数据源：通达信本地K线，零延迟。
    """
    code6 = _ticker_to_code6(symbol)

    try:
        from dragon_eye.signals import score_technical, ma, check_volume, check_ma_alignment, atr
        from dragon_eye.data_models import Market

        market = Market.SH if code6.startswith("6") else (Market.BJ if code6.startswith(("4", "8")) else Market.SZ)
        reader = _get_tdx_reader()
        klines = reader.get_day_klines(code6, market)

        if not klines:
            return f"No technical data available for {symbol} (dragon_eye)"

        # 使用龙瞳信号函数计算技术指标
        tech = score_technical(klines)
        closes = [k.close for k in klines]

        # 格式化为报告文本（与 yfinance 输出格式对齐）
        lines = [f"# Technical Analysis for {symbol} (dragon_eye)"]
        lines.append(f"# Date: {curr_date}, Look-back: {look_back_days} days")
        lines.append("")

        direction = tech.get("direction", "neutral")
        direction_cn = {"bull": "多头", "bear": "空头", "neutral": "震荡"}.get(direction, direction)
        lines.append(f"**综合评分**: {tech.get('total_score', 0):.1f}/100")
        lines.append(f"**技术面判断**: {direction_cn} (Bull={tech.get('bull_score',0)}, Bear={tech.get('bear_score',0)})")
        lines.append("")

        # 均线系统
        ma5 = ma(closes, 5)
        ma10 = ma(closes, 10)
        ma20 = ma(closes, 20)
        ma60 = ma(closes, 60)
        cur_price = closes[-1]
        lines.append("## Moving Averages")
        lines.append(f"- MA5: {ma5[-1]:.2f} ({'上方' if cur_price > ma5[-1] else '下方'})")
        lines.append(f"- MA10: {ma10[-1]:.2f} ({'上方' if cur_price > ma10[-1] else '下方'})")
        lines.append(f"- MA20: {ma20[-1]:.2f} ({'上方' if cur_price > ma20[-1] else '下方'})")
        lines.append(f"- MA60: {ma60[-1]:.2f} ({'上方' if cur_price > ma60[-1] else '下方'})")
        lines.append(f"- MA10 Angle: {tech.get('ma_angle_10', 0):.1f}°")
        lines.append(f"- MA20 Angle: {tech.get('ma_angle_20', 0):.1f}°")
        lines.append("")

        # 均线排列
        try:
            align = check_ma_alignment(klines)
            if align and align.triggered:
                align_type = align.details.get("type", "unknown")
                lines.append(f"## MA Alignment: {align_type} (strength={align.strength})")
        except Exception:
            pass

        # 量价信号
        try:
            vol_sig = check_volume(klines)
            lines.append("## Volume Analysis")
            if vol_sig.is_expand:
                lines.append("- Status: **放量** (Volume Expansion)")
            elif vol_sig.is_shrink:
                lines.append("- Status: **缩量** (Volume Shrinkage)")
            else:
                lines.append("- Status: 正常 (Normal)")
            lines.append(f"- Volume Ratio: {vol_sig.volume_ratio:.2f}")
            lines.append("")
        except Exception:
            pass

        # 支撑压力位
        support = tech.get("support", 0)
        resistance = tech.get("resistance", 0)
        if support or resistance:
            lines.append("## Support & Resistance")
            lines.append(f"- Support: {support:.2f}")
            lines.append(f"- Resistance: {resistance:.2f}")
            lines.append("")

        # 信号列表
        signals = tech.get("signals", [])
        if signals:
            lines.append("## Active Signals")
            for sig in signals:
                sig_name = getattr(sig, 'name', str(sig))
                sig_dir = getattr(sig, 'direction', 'neutral')
                sig_strength = getattr(sig, 'strength', 0)
                if sig_strength > 0:
                    lines.append(f"- **{sig_name}**: direction={sig_dir}, strength={sig_strength}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Technical analysis error for {symbol}: {e}"


def get_fundamentals_dragon_eye(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date, yyyy-mm-dd"],
) -> str:
    """龙瞳版：基本面数据（base.dbf + AkShare，替代 yfinance）"""
    code6 = _ticker_to_code6(ticker)
    dbf = _get_dbf_reader()
    return dbf.get_financial_summary(code6)


def get_balance_sheet_dragon_eye(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """龙瞳版：资产负债表（base.dbf）"""
    code6 = _ticker_to_code6(ticker)
    dbf = _get_dbf_reader()
    fin = dbf.get_financial(code6)

    if not fin or not fin.is_valid():
        return f"No balance sheet data for {ticker} (dragon_eye)"

    lines = [
        f"# Balance Sheet for {ticker} (dragon_eye/base.dbf)",
        f"# Report date: {fin.update_date}",
        "",
        "## 资产（万元）",
        f"- 流动资产: {fin.current_assets:,.2f}",
        f"- 固定资产: {fin.fixed_assets:,.2f}",
        f"- 无形资产: {fin.intangible_assets:,.2f}",
        f"- 长期投资: {fin.long_term_invest:,.2f}",
        f"- **总资产**: {fin.total_assets:,.2f}",
        "",
        "## 负债（万元）",
        f"- 流动负债: {fin.current_liabilities:,.2f}",
        f"- 长期负债: {fin.long_term_liabilities:,.2f}",
        f"- **资产负债率**: {fin.debt_ratio:.2f}%",
        "",
        "## 股东权益（万元）",
        f"- 资本公积金: {fin.capital_reserve:,.2f}",
        f"- 未分配利润: {fin.undistributed:,.2f}",
        f"- **净资产**: {fin.net_assets:,.2f}",
        "",
        "## 关键比率",
        f"- **流动比率**: {fin.current_ratio:.2f}",
    ]
    return "\n".join(lines)


def get_cashflow_dragon_eye(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """龙瞳版：现金流数据（base.dbf 有限，标注说明）"""
    code6 = _ticker_to_code6(ticker)
    dbf = _get_dbf_reader()
    fin = dbf.get_financial(code6)

    if not fin or not fin.is_valid():
        return f"No cashflow data for {ticker} (dragon_eye)"

    lines = [
        f"# Cash Flow for {ticker} (dragon_eye/base.dbf)",
        f"# Report date: {fin.update_date}",
        "",
        "**注**: 通达信base.dbf不包含详细现金流量表。",
        "以下为从利润表和资产负债表推断的现金流指标：",
        "",
        f"- 净利润: {fin.net_profit:,.2f} 万元",
        f"- 营业利润: {fin.operating_profit:,.2f} 万元",
        f"- 投资收益: {fin.invest_income:,.2f} 万元",
        f"- 补贴收入: {fin.subsidy:,.2f} 万元",
        f"- 营业外收支: {fin.non_operating:,.2f} 万元",
        "",
        "如需详细现金流量表，可使用AkShare接口补充。",
    ]
    return "\n".join(lines)


def get_income_statement_dragon_eye(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """龙瞳版：利润表（base.dbf）"""
    code6 = _ticker_to_code6(ticker)
    dbf = _get_dbf_reader()
    fin = dbf.get_financial(code6)

    if not fin or not fin.is_valid():
        return f"No income statement data for {ticker} (dragon_eye)"

    lines = [
        f"# Income Statement for {ticker} (dragon_eye/base.dbf)",
        f"# Report date: {fin.update_date}",
        "",
        "## 收入（万元）",
        f"- **主营业务收入**: {fin.revenue:,.2f}",
        f"- 主营业务利润: {fin.main_profit:,.2f}",
        "",
        "## 利润（万元）",
        f"- 营业利润: {fin.operating_profit:,.2f}",
        f"- 投资收益: {fin.invest_income:,.2f}",
        f"- 补贴收入: {fin.subsidy:,.2f}",
        f"- 营业外收支: {fin.non_operating:,.2f}",
        f"- 利润总额: {fin.total_profit:,.2f}",
        f"- **净利润**: {fin.net_profit:,.2f}",
        "",
        "## 盈利能力",
        f"- **ROE**: {fin.roe:.2f}%",
        f"- **净利率**: {fin.net_profit_margin:.2f}%",
        f"- **每股收益**: {fin.eps_approx:.4f} 元",
        f"- **每股营收**: {fin.revenue_per_share:.4f} 元",
    ]
    return "\n".join(lines)


def get_news_dragon_eye(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """龙瞳版：A股个股新闻+资金流向（替代 yfinance 英文新闻）

    数据源优先级：
    1. 东方财富7x24快讯（实时财经新闻）
    2. 财新网头条新闻（stock_news_main_cx）
    3. AkShare主力资金流（个股资金面）
    4. 上证e互动（投资者问答）
    5. base.dbf行业+财务摘要（兜底）

    返回格式与 yfinance get_news_yfinance 一致（Markdown标题+摘要）。
    """
    code6 = _ticker_to_code6(ticker)
    market = _code6_to_market(code6)
    ind_reader = _get_industry_reader()
    industry = ind_reader.get_industry(code6)

    news_str = ""
    article_count = 0

    # ── 1. 东方财富7x24快讯 ──
    try:
        import requests as _req
        _sess = _req.Session()
        _sess.trust_env = False
        url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        params = {
            "client": "web",
            "biz": "web_news_col",
            "column": "350",
            "order": "1",
            "needInteractData": "0",
            "page_index": "1",
            "page_size": "20",
            "req_trace": "1",
            "fields": "title,showTime,mediaName,srcUrl,content,digest",
        }
        resp = _sess.get(url, params=params, timeout=10)
        data = resp.json()
        articles = data.get("data", {}).get("list", [])

        if articles:
            for a in articles[:15]:
                title = a.get("title", "No title")
                media = a.get("mediaName", "Unknown")
                show_time = a.get("showTime", "")
                digest = a.get("digest", "") or a.get("content", "")
                if digest and len(digest) > 200:
                    digest = digest[:200] + "..."
                link = a.get("srcUrl", "")

                news_str += f"### {title} (source: {media})\n"
                if show_time:
                    news_str += f"Time: {show_time}\n"
                if digest:
                    news_str += f"{digest}\n"
                if link:
                    news_str += f"Link: {link}\n"
                news_str += "\n"
                article_count += 1
    except Exception:
        pass  # 东方财富不可用时静默跳过

    # ── 2. 财新网头条（AkShare stock_news_main_cx）──
    try:
        ak = _get_akshare_bridge()._get_ak()
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            for _, row in df.head(10).iterrows():
                title = row.get("summary", "No title")
                tag = row.get("tag", "")
                link = row.get("url", "")
                news_str += f"### {title} (source: 财新网/{tag})\n"
                if link:
                    news_str += f"Link: {link}\n"
                news_str += "\n"
                article_count += 1
    except Exception:
        pass

    # ── 3. 个股资金流向（AkShare）──
    try:
        ak = _get_akshare_bridge()._get_ak()
        mkt = "sh" if code6.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=code6, market=mkt)
        if df is not None and not df.empty:
            # AkShare返回倒序（第0行最老），取tail拿最新数据
            recent_df = df.tail(5)
            news_str += "## Individual Stock Fund Flow (Recent)\n\n"
            for _, row in recent_df.iterrows():
                date = row.get("日期", "")
                close = row.get("收盘价", 0)
                chg = row.get("涨跌幅", 0)
                main_net = row.get("主力净流入-净额", 0)
                main_pct = row.get("主力净流入-净占比", 0)
                super_net = row.get("超大单净流入-净额", 0)
                news_str += f"- {date}: Close {close}, Change {chg:.2f}%, "
                news_str += f"Main Force Net {main_net/1e4:.0f}万({main_pct:.2f}%), "
                news_str += f"Super Large Net {super_net/1e4:.0f}万\n"
                article_count += 1
    except Exception:
        pass

    # ── 4. 上证e互动（投资者问答）──
    try:
        ak = _get_akshare_bridge()._get_ak()
        df = ak.stock_sns_sseinfo(symbol=code6)
        if df is not None and not df.empty:
            news_str += "## Investor Q&A (SSE e-Interaction)\n\n"
            for _, row in df.head(5).iterrows():
                q = row.get("问题", "")
                a = row.get("回答", "")
                t = row.get("问题时间", "")
                if q:
                    news_str += f"- Q ({t}): {q[:80]}\n"
                    if a:
                        news_str += f"  A: {a[:80]}\n"
                article_count += 1
    except Exception:
        pass

    # ── 5. 兜底：行业+财务摘要 ──
    if article_count == 0:
        news_str += f"No real-time news available for {ticker}.\n\n"
        # 至少提供行业和财务信息
        if industry:
            news_str += f"**Industry**: {industry}\n\n"
        dbf = _get_dbf_reader()
        fin = dbf.get_financial(code6)
        if fin and fin.is_valid():
            news_str += "## Financial Summary (fallback)\n\n"
            news_str += f"- Latest report: {fin.update_date}\n"
            if fin.net_profit > 0:
                news_str += f"- Net Profit: {fin.net_profit:,.0f}万元, ROE: {fin.roe:.2f}%\n"
            else:
                news_str += f"- Net Loss: {fin.net_profit:,.0f}万元\n"
            if fin.revenue > 0:
                news_str += f"- Revenue: {fin.revenue:,.0f}万元, Net Margin: {fin.net_profit_margin:.2f}%\n"

    header = f"## {ticker} A-Stock News & Fund Flow, from {start_date} to {end_date}:\n\n"
    if industry:
        header += f"**Industry**: {industry}\n\n"

    # ── 伴随存档: 新闻自动归档 ──
    try:
        lk = _get_lk()
        if lk:
            today = datetime.now().strftime("%Y-%m-%d")
            # 东方财富新闻存档
            if articles:
                news_records = []
                for a in articles[:15]:
                    news_records.append({
                        "news_date": today,
                        "title": a.get("title", ""),
                        "content": (a.get("digest", "") or a.get("content", ""))[:500],
                        "url": a.get("srcUrl", ""),
                    })
                lk.archive_news("eastmoney", news_records)
            # 资金流存档（同 get_insider_transactions 的数据）
            if df is not None and not df.empty:
                fund_records = []
                for _, row in df.tail(10).iterrows():
                    fund_records.append({
                        "trade_date": str(row.get("日期", ""))[:10],
                        "close": float(row.get("收盘价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "main_net": float(row.get("主力净流入-净额", 0)),
                        "main_pct": float(row.get("主力净流入-净占比", 0)),
                        "super_net": float(row.get("超大单净流入-净额", 0)),
                        "large_net": float(row.get("大单净流入-净额", 0)),
                        "medium_net": float(row.get("中单净流入-净额", 0)),
                        "small_net": float(row.get("小单净流入-净额", 0)),
                    })
                lk.archive_fund_flow(code6, fund_records)
    except Exception:
        pass  # 存档失败不影响主流程

    return header + news_str


def get_global_news_dragon_eye(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """龙瞳版：A股宏观新闻+市场概览（替代 yfinance global news）

    数据源优先级：
    1. 东方财富7x24快讯（实时财经）
    2. 央视新闻联播（news_cctv）— 政策/宏观风向
    3. 百度财经日历（news_economic_baidu）— 经济数据发布
    4. 北向资金+大盘资金面

    返回格式与 yfinance get_global_news_yfinance 一致。
    """
    from datetime import datetime as _dt, timedelta as _td
    curr_dt = _dt.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - _td(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    news_str = ""
    article_count = 0

    # ── 1. 东方财富7x24快讯 ──
    try:
        import requests as _req
        _sess = _req.Session()
        _sess.trust_env = False
        url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        params = {
            "client": "web",
            "biz": "web_news_col",
            "column": "350",
            "order": "1",
            "needInteractData": "0",
            "page_index": "1",
            "page_size": str(min(limit * 2, 30)),
            "req_trace": "1",
            "fields": "title,showTime,mediaName,srcUrl,content,digest",
        }
        resp = _sess.get(url, params=params, timeout=10)
        data = resp.json()
        articles = data.get("data", {}).get("list", [])

        if articles:
            news_str += "## Market Flash News (EastMoney 7x24)\n\n"
            for a in articles[:limit]:
                title = a.get("title", "No title")
                media = a.get("mediaName", "Unknown")
                show_time = a.get("showTime", "")
                digest = a.get("digest", "") or a.get("content", "")
                if digest and len(digest) > 200:
                    digest = digest[:200] + "..."
                news_str += f"### {title} (source: {media})\n"
                if show_time:
                    news_str += f"Time: {show_time}\n"
                if digest:
                    news_str += f"{digest}\n"
                news_str += "\n"
                article_count += 1
    except Exception:
        pass

    # ── 2. 央视新闻联播 ──
    try:
        ak = _get_akshare_bridge()._get_ak()
        # 尝试最近几天的新闻联播
        for days_back in range(look_back_days + 1):
            check_date = (curr_dt - _td(days=days_back)).strftime("%Y%m%d")
            try:
                df = ak.news_cctv(date=check_date)
                if df is not None and not df.empty:
                    if article_count == 0 or days_back == 0:
                        news_str += "## CCTV News Broadcast (Policy & Macro)\n\n"
                    for _, row in df.head(3).iterrows():
                        title = row.get("title", "")
                        content = row.get("content", "")
                        if content and len(content) > 300:
                            content = content[:300] + "..."
                        if title:
                            news_str += f"### {title} (source: CCTV)\n"
                            if content:
                                news_str += f"{content}\n"
                            news_str += "\n"
                            article_count += 1
                    break  # 找到最近一天的就够了
            except Exception:
                continue
    except Exception:
        pass

    # ── 3. 百度财经日历 ──
    try:
        ak = _get_akshare_bridge()._get_ak()
        df = ak.news_economic_baidu()
        if df is not None and not df.empty:
            # 过滤最近 look_back_days 天
            recent = df[df["日期"] >= start_dt.date()]
            if not recent.empty:
                news_str += "## Economic Calendar (Baidu Finance)\n\n"
                for _, row in recent.head(limit).iterrows():
                    region = row.get("地区", "")
                    event = row.get("事件", "")
                    actual = row.get("公布", "")
                    expected = row.get("预期", "")
                    prev = row.get("前值", "")
                    importance = row.get("重要性", 0)
                    stars = "⭐" * min(int(importance), 3) if importance else ""
                    news_str += f"- [{region}] {event}: Actual={actual}, Expected={expected}, Prev={prev} {stars}\n"
                news_str += "\n"
                article_count += 1
    except Exception:
        pass

    # ── 4. 北向资金 ──
    try:
        ak = _get_akshare_bridge()._get_ak()
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and not df.empty:
            news_str += "## Northbound Capital Flow (HK-SZ-SH Connect)\n\n"
            for _, row in df.head(limit).iterrows():
                direction = str(row.get("资金方向", ""))
                amount = row.get("当日净流入(元)", 0)
                if amount:
                    news_str += f"- {direction}: Net Inflow {amount/1e8:.2f} 亿元\n"
            news_str += "\n"
    except Exception:
        pass

    if article_count == 0:
        return f"No global news found for {curr_date}"

    header = f"## A-Stock Market & Macro News, from {start_date} to {curr_date}:\n\n"
    return header + news_str


def get_insider_transactions_dragon_eye(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """龙瞳版：A股资金流向+股东结构（替代 yfinance insider transactions）

    A股没有美股insider transactions概念，替代方案：
    1. 主力资金流向（近10日）— 反映机构/大户动向
    2. 股本结构 — 流通比例、限售股解禁
    3. 十大股东变动（AkShare，如可用）

    返回格式与 yfinance get_insider_transactions 一致。
    """
    code6 = _ticker_to_code6(ticker)
    dbf = _get_dbf_reader()
    fin = dbf.get_financial(code6)

    lines = [
        f"# A-Stock Capital Flow & Shareholder Info for {ticker} (dragon_eye)",
        "",
    ]

    # ── 1. 主力资金流向（替代 insider 信号）──
    try:
        ak = _get_akshare_bridge()._get_ak()
        mkt = "sh" if code6.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=code6, market=mkt)
        if df is not None and not df.empty:
            lines.append("## Institutional Fund Flow (Last 10 Days)")
            lines.append("")
            lines.append("| Date | Close | Change% | Main Net(万) | Main% | SuperLarge(万) | Large(万) |")
            lines.append("|------|-------|---------|-------------|-------|---------------|----------|")
            # AkShare返回倒序（第0行最老），取tail拿最新10日数据
            recent_df = df.tail(10)
            for _, row in recent_df.iterrows():
                date = row.get("日期", "")
                close = row.get("收盘价", 0)
                chg = row.get("涨跌幅", 0)
                main_net = row.get("主力净流入-净额", 0) / 1e4
                main_pct = row.get("主力净流入-净占比", 0)
                super_net = row.get("超大单净流入-净额", 0) / 1e4
                large_net = row.get("大单净流入-净额", 0) / 1e4
                lines.append(f"| {date} | {close} | {chg:.2f}% | {main_net:.0f} | {main_pct:.2f}% | {super_net:.0f} | {large_net:.0f} |")
            lines.append("")
            lines.append("**Note**: Main Force (主力) = SuperLarge + Large orders. ")
            lines.append("Positive = Net Inflow (Institutions buying), Negative = Net Outflow (Selling).")
            lines.append("")
    except Exception as e:
        lines.append(f"- Fund flow data unavailable: {e}")
        lines.append("")

    # ── 2. 股本结构 ──
    lines.append("## Share Capital Structure")
    lines.append("")
    if fin and fin.is_valid():
        lines.append(f"- Total Shares: {fin.total_shares:,.2f} 万股")
        lines.append(f"- Circulating A-Shares: {fin.circulating_a:,.2f} 万股")
        if fin.b_shares:
            lines.append(f"- B-Shares: {fin.b_shares:,.2f} 万股")
        if fin.h_shares:
            lines.append(f"- H-Shares: {fin.h_shares:,.2f} 万股")
        if fin.total_shares > 0:
            circ_pct = fin.circulating_a / fin.total_shares * 100
            lines.append(f"- Circulating Ratio: {circ_pct:.1f}%")
            if circ_pct < 50:
                lines.append("  ⚠️ Low float — potential liquidity risk or lock-up period")
    else:
        lines.append(f"- No share capital data for {code6}")
    lines.append("")

    # ── 3. 关键财务指标（关联 insider 信号判断）──
    if fin and fin.is_valid():
        lines.append("## Key Financial Indicators")
        lines.append("")
        lines.append(f"- Net Profit: {fin.net_profit:,.0f} 万元")
        lines.append(f"- ROE: {fin.roe:.2f}%")
        lines.append(f"- Net Margin: {fin.net_profit_margin:.2f}%")
        lines.append(f"- EPS (approx): {fin.eps_approx:.4f} 元")
        lines.append(f"- Debt Ratio: {fin.debt_ratio:.2f}%")
        lines.append(f"- Report Date: {fin.update_date}")

    # ── 伴随存档: 资金流向数据自动归档 ──
    try:
        lk = _get_lk()
        if lk and df is not None and not df.empty:
            fund_records = []
            for _, row in df.tail(10).iterrows():
                fund_records.append({
                    "trade_date": str(row.get("日期", ""))[:10],
                    "close": float(row.get("收盘价", 0)),
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "main_net": float(row.get("主力净流入-净额", 0)),
                    "main_pct": float(row.get("主力净流入-净占比", 0)),
                    "super_net": float(row.get("超大单净流入-净额", 0)),
                    "large_net": float(row.get("大单净流入-净额", 0)),
                    "medium_net": float(row.get("中单净流入-净额", 0)),
                    "small_net": float(row.get("小单净流入-净额", 0)),
                })
            lk.archive_fund_flow(code6, fund_records)
    except Exception:
        pass  # 存档失败不影响主流程

    return "\n".join(lines)
