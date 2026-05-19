"""
dragon_eye.sector.ths_sector — 同花顺板块数据引擎

三大核心:
1. TdxSectorMapper   — TDX本地文件加载股票→行业/概念映射（<1s，零网络）
2. ThsSectorFetcher  — AKShare _ths接口获取行业/概念实时数据
3. SectorRanker      — 板块强度排名 + 轮动信号检测

数据流:
  TDX本地(瞬间) → THS实时(~3s) → 强度排名(<1s) → 轮动检测(~15s)
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# 数据类
# ============================================================

@dataclass
class SectorStrength:
    """板块强度评分结果"""
    name: str                           # 板块名称
    code: str = ""                      # 板块代码
    sector_type: str = "industry"       # industry / concept
    change_pct: float = 0.0            # 涨跌幅
    net_inflow: float = 0.0            # 净流入(亿)
    up_ratio: float = 0.0             # 上涨家数占比
    turnover: float = 0.0             # 换手率
    momentum_3d: float = 0.0          # 3日动量
    momentum_5d: float = 0.0          # 5日动量
    strength_score: float = 0.0       # 综合强度分
    grade: str = "C"                   # S/A/B/C
    rotation_signal: str = ""          # 轮动信号
    top_stocks: list = field(default_factory=list)  # 领涨股
    stock_count: int = 0               # 成分股数


# ============================================================
# TDX本地映射器
# ============================================================

class TdxSectorMapper:
    """从TDX本地文件加载股票→行业/概念映射

    数据源:
    - tdxhy.cfg: 5530只股票→行业映射
    - hy_tree.xml: 30大类/127子类/347细分行业树
    - infoharbor_block.dat: 269个概念板块→成分股
    """

    TDX_ROOT = "D:/new_tdx_test"

    def __init__(self, tdx_root: str | None = None):
        self.tdx_root = tdx_root or self.TDX_ROOT
        self._industry_map: dict[str, str] = {}    # {code6: industry_name}
        self._concept_map: dict[str, list[str]] = {}  # {concept_name: [code6, ...]}
        self._stock_concepts: dict[str, list[str]] = {}  # {code6: [concept_name, ...]}
        self._industry_tree: dict = {}  # 行业树层级
        self._code_to_name: dict[str, str] = {}   # {T代码/X代码: 中文名}

    def load_all(self) -> bool:
        """加载所有TDX本地映射数据

        加载顺序:
        1. hy_tree.xml → X-code→名称映射（概念）
        2. tdxhy.cfg → 股票→X-code映射（仅概念，T-code走AKShare）
        3. infoharbor_block.dat → 概念板块→成分股
        4. AKShare在线 → T-code行业映射（带缓存）
        """
        ok1 = self.load_hy_tree()
        ok2 = self.load_tdxhy()
        ok3 = self.load_infoharbor()
        # 行业映射：优先AKShare缓存，失败则fallback到TDX本地+AKShare在线
        ok4 = self.load_industry_from_akshare()
        return ok1 or ok2 or ok3 or ok4

    def load_tdxhy(self) -> bool:
        """加载 tdxhy.cfg → 股票→行业/概念映射

        格式: market|code6|T_code|||X_code
        T代码 = 行业, X代码 = 概念
        通过 self._code_to_name 转换为中文
        """
        path = os.path.join(self.tdx_root, "T0002/hq_cache/tdxhy.cfg")
        if not os.path.isfile(path):
            print(f"[TdxSectorMapper] tdxhy.cfg 不存在: {path}")
            return False

        industry_count = 0
        concept_count = 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 3:
                        continue

                    code6 = parts[1] if len(parts) > 1 else ""
                    if not code6 or len(code6) != 6 or not code6.isdigit():
                        continue

                    # T代码 = 行业
                    t_code = parts[2] if len(parts) > 2 else ""
                    if t_code and t_code.startswith("T"):
                        # 优先用精确匹配，否则用父级
                        industry_name = self._code_to_name.get(t_code, "")
                        if not industry_name:
                            # 尝试父级（T1206 → T12 → T1）
                            for parent_len in [len(t_code)-2, len(t_code)-1]:
                                if parent_len >= 2:
                                    parent_code = t_code[:parent_len]
                                    industry_name = self._code_to_name.get(parent_code, "")
                                    if industry_name:
                                        break
                        if industry_name:
                            self._industry_map[code6] = industry_name
                            industry_count += 1

                    # X代码 = 概念
                    x_code = parts[5] if len(parts) > 5 else ""
                    if x_code and x_code.startswith("X"):
                        concept_name = self._code_to_name.get(x_code, "")
                        if not concept_name:
                            for parent_len in [len(x_code)-2, len(x_code)-1]:
                                if parent_len >= 2:
                                    parent_code = x_code[:parent_len]
                                    concept_name = self._code_to_name.get(parent_code, "")
                                    if concept_name:
                                        break
                        if concept_name:
                            if concept_name not in self._concept_map:
                                self._concept_map[concept_name] = []
                            self._concept_map[concept_name].append(code6)
                            if code6 not in self._stock_concepts:
                                self._stock_concepts[code6] = []
                            self._stock_concepts[code6].append(concept_name)
                            concept_count += 1

            print(f"[TdxSectorMapper] tdxhy.cfg: {industry_count} 行业映射, "
                  f"{concept_count} 概念映射 ({len(set(self._industry_map.values()))} 个行业)")
            return industry_count > 0
        except Exception as e:
            print(f"[TdxSectorMapper] 加载 tdxhy.cfg 失败: {e}")
            return False

    def load_hy_tree(self) -> bool:
        """加载 hy_tree.xml → 代码→名称映射

        格式: GBK编码的XML，<node caption="行业名" blockid="X1001" .../>
        """
        path = os.path.join(self.tdx_root, "T0002/cloud_cfg/hy_tree.xml")
        if not os.path.isfile(path):
            print(f"[TdxSectorMapper] hy_tree.xml 不存在: {path}")
            return False

        try:
            # hy_tree.xml 是GBK编码，需要先解码再用ET解析
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("gbk", errors="replace")
            root = ET.fromstring(text)

            count = 0
            for node in root.iter():
                caption = node.get("caption", "")
                blockid = node.get("blockid", "")
                if caption and blockid:
                    self._code_to_name[blockid] = caption
                    count += 1

            print(f"[TdxSectorMapper] hy_tree.xml: {count} 个代码→名称映射")
            return count > 0
        except Exception as e:
            print(f"[TdxSectorMapper] 加载 hy_tree.xml 失败: {e}")
            return False

    def load_infoharbor(self) -> bool:
        """加载 infoharbor_block.dat -> 概念板块->成分股映射

        FIX 2026-05-19: 此文件是文本格式，不是二进制！
        格式: #GN_概念名,股票数,板块代码,起始日期,结束日期,,
              市场#股票代码,市场#股票代码,...    (每行~85个，逗号分隔)
              市场: 0=深市, 1=沪市, 2=北交所
        也有 #ZS_ 前缀的主题板块
        """
        path = os.path.join(self.tdx_root, "T0002/hq_cache/infoharbor_block.dat")
        if not os.path.isfile(path):
            print(f"[TdxSectorMapper] infoharbor_block.dat 不存在: {path}")
            return False

        try:
            with open(path, "rb") as f:
                data = f.read()
            text = data.decode("gbk", errors="replace")
            lines = text.split("\n")

            count = 0
            current_name = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("#GN_") or line.startswith("#ZS_"):
                    header = line[4:]  # 去掉 #GN_
                    if header.startswith("ZS_"):
                        header = header[3:]
                    parts = header.split(",")
                    if parts:
                        current_name = parts[0].strip()
                    continue

                if current_name and "#" in line:
                    codes = []
                    for seg in line.split(","):
                        seg = seg.strip()
                        if "#" in seg and not seg.startswith("#"):
                            mc = seg.split("#")
                            if len(mc) >= 2:
                                code = mc[1]
                                if len(code) == 6 and code.isdigit():
                                    codes.append(code)
                    if codes:
                        if current_name not in self._concept_map:
                            self._concept_map[current_name] = []
                        self._concept_map[current_name].extend(codes)
                        for c in codes:
                            if c not in self._stock_concepts:
                                self._stock_concepts[c] = []
                            if current_name not in self._stock_concepts[c]:
                                self._stock_concepts[c].append(current_name)
                        count += 1

            total = sum(len(v) for v in self._concept_map.values())
            print(f"[TdxSectorMapper] infoharbor_block.dat: {count} 个板块, {total} 条映射")
            return count > 0

        except Exception as e:
            print(f"[TdxSectorMapper] 加载 infoharbor_block.dat 失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    def _load_industry_map_from_akshare(self) -> bool:
        """加载行业映射（stock→行业中文名）

        数据源优先级:
        1. 本地缓存 _cache/stock_sectors.json（由 akshare_bridge 构建）
        2. 本地缓存 _cache/industry_map.json（本模块独立构建）
        3. AKShare在线拉取（stock_board_industry_name_ths + stock_board_industry_cons_em）
        4. 失败 → 不影响概念映射，行业为空
        """
        import json as _json

        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_cache")

        # --- 数据源1: stock_sectors.json（AkShareBridge 构建，优先） ---
        sectors_cache = os.path.join(cache_dir, "stock_sectors.json")
        if os.path.isfile(sectors_cache):
            try:
                with open(sectors_cache, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                mapping = data.get("data", {}) if "_meta" in data else data
                if mapping and len(mapping) >= 300:
                    loaded = 0
                    for code6, val in mapping.items():
                        if isinstance(val, str):
                            ind_name = val
                        elif isinstance(val, dict):
                            ind_name = val.get("industry", "") or val.get("concept", "")
                        else:
                            continue
                        if ind_name and code6 not in self._industry_map:
                            self._industry_map[code6] = ind_name
                            loaded += 1
                    if loaded > 0:
                        print(f"[TdxSectorMapper] stock_sectors.json: {loaded} 条行业映射 "
                              f"({len(set(self._industry_map.values()))} 个行业)")
                        return True
            except Exception:
                pass

        # --- 数据源2: industry_map.json（本模块独立构建） ---
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "industry_map.json")
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                cache_time = data.get("_cache_time", 0)
                if time.time() - cache_time < 86400:
                    mapping = data.get("data", {})
                    if mapping:
                        for code6, ind_name in mapping.items():
                            if code6 not in self._industry_map:
                                self._industry_map[code6] = ind_name
                        print(f"[TdxSectorMapper] industry_map.json: {len(mapping)} 条行业映射 "
                              f"({len(set(mapping.values()))} 个行业)")
                        return True
            except Exception:
                pass

        # --- 数据源3: AKShare在线拉取 ---
        print("[TdxSectorMapper] 行业映射缓存不存在/过期，正在通过AKShare拉取...")
        try:
            import akshare as ak
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)

            # Step 1: stock_board_industry_name_ths() → 行业列表
            # 列名: 'name' (行业名), 'code' (代码如881121)
            df_industries = ak.stock_board_industry_name_ths()
            if df_industries is None or df_industries.empty:
                print("[TdxSectorMapper] AKShare行业列表为空")
                return False

            industry_names = []
            for _, row in df_industries.iterrows():
                name = str(row.get("name", ""))
                if name and name != "nan":
                    industry_names.append(name)

            print(f"[TdxSectorMapper] AKShare: {len(industry_names)} 个行业板块")

            if not industry_names:
                return False

            # Step 2: stock_board_industry_cons_em() → 成分股（东方财富接口）
            # 需要设置NO_PROXY避免走代理
            os.environ["NO_PROXY"] = "eastmoney.com,push2.eastmoney.com,localhost,127.0.0.1"
            os.environ["no_proxy"] = os.environ["NO_PROXY"]

            mapping: dict[str, str] = {}
            print(f"[TdxSectorMapper] 正在获取成分股...")
            for idx, ind_name in enumerate(industry_names):
                try:
                    df_stocks = ak.stock_board_industry_cons_em(symbol=ind_name)
                    if df_stocks is not None and not df_stocks.empty:
                        for _, srow in df_stocks.iterrows():
                            code = str(srow.get("代码", ""))
                            if len(code) == 6 and code.isdigit():
                                mapping[code] = ind_name
                except Exception:
                    pass
                if (idx + 1) % 10 == 0:
                    print(f"  📊 行业进度: {idx + 1}/{len(industry_names)} | 已映射 {len(mapping)} 只股票")
                if (idx + 1) % 5 == 0:
                    time.sleep(0.3)

            if mapping:
                with open(cache_path, "w", encoding="utf-8") as f:
                    _json.dump({"_cache_time": time.time(), "data": mapping},
                               f, ensure_ascii=False, indent=2)
                for code6, ind_name in mapping.items():
                    if code6 not in self._industry_map:
                        self._industry_map[code6] = ind_name
                print(f"[TdxSectorMapper] 行业映射完成: {len(mapping)} 只股票 "
                      f"→ {len(set(mapping.values()))} 个行业 (已缓存)")
                return True

            print("[TdxSectorMapper] 行业映射: 未获取到数据 (可能网络问题)")
            return False

        except ImportError:
            print("[TdxSectorMapper] akshare未安装，跳过在线行业映射")
            return False
        except Exception as e:
            print(f"[TdxSectorMapper] AKShare行业映射失败: {e}")
            return False

    def load_industry_from_akshare(self) -> bool:
        """Fallback: 从AKShare/Sina构建行业映射

        当TDX本地T-code无法映射时使用。
        优先AKShare _ths接口，失败则使用Sina API（akshare_bridge方式）
        缓存到 _cache/industry_map.json
        """
        import json
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "industry_map.json")

        # 尝试从缓存加载
        try:
            if os.path.isfile(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                age = time.time() - cached.get("_cache_time", 0)
                if age < 86400 * 7:  # 7天有效期
                    self._industry_map = cached.get("data", {})
                    print(f"[TdxSectorMapper] AKShare缓存: {len(self._industry_map)} 条行业映射 "
                          f"(缓存于 {time.strftime('%Y-%m-%d', time.localtime(cached['_cache_time']))})")
                    return True
        except Exception:
            pass

        print("[TdxSectorMapper] T-code映射为空，从在线接口构建行业映射...")

        # 方案1: AKShare _ths 接口（列名: name, code）
        try:
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)

            import akshare as ak
            # 获取行业列表
            df = ak.stock_board_industry_name_ths()
            if df is not None and not df.empty:
                industries = []
                for _, row in df.iterrows():
                    name = str(row.get("name", ""))
                    code = str(row.get("code", ""))
                    if name:
                        industries.append((name, code))
                print(f"[TdxSectorMapper] AKShare: {len(industries)} 个行业板块")
        except Exception as e:
            print(f"[TdxSectorMapper] AKShare行业列表获取失败: {e}")
            industries = []

        # 方案2: _em接口被国内代理墙阻塞，直接走Sina API
        print("[TdxSectorMapper] 跳过_em(被代理墙), 直接走Sina API...")
        try:
            self._build_industry_from_sina()
            if self._industry_map:
                self._save_industry_cache(cache_path)
                return True
        except Exception as e:
            print(f"[TdxSectorMapper] Sina API失败: {e}")

        # 所有方案均失败
        print("[TdxSectorMapper] ⚠️ 所有在线行业映射方案均失败，concept数据可用")
        return False

    def _save_industry_cache(self, cache_path: str):
        """保存行业映射缓存"""
        import json
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "_cache_time": time.time(),
                    "data": self._industry_map,
                }, f, ensure_ascii=False)
            ind_set = set(self._industry_map.values())
            print(f"[TdxSectorMapper] 缓存已保存: {len(self._industry_map)} 只 → "
                  f"{len(ind_set)} 个行业")
        except Exception:
            pass

    def _build_industry_from_sina(self):
        """从新浪API构建行业映射（akshare_bridge的方式，避免代理问题）"""
        import requests as req
        import re as _re

        session = req.Session()
        session.trust_env = False

        # Step 1: 获取行业板块列表
        url = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
        params = {"param": "industry"}
        resp = session.get(url, params=params, timeout=15)
        resp.encoding = "gbk"

        board_pattern = r'"(\w+)":"([^"]+)"'
        boards = _re.findall(board_pattern, resp.text)
        print(f"[TdxSectorMapper] Sina: {len(boards)} 个行业板块")

        BATCH = 10
        for batch_start in range(0, len(boards), BATCH):
            batch = boards[batch_start:batch_start + BATCH]
            for key, val in batch:
                parts = val.split(",")
                sector_name = parts[1] if len(parts) >= 2 else val

                page = 1
                while True:
                    try:
                        url2 = ("https://vip.stock.finance.sina.com.cn/quotes_service/"
                                "api/json_v2.php/Market_Center.getHQNodeData")
                        params2 = {
                            "page": page, "num": 80, "sort": "symbol",
                            "asc": 1, "node": key, "_s_r_a": "auto",
                        }
                        resp2 = session.get(url2, params=params2, timeout=10)
                        data = resp2.json()
                        if not data:
                            break
                        for item in data:
                            code = item.get("code", "")
                            if len(code) == 6 and code.isdigit():
                                self._industry_map[code] = sector_name
                        page += 1
                    except Exception:
                        break

            done = min(batch_start + BATCH, len(boards))
            if self._industry_map:
                print(f"  Sina进度: {done}/{len(boards)}, 已映射 {len(self._industry_map)} 只")
            if done < len(boards):
                time.sleep(0.5)

        print(f"[TdxSectorMapper] Sina完成: {len(self._industry_map)} 条映射")
    def get_industry(self, code6: str) -> str:
        """获取股票所属行业"""
        return self._industry_map.get(code6, "")

    def get_concepts(self, code6: str) -> list[str]:
        """获取股票所属概念列表"""
        return self._stock_concepts.get(code6, [])

    def get_concept_stocks(self, concept_name: str) -> list[str]:
        """获取概念板块成分股"""
        return self._concept_map.get(concept_name, [])

    @property
    def industry_map(self) -> dict[str, str]:
        return self._industry_map

    @property
    def concept_map(self) -> dict[str, list[str]]:
        return self._concept_map


# ============================================================
# THS数据获取器
# ============================================================

class ThsSectorFetcher:
    """通过AKShare _ths接口获取同花顺行业/概念实时数据

    可用接口:
    - stock_board_industry_name_ths()   行业板块列表
    - stock_board_industry_summary_ths() 行业板块汇总
    - stock_board_industry_info_ths()   行业板块详情
    - stock_board_industry_index_ths()  行业板块指数
    - stock_board_concept_name_ths()    概念板块列表
    - stock_board_concept_summary_ths() 概念板块汇总
    - stock_board_concept_info_ths()    概念板块详情
    - stock_board_concept_index_ths()   概念板块指数
    """

    def __init__(self):
        self._ak = None

    def _get_ak(self):
        """懒加载akshare"""
        if self._ak is None:
            # 清除代理
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)
            import akshare as ak
            self._ak = ak
        return self._ak

    def get_industry_list(self) -> list[SectorStrength]:
        """获取同花顺行业板块列表（含涨跌幅等）

        Returns:
            行业板块强度列表
        """
        ak = self._get_ak()
        results = []

        try:
            df = ak.stock_board_industry_name_ths()
            if df is None or df.empty:
                return results

            for _, row in df.iterrows():
                name = str(row.get("板块", ""))
                code = str(row.get("代码", ""))

                # 解析涨跌幅
                change = 0.0
                change_str = str(row.get("涨跌幅", "0"))
                try:
                    change = float(change_str.replace("%", ""))
                except (ValueError, AttributeError):
                    pass

                if name:
                    results.append(SectorStrength(
                        name=name,
                        code=code,
                        sector_type="industry",
                        change_pct=change,
                    ))

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取行业板块失败: {e}")

        return results

    def get_concept_list(self) -> list[SectorStrength]:
        """获取同花顺概念板块列表（15s超时保护）"""
        ak = self._get_ak()
        results = []

        try:
            df = self._ak_with_timeout(lambda: ak.stock_board_concept_name_ths(), timeout=15)
            if df is None or df.empty:
                return results

            for _, row in df.iterrows():
                # stock_board_concept_name_ths 返回列: name, code（无涨跌幅）
                name = str(row.get("name", "") or row.get("板块", ""))

                change = 0.0
                change_str = str(row.get("涨跌幅", "0"))
                try:
                    change = float(change_str.replace("%", ""))
                except (ValueError, AttributeError):
                    pass

                if name:
                    results.append(SectorStrength(
                        name=name,
                        code=str(row.get("code", "") or row.get("代码", "")),
                        sector_type="concept",
                        change_pct=change,
                    ))

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取概念板块失败: {e}")

        return results

    def get_industry_detail(self, symbol: str) -> dict:
        """获取行业板块详情（成分股、净流入等）

        Args:
            symbol: 板块名称，如"半导体"
        """
        ak = self._get_ak()
        try:
            df = ak.stock_board_industry_info_ths(symbol=symbol)
            if df is None or df.empty:
                return {}

            result = {}
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("股票名称", ""))
                if code and len(code) == 6:
                    stocks.append({"code": code, "name": name})

            result["stocks"] = stocks
            result["stock_count"] = len(stocks)
            return result

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取行业详情失败({symbol}): {e}")
            return {}

    def get_concept_detail(self, symbol: str) -> dict:
        """获取概念板块详情"""
        ak = self._get_ak()
        try:
            df = ak.stock_board_concept_info_ths(symbol=symbol)
            if df is None or df.empty:
                return {}

            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("股票名称", ""))
                if code and len(code) == 6:
                    stocks.append({"code": code, "name": name})

            return {"stocks": stocks, "stock_count": len(stocks)}

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取概念详情失败({symbol}): {e}")
            return {}

    def get_industry_summary(self) -> list[SectorStrength]:
        """获取行业板块汇总（含净流入、换手等）

        Returns:
            含更多指标的板块列表
        """
        ak = self._get_ak()
        results = []

        try:
            df = ak.stock_board_industry_summary_ths()
            if df is None or df.empty:
                return results

            for _, row in df.iterrows():
                name = str(row.get("板块", ""))

                change = 0.0
                try:
                    change = float(str(row.get("涨跌幅", "0")).replace("%", ""))
                except (ValueError, AttributeError):
                    pass

                net_inflow = 0.0
                try:
                    net_inflow = float(str(row.get("净流入", "0")).replace("亿", ""))
                except (ValueError, AttributeError):
                    pass

                turnover = 0.0
                try:
                    turnover = float(str(row.get("换手率", "0")).replace("%", ""))
                except (ValueError, AttributeError):
                    pass

                up_ratio = 0.0
                try:
                    lead = str(row.get("领涨股", ""))
                    # 尝试解析上涨家数
                    up_str = str(row.get("上涨家数", "0"))
                    total_str = str(row.get("总家数", "0"))
                    up = int(up_str) if up_str.isdigit() else 0
                    total = int(total_str) if total_str.isdigit() else 1
                    up_ratio = up / total if total > 0 else 0
                except (ValueError, AttributeError):
                    pass

                if name:
                    results.append(SectorStrength(
                        name=name,
                        sector_type="industry",
                        change_pct=change,
                        net_inflow=net_inflow,
                        turnover=turnover,
                        up_ratio=up_ratio,
                    ))

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取行业汇总失败: {e}")

        return results

    def _ak_with_timeout(self, fn, timeout=15):
        """在独立线程中执行AkShare调用，超时则返回None"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        import traceback as _tb
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeout:
                print(f"[ThsSectorFetcher] AkShare调用超时({timeout}s)，已中断")
                return None
            except Exception as e:
                print(f"[ThsSectorFetcher] AkShare线程异常: {e}")
                _tb.print_exc()
                return None

    def get_concept_summary(self) -> list[SectorStrength]:
        """获取概念板块汇总（15s超时保护）"""
        ak = self._get_ak()
        results = []

        try:
            df = self._ak_with_timeout(lambda: ak.stock_board_concept_summary_ths(), timeout=30)
            if df is None or df.empty:
                return results

            for _, row in df.iterrows():
                name = str(row.get("板块", ""))

                change = 0.0
                try:
                    change = float(str(row.get("涨跌幅", "0")).replace("%", ""))
                except (ValueError, AttributeError):
                    pass

                net_inflow = 0.0
                try:
                    net_inflow = float(str(row.get("净流入", "0")).replace("亿", ""))
                except (ValueError, AttributeError):
                    pass

                if name:
                    results.append(SectorStrength(
                        name=name,
                        sector_type="concept",
                        change_pct=change,
                        net_inflow=net_inflow,
                    ))

        except Exception as e:
            print(f"[ThsSectorFetcher] 获取概念汇总失败: {e}")

        return results


