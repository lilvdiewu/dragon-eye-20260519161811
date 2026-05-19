"""
TDX 行情统计文件解析器 (tdxstat.cfg / tdxstat2.cfg)

文件格式：Pipe分隔，无表头。
tdxstat.cfg: 35 个字段 (综合统计)
tdxstat2.cfg: 21 个字段 (资金流向统计)

字段推断（基于样本数据验证）:
  tdxstat.cfg:
    [0] 市场 (0=深圳, 1=上海)
    [1] 股票代码
    [2] 量比
    [3] 委比/其他
    [4] 日期 (YYYYMMDD)
    [5] 排名分
    [6] 涨幅% (当日)
    [7] 涨速% (5分钟)
    [8] 换手率%
    [9] 市盈率(动)
    [10] 市净率/每股收益
    [11] 流通市值(万元)
    [14] 总市值(万元)
    [15] 成交量(手)
    [22] 成交额(元)
    [23] 上涨家数(板块)
    [24] 总成交额(板块)
    [17]-[21] 阶段涨跌幅(20日/60日/120日/250日/年初至今)
    [27]-[30] 阶段涨跌幅(另一组周期)
    
  tdxstat2.cfg:
    [0] 市场
    [1] 股票代码
    [2] 日期
    [3]+[5]+[7] 资金流入/流出/净额
    [11] 资金流向%
    [14]+[16]+[17] 大单/中单/小单
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TdxStockStat:
    """单只股票的行情统计"""
    market: int
    code: str
    date: str
    
    # 基础行情
    change_pct: float = 0.0        # 涨幅%
    speed_pct: float = 0.0          # 涨速%
    turnover: float = 0.0           # 换手率%
    volume_ratio: float = 0.0       # 量比
    
    # 估值
    pe: float = 0.0                 # 市盈率
    pb: float = 0.0                 # 市净率
    
    # 市值 (万元)
    float_mv: float = 0.0           # 流通市值
    total_mv: float = 0.0           # 总市值
    
    # 成交
    volume: float = 0.0             # 成交量(手)
    amount: float = 0.0             # 成交额
    
    # 阶段涨跌幅
    chg_20d: float = 0.0
    chg_60d: float = 0.0
    chg_120d: float = 0.0
    chg_250d: float = 0.0
    chg_ytd: float = 0.0
    
    # 排名
    rank_score: int = 0
    
    # 板块相关
    sector_up_count: int = 0        # 板块上涨家数
    sector_amount: float = 0.0      # 板块总成交额
    
    # 原始字段 (备用)
    raw: list = field(default_factory=list)


@dataclass  
class TdxStockStat2:
    """资金流向统计"""
    market: int
    code: str
    date: str
    
    flow_in: float = 0.0            # 主力流入
    flow_out: float = 0.0           # 主力流出
    flow_net: float = 0.0           # 主力净额
    flow_pct: float = 0.0           # 资金流向占比%
    
    big_order: float = 0.0          # 大单净额
    mid_order: float = 0.0          # 中单净额
    small_order: float = 0.0        # 小单净额
    
    chg_20d: float = 0.0
    chg_60d: float = 0.0
    
    raw: list = field(default_factory=list)


class TdxStatReader:
    """TDX 行情统计文件读取器"""
    
    TDX_ROOT = "D:/new_tdx_test"
    
    def __init__(self, tdx_root: str | None = None):
        self.tdx_root = tdx_root or self.TDX_ROOT
        self._stats: dict[str, TdxStockStat] = {}
        self._stats2: dict[str, TdxStockStat2] = {}
        self._loaded = False
    
    @property
    def cache_dir(self) -> str:
        return os.path.join(self.tdx_root, "T0002", "hq_cache")
    
    def load(self) -> bool:
        """加载全部统计"""
        if self._loaded:
            return True
        
        ok1 = self._load_stat()
        ok2 = self._load_stat2()
        self._loaded = ok1 or ok2
        return self._loaded
    
    def _load_stat(self) -> bool:
        """加载 tdxstat.cfg (35字段)"""
        path = os.path.join(self.cache_dir, "tdxstat.cfg")
        if not os.path.isfile(path):
            return False
        
        count = 0
        try:
            with open(path, "r", encoding="gbk", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 10:
                        continue
                    
                    try:
                        stat = self._parse_stat_line(parts)
                        if stat and stat.code:
                            self._stats[stat.code] = stat
                            count += 1
                    except (ValueError, IndexError):
                        continue
            
            if count > 0:
                print(f"[TdxStatReader] tdxstat.cfg: {count} 只股票统计已加载")
            return count > 0
        except Exception as e:
            print(f"[TdxStatReader] tdxstat.cfg 加载失败: {e}")
            return False
    
    def _parse_stat_line(self, parts: list) -> Optional[TdxStockStat]:
        """解析单行统计"""
        def _f(idx, default=0.0):
            try:
                v = parts[idx].strip()
                return float(v) if v else default
            except (ValueError, IndexError):
                return default
        
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code or len(code) != 6 or not code.isdigit():
            return None
        
        market = int(parts[0]) if parts[0].strip() else 0
        
        return TdxStockStat(
            market=market,
            code=code,
            date=parts[4].strip() if len(parts) > 4 else "",
            
            # 基础行情
            change_pct=_f(6),
            speed_pct=_f(7),
            turnover=_f(8),       # 换手率
            volume_ratio=_f(2),    # 量比
            
            # 估值
            pe=_f(9),
            pb=_f(10) if _f(10) > 0 else 0,  # PB只保留正值
            
            # 市值 (万元)
            float_mv=_f(11),
            total_mv=_f(14) if len(parts) > 14 else _f(11),
            
            # 成交
            volume=_f(15) if len(parts) > 15 else 0,
            amount=_f(22) if len(parts) > 22 else 0,
            
            # 阶段涨跌幅
            chg_20d=_f(17) if len(parts) > 17 else 0,
            chg_60d=_f(18) if len(parts) > 18 else 0,
            chg_120d=_f(19) if len(parts) > 19 else 0,
            chg_250d=_f(20) if len(parts) > 20 else 0,
            chg_ytd=_f(21) if len(parts) > 21 else 0,
            
            # 排名
            rank_score=int(_f(5, 0)),
            
            # 板块
            sector_up_count=int(_f(23, 0)) if len(parts) > 23 else 0,
            sector_amount=_f(24, 0) if len(parts) > 24 else 0,
            
            raw=list(parts),
        )
    
    def _load_stat2(self) -> bool:
        """加载 tdxstat2.cfg (21字段, 资金流向)"""
        path = os.path.join(self.cache_dir, "tdxstat2.cfg")
        if not os.path.isfile(path):
            return False
        
        count = 0
        try:
            with open(path, "r", encoding="gbk", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 10:
                        continue
                    
                    try:
                        stat = self._parse_stat2_line(parts)
                        if stat and stat.code:
                            self._stats2[stat.code] = stat
                            count += 1
                    except (ValueError, IndexError):
                        continue
            
            if count > 0:
                print(f"[TdxStatReader] tdxstat2.cfg: {count} 只资金流向已加载")
            return count > 0
        except Exception as e:
            print(f"[TdxStatReader] tdxstat2.cfg 加载失败: {e}")
            return False
    
    def _parse_stat2_line(self, parts: list) -> Optional[TdxStockStat2]:
        """解析资金流向行"""
        def _f(idx, default=0.0):
            try:
                v = parts[idx].strip()
                return float(v) if v else default
            except (ValueError, IndexError):
                return default
        
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code or len(code) != 6 or not code.isdigit():
            return None
        
        market = int(parts[0]) if parts[0].strip() else 0
        
        return TdxStockStat2(
            market=market,
            code=code,
            date=parts[2].strip() if len(parts) > 2 else "",
            
            flow_in=_f(3),
            flow_out=_f(5) if len(parts) > 5 else _f(7),
            flow_net=_f(7) if len(parts) > 7 else 0,
            flow_pct=_f(11) if len(parts) > 11 else 0,
            
            big_order=_f(14) if len(parts) > 14 else 0,
            mid_order=_f(16) if len(parts) > 16 else 0,
            small_order=_f(17) if len(parts) > 17 else 0,
            
            chg_20d=_f(19) if len(parts) > 19 else 0,
            chg_60d=_f(20) if len(parts) > 20 else 0,
            
            raw=list(parts),
        )
    
    def get_stat(self, code: str) -> Optional[TdxStockStat]:
        """获取单只股票统计"""
        self.load()
        return self._stats.get(code)
    
    def get_stat2(self, code: str) -> Optional[TdxStockStat2]:
        """获取单只股票资金流向"""
        self.load()
        return self._stats2.get(code)
    
    def get_top_by_change(self, n: int = 50) -> list[TdxStockStat]:
        """涨幅前N"""
        self.load()
        stats = [s for s in self._stats.values() if s.change_pct > 0]
        stats.sort(key=lambda s: s.change_pct, reverse=True)
        return stats[:n]
    
    def get_top_by_turnover(self, n: int = 50) -> list[TdxStockStat]:
        """换手率前N"""
        self.load()
        stats = [s for s in self._stats.values() if s.turnover > 0]
        stats.sort(key=lambda s: s.turnover, reverse=True)
        return stats[:n]
    
    def get_top_by_net_flow(self, n: int = 50) -> list[TdxStockStat2]:
        """资金净流入前N"""
        self.load()
        stats = [s for s in self._stats2.values() if s.flow_net > 0]
        stats.sort(key=lambda s: s.flow_net, reverse=True)
        return stats[:n]
    
    def get_stocks_by_sector_rank(self, min_up: int = 5) -> list[dict]:
        """板块上涨家数最多的股票（板块效应强的）"""
        self.load()
        results = []
        for stat in self._stats.values():
            if stat.sector_up_count >= min_up:
                results.append({
                    "code": stat.code,
                    "sector_up": stat.sector_up_count,
                    "change_pct": stat.change_pct,
                    "pe": stat.pe,
                    "turnover": stat.turnover,
                })
        results.sort(key=lambda x: x["sector_up"], reverse=True)
        return results[:100]


# 模块级单例
_reader: Optional[TdxStatReader] = None

def get_stat_reader() -> TdxStatReader:
    global _reader
    if _reader is None:
        _reader = TdxStatReader()
        _reader.load()
    return _reader


if __name__ == "__main__":
    r = get_stat_reader()
    print(f"\n-- 涨幅TOP10 --")
    for s in r.get_top_by_change(10):
        print(f"  {s.code}: {s.change_pct:+.2f}% PE={s.pe:.1f} 换手={s.turnover:.2f}% 市值={s.total_mv/10000:.1f}亿")
    
    print(f"\n-- 换手率TOP10 --")
    for s in r.get_top_by_turnover(10):
        print(f"  {s.code}: 换手={s.turnover:.2f}% 涨幅={s.change_pct:+.2f}%")
    
    print(f"\n-- 资金净流入TOP10 --")
    for s in r.get_top_by_net_flow(10):
        print(f"  {s.code}: 净流入={s.flow_net:.0f}万 占比={s.flow_pct:.2f}%")
