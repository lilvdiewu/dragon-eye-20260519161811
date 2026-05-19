"""
龙瞳Pro - 快速股票筛选器

纯本地数据，零网络请求，实时过滤。
数据源: TDX tdxstat.cfg (7866只股票, 35字段) + tdxhy.cfg (行业映射)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _load_screener_data() -> pd.DataFrame:
    """加载全量筛选数据 (TDX统计 + 股票名称 + 行业) — 纯本地，秒级加载"""
    from dragon_eye.analysis.tdx_stat_reader import TdxStatReader
    from dragon_eye.analysis.tdx_industry import TdxIndustryReader

    # --- 加载TDX统计 ---
    reader = TdxStatReader()
    reader.load()

    # --- 加载股票名称 ---
    names = _load_stock_names()

    # --- 加载行业映射 ---
    ind_reader = TdxIndustryReader()
    ind_reader._ensure_loaded()

    rows = []
    for code, stat in reader._stats.items():
        name = names.get(code, "")
        industry = ind_reader.get_industry(code) or ""

        rows.append({
            "代码": code,
            "名称": name,
            "涨幅%": round(stat.change_pct, 2),
            "换手%": round(stat.turnover, 2),
            "量比": round(stat.volume_ratio, 2),
            "PE": round(stat.pe, 1),
            "市值_亿": round(stat.total_mv / 10000, 2),  # 万元→亿
            "20日涨幅%": round(stat.chg_20d, 2),
            "行业": industry,
            # 保留原始值用于排序和过滤
            "_change_pct": stat.change_pct,
            "_turnover": stat.turnover,
            "_volume_ratio": stat.volume_ratio,
            "_pe": stat.pe,
            "_total_mv_yi": stat.total_mv / 10000,
            "_chg_20d": stat.chg_20d,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("_change_pct", ascending=False)
    return df


def _load_stock_names() -> dict[str, str]:
    """加载股票名称缓存"""
    cache_path = Path(__file__).resolve().parent.parent / "_cache" / "stock_names.json"
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


@st.cache_data(ttl=300, show_spinner=False)
def _load_industry_list() -> list[str]:
    """加载可用行业列表"""
    from dragon_eye.analysis.tdx_industry import TdxIndustryReader
    reader = TdxIndustryReader()
    reader._ensure_loaded()
    industries = reader.get_all_industries()
    # 按股票数量降序排列
    sorted_inds = sorted(industries.items(), key=lambda x: len(x[1]), reverse=True)
    return [f"{name} ({len(stocks)})" for name, stocks in sorted_inds if name]


# ============================================================
# 预设按钮
# ============================================================

PRESETS = {
    "🔥 今日涨停股": {
        "change_pct_min": 9.8,
        "change_pct_max": 20.0,
        "label": "涨幅 ≥ 9.8% (涨停板)",
    },
    "📈 放量突破": {
        "change_pct_min": 3.0,
        "volume_ratio_min": 2.0,
        "label": "量比 > 2 + 涨幅 > 3%",
    },
    "📉 超跌反弹": {
        "change_pct_max": -5.0,
        "chg_20d_min": -30.0,
        "chg_20d_max": 0.0,
        "label": "当日跌幅 > 5%，20日跌幅 > 0",
    },
    "💎 低估值": {
        "pe_max": 15.0,
        "pe_min": 0.1,
        "change_pct_min": 0.0,
        "label": "PE < 15 + 涨幅 > 0",
    },
}


# ============================================================
# 主渲染函数
# ============================================================

def render():
    st.header("🔎 快速股票筛选")
    st.caption("纯本地数据 · 零网络请求 · 秒级响应")

    # --- 加载数据 ---
    with st.spinner("加载数据中..."):
        df = _load_screener_data()

    if df.empty:
        st.warning("⚠️ 未加载到TDX统计数据，请确认 tdxstat.cfg 文件存在")
        return

    st.caption(f"📊 已加载 {len(df):,} 只股票")

    # --- 侧边栏过滤器 ---
    with st.sidebar:
        st.subheader("🎛️ 筛选条件")

        # ---- 预设按钮 ----
        st.caption("快捷预设:")
        cols_preset = st.columns(2)
        active_preset = None
        for i, (label, cfg) in enumerate(PRESETS.items()):
            col = cols_preset[i % 2]
            if col.button(label, key=f"preset_{i}", use_container_width=True):
                active_preset = cfg

        st.divider()

        # ---- 涨幅 ----
        st.caption("涨幅范围 (%)")
        col1, col2 = st.columns(2)
        with col1:
            chg_min = st.number_input(
                "涨幅≥", value=-20.0, step=0.5,
                key="chg_min", format="%.1f",
            )
        with col2:
            chg_max = st.number_input(
                "涨幅≤", value=20.0, step=0.5,
                key="chg_max", format="%.1f",
            )

        # ---- 换手率 ----
        st.caption("换手率范围 (%)")
        col1, col2 = st.columns(2)
        with col1:
            to_min = st.number_input(
                "换手≥", value=0.0, step=0.5,
                key="to_min", format="%.1f",
            )
        with col2:
            to_max = st.number_input(
                "换手≤", value=100.0, step=1.0,
                key="to_max", format="%.1f",
            )

        # ---- 量比 ----
        vol_min = st.number_input(
            "量比 ≥", value=0.0, step=0.1,
            key="vol_min", format="%.1f",
        )

        # ---- PE ----
        st.caption("市盈率范围")
        col1, col2 = st.columns(2)
        with col1:
            pe_min = st.number_input(
                "PE≥", value=0.0, step=1.0,
                key="pe_min", format="%.1f",
            )
        with col2:
            pe_max = st.number_input(
                "PE≤", value=1000.0, step=10.0,
                key="pe_max", format="%.1f",
            )

        # ---- 市值 ----
        st.caption("市值范围 (亿)")
        col1, col2 = st.columns(2)
        with col1:
            mv_min = st.number_input(
                "市值≥", value=0.0, step=1.0,
                key="mv_min", format="%.1f",
            )
        with col2:
            mv_max = st.number_input(
                "市值≤", value=50000.0, step=100.0,
                key="mv_max", format="%.1f",
            )

        # ---- 20日涨跌幅 ----
        st.caption("20日涨跌幅范围 (%)")
        col1, col2 = st.columns(2)
        with col1:
            chg20_min = st.number_input(
                "20日≥", value=-100.0, step=1.0,
                key="chg20_min", format="%.1f",
            )
        with col2:
            chg20_max = st.number_input(
                "20日≤", value=100.0, step=1.0,
                key="chg20_max", format="%.1f",
            )

        # ---- 行业 ----
        st.divider()
        industries = _load_industry_list()
        selected_industry = st.selectbox(
            "行业板块",
            options=["全部"] + industries,
            index=0,
            key="industry_filter",
        )

    # --- 应用预设 ---
    if active_preset:
        cfg = active_preset
        if "change_pct_min" in cfg:
            st.session_state.chg_min = cfg["change_pct_min"]
        if "change_pct_max" in cfg:
            st.session_state.chg_max = cfg["change_pct_max"]
        if "volume_ratio_min" in cfg:
            st.session_state.vol_min = cfg["volume_ratio_min"]
        if "pe_max" in cfg:
            st.session_state.pe_max = cfg["pe_max"]
        if "pe_min" in cfg:
            st.session_state.pe_min = cfg["pe_min"]
        if "chg_20d_min" in cfg:
            st.session_state.chg20_min = cfg["chg_20d_min"]
        if "chg_20d_max" in cfg:
            st.session_state.chg20_max = cfg["chg_20d_max"]
        st.info(f"✅ 已应用预设: {cfg['label']}")
        st.rerun()

    # --- 应用过滤 ---
    mask = pd.Series(True, index=df.index)

    mask &= (df["_change_pct"] >= chg_min) & (df["_change_pct"] <= chg_max)
    mask &= (df["_turnover"] >= to_min) & (df["_turnover"] <= to_max)
    mask &= df["_volume_ratio"] >= vol_min
    mask &= (df["_pe"] >= pe_min) & (df["_pe"] <= pe_max)
    mask &= (df["_total_mv_yi"] >= mv_min) & (df["_total_mv_yi"] <= mv_max)
    mask &= (df["_chg_20d"] >= chg20_min) & (df["_chg_20d"] <= chg20_max)

    # 行业过滤
    if selected_industry and selected_industry != "全部":
        ind_name = selected_industry.rsplit(" (", 1)[0]  # 去掉 "(N)" 后缀
        mask &= df["行业"] == ind_name

    filtered = df[mask]

    # --- 结果展示 ---
    st.subheader(f"筛选结果 ({len(filtered):,} 只)")

    # 显示列 (隐藏内部排序列)
    display_cols = ["代码", "名称", "涨幅%", "换手%", "量比", "PE", "市值_亿", "20日涨幅%", "行业"]
    display_df = filtered[display_cols].copy()

    # 应用列排序
    sort_col = st.selectbox(
        "排序字段",
        options=display_cols,
        index=2,  # 默认按涨幅排序
        key="sort_col",
    )
    sort_order = st.radio("排序方向", ["降序 ↓", "升序 ↑"], horizontal=True, index=0)

    # 映射显示列到内部排序列
    sort_map = {
        "代码": "代码",
        "名称": "名称",
        "涨幅%": "_change_pct",
        "换手%": "_turnover",
        "量比": "_volume_ratio",
        "PE": "_pe",
        "市值_亿": "_total_mv_yi",
        "20日涨幅%": "_chg_20d",
        "行业": "行业",
    }
    key_col = sort_map.get(sort_col, sort_col)
    ascending = sort_order == "升序 ↑"
    display_df = display_df.iloc[filtered[key_col].argsort(
        ascending=ascending, na_position="last"
    )]

    # 表格显示
    st.dataframe(
        display_df.rename(columns={"市值_亿": "市值(亿)", "换手%": "换手%"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="medium"),
            "涨幅%": st.column_config.NumberColumn(format="%.2f"),
            "换手%": st.column_config.NumberColumn(format="%.2f"),
            "量比": st.column_config.NumberColumn(format="%.2f"),
            "PE": st.column_config.NumberColumn(format="%.1f"),
            "市值(亿)": st.column_config.NumberColumn(format="%.2f"),
            "20日涨幅%": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    # --- 底部信息 ---
    if len(display_df) > 0:
        top_chg = filtered["_change_pct"].max()
        bottom_chg = filtered["_change_pct"].min()
        avg_to = filtered["_turnover"].mean()
        st.caption(
            f"统计: 涨幅区间 [{bottom_chg:+.1f}%, {top_chg:+.1f}%] | "
            f"均换手率 {avg_to:.2f}% | "
            f"共 {len(filtered)} 只"
        )
