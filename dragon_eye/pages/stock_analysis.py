"""
龙瞳Pro - 个股分析页

K线图 / 技术面 / 估值 / 策略信号 / 综合评分 / 10-Agent深度分析
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime


# ============================================================
# 缓存层：避免每次交互都重新拉取网络数据 / 重读本地文件
# ============================================================

@st.cache_resource(show_spinner=False)
def _cached_reader():
    """缓存通达信读取器（单例，避免反复初始化）"""
    from dragon_eye.tdx_reader import get_reader
    return get_reader()

@st.cache_data(ttl=120, show_spinner=False)
def _cached_klines(code, market):
    """缓存K线数据（2分钟过期，避免反复读本地文件）"""
    reader = _cached_reader()
    return reader.get_day_klines(code, market)

@st.cache_data(ttl=60, show_spinner=False)
def _cached_stock_names() -> dict:
    """缓存股票名称映射（60秒过期，避免反复拉取）"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.enrich_stock_names([])

@st.cache_data(ttl=30, show_spinner=False)
def _cached_realtime_tencent(code6: str) -> dict | None:
    """缓存腾讯实时行情（30秒过期）"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.get_realtime_quote_tencent(code6)

@st.cache_data(ttl=30, show_spinner=False)
def _cached_realtime_spot(code6: str) -> dict | None:
    """缓存全市场实时行情（30秒过期）"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.get_realtime_spot(code6)


def render():
    st.header("📊 个股分析")

    # ---- 股票搜索（支持代码/名称/拼音） ----
    # 核心设计: 搜索阶段不触发分析，只有确认选股后才分析
    # 避免 text_input 每次按键都重跑完整管线导致卡死
    confirmed_code = st.session_state.get("confirmed_stock", "")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        search_text = st.text_input(
            "输入股票代码/名称/拼音",
            value="",
            max_chars=20,
            placeholder="如: 600519 / 茅台 / GZMT",
        )

        # 搜索联想（纯本地搜索，秒出，不触发分析）
        pending_code = ""
        if search_text and len(search_text) >= 1:
            from dragon_eye.stock_search import get_search_engine
            engine = get_search_engine()
            results = engine.search(search_text, limit=15)
            if results:
                options = ["（请选择）"] + [f"{r.code} {r.name} ({r.pinyin})" for r in results]
                selected = st.selectbox(
                    "匹配结果",
                    options=options,
                    index=0,
                    key="stock_search_results",
                )
                if selected and selected != "（请选择）":
                    pending_code = selected.split()[0]
            else:
                # 没有匹配，检查是否是6位纯数字
                if len(search_text) == 6 and search_text.isdigit():
                    pending_code = search_text
                else:
                    st.info("无匹配结果，请输入代码/名称/拼音")
    with col2:
        st.write("")
        st.write("")
        analyze_btn = st.button("🔍 快速分析", type="primary", use_container_width=True)
    with col3:
        st.write("")
        st.write("")
        push_report_btn = st.button("📩 推送报告", use_container_width=True)

    # ---- 选股确认逻辑 ----
    # 只有点击按钮时才确认选股，避免搜索过程中误触发分析
    if analyze_btn and pending_code:
        st.session_state["confirmed_stock"] = pending_code
        confirmed_code = pending_code

    # 6位纯数字直接输入也自动确认
    if not confirmed_code and search_text and len(search_text) == 6 and search_text.isdigit():
        st.session_state["confirmed_stock"] = search_text
        confirmed_code = search_text

    code = confirmed_code
    if not code or len(code) != 6 or not code.isdigit():
        if search_text:
            pass  # 搜索中，不显示提示
        else:
            st.info("输入股票代码、名称或拼音首字母搜索，选择后点击「快速分析」")
        return

    # ---- 加载数据（全部走缓存） ----
    from dragon_eye.data_models import market_from_code, Market
    from dragon_eye.signals import score_technical, ma

    market = market_from_code(code)
    reader = _cached_reader()

    with st.spinner("加载K线数据..."):
        klines = _cached_klines(code, market)

    if not klines:
        st.error(f"未找到 {code} 的K线数据，请检查通达信数据目录")
        return

    # 获取股票名称（用缓存，不卡）
    stock_name = code
    try:
        name_map = _cached_stock_names()
        stock_name = name_map.get(code, code)
    except Exception:
        pass

    st.subheader(f"{stock_name} ({code})")

    # ---- K线图（本地数据，秒出） ----
    _render_kline_chart(klines, stock_name)

    st.divider()

    # ---- 技术面 + 估值 并排 ----
    col_tech, col_val = st.columns(2)

    with col_tech:
        _render_technical_analysis(klines)

    with col_val:
        _render_valuation(code)

    st.divider()

    # ---- 策略信号（本地数据，秒出） ----
    _render_strategy_signals(code, market, klines)

    st.divider()

    # ---- 综合评分（本地数据，秒出） ----
    _render_comprehensive_score(klines)

    # ---- 10-Agent 深度分析（始终显示，离线秒出） ----
    st.divider()
    _render_ta_deep_analysis(code, market)

    # ---- 推送分析报告 ----
    if push_report_btn:
        from dragon_eye.push import PushManager
        from dragon_eye.analysis import StockAnalyzer
        analyzer = StockAnalyzer()
        with st.spinner("生成分析报告并推送..."):
            try:
                report = analyzer.analyze(code)
                pm = PushManager()
                ok = pm.push_analysis_report(report)
                if ok:
                    st.success("分析报告已推送到微信!")
                else:
                    st.error("推送失败，请检查PushPlus Token配置")
            except Exception as e:
                st.error(f"推送失败: {e}")


