# 龙瞳 DragonEye — 股票Skills & 通达信连接参考手册

_最后更新: 2026-05-19_

---

## 一、已安装的股票/金融相关 Skills（34个）

### A股专用（仅沪深A股，最常用）

| # | Skill名称 | 简介 | 关键能力 | 推荐场景 |
|---|-----------|------|----------|----------|
| 1 | `a-share-stock-dossier` | 分析师级A股个股报告 | 产业逻辑+交易逻辑双层分析; 持仓复盘; 盘前执行单; 组合分层(A/B/C) | 个股深度研究 |
| 2 | `a-stock-analysis` | A股实时行情与分时量能 | 东方财富/新浪接口; 分时成交量; 主力动向(抢筹/出货); 涨停封单 | 盘中实时监控 |
| 3 | `a-stock-trading-assistant` | A股智能交易助手 | 实时行情; 大盘情绪; 热点板块; 交易策略; 仅处理6/00/30/68开头 | 日常交易辅助 |
| 4 | `astock-research` | A股深度投研(五维一体) | 基本面+资金面+技术面+情绪面+消息面; 同花顺/萝卜投研体系 | 深度投研 |
| 5 | `akshare-stock` | A股量化数据(AKShare) | 个股实时行情; 历史K线; 财务数据; 板块信息; **龙瞳主要数据源** | 龙瞳数据接口 |
| 6 | `akshare-finance` | AKShare财经数据(全) | 股票/期货/期权/基金/外汇/债券/指数/加密货币 | 全品类金融数据 |
| 7 | `stock-board` | A股涨停板筛选 | 涨停板; 接近涨停(≥7%); 昨日涨停今表现; 板块涨停统计 | 打板/涨停分析 |
| 8 | `stock-monitor-skill` | 智能股票监控预警 | 7大预警规则(成本%/均线/RSI/成交量/缺口/动态止盈); 分级预警; **红涨绿跌** | 自选股预警 |
| 9 | `stock-select` | AI驱动智能选股 | 自然语言选股(类似问财); Level2主力资金; 集合竞价异动; AI辅助下单 | 智能选股 |
| 10 | `redquant-ashare-quant` | A股只读投研(RedQuant MCP) | 46个只读工具; 行情技术分析; 财务报表; 指数行业; 量化因子选股 | 量化因子研究 |
| 11 | `tushare-stock-skill` | A股Tushare专用 | 股票数据获取; 个股分析; 需TUSHARE_TOKEN | Tushare数据源 |

### 数据源/接口类

| # | Skill名称 | 简介 | 数据源 | 是否需Key |
|---|-----------|------|--------|-----------|
| 12 | `ths-financial-data` | 同花顺金融数据(thsdk) | thsdk库; 实时行情; 中文名查询; 键盘缩写; 资金流向; 日K线 | 需安装thsdk |
| 13 | `ths-advanced-analysis` | 同花顺高级分析(thsdk) | 分钟K线(1m~120m); 板块/指数行情; 盘口深度; 大单流向; 集合竞价 | 需安装thsdk |
| 14 | `tushare-finance` | Tushare Pro(220+接口) | A股/港股/美股/基金/期货/债券 | 需TUSHARE_TOKEN |
| 15 | `tushare` | Tushare Pro通用 | A股+期货; 实时/历史; 宏观指标 | 需TUSHARE_TOKEN |
| 16 | `finnhub` | Finnhub API实时数据 | 美股为主; 实时报价; 公司新闻; 财务报表 | 需API Key |
| 17 | `yahoo-finance` | Yahoo Finance CLI | yfinance库; 股价/基本面/财报/期权/分红 | 无需Key |
| 18 | `finance` | 股票/ETF/外汇/加密追踪 | yfinance; 最新报价; 本地自选股; 缓存 | 无需Key |
| 19 | `financial-data` | 跨资产金融数据(MarketPulse) | AIsa API; 实时/历史行情; 内部交易; 分析师估计 | 需API Key |
| 20 | `NeoData金融搜索服务` | 自然语言金融搜索 | 股票/基金/指数/板块/宏观/外汇; 即问即答 | 插件内置 |
| 21 | `mx-macro-data` | 宏观经济数据(东方财富) | 国民经济核算/价格指数/货币金融/财政/外贸/就业 | 无需Key |

### 分析策略类

