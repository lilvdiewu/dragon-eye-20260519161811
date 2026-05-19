"""
龙瞳Pro - 板块产业链页

选择概念 / 产业链拆解 / 成分股和龙头 / 龙头评分排行
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def _cached_stock_names() -> dict:
    """缓存股票名称映射（60秒过期）"""
    from dragon_eye.akshare_bridge import get_bridge
    bridge = get_bridge()
    return bridge.enrich_stock_names([])


def render():
    st.header("🏭 板块产业链")

    # ---- 概念选择 ----
    col1, col2 = st.columns([3, 1])
    with col1:
        concept = st.text_input("输入概念名称", value="人工智能", placeholder="如: 固态电池、人形机器人、半导体")
    with col2:
        st.write("")
        st.write("")
        analyze_btn = st.button("分析", type="primary", width="stretch")

    if not concept:
        st.info("请输入概念名称")
        return

    # 预设概念列表
    preset_concepts = [
        "固态电池", "人工智能", "人形机器人", "半导体",
        "新能源车", "光伏", "低空经济", "数据要素", "算力",
    ]
    selected_preset = st.selectbox("或选择预设概念", [""] + preset_concepts)
    if selected_preset:
        concept = selected_preset

    if not analyze_btn and not selected_preset:
        return

    # ---- 执行分析 ----
    from dragon_eye.sector import ChainAnalyzer

    with st.spinner(f"正在分析「{concept}」产业链..."):
        try:
            analyzer = ChainAnalyzer()
            result = analyzer.analyze(concept)
        except Exception as e:
            st.error(f"产业链分析失败: {e}")
            return

    if not result.chains and not result.leader_stocks:
        st.warning(f"未找到「{concept}」的产业链数据")
        return

    # ---- 概要 ----
    if result.summary:
        st.success(result.summary)

    st.divider()

    # ---- 产业链拆解图 ----
    _render_chain_diagram(result)

    st.divider()

    # ---- 各环节详情 ----
    _render_chain_details(result)

    st.divider()

    # ---- 龙头评分排行 ----
    _render_leader_ranking(result)


def _render_chain_diagram(result):
    """产业链拆解可视化"""
    st.subheader("产业链拆解")

    if not result.chains:
        st.info("暂无产业链数据")
        return

    # 用条形图展示各环节成分股数量
    roles = []
    names = []
    counts = []
    colors_map = {"上游": "#ff6b6b", "中游": "#ffd93d", "下游": "#6bcb77"}

    for node in result.chains:
        roles.append(node.role)
        names.append(f"{node.role}·{node.name}")
        counts.append(len(node.stocks))

    fig = go.Figure(go.Bar(
        x=counts,
        y=names,
        orientation="h",
        marker_color=[colors_map.get(r, "#636efa") for r in roles],
        text=counts,
        textposition="outside",
    ))
    fig.update_layout(
        title="产业链各环节成分股数量",
        height=max(200, len(names) * 40 + 80),
        margin=dict(l=20, r=40, t=40, b=20),
        xaxis_title="成分股数量",
        yaxis_title="",
    )
    st.plotly_chart(fig, width="stretch")


def _render_chain_details(result):
    """各环节成分股详情"""
    st.subheader("各环节成分股")

    if not result.chains:
        return

    for node in result.chains:
        with st.expander(f"{node.role} - {node.name} ({len(node.stocks)}只)", expanded=False):
            if not node.stocks:
                st.info("暂无成分股数据")
                continue

            # 获取股票名称
            name_map = {}
            try:
                name_map = _cached_stock_names()
            except Exception:
                pass

            # 显示成分股列表
            stock_rows = []
            for code6 in node.stocks:
                stock_rows.append({
                    "代码": code6,
                    "名称": name_map.get(code6, "--"),
                })

            if stock_rows:
                st.dataframe(stock_rows, hide_index=True, width="stretch", height=200)


def _render_leader_ranking(result):
    """龙头评分排行"""
    st.subheader("龙头评分排行")

    if not result.leader_stocks:
        st.info("暂无龙头评分数据")
        return

    rows = []
    for s in result.leader_stocks[:20]:
        rows.append({
            "代码": s.code,
            "名称": s.name or "--",
            "综合评分": s.score,
            "市值排名": s.market_cap_rank,
            "技术面": s.tech_rank,
            "资金面": s.fund_rank,
            "估值": s.valuation_rank,
            "量能": s.volume_rank,
            "总市值(亿)": f"{s.market_cap:.0f}" if s.market_cap > 0 else "--",
        })

    if rows:
        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            column_config={
                "综合评分": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )

        # 龙头评分雷达图（TOP5）
        top5 = result.leader_stocks[:5]
        if len(top5) >= 2:
            categories = ["市值", "技术面", "资金面", "估值", "量能"]
            fig = go.Figure()
            for s in top5:
                fig.add_trace(go.Scatterpolar(
                    r=[s.market_cap_rank, s.tech_rank, s.fund_rank, s.valuation_rank, s.volume_rank],
                    theta=categories,
                    fill="toself",
                    name=s.name or s.code,
                ))
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                title="龙头评分雷达图 (TOP5)",
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig, width="stretch")
