#!/usr/bin/env python
"""TDX Sector Index Reader — 从本地通达信 .day 文件秒读板块指数日线

Usage:
    from tdx_sector_reader import TdxSectorReader
    reader = TdxSectorReader()
    momentum = reader.get_momentum("半导体")  # → {change_today, momentum_3d, momentum_5d}
"""
import os, sys
from typing import Dict, Optional
import pandas as pd
from pytdx.reader import TdxDailyBarReader

# ── 880xxx → 中文名映射 ────────────────────────────
# 从 tdxzs3.cfg 解析（含行业+概念+地域）

class TdxSectorReader:
    """读取TDX本地板块指数数据"""
    
    TDX_ROOT = r"D:\new_tdx_test"
    
    def __init__(self, tdx_root: str = None):
        self.tdx_root = tdx_root or self.TDX_ROOT
        self.vipdoc = os.path.join(self.tdx_root, "vipdoc")
        self._reader = None
        self._code_to_name: Dict[str, str] = {}
        self._name_to_code: Dict[str, str] = {}
        self._loaded = False
    
    @property
    def reader(self):
        if self._reader is None:
            self._reader = TdxDailyBarReader()
            self._reader.vipdoc_path = self.vipdoc
        return self._reader
    
    def load_sector_map(self) -> Dict[str, str]:
        """加载板块代码→名称映射 (从 tdxzs3.cfg)"""
        if self._loaded:
            return self._code_to_name
        
        # Parse tdxzs3.cfg (more complete than tdxzs.cfg)
        zs_path = os.path.join(self.tdx_root, "T0002", "hq_cache", "tdxzs3.cfg")
        if not os.path.isfile(zs_path):
            zs_path = os.path.join(self.tdx_root, "T0002", "hq_cache", "tdxzs.cfg")
        
        if not os.path.isfile(zs_path):
            print("[TdxSectorReader] 未找到板块定义文件")
            return {}
        
        count = 0
        with open(zs_path, "r", encoding="gbk", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                code = parts[1].strip() if len(parts) > 1 else ""
                # 只取 880xxx 行业/概念板块指数
                if code.startswith("88") and len(code) == 6 and code[2:].isdigit():
                    self._code_to_name[code] = name
                    # 可能有同名板块用不同代码（如细分vs汇总），保留第一个
                    if name not in self._name_to_code:
                        self._name_to_code[name] = code
                    count += 1
        
        self._loaded = True
        print(f"[TdxSectorReader] 加载 {count} 个板块映射")
        return self._code_to_name
    
    def get_code(self, name: str) -> Optional[str]:
        """根据中文名获取TDX板块代码"""
        if not self._loaded:
            self.load_sector_map()
        # 精确匹配
        if name in self._name_to_code:
            return self._name_to_code[name]
        # 模糊匹配（含有关键词即匹配）
        for n, c in self._name_to_code.items():
            if name in n or n in name:
                return c
        return None
    
    def get_df(self, code: str) -> Optional[pd.DataFrame]:
        """读取板块日线数据"""
        try:
            return self.reader.get_df_by_code(code, exchange="sh")
        except Exception:
            return None
    
    def get_momentum(self, name_or_code: str) -> Dict:
        """计算板块动量指标
        
        Returns:
            {close_today, change_pct, momentum_3d, momentum_5d, 
             high_3d, low_5d, volume_ratio}
        """
        # 判断是代码还是名称
        if name_or_code.startswith("88") and len(name_or_code) == 6:
            code = name_or_code
        else:
            code = self.get_code(name_or_code)
        
        if not code:
            return {}
        
        df = self.get_df(code)
        if df is None or len(df) < 6:
            return {}
        
        df = df.tail(10)  # 最近10天足够
        
        try:
            close_today = float(df["close"].iloc[-1])
            close_yesterday = float(df["close"].iloc[-2])
            
            # 今日涨跌幅（相对昨日）
            change_pct = round((close_today - close_yesterday) / close_yesterday * 100, 2)
            
            # 3日动量（3个交易日前到今天）
            if len(df) >= 4:
                close_3d_ago = float(df["close"].iloc[-4])
                momentum_3d = round((close_today - close_3d_ago) / close_3d_ago * 100, 2)
            else:
                momentum_3d = 0.0
            
            # 5日动量
            if len(df) >= 6:
                close_5d_ago = float(df["close"].iloc[-6])
                momentum_5d = round((close_today - close_5d_ago) / close_5d_ago * 100, 2)
            else:
                momentum_5d = 0.0
            
            # 3日最高
            high_3d = round(float(df["high"].iloc[-3:].max()), 2)
            
            # 5日最低
            low_5d = round(float(df["low"].iloc[-5:].min()), 2)
            
            # 量比（近日均量 / 5日均量）
            vol_recent = float(df["volume"].iloc[-1])
            vol_5d_avg = float(df["volume"].iloc[-6:-1].mean()) if len(df) >= 6 else vol_recent
            volume_ratio = round(vol_recent / vol_5d_avg, 2) if vol_5d_avg > 0 else 1.0
            
            return {
                "close": close_today,
                "change_pct": change_pct,
                "momentum_3d": momentum_3d,
                "momentum_5d": momentum_5d,
                "high_3d": high_3d,
                "low_5d": low_5d,
                "volume_ratio": volume_ratio,
            }
        except (IndexError, KeyError, TypeError):
            return {}
    
    def get_all_sectors(self) -> pd.DataFrame:
        """批量读取所有板块最新行情"""
        if not self._loaded:
            self.load_sector_map()
        
        rows = []
        for code, name in self._code_to_name.items():
            mom = self.get_momentum(code)
            if mom:
                rows.append({
                    "code": code,
                    "name": name,
                    **mom,
                })
        
        return pd.DataFrame(rows)


# ── Quick test ──────────────────────────────────────
if __name__ == "__main__":
    reader = TdxSectorReader()
    
    # Test single sector
    print("=== 单板块测试 ===")
    for name in ["半导体", "元器件", "银行", "通信设备", "国防军工", "IT服务"]:
        mom = reader.get_momentum(name)
        code = reader.get_code(name)
        if mom:
            print(f"{name}({code}): "
                  f"今日{mom['change_pct']:+.2f}% | "
                  f"3日{mom['momentum_3d']:+.2f}% | "
                  f"5日{mom['momentum_5d']:+.2f}% | "
                  f"量比{mom['volume_ratio']:.2f}")
        else:
            print(f"{name}: 未找到映射")
    
    # Batch test
    print(f"\n=== 批量板块行情 ===")
    t0 = __import__('time').time()
    df = reader.get_all_sectors()
    print(f"读取 {len(df)} 个板块 (耗时 {__import__('time').time()-t0:.2f}s)")
    
    if not df.empty:
        # Sort by change_pct descending
        df_sorted = df.sort_values("change_pct", ascending=False)
        print("\n涨幅前10:")
        for _, row in df_sorted.head(10).iterrows():
            print(f"  {row['name']}({row['code']}): "
                  f"{row['change_pct']:+.2f}% | "
                  f"3日{row['momentum_3d']:+.2f}% | "
                  f"5日{row['momentum_5d']:+.2f}%")
