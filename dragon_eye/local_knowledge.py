"""
dragon_eye.local_knowledge — 龙瞳Pro 伴随式本地资料库

核心设计: 用过就存，存了能查能比
- 被动存档: 不主动爬数据，只在分析过程中自动存
- 零侵入: vendor 函数末尾加一行 archive() 调用
- 可对比: 同一股票/板块跨时间对比
- 可查询: "我分析过哪些股票?" "XX上次分析是什么时候?"

用法:
    from dragon_eye.local_knowledge import get_lk
    lk = get_lk()

    # 存档
    lk.archive_stock_snapshot("603618", "10agent", price=38.5, pe_ttm=25.3, ...)
    lk.archive_fund_flow("603618", [{"trade_date": "2026-05-13", ...}, ...])
    lk.archive_news("eastmoney", [{"title": "...", "content": "..."}, ...])

    # 查询
    history = lk.get_stock_history("603618", limit=5)
    compare = lk.compare_stock("603618", days_back=1)
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional


# ============================================================
# 路径配置
# ============================================================

_DATA_DIR = os.path.join(os.path.dirname(__file__), "_data")
_DB_PATH = os.path.join(_DATA_DIR, "local_knowledge.db")

# 通过环境变量可覆盖
DB_PATH = os.environ.get("DRAGON_EYE_DB", _DB_PATH)


# ============================================================
# 建表 SQL
# ============================================================

_CREATE_TABLES = """
-- 个股分析快照
CREATE TABLE IF NOT EXISTS stock_snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code6       TEXT NOT NULL,
    name        TEXT,
    trade_date  TEXT NOT NULL,
    source      TEXT NOT NULL,
    price       REAL,
    change_pct  REAL,
    pe_ttm      REAL,
    pb          REAL,
    total_mv    REAL,
    turnover    REAL,
    main_net    REAL,
    main_pct    REAL,
    super_net   REAL,
    large_net   REAL,
    tech_score  REAL,
    ma_status   TEXT,
    ta_rating   TEXT,
    ta_target   REAL,
    ta_horizon  TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code6, trade_date, source)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_code ON stock_snapshot(code6);
CREATE INDEX IF NOT EXISTS idx_snapshot_date ON stock_snapshot(trade_date);

-- 板块概念快照
CREATE TABLE IF NOT EXISTS sector_snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_type TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    source      TEXT NOT NULL,
    change_pct  REAL,
    lead_stock  TEXT,
    lead_change REAL,
    fund_flow   REAL,
    stock_count INTEGER,
    up_count    INTEGER,
    down_count  INTEGER,
    top_stocks  TEXT,
    analysis    TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sector_code, sector_type, trade_date, source)
);
CREATE INDEX IF NOT EXISTS idx_sector_date ON sector_snapshot(trade_date);
CREATE INDEX IF NOT EXISTS idx_sector_type ON sector_snapshot(sector_type);

-- 资金流向明细
CREATE TABLE IF NOT EXISTS fund_flow (
    code6       TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    close       REAL,
    change_pct  REAL,
    main_net    REAL,
    main_pct    REAL,
    super_net   REAL,
    large_net   REAL,
    medium_net  REAL,
    small_net   REAL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code6, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_flow_date ON fund_flow(trade_date);

-- 新闻存档
CREATE TABLE IF NOT EXISTS news_archive (
    source      TEXT NOT NULL,
    news_date   TEXT NOT NULL,
    title       TEXT,
    content     TEXT,
    url         TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, news_date, title)
);
CREATE INDEX IF NOT EXISTS idx_news_date ON news_archive(news_date);