# ============================================================
# 板块强度排名器
# ============================================================

class SectorRanker:
    """板块强度排名 + 轮动信号检测

    强度评分 = 涨跌幅(30%) + 净流入(20%) + 上涨家数占比(15%)
               + 换手率(10%) + 3日动量(15%) + 5日动量(10%)

    等级: S(>=80) | A(>=60) | B(>=40) | C(<40)

    轮动信号:
    - 加速上攻: 3d>0 且加速>0  (最强，适合追入)
    - 持续强势: 3d>0 且加速<=0 (热但可能见顶)
    - 触底反弹: 5d<0 且 3d>0   (最适合MA120抄底)
    - 弱势下行: 3d<0           (回避)
    """

    # 评分权重
    WEIGHTS = {
        "change_pct": 0.30,
        "net_inflow": 0.20,
        "up_ratio": 0.15,
        "turnover": 0.10,
        "momentum_3d": 0.15,
        "momentum_5d": 0.10,
    }

    def rank(self, sectors: list[SectorStrength]) -> list[SectorStrength]:
        """计算板块强度评分并排名

        Args:
            sectors: 板块列表（需要有基础数据）

        Returns:
            按强度降序排列的板块列表
        """
        if not sectors:
            return []

        # 归一化各指标到0-100
        changes = [s.change_pct for s in sectors if s.change_pct != 0]
        inflows = [s.net_inflow for s in sectors if s.net_inflow != 0]
        up_ratios = [s.up_ratio for s in sectors if s.up_ratio > 0]
        turnovers = [s.turnover for s in sectors if s.turnover > 0]

        def normalize(value, values, default=50):
            """将值归一化到0-100"""
            if not values:
                return default
            vmin = min(values)
            vmax = max(values)
            if vmax == vmin:
                return 50
            return max(0, min(100, (value - vmin) / (vmax - vmin) * 100))

        for s in sectors:
            score = 0.0
            score += normalize(s.change_pct, changes) * self.WEIGHTS["change_pct"]
            score += normalize(s.net_inflow, inflows) * self.WEIGHTS["net_inflow"]
            score += normalize(s.up_ratio, up_ratios, 50) * self.WEIGHTS["up_ratio"]
            score += normalize(s.turnover, turnovers, 50) * self.WEIGHTS["turnover"]

            # 动量（已有数据则直接用，否则从涨跌幅估算）
            mom_3d = s.momentum_3d if s.momentum_3d != 0 else s.change_pct
            mom_5d = s.momentum_5d if s.momentum_5d != 0 else s.change_pct

            mom_3d_list = [ss.momentum_3d or ss.change_pct for ss in sectors]
            mom_5d_list = [ss.momentum_5d or ss.change_pct for ss in sectors]

            score += normalize(mom_3d, mom_3d_list, 50) * self.WEIGHTS["momentum_3d"]
            score += normalize(mom_5d, mom_5d_list, 50) * self.WEIGHTS["momentum_5d"]

            s.strength_score = round(score, 1)

            # 评级
            if s.strength_score >= 80:
                s.grade = "S"
            elif s.strength_score >= 60:
                s.grade = "A"
            elif s.strength_score >= 40:
                s.grade = "B"
            else:
                s.grade = "C"

        # 降序排列
        sectors.sort(key=lambda s: s.strength_score, reverse=True)
        return sectors

    def detect_rotation(self, sectors: list[SectorStrength]) -> list[SectorStrength]:
        """检测轮动信号

        需要板块有 momentum_3d 和 momentum_5d 数据

        Args:
            sectors: 已计算强度的板块列表

        Returns:
            带轮动信号的板块列表
        """
        for s in sectors:
            mom_3d = s.momentum_3d if s.momentum_3d != 0 else s.change_pct
            mom_5d = s.momentum_5d if s.momentum_5d != 0 else s.change_pct

            if mom_3d > 0:
                # 3日动量为正
                acceleration = mom_3d - mom_5d  # 简化：3日vs5日
                if acceleration > 0:
                    s.rotation_signal = "加速上攻"
                else:
                    s.rotation_signal = "持续强势"
            elif mom_5d < 0 and mom_3d > 0:
                s.rotation_signal = "触底反弹"
            else:
                # 3日动量为负
                if mom_5d < 0:
                    s.rotation_signal = "弱势下行"
                else:
                    s.rotation_signal = "震荡整理"

        return sectors

    def detect_rotation_with_history(self, sector_name: str,
                                      fetcher: ThsSectorFetcher) -> str:
        """通过THS指数历史数据检测轮动信号（更精确）

        Args:
            sector_name: 板块名称
            fetcher: 数据获取器

        Returns:
            轮动信号文本
        """
        ak = fetcher._get_ak()
        try:
            # 获取近5日指数数据
            df = ak.stock_board_industry_index_ths(
                symbol=sector_name, start_date="", end_date=""
            )
            if df is None or len(df) < 5:
                return "数据不足"

            # 计算动量
            closes = df.iloc[-5:]["收盘价"].values if "收盘价" in df.columns else []
            if len(closes) < 5:
                return "数据不足"

            mom_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
            mom_5d = (closes[-1] - closes[0]) / closes[0] * 100

            if mom_3d > 0:
                acceleration = mom_3d - mom_5d
                if acceleration > 0:
                    return "加速上攻"
                return "持续强势"
            elif mom_5d < 0 and mom_3d > 0:
                return "触底反弹"
            else:
                return "弱势下行"

        except Exception as e:
            return "检测失败"


# ============================================================
# 便捷函数
# ============================================================

_mapper: TdxSectorMapper | None = None

def get_mapper() -> TdxSectorMapper:
    """获取全局TDX映射器单例"""
    global _mapper
    if _mapper is None:
        _mapper = TdxSectorMapper()
        _mapper.load_all()
    return _mapper


def get_hot_sectors(sector_type: str = "industry",
                    top_n: int = 20) -> list[SectorStrength]:
    """获取热门板块排名（一键调用）

    Args:
        sector_type: industry / concept
        top_n: 返回前N个

    Returns:
        按强度降序的板块列表
    """
    fetcher = ThsSectorFetcher()
    ranker = SectorRanker()

    if sector_type == "industry":
        sectors = fetcher.get_industry_summary()
        if not sectors:
            sectors = fetcher.get_industry_list()
    else:
        sectors = fetcher.get_concept_summary()
        if not sectors:
            sectors = fetcher.get_concept_list()

    if sectors:
        sectors = ranker.rank(sectors)

    return sectors[:top_n]
