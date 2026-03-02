import streamlit as st
import pandas as pd
import numpy as np
import requests
import re
import json
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 页面UI配置 (Streamlit 自动生成前端)
# ==========================================
st.set_page_config(page_title="A股机构慢牛扫地僧", page_icon="📈", layout="wide")

st.title("📈 A股机构慢牛扫地僧 (纯Python + 新浪数据版)")
st.markdown("""
**策略逻辑**：寻找脱离散户视线、机构控盘的“碎步小阳”慢牛股。
条件：均线多头排列 + 近期阳线多且无游资暴涨 + 极度缩量回踩 20 日均线。
*(本工具直接调用新浪财经免鉴权API，无需安装复杂依赖)*
""")

# ==========================================
# 2. 侧边栏：参数调节 UI
# ==========================================
st.sidebar.header("⚙️ 扫地僧选股参数")
max_distance = st.sidebar.slider("允许偏离 20日线最大幅度 (%)", min_value=0.0, max_value=5.0, value=2.0, step=0.5) / 100
max_scan_num = st.sidebar.slider("本次扫描股票数量", min_value=10, max_value=200, value=50, step=10)

# ==========================================
# 3. 核心数据接口：底层请求新浪财经 API
# ==========================================
def fetch_sina_data(symbol):
    """从新浪财经获取最近120天日K线数据"""
    # 构造请求 URL
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=120"
    
    try:
        response = requests.get(url, timeout=3)
        # 新浪返回的JSON键值没有双引号，标准的 json.loads 会报错，需要用正则处理一下
        text = response.text
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', text) 
        data = json.loads(text)
        
        if not data:
            return None
            
        df = pd.DataFrame(data)
        # 数据类型转换
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        df['symbol'] = symbol
        return df
    except Exception as e:
        return None

# ==========================================
# 4. 核心策略：慢牛扫地僧算法
# ==========================================
def check_stealth_bull(df, max_dist):
    """判断单只股票是否符合量化形态"""
    if df is None or len(df) < 120:
        return False, None
    
    # 1. 计算均线
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()
    df['MA120'] = df['close'].rolling(window=120).mean()
    
    current = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 条件A：完美均线多头 (现价 > 20 > 60 > 120) 且 60日线向上发散
    if not (current['close'] > current['MA20'] > current['MA60'] > current['MA120']):
        return False, None
    if not (current['MA60'] > prev['MA60']):
        return False, None
        
    # 条件B：碎步小阳，拒绝暴涨 (近15天阳线>=9天，近20天涨幅超6%的日子<=2)
    last_15 = df.tail(15)
    last_20 = df.tail(20)
    
    positive_days = len(last_15[last_15['close'] > last_15['open']])
    if positive_days < 9: # 至少9天是红盘
        return False, None
        
    df['pct_change'] = df['close'].pct_change()
    pump_days = len(last_20[last_20['pct_change'] > 0.06])
    if pump_days > 2: # 拒绝游资拉升
        return False, None
        
    # 条件C：买点确认 - 缩量回踩 20 日线附近
    dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
    if not (0 <= dist_to_ma20 <= max_dist):
        return False, None
        
    # 如果全部符合，返回关键数据
    result_data = {
        '代码': current['symbol'],
        '现价': round(current['close'], 2),
        'MA20': round(current['MA20'], 2),
        '偏离20日线': f"{round(dist_to_ma20 * 100, 2)}%"
    }
    return True, result_data

# ==========================================
# 5. 执行逻辑 与 渲染UI
# ==========================================
# 模拟一个稳健的股票池 (混合蓝筹与中小盘测试)
# 实际运用中你可以把这里替换为读取本地全市场 CSV 的列表
test_stock_pool = [
    "sh600519", "sz000858", "sh600036", "sz002594", "sh600900", "sz300750", 
    "sz002714", "sh601012", "sz000333", "sh600887", "sh601166", "sz002304",
    "sh603259", "sz002475", "sh600690", "sz000538", "sh600276", "sz300015",
    "sh601318", "sz000001", "sh600000", "sz002236", "sh603501", "sz300450",
    "sz002415", "sh600763", "sz002027", "sh601899", "sz002142", "sh600438",
    "sz000895", "sh603288", "sz300896", "sh600809", "sz002271", "sh601601",
    "sz002001", "sh600104", "sz002311", "sh600522", "sz002352", "sh600309"
] * 5  # 乘以5放大测试池数量

if st.button("🚀 开始执行量化扫描", type="primary"):
    pool_to_scan = test_stock_pool[:max_scan_num]
    st.write(f"正在并发扫描 {len(pool_to_scan)} 只股票，请稍候...")
    
    # 进度条 UI
    progress_bar = st.progress(0)
    matched_stocks = []
    historical_data_dict = {} # 保存 K 线图数据
    
    # 使用多线程并发获取数据，防止网页卡死
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_symbol = {executor.submit(fetch_sina_data, sym): sym for sym in pool_to_scan}
        
        for i, future in enumerate(as_completed(future_to_symbol)):
            symbol = future_to_symbol[future]
            df = future.result()
            
            if df is not None:
                historical_data_dict[symbol] = df
                is_match, info = check_stealth_bull(df, max_distance)
                if is_match:
                    matched_stocks.append(info)
                    
            # 更新进度条
            progress_bar.progress((i + 1) / len(pool_to_scan))
            
    st.success("扫描完成！")
    
    # ==========================================
    # 6. 结果展示：表格与可交互K线图
    # ==========================================
    if matched_stocks:
        st.subheader("🎯 发现符合【慢牛扫地僧】形态的股票：")
        results_df = pd.DataFrame(matched_stocks)
        st.dataframe(results_df, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📊 查看 K 线形态确认")
        
        # 让用户选择选中的股票看图
        selected_sym = st.selectbox("选择股票绘制趋势图：", results_df['代码'].tolist())
        
        if selected_sym:
            chart_df = historical_data_dict[selected_sym]
            
            # 使用 Plotly 画出极其专业的带均线 K 线图
            fig = go.Figure()
            # K线
            fig.add_trace(go.Candlestick(
                x=chart_df['day'], open=chart_df['open'], high=chart_df['high'],
                low=chart_df['low'], close=chart_df['close'], name='K线'
            ))
            # 均线
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='MA20'))
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA60'], line=dict(color='blue', width=1.5), name='MA60'))
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA120'], line=dict(color='purple', width=1.5), name='MA120'))
            
            fig.update_layout(
                title=f"{selected_sym} 近120日走势 (深色主题)",
                yaxis_title="价格",
                template="plotly_dark", # 深色高级金融面板主题
                xaxis_rangeslider_visible=False,
                height=600
            )
            st.plotly_chart(fig, use_container_width=True)
            
    else:
        st.warning("😭 当前行情下，没有找到符合该严苛条件的股票。请尝试放宽左侧参数。")
