"""全局配置参数"""

# ========== 预警阈值 ==========
CONSECUTIVE_DAYS = 2              # 连续上涨天数阈值
SECTOR_GAIN_THRESHOLD = 1.5       # 板块单日涨幅预警线(%)
CAPITAL_INFLOW_THRESHOLD = 1.0    # 主力净流入预警线(亿元)
STOCK_GAIN_THRESHOLD = 5.0        # 个股显著涨幅阈值(%)
STOCK_LIMIT_UP_THRESHOLD = 9.5    # 涨停判定阈值(%)
ROTATION_OUTFLOW_THRESHOLD = -0.5 # 板块轮出资金阈值(亿元)
ROTATION_INFLOW_THRESHOLD = 1.0   # 板块轮入资金阈值(亿元)

# ========== 数据参数 ==========
HISTORY_DAYS = 10                 # 拉取历史天数
TOP_N_SECTORS = 30                # 展示板块数量
TOP_N_STOCKS = 10                 # 每板块展示个股数量
BOARD_TYPES = ["concept", "industry"]  # 板块类型：概念/行业

# ========== 显示参数 ==========
ALERT_COLOR_HIGH = "#FF4444"      # 高危预警色
ALERT_COLOR_MID = "#FF8800"       # 中危预警色
ALERT_COLOR_LOW = "#FFCC00"       # 低危预警色
ROTATION_IN_COLOR = "#00CC66"     # 轮入标注色
ROTATION_OUT_COLOR = "#CC3333"    # 轮出标注色
