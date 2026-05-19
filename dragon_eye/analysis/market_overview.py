"""
东方财富市场概况 — 获取两市真实成交额、涨跌家数

解决 tdxstat.cfg 字段映射不可靠问题:
  - field[22] 映射为"成交额"错误（值太小，可能是成交笔数）
  - field[14] 映射为"总市值"存疑
  - 用东财API交叉验证关键指标
"""
import json
import urllib.request
from typing import Optional


def fetch_market_overview() -> dict:
    """
    获取全市场概况数据
    
    Returns:
        {
            "total_amount": float,  # 两市成交额(亿元)
            "sh_amount": float,
            "sz_amount": float,
            "up_count": int,
            "down_count": int,
            "limit_up_count": int,
            "time": str,
        }
    """
    try:
        # 东财市场概况接口
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get?"
            "fltt=2&invt=2&secids=1.000001,0.399001,1.000688,0.399006"
            "&fields=f2,f3,f4,f5,f6,f7,f8,f12,f13,f14,f20"
        )
        req = urllib.request.Request(url, headers={
            "Referer": "https://data.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        result = {"total_amount": 0.0, "up_count": 0, "down_count": 0, "limit_up_count": 0}
        
        if data.get("data") and data["data"].get("diff"):
            for item in data["data"]["diff"]:
                code = item.get("f12", "")
                result[f"{code}_change"] = item.get("f3", 0)  # 涨跌幅
        
        # 再用东财行情中心获取涨跌家数和成交额
        result.update(_fetch_advance_decline())
        
        return result
    except Exception as e:
        print(f"[MarketOverview] 东财API失败: {e}")
        return {}


def _fetch_advance_decline() -> dict:
    """获取涨跌家数和板块成交额"""
    result = {}
    try:
        # 涨跌家数
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get?"
            "cb=&fid=f62&po=1&pz=1&pn=1&np=1&fltt=2&invt=2"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205"
        )
        req = urllib.request.Request(url, headers={
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        if data.get("data") and data["data"].get("diff"):
            total_amt = 0
            up = down = limit_up = 0
            for item in data["data"]["diff"]:
                total_amt += item.get("f62", 0)  # 成交额(元)
                up += item.get("f104", 0) or 0  # 上涨家数
                down += item.get("f105", 0) or 0  # 下跌家数
                limit_up += item.get("f108", 0) or 0  # 涨停家数
            
            result["total_amount"] = total_amt / 1e8  # 转亿元
            result["up_count"] = up
            result["down_count"] = down
            result["limit_up_count"] = limit_up
            
    except Exception as e:
        print(f"[AdvanceDecline] 涨跌家数API失败: {e}")
    
    return result


def _fetch_market_overview_v2() -> dict:
    """
    Plan B: 从东财行情中心接口获取（更可靠）
    """
    result = {}
    try:
        # 沪市
        for board_id, prefix in [("m:1+t:2", "SH"), ("m:0+t:6", "SZ"), 
                                   ("m:0+t:80", "BJ"), ("m:1+t:23", "KC")]:
            url = (
                f"https://push2.eastmoney.com/api/qt/clist/get?"
                f"cb=&fid=f3&po=1&pz=1&pn=1&np=1&fltt=2&invt=2"
                f"&fs={board_id}"
                f"&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f104,f105,f108,f109"
            )
            req = urllib.request.Request(url, headers={
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            if data.get("data"):
                total = data["data"].get("total", 0)
                result[f"{prefix}_total"] = total
        
        # 上海+深圳总成交额
        # 深证成指 399001, 上证指数 000001
        url2 = (
            "https://push2.eastmoney.com/api/qt/stock/get?"
            "secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170,f171"
        )
        req2 = urllib.request.Request(url2, headers={
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            data2 = json.loads(resp2.read().decode("utf-8"))
        
        if data2.get("data"):
            d = data2["data"]
            # f44=最高, f45=最低, f46=今开, f47=总金额, f48=总手, f50=量比
            # f57=代码, f58=名称, f60=昨收
            result["sh_index_change"] = d.get("f43", 0) / 100  # 涨跌幅
            result["sh_index_price"] = d.get("f43", 0) / 100
            
    except Exception as e:
        print(f"[MarketOverviewV2] Error: {e}")
    
    return result


if __name__ == "__main__":
    result = fetch_market_overview()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    result2 = _fetch_market_overview_v2()
    print(json.dumps(result2, ensure_ascii=False, indent=2))
