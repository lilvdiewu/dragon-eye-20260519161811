"""
龙瞳Pro - 板块热度页面

行业板块热力图 + 概念板块排名 + 轮动信号 + 板块成分股查看
"""
from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
import plotly.figure_factory as ff
import pandas as pd


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _cached_industry_sectors() -> list:
    """缓存行业板块数据（5分钟过期）"""
    from dragon_eye.sector.ths_sector import ThsSectorFetcher, SectorRanker
    fetcher = ThsSectorFetcher()
    ranker = SectorRanker()

    sectors = fetcher.get_industry_summary()
    if not sectors:
        sectors = fetcher.get_industry_list()
    if sectors:
        sectors = ranker.rank(sectors)
    return sectors


@st.cache_data(ttl=300, show_spinner=False)
def _cached_concept_sectors() -> list:
    """缓存概念板块数据（5分钟过期）"""
    from dragon_eye.sector.ths_sector import ThsSectorFetcher, SectorRanker, SectorStrength
    fetcher = ThsSectorFetcher()
    ranker = SectorRanker()

    # 本地缓存：概念数据一天内有效，避免每次重启都等AkShare
    cache_dir = Path(tempfile.gettempdir()) / "dragon_eye"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "concept_cache.json"
    cache_age = 86400  # 24h

    if cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime < cache_age:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                sectors = cached.get("sectors", [])
                return [SectorStrength(**s) for s in sectors]
        except Exception:
            pass

    # 在线获取 — 优先用concept_summary（有涨跌幅+资金流向），回落用concept_list（快但只有名字）
    sectors = fetcher.get_concept_summary()
    if not sectors:
        sectors = fetcher.get_concept_list()
    if sectors:
        sectors = ranker.rank(sectors)

        # 保存到本地缓存
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"sectors": [s.__dict__ for s in sectors], "cached_at": time.time()}, f, ensure_ascii=False)
        except Exception:
            pass

    return sectors


def render():
    st.header("🔥 板块热度")

    # ---- Tab切换 ----
    tab1, tab2, tab3 = st.tabs(["🏭 行业板块", "💡 概念板块", "📊 板块对比"])

    with tab1:
        _render_industry_sectors()

    with tab2:
        _render_concept_sectors()

    with tab3:
        _render_sector_compare()


def _render_industry_sectors():
    """行业板块热力图 + 排名"""
    with st.spinner("正在获取同花顺行业板块数据..."):
        sectors = _cached_industry_sectors()

    if not sectors:
        st.warning("⚠️ 行业板块数据获取失败，请检查网络连接")
        return

    # ---- 强度分布 ----
    col1, col2, col3, col4 = st.columns(4)
    s_count = sum(1 for s in sectors if s.grade == "S")
    a_count = sum(1 for s in sectors if s.grade == "A")
    b_count = sum(1 for s in sectors if s.grade == "B")
    c_count = sum(1 for s in sectors if s.grade == "C")

    col1.metric("S级 最热", f"{s_count} 个", delta="🔥🔥🔥", delta_color="off")
    col2.metric("A级 强势", f"{a_count} 个", delta="🔥🔥", delta_color="off")
    col3.metric("B级 中性", f"{b_count} 个", delta="🔥", delta_color="off")
    col4.metric("C级 弱势", f"{c_count} 个", delta="❄️", delta_color="off")

    st.divider()

    # ---- 热力图 ----
    st.subheader("行业板块热力图")
    _render_heatmap(sectors)

    st.divider()

    # ---- 排名表格 ----
    st.subheader("行业板块排名")

    # 筛选
    col1, col2 = st.columns([1, 3])
    with col1:
        grade_filter = st.multiselect(
            "等级筛选",
            ["S", "A", "B", "C"],
            default=["S", "A"],
            key="industry_grade",
        )
    with col2:
        rotation_filter = st.multiselect(
            "轮动信号",
            ["加速上攻", "持续强势", "触底反弹", "弱势下行", "震荡整理"],
            default=["加速上攻", "持续强势", "触底反弹"],
            key="industry_rotation",
        )

    filtered = sectors
    if grade_filter:
        filtered = [s for s in filtered if s.grade in grade_filter]
    if rotation_filter:
        filtered = [s for s in filtered if s.rotation_signal in rotation_filter]

    # 构建表格
    rows = []
    for s in filtered:
        # 红涨绿跌标记
        change_color = "🔴" if s.change_pct < 0 else "🟢"
        rows.append({
            "板块": s.name,
            "等级": s.grade,
            "强度分": s.strength_score,
            "涨跌幅": f"{change_color} {s.change_pct:+.2f}%",
            "净流入(亿)": round(s.net_inflow, 2),
            "换手率": f"{s.turnover:.2f}%",
            "轮动信号": s.rotation_signal,
        })

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("没有符合条件的板块")

    # ---- 板块详情查看 ----
    st.divider()
    st.subheader("查看板块详情")
    sector_names = [s.name for s in sectors]
    selected_sector = st.selectbox("选择行业板块", sector_names, key="industry_detail_select")

    if st.button("📊 查看详情", key="view_industry_detail"):
        with st.spinner(f"正在获取 {selected_sector} 成分股..."):
            from dragon_eye.sector.ths_sector import ThsSectorFetcher
            fetcher = ThsSectorFetcher()
            detail = fetcher.get_industry_detail(selected_sector)

        if detail and detail.get("stocks"):
            st.success(f"**{selected_sector}** 共 {detail['stock_count']} 只成分股")
            stock_rows = detail["stocks"][:50]  # 最多显示50只
            st.dataframe(stock_rows, use_container_width=True, hide_index=True)
        else:
            st.warning("成分股数据获取失败")


