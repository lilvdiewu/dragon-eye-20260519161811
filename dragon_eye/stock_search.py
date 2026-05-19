"""
dragon_eye.stock_search — 龙瞳Pro 股票搜索引擎

支持三种搜索维度: 代码前缀 / 名称模糊 / 拼音首字母前缀
启动时从 stock_pinyin.json 加载全量索引，纯内存过滤，单次 <10ms。

用法:
    from dragon_eye.stock_search import get_search_engine
    engine = get_search_engine()
    results = engine.search("MT")    # → 贵州茅台(MT) 等
    results = engine.search("茅台")  # → 600519 贵州茅台
    results = engine.search("600")   # → 600xxx 列表
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .tnf_parser import ensure_cache


# ============================================================
# 搜索结果
# ============================================================

@dataclass
class SearchResult:
    """单条搜索结果"""
    code: str       # 6位代码
    name: str       # 股票名称
    pinyin: str     # 拼音首字母
    market: str     # 市场: sh/sz/bj
    match_type: str # "exact" / "code_prefix" / "pinyin_prefix" / "name_contains"
    priority: int   # 排序用: 0=精确, 1=代码前缀, 2=拼音前缀, 3=名称包含


# ============================================================
# 搜索引擎
# ============================================================

class StockSearchEngine:
    """龙瞳Pro 股票搜索引擎

    - 单例模式，全局共享
    - 懒加载索引: 首次搜索时从 stock_pinyin.json 加载
    - 三维度搜索: 代码/名称/拼音
    - 结果按优先级排序: 精确 > 代码前缀 > 拼音前缀 > 名称包含
    """

    def __init__(self):
        self._index: Optional[dict[str, dict]] = None  # code -> {name, pinyin, market}

    def _ensure_loaded(self):
        """懒加载索引"""
        if self._index is None:
            self._index = ensure_cache()

    @property
    def count(self) -> int:
        """索引中的股票数量"""
        self._ensure_loaded()
        return len(self._index) if self._index else 0

    def search(self, keyword: str, limit: int = 20) -> list[SearchResult]:
        """模糊搜索

        搜索逻辑:
        1. keyword 为纯数字 → 代码前缀匹配 + 精确匹配
        2. keyword 为纯字母 → 拼音首字母前缀匹配 + 代码前缀匹配
        3. keyword 含中文 → 名称模糊包含 + 拼音前缀匹配
        4. 混合输入 → 各维度分别匹配，合并去重

        Args:
            keyword: 搜索关键词
            limit: 最多返回条数

        Returns:
            按优先级排序的搜索结果列表
        """
        self._ensure_loaded()
        if not self._index or not keyword or not keyword.strip():
            return []

        keyword = keyword.strip()
        results: dict[str, SearchResult] = {}  # code -> result (去重)

        kw_upper = keyword.upper()
        is_digit = keyword.isdigit()
        is_alpha = keyword.isalpha() and keyword.isascii()
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', keyword))

        # ---- 1. 精确匹配(代码完全匹配) ----
        if is_digit and len(keyword) == 6 and keyword in self._index:
            info = self._index[keyword]
            results[keyword] = SearchResult(
                code=keyword, name=info["name"], pinyin=info["pinyin"],
                market=info["market"], match_type="exact", priority=0,
            )

        # ---- 2. 代码前缀匹配 ----
        if is_digit or is_alpha:
            for code, info in self._index.items():
                if code.startswith(keyword):
                    if code not in results:
                        results[code] = SearchResult(
                            code=code, name=info["name"], pinyin=info["pinyin"],
                            market=info["market"], match_type="code_prefix", priority=1,
                        )

        # ---- 3. 拼音首字母前缀匹配 ----
        if is_alpha or has_chinese:
            for code, info in self._index.items():
                pinyin = info.get("pinyin", "")
                if pinyin.startswith(kw_upper):
                    if code not in results:
                        results[code] = SearchResult(
                            code=code, name=info["name"], pinyin=info["pinyin"],
                            market=info["market"], match_type="pinyin_prefix", priority=2,
                        )

        # ---- 4. 名称模糊包含 ----
        if has_chinese or (not is_digit and not is_alpha):
            for code, info in self._index.items():
                if keyword in info["name"]:
                    if code not in results:
                        results[code] = SearchResult(
                            code=code, name=info["name"], pinyin=info["pinyin"],
                            market=info["market"], match_type="name_contains", priority=3,
                        )

        # ---- 排序: priority 升序, 同 priority 按代码排序 ----
        sorted_results = sorted(results.values(), key=lambda r: (r.priority, r.code))

        return sorted_results[:limit]


# ============================================================
# 全局单例
# ============================================================

_engine: Optional[StockSearchEngine] = None


def get_search_engine() -> StockSearchEngine:
    """获取全局搜索引擎实例"""
    global _engine
    if _engine is None:
        _engine = StockSearchEngine()
    return _engine


# ============================================================
# 命令行测试
# ============================================================

if __name__ == "__main__":
    engine = get_search_engine()
    print(f"索引: {engine.count} 只股票\n")

    test_keywords = ["MT", "茅台", "600", "603618", "SKS", "PFYH", "NDSD", "ZGPA"]
    for kw in test_keywords:
        results = engine.search(kw, limit=5)
        print(f"搜索 '{kw}':")
        for r in results:
            print(f"  {r.code} {r.name} ({r.pinyin}) [{r.match_type}]")
        print()
