"""
龙瞳Pro - 策略回测页

选择策略 / 输入股票和区间 / 回测结果 / 可视化
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


def render():
    st.header("⚡ 策略回测")

    # ---- 参数设置 ----
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("策略与股票")
        strategy_choice = st.selectbox("选择策略", ["底部起爆", "强势回调"])
        code = st.text_input("股票代码（6位）", value="603618", max_chars=6)
        code = code.strip()

    with col2:
        st.subheader("回测区间")
        col_start, col_end = st.columns(2)
        with col_start:
            start_date = st.date_input("开始日期", value=None)
        with col_end:
            end_date = st.date_input("结束日期", value=None)

    # 默认日期
    if start_date is None:
        from datetime import date, timedelta
        start_date = date.today() - timedelta(days=180)
    if end_date is None:
        from datetime import date
        end_date = date.today()

    # 执行按钮
    run_btn = st.button("🚀 开始回测", type="primary", width="stretch")

    if not run_btn:
        st.info("设置参数后点击「开始回测」")
        return

    if not code or len(code) != 6 or not code.isdigit():
        st.error("请输入有效的6位股票代码")
        return

    start_str = start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date)
    end_str = end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date)

    # ---- 执行回测 ----
    from dragon_eye.data_models import market_from_code, Market
    from dragon_eye.strategy import BottomBreakout, PullbackBuy, BacktestEngine

    market = market_from_code(code)

    if strategy_choice == "底部起爆":
        strategy = BottomBreakout()
    else:
        strategy = PullbackBuy()

    with st.spinner(f"正在回测 {code} ({start_str} ~ {end_str})..."):
        try:
            engine = BacktestEngine(strategy)
            result = engine.run(code, market, start_str, end_str)
        except Exception as e:
            st.error(f"回测失败: {e}")
            return

    # ---- 回测结果 ----
    st.divider()
    st.subheader("回测结果")

    # 概要指标
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总收益率", f"{result.total_return:.2f}%",
                delta="盈利" if result.total_return > 0 else "亏损")
    col2.metric("胜率", f"{result.win_rate:.1f}%")
    col3.metric("最大回撤", f"{result.max_drawdown:.2f}%",
                delta="回撤", delta_color="inverse")
    col4.metric("夏普比率", f"{result.sharpe_ratio:.2f}")

    col5, col6 = st.columns(2)
    col5.metric("交易次数", f"{result.total_trades}")
    col6.metric("平均持仓天数", f"{result.avg_hold_days:.1f}")

    st.divider()

    # ---- 交易明细 ----
    _render_trade_details(result)

    st.divider()

    # ---- 收益曲线 ----
    _render_equity_curve(result)


def _render_trade_details(result):
    """交易明细表"""
    st.subheader("交易明细")

    if not result.trades:
        st.info("回测期间没有产生交易信号")
        return

    rows = []
    for t in result.trades:
        reason_map = {
            "take_profit": "止盈",
            "stop_loss": "止损",
            "timeout": "超时平仓",
            "end_of_backtest": "回测结束",
            "signal_reverse": "信号反转",
        }
        rows.append({
            "买入日期": t.entry_date,
            "买入价格": f"{t.entry_price:.2f}",
            "卖出日期": t.exit_date or "--",
            "卖出价格": f"{t.exit_price:.2f}" if t.exit_price else "--",
            "平仓原因": reason_map.get(t.exit_reason, t.exit_reason),
            "盈亏%": f"{t.pnl_pct:+.2f}%",
            "持仓天数": t.hold_days,
        })

    st.dataframe(rows, hide_index=True, width="stretch")


def _render_equity_curve(result):
    """收益曲线"""
    st.subheader("累计收益曲线")

    if not result.trades:
        return

    cumulative = 0.0
    dates = []
    equity = []

    for t in result.trades:
        cumulative += t.pnl_pct
        dates.append(t.exit_date or t.entry_date)
        equity.append(cumulative)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=equity,
        mode="lines+markers",
        name="累计收益率%",
        line=dict(color="#636efa", width=2),
        marker=dict(size=6),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="累计收益曲线",
        xaxis_title="日期",
        yaxis_title="累计收益率%",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, width="stretch")