def _render_concept_sectors():
    """概念板块排名"""
    with st.spinner("正在获取同花顺概念板块数据..."):
        sectors = _cached_concept_sectors()

    if not sectors:
        st.warning("⚠️ 概念板块数据获取失败，请检查网络连接")
        return

    # ---- 概念搜索 ----
    search_keyword = st.text_input("🔍 搜索概念", placeholder="输入关键词...")

    filtered = sectors
    if search_keyword:
        filtered = [s for s in filtered if search_keyword in s.name]

    # ---- 概念排名 ----
    st.subheader(f"概念板块排名 ({len(filtered)} 个)")

    rows = []
    for s in filtered[:100]:  # 最多显示100个
        change_color = "🔴" if s.change_pct < 0 else "🟢"
        rows.append({
            "概念": s.name,
            "等级": s.grade,
            "强度分": s.strength_score,
            "涨跌幅": f"{change_color} {s.change_pct:+.2f}%",
            "净流入(亿)": round(s.net_inflow, 2),
            "轮动信号": s.rotation_signal,
        })

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("没有匹配的概念板块")

    # ---- 热门概念 TOP20 ----
    st.divider()
    st.subheader("热门概念 TOP20")

    top20 = filtered[:20]
    if top20:
        fig = go.Figure(data=[
            go.Bar(
                x=[s.change_pct for s in top20],
                y=[s.name for s in top20],
                orientation="h",
                marker_color=["#ff4b4b" if s.change_pct > 0 else "#4baf4f" for s in top20],
                text=[f"{s.change_pct:+.2f}%" for s in top20],
                textposition="outside",
            )
        ])
        fig.update_layout(
            height=500,
            margin=dict(l=120, r=30, t=30, b=20),
            xaxis_title="涨跌幅%",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---- 概念详情 ----
    st.divider()
    st.subheader("查看概念详情")
    concept_names = [s.name for s in sectors]
    selected_concept = st.selectbox("选择概念板块", concept_names, key="concept_detail_select")

    if st.button("📊 查看概念详情", key="view_concept_detail"):
        with st.spinner(f"正在获取 {selected_concept} 成分股..."):
            from dragon_eye.sector.ths_sector import ThsSectorFetcher
            fetcher = ThsSectorFetcher()
            detail = fetcher.get_concept_detail(selected_concept)

        if detail and detail.get("stocks"):
            st.success(f"**{selected_concept}** 共 {detail['stock_count']} 只成分股")
            stock_rows = detail["stocks"][:50]
            st.dataframe(stock_rows, use_container_width=True, hide_index=True)
        else:
            st.warning("成分股数据获取失败")


def _render_sector_compare():
    """板块对比分析"""
    st.subheader("板块对比")

    col1, col2 = st.columns(2)
    with col1:
        industry_sectors = _cached_industry_sectors()
        industry_names = [s.name for s in industry_sectors]
        selected_industries = st.multiselect(
            "选择行业板块（最多5个）",
            industry_names,
            default=industry_names[:3] if len(industry_names) >= 3 else industry_names,
            max_selections=5,
            key="compare_industry",
        )
    with col2:
        concept_sectors = _cached_concept_sectors()
        concept_names = [s.name for s in concept_sectors]
        selected_concepts = st.multiselect(
            "选择概念板块（最多5个）",
            concept_names,
            default=concept_names[:2] if len(concept_names) >= 2 else concept_names,
            max_selections=5,
            key="compare_concept",
        )

    if st.button("📈 开始对比", key="start_compare"):
        # 构建对比数据
        all_selected = []
        for s in industry_sectors:
            if s.name in selected_industries:
                s.sector_type = "industry"
                all_selected.append(s)
        for s in concept_sectors:
            if s.name in selected_concepts:
                s.sector_type = "concept"
                all_selected.append(s)

        if not all_selected:
            st.warning("请至少选择一个板块")
            return

        # 对比表格
        rows = []
        for s in all_selected:
            type_label = "🏭" if s.sector_type == "industry" else "💡"
            rows.append({
                "类型": type_label,
                "板块": s.name,
                "涨跌幅": s.change_pct,
                "强度分": s.strength_score,
                "等级": s.grade,
                "净流入(亿)": round(s.net_inflow, 2),
                "轮动信号": s.rotation_signal,
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)

        # 涨跌幅对比柱状图
        fig = go.Figure(data=[
            go.Bar(
                x=[s.name for s in all_selected],
                y=[s.change_pct for s in all_selected],
                marker_color=["#ff4b4b" if s.change_pct > 0 else "#4baf4f" for s in all_selected],
                text=[f"{s.change_pct:+.2f}%" for s in all_selected],
                textposition="outside",
            )
        ])
        fig.update_layout(
            title="涨跌幅对比",
            height=350,
            margin=dict(l=20, r=20, t=40, b=60),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig, use_container_width=True)


def _render_heatmap(sectors: list):
    """板块热力图

    用涨跌幅渲染颜色，格子大小表示强度
    """
    if not sectors:
        st.info("暂无数据")
        return

    # 取TOP30做热力图
    top = sectors[:30]

    # 用plotly做简单的treemap
    names = [s.name for s in top]
    changes = [s.change_pct for s in top]
    strengths = [s.strength_score for s in top]

    fig = go.Figure(go.Treemap(
        labels=names,
        parents=["行业板块"] * len(names),
        values=[max(1, s + 10) for s in strengths],  # 避免负值
        marker=dict(
            colors=changes,
            colorscale=[
                [0, "#4baf4f"],     # 深绿 = 大跌
                [0.3, "#90c695"],   # 浅绿
                [0.5, "#f0f0f0"],   # 灰色 = 持平
                [0.7, "#ff9999"],   # 浅红
                [1, "#ff4b4b"],     # 深红 = 大涨
            ],
            showscale=True,
            colorbar=dict(title="涨跌幅%"),
        ),
        text=[f"{s.name}<br>{s.change_pct:+.2f}%<br>{s.grade}级" for s in top],
        textinfo="label",
        hovertemplate="<b>%{label}</b><br>涨跌幅: %{color:+.2f}%<extra></extra>",
    ))

    fig.update_layout(
        height=400,
        margin=dict(l=10, r=10, t=10, b=10),
    )

    st.plotly_chart(fig, use_container_width=True)
