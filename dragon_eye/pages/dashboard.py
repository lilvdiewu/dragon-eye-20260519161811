"""
龙瞳Pro - 首页仪表盘

大盘指数 / 扫描摘要 / 策略信号TOP10 / 市场情绪
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


# ============================================================
# 缓存层：避免每次交互都重新拉取网络数据
# ============================================================

@st.cache_data(ttl=30, show_spinner=False)
def _cached_tencent_quote(code6: str) -> dict | None:
    """缓存腾讯实时行情（30秒过期）"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.get_realtime_quote_tencent(code6)


def render():
    st.header("🏠 首页仪表盘")

    # ---- 大盘指数 ----
    _render_index_cards()

    st.divider()

    # ---- 全市场扫描摘要 ----
    col1, col2 = st.columns(2)
    with col1:
        _render_scan_summary()
    with col2:
        _render_market_sentiment()

    st.divider()

    # ---- 最近策略信号TOP10 ----
    _render_top_signals()


def _render_index_cards():
    """大盘指数卡片"""
    st.subheader("大盘指数")

    index_codes = {
        "上证指数": ("000001", "sh"),
        "深证成指": ("399001", "sz"),
        "创业板指": ("399006", "sz"),
    }

    cols = st.columns(len(index_codes))

    for i, (name, (code, market)) in enumerate(index_codes.items()):
        with cols[i]:
            try:
                quote = _cached_tencent_quote(code)
                if quote and quote.get("price", 0) > 0:
                    price = quote["price"]
                    change = quote.get("change_pct", 0)
                    color = "🔴" if change < 0 else "🟢"
                    st.metric(
                        label=name,
                        value=f"{price:,.2f}",
                        delta=f"{color} {change:+.2f}%",
                    )
                else:
                    st.metric(label=name, value="--", delta="数据暂无")
            except Exception:
                st.metric(label=name, value="--", delta="加载失败")


def _render_scan_summary():
    """全市场扫描结果摘要"""
    st.subheader("全市场扫描摘要")

    # 尝试从session_state获取缓存结果
    scan_results = st.session_state.get("scan_results", None)

    if scan_results is None:
        st.info("尚未执行全市场扫描，请前往「全市场扫描」页面开始扫描。")
        return

    bottom_count = sum(1 for r in scan_results if r.signal_type == "bottom_breakout")
    pullback_count = sum(1 for r in scan_results if r.signal_type == "pullback_buy")

    col1, col2, col3 = st.columns(3)
    col1.metric("底部起爆", f"{bottom_count} 只")
    col2.metric("强势回调", f"{pullback_count} 只")
    col3.metric("总计信号", f"{len(scan_results)} 只")

    # 信号强度分布
    if scan_results:
        strengths = [r.strength for r in scan_results]
        fig = go.Figure(data=[go.Histogram(x=strengths, nbinsx=20, marker_color="#636efa")])
        fig.update_layout(
            title="信号强度分布",
            xaxis_title="强度",
            yaxis_title="数量",
            height=250,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, width="stretch")


def _render_market_sentiment():
    """市场情绪指标"""
    st.subheader("市场情绪")

    try:
        from dragon_eye.stock_list import get_stock_list
        from dragon_eye.tdx_reader import get_reader
        from dragon_eye.data_models import Market

        sl = get_stock_list()
        reader = get_reader()
        stocks = sl.get_all()

        # 统计涨跌家数（从最新K线的change_pct推断）
        up_count = 0
        down_count = 0
        flat_count = 0

        # 采样避免太慢
        sample = stocks[:500] if len(stocks) > 500 else stocks

        for stock in sample:
            klines = reader.get_day_klines(stock.code, stock.market)
            if klines and klines[-1].change_pct is not None:
                if klines[-1].change_pct > 0:
                    up_count += 1
                elif klines[-1].change_pct < 0:
                    down_count += 1
                else:
                    flat_count += 1

        total = up_count + down_count + flat_count
        if total > 0:
            up_ratio = up_count / total * 100
            down_ratio = down_count / total * 100

            # 情绪条
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[up_ratio],
                orientation="h",
                name="上涨",
                marker_color="#ff4b4b",
                text=f"{up_count}只 ({up_ratio:.1f}%)",
                textposition="inside",
            ))
            fig.add_trace(go.Bar(
                x=[-down_ratio],
                orientation="h",
                name="下跌",
                marker_color="#4baf4f",
                text=f"{down_count}只 ({down_ratio:.1f}%)",
                textposition="inside",
            ))
            fig.update_layout(
                barmode="relative",
                title=f"涨跌家数 (采样{total}只)",
                height=250,
                margin=dict(l=20, r=20, t=40, b=20),
                yaxis=dict(showticklabels=False),
                xaxis_title="占比%",
                showlegend=True,
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无行情数据")
    except Exception as e:
        st.warning(f"情绪指标加载失败: {e}")


def _render_top_signals():
    """最近策略信号TOP10"""
    st.subheader("策略信号 TOP10")

    scan_results = st.session_state.get("scan_results", None)

    if not scan_results:
        st.info("请先执行全市场扫描")
        return

    top10 = scan_results[:10]

    # 构建表格数据
    rows = []
    for r in top10:
        rows.append({
            "代码": r.code,
            "名称": r.name or "--",
            "策略": "底部起爆" if r.signal_type == "bottom_breakout" else "强势回调",
            "强度": r.strength,
            "买入价": r.entry_price,
            "止损价": r.stop_loss,
            "目标价": r.target_price,
            "风险收益比": r.risk_reward,
        })

    if rows:
        st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
            column_config={
                "强度": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )
