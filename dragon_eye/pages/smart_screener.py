"""
龙瞳Pro - 智能选股页面

综合选股引擎: 多策略 + 板块过滤 + 四维评分 + 一键扫描 + 跳转10-Agent深度分析
"""
from __future__ import annotations

import time
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def _cached_stock_names() -> dict:
    """缓存股票名称映射"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.enrich_stock_names([])


@st.cache_data(ttl=300, show_spinner=False)
def _cached_hot_industries() -> list:
    """缓存热门行业"""
    from dragon_eye.sector.ths_sector import get_hot_sectors
    return get_hot_sectors("industry", top_n=30)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_hot_concepts() -> list:
    """缓存热门概念"""
    from dragon_eye.sector.ths_sector import get_hot_sectors
    return get_hot_sectors("concept", top_n=30)


def render():
    st.header("🎯 智能选股")

    # ---- 策略说明 ----
    with st.expander("📖 策略说明", expanded=False):
        st.markdown("""
        **综合四维评分体系**

        | 维度 | 权重 | 说明 |
        |------|------|------|
        | 策略信号 | 40% | 底部潜伏 + 缩量蓄势 + MA120踩穿反转 |
        | K线形态 | 25% | 下影线/锤子线/放量阳线/缩量洗盘 |
        | 板块热度 | 20% | 行业/概念板块强度排名 |
        | 趋势方向 | 15% | MA排列/均线角度/价格位置 |

        **策略说明:**
        - 🔍 **底部潜伏**: 卖盘枯竭+波动收缩+还没启动
        - 📉 **缩量蓄势**: 回调到位+量能萎缩+均线走平
        - 📊 **MA120踩穿反转**: 均线向上+缩量跌破+首次踩穿
        """)

    # ---- 控制面板 ----
    _render_control_panel()


def _render_control_panel():
    """控制面板"""
    st.subheader("扫描设置")

    # ---- 扫描模式 ----
    col1, col2 = st.columns([1, 1])
    with col1:
        scan_mode = st.radio(
            "扫描模式",
            ["🚀 全市场扫描", "🔥 热门板块选股", "📋 自选股扫描"],
            horizontal=True,
        )
    with col2:
        min_score = st.slider("最低综合分", 0, 100, 50)

    # ---- 策略选择 ----
    strategy_options = st.multiselect(
        "选择策略（可多选）",
        ["底部潜伏", "缩量蓄势", "MA120踩穿反转"],
        default=["底部潜伏", "MA120踩穿反转"],
    )

    # ---- 板块过滤 ----
    with st.expander("🏷️ 板块过滤（可选）", expanded=False):
        tab1, tab2 = st.tabs(["🏭 行业板块", "💡 概念板块"])

        with tab1:
            hot_industries = _cached_hot_industries()
            industry_names = [s.name for s in hot_industries if s.grade in ("S", "A")]
            selected_industries = st.multiselect(
                "选择行业（留空=不过滤）",
                industry_names,
                key="smart_industry_filter",
            )

        with tab2:
            hot_concepts = _cached_hot_concepts()
            concept_names = [s.name for s in hot_concepts if s.grade in ("S", "A")]
            selected_concepts = st.multiselect(
                "选择概念（留空=不过滤）",
                concept_names,
                key="smart_concept_filter",
            )

    # ---- 自选股输入 ----
    if scan_mode == "📋 自选股扫描":
        watchlist_input = st.text_area(
            "输入股票代码（每行一个，如 603618）",
            height=100,
            placeholder="603618\n300750\n000001",
        )

    # ---- 开始扫描 ----
    st.divider()
    scan_btn = st.button("🚀 开始扫描", type="primary", use_container_width=True)

    if scan_btn:
        _execute_scan(
            scan_mode=scan_mode,
            min_score=min_score,
            strategy_options=strategy_options,
            selected_industries=selected_industries if scan_mode != "📋 自选股扫描" else [],
            selected_concepts=selected_concepts if scan_mode != "📋 自选股扫描" else [],
            watchlist_input=watchlist_input if scan_mode == "📋 自选股扫描" else "",
        )


def _execute_scan(scan_mode: str, min_score: float, strategy_options: list,
                   selected_industries: list, selected_concepts: list,
                   watchlist_input: str):
    """执行扫描"""
    from dragon_eye.strategy.composite_screener import CompositeScreener, CompositeResult
    from dragon_eye.strategy import BottomBreakout, PullbackBuy, MA120Reversal

    # 构建策略列表
    strategies = []
    if "底部潜伏" in strategy_options:
        strategies.append(BottomBreakout())
    if "缩量蓄势" in strategy_options:
        strategies.append(PullbackBuy())
    if "MA120踩穿反转" in strategy_options:
        strategies.append(MA120Reversal())

    if not strategies:
        st.warning("请至少选择一个策略")
        return

    screener = CompositeScreener(strategies=strategies)

    with st.spinner("正在扫描，请稍候..."):
        t0 = time.time()

        if scan_mode == "🚀 全市场扫描":
            # 板块过滤
            sector_filter = None
            if selected_industries:
                sector_filter = selected_industries[0]  # 取第一个行业过滤
            results = screener.scan_all(
                min_score=min_score,
                sector_filter=sector_filter,
            )

        elif scan_mode == "🔥 热门板块选股":
            results = screener.scan_hot_sectors(
                top_n=30,
                min_score=min_score,
            )

        elif scan_mode == "📋 自选股扫描":
            codes = [c.strip() for c in watchlist_input.strip().split("\n") if c.strip()]
            if not codes:
                st.warning("请输入股票代码")
                return

            results = []
            from dragon_eye.stock_list import get_stock_list
            from dragon_eye.tdx_reader import get_reader
            from dragon_eye.data_models import market_from_code

            reader = get_reader()
            for code6 in codes:
                if len(code6) != 6 or not code6.isdigit():
                    continue
                market = market_from_code(code6)
                klines = reader.get_day_klines(code6, market)
                if klines and len(klines) >= 60:
                    result = screener.scan_stock(klines, code=code6)
                    if result.total_score >= min_score:
                        results.append(result)

        scan_time = time.time() - t0

        # 补充股票名称
        try:
            name_map = _cached_stock_names()
            for r in results:
                if not r.name and r.code in name_map:
                    r.name = name_map[r.code]
        except Exception:
            pass

        # 概念过滤
        if selected_concepts:
            from dragon_eye.sector.ths_sector import get_mapper
            mapper = get_mapper()
            results = [
                r for r in results
                if any(c in r.concepts for c in selected_concepts)
                or any(c in mapper.get_concepts(r.code) for c in selected_concepts)
            ]

        st.session_state["smart_results"] = results
        st.session_state["smart_scan_time"] = scan_time
        st.session_state["smart_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        st.success(f"扫描完成! 共发现 {len(results)} 只达标 (耗时 {scan_time:.1f}s)")

    # ---- 显示结果 ----
    _render_results()


def _render_results():
    """显示扫描结果"""
    results = st.session_state.get("smart_results", None)

    if not results:
        st.info("点击「开始扫描」按钮执行智能选股")
        return

    scan_ts = st.session_state.get("smart_timestamp", "")
    scan_dur = st.session_state.get("smart_scan_time", 0)
    st.caption(f"🕐 上次扫描: {scan_ts} (耗时 {scan_dur:.1f}s)")

    # ---- 评分分布 ----
    st.subheader("评分分布")
    scores = [r.total_score for r in results]
    fig = go.Figure(data=[go.Histogram(x=scores, nbinsx=20, marker_color="#636efa")])
    fig.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title="综合评分",
        yaxis_title="数量",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ---- 结果表格 ----
    st.subheader(f"扫描结果 ({len(results)} 只)")

    rows = []
    for r in results:
        # 策略标签
        strategy_tags = " + ".join(r.triggered_strategies) if r.triggered_strategies else "--"

        # 板块标签
        sector_tag = r.industry if r.industry else "--"
        if r.concepts:
            sector_tag += f" | {r.concepts[0]}"

        rows.append({
            "代码": r.code,
            "名称": r.name or "--",
            "综合分": r.total_score,
            "策略": strategy_tags,
            "策略分": r.strategy_score,
            "形态分": r.pattern_score,
            "板块分": r.sector_score,
            "趋势分": r.trend_score,
            "板块": sector_tag,
            "轮动": r.sector_signal,
            "买入价": r.entry_price,
            "止损价": r.stop_loss,
            "风险收益比": r.risk_reward,
        })

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "综合分": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "策略分": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "形态分": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "板块分": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "趋势分": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )

        # ---- 一键推送 ----
        st.divider()
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("📩 推送到微信", key="smart_push"):
                from dragon_eye.push import PushManager
                from dragon_eye.strategy.composite_screener import CompositeScreener
                pm = PushManager()
                screener = CompositeScreener()
                sr_list = screener.to_strategy_results(results)
                stats = pm.push_batch(sr_list)
                st.success(f"推送完成! 已推送: {stats['pushed']} | 跳过: {stats['skipped_dup']}")

        # ---- 跳转10-Agent深度分析 ----
        with col2:
            if st.button("🤖 深度分析选中股票", key="smart_deep_analyze", use_container_width=True):
                st.session_state["trigger_deep_analysis"] = True

        st.divider()
        st.subheader("🔍 深度分析")
        st.caption("选中股票后可进行多维度深度分析（基本面+技术面+资金面+情绪面）")

        selected_code = st.selectbox(
            "选择股票代码",
            options=[r["代码"] for r in rows],
            index=0,
            key="smart_stock_select",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🤖 10-Agent深度分析", type="primary", key="goto_deep_analysis",
                         use_container_width=True):
                st.session_state["selected_stock"] = selected_code
                st.session_state["run_deep_analysis"] = True
                st.rerun()
        with col_b:
            if st.button("📊 快速多维度分析", key="quick_multi_analysis",
                         use_container_width=True):
                st.session_state["selected_stock"] = selected_code
                st.session_state["run_quick_analysis"] = True
                st.rerun()

        # --- 执行深度分析 ---
        if st.session_state.get("run_deep_analysis"):
            _run_deep_analysis(st.session_state.get("selected_stock", ""))
            st.session_state["run_deep_analysis"] = False

        if st.session_state.get("run_quick_analysis"):
            _run_quick_analysis(st.session_state.get("selected_stock", ""))
            st.session_state["run_quick_analysis"] = False
    else:
        st.warning("没有符合条件的股票")


# ============================================================
# 深度分析函数
# ============================================================

def _run_deep_analysis(code6: str):
    """执行10-Agent深度分析"""
    if not code6:
        st.warning("请先选择股票")
        return

    st.divider()
    st.subheader(f"🤖 10-Agent深度分析: {code6}")

    with st.spinner(f"正在启动10-Agent专家团队分析 {code6}..."):
        try:
            from dragon_eye.analysis.stock_analyzer import StockAnalyzer
            from dragon_eye.data_models import market_from_code

            analyzer = StockAnalyzer()
            market = market_from_code(code6)

            # 尝试调用 TradingAgents 10-Agent 管线
            # 设置较短的超时避免页面卡死
            import os
            os.environ.setdefault("DRAGON_EYE_PROXY", "http://127.0.0.1:7897")

            result = analyzer.ta_deep_analysis(
                code6=code6,
                market=market,
                output_language="Chinese",
            )

            if result.has_reports or result.final_trade_decision:
                st.success(f"✅ 分析完成! 评级: {result.rating_cn}")

                # 显示关键信息
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("评级", result.rating_cn)
                with col2:
                    st.metric("目标价", f"{result.price_target:.2f}" if result.price_target else "N/A")
                with col3:
                    st.metric("时间维度", result.time_horizon or "N/A")
                with col4:
                    st.metric("分析师", "10-Agent")

                # 执行摘要
                if result.executive_summary:
                    with st.expander("📋 执行摘要", expanded=True):
                        st.markdown(result.executive_summary)

                # 投资论点
                if result.investment_thesis:
                    with st.expander("💡 投资论点"):
                        st.markdown(result.investment_thesis)

                # 各Agent报告
                tab1, tab2, tab3, tab4 = st.tabs([
                    "📈 技术面", "📰 新闻舆情", "💰 基本面", "🎯 最终决策"
                ])
                with tab1:
                    if result.market_report:
                        st.markdown(result.market_report)
                    else:
                        st.info("无技术面报告")
                with tab2:
                    if result.news_report:
                        st.markdown(result.news_report)
                    if result.sentiment_report:
                        st.markdown("---")
                        st.markdown(result.sentiment_report)
                    if not result.news_report and not result.sentiment_report:
                        st.info("无新闻/情绪报告")
                with tab3:
                    if result.fundamentals_report:
                        st.markdown(result.fundamentals_report)
                    else:
                        st.info("无基本面报告")
                with tab4:
                    if result.final_trade_decision:
                        st.markdown(result.final_trade_decision)
                    else:
                        st.info("无最终决策报告")

                # 投资计划
                if result.investment_plan:
                    with st.expander("📝 投资计划"):
                        st.markdown(result.investment_plan)
                if result.trader_investment_plan:
                    with st.expander("💹 交易提案"):
                        st.markdown(result.trader_investment_plan)

            else:
                st.warning("⚠️ 10-Agent分析未返回完整结果，请检查网络或稍后重试")

        except ImportError as e:
            st.warning(f"⚠️ TradingAgents未安装: {e}\n\n请先安装: pip install tradingagents")
            # Fallback: 快速多维度分析
            _run_quick_analysis(code6)
        except Exception as e:
            st.error(f"❌ 深度分析异常: {e}")
            st.info("💡 建议尝试「快速多维度分析」按钮")


def _run_quick_analysis(code6: str):
    """执行快速多维度分析（基本面+技术面+资金面+情绪面）

    不依赖 TradingAgents，使用龙瞳本地数据 + AKShare
    """
    if not code6:
        st.warning("请先选择股票")
        return

    st.divider()
    st.subheader(f"📊 快速多维度分析: {code6}")

    with st.spinner(f"正在分析 {code6}..."):
        try:
            from dragon_eye.analysis.stock_analyzer import StockAnalyzer
            from dragon_eye.data_models import market_from_code

            analyzer = StockAnalyzer()
            market = market_from_code(code6)

            # 获取标准分析报告
            report = analyzer.analyze(code6, market)

            # 获取支撑压力
            sr = analyzer.find_support_resistance(code6, market)

            # 显示基本信息
            st.markdown(f"**{report.name or code6}** | {report.market} | {report.sector or '未知行业'}")

            # 四维评分卡
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("综合评分", f"{report.total_score:.1f}")
            with col2:
                st.metric("操作建议", report.recommendation)
            with col3:
                st.metric("趋势", report.trend)
            with col4:
                st.metric("量价", report.volume_status)

            # 技术面
            st.subheader("📈 技术面")
            t_col1, t_col2, t_col3 = st.columns(3)
            with t_col1:
                st.metric("支撑位", f"{sr.get('support', 0):.2f}")
            with t_col2:
                st.metric("压力位", f"{sr.get('resistance', 0):.2f}")
            with t_col3:
                st.metric("估值", report.valuation_level)

            # MA状态
            if report.ma_status:
                ma_text = " | ".join(
                    f"{k}: {v}" for k, v in report.ma_status.items()
                    if not k.startswith("price_vs")
                )
                st.caption(f"均线: {ma_text}")
                pos_text = " | ".join(
                    f"{k}: {v}" for k, v in report.ma_status.items()
                    if k.startswith("price_vs")
                )
                st.caption(f"价格位置: {pos_text}")

            # 基本面（尝试获取财务数据）
            st.subheader("💰 基本面")
            try:
                from dragon_eye.akshare_bridge import get_bridge
                bridge = get_bridge()
                fin = bridge.get_financial(code6)
                if fin:
                    f_col1, f_col2, f_col3 = st.columns(3)
                    with f_col1:
                        st.metric("EPS", f"{fin.eps:.4f}" if fin.eps else "N/A")
                    with f_col2:
                        st.metric("ROE", f"{fin.roe:.2f}%" if fin.roe else "N/A")
                    with f_col3:
                        st.metric("BVPS", f"{fin.bvps:.2f}" if fin.bvps else "N/A")
                else:
                    st.info("暂无财务数据")
            except Exception as e:
                st.info(f"财务数据获取失败: {e}")

            # 资金面（实时行情）
            st.subheader("💹 资金面")
            try:
                from dragon_eye.akshare_bridge import get_bridge
                bridge = get_bridge()
                spot = bridge.get_realtime_spot(code6)
                if spot:
                    s_col1, s_col2, s_col3 = st.columns(3)
                    with s_col1:
                        price = spot.get("price", 0)
                        chg = spot.get("change_pct", 0)
                        st.metric("现价", f"{price:.2f}", f"{chg:+.2f}%")
                    with s_col2:
                        vol = spot.get("volume", 0)
                        st.metric("成交量", f"{vol/10000:.1f}万手" if vol else "N/A")
                    with s_col3:
                        turnover = spot.get("turnover_rate", 0)
                        st.metric("换手率", f"{turnover:.2f}%" if turnover else "N/A")
            except Exception:
                st.info("实时行情获取失败")

            # 情绪面（板块热度）
            st.subheader("🔥 情绪面")
            try:
                from dragon_eye.sector.ths_sector import get_mapper, ThsSectorFetcher, SectorRanker

                mapper = get_mapper()
                industry = mapper.get_industry(code6)
                concepts = mapper.get_concepts(code6)[:5]

                st.markdown(f"**所属行业**: {industry or '未知'}")

                if concepts:
                    st.markdown(f"**概念标签**: {' | '.join(concepts)}")

                # 尝试获取行业热度
                if industry:
                    fetcher = ThsSectorFetcher()
                    ranker = SectorRanker()
                    industries = fetcher.get_industry_summary()
                    if industries:
                        ranked = ranker.rank(industries)
                        for s in ranked:
                            if s.name == industry:
                                strength_col1, strength_col2 = st.columns(2)
                                with strength_col1:
                                    st.metric("行业强度", f"{s.strength_score:.1f}", s.grade)
                                with strength_col2:
                                    st.metric("轮动信号", s.rotation_signal or "N/A")
                                break
            except Exception as e:
                st.info(f"板块数据获取失败: {e}")

            # 策略信号
            if report.signals:
                st.subheader("🎯 策略信号")
                for sig in report.signals:
                    st.markdown(
                        f"- **{sig.signal_type}** (强度: {sig.strength:.0f}) "
                        f"| 入场: {sig.entry_price:.2f} | "
                        f"止损: {sig.stop_loss:.2f} | "
                        f"风险收益比: {sig.risk_reward:.2f}"
                    )

            # 综合摘要
            if report.summary:
                st.divider()
                st.markdown(f"**📝 综合摘要**: {report.summary}")

        except Exception as e:
            st.error(f"❌ 快速分析异常: {e}")
            import traceback
            st.code(traceback.format_exc())