def _render_kline_chart(klines, title: str):
    """绘制K线图 + 均线 + 成交量（默认仅显示近1年，避免浏览器卡死）"""
    from dragon_eye.signals import ma as calc_ma

    # ⚠️ 关键优化：只显示最近250个交易日（~1年），避免Plotly渲染6000+蜡烛图卡死浏览器
    max_display = 250
    if len(klines) > max_display:
        display_klines = klines[-max_display:]
        st.caption(f"📊 显示近 {max_display} 个交易日（共 {len(klines)} 天数据）")
    else:
        display_klines = klines

    dates = [k.date for k in display_klines]
    opens = [k.open for k in display_klines]
    highs = [k.high for k in display_klines]
    lows = [k.low for k in display_klines]
    closes = [k.close for k in display_klines]
    volumes = [k.volume for k in display_klines]

    # 均线
    closes_list = closes
    ma5 = calc_ma(closes_list, 5)
    ma10 = calc_ma(closes_list, 10)
    ma20 = calc_ma(closes_list, 20)
    ma60 = calc_ma(closes_list, 60)

    # 创建子图: K线 + 成交量
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    # K线（涨红跌绿）
    fig.add_trace(go.Candlestick(
        x=dates, open=opens, high=highs, low=lows, close=closes,
        name="K线",
        increasing_line_color="#ff4b4b",
        decreasing_line_color="#4baf4f",
    ), row=1, col=1)

    # 均线
    for ma_vals, name, color in [
        (ma5, "MA5", "#ffa500"),
        (ma10, "MA10", "#1e90ff"),
        (ma20, "MA20", "#ff69b4"),
        (ma60, "MA60", "#9370db"),
    ]:
        valid_idx = [(i, v) for i, v in enumerate(ma_vals) if v is not None]
        if valid_idx:
            idx, vals = zip(*valid_idx)
            fig.add_trace(go.Scatter(
                x=[dates[i] for i in idx],
                y=list(vals),
                mode="lines",
                name=name,
                line=dict(width=1, color=color),
            ), row=1, col=1)

    # 成交量
    colors = ["#ff4b4b" if c >= o else "#4baf4f" for c, o in zip(closes, opens)]
    fig.add_trace(go.Bar(
        x=dates, y=volumes,
        marker_color=colors,
        name="成交量",
        showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        title=f"{title} K线图",
        height=550,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    fig.update_xaxes(type="category", row=1, col=1)
    fig.update_xaxes(type="category", row=2, col=1)

    st.plotly_chart(fig, width="stretch")


def _render_technical_analysis(klines):
    """技术面分析（纯本地计算，秒出）"""
    st.subheader("技术面分析")

    from dragon_eye.signals import (
        check_ma_cross, check_volume, check_breakout,
        check_stop_drop, check_ma_alignment, ma_angle,
        score_technical,
    )

    if len(klines) < 30:
        st.warning("K线数据不足30天，无法进行技术分析")
        return

    result = score_technical(klines)

    # 方向和总评分
    direction_map = {"bull": "看多 🔴", "bear": "看空 🟢", "neutral": "中性 ⚪"}
    direction = direction_map.get(result["direction"], "未知")

    st.metric("综合技术评分", f"{result['total_score']:.0f}/100", delta=direction)

    # 各信号
    signal_details = []
    for sig in result.get("signals", []):
        if hasattr(sig, "name") and sig.triggered:
            dir_label = {"bull": "多", "bear": "空", "neutral": "中"}.get(sig.direction, "?")
            signal_details.append({
                "信号": getattr(sig, "name", ""),
                "方向": dir_label,
                "强度": f"{sig.strength:.0f}",
            })

    if signal_details:
        st.dataframe(signal_details, hide_index=True, width="stretch")

    # MA角度
    st.write(f"MA10角度: {result.get('ma_angle_10', 0):.1f}°")
    st.write(f"MA20角度: {result.get('ma_angle_20', 0):.1f}°")

    # 支撑压力位
    col1, col2 = st.columns(2)
    col1.metric("支撑位", f"{result.get('support', 0):.2f}")
    col2.metric("压力位", f"{result.get('resistance', 0):.2f}")


def _render_valuation(code: str):
    """估值分析（联网，有超时保护，不卡页面）"""
    st.subheader("估值分析")

    try:
        from dragon_eye.akshare_bridge import get_bridge
        bridge = get_bridge()

        # 优先腾讯API（快，不走代理）— 用缓存
        spot = _cached_realtime_tencent(code)

        # 腾讯没PE/PB，再尝试东方财富（有超时保护）— 用缓存
        if spot and not spot.get("pe_ttm"):
            try:
                spot_em = _cached_realtime_spot(code)
                if spot_em:
                    # 合并PE/PB数据
                    if not spot.get("pe_ttm") and spot_em.get("pe_ttm"):
                        spot["pe_ttm"] = spot_em["pe_ttm"]
                    if not spot.get("pb") and spot_em.get("pb"):
                        spot["pb"] = spot_em["pb"]
            except Exception:
                pass

        if spot:
            col1, col2, col3 = st.columns(3)
            pe = spot.get('pe_ttm', 0)
            pb = spot.get('pb', 0)
            mv = spot.get('total_mv', 0)
            col1.metric("PE(TTM)", f"{pe:.1f}" if pe else "--")
            col2.metric("PB", f"{pb:.2f}" if pb else "--")
            col3.metric("总市值(亿)", f"{mv / 1e8:.0f}" if mv else "--")

            col4, col5 = st.columns(2)
            col4.metric("换手率", f"{spot.get('turnover_rate', 0):.2f}%")
            col5.metric("涨跌幅", f"{spot.get('change_pct', 0):.2f}%")
        else:
            st.info("暂无实时估值数据（网络不通或非交易时段）")
    except Exception:
        st.info("估值数据暂不可用，跳过")


def _render_strategy_signals(code: str, market, klines):
    """策略信号检测（纯本地计算，秒出）"""
    st.subheader("策略信号")

    from dragon_eye.strategy import BottomBreakout, PullbackBuy

    col1, col2 = st.columns(2)

    with col1:
        st.write("**底部起爆**")
        try:
            bb = BottomBreakout()
            result = bb.scan(klines, code=code)
            if result.triggered:
                st.success(f"触发! 强度: {result.strength:.0f}")
                st.write(f"建议买入价: {result.entry_price:.2f}")
                st.write(f"止损价: {result.stop_loss:.2f}")
                st.write(f"目标价: {result.target_price:.2f}")
                st.write(f"风险收益比: {result.risk_reward:.2f}")
            else:
                st.info("未触发")
        except Exception as e:
            st.error(f"检测失败: {e}")

    with col2:
        st.write("**强势回调**")
        try:
            pb = PullbackBuy()
            result = pb.scan(klines, code=code)
            if result.triggered:
                st.success(f"触发! 强度: {result.strength:.0f}")
                st.write(f"建议买入价: {result.entry_price:.2f}")
                st.write(f"止损价: {result.stop_loss:.2f}")
                st.write(f"目标价: {result.target_price:.2f}")
                st.write(f"风险收益比: {result.risk_reward:.2f}")
            else:
                st.info("未触发")
        except Exception as e:
            st.error(f"检测失败: {e}")


def _render_comprehensive_score(klines):
    """综合评分和建议（纯本地计算，秒出）"""
    st.subheader("综合评分与建议")

    from dragon_eye.signals import score_technical

    if len(klines) < 30:
        st.warning("数据不足，无法评分")
        return

    result = score_technical(klines)
    score = result["total_score"]
    direction = result["direction"]

    # 评分仪表
    import plotly.graph_objects as go

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "综合评分"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#636efa"},
            "steps": [
                {"range": [0, 30], "color": "#ff6b6b"},
                {"range": [30, 60], "color": "#ffd93d"},
                {"range": [60, 80], "color": "#6bcb77"},
                {"range": [80, 100], "color": "#4d96ff"},
            ],
        },
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, width="stretch")

    # 建议
    if direction == "bull" and score >= 60:
        st.success(f"技术面偏多 (评分{score:.0f})，可关注买入机会")
    elif direction == "bear" and score >= 60:
        st.error(f"技术面偏空 (评分{score:.0f})，建议观望或减仓")
    else:
        st.info(f"技术面中性 (评分{score:.0f})，建议等待明确信号")


