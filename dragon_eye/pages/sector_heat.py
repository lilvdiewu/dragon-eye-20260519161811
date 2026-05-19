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
def _cached_concept_sectors_tdx() -> list:
    """从TDX本地 infoharbor_block.dat 加载概念板块 + TDX动量"""
    from dragon_eye.sector.ths_sector import TdxSectorMapper, SectorStrength, SectorRanker
    from dragon_eye.sector.tdx_sector_reader import TdxSectorReader
    
    mapper = TdxSectorMapper()
    mapper.load_infoharbor()
    
    # 加载TDX动量数据
    tdx = TdxSectorReader()
    tdx.load_sector_map()
    
    ranker = SectorRanker()
    sectors = []
    for concept_name, stocks in mapper._concept_map.items():
        # 关联TDX动量
        mom_3d, mom_5d, chg_pct = 0.0, 0.0, 0.0
        tdx_code = tdx.get_code(concept_name)
        if tdx_code:
            mom = tdx.get_momentum(concept_name)
            if mom:
                chg_pct = mom.get("change_pct", 0.0)
                mom_3d = mom.get("momentum_3d", 0.0)
                mom_5d = mom.get("momentum_5d", 0.0)
        
        s = SectorStrength(
            name=concept_name,
            sector_type="concept",
            change_pct=chg_pct,
            net_inflow=0,
            turnover=0,
            momentum_3d=mom_3d,
            momentum_5d=mom_5d,
            up_ratio=len(stocks) / 5000,
        )
        s.stock_count = len(stocks)
        sectors.append(s)

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
    """概念板块排名（基于TDX本地 infoharbor_block.dat，含成分股数）"""
    with st.spinner("正在加载TDX概念板块数据..."):
        sectors = _cached_concept_sectors_tdx()

    if not sectors:
        st.warning("⚠️ 概念板块数据加载失败，请检查TDX数据")
        return

    # ---- 概念搜索 ----
    search_keyword = st.text_input("🔍 搜索概念", placeholder="输入关键词...")

    filtered = sectors
    if search_keyword:
        filtered = [s for s in filtered if search_keyword in s.name]

    # ---- 概念排名（按成分股数量+强度分） ----
    st.subheader(f"概念板块 ({len(filtered)} 个)")
    st.caption("📦 数据来源: TDX本地 infoharbor_block.dat | 成分股数=板块覆盖广度")

    rows = []
    for s in filtered[:100]:
        rows.append({
            "概念": s.name,
            "等级": s.grade,
            "强度分": s.strength_score,
            "成分股数": s.stock_count if hasattr(s, 'stock_count') and s.stock_count else "--",
            "联动性": f"{s.up_ratio:.0%}" if hasattr(s, 'up_ratio') and s.up_ratio else "——",
        })

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("没有匹配的概念板块")

    # ---- 热门概念 TOP20（按成分股数） ----
    st.divider()
    st.subheader("热门概念 TOP20（成分股最多）")

    by_count = sorted(filtered, key=lambda s: getattr(s, 'stock_count', 0) or 0, reverse=True)
    top20 = by_count[:20]
    if top20:
        fig = go.Figure(data=[
            go.Bar(
                x=[getattr(s, 'stock_count', 0) or 0 for s in top20],
                y=[s.name for s in top20],
                orientation="h",
                marker_color="#1f77b4",
                text=[getattr(s, 'stock_count', 0) or 0 for s in top20],
                textposition="outside",
            )
        ])
        fig.update_layout(
            title="成分股数量排名",
            height=500,
            margin=dict(l=20, r=40, t=40, b=20),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("数据不足")


def _render_sector_compare():
    """板块对比（行业 vs 概念）"""
    st.subheader("行业 vs 概念 对比")

    industry_sectors = _cached_industry_sectors()
    concept_sectors = _cached_concept_sectors_tdx()

    col1, col2 = st.columns(2)
    with col1:
        ind_names = [s.name for s in industry_sectors]
        selected_inds = st.multiselect(
            "选择行业板块（最多5个）",
            ind_names,
            default=ind_names[:3] if len(ind_names) >= 3 else ind_names,
            max_selections=5,
            key="compare_industry",
        )
    with col2:
        con_names = [s.name for s in concept_sectors]
        selected_cons = st.multiselect(
            "选择概念板块（最多5个）",
            con_names,
            default=con_names[:2] if len(con_names) >= 2 else con_names,
            max_selections=5,
            key="compare_concept",
        )

    if st.button("📈 开始对比", key="start_compare"):
        all_selected = []
        for s in industry_sectors:
            if s.name in selected_inds:
                s.sector_type = "industry"
                all_selected.append(s)
        for s in concept_sectors:
            if s.name in selected_cons:
                s.sector_type = "concept"
                all_selected.append(s)

        if not all_selected:
            st.warning("请至少选择一个板块")
            return

        rows = []
        for s in all_selected:
            type_label = "🏭" if s.sector_type == "industry" else "💡"
            stock_cnt = getattr(s, 'stock_count', 0) or 0
            rows.append({
                "类型": type_label,
                "板块": s.name,
                "涨跌幅": f"{s.change_pct:+.2f}%" if s.change_pct else "——",
                "强度分": s.strength_score,
                "等级": s.grade,
                "成分股数": stock_cnt if s.sector_type == "concept" else "——",
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)

        fig = go.Figure(data=[
            go.Bar(
                x=[s.name for s in all_selected],
                y=[s.strength_score for s in all_selected],
                marker_color=["#1f77b4" if s.sector_type == "industry" else "#ff7f0e" for s in all_selected],
                text=[f"{s.strength_score:.0f}" for s in all_selected],
                textposition="outside",
            )
        ])
        fig.update_layout(
            title="强度分对比（蓝=行业 / 橙=概念）",
            height=350,
            margin=dict(l=20, r=20, t=40, b=80),
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
