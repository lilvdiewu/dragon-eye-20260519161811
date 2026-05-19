"""
龙瞳Pro - A股智能投研平台

Streamlit多页面应用入口
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path 中，dragon_eye 包可被导入
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

st.set_page_config(
    page_title="龙瞳Pro - A股智能投研",
    page_icon="🐉",
    layout="wide",
)

# 侧边栏导航
with st.sidebar:
    st.title("🐉 龙瞳Pro")
    st.caption("A股智能投研平台 v2.0")
    st.divider()
    page = st.radio(
        "导航",
        ["🏠 首页仪表盘", "🎯 智能选股", "🔥 板块热度", "🔍 全市场扫描", "📊 个股分析", "⚡ 策略回测", "📋 深度复盘", "🔔 通知设置"],
        label_visibility="collapsed",
    )
    st.divider()

    # 板块缓存管理
    st.subheader("📦 板块缓存")
    try:
        from dragon_eye.akshare_bridge import get_bridge as _get_bridge
        _bridge_inst = _get_bridge()
        _meta = _bridge_inst._get_sector_cache_meta()
        if _meta:
            _count = _meta.get("stock_count", 0)
            _built = _meta.get("built_at", "unknown")
            # 计算缓存年龄
            if _built != "unknown":
                try:
                    from datetime import datetime as _dt
                    _built_dt = _dt.fromisoformat(_built)
                    _age_hours = (_dt.now() - _built_dt).total_seconds() / 3600
                    if _age_hours < 1:
                        _age_str = f"{_age_hours * 60:.0f}分钟前"
                    elif _age_hours < 24:
                        _age_str = f"{_age_hours:.1f}小时前"
                    else:
                        _age_str = f"{_age_hours / 24:.1f}天前"
                except Exception:
                    _age_str = _built[:10]
            else:
                _age_str = "未知"
            st.success(f"已缓存 {_count} 只股票归属\n\n🕐 {_age_str}构建", icon="✅")
        else:
            st.warning("板块缓存未构建", icon="⚠️")
    except Exception:
        st.warning("板块缓存状态读取失败", icon="⚠️")

    if st.button("🔄 刷新板块缓存", use_container_width=True):
        with st.spinner("正在构建板块归属缓存（约1-3分钟）..."):
            from dragon_eye.akshare_bridge import get_bridge
            _bridge = get_bridge()
            _mapping = _bridge.build_sector_cache()
            if _mapping:
                st.success(f"✅ 缓存构建完成: {len(_mapping)} 只股票", icon="🎉")
            else:
                st.error("❌ 缓存构建失败，请检查网络连接")
        st.rerun()

    if st.button("🔄 刷新概念板块", use_container_width=True):
        with st.spinner("正在拉取概念板块数据..."):
            from dragon_eye.pages.sector_heat import _cached_concept_sectors
            _cached_concept_sectors.clear()
            _cached_concept_sectors()
            st.success("✅ 概念板块数据已刷新", icon="🎉")
        st.rerun()

    st.divider()
    st.caption("数据来源: 通达信本地 + AkShare")

# 根据选择渲染不同页面
if page == "🏠 首页仪表盘":
    from pages.dashboard import render
    render()
elif page == "🎯 智能选股":
    from pages.smart_screener import render
    render()
elif page == "🔥 板块热度":
    from pages.sector_heat import render
    render()
elif page == "🔍 全市场扫描":
    from pages.screener import render
    render()
elif page == "📊 个股分析":
    from pages.stock_analysis import render
    render()
elif page == "⚡ 策略回测":
    from pages.backtest import render
    render()
elif page == "📋 深度复盘":
    from pages.daily_review import render
    render()
elif page == "🔔 通知设置":
    from pages.push_settings import render
    render()
