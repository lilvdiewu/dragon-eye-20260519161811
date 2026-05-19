"""
龙瞳Pro - 全市场扫描页

开始扫描 / 结果表格 / 策略筛选 / 跳转个股分析

v2: 策略重写 — 底部潜伏 + 缩量蓄势（找潜伏股，不是追涨）
"""
from __future__ import annotations

import time
from datetime import datetime
import streamlit as st

from dragon_eye.strategy import Screener, BottomBreakout, PullbackBuy
from dragon_eye.akshare_bridge import get_bridge


# ============================================================
# 缓存层
# ============================================================

import streamlit as st

@st.cache_data(ttl=60, show_spinner=False)
def _cached_stock_names() -> dict:
    """缓存股票名称映射（60秒过期）"""
    bridge = get_bridge()
    return bridge.enrich_stock_names([])


def render():
    st.header("🔍 全市场扫描")

    # ---- 策略说明 ----
    with st.expander("📖 策略说明", expanded=False):
        st.markdown("""
        **底部潜伏** — 卖盘枯竭 + 波动收缩 + 还没启动
        - 价格在60日低点±5%
        - 近10日成交量萎缩（地量 = 卖盘枯竭）
        - ATR收缩（波动收敛，弹簧越压越紧）
        - 近3日涨幅<5%（排除已起爆的）
        - 偶有放量阳线（主力吸筹痕迹）

        **缩量蓄势** — 回调到位 + 量能萎缩 + 均线走平 + 还没反弹
        - 距60日高点回调15%以上
        - 量能阶梯式萎缩（VCP模式）
        - 近5日振幅<4%（横盘蓄势）
        - MA20走平或拐头（下跌趋势结束）
        - 近3日涨幅<5%（还没反弹）

        > 💡 核心原则：潜伏是在起爆前找到介入点，不是追涨
        """)

    # ---- 控制面板 ----
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        strategy_filter = st.selectbox(
            "策略筛选",
            ["全部", "底部潜伏", "缩量蓄势"],
            index=0,
        )
    with col2:
        min_strength = st.slider("最低信号强度", 0, 100, 50)
    with col3:
        st.write("")
        scan_btn = st.button("🚀 开始扫描", type="primary", use_container_width=True)

    # ---- 执行扫描 ----
    if scan_btn:
        strategy_name = None
        if strategy_filter == "底部潜伏":
            strategy_name = "bottom_breakout"
        elif strategy_filter == "缩量蓄势":
            strategy_name = "pullback_buy"

        with st.spinner("正在扫描全市场，请稍候..."):
            try:
                t0 = time.time()
                screener = Screener()
                results = screener.scan_all(strategy_name=strategy_name)
                scan_time = time.time() - t0

                # 补充股票名称（失败不卡住）
                try:
                    name_map = _cached_stock_names()
                    for r in results:
                        if not r.name and r.code in name_map:
                            r.name = name_map[r.code]
                except Exception:
                    pass

                # 新鲜度过滤：与上次结果对比，标记"新触发"
                prev_results = st.session_state.get("scan_results", [])
                prev_codes = {r.code for r in prev_results}
                for r in results:
                    r.details["is_new"] = r.code not in prev_codes

                st.session_state["scan_results"] = results
                st.session_state["scan_time"] = scan_time
                st.session_state["scan_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.success(f"扫描完成! 共发现 {len(results)} 只触发信号 (耗时 {scan_time:.1f}s)")
            except Exception as e:
                st.error(f"扫描失败: {e}")
                import traceback
                traceback.print_exc()
                return

    # ---- 显示结果 ----
    scan_results = st.session_state.get("scan_results", None)

    if not scan_results:
        st.info("点击「开始扫描」按钮执行全市场扫描")
        return

    # 显示上次扫描时间
    scan_ts = st.session_state.get("scan_timestamp", "")
    scan_dur = st.session_state.get("scan_time", 0)
    st.caption(f"🕐 上次扫描: {scan_ts} (耗时 {scan_dur:.1f}s)")

    # 应用筛选
    filtered = scan_results
    if strategy_filter == "底部潜伏":
        filtered = [r for r in filtered if r.signal_type == "bottom_breakout"]
    elif strategy_filter == "缩量蓄势":
        filtered = [r for r in filtered if r.signal_type == "pullback_buy"]
    filtered = [r for r in filtered if r.strength >= min_strength]

    st.subheader(f"扫描结果 ({len(filtered)} 只)")

    # 构建表格
    rows = []
    for r in filtered:
        signal_label = "底部潜伏" if r.signal_type == "bottom_breakout" else "缩量蓄势"
        is_new = r.details.get("is_new", False)
        new_tag = " 🆕" if is_new else ""
        rows.append({
            "代码": r.code,
            "名称": r.name or "--",
            "信号": signal_label + new_tag,
            "强度": r.strength,
            "买入价": r.entry_price,
            "止损价": r.stop_loss,
            "目标价": r.target_price,
            "风险收益比": r.risk_reward,
        })

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "强度": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )

        # 一键推送到微信
        st.divider()
        col_push1, col_push2 = st.columns([1, 3])
        with col_push1:
            push_btn = st.button("📩 推送到微信", type="primary", use_container_width=True)
        with col_push2:
            push_summary_btn = st.button("📋 推送汇总报告", use_container_width=True)

        if push_btn:
            from dragon_eye.push import PushManager
            pm = PushManager()
            stats = pm.push_batch(filtered)
            st.success(f"推送完成! 已推送: {stats['pushed']} | 去重跳过: {stats['skipped_dup']} | 级别不足: {stats['skipped_level']}")

        if push_summary_btn:
            from dragon_eye.push import PushManager
            pm = PushManager()
            ok = pm.push_scan_summary(filtered)
            if ok:
                st.success("汇总报告已推送到微信!")
            else:
                st.error("推送失败，请检查PushPlus Token配置")

        # 点击跳转个股分析
        st.divider()
        st.subheader("查看个股详情")
        selected_code = st.selectbox(
            "选择股票代码查看分析",
            options=[r["代码"] for r in rows],
            index=0,
        )
        if st.button("📊 前往个股分析", key="goto_stock"):
            st.session_state["selected_stock"] = selected_code
            st.info(f"请点击左侧导航栏「个股分析」查看 {selected_code} 的详细分析")
    else:
        st.warning("没有符合条件的信号")
