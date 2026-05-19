"""
盘后深度复盘 — 每日收盘后运行

核心理念：不追求快，追求深度。
像第二个交易员跟你一起复盘，补你一个人看不到的维度。
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _get_today_date():
    return datetime.now().strftime("%Y-%m-%d")


@st.cache_data(ttl=300, show_spinner=False)
def _get_all_stocks_with_sectors():
    """获取全市场股票 + 行业/概念归属"""
    from dragon_eye.sector.ths_sector import TdxSectorMapper
    from dragon_eye.dataflows.dragon_eye_vendor import _get_dbf_reader
    mapper = TdxSectorMapper()
    mapper.load_all()
    dbf = _get_dbf_reader()
    stocks = dbf.get_all_stocks()
    result = []
    for s in stocks:
        code = s.get("code", "")
        result.append({
            "code": code,
            "name": s.get("name", code),
            "market": "SH" if code.startswith("6") or code.startswith("9") else "SZ",
            "industry": mapper.get_industry(code),
            "concepts": mapper.get_concepts(code)[:5],
        })
    return result


@st.cache_data(ttl=600, show_spinner=False)
def _get_industry_sectors():
    """行业板块排名（含涨跌幅）"""
    from dragon_eye.pages.sector_heat import _cached_industry_sectors
    return _cached_industry_sectors()


@st.cache_data(ttl=600, show_spinner=False)
def _get_concept_sectors():
    """概念板块排名（TDX本地）"""
    from dragon_eye.pages.sector_heat import _cached_concept_sectors_tdx
    return _cached_concept_sectors_tdx()


@st.cache_data(ttl=300, show_spinner=False)
def _get_kline_for_code(code6: str, market: str):
    """获取个股K线（缓存共用）"""
    from dragon_eye.tdx_reader import TdxReader
    reader = TdxReader()
    try:
        return reader.get_day_klines(code6, market)
    except Exception:
        return []


# ============================================================
# 渲染入口
# ============================================================

def render():
    st.header("📋 盘后深度复盘")

    date = _get_today_date()
    st.caption(f"📅 {date} · 点击下方按钮开始分析")

    if st.button("🔍 开始盘后复盘", type="primary", use_container_width=True):
        with st.spinner("正在深度复盘，请稍候（约30-60秒）..."):
            results = _run_deep_review()

        _render_review_report(results)


# ============================================================
# 复盘核心逻辑
# ============================================================

def _run_deep_review() -> dict:
    """执行深度复盘，返回结构化结果"""
    results = {}

    # 1. 主线确认
    results["main_themes"] = _analyze_main_themes()

    # 2. 龙头梳理
    results["dragon_heads"] = _identify_dragon_heads(results["main_themes"])

    # 3. 市场情绪
    results["sentiment"] = _assess_sentiment()

    # 4. 联动分析
    results["sector_linkage"] = _analyze_sector_linkage(results["main_themes"])

    return results


def _analyze_main_themes() -> list:
    """
    主线确认：不只是看今天涨跌，看多日持续性
    - 行业板块按强度分排序
    - 标记主线候选（连续走强 + 有龙头带队）
    """
    ind_sectors = _get_industry_sectors()
    con_sectors = _get_concept_sectors()

    themes = []

    # 行业板块排名
    if ind_sectors:
        st.info(f"📊 行业板块分析：{len(ind_sectors)} 个板块")
        # 按强度分排序取前10
        top_ind = sorted(ind_sectors, key=lambda s: s.strength_score, reverse=True)[:10]
        for s in top_ind:
            themes.append({
                "name": s.name,
                "type": "行业",
                "grade": s.grade,
                "score": s.strength_score,
                "change_pct": s.change_pct,
                "inflow": getattr(s, 'net_inflow', 0),
                "rotation": getattr(s, 'rotation_signal', ''),
                "stock_count": 0,  # 行业没有成分股数
            })

    # 概念板块排名（按成分股数+强度排序）
    if con_sectors:
        st.info(f"📊 概念板块分析：{len(con_sectors)} 个板块")
        top_con = sorted(con_sectors, key=lambda s: s.strength_score, reverse=True)[:15]
        for s in top_con:
            stock_cnt = getattr(s, 'stock_count', 0) or 0
            themes.append({
                "name": s.name,
                "type": "概念",
                "grade": s.grade,
                "score": s.strength_score,
                "change_pct": s.change_pct,
                "inflow": 0,
                "rotation": "",
                "stock_count": stock_cnt,
            })

    # 综合排序
    themes.sort(key=lambda t: t["score"], reverse=True)
    return themes


def _identify_dragon_heads(themes: list) -> dict:
    """
    主线龙头识别：在每个热点板块里找龙头
    - 涨幅最大
    - 成交量最大
    - K线位置（突破/高位/低位）
    """
    if not themes:
        return {}

    stocks = _get_all_stocks_with_sectors()
    heads = {}

    # 取前5个主线
    for theme in themes[:5]:
        theme_name = theme["name"]
        # 找属于这个板块的股票
        members = []
        for s in stocks:
            if theme["type"] == "行业" and s["industry"] == theme_name:
                members.append(s)
            elif theme["type"] == "概念" and theme_name in s["concepts"]:
                members.append(s)

        if not members:
            continue

        # 分析每只成分股的最近表现
        stock_scores = []
        for member in members[:50]:  # 限制数量
            kl = _get_kline_for_code(member["code"], member["market"])
            if not kl or len(kl) < 5:
                continue

            # 近5日涨幅
            latest_close = kl[-1].close
            day5_close = kl[-5].close if len(kl) >= 5 else kl[0].close
            chg_5d = (latest_close - day5_close) / day5_close * 100

            # 近1日涨幅 + 放量情况
            today_chg = (kl[-1].close - kl[-2].close) / kl[-2].close * 100 if len(kl) >= 2 else 0
            today_vol = kl[-1].volume
            prev_vol = kl[-2].volume if len(kl) >= 2 else 1
            vol_ratio = today_vol / prev_vol if prev_vol > 0 else 1

            # 位置判断
            ma5 = sum(k.close for k in kl[-5:]) / min(5, len(kl))
            position = "突破高位" if latest_close > ma5 * 1.05 else ("支撑位" if latest_close < ma5 * 0.95 else "均线附近")

            stock_scores.append({
                "code": member["code"],
                "name": member["name"],
                "chg_today": today_chg,
                "chg_5d": chg_5d,
                "vol_ratio": vol_ratio,
                "position": position,
                "composite": today_chg * 0.5 + chg_5d * 0.3 + (vol_ratio - 1) * 2,
            })

        if stock_scores:
            stock_scores.sort(key=lambda x: x["composite"], reverse=True)
            heads[theme_name] = stock_scores[:5]  # 前5只龙头候选

    return heads


def _assess_sentiment() -> dict:
    """
    市场情绪评估
    维度：
    - 涨跌比（全市场）
    - 涨停/跌停数量（需要东方财富数据，这里用TDX近似）
    - 成交额变化
    - 连板高度
    """
    # 基于现有数据做粗略评估
    ind_sectors = _get_industry_sectors()

    up_count = sum(1 for s in ind_sectors if s.change_pct > 0)
    down_count = sum(1 for s in ind_sectors if s.change_pct < 0)
    total = len(ind_sectors) if ind_sectors else 1

    up_ratio = up_count / total if total > 0 else 0.5

    if up_ratio >= 0.7:
        mood = "亢奋 🟢"
        advice = "板块普涨，追高需警惕分歧"
        score = 80
    elif up_ratio >= 0.5:
        mood = "温和 🟡"
        advice = "正常轮动，按计划执行"
        score = 60
    elif up_ratio >= 0.3:
        mood = "偏弱 🟠"
        advice = "多数板块下跌，控制仓位"
        score = 40
    else:
        mood = "冰点 🔴"
        advice = "恐慌蔓延，观望为主，盯紧逆势板块"
        score = 20

    return {
        "up_ratio": up_ratio,
        "up_count": up_count,
        "down_count": down_count,
        "total": total,
        "mood": mood,
        "advice": advice,
        "score": score,
    }


def _analyze_sector_linkage(themes: list) -> dict:
    """
    板块联动分析：哪些板块之间关联性强
    - 通过概念重叠度判断
    """
    if len(themes) < 2:
        return {"pairs": [], "note": "板块数量不足，无法做联动分析"}

    # 取前10个主题，计算两两重叠
    top_themes = themes[:10]
    stocks = _get_all_stocks_with_sectors()

    # 为每个主题建股票集合
    theme_stocks = {}
    for t in top_themes:
        tset = set()
        for s in stocks:
            if t["type"] == "行业" and s["industry"] == t["name"]:
                tset.add(s["code"])
            elif t["type"] == "概念" and t["name"] in s["concepts"]:
                tset.add(s["code"])
        theme_stocks[t["name"]] = tset

    pairs = []
    names = list(theme_stocks.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            set_i = theme_stocks[names[i]]
            set_j = theme_stocks[names[j]]
            if not set_i or not set_j:
                continue
            overlap = len(set_i & set_j) / min(len(set_i), len(set_j)) if min(len(set_i), len(set_j)) > 0 else 0
            if overlap > 0.1:
                pairs.append({
                    "sector_a": names[i],
                    "sector_b": names[j],
                    "overlap": overlap,
                })

    pairs.sort(key=lambda p: p["overlap"], reverse=True)
    return {"pairs": pairs[:10], "note": ""}


# ============================================================
# 报告渲染
# ============================================================

def _render_review_report(results: dict):
    """渲染复盘报告"""
    st.divider()
    st.subheader("📋 深度复盘报告")

    # === 一、市场情绪 ===
    sentiment = results.get("sentiment", {})
    if sentiment:
        st.markdown("## 🎯 一、市场情绪")
        mood = sentiment.get("mood", "未知")
        advice = sentiment.get("advice", "")
        score = sentiment.get("score", 50)
        up_count = sentiment.get("up_count", 0)
        down_count = sentiment.get("down_count", 0)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("情绪状态", mood)
            st.metric("上涨板块", up_count)
        with col2:
            st.metric("情绪分", f"{score}/100")
            st.metric("下跌板块", down_count)

        st.info(f"💡 **建议**: {advice}")
        st.divider()

    # === 二、主线板块 ===
    themes = results.get("main_themes", [])
    if themes:
        st.markdown("## 🔥 二、主线板块 TOP15")

        rows = []
        for i, t in enumerate(themes[:15], 1):
            change_str = f"{t['change_pct']:+.2f}%" if t['change_pct'] else "——"
            inflow_str = f"{t['inflow']:.2f}亿" if t.get('inflow') else "——"
            type_icon = "🏭" if t["type"] == "行业" else "💡"
            stock_cnt = f"{t['stock_count']}只" if t['stock_count'] else "——"

            rows.append({
                "#": i,
                "板块": f"{type_icon} {t['name']}",
                "类型": t["type"],
                "等级": t["grade"],
                "强度分": f"{t['score']:.0f}",
                "涨跌": change_str,
                "资金": inflow_str,
                "成分股": stock_cnt,
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.divider()

    # === 三、龙头候选 ===
    dragon_heads = results.get("dragon_heads", {})
    if dragon_heads:
        st.markdown("## 👑 三、龙头候选")

        tabs = st.tabs(list(dragon_heads.keys())[:5])
        for idx, (theme_name, heads) in enumerate(dragon_heads.items()):
            if idx >= 5:
                break
            with tabs[idx]:
                if heads:
                    head_rows = []
                    for h in heads:
                        chg_icon = "🟢" if h["chg_today"] > 0 else "🔴"
                        head_rows.append({
                            "代码": h["code"],
                            "名称": h["name"],
                            "今日涨跌": f"{chg_icon} {h['chg_today']:+.2f}%",
                            "近5日": f"{h['chg_5d']:+.2f}%",
                            "量比": f"{h['vol_ratio']:.1f}",
                            "位置": h["position"],
                            "综合分": f"{h['composite']:.1f}",
                        })
                    st.dataframe(head_rows, use_container_width=True, hide_index=True)
                    st.caption("💡 综合分 = 今日涨幅×0.5 + 5日涨幅×0.3 + 放量溢价")
                else:
                    st.info("该板块未找到有效龙头候选")
        st.divider()

    # === 四、板块联动 ===
    linkage = results.get("sector_linkage", {})
    pairs = linkage.get("pairs", [])
    if pairs:
        st.markdown("## 🔗 四、板块联动（重叠度>10%）")
        st.caption("重叠度高说明两个板块的股票大量重合，可能联动涨跌")

        link_rows = []
        for p in pairs:
            link_rows.append({
                "板块A": p["sector_a"],
                "板块B": p["sector_b"],
                "重叠度": f"{p['overlap']:.0%}",
            })
        st.dataframe(link_rows, use_container_width=True, hide_index=True)
        st.divider()

    # === 五、明日操作建议 ===
    st.markdown("## 📝 五、明日操作思路")

    sentiment_score = sentiment.get("score", 50)
    if sentiment_score >= 70:
        st.success("**节奏**: 市场情绪偏暖，可按计划积极操作。关注主线龙头分歧转一致机会。")
    elif sentiment_score >= 50:
        st.warning("**节奏**: 中性市况。不追高，等待回调确认。控制在主线范围内。")
    else:
        st.error("**节奏**: 情绪偏冷。防守为主，减少开仓。守住已有的，不轻易加仓。")

    if themes:
        top3 = themes[:3]
        st.markdown("**主线方向**: " + " > ".join([f"{t['name']}({t['grade']})" for t in top3]))

    if dragon_heads:
        st.markdown("**候选池**: 上述龙头候选列表中综合分最高的3-5只，明天竞价确认强度后决定。")

    st.info("⚠️ 以上为数据驱动的复盘参考，最终决策请结合你的盘感和交易纪律。")

    # 导出按钮
    st.divider()
    st.download_button(
        "📥 导出复盘报告 (CSV)",
        data=_export_to_csv(themes, dragon_heads, sentiment),
        file_name=f"review_{_get_today_date()}.csv",
        mime="text/csv",
    )


def _export_to_csv(themes, dragon_heads, sentiment) -> str:
    """导出CSV"""
    lines = ["板块,类型,等级,强度分,涨跌幅"]
    for t in themes:
        lines.append(f'{t["name"]},{t["type"]},{t["grade"]},{t["score"]:.0f},{t["change_pct"]:+.2f}')
    lines.append("")
    lines.append("板块,代码,名称,今日涨跌,5日涨幅,量比,位置,综合分")
    for theme, heads in dragon_heads.items():
        for h in heads:
            lines.append(f'{theme},{h["code"]},{h["name"]},{h["chg_today"]:+.2f},{h["chg_5d"]:+.2f},{h["vol_ratio"]:.1f},{h["position"]},{h["composite"]:.1f}')
    lines.append("")
    lines.append(f'情绪,{sentiment.get("mood","")},{sentiment.get("score","")}分,{sentiment.get("advice","")}')
    return "\n".join(lines)


# ============================================================
# 独立运行
# ============================================================

if __name__ == "__main__":
    render()