| # | Skill名称 | 简介 | 核心方法 |
|---|-----------|------|----------|
| 22 | `fundamental-stock-analysis` | 基本面股权分析 | 质量/安全/现金流/估值四维评分; 行业调整; 同行比较 |
| 23 | `technical-analyst` | 技术分析师(周线) | 趋势识别; 支撑/阻力; 均线关系; 成交量形态; 概率情景 |
| 24 | `stock-analyst` | 股票综合分析 | 宏观+行业景气度; 财务健康度(ROE); 技术指标; 量化+行为金融 |
| 25 | `stock-analysis-23` | 23个通达信技术指标分析 | MACD/KDJ/RSI/布林带/筹码分布/资金流向; 妖股挖掘 |
| 26 | `china-stock-analysis` | 中国股票分析(A股+港股) | A股沪深; 港股; Web搜索当前价格; 买卖建议 |
| 27 | `股票综合分析器` | 全球股票综合分析(东方财富) | A股/港股/美股; 基本面+新闻+资金三维分析; HTML报告 |
| 28 | `backtest-expert` | 量化回测专家 | 回测方法论; 参数鲁棒性; 滑点建模; 过拟合/前视偏差检测 |
| 29 | `trade-signal-ttx` | 实时交易信号(Terminal-X) | Buy/Sell/Hold建议; 价格目标; 全球市场+ETF+期权 |
| 30 | `stock-predictor` | 智能股票预测(集成学习) | LightGBM+XGBoost+RF; 次日涨5%+预测; 23技术因子; 智能回测 |
| 31 | `stock-market-pro` | Yahoo Finance专业版 | 实时报价+基本面; ASCII趋势; 高分辨率图表(RSI/MACD/BB/VWAP/ATR) |

### 监控/预警类

| # | Skill名称 | 简介 | 核心功能 |
|---|-----------|------|----------|
| 32 | `stock-watcher` | 自选股管理与行情追踪 | 添加/删除自选股; 行情概览; 同花顺数据源 |
| 33 | `宏观数据监控` | 每日宏观数据监控推送 | Trading Economics/FRED/国家统计局/央行; cron每晚10点 |
| 34 | `财报追踪` | AI驱动A股/美股财报追踪 | 财报日历扫描; 业绩预告/快报/正式财报; 超预期判断 |

### 重复/副本（可忽略）
- `new-akshare-stock` = `akshare-stock` 副本
- `stock-analysis-lianghua` = `stock-analyst` 副本
- `financial-data` = `finance` 中的 MarketPulse 同内容

---

## 二、龙瞳项目最近使用的 Skills

| 日期 | 调用的Skill | 用途 | 结果 |
|------|------------|------|------|
| 05-18 | `akshare-stock` | 龙瞳主要数据源，获取A股实时行情、历史K线、板块数据 | ✅ 核心数据源，已集成到`sector/ths_sector.py` |
| 05-18 | `akshare-finance` | 验证AKShare `_ths`系列接口可用性 | ✅ 确认42个同花顺接口可用 |
| 05-17 | `a-stock-analysis` | 探索A股实时行情获取方式 | ✅ 确认东方财富/新浪接口可用 |
| 05-17 | (无skill) | 通达信本地数据直接Python读取 | ✅ 自行解析TDX二进制/文本文件 |

> **说明**: 龙瞳项目主要依赖 **直接Python代码读取TDX本地文件** + **AKShare库调用**，而非通过Skill间接调用。Skill更多用于探索/验证阶段。

---

## 三、通达信(TDX)本地数据连接方法

### 3.1 TDX安装路径

```
D:/new_tdx_test/
├── T0002/
│   ├── hq_cache/
│   │   ├── tdxhy.cfg           # 股票→行业/概念代码映射
│   │   └── infoharbor_block.dat  # 概念板块→成分股(二进制)
│   └── cloud_cfg/
│       └── hy_tree.xml          # 行业树(GBK编码XML)
├── vipdoc/
│   ├── sh/                      # 沪市日线数据 .day 文件
│   │   └── sh600xxx.day        # 每只股票一个文件
│   └── sz/                      # 深市日线数据 .day 文件
│       └── sz000xxx.day
└── T0002/hq_cache/
    └── *.lc1/*.lc5              # 分钟线数据
```

### 3.2 tdxhy.cfg 格式与解析

```
格式: 市场代码|6位股票代码|T_code|||X_code
示例: 1|600519|T01|||X001
```

| 字段 | 位置 | 说明 |
|------|------|------|
| 市场代码 | parts[0] | 1=沪市, 0=深市 |
| 6位股票代码 | parts[1] | 如 600519 |
| T_code | parts[2] | 申万行业代码(4位), 如 T01, T1206 |
| 空字段 | parts[3-4] | 废弃 |
| X_code | parts[5] | 概念板块代码(4位), 如 X001, X0234 |