# ============================================================
# 10-Agent 深度分析（TradingAgents 管线）
# 抄作业: 参照 run_deepseek.py 的逻辑流程
# 核心原则: session_state 缓存结果，按钮触发分析，不每次重算
# ============================================================

def _render_ta_deep_analysis(code: str, market):
    """调用 TradingAgents 10-Agent 管线进行深度分析

    逻辑（抄 run_deepseek.py）:
    1. 用 session_state 缓存分析结果，不每次重算
    2. 按钮点击触发分析，结果写入 session_state
    3. 已有缓存直接展示，秒出
    4. 换股票代码时自动清缓存
    """

    st.subheader("🤖 TradingAgents 10-Agent 深度分析")

    # ---- 缓存 key: 股票代码变了就清掉旧结果 ----
    cache_key = f"ta_result_{code}"

    if st.session_state.get("_ta_code") != code:
        # 股票代码变了，清旧缓存
        st.session_state.pop(cache_key, None)
        st.session_state["_ta_code"] = code

    # ---- 模式选择 ----
    col_mode1, col_mode2 = st.columns(2)
    with col_mode1:
        offline = st.checkbox("📦 离线模式（从已有报告加载）", value=True,
                               help="yfinance被限速或网络不通时，加载之前跑过的报告")
    with col_mode2:
        language = st.selectbox("报告语言", ["Chinese", "English"], index=0)

    # 分析师选择（仅在线模式有效）
    if not offline:
        analysts = st.multiselect(
            "选择分析师",
            ["market", "social", "news", "fundamentals"],
            default=["market", "fundamentals", "news"],
        )
        if not analysts:
            st.error("请至少选择一个分析师")
            return
    else:
        analysts = ["market", "social", "news", "fundamentals"]

    # ---- 按钮: 触发分析，结果存 session_state ----
    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        run_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)
    with col_btn2:
        if st.session_state.get(cache_key):
            _cached = st.session_state[cache_key]
            st.caption(f"✅ 已有分析结果: {_cached.rating_cn} ({_cached.rating}) · {_cached.trade_date}")

    # ---- 按钮点击: 跑分析，存缓存 ----
    if run_btn:
        from dragon_eye.analysis import StockAnalyzer
        analyzer = StockAnalyzer()

        if offline:
            with st.spinner("📦 从日志加载 TradingAgents 报告..."):
                ta_result = analyzer.ta_deep_analysis(
                    code6=code,
                    market=market,
                    selected_analysts=analysts,
                    output_language=language,
                    offline=True,
                )
        else:
            with st.spinner("🤖 正在运行10-Agent管线，请耐心等待（3-5分钟）..."):
                ta_result = analyzer.ta_deep_analysis(
                    code6=code,
                    market=market,
                    selected_analysts=analysts,
                    output_language=language,
                    offline=False,
                )

        # 存入 session_state
        st.session_state[cache_key] = ta_result

    # ---- 从 session_state 读结果展示 ----
    ta_result = st.session_state.get(cache_key)

    if not ta_result:
        st.info("👆 点击「🚀 开始分析」按钮启动10-Agent深度分析")
        return

    if not ta_result.rating:
        st.error(f"分析失败: {ta_result.final_trade_decision}")
        return

    # ---- 最终决策卡片 ----
    st.divider()
    _render_ta_decision_card(ta_result)

    # ---- 各Agent报告 ----
    st.divider()

    tab_market, tab_social, tab_news, tab_fund, tab_debate = st.tabs([
        "📈 技术面", "💬 情绪面", "📰 新闻面", "💰 基本面", "⚔️ 辩论与决策",
    ])

    with tab_market:
        if ta_result.market_report:
            st.markdown(ta_result.market_report)
        else:
            st.info("未选择 Market Analyst 或无数据")

    with tab_social:
        if ta_result.sentiment_report:
            st.markdown(ta_result.sentiment_report)
        else:
            st.info("未选择 Social Analyst 或无数据")

    with tab_news:
        if ta_result.news_report:
            st.markdown(ta_result.news_report)
        else:
            st.info("未选择 News Analyst 或无数据")

    with tab_fund:
        if ta_result.fundamentals_report:
            st.markdown(ta_result.fundamentals_report)
        else:
            st.info("未选择 Fundamentals Analyst 或无数据")

    with tab_debate:
        if ta_result.trader_investment_plan:
            st.subheader("💹 Trader 交易提案")
            st.markdown(ta_result.trader_investment_plan)
            st.divider()
        if ta_result.final_trade_decision:
            st.subheader("🏦 Portfolio Manager 最终决策")
            st.markdown(ta_result.final_trade_decision)

    # ---- 伴随存档: 10-Agent结果自动归档 ----
    try:
        from dragon_eye.local_knowledge import get_lk
        import json as _json
        lk = get_lk()
        today = datetime.now().strftime("%Y-%m-%d")

        # 获取股票名称
        stock_name = code
        try:
            name_map = _cached_stock_names()
            stock_name = name_map.get(code, code)
        except Exception:
            pass

        # 存档快照
        lk.archive_stock_snapshot(code, "10agent",
            name=stock_name,
            ta_rating=ta_result.rating,
            ta_target=getattr(ta_result, 'target_price', None),
            ta_horizon=getattr(ta_result, 'time_horizon', None),
        )

        # 存档完整报告
        report_data = {
            "rating": ta_result.rating,
            "rating_cn": getattr(ta_result, 'rating_cn', ''),
            "target_price": getattr(ta_result, 'target_price', None),
            "time_horizon": getattr(ta_result, 'time_horizon', None),
            "market_report": ta_result.market_report or "",
            "sentiment_report": ta_result.sentiment_report or "",
            "news_report": ta_result.news_report or "",
            "fundamentals_report": ta_result.fundamentals_report or "",
            "trader_investment_plan": ta_result.trader_investment_plan or "",
            "final_trade_decision": ta_result.final_trade_decision or "",
        }
        lk.archive_report(code, today, "10agent",
            report_json=_json.dumps(report_data, ensure_ascii=False, default=str),
            rating=ta_result.rating,
            target_price=getattr(ta_result, 'target_price', None),
        )
    except Exception:
        pass  # 存档失败不影响展示

    # ---- 历史对比 ----
    try:
        from dragon_eye.local_knowledge import get_lk
        lk = get_lk()
        history = lk.get_stock_history(code, limit=5)
        if len(history) >= 2:
            st.divider()
            st.subheader("📊 历史对比")
            curr = history[0]
            prev = history[1]

            cols = st.columns(4)
            # PE对比
            if curr.get("pe_ttm") and prev.get("pe_ttm"):
                delta = curr["pe_ttm"] - prev["pe_ttm"]
                cols[0].metric("PE(TTM)", f"{curr['pe_ttm']:.1f}", delta=f"{delta:+.1f}")
            # 评级对比
            curr_rating = curr.get("ta_rating") or "—"
            prev_rating = prev.get("ta_rating") or "—"
            cols[1].metric("10-Agent评级", curr_rating, delta=f"上次: {prev_rating}")
            # 日期
            cols[2].metric("本次分析", curr["trade_date"])
            cols[3].metric("上次分析", prev["trade_date"])
            st.caption(f"💡 对比: {curr['trade_date']} vs {prev['trade_date']}")
    except Exception:
        pass  # 对比失败不影响展示


