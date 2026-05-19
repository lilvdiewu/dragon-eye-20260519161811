"""
dragon_eye.tnf_parser — 通达信 .tnf 文件解析器

从通达信 hq_cache 目录下的 shs.tnf / szs.tnf / bjs.tnf 文件中
提取"代码+名称+拼音首字母"三合一数据，生成 JSON 缓存供搜索引擎使用。

文件格式(已验证):
- 360字节/条，50字节文件头
- 偏移 0-30:  代码(ASCII, null-terminated)
- 偏移 31-62: 名称(GBK, null-terminated)
- 偏移 329-360: 拼音首字母(ASCII大写, null-terminated)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .data_models import Market


# ============================================================
# 默认路径
# ============================================================

_TDX_HQ_CACHE = os.environ.get(
    "TDX_HQ_CACHE",
    "D:/new_tdx_test/T0002/hq_cache"
)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "stock_pinyin.json")


# ============================================================
# .tnf 文件解析
# ============================================================

RECORD_SIZE = 360
HEADER_SIZE = 50

# 各市场 .tnf 文件名
TNF_FILES = {
    "sh": "shs.tnf",
    "sz": "szs.tnf",
    "bj": "bjs.tnf",
}

# 需要排除的沪市指数代码
SH_INDEX_CODES = {
    "000001", "000002", "000003", "000004", "000005",
    "000006", "000007", "000008", "000009", "000010",
    "000011", "000012", "000013", "000015", "000016",
    "000017", "000300",
}


def _is_valid_stock_code(code6: str, market_key: str) -> bool:
    """判断6位代码是否是有效A股个股（轻量版，不依赖StockList）"""
    if len(code6) != 6 or not code6.isdigit():
        return False

    first = code6[0]
    if first not in ("0", "3", "4", "6", "8", "9"):
        return False

    # 沪市
    if market_key == "sh":
        if code6 in SH_INDEX_CODES:
            return False
        if code6.startswith("5"):
            return False  # ETF/基金

    # 深市
    if market_key == "sz":
        if code6.startswith("1") or code6.startswith("2"):
            return False  # 基金/B股

    # 北交所: 8xxxxx(个股, 83xxxx) / 9xxxxx(新股, 92xxxx)
    # 排除: 81xxxx(定转), 82xxxx(债券), 89xxxx(指数), 90xxxx(其他)
    if market_key == "bj":
        if code6.startswith("83") or code6.startswith("92"):
            return True
        return False

    return True


def parse_tnf_file(filepath: str, market_key: str) -> list[dict]:
    """解析单个 .tnf 文件

    返回: [{"code": "600000", "name": "浦发银行", "pinyin": "PFYH", "market": "sh"}, ...]
    """
    results = []
    file_size = os.path.getsize(filepath)

    if file_size <= HEADER_SIZE:
        return results

    num_records = (file_size - HEADER_SIZE) // RECORD_SIZE

    with open(filepath, "rb") as f:
        f.seek(HEADER_SIZE)  # 跳过文件头

        for _ in range(num_records):
            record = f.read(RECORD_SIZE)
            if len(record) < RECORD_SIZE:
                break

            # 提取代码 (偏移0-30, ASCII, null-terminated)
            code_raw = record[0:30]
            code = code_raw.split(b"\x00")[0].decode("ascii", errors="ignore").strip()

            # 提取名称 (偏移31-62, GBK, null-terminated)
            name_raw = record[31:62]
            name = name_raw.split(b"\x00")[0].decode("gbk", errors="ignore").strip()

            # 提取拼音 (偏移329-360, ASCII大写, null-terminated)
            pinyin_raw = record[329:360]
            pinyin = pinyin_raw.split(b"\x00")[0].decode("ascii", errors="ignore").strip().upper()

            # 过滤无效股票
            if not _is_valid_stock_code(code, market_key):
                continue

            # 过滤空名称/空拼音
            if not name or not pinyin:
                continue

            results.append({
                "code": code,
                "name": name,
                "pinyin": pinyin,
                "market": market_key,
            })

    return results


def parse_all(tdx_hq_cache: str = _TDX_HQ_CACHE) -> dict[str, dict]:
    """解析所有 .tnf 文件，返回 {code6: {name, pinyin, market}}

    自动去重（同一代码只保留第一个）
    """
    all_stocks: dict[str, dict] = {}

    for market_key, filename in TNF_FILES.items():
        filepath = os.path.join(tdx_hq_cache, filename)
        if not os.path.isfile(filepath):
            continue

        records = parse_tnf_file(filepath, market_key)
        for r in records:
            code = r["code"]
            if code not in all_stocks:  # 去重
                all_stocks[code] = {
                    "name": r["name"],
                    "pinyin": r["pinyin"],
                    "market": r["market"],
                }

    return all_stocks


def build_cache(output_path: str = _CACHE_PATH, tdx_hq_cache: str = _TDX_HQ_CACHE) -> dict[str, dict]:
    """解析 .tnf 文件并保存到 JSON 缓存

    返回: 解析后的 {code6: {name, pinyin, market}} 字典
    """
    data = parse_all(tdx_hq_cache)

    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def load_cache(cache_path: str = _CACHE_PATH) -> Optional[dict[str, dict]]:
    """从 JSON 缓存加载（主路径，避免每次重解析 .tnf）

    返回: {code6: {name, pinyin, market}} 或 None（缓存不存在时）
    """
    if not os.path.isfile(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def ensure_cache(cache_path: str = _CACHE_PATH, tdx_hq_cache: str = _TDX_HQ_CACHE) -> dict[str, dict]:
    """确保缓存可用: 先尝试加载，不存在则重新解析

    这是外部调用的主入口。
    """
    data = load_cache(cache_path)
    if data is not None:
        return data

    # 缓存不存在，重新解析
    return build_cache(cache_path, tdx_hq_cache)


# ============================================================
# 命令行入口: 手动重建缓存
# ============================================================

if __name__ == "__main__":
    print("解析通达信 .tnf 文件...")
    data = build_cache()
    print(f"完成! 共 {len(data)} 只股票")

    # 按市场统计
    markets = {}
    for code, info in data.items():
        m = info["market"]
        markets[m] = markets.get(m, 0) + 1
    for m, count in sorted(markets.items()):
        print(f"  {m}: {count} 只")

    # 示例
    print("\n示例:")
    for code in ["600519", "000001", "603618", "300750"]:
        if code in data:
            info = data[code]
            print(f"  {code} {info['name']} ({info['pinyin']})")
