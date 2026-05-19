"""
dragon_eye.analysis.stock_analyzer — 个股深度分析器

整合通达信K线数据、技术信号、板块产业链、估值分析，
以及 TradingAgents 10-Agent 多模型管线深度分析，
生成完整的个股分析报告。

Agent管线: Market Analyst → Social Analyst → News Analyst → Fundamentals Analyst
         → Bull Researcher ↔ Bear Researcher → Research Manager
         → Trader → Aggressive/Conservative/Neutral Debator → Portfolio Manager
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..tdx_reader import TdxReader, get_reader
from ..akshare_bridge import AkShareBridge, get_bridge
from ..data_models import Market, market_from_code, classify_stock, StockType, Kline
from ..signals import ma, score_technical, check_volume, check_ma_cross, check_ma_alignment
from ..sector.valuation import ValuationAnalyzer
from ..sector.sector_data import SectorData
from ..strategy.bottom_breakout import BottomBreakout
from ..strategy.pullback_buy import PullbackBuy
from ..strategy.base_strategy import StrategyResult

logger = logging.getLogger(__name__)


# ============================================================
# TradingAgents 10-Agent 管线分析结果
# ============================================================

@dataclass
class TAAnalysisResult:
    """TradingAgents 10-Agent 管线分析结果

    管线流程:
    1. Market Analyst   — 技术面深度报告（均线/MACD/RSI/布林带/VWMA）
    2. Social Analyst   — 社交媒体情绪报告
    3. News Analyst     — 新闻与内部人交易报告
    4. Fundamentals    — 基本面深度报告（营收/利润/现金流/负债）
    5. Bull Researcher  — 看多论点
    6. Bear Researcher  — 看空论点
    7. Research Manager — 投资计划（Buy/Overweight/Hold/Underweight/Sell）
    8. Trader           — 交易提案（入场价/止损/仓位）
    9. Risk Debate      — 激进/保守/中性三方辩论
    10. Portfolio Mgr   — 最终决策（5级评级+投资论点+目标价+时间维度）
    """
    ticker: str = ""
    trade_date: str = ""
    rating: str = ""               # Buy/Overweight/Hold/Underweight/Sell
    executive_summary: str = ""    # 执行摘要
    investment_thesis: str = ""    # 投资论点
    price_target: float = 0.0      # 目标价
    time_horizon: str = ""         # 建议持有期

    # 4份分析师报告
    market_report: str = ""
    sentiment_report: str = ""
    news_report: str = ""
    fundamentals_report: str = ""

    # 投资辩论
    investment_plan: str = ""
    trader_investment_plan: str = ""

    # 最终决策全文
    final_trade_decision: str = ""

    # 状态日志路径
    log_dir: str = ""

    @property
    def rating_cn(self) -> str:
        """中文评级"""
        cn_map = {
            "Buy": "买入", "Overweight": "超配",
            "Hold": "持有", "Underweight": "低配", "Sell": "卖出",
        }
        return cn_map.get(self.rating, self.rating)

    @property
    def has_reports(self) -> bool:
        return bool(self.market_report or self.fundamentals_report)


# ============================================================
# 分析报告数据类
# ============================================================

@dataclass
class AnalysisReport:
    """个股深度分析报告"""
    code: str
    name: str = ""
    market: str = ""

    # 技术面
    trend: str = ""                        # 多头/空头/震荡
    ma_status: dict = field(default_factory=dict)   # MA5/10/20/60状态
    support_price: float = 0.0             # 支撑位
    resistance_price: float = 0.0          # 压力位

    # 量价
    volume_status: str = ""                # 放量/缩量/正常
    turnover_rate: float = 0.0             # 换手率

    # 估值
    pe_ttm: float = 0.0
    pb: float = 0.0
    valuation_level: str = ""              # 低估/合理/高估

    # 板块
    sector: str = ""
    chain_position: str = ""               # 在产业链中的位置

    # 策略信号
    signals: list = field(default_factory=list)  # StrategyResult列表

    # 综合
    total_score: float = 0.0
    recommendation: str = ""               # 买入/持有/观望/卖出
    summary: str = ""

    # TradingAgents 10-Agent 管线结果
    ta_result: Optional[TAAnalysisResult] = field(default=None, repr=False)


# ============================================================
# 个股深度分析器
# ============================================================

class StockAnalyzer:
    """个股深度分析器

    整合通达信K线数据、技术信号、板块产业链、估值分析，
    生成完整的个股分析报告。

    用法:
        analyzer = StockAnalyzer()
        report = analyzer.analyze("603618")
        sr = analyzer.find_support_resistance("603618")
        signals = analyzer.check_signals("603618")
    """

    def __init__(self, reader: Optional[TdxReader] = None, bridge: Optional[AkShareBridge] = None):
        self._reader = reader or get_reader()
        self._bridge = bridge or get_bridge()  # 全局单例
        self._valuation = ValuationAnalyzer(reader=self._reader, bridge=self._bridge)
        self._sector_data = SectorData(bridge=self._bridge)
        self._bottom_breakout = BottomBreakout()
        self._pullback_buy = PullbackBuy()
        self._name_map: Optional[dict[str, str]] = None

    # ----------------------------------------------------------
    # 核心方法
    # ----------------------------------------------------------

    def analyze(self, code6: str, market: Optional[Market] = None) -> AnalysisReport:
        """对单只股票进行全面深度分析

        包括:
        1. 基本信息（名称、市场、类型）
        2. 技术面分析（均线排列、MACD趋势、支撑压力位）
        3. 量价分析（放量缩量、换手率、资金流向）
        4. 估值分析（PE/PB、历史分位）
        5. 板块归属（所属行业/概念）
        6. 策略信号（底部起爆/强势回调触发状态）
        7. 综合评分和操作建议
        """
        if market is None:
            market = market_from_code(code6)

        report = AnalysisReport(code=code6, market=market.value)

        # 1. 基本信息
        self._fill_basic_info(report, code6, market)

        # 2. 获取K线数据
        klines = self._reader.get_day_klines(code6, market)
        if not klines:
            report.summary = "无法获取K线数据，可能通达信数据目录未配置"
            return report

        # 3. 技术面分析
        self._analyze_technical(report, klines)

        # 4. 量价分析
        self._analyze_volume(report, klines, code6)

        # 5. 估值分析
        self._analyze_valuation(report, code6)

        # 6. 板块归属
        self._analyze_sector(report, code6)

        # 7. 策略信号
        report.signals = self.check_signals(code6, market)

        # 8. 综合评分
        self._calc_total_score(report, klines)

        return report

    def find_support_resistance(self, code6: str, market: Optional[Market] = None) -> dict:
        """找出关键支撑位和压力位

        用近60日K线数据:
        - 支撑位: 近30日低点、MA20、前期成交密集区
        - 压力位: 近30日高点、MA60、前期成交密集区
        """
        if market is None:
            market = market_from_code(code6)

        klines = self._reader.get_day_klines(code6, market)
        if len(klines) < 30:
            return {"support": 0.0, "resistance": 0.0}

        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]

        # 近30日数据
        recent_30 = klines[-30:] if len(klines) >= 30 else klines
        low_30 = min(k.low for k in recent_30)
        high_30 = max(k.high for k in recent_30)

        # MA值
        ma20_vals = ma(closes, 20)
        ma60_vals = ma(closes, 60)
        ma20_val = ma20_vals[-1] if ma20_vals and ma20_vals[-1] is not None else 0
        ma60_val = ma60_vals[-1] if ma60_vals and ma60_vals[-1] is not None else 0

        # 成交密集区: 近60日成交量加权价格
        recent_60 = klines[-60:] if len(klines) >= 60 else klines
        total_vol = sum(k.volume for k in recent_60)
        vwap = 0.0
        if total_vol > 0:
            vwap = sum(k.close * k.volume for k in recent_60) / total_vol

        # 支撑位: 取近30日低点、MA20、VWAP中最低且接近当前价的
        cur_price = closes[-1]
        support_candidates = []
        if low_30 > 0:
            support_candidates.append(low_30)
        if ma20_val > 0 and ma20_val < cur_price:
            support_candidates.append(ma20_val)
        if vwap > 0 and vwap < cur_price:
            support_candidates.append(vwap)
        support = max(support_candidates) if support_candidates else low_30

        # 压力位: 取近30日高点、MA60、VWAP中最高且高于当前价的
        resistance_candidates = []
        if high_30 > cur_price:
            resistance_candidates.append(high_30)
        if ma60_val > cur_price:
            resistance_candidates.append(ma60_val)
        if vwap > cur_price:
            resistance_candidates.append(vwap)
        resistance = min(resistance_candidates) if resistance_candidates else high_30

        return {
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "support_sources": {
                "low_30d": round(low_30, 2),
                "ma20": round(ma20_val, 2) if ma20_val else 0,
                "vwap": round(vwap, 2),
            },
            "resistance_sources": {
                "high_30d": round(high_30, 2),
                "ma60": round(ma60_val, 2) if ma60_val else 0,
                "vwap": round(vwap, 2),
            },
        }

    def check_signals(self, code6: str, market: Optional[Market] = None) -> list[StrategyResult]:
        """检查所有策略信号

        对该股同时运行底部起爆和强势回调策略，
        返回触发的信号列表。
        """
        if market is None:
            market = market_from_code(code6)

        klines = self._reader.get_day_klines(code6, market)
        if not klines:
            return []

        name = self._get_stock_name(code6)
        triggered = []

        # 底部起爆
        try:
            bb_result = self._bottom_breakout.scan(klines, code=code6, name=name)
            if bb_result.triggered:
                triggered.append(bb_result)
        except Exception as e:
            logger.debug("底部起爆策略异常 %s: %s", code6, e)

        # 强势回调
        try:
            pb_result = self._pullback_buy.scan(klines, code=code6, name=name)
            if pb_result.triggered:
                triggered.append(pb_result)
        except Exception as e:
            logger.debug("强势回调策略异常 %s: %s", code6, e)

        # 按信号强度降序排列
        triggered.sort(key=lambda r: r.strength, reverse=True)
        return triggered

    # ----------------------------------------------------------
    # TradingAgents 10-Agent 管线深度分析
    # ----------------------------------------------------------

    @staticmethod
    def code6_to_yf_ticker(code6: str, market: Market) -> str:
        """6位代码 → yfinance ticker
        例: 603618 + SH → 603618.SS,  002149 + SZ → 002149.SZ
        """
        suffix_map = {Market.SH: ".SS", Market.SZ: ".SZ"}
        suffix = suffix_map.get(market, ".SS")
        return f"{code6}{suffix}"

    # ----------------------------------------------------------
    # 离线模式：从已有 TradingAgents 日志加载报告
    # ----------------------------------------------------------

    @staticmethod
    def ta_load_from_logs(
        code6: str,
        market: Optional[Market] = None,
        trade_date: Optional[str] = None,
    ) -> Optional[TAAnalysisResult]:
        """从 TradingAgents 已有 JSON 日志加载分析报告（离线模式）

        日志结构: ~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json

        当 yfinance 被限速或网络不通时，可以加载之前跑过的报告。

        Args:
            code6: 6位股票代码
            market: 市场类型
            trade_date: 交易日期，None则自动搜索最新

        Returns:
            TAAnalysisResult 或 None（无匹配日志）
        """
        if market is None:
            market = market_from_code(code6)

        ticker = StockAnalyzer.code6_to_yf_ticker(code6, market)

        # TradingAgents 实际日志目录
        logs_base = Path.home() / ".tradingagents" / "logs" / ticker
        strategy_logs = logs_base / "TradingAgentsStrategy_logs"

        if not strategy_logs.exists():
            return None

        # 查找日志文件
        if trade_date is None:
            # 找最新的 JSON 日志
            json_files = sorted(strategy_logs.glob("full_states_log_*.json"), reverse=True)
            if not json_files:
                return None
            log_file = json_files[0]
            # 从文件名提取日期: full_states_log_2026-05-12.json → 2026-05-12
            trade_date = log_file.stem.replace("full_states_log_", "")
        else:
            log_file = strategy_logs / f"full_states_log_{trade_date}.json"
            if not log_file.exists():
                # 尝试模糊匹配日期格式
                candidates = list(strategy_logs.glob(f"full_states_log_*{trade_date}*.json"))
                if candidates:
                    log_file = sorted(candidates, reverse=True)[0]
                    trade_date = log_file.stem.replace("full_states_log_", "")
                else:
                    return None

        # 读取 JSON 日志
        try:
            import json as _json
            with open(log_file, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except Exception as e:
            logger.error("读取日志文件失败: %s → %s", log_file, e)
            return None

        # 从 JSON 提取各 Agent 报告
        result = TAAnalysisResult(
            ticker=ticker,
            trade_date=trade_date,
            market_report=data.get("market_report", "") or "",
            sentiment_report=data.get("sentiment_report", "") or "",
            news_report=data.get("news_report", "") or "",
            fundamentals_report=data.get("fundamentals_report", "") or "",
        )

        # 投资辩论
        invest_debate = data.get("investment_debate_state", {})
        if isinstance(invest_debate, dict):
            result.investment_plan = invest_debate.get("judge_decision", "") or ""

        result.trader_investment_plan = data.get("trader_investment_decision", "") or data.get("trader_investment_plan", "") or ""

        # 风险辩论
        risk_debate = data.get("risk_debate_state", {})
        if isinstance(risk_debate, dict):
            result.final_trade_decision = risk_debate.get("judge_decision", "") or ""

        # 如果风险辩论无结果，尝试直接用 final_trade_decision
        if not result.final_trade_decision:
            result.final_trade_decision = data.get("final_trade_decision", "") or ""

        # 从trader提案提取Action作为评级
        trader_text = result.trader_investment_plan
        action = StockAnalyzer._extract_trader_action(trader_text)
        if action:
            result.rating = action

        # 从最终决策提取结构化信息
        final_text = result.final_trade_decision
        if final_text:
            StockAnalyzer._parse_final_decision_static(result, final_text)

        # 从trader提案提取入场价作为目标价参考
        if trader_text and not result.price_target:
            import re
            m = re.search(r"\*\*Entry Price\*\*:\s*([\d.]+)", trader_text)
            if m:
                result.price_target = float(m.group(1))

        # 日志目录（指向文件所在目录）
        result.log_dir = str(log_file.parent)

        logger.info("从JSON日志加载 TradingAgents 报告: %s (%s) → %s", ticker, trade_date, result.rating)
        return result

    @staticmethod
    def _extract_trader_action(text: str) -> str:
        """从Trader投资提案提取Action (Buy/Hold/Sell)"""
        import re
        # 匹配 **Action**: Sell / **Action**: Buy / **Action**: Hold
        m = re.search(r"\*\*Action\*\*:\s*(Buy|Sell|Hold|Overweight|Underweight)", text, re.IGNORECASE)
        if m:
            action = m.group(1).capitalize()
            # Trader用3级，映射到5级
            action_map = {"Buy": "Buy", "Sell": "Sell", "Hold": "Hold"}
            return action_map.get(action, action)
        # 备选: FINAL TRANSACTION PROPOSAL: **SELL**
        m = re.search(r"FINAL TRANSACTION PROPOSAL:\s*\*\*(\w+)\*\*", text)
        if m:
            action = m.group(1).capitalize()
            action_map = {"Buy": "Buy", "Sell": "Sell", "Hold": "Hold"}
            return action_map.get(action, action)
        return ""

    @staticmethod
    def _parse_final_decision_static(result: TAAnalysisResult, text: str) -> None:
        """从Portfolio Manager的决策文本中提取结构化字段（静态版本）"""
        import re

        if not text:
            return

        # 提取目标价
        m = re.search(r"\*\*Price Target\*\*:\s*([\d.]+)", text)
        if m:
            result.price_target = float(m.group(1))

        # 提取时间维度
        m = re.search(r"\*\*Time Horizon\*\*:\s*(.+?)(?:\n|$)", text)
        if m:
            result.time_horizon = m.group(1).strip()

        # 提取执行摘要
        m = re.search(r"\*\*Executive Summary\*\*:\s*(.+?)(?=\n\*\*|\Z)", text, re.DOTALL)
        if m:
            result.executive_summary = m.group(1).strip()

        # 提取投资论点
        m = re.search(r"\*\*Investment Thesis\*\*:\s*(.+?)(?=\n\*\*|\Z)", text, re.DOTALL)
        if m:
            result.investment_thesis = m.group(1).strip()

        # 如果没有结构化提取，生成摘要
        if not result.executive_summary and not result.investment_thesis:
            # 截取前500字作为摘要
            result.executive_summary = text[:500] + ("..." if len(text) > 500 else "")
            result.investment_thesis = text

    def ta_deep_analysis(
        self,
        code6: str,
        market: Optional[Market] = None,
        trade_date: Optional[str] = None,
        selected_analysts: list[str] | None = None,
        output_language: str = "Chinese",
        offline: bool = False,
    ) -> TAAnalysisResult:
        """调用 TradingAgents 10-Agent 管线进行深度分析

        管线流程（10个Agent协作）:
        1. Market Analyst     — 技术面（均线/MACD/RSI/布林带/ATR/VWMA）
        2. Social Analyst     — 社交媒体情绪
        3. News Analyst       — 新闻 + 内部人交易 + 全球宏观
        4. Fundamentals      — 财报深度（营收/利润/现金流/负债表）
        5. Bull Researcher    — 看多论点
        6. Bear Researcher    — 看空论点
        7. Research Manager   — 综合投资计划（5级评级）
        8. Trader             — 交易执行提案（入场价/止损/仓位）
        9. Aggressive/Conservative/Neutral — 风险三方辩论
        10. Portfolio Manager  — 最终决策（评级+论点+目标价+时间维度）

        Args:
            code6: 6位股票代码
            market: 市场类型，None自动判断
            trade_date: 交易日期，默认今天
            selected_analysts: 选用的分析师，默认全选 ["market","social","news","fundamentals"]
            output_language: 报告语言，默认中文
            offline: 离线模式，从已有日志加载报告（无需API调用）

        Returns:
            TAAnalysisResult 包含所有Agent的报告和最终决策
        """
        if market is None:
            market = market_from_code(code6)

        # 离线模式优先：从已有日志加载（不设默认日期，让load函数自动找最新）
        if offline:
            result = self.ta_load_from_logs(code6, market, trade_date)
            if result:
                return result
            # 无日志则降级
            ticker = self.code6_to_yf_ticker(code6, market)
            return TAAnalysisResult(
                ticker=ticker,
                trade_date=trade_date or datetime.now().strftime("%Y-%m-%d"),
                final_trade_decision="离线模式：未找到已有分析报告，请先在线运行一次",
            )

        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        if selected_analysts is None:
            selected_analysts = ["market", "social", "news", "fundamentals"]

        # 转换为 yfinance ticker 格式
        ticker = self.code6_to_yf_ticker(code6, market)

        result = TAAnalysisResult(
            ticker=ticker,
            trade_date=trade_date,
        )

        try:
            # 设置代理环境变量（yfinance需要访问yahoo.com）
            # 关键修复：同时设置NO_PROXY排除国内站点，避免AkShare/东方财富也走代理
            if "http_proxy" not in os.environ and "HTTP_PROXY" not in os.environ:
                # 检测代理是否可用（1秒超时，会话内缓存结果避免反复检测）
                if not hasattr(self, "_proxy_checked"):
                    self._proxy_checked = True
                    self._proxy_ok = False
                    try:
                        import requests as _req
                        _sess = _req.Session()
                        _sess.trust_env = False
                        proxy_addr = os.environ.get("DRAGON_EYE_PROXY", "http://127.0.0.1:7897")
                        _resp = _sess.get(proxy_addr, timeout=1)
                        self._proxy_ok = True
                        self._proxy_addr = proxy_addr
                    except Exception:
                        pass

                if self._proxy_ok:
                    os.environ["http_proxy"] = self._proxy_addr
                    os.environ["https_proxy"] = self._proxy_addr
                else:
                    logger.warning("代理不可用，yfinance可能无法访问（国内网络限制）")

            # 无论代理是否设置，都要排除国内站点走代理
            no_proxy = ",".join([
                "*.eastmoney.com", "eastmoney.com",
                "*.sina.com.cn", "sina.com.cn",
                "*.gtimg.cn", "gtimg.cn",
                "*.qq.com", "qq.com",
                "*.10jqka.com.cn", "10jqka.com.cn",
                "localhost", "127.0.0.1",
            ])
            existing_no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
            if existing_no_proxy:
                no_proxy = f"{existing_no_proxy},{no_proxy}"
            os.environ["NO_PROXY"] = no_proxy
            os.environ["no_proxy"] = no_proxy

            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.default_config import DEFAULT_CONFIG
            from dotenv import load_dotenv

            load_dotenv()

            # 构建配置 — DeepSeek Chat
            config = DEFAULT_CONFIG.copy()
            config["llm_provider"] = "deepseek"
            config["deep_think_llm"] = "deepseek-chat"
            config["quick_think_llm"] = "deepseek-chat"
            config["max_debate_rounds"] = 1
            config["max_risk_discuss_rounds"] = 1
            config["output_language"] = output_language
            config["data_vendors"] = {
                "core_stock_apis": "dragon_eye,yfinance",
                "technical_indicators": "dragon_eye,yfinance",
                "fundamental_data": "dragon_eye,yfinance",
                "news_data": "dragon_eye,yfinance",
            }

            logger.info("TradingAgents 10-Agent 管线启动: %s (%s)", ticker, trade_date)

            ta = TradingAgentsGraph(
                selected_analysts=selected_analysts,
                debug=False,
                config=config,
            )

            # 🔑 注入A股数据到 memory_log 的 past_context
            # TradingAgents 的 _run_graph() 会自动读取 memory_log.get_past_context()
            # 我们在调用 propagate 前，把A股真实数据写进去
            a_stock_context = self._build_a_stock_context(code6, market)
            if a_stock_context:
                ta.memory_log.inject_a_stock_context(ticker, a_stock_context)

            final_state, decision = ta.propagate(ticker, trade_date)

            # 提取各Agent报告
            result.market_report = final_state.get("market_report", "")
            result.sentiment_report = final_state.get("sentiment_report", "")
            result.news_report = final_state.get("news_report", "")
            result.fundamentals_report = final_state.get("fundamentals_report", "")

            # 投资辩论
            invest_debate = final_state.get("investment_debate_state", {})
            if isinstance(invest_debate, dict):
                result.investment_plan = invest_debate.get("judge_decision", "")

            result.trader_investment_plan = final_state.get("trader_investment_plan", "")

            # 风险辩论
            risk_debate = final_state.get("risk_debate_state", {})
            if isinstance(risk_debate, dict):
                result.final_trade_decision = risk_debate.get("judge_decision", "")

            # 最终决策
            result.rating = decision  # Buy/Overweight/Hold/Underweight/Sell

            # 从trader提案提取Action（如果最终决策没给评级）
            if not result.rating and result.trader_investment_plan:
                result.rating = self._extract_trader_action(result.trader_investment_plan)

            # 从最终决策文本中提取结构化信息
            final_decision_text = final_state.get("final_trade_decision", "")
            self._parse_final_decision(result, final_decision_text)

            # 日志目录
            results_dir = config.get("results_dir", "")
            if results_dir:
                safe_ticker = ticker.replace(".", "_")
                result.log_dir = str(Path(results_dir) / safe_ticker / trade_date / "reports")

            # 如果在线运行成功但没记录log_dir，尝试从默认路径查找
            if not result.log_dir:
                default_log = Path.home() / ".tradingagents" / "logs" / ticker / trade_date / "reports"
                if default_log.exists():
                    result.log_dir = str(default_log)

            logger.info("TradingAgents 管线完成: %s → %s", ticker, result.rating)

        except ImportError as e:
            logger.error("TradingAgents 未安装: %s", e)
            result.final_trade_decision = f"TradingAgents 未安装: {e}"
        except Exception as e:
            logger.error("TradingAgents 管线异常: %s", e, exc_info=True)
            result.final_trade_decision = f"分析异常: {e}"

        return result

    def _parse_final_decision(self, result: TAAnalysisResult, text: str) -> None:
        """从Portfolio Manager的决策文本中提取结构化字段（委托给静态方法）"""
        self._parse_final_decision_static(result, text)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _build_a_stock_context(self, code6: str, market: Market) -> str:
        """构建A股数据上下文，注入到 TradingAgents 的 past_context

        数据源优先级：
        1. 通达信本地（K线/财务/行业）— 零延迟
        2. AkShare 在线（资金流/板块）— 有缓存
        3. 失败不阻塞主流程
        """
        parts = []
        parts.append("# 🔴 A股真实数据上下文（龙瞳注入）")
        parts.append("**重要提示**：以下是该A股股票的真实数据，你必须基于此数据进行分析，不要依赖yfinance等外部数据源。")
        parts.append("")

        stock_name = self._get_stock_name(code6)
        parts.append(f"## 基本信息")
        parts.append(f"- 代码: {code6}")
        parts.append(f"- 名称: {stock_name}")
        parts.append(f"- 市场: {'上海' if market == Market.SH else ('深圳' if market == Market.SZ else '北交所')}")
        parts.append("")

        # 1. K线数据摘要
        try:
            klines = self._reader.get_day_klines(code6, market)
            if klines:
                latest = klines[-1]
                parts.append("## 最新行情（通达信本地）")
                parts.append(f"- 日期: {latest.date}")
                parts.append(f"- 收盘: {latest.close:.2f}")
                parts.append(f"- 涨跌幅: {latest.change_pct:.2f}%" if latest.change_pct else "")
                parts.append(f"- 成交量: {latest.volume:,} 手")
                parts.append(f"- 成交额: {latest.amount:,.0f} 元")

                # 近5日涨跌
                if len(klines) >= 5:
                    recent5 = klines[-5:]
                    avg_vol = sum(k.volume for k in recent5) / 5
                    parts.append(f"- 近5日均量: {avg_vol:,.0f} 手")

                # 近20日区间
                if len(klines) >= 20:
                    high20 = max(k.high for k in klines[-20:])
                    low20 = min(k.low for k in klines[-20:])
                    parts.append(f"- 20日最高: {high20:.2f}")
                    parts.append(f"- 20日最低: {low20:.2f}")
                    pos = (latest.close - low20) / (high20 - low20) * 100 if high20 > low20 else 50
                    parts.append(f"- 20日位置: {pos:.1f}%")
                parts.append("")
        except Exception as e:
            parts.append(f"## K线数据: 获取失败 ({e})")
            parts.append("")

        # 2. 财务数据摘要
        try:
            from dragon_eye.analysis.base_dbf_reader import get_dbf_reader
            dbf = get_dbf_reader()
            fin = dbf.get_financial(code6)
            if fin and fin.is_valid():
                parts.append("## 财务数据（通达信base.dbf）")
                parts.append(f"- 财报更新: {fin.update_date}")
                parts.append(f"- 总资产: {fin.total_assets:,.0f} 万元")
                parts.append(f"- 净资产: {fin.net_assets:,.0f} 万元")
                parts.append(f"- 营收: {fin.revenue:,.0f} 万元")
                parts.append(f"- 净利润: {fin.net_profit:,.0f} 万元")
                parts.append(f"- ROE: {fin.roe:.2f}%")
                parts.append(f"- 资产负债率: {fin.debt_ratio:.2f}%")
                parts.append(f"- 每股收益: {fin.eps_approx:.4f} 元")
                parts.append(f"- 净利率: {fin.net_profit_margin:.2f}%")
                parts.append(f"- 流动比率: {fin.current_ratio:.2f}")
                parts.append("")
        except Exception as e:
            parts.append(f"## 财务数据: 获取失败 ({e})")
            parts.append("")

        # 3. 行业信息
        try:
            from dragon_eye.analysis.tdx_industry import get_industry_reader
            ind = get_industry_reader()
            industry = ind.get_industry(code6)
            if industry:
                parts.append("## 行业分类（通达信）")
                parts.append(f"- 所属行业: {industry}")
                # 同行业股票数量
                peers = ind.get_industry_stocks(ind.get_industry_code(code6))
                parts.append(f"- 同行业股票数: {len(peers)}")
                parts.append("")
        except Exception as e:
            parts.append(f"## 行业分类: 获取失败 ({e})")
            parts.append("")

        # 4. 龙瞳技术信号
        try:
            from dragon_eye.signals import score_technical
            if klines:
                tech = score_technical(klines)
                if tech:
                    direction = tech.get("direction", "neutral")
                    direction_cn = {"bull": "多头", "bear": "空头", "neutral": "震荡"}.get(direction, direction)
                    parts.append("## 龙瞳技术信号")
                    parts.append(f"- 综合评分: {tech.get('total_score', 0):.1f}/100")
                    parts.append(f"- 技术面判断: {direction_cn}")
                    parts.append(f"- 多头评分: {tech.get('bull_score', 0)}, 空头评分: {tech.get('bear_score', 0)}")
                    parts.append(f"- 支撑位: {tech.get('support', 0):.2f}")
                    parts.append(f"- 压力位: {tech.get('resistance', 0):.2f}")
                    # 信号列表
                    for sig in tech.get("signals", []):
                        sig_name = getattr(sig, 'name', str(sig))
                        sig_dir = getattr(sig, 'direction', 'neutral')
                        sig_strength = getattr(sig, 'strength', 0)
                        if sig_strength > 0:
                            parts.append(f"- 信号 {sig_name}: {sig_dir} (强度={sig_strength})")
                    parts.append("")
        except Exception:
            pass  # 信号引擎失败不影响主流程

        # 过滤空行
        return "\n".join(line for line in parts if line is not None)

    def _get_stock_name(self, code6: str) -> str:
        """获取股票名称"""
        if self._name_map is None:
            try:
                self._name_map = self._bridge.enrich_stock_names([])
            except Exception:
                self._name_map = {}
        return self._name_map.get(code6, "")

    def _fill_basic_info(self, report: AnalysisReport, code6: str, market: Market) -> None:
        """填充基本信息"""
        report.name = self._get_stock_name(code6)
        stock_type = classify_stock(code6, market)
        # 将StockType转为中文描述
        type_names = {
            StockType.MAINLAND_SH: "沪主板",
            StockType.KCB: "科创板",
            StockType.MAINLAND_SZ: "深主板",
            StockType.CYB: "创业板",
            StockType.BSE: "北交所",
        }
        report.market = f"{market.value}({type_names.get(stock_type, '')})"

    def _analyze_technical(self, report: AnalysisReport, klines: list[Kline]) -> None:
        """技术面分析"""
        if len(klines) < 30:
            report.trend = "数据不足"
            return

        # 综合技术评分
        tech = score_technical(klines)

        # 趋势判断
        direction = tech.get("direction", "neutral")
        trend_map = {"bull": "多头", "bear": "空头", "neutral": "震荡"}
        report.trend = trend_map.get(direction, "震荡")

        # MA状态
        closes = [k.close for k in klines]
        ma5_vals = ma(closes, 5)
        ma10_vals = ma(closes, 10)
        ma20_vals = ma(closes, 20)
        ma60_vals = ma(closes, 60)
        cur_price = closes[-1]

        report.ma_status = {
            "MA5": round(ma5_vals[-1], 2) if ma5_vals and ma5_vals[-1] is not None else 0,
            "MA10": round(ma10_vals[-1], 2) if ma10_vals and ma10_vals[-1] is not None else 0,
            "MA20": round(ma20_vals[-1], 2) if ma20_vals and ma20_vals[-1] is not None else 0,
            "MA60": round(ma60_vals[-1], 2) if ma60_vals and ma60_vals[-1] is not None else 0,
            "price_vs_ma5": "上方" if cur_price > (ma5_vals[-1] or 0) else "下方",
            "price_vs_ma20": "上方" if cur_price > (ma20_vals[-1] or 0) else "下方",
            "price_vs_ma60": "上方" if cur_price > (ma60_vals[-1] or 0) else "下方",
        }

        # 支撑压力位
        report.support_price = tech.get("support", 0)
        report.resistance_price = tech.get("resistance", 0)

    def _analyze_volume(self, report: AnalysisReport, klines: list[Kline], code6: str) -> None:
        """量价分析"""
        if len(klines) < 25:
            return

        vol_sig = check_volume(klines)
        if vol_sig.is_expand:
            report.volume_status = "放量"
        elif vol_sig.is_shrink:
            report.volume_status = "缩量"
        else:
            report.volume_status = "正常"

        # 换手率: 从实时行情获取
        try:
            spot = self._bridge.get_realtime_spot(code6)
            if spot:
                report.turnover_rate = float(spot.get("turnover_rate", 0) or 0)
        except Exception:
            pass

    def _analyze_valuation(self, report: AnalysisReport, code6: str) -> None:
        """估值分析（可能联网，超时跳过）"""
        try:
            val_result = self._valuation.analyze(code6)
            report.pe_ttm = val_result.pe_ttm
            report.pb = val_result.pb
            report.valuation_level = val_result.valuation_level
        except Exception as e:
            logger.debug("估值分析失败 %s: %s，跳过", code6, e)
            report.valuation_level = "未知"

    def _analyze_sector(self, report: AnalysisReport, code6: str) -> None:
        """板块归属分析（优先本地缓存，不依赖 stock_individual_info_em）

        获取行业名的方式:
        1. 优先从板块成分股反向查（AkShare 缓存）
        2. 备选 stock_individual_info_em（经常连接被拒）
        3. 纯本地: 从概念板块缓存匹配

        拿到行业名后，用本地模板匹配产业链位置。
        """
        # 方法1: 从行业板块成分股反向查找（用已缓存数据）
        if not report.sector:
            try:
                # 先尝试用板块数据反查
                sector_found = self._find_sector_from_boards(code6)
                if sector_found:
                    report.sector = sector_found
            except Exception as e:
                logger.debug("板块反查失败 %s: %s", code6, e)

        # 方法2: 备选 stock_individual_info_em（经常连不上）
        if not report.sector:
            try:
                import akshare as ak
                df = ak.stock_individual_info_em(symbol=code6)
                for _, row in df.iterrows():
                    item = str(row.get("item", ""))
                    value = str(row.get("value", ""))
                    if "行业" in item:
                        report.sector = value
                        break
            except Exception as e:
                logger.debug("stock_individual_info_em 失败 %s: %s", code6, e)
            except ImportError:
                logger.debug("akshare未安装，跳过板块分析")

        # 产业链位置：只在有行业名+模板匹配时才查
        if report.sector:
            try:
                from ..sector.chain_analyzer import ChainAnalyzer
                chain_analyzer = ChainAnalyzer(
                    reader=self._reader, bridge=self._bridge
                )
                # 只用本地模板匹配，不触发在线查询
                chain_result = chain_analyzer.analyze_local(report.sector, code6)
                if chain_result:
                    for node in chain_result.chains:
                        if code6 in node.stocks:
                            report.chain_position = f"{node.role}({node.name})"
                            break
            except Exception as e:
                logger.debug("产业链分析失败 %s: %s", code6, e)

    def _find_sector_from_boards(self, code6: str) -> str:
        """从本地缓存查股票所属行业（零网络请求）

        数据来源: _cache/stock_sectors.json（由 build_sector_cache() 一次性构建）
        不再每次发84次网络请求！
        """
        try:
            return self._bridge.get_stock_sector_local(code6)
        except Exception as e:
            logger.debug("本地板块查询失败 %s: %s", code6, e)
            return ""

    def _calc_total_score(self, report: AnalysisReport, klines: list[Kline]) -> None:
        """计算综合评分和操作建议"""
        score = 0.0

        # 技术面评分 (0-30)
        tech = score_technical(klines)
        tech_score = tech.get("total_score", 0)
        direction = tech.get("direction", "neutral")
        if direction == "bull":
            score += tech_score * 0.3
        elif direction == "bear":
            score += (100 - tech_score) * 0.1  # 空头给少量分
        else:
            score += tech_score * 0.15

        # 估值评分 (0-25)
        val_map = {"低估": 25, "合理": 15, "高估": 5, "亏损": 0, "未知": 10}
        score += val_map.get(report.valuation_level, 10)

        # 量价评分 (0-20)
        vol_map = {"放量": 15, "缩量": 5, "正常": 10}
        score += vol_map.get(report.volume_status, 8)
        # 换手率加分
        if 3 <= report.turnover_rate <= 10:
            score += 5
        elif report.turnover_rate > 10:
            score += 3  # 过高换手风险也大
        elif report.turnover_rate > 0:
            score += 2

        # 策略信号评分 (0-25)
        if report.signals:
            max_strength = max(s.strength for s in report.signals)
            score += min(25, max_strength * 0.25)

        report.total_score = round(min(100, score), 1)

        # 操作建议
        if report.total_score >= 75:
            report.recommendation = "买入"
        elif report.total_score >= 55:
            report.recommendation = "持有"
        elif report.total_score >= 35:
            report.recommendation = "观望"
        else:
            report.recommendation = "卖出"

        # 摘要
        parts = [
            f"{report.name or report.code}",
            f"趋势:{report.trend}",
            f"量价:{report.volume_status}",
        ]
        if report.valuation_level:
            parts.append(f"估值:{report.valuation_level}")
        if report.sector:
            parts.append(f"行业:{report.sector}")
        if report.signals:
            sig_names = [s.signal_type for s in report.signals]
            parts.append(f"信号:{'+'.join(sig_names)}")
        parts.append(f"评分:{report.total_score}")
        parts.append(f"建议:{report.recommendation}")
        report.summary = " | ".join(parts)
