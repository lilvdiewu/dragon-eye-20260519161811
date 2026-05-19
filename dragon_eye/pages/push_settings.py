"""
龙瞳Pro - 通知设置页

PushPlus Token / 推送级别 / 去重时间 / Toast开关 / 定时扫描 / 测试推送
"""
from __future__ import annotations

import streamlit as st


def render():
    st.header("🔔 通知设置")

    # 加载配置
    from dragon_eye.push.config import PushConfig, PushLevel, load_push_config, save_push_config
    from dragon_eye.scheduler.config import SchedulerConfig, load_scheduler_config, save_scheduler_config

    push_cfg = load_push_config()
    sched_cfg = load_scheduler_config()

    # ---- 推送设置 ----
    st.subheader("微信推送 (PushPlus)")
    st.caption("通过PushPlus将信号推送至微信，关注「PushPlus推送加」公众号接收")

    col1, col2 = st.columns([3, 1])
    with col1:
        token = st.text_input(
            "PushPlus Token",
            value=push_cfg.pushplus_token,
            type="password",
            help="在 pushplus.plus 获取",
        )
    with col2:
        pushplus_on = st.checkbox("启用", value=push_cfg.pushplus_enabled)

    min_level = st.selectbox(
        "最低推送级别",
        ["high", "medium", "low"],
        index=["high", "medium", "low"].index(push_cfg.min_level.value),
        format_func=lambda x: {"high": "🔴 高（仅猛突）", "medium": "🟡 中（策略信号）", "low": "🟢 低（全部）"}[x],
    )

    col3, col4 = st.columns(2)
    with col3:
        dedup_hours = st.number_input(
            "去重时间（小时）",
            min_value=0,
            max_value=48,
            value=push_cfg.dedup_hours,
            help="同一只股票N小时内不重复推送",
        )
    with col4:
        toast_on = st.checkbox("Windows桌面通知", value=push_cfg.toast_enabled)

    # ---- 定时扫描设置 ----
    st.divider()
    st.subheader("定时扫描")

    sched_enabled = st.checkbox("启用定时扫描", value=sched_cfg.enabled)

    col5, col6 = st.columns(2)
    with col5:
        scan_time = st.text_input("扫描时间", value=sched_cfg.scan_time, help="格式: HH:MM")
    with col6:
        summary_time = st.text_input("汇总推送时间", value=sched_cfg.summary_time)

    col7, col8 = st.columns(2)
    with col7:
        min_strength = st.number_input(
            "最低信号强度",
            min_value=0,
            max_value=100,
            value=sched_cfg.min_strength,
        )
    with col8:
        watchlist_str = st.text_input(
            "自选股（逗号分隔，留空=全市场）",
            value=",".join(sched_cfg.watchlist) if sched_cfg.watchlist else "",
        )

    # ---- 保存按钮 ----
    st.divider()
    col_save, col_test, col_clear = st.columns(3)

    with col_save:
        if st.button("💾 保存设置", type="primary", width="stretch"):
            new_push = PushConfig(
                pushplus_token=token,
                min_level=PushLevel(min_level),
                dedup_hours=dedup_hours,
                toast_enabled=toast_on,
                pushplus_enabled=pushplus_on,
            )
            watchlist = [c.strip() for c in watchlist_str.split(",") if c.strip()] if watchlist_str else []
            new_sched = SchedulerConfig(
                enabled=sched_enabled,
                scan_time=scan_time,
                summary_time=summary_time,
                min_strength=min_strength,
                watchlist=watchlist,
            )
            save_push_config(new_push)
            save_scheduler_config(new_sched)
            st.success("设置已保存!")

    with col_test:
        if st.button("🧪 测试推送", width="stretch"):
            from dragon_eye.push import PushManager
            pm = PushManager(PushConfig(
                pushplus_token=token,
                min_level=PushLevel(min_level),
                toast_enabled=toast_on,
                pushplus_enabled=pushplus_on,
            ))
            ok = pm.push_custom(
                "龙瞳Pro测试推送",
                f"推送通道测试\n级别: {min_level}\nToast: {'开' if toast_on else '关'}",
            )
            if ok:
                st.success("测试推送已发送! 请检查微信和桌面通知")
            else:
                st.error("推送失败，请检查Token是否正确")

    with col_clear:
        if st.button("🗑️ 清空去重记录", width="stretch"):
            from dragon_eye.push import PushManager
            pm = PushManager()
            pm.clear_dedup()
            st.success("去重记录已清空")

    # ---- 推送历史 ----
    st.divider()
    st.subheader("推送历史")
    try:
        from pathlib import Path
        history_path = Path(__file__).parent.parent / "config" / "push_history.json"
        if history_path.exists():
            import json
            data = json.loads(history_path.read_text(encoding="utf-8"))
            if data:
                # 只显示最近20条
                items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:20]
                st.dataframe(
                    [{"代码": k, "最后推送时间": v} for k, v in items],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("暂无推送记录")
        else:
            st.info("暂无推送记录")
    except Exception as e:
        st.warning(f"加载推送历史失败: {e}")
