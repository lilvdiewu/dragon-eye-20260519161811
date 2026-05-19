"""
dragon_eye.akshare_bridge — AkShare补充数据层

通达信本地数据覆盖: K线/分钟线
AkShare补充: 板块概念/财务/新闻/实时行情

设计原则:
  - AkShare按需调用，结果缓存
  - 失败不阻塞主流程
  - 返回标准数据模型
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .data_models import SectorInfo, Financial

# ============================================================
# 缓存配置
# ============================================================

CACHE_DIR = os.path.join(os.path.dirname(__file__), "_cache")
CACHE_TTL = {
    "sector_list": 86400,       # 板块列表: 1天
    "sector_stocks": 86400,     # 板块成分股: 1天
    "financial": 86400,          # 财务数据: 1天
    "realtime": 30,              # 实时行情: 30秒
    "news": 3600,                # 新闻: 1小时
}


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(prefix: str, identifier: str) -> str:
    return os.path.join(CACHE_DIR, f"{prefix}_{identifier}.json")


def _load_cache(prefix: str, identifier: str) -> Optional[dict]:
    """加载缓存，过期返回None"""
    path = _cache_key(prefix, identifier)
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cache_time = data.get("_cache_time", 0)
        ttl = CACHE_TTL.get(prefix, 3600)
        if time.time() - cache_time > ttl:
            return None
        return data
    except Exception:
        return None


def _save_cache(prefix: str, identifier: str, data: dict):
    """保存缓存"""
    _ensure_cache_dir()
    data["_cache_time"] = time.time()
    path = _cache_key(prefix, identifier)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# AkShare Bridge
# ============================================================

class AkShareBridge:
    """AkShare补充数据桥

    用法:
        bridge = AkShareBridge()
        sectors = bridge.get_industry_sectors()
        stocks = bridge.get_sector_stocks("BK0428")
        financial = bridge.get_financial("603618")
    """

    # 国内站点域名，不应走代理
    _DOMESTIC_DOMAINS = [
        "eastmoney.com", "push2.eastmoney.com",
        "sina.com.cn", "finance.sina.com.cn", "vip.stock.finance.sina.com.cn",
        "gtimg.cn", "qt.gtimg.cn",
        "qq.com",
        "10jqka.com.cn",
        "ths123.com",
    ]

    # 🔑 全局单例（避免Streamlit每个组件重复创建 → 内存爆炸+重复请求）
    _instance: Optional[AkShareBridge] = None

    def __init__(self, use_cache: bool = True, no_proxy: bool = True):
        self.use_cache = use_cache
        self.no_proxy = no_proxy  # 默认绕过代理（东方财富是国内站点）
        self._ak = None

        # 🔴 关键修复：在初始化时清除代理 + 设置NO_PROXY
        # 东方财富/腾讯/新浪都是国内站点，不应走代理
        # 不清除的话requests/urllib3会缓存代理配置导致超时
        if self.no_proxy:
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)
            self._set_no_proxy()

    @classmethod
    def _set_no_proxy(cls):
        """设置NO_PROXY环境变量，确保国内站点不走代理"""
        no_proxy_val = ",".join(cls._DOMESTIC_DOMAINS + ["localhost", "127.0.0.1"])
        existing = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
        if existing:
            # 合并，去重
            parts = set(existing.split(",")) | set(no_proxy_val.split(","))
            no_proxy_val = ",".join(parts)
        os.environ["NO_PROXY"] = no_proxy_val
        os.environ["no_proxy"] = no_proxy_val

    def _get_ak(self):
        """懒加载akshare，绕过代理访问国内数据源"""
        if self._ak is None:
            # 🔑 关键修复：彻底清除所有代理设置
            # 必须在 import akshare 之前清，因为 akshare import 时会读取环境变量
            for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                       "all_proxy", "ALL_PROXY", "socks_proxy", "SOCKS_PROXY"]:
                os.environ.pop(k, None)
            self._set_no_proxy()

            try:
                import akshare as ak
                self._ak = ak
                # 🔑 不再 monkey-patch requests.Session.request！
                # 之前的 patch 会导致:
                # 1. 所有 requests.Session（包括东方财富内部）被修改
                # 2. 与 akshare 内部的 session 管理冲突
                # 3. 可能触发东方财富风控
                # 改为在每个调用的 session 上单独设置 timeout
            except ImportError:
                raise ImportError(
                    "akshare未安装，请运行: pip install akshare"
                )
        return self._ak

    # --- 板块/概念 ---

    def get_industry_sectors(self) -> list[SectorInfo]:
        """获取行业板块列表"""
        if self.use_cache:
            cached = _load_cache("sector_list", "industry")
            if cached:
                return [SectorInfo(**s) for s in cached.get("data", [])]

        # 尝试AkShare
        ak = self._get_ak()
        try:
            df = self._fetch_retry(
                lambda: ak.stock_board_industry_name_em(),
                "行业板块列表(AkShare)",
            )
            if df is None:
                raise RuntimeError("行业板块列表获取失败")
            sectors = []
            for _, row in df.iterrows():
                sectors.append(SectorInfo(
                    name=str(row.get("板块名称", "")),
                    code=str(row.get("板块代码", "")),
                    sector_type="industry",
                    change_pct=float(row.get("涨跌幅", 0)),
                ))
            if self.use_cache:
                _save_cache("sector_list", "industry", {
                    "data": [{"name": s.name, "code": s.code,
                              "sector_type": s.sector_type, "change_pct": s.change_pct}
                             for s in sectors]
                })
            return sectors
        except Exception as e:
            print(f"⚠️ AkShare获取行业板块失败: {e}")

        # Fallback: 新浪行业板块
        return self._fetch_sectors_from_sina("industry")

    def get_concept_sectors(self) -> list[SectorInfo]:
        """获取概念板块列表"""
        if self.use_cache:
            cached = _load_cache("sector_list", "concept")
            if cached:
                return [SectorInfo(**s) for s in cached.get("data", [])]

        # 尝试AkShare
        ak = self._get_ak()
        try:
            df = self._fetch_retry(
                lambda: ak.stock_board_concept_name_em(),
                "概念板块列表(AkShare)",
            )
            if df is None:
                raise RuntimeError("概念板块列表获取失败")
            sectors = []
            for _, row in df.iterrows():
                sectors.append(SectorInfo(
                    name=str(row.get("板块名称", "")),
                    code=str(row.get("板块代码", "")),
                    sector_type="concept",
                    change_pct=float(row.get("涨跌幅", 0)),
                ))
            if self.use_cache:
                _save_cache("sector_list", "concept", {
                    "data": [{"name": s.name, "code": s.code,
                              "sector_type": s.sector_type, "change_pct": s.change_pct}
                             for s in sectors]
                })
            return sectors
        except Exception as e:
            print(f"⚠️ AkShare获取概念板块失败: {e}")

        # Fallback: 新浪概念板块
        return self._fetch_sectors_from_sina("concept")

    def get_sector_stocks(self, sector_code: str, sector_type: str = "industry") -> list[str]:
        """获取板块成分股代码列表

        Args:
            sector_code: 板块代码
            sector_type: industry/concept
        Returns:
            6位股票代码列表
        """
        cache_id = f"{sector_type}_{sector_code}"
        if self.use_cache:
            cached = _load_cache("sector_stocks", cache_id)
            if cached:
                return cached.get("data", [])

        ak = self._get_ak()
        try:
            if sector_type == "industry":
                df = self._fetch_retry(
                    lambda: ak.stock_board_industry_cons_em(symbol=sector_code),
                    f"行业板块成分股({sector_code})",
                )
            else:
                df = self._fetch_retry(
                    lambda: ak.stock_board_concept_cons_em(symbol=sector_code),
                    f"概念板块成分股({sector_code})",
                )
            if df is None:
                return []

            codes = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                if len(code) == 6 and code.isdigit():
                    codes.append(code)

            if self.use_cache:
                _save_cache("sector_stocks", cache_id, {"data": codes})
            return codes
        except Exception as e:
            print(f"⚠️ AkShare获取板块成分股失败({sector_code}): {e}")
            return []

    def search_sector(self, keyword: str) -> list[SectorInfo]:
        """搜索板块/概念"""
        results = []
        # 行业板块
        for sector in self.get_industry_sectors():
            if keyword in sector.name:
                results.append(sector)
        # 概念板块
        for sector in self.get_concept_sectors():
            if keyword in sector.name:
                results.append(sector)
        return results

    # --- 财务数据 ---

    def get_financial(self, code6: str) -> Optional[Financial]:
        """获取个股财务摘要"""
        if self.use_cache:
            cached = _load_cache("financial", code6)
            if cached and "data" in cached:
                return Financial(**cached["data"])

        ak = self._get_ak()
        try:
            # 获取主要财务指标
            df = self._fetch_retry(
                lambda: ak.stock_financial_abstract_ths(symbol=code6, indicator="按报告期"),
                f"财务数据({code6})",
            )
            if df is None or df.empty:
                return None

            row = df.iloc[0]  # 最新一期
            financial = Financial(
                code=code6,
                name=str(row.get("股票名称", "")),
                report_date=str(row.get("报告期", "")),
                eps=float(row.get("每股收益", 0) or 0),
                bvps=float(row.get("每股净资产", 0) or 0),
                roe=float(row.get("净资产收益率", 0) or 0),
            )

            if self.use_cache:
                _save_cache("financial", code6, {"data": vars(financial)})
            return financial
        except Exception as e:
            print(f"⚠️ AkShare获取财务数据失败({code6}): {e}")
            return None

    # --- 实时行情 ---

    def get_realtime_spot(self, code6: str) -> Optional[dict]:
        """获取实时行情快照

        优先腾讯API（稳定），AkShare/东方财富作为备用（当前SSL不兼容）
        """
        # 1. 优先腾讯API（直接可用）
        result = self.get_realtime_quote_tencent(code6)
        if result and result.get("price", 0) > 0:
            return result

        # 2. AkShare/东方财富作为备用
        try:
            ak = self._get_ak()
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == code6]
            if not row.empty:
                r = row.iloc[0]
                return {
                    "code": code6,
                    "name": str(r.get("名称", "")),
                    "price": float(r.get("最新价", 0) or 0),
                    "change_pct": float(r.get("涨跌幅", 0) or 0),
                    "volume": float(r.get("成交量", 0) or 0),
                    "amount": float(r.get("成交额", 0) or 0),
                    "turnover_rate": float(r.get("换手率", 0) or 0),
                    "pe_ttm": float(r.get("市盈率-动态", 0) or 0),
                    "pb": float(r.get("市净率", 0) or 0),
                    "total_mv": float(r.get("总市值", 0) or 0),
                    "circ_mv": float(r.get("流通市值", 0) or 0),
                }
        except Exception as e:
            print(f"⚠️ AkShare获取实时行情失败({code6}): {e}")

        return result

    # --- 股票名称补充 ---

    def enrich_stock_names(self, stock_infos: list) -> dict[str, str]:
        """获取股票名称映射（纯本地优先，不轻易联网）

        优先级:
        1. 本地JSON缓存（sina_fetch_names.py 生成）→ 直接返回，不联网
        2. 新浪API在线拉取 → 仅当缓存不存在时
        3. AkShare → 最后手段

        Returns:
            {code6: name, ...}
        """
        # 1. 优先从本地JSON缓存加载（已由sina_fetch_names.py生成）
        name_map = self._load_local_names()
        if name_map and len(name_map) >= 1000:
            return name_map

        # 2. 如果本地缓存不存在或过小，才尝试在线拉取
        # 🔑 关键修复：只在缓存不存在时才联网，避免Streamlit每次渲染都拉取
        try:
            name_map = self._fetch_names_from_sina()
            if name_map and len(name_map) >= 1000:
                return name_map
        except Exception as e:
            print(f"⚠️ 新浪API获取股票名称失败: {e}")

        # 3. 最后尝试AkShare（会拉全市场数据，最慢）
        # 🔑 同样只在上面都失败时才调用
        ak = self._get_ak()
        try:
            df = ak.stock_zh_a_spot_em()
            name_map = {}
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                if code and name:
                    name_map[code] = name
            # 保存到本地缓存，下次不用再联网
            if name_map:
                cache_path = os.path.join(os.path.dirname(__file__), "_cache", "stock_names.json")
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(name_map, f, ensure_ascii=False)
            return name_map
        except Exception as e:
            print(f"⚠️ AkShare获取股票名称失败: {e}")
            return {}

    def _load_local_names(self) -> dict[str, str]:
        """从本地JSON缓存加载股票名称"""
        cache_path = os.path.join(os.path.dirname(__file__), "_cache", "stock_names.json")
        if not os.path.isfile(cache_path):
            return {}
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _fetch_names_from_sina(self) -> dict[str, str]:
        """从新浪API批量拉取A股名称"""
        import requests as req

        # 清除代理
        session = req.Session()
        session.trust_env = False

        name_map = {}
        page = 1
        while True:
            url = ("https://vip.stock.finance.sina.com.cn/quotes_service/"
                   "api/json_v2.php/Market_Center.getHQNodeData")
            params = {"page": page, "num": 80, "sort": "symbol",
                      "asc": 1, "node": "hs_a", "symbol": "", "_s_r_a": "auto"}
            try:
                resp = session.get(url, params=params, timeout=15)
                data = resp.json()
                if not data:
                    break
                for item in data:
                    code = item.get("code", "")
                    name = item.get("name", "")
                    if code and name and len(code) == 6 and code.isdigit():
                        name_map[code] = name
                page += 1
            except Exception:
                break

        # 保存到本地缓存
        if name_map:
            cache_path = os.path.join(os.path.dirname(__file__), "_cache", "stock_names.json")
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(name_map, f, ensure_ascii=False)

        return name_map

    # --- 行业/概念归属 本地缓存 ---

    def get_stock_sector_local(self, code6: str) -> str:
        """从本地缓存查股票所属行业（零网络请求）

        优先级:
        1. 本地 _cache/stock_sectors.json → 直接返回
        2. 本地缓存不存在 → 触发一次在线构建
        3. 构建失败 → 返回空串

        Returns:
            行业名称，如"半导体"；找不到返回空串
        """
        # 1. 优先读本地
        mapping = self._load_sector_mapping()
        if mapping:
            return mapping.get(code6, "")

        # 2. 本地缓存不存在，触发一次构建
        print("📦 板块缓存不存在，正在构建（仅此一次）...")
        mapping = self.build_sector_cache()
        if mapping:
            return mapping.get(code6, "")

        return ""

    def build_sector_cache(self) -> dict[str, str]:
        """一次性构建 {code6: industry_name} 映射并保存本地

        抄自原版 data_collector.py 的稳定模式:
        - 分批请求（每10个板块），批次间休眠1秒
        - 单次请求带重试（3次，退避1.5s）
        - 每10个板块增量存盘，断了不丢数据
        - 只拉行业板块（84个），不拉概念板块（几百个会卡死）

        Returns:
            {code6: industry_name} 映射字典
        """
        import requests as req

        session = req.Session()
        session.trust_env = False

        # 先加载已有映射（增量模式：断了继续）
        mapping = self._load_sector_mapping()
        existing_count = len(mapping)

        # ---- 新浪API：分批拉行业板块+成分股 ----
        try:
            url = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
            params = {"param": "industry"}
            resp = self._fetch_retry(
                lambda: session.get(url, params=params, timeout=15),
                "行业板块列表",
            )
            if resp is None:
                print("  ❌ 行业板块列表获取失败")
                return mapping

            resp.encoding = "gbk"
            import re
            board_pattern = r'"(\w+)":"([^"]+)"'
            boards = re.findall(board_pattern, resp.text)

            total = len(boards)
            print(f"  📡 新浪API: {total} 个行业板块，分批拉取（每批10个，间隔1秒）")

            BATCH = 10
            for batch_start in range(0, total, BATCH):
                batch = boards[batch_start:batch_start + BATCH]

                for key, val in batch:
                    # 跳过已映射的板块（增量：断了继续）
                    parts = val.split(",")
                    sector_name = parts[1] if len(parts) >= 2 else val

                    # 分页拉成分股（带重试）
                    page = 1
                    while True:
                        url2 = ("https://vip.stock.finance.sina.com.cn/quotes_service/"
                                "api/json_v2.php/Market_Center.getHQNodeData")
                        params2 = {
                            "page": page, "num": 80, "sort": "symbol",
                            "asc": 1, "node": key, "_s_r_a": "auto",
                        }
                        try:
                            resp2 = self._fetch_retry(
                                lambda p=params2: session.get(
                                    "https://vip.stock.finance.sina.com.cn/quotes_service/"
                                    "api/json_v2.php/Market_Center.getHQNodeData",
                                    params=p, timeout=10,
                                ),
                                f"板块成分股({sector_name})",
                            )
                            if resp2 is None:
                                break
                            data = resp2.json()
                            if not data:
                                break
                            for item in data:
                                code = item.get("code", "")
                                if len(code) == 6 and code.isdigit():
                                    if code not in mapping:
                                        mapping[code] = sector_name
                            page += 1
                        except Exception:
                            break

                # 批次进度 + 存盘 + 休眠
                done = min(batch_start + BATCH, total)
                print(f"  📊 进度: {done}/{total} | 已映射 {len(mapping)} 只股票")
                # 每10个板块增量存盘
                self._save_sector_mapping(mapping)
                # 休眠1秒，避免被限流（抄原版 _fetch_retry 退避思路）
                if done < total:
                    time.sleep(1)

            print(f"  ✅ 行业映射完成: {len(mapping)} 只股票"
                  f"（新增 {len(mapping) - existing_count}）")

        except Exception as e:
            print(f"  ⚠️ 新浪API构建失败: {e}")
            # 即使失败也保存已有数据
            if mapping:
                self._save_sector_mapping(mapping)

        # ---- 东方财富行业板块补充（仅当新浪数据不足时）----
        if len(mapping) < 3000:
            print(f"  📡 映射偏少({len(mapping)})，东方财富行业补充（分批+间隔）...")
            try:
                industries = self.get_industry_sectors()  # 有缓存
                for i, ind in enumerate(industries):
                    if ind.code and not ind.code.startswith("SINA_"):
                        stocks = self.get_sector_stocks(ind.code, "industry")  # 有缓存
                        for code in stocks:
                            if code not in mapping:
                                mapping[code] = ind.name
                    # 每10个存一次盘
                    if (i + 1) % 10 == 0:
                        self._save_sector_mapping(mapping)
                        time.sleep(0.5)  # 短暂休息
                print(f"  ✅ 东方财富补充完成: 共 {len(mapping)} 只股票")
            except Exception as e:
                print(f"  ⚠️ 东方财富补充失败: {e}")

        # ---- 最终存盘 ----
        if mapping:
            self._save_sector_mapping(mapping)
            print(f"  💾 板块映射已保存: {len(mapping)} 只股票 → _cache/stock_sectors.json")
        else:
            print(f"  ❌ 构建失败: 映射为空")

        return mapping

    def _fetch_retry(self, func, label: str, max_retries: int = 3):
        """带重试的请求（抄自原版 data_collector._fetch_retry）

        Args:
            func: 返回 Response 的调用
            label: 日志标签
            max_retries: 最大重试次数
        Returns:
            Response 或 None
        """
        last_err = None
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = 1.5 * (attempt + 1)
                    print(f"  ⚠️ {label} 第{attempt+1}次失败，{wait}秒后重试: {e}")
                    time.sleep(wait)
        print(f"  ❌ {label} 重试{max_retries}次均失败: {type(last_err).__name__}")
        return None

    def _load_sector_mapping(self) -> dict[str, str]:
        """从本地加载股票→行业映射（不过期，手动刷新）

        支持两种格式:
        1. {code: name} — 旧格式
        2. {"_meta": {...}, "data": {code: name}} — 新格式（含元数据）
        """
        cache_path = os.path.join(CACHE_DIR, "stock_sectors.json")
        if not os.path.isfile(cache_path):
            return {}
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 新格式：带 _meta 字段
            if isinstance(data, dict) and "_meta" in data:
                mapping_data = data.get("data", {})
            else:
                mapping_data = data

            # 兼容: {code: name} 或 {code: {"industry": name, ...}}
            result = {}
            for k, v in mapping_data.items():
                if k == "_meta":
                    continue
                if isinstance(v, str):
                    result[k] = v
                elif isinstance(v, dict):
                    result[k] = v.get("industry", v.get("concept", ""))
            return result
        except Exception:
            return {}

    def _save_sector_mapping(self, mapping: dict[str, str]):
        """保存股票→行业映射到本地（含元数据）"""
        _ensure_cache_dir()
        cache_path = os.path.join(CACHE_DIR, "stock_sectors.json")
        payload = {
            "_meta": {
                "version": 1,
                "built_at": datetime.now().isoformat(),
                "stock_count": len(mapping),
            },
            "data": mapping,
        }
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存板块映射失败: {e}")

    def _get_sector_cache_meta(self) -> Optional[dict]:
        """读取板块缓存元数据（不加载全量数据）"""
        cache_path = os.path.join(CACHE_DIR, "stock_sectors.json")
        if not os.path.isfile(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "_meta" in data:
                return data["_meta"]
            # 旧格式：没有 _meta，返回基本信息
            return {
                "version": 0,
                "built_at": "unknown",
                "stock_count": len(data) if isinstance(data, dict) else 0,
            }
        except Exception:
            return None

    # --- 新浪API Fallback ---

    def _fetch_sectors_from_sina(self, sector_type: str = "industry") -> list[SectorInfo]:
        """从新浪API获取行业/概念板块列表（东方财富SSL不兼容时的备用通道）"""
        import re
        import requests as req

        session = req.Session()
        session.trust_env = False

        sectors = []
        try:
            if sector_type == "industry":
                url = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
                params = {"param": "class"}
                resp = session.get(url, params=params, timeout=15)
                resp.encoding = "gbk"
                text = resp.text
                pattern = r'var\s+S_Finance_bankuai_sin\d+\s*=\s*"([^"]+)"'
                matches = re.findall(pattern, text)
                for match in matches:
                    parts = match.split("|")
                    if len(parts) >= 3:
                        name = parts[0]
                        code = f"SINA_{sector_type}_{len(sectors)}"
                        change = 0.0
                        if len(parts) >= 4:
                            try:
                                change = float(parts[-1])
                            except (ValueError, IndexError):
                                pass
                        sectors.append(SectorInfo(
                            name=name, code=code,
                            sector_type=sector_type, change_pct=change,
                        ))
        except Exception as e:
            print(f"⚠️ 新浪API获取板块失败: {e}")

        return sectors

    def get_realtime_quote_tencent(self, code6: str) -> Optional[dict]:
        """从腾讯API获取实时行情（东方财富SSL不兼容时的备用通道）

        Returns:
            {code, name, price, change_pct, volume, amount, pe_ttm, pb, total_mv}
        """
        import requests as req

        market = "sh" if code6.startswith("6") else "sz"
        symbol = f"{market}{code6}"

        # 清除代理 + 设置NO_PROXY（腾讯API是国内站点，不走代理）
        for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            os.environ.pop(k, None)
        self._set_no_proxy()
        session = req.Session()
        session.trust_env = False  # 不读系统代理

        try:
            url = f"https://qt.gtimg.cn/q={symbol}"
            resp = session.get(url, timeout=10)
            text = resp.text
            if not text or "~" not in text:
                return None

            parts = text.split("~")
            if len(parts) < 50:
                return None

            name = parts[1] if len(parts) > 1 else ""
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
            volume = float(parts[6]) if len(parts) > 6 and parts[6] else 0
            amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0
            total_mv = float(parts[45]) if len(parts) > 45 and parts[45] else 0

            return {
                "code": code6,
                "name": name,
                "price": price,
                "change_pct": change_pct,
                "volume": volume,
                "amount": amount,
                "turnover_rate": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                "pe_ttm": 0.0,
                "pb": 0.0,
                "total_mv": total_mv * 10000 if total_mv > 0 else 0,
                "circ_mv": 0,
            }
        except Exception as e:
            print(f"⚠️ 腾讯行情获取失败({code6}): {e}")
            return None


# ============================================================
# 全局单例（核心修复：避免Streamlit每次渲染都创建新实例）
# ============================================================

_bridge_instance: Optional[AkShareBridge] = None

def get_bridge() -> AkShareBridge:
    """获取全局 AkShareBridge 单例

    Streamlit 每次交互都重新渲染页面，如果每个组件都 AkShareBridge()
    创建新实例，会导致:
    1. 重复 monkey-patch requests（冲突）
    2. 重复拉取全市场数据（5000+行DataFrame × N次 = 内存爆炸）
    3. 重复清除/设置代理环境变量（竞态条件）

    使用单例后：
    - akshare 只 import 一次
    - requests 只 patch 一次
    - 缓存只维护一份
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = AkShareBridge()
    return _bridge_instance