def _render_ta_decision_card(result):
    """渲染10-Agent最终决策卡片"""

    # 5级评级颜色
    rating_colors = {
        "Buy": "#4d96ff",
        "Overweight": "#6bcb77",
        "Hold": "#ffd93d",
        "Underweight": "#ff9f43",
        "Sell": "#ff6b6b",
    }
    rating_emoji = {
        "Buy": "🟢",
        "Overweight": "🔵",
        "Hold": "🟡",
        "Underweight": "🟠",
        "Sell": "🔴",
    }

    emoji = rating_emoji.get(result.rating, "⚪")
    color = rating_colors.get(result.rating, "#636efa")

    # 大标题决策
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {color}22, {color}11);
        border-left: 5px solid {color};
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    ">
        <h2 style="margin:0; color:{color};">{emoji} {result.rating_cn} ({result.rating})</h2>
        <p style="margin:5px 0; color:#666;">{result.ticker} · {result.trade_date}</p>
    </div>
    """, unsafe_allow_html=True)

    # 关键指标
    col1, col2, col3 = st.columns(3)
    col1.metric("评级", f"{result.rating_cn} ({result.rating})")
    col2.metric("参考入场价", f"{result.price_target:.2f}" if result.price_target else "--")
    col3.metric("持有期", result.time_horizon or "中期")

    # 标注数据来源
    if result.log_dir:
        st.caption(f"📁 报告来源: `{result.log_dir}`")

    # 执行摘要
    if result.executive_summary:
        st.subheader("📋 执行摘要")
        st.markdown(result.executive_summary)

    # 投资论点
    if result.investment_thesis:
        st.subheader("📝 投资论点")
        st.markdown(result.investment_thesis)