**Python解析代码:**
```python
with open("D:/new_tdx_test/T0002/hq_cache/tdxhy.cfg", "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        code6 = parts[1]       # 股票代码
        t_code = parts[2]      # 行业代码
        x_code = parts[5] if len(parts) > 5 else ""  # 概念代码
```

### 3.3 hy_tree.xml 格式与解析

```xml
<!-- GBK编码的XML，节点结构 -->
<node caption="行业名称" blockid="X1001" ...>
  <node caption="子行业" blockid="X100101" .../>
</node>
```

**Python解析代码:**
```python
import xml.etree.ElementTree as ET

# 注意：GBK编码，必须先解码再用ET解析
with open("D:/new_tdx_test/T0002/cloud_cfg/hy_tree.xml", "rb") as f:
    raw = f.read()
text = raw.decode("gbk", errors="replace")
root = ET.fromstring(text)

code_to_name = {}
for node in root.iter():
    caption = node.get("caption", "")
    blockid = node.get("blockid", "")
    if caption and blockid:
        code_to_name[blockid] = caption
```

**⚠️ 已修复 (2026-05-19)**: hy_tree.xml中只有X前缀的blockid（约470个概念），**没有T前缀的blockid**（行业代码无法从XML映射中文名）。

**修复方案**: 不再依赖 hy_tree.xml 做T-code映射。改为使用AKShare的 `stock_board_industry_name_ths()` 获取行业列表 + `stock_board_industry_cons_em()` 获取成分股，构建反向映射 stock→industry。结果缓存到 `_cache/stock_sectors.json`（由 akshare_bridge 构建，5588只股票→84个行业）。加载优先级：`_cache/stock_sectors.json` → `_cache/industry_map.json` → AKShare在线。

### 3.3b infoharbor_block.dat 格式与解析 (已修复 2026-05-19)

**格式: 文本文件**（不是二进制！）

```
#GN_<概念名>,<参数1>,<参数2>,<起始日期>,<结束日期>,,\n<市场>#<代码>,<市场>#<代码>,...\r\n
```

- 每行以 `#GN_` 开头，后跟GBK编码的概念名和逗号分隔的股票列表
- 市场代码: 0=深市, 1=沪市, 2=北交所
- 股票代码格式: `0#000408` (深市) 或 `1#600000` (沪市)
- 通常269个概念板块，约5.5万条股票映射

**Python解析代码:**
```python
import re

with open("D:/new_tdx_test/T0002/hq_cache/infoharbor_block.dat", "rb") as f:
    raw = f.read()
text = raw.decode("gbk", errors="replace")

concept_map = {}
for block in text.split("#GN_"):
    if not block.strip():
        continue
    lines = block.split("\n")
    concept_name = lines[0].split(",")[0].strip()
    if not concept_name or len(concept_name) < 2:
        continue
    codes = re.findall(r'[01]#(\d{6})', block)
    if codes:
        concept_map[concept_name] = list(dict.fromkeys(codes))  # 去重保序
```

### 3.4 日线数据(.day文件)读取

每个`.day`文件为二进制格式，每条记录32字节：

```
字段          | 偏移 | 类型     | 说明
-------------|------|---------|------
日期          | 0    | int32   | YYYYMMDD
开盘价*100    | 4    | int32   | 实际价格 = 值 / 100
最高价*100    | 8    | int32   |
最低价*100    | 12   | int32   |
收盘价*100    | 16   | int32   |
成交额(元)   | 20   | float32 |
成交量(手)   | 24   | int32   |
保留          | 28   | int32   |
```

**Python解析代码:**
```python
import struct

def read_tdx_day(filepath):
    """读取通达信日线数据"""
    records = []
    with open(filepath, "rb") as f:
        data = f.read()
    record_size = 32
    for i in range(0, len(data), record_size):
        chunk = data[i:i+record_size]
        if len(chunk) < record_size:
            break
        date_int, o, h, l, c, amount, vol, _ = struct.unpack("<IIIIIfII", chunk)
        records.append({
            "date": str(date_int),
            "open": o / 100.0,
            "high": h / 100.0,
            "low": l / 100.0,
            "close": c / 100.0,
            "amount": amount,
            "volume": vol,
        })
    return records

# 使用示例（沪市600519）
data = read_tdx_day("D:/new_tdx_test/vipdoc/sh/sh600519.day")
```

### 3.5 分钟线数据(.lc1/.lc5)读取

格式类似日线但记录结构不同（每条32字节）：

