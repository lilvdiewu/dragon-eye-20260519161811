"""
dragon_eye.sector.chain_analyzer — 产业链拆解引擎

输入一个概念，拆解产业链（上游/中游/下游），找细分龙头。

v2: 大幅扩充产业链模板覆盖，增加 analyze_local() 纯本地方法，
    改进关键词匹配精度（优先长关键词，避免短词误匹配）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .sector_data import SectorData
from .stock_screener import StockScreener, StockScore
from ..tdx_reader import get_reader
from ..akshare_bridge import AkShareBridge, get_bridge
from ..data_models import market_from_code, Market
from ..stock_list import get_stock_list

logger = logging.getLogger(__name__)


# ============================================================
# 数据类
# ============================================================

@dataclass
class ChainNode:
    """产业链节点"""
    name: str                          # 节点名称
    role: str                          # 上游/中游/下游
    stocks: list[str] = field(default_factory=list)  # 成分股代码列表
    keywords: list[str] = field(default_factory=list)  # 匹配关键词


@dataclass
class ChainResult:
    """产业链分析结果"""
    concept: str                                     # 概念名称
    chains: list[ChainNode] = field(default_factory=list)  # 产业链节点
    leader_stocks: list[StockScore] = field(default_factory=list)  # 龙头股排名
    summary: str = ""                                 # 概要


# ============================================================
# 产业链模板 v2 — 覆盖30+主流行业/概念
# ============================================================
# 设计原则:
# 1. 关键词从长到短排列，优先匹配精确的长词
# 2. 每个节点至少4个关键词，确保覆盖面
# 3. 避免过于宽泛的短词（如"电子""材料""设备"单独使用）

CHAIN_TEMPLATES: dict[str, list[ChainNode]] = {
    # ---- 新能源 ----
    "固态电池": [
        ChainNode(name="正极材料", role="上游", keywords=["正极材料", "三元正极", "磷酸铁锂", "高镍正极", "正极"]),
        ChainNode(name="负极材料", role="上游", keywords=["负极材料", "硅基负极", "石墨负极", "碳负极", "负极"]),
        ChainNode(name="固态电解质", role="上游", keywords=["固态电解质", "氧化物电解质", "硫化物电解质", "聚合物电解质", "电解质"]),
        ChainNode(name="电池制造", role="中游", keywords=["固态电池", "电池制造", "电芯制造", "电池封装", "pack组装"]),
        ChainNode(name="整车应用", role="下游", keywords=["新能源整车", "电动汽车", "新能源汽车", "动力电池车"]),
    ],
    "锂电池": [
        ChainNode(name="锂矿资源", role="上游", keywords=["锂矿", "锂盐", "碳酸锂", "氢氧化锂", "锂辉石", "盐湖提锂"]),
        ChainNode(name="正极材料", role="上游", keywords=["正极材料", "三元材料", "磷酸铁锂", "钴酸锂", "锰酸锂", "正极"]),
        ChainNode(name="负极材料", role="上游", keywords=["负极材料", "人造石墨", "天然石墨", "硅碳负极", "负极"]),
        ChainNode(name="隔膜电解液", role="上游", keywords=["隔膜", "电解液", "铜箔", "铝箔", "粘结剂"]),
        ChainNode(name="电芯制造", role="中游", keywords=["电芯", "电池制造", "pack", "电池组", "动力电池"]),
        ChainNode(name="电池回收", role="下游", keywords=["电池回收", "梯次利用", "再生利用", "拆解"]),
    ],
    "新能源车": [
        ChainNode(name="锂矿资源", role="上游", keywords=["锂矿", "锂盐", "碳酸锂", "钴", "镍", "稀土"]),
        ChainNode(name="电池材料", role="上游", keywords=["正极材料", "负极材料", "隔膜", "电解液", "铜箔"]),
        ChainNode(name="动力电池", role="中游", keywords=["动力电池", "电芯", "电池组", "锂电池"]),
        ChainNode(name="整车制造", role="中游", keywords=["整车制造", "汽车制造", "新能源车", "电动汽车"]),
        ChainNode(name="充电运营", role="下游", keywords=["充电桩", "换电站", "充电运营", "充电服务"]),
    ],
    "光伏": [
        ChainNode(name="硅料硅片", role="上游", keywords=["硅料", "多晶硅", "单晶硅", "硅片", "硅棒"]),
        ChainNode(name="电池片", role="中游", keywords=["电池片", "HJT电池", "TOPCon", "BC电池", "钙钛矿", "PERC"]),
        ChainNode(name="组件", role="中游", keywords=["光伏组件", "组件封装", "光伏玻璃", "胶膜", "背板"]),
        ChainNode(name="逆变器", role="中游", keywords=["逆变器", "汇流箱", "配电柜"]),
        ChainNode(name="电站运营", role="下游", keywords=["光伏电站", "EPC", "光伏运营", "并网发电", "分布式光伏"]),
    ],
    "风电": [
        ChainNode(name="叶片材料", role="上游", keywords=["风电叶片", "玻璃纤维", "碳纤维", "树脂", "芯材"]),
        ChainNode(name="核心部件", role="上游", keywords=["风电机组", "齿轮箱", "发电机", "主轴", "轴承", "塔筒"]),
        ChainNode(name="整机制造", role="中游", keywords=["风电整机", "风机制造", "机组装配"]),
        ChainNode(name="风电运营", role="下游", keywords=["风电场", "风力发电", "风电运营", "海上风电"]),
    ],
    "储能": [
        ChainNode(name="电池材料", role="上游", keywords=["磷酸铁锂", "电解液", "隔膜", "正极材料", "负极材料"]),
        ChainNode(name="储能电池", role="中游", keywords=["储能电池", "锂电池", "钠电池", "液流电池"]),
        ChainNode(name="储能系统", role="中游", keywords=["储能系统", "PCS", "BMS", "EMS", "储能变流器"]),
        ChainNode(name="储能运营", role="下游", keywords=["储能电站", "储能运营", "峰谷套利", "调频调峰"]),
    ],

    # ---- 半导体/电子 ----
    "半导体": [
        ChainNode(name="半导体材料", role="上游", keywords=["硅片", "光刻胶", "靶材", "电子气体", "抛光液", "掩膜版"]),
        ChainNode(name="半导体设备", role="上游", keywords=["光刻机", "刻蚀设备", "沉积设备", "检测设备", "清洗设备", "离子注入"]),
        ChainNode(name="芯片设计", role="中游", keywords=["芯片设计", "IC设计", "IP核", "EDA"]),
        ChainNode(name="晶圆制造", role="中游", keywords=["晶圆代工", "芯片制造", "封装测试", "先进封装"]),
        ChainNode(name="终端应用", role="下游", keywords=["消费电子", "通信设备", "汽车电子", "工业控制"]),
    ],
    "芯片": [
        ChainNode(name="芯片材料", role="上游", keywords=["硅片", "光刻胶", "电子气体", "靶材", "CMP材料"]),
        ChainNode(name="芯片设备", role="上游", keywords=["光刻机", "刻蚀机", "薄膜设备", "量测设备"]),
        ChainNode(name="芯片设计", role="中游", keywords=["芯片设计", "FPGA", "GPU", "CPU", "SoC", "MCU"]),
        ChainNode(name="芯片制造", role="中游", keywords=["晶圆代工", "芯片封装", "芯片测试", "先进封装"]),
    ],
    "消费电子": [
        ChainNode(name="核心器件", role="上游", keywords=["显示面板", "芯片", "传感器", "摄像头模组", "声学器件"]),
        ChainNode(name="零部件", role="上游", keywords=["结构件", "连接器", "FPC", "电池", "玻璃盖板"]),
        ChainNode(name="整机组装", role="中游", keywords=["整机组装", "代工", "ODM", "EMS"]),
        ChainNode(name="品牌终端", role="下游", keywords=["手机", "平板", "笔记本", "可穿戴", "TWS"]),
    ],
    "PCB": [
        ChainNode(name="覆铜板", role="上游", keywords=["覆铜板", "铜箔", "玻纤布", "环氧树脂"]),
        ChainNode(name="PCB制造", role="中游", keywords=["PCB", "印制电路板", "线路板", "柔性板"]),
        ChainNode(name="PCB应用", role="下游", keywords=["通信基站", "服务器", "汽车电子", "消费电子"]),
    ],

    # ---- 人工智能/数字经济 ----
    "人工智能": [
        ChainNode(name="算力芯片", role="上游", keywords=["AI芯片", "GPU", "算力芯片", "NPU", "TPU"]),
        ChainNode(name="数据服务", role="上游", keywords=["数据标注", "数据清洗", "语料库", "训练数据"]),
        ChainNode(name="基础模型", role="中游", keywords=["大模型", "GPT", "大语言模型", "深度学习框架", "AI训练"]),
        ChainNode(name="AI应用", role="下游", keywords=["AI应用", "智能客服", "自动驾驶", "AI医疗", "AI办公"]),
    ],
    "算力": [
        ChainNode(name="算力芯片", role="上游", keywords=["GPU", "AI芯片", "算力芯片", "NPU", "HBM", "加速卡"]),
        ChainNode(name="服务器", role="中游", keywords=["AI服务器", "液冷服务器", "光模块", "交换机", "网卡"]),
        ChainNode(name="数据中心", role="中游", keywords=["数据中心", "IDC", "机房", "液冷", "配电"]),
        ChainNode(name="算力服务", role="下游", keywords=["云算力", "智算中心", "AI推理", "模型训练", "算力租赁"]),
    ],
    "数据要素": [
        ChainNode(name="数据采集", role="上游", keywords=["数据采集", "传感器", "物联网", "数据入口"]),
        ChainNode(name="数据存储计算", role="中游", keywords=["数据存储", "数据库", "云计算", "大数据平台"]),
        ChainNode(name="数据流通交易", role="中游", keywords=["数据交易", "数据确权", "隐私计算", "数据脱敏"]),
        ChainNode(name="数据应用", role="下游", keywords=["金融科技", "智慧城市", "医疗数据", "政务数据"]),
    ],
    "机器人": [
        ChainNode(name="核心零部件", role="上游", keywords=["伺服电机", "减速器", "控制器", "传感器", "丝杠", "轴承"]),
        ChainNode(name="本体制造", role="中游", keywords=["机器人本体", "工业机器人", "协作机器人", "机器人集成"]),
        ChainNode(name="系统集成", role="中游", keywords=["系统集成", "运动控制", "机器视觉", "控制系统"]),
        ChainNode(name="场景应用", role="下游", keywords=["工业自动化", "服务机器人", "医疗机器人", "物流机器人"]),
    ],
    "人形机器人": [
        ChainNode(name="核心零部件", role="上游", keywords=["伺服电机", "减速器", "传感器", "丝杠", "轴承", "空心杯电机"]),
        ChainNode(name="本体制造", role="中游", keywords=["人形机器人", "机器人本体", "仿生机器人", "双足机器人"]),
        ChainNode(name="控制系统", role="中游", keywords=["运动控制", "机器视觉", "触觉传感", "力控"]),
        ChainNode(name="场景应用", role="下游", keywords=["工业制造", "家庭服务", "医疗辅助", "危险作业"]),
    ],

    # ---- 医药/生物 ----
    "创新药": [
        ChainNode(name="药物发现", role="上游", keywords=["药物发现", "靶点", "先导化合物", "CRO", "药物筛选"]),
        ChainNode(name="临床研究", role="中游", keywords=["临床研究", "临床试验", "CRO", "CDMO"]),
        ChainNode(name="药品制造", role="中游", keywords=["制药", "原料药", "制剂", "生物制药"]),
        ChainNode(name="药品销售", role="下游", keywords=["医药流通", "药店", "医药销售"]),
    ],
    "中药": [
        ChainNode(name="中药材", role="上游", keywords=["中药材", "中药饮片", "道地药材", "中药种植"]),
        ChainNode(name="中药制造", role="中游", keywords=["中成药", "中药制剂", "中药配方颗粒", "中药提取"]),
        ChainNode(name="中药销售", role="下游", keywords=["中药销售", "中医诊所", "中药房"]),
    ],
    "医疗器械": [
        ChainNode(name="原材料", role="上游", keywords=["医用材料", "生物材料", "医用塑料", "医用金属"]),
        ChainNode(name="设备制造", role="中游", keywords=["医疗设备", "影像设备", "手术器械", "诊断设备"]),
        ChainNode(name="耗材", role="中游", keywords=["医用耗材", "IVD", "体外诊断", "试剂"]),
        ChainNode(name="医院终端", role="下游", keywords=["医院", "体检中心", "第三方检验"]),
    ],
    "CXO": [
        ChainNode(name="药物发现CRO", role="上游", keywords=["药物发现", "CRO", "药物筛选", "靶点验证"]),
        ChainNode(name="临床CRO", role="中游", keywords=["临床CRO", "临床试验", "数据管理", "SMO"]),
        ChainNode(name="CDMO", role="中游", keywords=["CDMO", "定制生产", "工艺开发", "制剂开发"]),
    ],

    # ---- 金融/地产 ----
    "银行": [
        ChainNode(name="国有大行", role="上游", keywords=["国有银行", "大型银行", "国有大行"]),
        ChainNode(name="股份行", role="中游", keywords=["股份制银行", "股份行", "商业银行"]),
        ChainNode(name="城农商行", role="下游", keywords=["城商行", "农商行", "地方银行", "区域银行"]),
    ],
    "券商": [
        ChainNode(name="头部券商", role="上游", keywords=["头部券商", "大型券商", "综合券商"]),
        ChainNode(name="中型券商", role="中游", keywords=["中型券商", "特色券商"]),
        ChainNode(name="券商服务", role="下游", keywords=["金融科技", "行情软件", "交易系统"]),
    ],
    "房地产": [
        ChainNode(name="土地开发", role="上游", keywords=["土地开发", "城投", "园区开发"]),
        ChainNode(name="房地产开发", role="中游", keywords=["房地产开发", "住宅开发", "商业地产", "地产开发"]),
        ChainNode(name="物业管理", role="下游", keywords=["物业管理", "物业服务", "社区运营"]),
    ],

    # ---- 基建/制造 ----
    "建筑": [
        ChainNode(name="建材", role="上游", keywords=["水泥", "钢铁", "玻璃", "建材", "管材"]),
        ChainNode(name="工程施工", role="中游", keywords=["建筑施工", "工程总承包", "基建施工", "土木工程"]),
        ChainNode(name="装饰装修", role="下游", keywords=["装饰装修", "幕墙", "园林", "设计咨询"]),
    ],
    "电力": [
        ChainNode(name="发电", role="上游", keywords=["火力发电", "水力发电", "核电", "风力发电", "光伏发电"]),
        ChainNode(name="输配电", role="中游", keywords=["输变电", "变压器", "开关柜", "电力设备", "特高压"]),
        ChainNode(name="售电运营", role="下游", keywords=["电力运营", "售电", "电网", "配电"]),
    ],
    "军工": [
        ChainNode(name="军工材料", role="上游", keywords=["钛合金", "高温合金", "碳纤维", "特种钢", "复合材料"]),
        ChainNode(name="核心器件", role="上游", keywords=["军工电子", "雷达", "芯片", "红外", "导航"]),
        ChainNode(name="装备制造", role="中游", keywords=["航空发动机", "导弹", "战斗机", "舰船", "坦克"]),
        ChainNode(name="军工配套", role="下游", keywords=["军用通信", "军工信息化", "军用软件"]),
    ],
    "航空航天": [
        ChainNode(name="航空材料", role="上游", keywords=["钛合金", "高温合金", "碳纤维", "复合材料", "航空铝"]),
        ChainNode(name="航空发动机", role="上游", keywords=["航空发动机", "涡轮", "叶片", "燃烧室"]),
        ChainNode(name="飞机制造", role="中游", keywords=["飞机制造", "大飞机", "航空制造", "机体制造"]),
        ChainNode(name="航空运营", role="下游", keywords=["航空公司", "航空物流", "机场运营", "航天发射"]),
    ],
    "船舶": [
        ChainNode(name="船用材料", role="上游", keywords=["船用钢材", "船用涂料", "船舶配件"]),
        ChainNode(name="造船", role="中游", keywords=["造船", "船厂", "船舶制造", "船舶修理"]),
        ChainNode(name="航运运营", role="下游", keywords=["航运", "集装箱运输", "散货运输", "油运"]),
    ],

    # ---- 消费 ----
    "白酒": [
        ChainNode(name="粮食原料", role="上游", keywords=["高粱", "小麦", "粮食", "酒曲"]),
        ChainNode(name="白酒酿造", role="中游", keywords=["白酒", "酿酒", "白酒生产", "基酒"]),
        ChainNode(name="白酒销售", role="下游", keywords=["白酒销售", "经销商", "烟酒店", "电商渠道"]),
    ],
    "食品饮料": [
        ChainNode(name="农产品原料", role="上游", keywords=["农产品", "粮食", "养殖", "种植", "乳制品原料"]),
        ChainNode(name="食品加工", role="中游", keywords=["食品加工", "调味品", "乳制品", "肉制品", "饮料制造"]),
        ChainNode(name="渠道销售", role="下游", keywords=["商超", "便利店", "电商", "餐饮", "零食店"]),
    ],
    "家电": [
        ChainNode(name="核心部件", role="上游", keywords=["压缩机", "电机", "芯片", "显示面板", "阀门"]),
        ChainNode(name="家电制造", role="中游", keywords=["白电", "空调", "冰箱", "洗衣机", "厨电"]),
        ChainNode(name="家电零售", role="下游", keywords=["家电零售", "家电连锁", "线上渠道", "售后服务"]),
    ],
    "纺织服装": [
        ChainNode(name="纺织原料", role="上游", keywords=["棉花", "化纤", "涤纶", "锦纶", "粘胶"]),
        ChainNode(name="纺织制造", role="中游", keywords=["纺织", "织造", "印染", "面料", "服装代工"]),
        ChainNode(name="品牌零售", role="下游", keywords=["服装品牌", "运动品牌", "家纺", "鞋履"]),
    ],

    # ---- 新兴 ----
    "低空经济": [
        ChainNode(name="核心部件", role="上游", keywords=["eVTOL电机", "飞控系统", "传感器", "碳纤维", "桨叶"]),
        ChainNode(name="整机制造", role="中游", keywords=["eVTOL", "无人机", "飞行器制造", "通用航空"]),
        ChainNode(name="运营服务", role="下游", keywords=["低空运营", "物流配送", "测绘巡检", "培训服务"]),
        ChainNode(name="基础设施", role="下游", keywords=["起降场", "低空空管", "通信导航", "气象服务"]),
    ],
    "商业航天": [
        ChainNode(name="航天材料", role="上游", keywords=["航天材料", "钛合金", "碳纤维", "耐高温材料"]),
        ChainNode(name="火箭制造", role="中游", keywords=["火箭", "运载火箭", "发动机", "卫星制造"]),
        ChainNode(name="航天运营", role="下游", keywords=["卫星运营", "卫星通信", "遥感服务", "发射服务"]),
    ],
    "量子计算": [
        ChainNode(name="量子器件", role="上游", keywords=["量子芯片", "超导器件", "量子比特", "稀释制冷机"]),
        ChainNode(name="量子系统", role="中游", keywords=["量子计算机", "量子测控", "量子软件"]),
        ChainNode(name="量子应用", role="下游", keywords=["量子通信", "量子加密", "量子模拟", "量子传感"]),
    ],
    "Web3": [
        ChainNode(name="基础设施", role="上游", keywords=["区块链", "公链", "跨链", "节点服务"]),
        ChainNode(name="开发工具", role="中游", keywords=["智能合约", "DApp", "DeFi", "NFT平台"]),
        ChainNode(name="应用服务", role="下游", keywords=["数字藏品", "元宇宙", "链游", "社交"]),
    ],

    # ---- 资源/化工 ----
    "石油化工": [
        ChainNode(name="石油开采", role="上游", keywords=["石油开采", "油气勘探", "钻井", "采油"]),
        ChainNode(name="炼油化工", role="中游", keywords=["炼油", "石化", "乙烯", "PTA", "聚酯"]),
        ChainNode(name="精细化工", role="下游", keywords=["精细化工", "涂料", "农药", "日化", "添加剂"]),
    ],
    "有色金属": [
        ChainNode(name="矿山开采", role="上游", keywords=["铜矿", "铝矿", "锌矿", "锡矿", "镍矿", "钨矿"]),
        ChainNode(name="冶炼加工", role="中游", keywords=["铜冶炼", "铝冶炼", "锌冶炼", "有色金属加工"]),
        ChainNode(name="深加工应用", role="下游", keywords=["铜加工", "铝加工", "锂电铜箔", "电子铝箔"]),
    ],
    "钢铁": [
        ChainNode(name="铁矿石", role="上游", keywords=["铁矿石", "焦炭", "焦煤", "废钢"]),
        ChainNode(name="钢铁冶炼", role="中游", keywords=["炼钢", "轧钢", "特钢", "不锈钢"]),
        ChainNode(name="钢材加工", role="下游", keywords=["钢材加工", "钢结构", "钢管", "线材"]),
    ],
    "煤炭": [
        ChainNode(name="煤炭开采", role="上游", keywords=["煤炭开采", "煤矿", "采煤", "焦煤"]),
        ChainNode(name="煤炭加工", role="中游", keywords=["煤炭洗选", "煤化工", "焦化", "煤制油"]),
        ChainNode(name="煤炭运输", role="下游", keywords=["煤炭运输", "铁路运输", "港口", "电力供应"]),
    ],

    # ---- 通信 ----
    "5G": [
        ChainNode(name="芯片器件", role="上游", keywords=["5G芯片", "射频器件", "滤波器", "天线", "光模块"]),
        ChainNode(name="基站设备", role="中游", keywords=["5G基站", "基站天线", "射频单元", "基带"]),
        ChainNode(name="网络运营", role="下游", keywords=["运营商", "通信服务", "5G应用"]),
    ],
    "光通信": [
        ChainNode(name="光纤光缆", role="上游", keywords=["光纤", "光缆", "光纤预制棒", "光器件"]),
        ChainNode(name="光模块", role="中游", keywords=["光模块", "光通信设备", "光传输"]),
        ChainNode(name="光网络", role="下游", keywords=["光网络", "数据中心互联", "5G承载"]),
    ],
}

# 行业别名映射：行业名 → 模板名（用于模糊匹配）
INDUSTRY_ALIAS: dict[str, str] = {
    # 申万行业 → 产业链模板
    "电力设备": "光伏",
    "电力设备-光伏": "光伏",
    "电力设备-风电": "风电",
    "电力设备-电池": "锂电池",
    "电力设备-储能": "储能",
    "汽车-汽车零部件": "新能源车",
    "汽车-整车": "新能源车",
    "电子-半导体": "半导体",
    "电子-消费电子": "消费电子",
    "电子-元件": "PCB",
    "计算机-IT服务": "人工智能",
    "计算机-软件开发": "人工智能",
    "通信-通信设备": "5G",
    "医药生物-化学制药": "创新药",
    "医药生物-中药": "中药",
    "医药生物-医疗器械": "医疗器械",
    "医药生物-医疗服务": "CXO",
    "国防军工": "军工",
    "国防军工-航空装备": "航空航天",
    "国防军工-航海装备": "船舶",
    "建筑装饰": "建筑",
    "建筑材料": "建筑",
    "房地产": "房地产",
    "银行": "银行",
    "非银金融-证券": "券商",
    "食品饮料-白酒": "白酒",
    "食品饮料-饮料乳品": "食品饮料",
    "食品饮料-调味发酵品": "食品饮料",
    "家用电器": "家电",
    "纺织服饰": "纺织服装",
    "石油石化": "石油化工",
    "有色金属": "有色金属",
    "钢铁": "钢铁",
    "煤炭": "煤炭",
    "公用事业-电力": "电力",
    # 简称匹配
    "光伏设备": "光伏",
    "风电设备": "风电",
    "储能设备": "储能",
    "半导体设备": "半导体",
    "汽车": "新能源车",
    "新能源汽车": "新能源车",
    "医药": "创新药",
    "生物制药": "创新药",
    "制药": "创新药",
    "军工": "军工",
    "航空": "航空航天",
    "航天": "航空航天",
    "白酒": "白酒",
    "食品": "食品饮料",
    "饮料": "食品饮料",
    "家电": "家电",
    "房地产": "房地产",
    "地产": "房地产",
    "银行": "银行",
    "券商": "券商",
    "证券": "券商",
    "石化": "石油化工",
    "化工": "石油化工",
    "煤炭": "煤炭",
    "电力": "电力",
    "钢铁": "钢铁",
    "通信": "5G",
    "光通信": "光通信",
    "纺织": "纺织服装",
    "服装": "纺织服装",
    "机器人": "机器人",
    "人形机器人": "人形机器人",
    "低空经济": "低空经济",
    "商业航天": "商业航天",
    "算力": "算力",
    "AI": "人工智能",
    "芯片": "芯片",
    "数据要素": "数据要素",
    "量子计算": "量子计算",
    "Web3": "Web3",
}


# ============================================================
# 产业链分析引擎 v2
# ============================================================

class ChainAnalyzer:
    """产业链拆解引擎 v2

    用法:
        analyzer = ChainAnalyzer()
        result = analyzer.analyze("固态电池")  # 完整分析（可能联网）
        result = analyzer.analyze_local("半导体", "603618")  # 纯本地分析
    """

    def __init__(
        self,
        sector_data: Optional[SectorData] = None,
        screener: Optional[StockScreener] = None,
        reader=None,
        bridge=None,
    ):
        self._sector_data = sector_data or SectorData()
        self._screener = screener or StockScreener()
        self._reader = reader or get_reader()
        self._bridge = bridge or get_bridge()  # 全局单例

    def analyze_local(self, concept_name: str, target_code: str = "") -> Optional[ChainResult]:
        """纯本地产业链分析（不联网，秒出结果）

        通过本地模板 + 股票名称关键词匹配，判断个股在产业链中的位置。
        当网络不通或AkShare不可用时使用。

        Args:
            concept_name: 行业/概念名称
            target_code: 目标股票代码（用于标记位置）

        Returns:
            ChainResult 或 None（无匹配模板时）
        """
        # 1. 匹配模板
        template = self._match_template(concept_name)
        if not template:
            return None

        # 2. 构建结果
        result = ChainResult(concept=concept_name)
        result.chains = [
            ChainNode(name=n.name, role=n.role, keywords=list(n.keywords))
            for n in template
        ]

        # 3. 如果有目标股票，用名称匹配定位
        if target_code:
            stock_name = self._get_single_stock_name(target_code)
            if stock_name:
                for node in result.chains:
                    # 精确匹配：股票名称包含节点关键词
                    if self._match_keywords_precise(stock_name, node.keywords):
                        node.stocks.append(target_code)
                        break
                else:
                    # 没匹配上，标记在最后一个节点
                    if result.chains:
                        result.chains[-1].stocks.append(target_code)
            else:
                # 连名称都没有，标记在最后一个节点
                if result.chains:
                    result.chains[-1].stocks.append(target_code)

        # 4. 生成概要
        result.summary = self._generate_summary(concept_name, result, None)
        return result

    def analyze(self, concept_name: str) -> ChainResult:
        """完整产业链分析（可能联网，有超时保护）

        流程:
        1. 优先从AkShare获取板块成分股（在线，5秒超时）
        2. AkShare不可用时，从全市场股票名称匹配关键词（离线fallback）
        3. 获取产业链模板拆解节点
        4. 通过关键词将成分股分配到各节点
        5. StockScreener多维度评分排序
        6. 返回ChainResult
        """
        result = ChainResult(concept=concept_name)

        # 1. 搜索概念板块（优先在线，有超时保护，fallback离线）
        all_stocks: list[str] = []
        matched_sector = None

        try:
            sector_list = self._sector_data.search_sector(concept_name)
            for sec in sector_list:
                if concept_name in sec.name:
                    stocks = self._sector_data.get_sector_stocks(sec.code, sec.sector_type)
                    if stocks:
                        all_stocks.extend(stocks)
                        matched_sector = sec
                        break
            all_stocks = list(dict.fromkeys(all_stocks))
        except Exception:
            pass

        # 离线fallback: 从全市场股票名称匹配产业链关键词
        if not all_stocks:
            all_stocks = self._local_keyword_match(concept_name)
            if all_stocks:
                logger.info("离线模式: 通过关键词匹配到 %d 只股票", len(all_stocks))

        if not all_stocks:
            result.summary = f"未找到概念'{concept_name}'的成分股数据"
            return result

        # 2. 获取产业链模板
        template = self._match_template(concept_name)
        if template:
            result.chains = [
                ChainNode(name=n.name, role=n.role, keywords=list(n.keywords))
                for n in template
            ]
        else:
            # 无模板时，自动生成上/中/下游三层
            result.chains = [
                ChainNode(name="上游原材料", role="上游", keywords=["材料", "原料", "资源", "开采", "矿产"]),
                ChainNode(name="中游制造", role="中游", keywords=["制造", "生产", "加工", "装备", "设备"]),
                ChainNode(name="下游应用", role="下游", keywords=["应用", "终端", "服务", "运营", "销售"]),
            ]

        # 3. 将成分股分配到产业链节点
        self._assign_stocks_to_nodes(all_stocks, result.chains)

        # 4. 多维度评分排序
        try:
            result.leader_stocks = self._screener.screen(all_stocks)
        except Exception:
            pass

        # 5. 生成概要
        result.summary = self._generate_summary(concept_name, result, matched_sector)

        return result

    def _match_template(self, concept_name: str) -> Optional[list[ChainNode]]:
        """匹配产业链模板

        匹配优先级:
        1. 精确匹配 CHAIN_TEMPLATES
        2. 别名映射 INDUSTRY_ALIAS
        3. 模糊匹配（概念名包含/被包含）
        """
        # 1. 精确匹配
        if concept_name in CHAIN_TEMPLATES:
            return CHAIN_TEMPLATES[concept_name]

        # 2. 别名映射
        if concept_name in INDUSTRY_ALIAS:
            template_name = INDUSTRY_ALIAS[concept_name]
            if template_name in CHAIN_TEMPLATES:
                return CHAIN_TEMPLATES[template_name]

        # 3. 模糊匹配: 概念名包含模板关键词
        for key, template in CHAIN_TEMPLATES.items():
            if key in concept_name or concept_name in key:
                return template

        # 4. 别名模糊匹配
        for alias, template_name in INDUSTRY_ALIAS.items():
            if alias in concept_name or concept_name in alias:
                if template_name in CHAIN_TEMPLATES:
                    return CHAIN_TEMPLATES[template_name]

        return None

    def _assign_stocks_to_nodes(self, stocks: list[str], nodes: list[ChainNode]) -> None:
        """通过关键词将成分股分配到产业链节点

        改进: 优先匹配长关键词（更精确），避免短词误匹配
        """
        # 获取股票名称
        name_map = self._get_stock_name_map(stocks)
        assigned: set[str] = set()

        # 对每个节点，按关键词长度降序匹配（长词更精确）
        for node in nodes:
            sorted_keywords = sorted(node.keywords, key=len, reverse=True)
            for code6 in stocks:
                if code6 in assigned:
                    continue
                stock_name = name_map.get(code6, "")
                if self._match_keywords_precise(stock_name, sorted_keywords):
                    node.stocks.append(code6)
                    assigned.add(code6)

        # 未匹配的归入最后一个节点
        if nodes:
            last_node = nodes[-1]
            for code6 in stocks:
                if code6 not in assigned:
                    last_node.stocks.append(code6)

    def _get_single_stock_name(self, code6: str) -> str:
        """获取单只股票名称（纯本地优先）"""
        # 1. 从StockList本地获取
        try:
            sl = get_stock_list()
            info = sl.get_stock(code6)
            if info and info.name:
                return info.name
        except Exception:
            pass

        # 2. 从本地名称缓存
        try:
            name_map = self._bridge._load_local_names()
            if name_map and code6 in name_map:
                return name_map[code6]
        except Exception:
            pass

        return ""

    def _get_stock_name_map(self, stocks: list[str]) -> dict[str, str]:
        """获取股票代码→名称映射（本地优先，不联网）"""
        name_map: dict[str, str] = {}

        # 优先从本地名称缓存获取
        try:
            local_names = self._bridge._load_local_names()
            if local_names and len(local_names) >= 100:
                for code6 in stocks:
                    if code6 in local_names:
                        name_map[code6] = local_names[code6]
        except Exception:
            pass

        # 补充从StockList获取
        if len(name_map) < len(stocks):
            try:
                sl = get_stock_list()
                for code6 in stocks:
                    if code6 not in name_map:
                        info = sl.get_stock(code6)
                        if info and info.name:
                            name_map[code6] = info.name
            except Exception:
                pass

        return name_map

    @staticmethod
    def _match_keywords_precise(stock_name: str, keywords: list[str]) -> bool:
        """精确关键词匹配

        改进:
        - 空名称返回False
        - 按关键词长度匹配（长词优先，调用方应已排序）
        - 单字关键词不匹配（太宽泛，如"电""化"等）
        """
        if not stock_name:
            return False
        for kw in keywords:
            if len(kw) < 2:  # 跳过单字关键词
                continue
            if kw in stock_name:
                return True
        return False

    @staticmethod
    def _match_keywords(stock_name: str, keywords: list[str]) -> bool:
        """检查股票名称是否匹配关键词列表（兼容旧接口）"""
        return ChainAnalyzer._match_keywords_precise(stock_name, keywords)

    def _local_keyword_match(self, concept_name: str) -> list[str]:
        """离线关键词匹配: 从全市场股票名称中匹配产业链关键词

        当AkShare不可用时，通过产业链模板的关键词在本地名称中搜索匹配的股票。
        """
        # 获取匹配模板的关键词
        template = self._match_template(concept_name)
        if not template:
            return []

        all_keywords: list[str] = []
        for node in template:
            all_keywords.extend(node.keywords)

        # 也把概念名本身加入关键词（≥2字才加）
        if len(concept_name) >= 2:
            all_keywords.append(concept_name)

        # 过滤掉单字关键词
        all_keywords = [kw for kw in all_keywords if len(kw) >= 2]

        # 从本地名称缓存中搜索
        try:
            name_map = self._bridge._load_local_names()
            if not name_map or len(name_map) < 100:
                # 尝试StockList
                sl = get_stock_list()
                stocks = sl.get_all()
                # 需要名称才能匹配
                name_map = self._get_stock_name_map([s.code for s in stocks[:200]])
        except Exception:
            return []

        if not name_map:
            return []

        matched: list[str] = []
        for code6, name in name_map.items():
            if not name:
                continue
            for kw in all_keywords:
                if kw in name:
                    matched.append(code6)
                    break

        return list(dict.fromkeys(matched))  # 去重

    def _generate_summary(self, concept_name: str, result: ChainResult,
                          matched_sector: Optional[object]) -> str:
        """生成产业链分析概要"""
        parts = [f"【{concept_name}】产业链分析"]

        # 产业链节点
        for node in result.chains:
            stock_count = len(node.stocks)
            parts.append(f"  {node.role}·{node.name}: {stock_count}只")

        # 龙头股
        if result.leader_stocks:
            top3 = result.leader_stocks[:3]
            leaders = "、".join(
                f"{s.name or s.code}({s.score}分)" for s in top3
            )
            parts.append(f"  龙头股: {leaders}")

        # 总成分股
        total_stocks = set()
        for node in result.chains:
            total_stocks.update(node.stocks)
        parts.append(f"  成分股总数: {len(total_stocks)}")

        return "\n".join(parts)
