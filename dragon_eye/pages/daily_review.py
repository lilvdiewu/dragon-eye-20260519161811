"""
盘后深度复盘 v2 — 数据驱动，拒绝笼统

核心理念：每一个结论都有具体数字支撑。
"""
import streamlit as st
import json
import os
from datetime import datetime


# ============================================================
# 缓存层
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _get_today_date():
    return datetime.now().strftime("%Y-%m-%d")


@st.cache_data(ttl=600, show_spinner=False)
def _get_stat_reader():
    """TDX行情统计读取器（7866只股票，35字段）"""
    from dragon_eye.analysis.tdx_stat_reader import get_stat_reader
    return get_stat_reader()


@st.cache_data(ttl=600, show_spinner=False)
def _get_sector_mapper():
    """行业/概念映射"""
    from dragon_eye.sector.ths_sector import TdxSectorMapper
    m = TdxSectorMapper()
    m.load_all()
    return m


@st.cache_data(ttl=3600, show_spinner=False)
def _get_stock_names():
    """股票代码→名称（从缓存JSON）"""
    names_path = os.path.join(os.path.dirname(__file__), "..", "_cache", "stock_names.json")
    if os.path.exists(names_path):
        with open(names_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


@st.cache_data(ttl=600, show_spinner=False)
def _get_industry_sectors():
    from dragon_eye.pages.sector_heat import _cached_industry_sectors
    return _cached_industry_sectors()


@st.cache_data(ttl=600, show_spinner=False)
def _get_concept_sectors():
    from dragon_eye.pages.sector_heat import _cached_concept_sectors_tdx
    return _cached_concept_sectors_tdx()


# ============================================================
# 渲染入口
# ============================================================

def render():
    st.header("📋 盘后深度复盘")

    date = _get_today_date()
    st.caption(f"📅 {date} · 数据源: TDX本地 (tdxstat.cfg + tdxstat2.cfg)")

    # 自动检测：如果市场已收盘（>15:00），默认开启
    auto_run = datetime.now().hour >= 15

    if auto_run:
        st.info("🕒 已过收盘时间，点击下方按钮开始复盘")
    
    if st.button("🔍 开始盘后复盘", type="primary", use_container_width=True):
        with st.spinner("正在深度复盘..."):
            results = _run_deep_review()
        _render_review_report(results)
    elif not auto_run:
        st.caption("💡 建议收盘后(15:00)运行，数据最完整")


# ============================================================
# 复盘核心逻辑
# ============================================================

def _run_deep_review() -> dict:
    results = {}

    # 1. 主线确认（含板块内个股统计）
    results["main_themes"] = _analyze_main_themes()

    # 2. 龙头识别（含具体数据）
    results["dragon_heads"] = _identify_dragon_heads(results["main_themes"])

    # 3. 市场全景
    results["market_overview"] = _assess_market_overview()

    # 4. 资金流向
    results["fund_flow"] = _analyze_fund_flow()

    # 5. 涨停板深度分析
    results["limit_up_analysis"] = _analyze_limit_up()

    # 6. 板块联动
    results["sector_linkage"] = _analyze_sector_linkage(results["main_themes"])

    return results


def _analyze_main_themes() -> list:
    """
    主线确认：行业 + 概念，含板块内涨跌比
    """
    ind_sectors = _get_industry_sectors()
    con_sectors = _get_concept_sectors()
    stats = _get_stat_reader()
    mapper = _get_sector_mapper()
    names = _get_stock_names()

    themes = []

    # 行业板块
    if ind_sectors:
        top_ind = sorted(ind_sectors, key=lambda s: s.strength_score, reverse=True)[:8]
        for s in top_ind:
            # 统计板块内个股表现
            sector_stocks = _get_stocks_in_sector(s.name, "industry", mapper)
            sector_change = _calc_sector_change(sector_stocks, stats)

            themes.append({
                "name": s.name,
                "type": "行业",
                "grade": s.grade,
                "score": s.strength_score,
                "change_pct": s.change_pct,
                "breadth": sector_change.get("breadth", 0),    # 涨跌比
                "up_count": sector_change.get("up_count", 0),
                "down_count": sector_change.get("down_count", 0),
                "leader_name": sector_change.get("leader_name", ""),
                "leader_code": sector_change.get("leader_code", ""),
                "leader_chg": sector_change.get("leader_chg", 0),
            })

    # 概念板块
    if con_sectors:
        top_con = sorted(con_sectors, key=lambda s: s.strength_score, reverse=True)[:10]
        for s in top_con:
            stock_cnt = getattr(s, 'stock_count', 0) or 0
            sector_stocks = _get_stocks_in_sector(s.name, "concept", mapper)
            sector_change = _calc_sector_change(sector_stocks, stats)

            themes.append({
                "name": s.name,
                "type": "概念",
                "grade": s.grade,
                "score": s.strength_score,
                "change_pct": s.change_pct or 0,
                "breadth": sector_change.get("breadth", 0),
                "up_count": sector_change.get("up_count", 0),
                "down_count": sector_change.get("down_count", 0),
                "leader_name": sector_change.get("leader_name", ""),
                "leader_code": sector_change.get("leader_code", ""),
                "leader_chg": sector_change.get("leader_chg", 0),
                "stock_count": stock_cnt,
            })

    themes.sort(key=lambda t: t["score"], reverse=True)
    return themes


def _get_stocks_in_sector(sector_name: str, sector_type: str, mapper) -> set:
    """获取板块内股票代码集合"""
    codes = set()
    if sector_type == "concept":
        stocks = mapper._concept_map.get(sector_name, [])
        codes = set(stocks)
    else:
        # 行业：通过 AKShare 获取 THS 行业成分股（与 sector_heat 口径一致）
        codes = _get_ths_industry_stocks(sector_name)
    return codes


@st.cache_data(ttl=3600, show_spinner=False)
def _get_ths_industry_stocks(sector_name: str) -> set:
    """获取同花顺行业成分股（缓存1小时）"""
    try:
        import akshare as ak
        for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "eastmoney.com,push2.eastmoney.com,localhost,127.0.0.1"
        df = ak.stock_board_industry_cons_em(symbol=sector_name)
        if df is not None and not df.empty:
            codes = set()
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                if len(code) == 6 and code.isdigit():
                    codes.add(code)
            return codes
    except Exception:
        pass
    return set()


def _calc_sector_change(codes: set, stats) -> dict:
    """计算板块内涨跌统计"""
    if not codes:
        return {"breadth": 0, "up_count": 0, "down_count": 0}

    up, down, total = 0, 0, 0
    best_code, best_chg = "", -999
    best_name = ""
    names = _get_stock_names()

    for code in codes:
        stat = stats.get_stat(code)
        if stat is None:
            continue
        total += 1
        if stat.change_pct > 0:
            up += 1
        elif stat.change_pct < 0:
            down += 1

        if stat.change_pct > best_chg:
            best_chg = stat.change_pct
            best_code = code
            best_name = names.get(code, code)

    breadth = up / max(total, 1)
    return {
        "breadth": breadth,
        "up_count": up,
        "down_count": down,
        "total": total,
        "leader_code": best_code,
        "leader_name": best_name,
        "leader_chg": best_chg,
    }


def _identify_dragon_heads(themes: list) -> dict:
    """
    龙头识别：每个主线里找最强个股，含详细数据
    """
    if not themes:
        return {}

    stats = _get_stat_reader()
    mapper = _get_sector_mapper()
    names = _get_stock_names()
    heads = {}

    for theme in themes[:6]:
        theme_name = theme["name"]
        codes = _get_stocks_in_sector(theme_name, theme["type"], mapper)
        if not codes:
            continue

        stock_data = []
        for code in codes:
            stat = stats.get_stat(code)
            stat2 = stats.get_stat2(code)
            if stat is None:
                continue

            name = names.get(code, code)
            net_flow = stat2.flow_net if stat2 else 0

            # 综合评分：涨幅 + 换手(活性) + 资金 + 市值(适中为好)
            mv_score = 0
            if stat.total_mv > 0:
                mv_yi = stat.total_mv / 10000  # 万元→亿
                mv_score = 0 if mv_yi < 20 else (10 if mv_yi < 500 else 5)  # 20-500亿最优

            composite = (
                stat.change_pct * 0.35 +
                min(stat.turnover, 15) * 0.15 +  # 换手率15%封顶
                (1 if net_flow > 0 else -1) * min(abs(net_flow) / 100000, 10) * 0.2 +
                mv_score * 0.1 +
                stat.chg_20d * 0.1 +
                stat.chg_60d * 0.1
            )

            stock_data.append({
                "code": code,
                "name": name,
                "chg_today": stat.change_pct,
                "chg_5d": stat.chg_20d / 4 if stat.chg_20d else 0,  # 近似
                "chg_20d": stat.chg_20d,
                "turnover": stat.turnover,
                "pe": stat.pe,
                "mv_yi": stat.total_mv / 10000 if stat.total_mv > 0 else 0,
                "net_flow_yi": net_flow / 10000 if net_flow else 0,
                "composite": composite,
            })

        if stock_data:
            stock_data.sort(key=lambda x: x["composite"], reverse=True)
            heads[theme_name] = stock_data[:6]

    return heads


def _assess_market_overview() -> dict:
    """
    市场全景：涨跌分布、涨停板统计、成交额
    """
    stats = _get_stat_reader()

    up_count, down_count, flat_count = 0, 0, 0
    limit_up, limit_down = 0, 0
    total_amount = 0.0
    valid = 0

    for code, stat in stats._stats.items():
        if abs(stat.change_pct) < 0.01:
            flat_count += 1
        elif stat.change_pct > 0:
            up_count += 1
            if stat.change_pct >= 9.8:
                limit_up += 1
        else:
            down_count += 1
            if stat.change_pct <= -9.8:
                limit_down += 1

        # 成交额估算: amount_est = 流通市值 × |换手率| / 100 (单位:万元)
        # field[22] 不是成交额，用 amount_est 替代
        total_amount += stat.amount_est
        valid += 1

    total = up_count + down_count + flat_count
    up_ratio = up_count / max(total, 1)

    # 情绪判断
    if limit_up >= 100 and up_ratio >= 0.7:
        mood = "🔥 亢奋"
        advice = "涨停潮+普涨，注意高潮次日分歧。追高谨慎，关注前排龙头分歧转一致。"
    elif limit_up >= 50 and up_ratio >= 0.55:
        mood = "🟢 偏暖"
        advice = "赚钱效应好，主线明确，可按计划积极操作。"
    elif up_ratio >= 0.45:
        mood = "🟡 中性"
        advice = "涨跌参半，轮动较快。只做最强，杂毛不碰。"
    elif limit_down >= 30:
        mood = "🔴 偏冷"
        advice = "跌停增加，亏钱效应扩散。防守为主，减仓观望。"
    else:
        mood = "🧊 冰点"
        advice = "恐慌释放中。可小仓位试错逆势抗跌品种，等情绪修复。"

    return {
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "up_ratio": up_ratio,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "total_amount": total_amount,
        "total_stocks": valid,
        "mood": mood,
        "advice": advice,
    }


def _analyze_limit_up() -> dict:
    """
    涨停板深度分析：
    - 涨停股行业/概念分布
    - 换手率特征（缩量板 vs 放量板）
    - PE/市值特征
    """
    stats = _get_stat_reader()
    mapper = _get_sector_mapper()
    names = _get_stock_names()

    limit_up_stocks = []
    for code, stat in stats._stats.items():
        if stat.change_pct >= 9.8:
            name = names.get(code, code)
            industry = mapper.get_industry(code)
            limit_up_stocks.append({
                "code": code,
                "name": name,
                "chg": stat.change_pct,
                "turnover": stat.turnover,
                "volume_ratio": stat.volume_ratio,
                "pe": stat.pe,
                "mv_yi": stat.total_mv / 10000 if stat.total_mv > 0 else 0,
                "industry": industry or "未分类",
            })

    if not limit_up_stocks:
        return {"total": 0, "by_industry": {}, "features": {}}

    # 行业分布
    industry_dist: dict[str, int] = {}
    for s in limit_up_stocks:
        ind = s["industry"]
        industry_dist[ind] = industry_dist.get(ind, 0) + 1
    top_industries = sorted(industry_dist.items(), key=lambda x: x[1], reverse=True)[:8]

    # 换手率特征
    turnovers = [s["turnover"] for s in limit_up_stocks if s["turnover"] > 0]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
    low_turn = sum(1 for t in turnovers if t < 3)  # 缩量板(<3%)
    mid_turn = sum(1 for t in turnovers if 3 <= t < 10)  # 适中
    high_turn = sum(1 for t in turnovers if t >= 10)  # 放量板(>=10%)

    # PE分布
    pes = [s["pe"] for s in limit_up_stocks if 0 < s["pe"] < 1000]
    avg_pe = sum(pes) / len(pes) if pes else 0

    # 市值分布
    mvs = [s["mv_yi"] for s in limit_up_stocks if s["mv_yi"] > 0]
    small_cap = sum(1 for m in mvs if m < 50)   # <50亿
    mid_cap = sum(1 for m in mvs if 50 <= m < 200)
    large_cap = sum(1 for m in mvs if m >= 200)

    return {
        "total": len(limit_up_stocks),
        "stocks": limit_up_stocks,
        "by_industry": top_industries,
        "features": {
            "avg_turnover": avg_turnover,
            "low_turn_count": low_turn,
            "mid_turn_count": mid_turn,
            "high_turn_count": high_turn,
            "avg_pe": avg_pe,
            "small_cap_count": small_cap,
            "mid_cap_count": mid_cap,
            "large_cap_count": large_cap,
        },
    }


def _analyze_fund_flow() -> dict:
    """
    资金流向：主力净流入TOP + 行业分布
    """
    stats = _get_stat_reader()
    mapper = _get_sector_mapper()
    names = _get_stock_names()

    # 主力净流入TOP30
    top_flows = stats.get_top_by_net_flow(30)

    flow_list = []
    sector_flow: dict[str, float] = {}

    for s in top_flows:
        name = names.get(s.code, s.code)
        industry = mapper.get_industry(s.code)
        if industry:
            sector_flow[industry] = sector_flow.get(industry, 0) + s.flow_net

        flow_list.append({
            "code": s.code,
            "name": name,
            "net_flow_yi": s.flow_net / 10000,  # 亿元
            "flow_pct": s.flow_pct,
        })

    # 行业资金流入排名
    sector_flow_rank = sorted(sector_flow.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "top_stocks": flow_list,
        "sector_flow_rank": [{"sector": k, "flow_yi": v / 10000} for k, v in sector_flow_rank],
    }


def _analyze_sector_linkage(themes: list) -> dict:
    """板块联动"""
    if len(themes) < 2:
        return {"pairs": []}

    mapper = _get_sector_mapper()

    theme_stocks = {}
    for t in themes[:10]:
        tset = _get_stocks_in_sector(t["name"], t["type"], mapper)
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
            if overlap > 0.05:
                pairs.append({
                    "sector_a": names[i],
                    "sector_b": names[j],
                    "overlap": overlap,
                })

    pairs.sort(key=lambda p: p["overlap"], reverse=True)
    return {"pairs": pairs[:15]}


# ============================================================
# 报告渲染
# ============================================================

def _render_review_report(results: dict):
    st.divider()
    st.subheader("📋 深度复盘报告")

    # === 一、市场全景 ===
    overview = results.get("market_overview", {})
    if overview:
        st.markdown("## 📊 一、市场全景")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("上涨家数", f"{overview.get('up_count', 0):,}")
        with col2:
            st.metric("下跌家数", f"{overview.get('down_count', 0):,}")
        with col3:
            st.metric("涨停", f"{overview.get('limit_up', 0)} 只")
        with col4:
            st.metric("跌停", f"{overview.get('limit_down', 0)} 只")

        col5, col6 = st.columns(2)
        with col5:
            st.metric("涨跌比", f"{overview.get('up_ratio', 0):.0%}")
        with col6:
            total_yi = overview.get('total_amount', 0) / 10000  # 万元→亿
            st.metric("成交额(估)", f"{total_yi:.0f}亿")

        mood = overview.get("mood", "")
        st.info(f"**市场情绪**: {mood}")
        st.success(f"**建议**: {overview.get('advice', '')}")
        st.divider()

    # === 二、主线板块（含个股涨幅统计）===
    themes = results.get("main_themes", [])
    if themes:
        st.markdown("## 🔥 二、主线板块")

        rows = []
        for i, t in enumerate(themes[:15], 1):
            type_icon = "🏭" if t["type"] == "行业" else "💡"
            breadth_bar = _breadth_bar(t.get("breadth", 0))

            leader = ""
            if t.get("leader_code"):
                leader_name = t.get("leader_name", "") or t["leader_code"]
                chg_str = f"{t['leader_chg']:+.2f}%"
                chg_icon = "🔴" if t['leader_chg'] > 0 else "🟢"
                leader = f"{chg_icon} {leader_name}({t['leader_code']}) {chg_str}"

            rows.append({
                "#": i,
                "板块": f"{type_icon} {t['name']}",
                "强度": f"{t['score']:.0f} ({t['grade']})",
                "涨跌比": f"{t.get('up_count',0)}↑/{t.get('down_count',0)}↓ {breadth_bar}",
                "领涨龙头": leader,
            })

        st.dataframe(rows, use_container_width=True, hide_index=True, height=600)
        st.divider()

    # === 三、龙头深度分析 ===
    dragon_heads = results.get("dragon_heads", {})
    if dragon_heads:
        st.markdown("## 👑 三、主线龙头深度分析")

        tabs = st.tabs(list(dragon_heads.keys())[:5])
        for idx, (theme_name, heads) in enumerate(dragon_heads.items()):
            if idx >= 5:
                break
            with tabs[idx]:
                if heads:
                    head_rows = []
                    for h in heads:
                        chg_icon = "🔴" if h["chg_today"] > 0 else "🟢"
                        mv_str = f"{h['mv_yi']:.0f}亿" if h['mv_yi'] > 0 else "——"
                        turn_str = f"{h['turnover']:.1f}%" if h['turnover'] > 0 else "——"
                        flow_str = f"{h['net_flow_yi']:+.1f}亿" if h['net_flow_yi'] != 0 else "——"

                        head_rows.append({
                            "代码": h["code"],
                            "名称": h["name"],
                            "今日": f"{chg_icon} {h['chg_today']:+.2f}%",
                            "20日": f"{h['chg_20d']:+.1f}%",
                            "换手": turn_str,
                            "PE": f"{h['pe']:.1f}" if h['pe'] > 0 else "亏损",
                            "市值": mv_str,
                            "主力净额": flow_str,
                            "综合分": f"{h['composite']:.1f}",
                        })
                    st.dataframe(head_rows, use_container_width=True, hide_index=True)

                    # 提示
                    top_stock = heads[0]
                    st.caption(
                        f"💡 **{top_stock['name']}** 综合最强：今日{top_stock['chg_today']:+.2f}%，"
                        f"20日{top_stock['chg_20d']:+.1f}%，市值约{top_stock['mv_yi']:.0f}亿。"
                        f"\"{'适合短线关注' if abs(top_stock['chg_today']) < 9.5 else '已涨停，明天看分歧'}\"。"
                    )
                else:
                    st.info("未找到有效龙头")
        st.divider()

    # === 四、资金流向 ===
    fund_flow = results.get("fund_flow", {})
    if fund_flow:
        st.markdown("## 💰 四、主力资金动向")

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("个股净流入 TOP15")
            top_stocks = fund_flow.get("top_stocks", [])[:15]
            if top_stocks:
                flow_rows = []
                for s in top_stocks:
                    flow_rows.append({
                        "名称": f"{s['name']}({s['code']})",
                        "净流入(亿)": f"{s['net_flow_yi']:+.1f}",
                        "占比": f"{s['flow_pct']:.1f}%",
                    })
                st.dataframe(flow_rows, use_container_width=True, hide_index=True)

        with col_right:
            st.subheader("行业资金流入 TOP10")
            sector_flows = fund_flow.get("sector_flow_rank", [])[:10]
            if sector_flows:
                import plotly.graph_objects as go
                fig = go.Figure(data=[
                    go.Bar(
                        x=[sf["flow_yi"] for sf in sector_flows],
                        y=[sf["sector"] for sf in sector_flows],
                        orientation="h",
                        marker_color=["#ff4b4b" if sf["flow_yi"] > 0 else "#4baf4f" for sf in sector_flows],
                    )
                ])
                fig.update_layout(height=350, margin=dict(l=20, r=20, t=10, b=20))
                st.plotly_chart(fig, use_container_width=True)

        st.divider()

    # === 四-半、涨停板深度分析 ===
    lu = results.get("limit_up_analysis", {})
    if lu and lu.get("total", 0) > 0:
        st.markdown("## 🔥 涨停板深度分析")
        
        total_lu = lu["total"]
        feats = lu.get("features", {})
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("涨停总数", f"{total_lu} 只")
            st.metric("均换手率", f"{feats.get('avg_turnover', 0):.1f}%")
        with c2:
            st.metric("缩量板(<3%)", f"{feats.get('low_turn_count', 0)} 只")
            st.metric("放量板(>=10%)", f"{feats.get('high_turn_count', 0)} 只")
        with c3:
            st.metric("均PE", f"{feats.get('avg_pe', 0):.0f}")
            small = feats.get('small_cap_count', 0)
            large = feats.get('large_cap_count', 0)
            st.metric("小盘(<50亿)/大盘(>=200亿)", f"{small}/{large}")
        
        # 行业分布
        by_ind = lu.get("by_industry", [])
        if by_ind:
            st.caption("**涨停行业集中度**（涨停数TOP8）：")
            ind_text = " | ".join([f"{ind}({cnt}只)" for ind, cnt in by_ind])
            st.caption(ind_text)
            
            # 集中度判断
            total_ind = sum(cnt for _, cnt in by_ind)
            top3_cnt = sum(cnt for _, cnt in by_ind[:3])
            if top3_cnt / max(total_lu, 1) > 0.6:
                st.success(f"🎯 涨停高度集中：前3行业占{top3_cnt}/{total_lu}（{top3_cnt/total_lu*100:.0f}%），主线明确")
            else:
                st.info(f"📊 涨停分散：前3行业仅占{top3_cnt}/{total_lu}（{top3_cnt/total_lu*100:.0f}%），轮动快")

        st.divider()

    # === 五、板块联动 ===
    linkage = results.get("sector_linkage", {})
    pairs = linkage.get("pairs", [])
    if pairs:
        st.markdown("## 🔗 五、板块联动")
        linked = [p for p in pairs if p["overlap"] >= 0.15]
        if linked:
            for p in linked[:8]:
                st.caption(f"⚡ **{p['sector_a']}** ↔ **{p['sector_b']}** — 重叠度 {p['overlap']:.0%}，联动概率高")
        else:
            st.caption("板块间联动关系较弱，各自独立走势为主")
        st.divider()

    # === 六、明日操作思路 ===
    _render_strategy_section(results)

    # 导出
    st.divider()
    csv_data = _export_to_csv(themes, dragon_heads, overview, fund_flow)
    st.download_button(
        "📥 导出复盘报告 (CSV)",
        data=csv_data,
        file_name=f"review_{_get_today_date()}.csv",
        mime="text/csv",
    )


# ============================================================
# 策略渲染（数据驱动，拒绝笼统）
# ============================================================

def _render_strategy_section(results: dict):
    """生成具体的明日操作策略，每个结论都有数字支撑"""
    st.markdown("## 📝 六、明日操作思路")
    overview = results.get("market_overview", {})
    themes = results.get("main_themes", [])
    dragon_heads = results.get("dragon_heads", {})
    fund_flow = results.get("fund_flow", {})

    limit_up = overview.get("limit_up", 0)
    limit_down = overview.get("limit_down", 0)
    up_ratio = overview.get("up_ratio", 0)
    total_yi = overview.get("total_amount", 0) / 10000

    # 1. 节奏判断
    st.markdown("### 🎯 节奏判断")
    rhythm = f"涨停**{limit_up}**只 / 跌停**{limit_down}**只 / 涨跌比 **{up_ratio:.0%}** / 成交约 **{total_yi:.0f}亿**"

    if limit_up >= 100 and up_ratio >= 0.6:
        st.warning(f"🔥 **高潮期** | {rhythm}")
        st.markdown("- ⚠️ 次日分歧概率高（历史上高潮次日成功率仅~40%）\n- 🚫 不追缩量一字板\n- ✅ 标的：今日放量封板+换手>5%+尾盘未炸板\n- 📊 买点：竞价高开<3%试仓，>5%等回踩")
    elif limit_up >= 50 and up_ratio >= 0.5:
        st.success(f"🟢 **做多窗口** | {rhythm}")
        st.markdown("- ✅ 仓位：5-7成\n- 📊 买点：龙头开0-3%介入，止损=今日最低-0.5%")
    elif up_ratio >= 0.4:
        st.info(f"🟡 **轮动格局** | {rhythm}")
        st.markdown("- 📌 仓位：3-5成，只做最强1-2板块\n- ⚡ 策略：买龙头不买杂毛，不追轮动")
    elif limit_down >= 30:
        st.error(f"🔴 **亏钱效应** | {rhythm}")
        st.markdown("- 🛑 仓位≤2成或空仓\n- 👀 关注逆势抗跌票（20日线上+缩量）")
    else:
        st.error(f"🧊 **冰点** | {rhythm}")
        st.markdown("- 🌡️ 仓位：1成试错或空仓\n- 🔍 止损-3%无条件走")

    # 2. 主线方向
    st.markdown("### 🧭 明日主线方向")
    top3 = themes[:3] if themes else []
    for i, t in enumerate(top3):
        b = "🟢" if t.get("breadth", 0) >= 0.6 else ("🟡" if t.get("breadth", 0) >= 0.4 else "🔴")
        st.markdown(f"{i+1}. **{t['name']}** {b} {t.get('up_count',0)}↑/{t.get('down_count',0)}↓ (强度{t['score']:.0f}) · 龙头:{t.get('leader_name','?')} {t.get('leader_chg',0):+.2f}%")
    if len(top3) >= 2:
        gap = top3[0]["score"] - top3[1]["score"]
        st.caption(f"💪 {top3[0]['name']}领先{gap:.0f}分" if gap > 20 else f"⚖️ 差距仅{gap:.0f}分，明天可能轮动")

    # 3. 候选池
    st.markdown("### 🎫 明日候选池")
    candidates = []
    theme_order = {t["name"]: i for i, t in enumerate(themes) if t} if themes else {}
    for theme_name, heads in dragon_heads.items():
        rank = theme_order.get(theme_name, 99)
        for h in heads:
            if h["composite"] > 0:
                chg = h["chg_today"]
                if chg >= 9.5: action = "涨停→竞价看强度"
                elif chg >= 5: action = "强势→开0-2%可入"
                elif chg >= 0: action = "温和→开0-1%可入"
                else: action = "抗跌→翻红确认再入"
                candidates.append({"code": h["code"], "name": h["name"], "theme": theme_name[:8],
                                   "chg": f"{chg:+.1f}%", "score": f"{h['composite']:.1f}",
                                   "turn": f"{h.get('turnover',0):.1f}%", "action": action,
                                   "rank": rank, "is_limit": chg >= 9.5})
    candidates.sort(key=lambda c: (c["is_limit"], -float(c["score"]), c["rank"]))
    
    if candidates:
        st.dataframe([{k: v for k, v in c.items() if k not in ("rank", "is_limit")} 
                       for c in candidates[:10]], use_container_width=True, hide_index=True, height=380)
        st.info("📋 **盘前检查**: 1.竞价低开>-3%的删 2.前10分钟不动手 3.单票≤15%仓位 4.龙头高开>5%不追 5.大盘开跌>1%不新开仓")
    else:
        st.caption("暂无明显候选")

    # 4. 资金验证
    sector_flows = fund_flow.get("sector_flow_rank", [])
    if sector_flows:
        theme_names = [t["name"] for t in themes[:8]] if themes else []
        matched = [sf for sf in sector_flows if sf["sector"] in theme_names]
        st.markdown("### 💰 资金验证")
        if matched:
            st.success(f"✅ 主力与主线一致：{'、'.join(f['sector'] for f in matched[:3])}")
        else:
            st.warning(f"⚠️ 主力净流入第一【{sector_flows[0]['sector']}】({sector_flows[0]['flow_yi']:+.1f}亿)不在前8主线，注意切换")

    # 5. 风险
    st.markdown("### ⚠️ 风险因子")
    risks = []
    if limit_up >= 150: risks.append(f"涨停{limit_up}只→高潮极致，明天大概率分化")
    if limit_down >= 20: risks.append(f"跌停{limit_down}只→亏钱效应扩散")
    if up_ratio < 0.35: risks.append(f"涨跌比仅{up_ratio:.0%}→信心不足")
    if total_yi < 8000: risks.append(f"成交仅{total_yi:.0f}亿→流动性不足")
    st.markdown("\n".join(f"• {r}" for r in risks) if risks else "• 未检测到明显风险")


# ============================================================
# 辅助
# ============================================================

def _breadth_bar(ratio: float) -> str:
    """涨跌比可视化"""
    n = int(ratio * 10)
    return "🟢" * n + "⚪" * (10 - n)


def _export_to_csv(themes, dragon_heads, overview, fund_flow) -> str:
    lines = ["=== 市场全景 ==="]
    lines.append(f"上涨,{overview.get('up_count',0)}")
    lines.append(f"下跌,{overview.get('down_count',0)}")
    lines.append(f"涨停,{overview.get('limit_up',0)}")
    lines.append(f"跌停,{overview.get('limit_down',0)}")
    lines.append(f"情绪,{overview.get('mood','')}")
    lines.append("")
    lines.append("=== 主线板块 ===")
    lines.append("板块,类型,强度,领涨龙头,涨幅")
    for t in themes[:15]:
        leader = f"{t.get('leader_name','')}({t.get('leader_code','')})"
        lines.append(f"{t['name']},{t['type']},{t['score']:.0f},{leader},{t.get('leader_chg',0):+.2f}%")
    lines.append("")
    lines.append("=== 龙头个股 ===")
    lines.append("板块,代码,名称,今日涨幅,20日涨幅,换手率,PE,市值(亿),主力净额(亿),综合分")
    for theme, heads in dragon_heads.items():
        for h in heads:
            lines.append(f"{theme},{h['code']},{h['name']},{h['chg_today']:+.2f},{h['chg_20d']:+.1f},{h['turnover']:.1f},{h['pe']:.1f},{h['mv_yi']:.0f},{h['net_flow_yi']:+.1f},{h['composite']:.1f}")
    lines.append("")
    lines.append("=== 资金净流入TOP ===")
    for s in fund_flow.get("top_stocks", [])[:15]:
        lines.append(f"{s['name']}({s['code']}),{s['net_flow_yi']:+.1f}亿,{s['flow_pct']:.1f}%")
    return "\n".join(lines)


if __name__ == "__main__":
    render()