```
字段          | 偏移 | 类型     | 说明
-------------|------|---------|------
日期时间      | 0    | int32   | HHMM*10000 + MMDD
开盘价*100    | 4    | int32   |
最高价*100    | 8    | int32   |
最低价*100    | 12   | int32   |
收盘价*100    | 16   | int32   |
成交额        | 20   | float32 |
成交量(手)   | 24   | int32   |
保留          | 28   | int32   |
```

### 3.6 实时行情获取（AKShare）

龙瞳使用的AKShare核心函数：

```python
import akshare as ak

# 1. 沪深A股实时行情（替代被墙的_em接口）
df = ak.stock_zh_a_spot_em()  # 全市场实时行情

# 2. 同花顺行业板块数据
df = ak.stock_board_industry_name_em()   # 行业板块列表
df = ak.stock_board_industry_cons_em(symbol="白酒")  # 行业成分股
df = ak.stock_board_industry_summary_em()  # 行业汇总

# 3. 同花顺概念板块数据
df = ak.stock_board_concept_name_em()    # 概念板块列表
df = ak.stock_board_concept_cons_em(symbol="人工智能")  # 概念成分股

# 4. 个股历史K线
df = ak.stock_zh_a_hist(symbol="600519", period="daily",
                         start_date="20250101", end_date="20260519")
```

> **重要**: `_em` 后缀接口（东方财富）在国内需代理，可能被墙。`_ths` 后缀（同花顺）通常可用。`stock_zh_a_spot_em()` 是实时行情的稳定接口。

### 3.7 龙瞳双数据源架构

```
┌─────────────────────────────────────────────┐
│               龙瞳 DragonEye                  │
├─────────────────────────────────────────────┤
│                                              │
│  数据源1: TDX本地文件 (零延迟, 静态)           │
│  ├── tdxhy.cfg → 股票→行业/概念映射            │
│  ├── hy_tree.xml → 行业树+代码→名称           │
│  ├── .day文件 → 日线OHLCV                     │
│  └── .lc1/.lc5 → 分钟线                       │
│                                              │
│  数据源2: AKShare在线 (实时, ~3s延迟)          │
│  ├── stock_zh_a_spot_em() → 实时行情          │
│  ├── stock_board_*_ths() → 同花顺板块数据     │
│  └── stock_zh_a_hist() → 历史K线              │
│                                              │
│  融合策略:                                    │
│  ├── TDX本地 = 历史数据 + 行业映射(基础)       │
│  └── AKShare = 实时行情 + 板块数据(增量)       │
│                                              │
└─────────────────────────────────────────────┘
```

### 3.8 每日操作流程

```
09:15  通达信登录，等待数据同步
09:30  开盘，AKShare实时数据可用
14:30  运行龙瞳MA120扫描.bat
       → 读取TDX本地日线(截至昨日)
       → AKShare获取今日实时行情
       → MA120策略扫描 + 板块标注
14:50  扫描结果推送到微信(可选)
```

---

## 四、龙瞳项目文件清单

### 核心代码 (D:/AI-Tools/TradingAgents/dragon_eye/)

| 文件 | 行数 | 说明 | 状态 |
|------|------|------|------|
| `app.py` | ~100 | Streamlit主入口，7页导航 | ✅ 已更新 |
| `sector/ths_sector.py` | 748 | 板块数据核心(TDX+AKShare+排名+轮动) | ✅ 新建 |
| `sector/__init__.py` | - | 模块导出 | ✅ 已更新 |
| `strategy/ma120_reversal.py` | 246 | MA120踩穿反转策略 | ✅ 新建 |
| `strategy/composite_screener.py` | 475 | 四维综合评分引擎 | ✅ 新建 |
| `strategy/__init__.py` | - | 模块导出 | ✅ 已更新 |
| `pages/sector_heat.py` | 360 | 板块热度页(热力图+排名+对比) | ✅ 新建 |
| `pages/smart_screener.py` | 326 | 智能选股页(多模式+多策略+推送) | ✅ 新建 |

### 待修复/待完成 (2026-05-19 更新)

| 优先级 | 问题 | 状态 |
|--------|------|------|
| 🔴 P0 | T-code行业映射全挂(hy_tree.xml无T前缀blockid) | ✅ 已修复 (AKShare+缓存) |
| 🟡 P1 | 整体Streamlit端到端测试未做 | ✅ 已完成 (6项全过) |
| 🟡 P1 | 10-Agent深度分析系统集成 | ✅ 已集成 (smart_screener双按钮) |
| 🟡 P2 | WeChat推送对接 | ✅ 已对接 (自动从YAML读配置) |
| 🟢 P3 | infoharbor_block.dat二进制解析 | ✅ 已修复 (文本格式#GN_解析) |