-- 分析报告存档
CREATE TABLE IF NOT EXISTS analysis_report (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code6        TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    source       TEXT NOT NULL,
    report_json  TEXT NOT NULL,
    rating       TEXT,
    target_price REAL,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code6, trade_date, source)
);
CREATE INDEX IF NOT EXISTS idx_report_code ON analysis_report(code6);
"""


# ============================================================
# LocalKnowledge 核心
# ============================================================

class LocalKnowledge:
    """龙瞳Pro 伴随式本地资料库"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（懒加载）"""
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, timeout=10)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._ensure_tables()
        return self._conn

    def _ensure_tables(self):
        """建表（首次运行）"""
        self._conn.executescript(_CREATE_TABLES)
        self._conn.commit()

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ================================================================
    # 存档接口
    # ================================================================

    def archive_stock_snapshot(self, code6: str, source: str, **kwargs):
        """存档个股分析快照

        Args:
            code6: 6位代码
            source: 来源 '10agent'/'quick_analysis'/'manual'
            **kwargs: name, price, change_pct, pe_ttm, pb, total_mv, turnover,
                      main_net, main_pct, super_net, large_net,
                      tech_score, ma_status, ta_rating, ta_target, ta_horizon
        """
        conn = self._get_conn()
        today = datetime.now().strftime("%Y-%m-%d")

        conn.execute("""
            INSERT OR REPLACE INTO stock_snapshot
            (code6, name, trade_date, source, price, change_pct,
             pe_ttm, pb, total_mv, turnover,
             main_net, main_pct, super_net, large_net,
             tech_score, ma_status, ta_rating, ta_target, ta_horizon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code6,
            kwargs.get("name"),
            today,
            source,
            kwargs.get("price"),
            kwargs.get("change_pct"),
            kwargs.get("pe_ttm"),
            kwargs.get("pb"),
            kwargs.get("total_mv"),
            kwargs.get("turnover"),
            kwargs.get("main_net"),
            kwargs.get("main_pct"),
            kwargs.get("super_net"),
            kwargs.get("large_net"),
            kwargs.get("tech_score"),
            kwargs.get("ma_status"),
            kwargs.get("ta_rating"),
            kwargs.get("ta_target"),
            kwargs.get("ta_horizon"),
        ))
        conn.commit()

    def archive_sector_snapshot(self, sector_code: str, sector_name: str,
                                sector_type: str, source: str, **kwargs):
        """存档板块快照

        Args:
            sector_code: 板块代码
            sector_name: 板块名称
            sector_type: 'industry'/'concept'
            source: 来源
            **kwargs: change_pct, lead_stock, lead_change, fund_flow,
                      stock_count, up_count, down_count, top_stocks, analysis
        """
        conn = self._get_conn()
        today = datetime.now().strftime("%Y-%m-%d")

        conn.execute("""
            INSERT OR REPLACE INTO sector_snapshot
            (sector_code, sector_name, sector_type, trade_date, source,
             change_pct, lead_stock, lead_change, fund_flow,
             stock_count, up_count, down_count, top_stocks, analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sector_code, sector_name, sector_type, today, source,
            kwargs.get("change_pct"),
            kwargs.get("lead_stock"),
            kwargs.get("lead_change"),
            kwargs.get("fund_flow"),
            kwargs.get("stock_count"),
            kwargs.get("up_count"),
            kwargs.get("down_count"),
            json.dumps(kwargs.get("top_stocks", []), ensure_ascii=False) if kwargs.get("top_stocks") else None,
            kwargs.get("analysis"),
        ))
        conn.commit()

    def archive_fund_flow(self, code6: str, records: list[dict]):
        """存档资金流向明细

        Args:
            code6: 6位代码
            records: [{"trade_date": "2026-05-13", "close": 38.5, "change_pct": 1.2,
                       "main_net": 123456, "main_pct": 5.2, ...}, ...]
        """
        if not records:
            return

        conn = self._get_conn()
        for r in records:
            conn.execute("""
                INSERT OR REPLACE INTO fund_flow
                (code6, trade_date, close, change_pct,
                 main_net, main_pct, super_net, large_net, medium_net, small_net)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code6,
                r.get("trade_date"),
                r.get("close"),
                r.get("change_pct"),
                r.get("main_net"),
                r.get("main_pct"),
                r.get("super_net"),
                r.get("large_net"),
                r.get("medium_net"),
                r.get("small_net"),
            ))
        conn.commit()

    def archive_news(self, source: str, records: list[dict]):
        """存档新闻

        Args:
            source: 'eastmoney'/'caixin'/'cctv'/'sseinfo'
            records: [{"news_date": "2026-05-13", "title": "...", "content": "...", "url": "..."}, ...]
        """
        if not records:
            return

        conn = self._get_conn()
        for r in records:
            title = r.get("title", "")
            if not title:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO news_archive
                (source, news_date, title, content, url)
                VALUES (?, ?, ?, ?, ?)
            """, (
                source,
                r.get("news_date", datetime.now().strftime("%Y-%m-%d")),
                title,
                r.get("content", ""),
                r.get("url", ""),
            ))
        conn.commit()

    def archive_report(self, code6: str, trade_date: str, source: str,
                       report_json: str, **kwargs):
        """存档完整分析报告

        Args:
            code6: 6位代码
            trade_date: 分析日期
            source: '10agent'/'custom'
            report_json: 完整报告 JSON
            **kwargs: rating, target_price
        """
        conn = self._get_conn()

        conn.execute("""
            INSERT OR REPLACE INTO analysis_report
            (code6, trade_date, source, report_json, rating, target_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            code6, trade_date, source, report_json,
            kwargs.get("rating"),
            kwargs.get("target_price"),
        ))
        conn.commit()

    # ================================================================
    # 查询接口
    # ================================================================

    def get_stock_history(self, code6: str, limit: int = 10) -> list[dict]:
        """查询某股票的分析历史（按日期倒序）"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM stock_snapshot
            WHERE code6 = ?
            ORDER BY trade_date DESC, created_at DESC
            LIMIT ?
        """, (code6, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_sector_history(self, sector_code: str, sector_type: str,
                           limit: int = 10) -> list[dict]:
        """查询某板块的分析历史"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM sector_snapshot
            WHERE sector_code = ? AND sector_type = ?
            ORDER BY trade_date DESC, created_at DESC
            LIMIT ?
        """, (sector_code, sector_type, limit)).fetchall()
        return [dict(r) for r in rows]

    def compare_stock(self, code6: str, days_back: int = 1) -> Optional[dict]:
        """个股跨期对比

        Returns:
            {"current": {...}, "previous": {...}, "delta": {...}} 或 None
        """
        history = self.get_stock_history(code6, limit=days_back + 1)
        if len(history) < 2:
            return None

        curr = history[0]
        prev = history[days_back] if len(history) > days_back else history[-1]

        # 计算变化值
        delta = {}
        numeric_fields = ["price", "change_pct", "pe_ttm", "pb", "total_mv",
                         "turnover", "main_net", "main_pct", "super_net",
                         "large_net", "tech_score", "ta_target"]
        for f in numeric_fields:
            c = curr.get(f)
            p = prev.get(f)
            if c is not None and p is not None:
                delta[f] = c - p
            else:
                delta[f] = None

        return {"current": curr, "previous": prev, "delta": delta}

    def get_fund_flow_history(self, code6: str, days: int = 30) -> list[dict]:
        """查询资金流向历史"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM fund_flow
            WHERE code6 = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, (code6, days)).fetchall()
        return [dict(r) for r in rows]

    def get_news_history(self, source: str = None, date: str = None,
                         limit: int = 50) -> list[dict]:
        """查询新闻存档"""
        conn = self._get_conn()
        if source and date:
            rows = conn.execute("""
                SELECT * FROM news_archive
                WHERE source = ? AND news_date = ?
                ORDER BY created_at DESC LIMIT ?
            """, (source, date, limit)).fetchall()
        elif source:
            rows = conn.execute("""
                SELECT * FROM news_archive
                WHERE source = ?
                ORDER BY news_date DESC, created_at DESC LIMIT ?
            """, (source, limit)).fetchall()
        elif date:
            rows = conn.execute("""
                SELECT * FROM news_archive
                WHERE news_date = ?
                ORDER BY created_at DESC LIMIT ?
            """, (date, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM news_archive
                ORDER BY news_date DESC, created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_analyzed_stocks(self, source: str = None, days: int = 30) -> list[dict]:
        """查询最近分析过的股票列表"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        if source:
            rows = conn.execute("""
                SELECT code6, name, MAX(trade_date) as last_date,
                       COUNT(*) as times, source
                FROM stock_snapshot
                WHERE trade_date >= ? AND source = ?
                GROUP BY code6
                ORDER BY last_date DESC
            """, (cutoff, source)).fetchall()
        else:
            rows = conn.execute("""
                SELECT code6, name, MAX(trade_date) as last_date,
                       COUNT(*) as times, source
                FROM stock_snapshot
                WHERE trade_date >= ?
                GROUP BY code6
                ORDER BY last_date DESC
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def get_report(self, code6: str, trade_date: str = None,
                   source: str = "10agent") -> Optional[dict]:
        """查询完整分析报告"""
        conn = self._get_conn()
        if trade_date:
            row = conn.execute("""
                SELECT * FROM analysis_report
                WHERE code6 = ? AND trade_date = ? AND source = ?
            """, (code6, trade_date, source)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM analysis_report
                WHERE code6 = ? AND source = ?
                ORDER BY trade_date DESC LIMIT 1
            """, (code6, source)).fetchone()
        return dict(row) if row else None

    # ================================================================
    # 维护
    # ================================================================

    def get_stats(self) -> dict:
        """资料库统计"""
        conn = self._get_conn()
        stats = {}
        for table in ["stock_snapshot", "sector_snapshot", "fund_flow",
                      "news_archive", "analysis_report"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            stats[table] = count

        # DB文件大小
        if os.path.isfile(self.db_path):
            stats["db_size_mb"] = round(os.path.getsize(self.db_path) / 1024 / 1024, 2)
        else:
            stats["db_size_mb"] = 0

        # 时间范围
        try:
            row = conn.execute(
                "SELECT MIN(trade_date), MAX(trade_date) FROM stock_snapshot"
            ).fetchone()
            stats["date_range"] = f"{row[0]} ~ {row[1]}" if row[0] else "无数据"
        except Exception:
            stats["date_range"] = "无数据"

        return stats

    def cleanup(self, keep_days: int = 180):
        """清理超期数据

        - 新闻: 永久保留
        - 其他表: 保留 keep_days 天
        """
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")

        for table in ["stock_snapshot", "sector_snapshot", "fund_flow", "analysis_report"]:
            conn.execute(f"DELETE FROM {table} WHERE trade_date < ?", (cutoff,))

        # 删除 cache_meta 中的过期记录（如果存在该表）
        try:
            conn.execute(f"DELETE FROM cache_meta WHERE expires_at < datetime('now')")
        except Exception:
            pass

        conn.commit()

        # VACUUM 压缩（仅当 DB > 100MB 时）
        if os.path.isfile(self.db_path) and os.path.getsize(self.db_path) > 100 * 1024 * 1024:
            conn.execute("VACUUM")


# ============================================================
# 全局单例
# ============================================================

_lk: Optional[LocalKnowledge] = None


def get_lk() -> LocalKnowledge:
    """获取全局资料库实例"""
    global _lk
    if _lk is None:
        _lk = LocalKnowledge()
    return _lk


# ============================================================
# 命令行测试
# ============================================================

if __name__ == "__main__":
    lk = get_lk()

    # 测试存档
    print("=== 存档测试 ===")
    lk.archive_stock_snapshot("600519", "10agent",
        name="贵州茅台", price=1850.0, pe_ttm=25.3, pb=8.5,
        main_net=5.2e8, ta_rating="Buy", ta_target=2000.0)

    lk.archive_stock_snapshot("603737", "quick_analysis",
        name="三棵树", price=45.2, pe_ttm=30.1, pb=5.2,
        main_net=-1.5e8)

    lk.archive_fund_flow("600519", [
        {"trade_date": "2026-05-13", "close": 1850.0, "change_pct": 1.2,
         "main_net": 5.2e8, "main_pct": 3.5, "super_net": 3.1e8,
         "large_net": 2.1e8, "medium_net": -1.5e8, "small_net": -3.7e8},
    ])

    lk.archive_news("eastmoney", [
        {"news_date": "2026-05-13", "title": "测试新闻1", "content": "内容1"},
        {"news_date": "2026-05-13", "title": "测试新闻2", "content": "内容2"},
    ])

    # 查询测试
    print("\n=== 查询测试 ===")
    history = lk.get_stock_history("600519")
    print(f"600519 历史: {len(history)} 条")
    for h in history:
        print(f"  {h['trade_date']} {h.get('name','')} price={h.get('price')} pe={h.get('pe_ttm')} rating={h.get('ta_rating')}")

    analyzed = lk.get_analyzed_stocks()
    print(f"\n最近分析: {len(analyzed)} 只")
    for a in analyzed:
        print(f"  {a['code6']} {a.get('name','')} last={a['last_date']} times={a['times']}")

    # 对比测试
    compare = lk.compare_stock("600519")
    print(f"\n对比结果: {'有' if compare else '无（只有1条记录）'}")

    # 统计
    stats = lk.get_stats()
    print(f"\n=== 资料库统计 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
