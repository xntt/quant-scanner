import streamlit as st
import pandas as pd
import requests
import re
import json
import time
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 页面UI配置
# ==========================================
st.set_page_config(page_title="A股机构慢牛扫地僧", page_icon="📈", layout="wide")

st.title("📈 A股机构慢牛扫地僧 (全市场扫描版)")
st.markdown("""
**策略逻辑**：寻找脱离散户视线、机构控盘的“碎步小阳”慢牛股。
**扫描路径**：先从东方财富获取全市场最新市值 -> 按市值过滤 -> 对入围股票调用新浪 K 线进行形态比对。
*(扫描全市场可能需要 1-3 分钟，请耐心等待)*
""")

# ==========================================
# 2. 侧边栏：参数调节 UI (新增市值筛选)
# ==========================================
st.sidebar.header("⚙️ 1. 基础过滤池")
# 默认筛选 50亿 到 300亿 的股票，这是最容易出慢牛的区间
market_cap_range = st.sidebar.slider("总市值范围 (亿元)", min_value=10, max_value=3000, value=(50, 300), step=10)
max_scan_num = st.sidebar.number_input("最多扫描多少只符合市值的股票？(防卡死)", min_value=100, max_value=3000, value=1000)

st.sidebar.header("⚙️ 2. 形态严苛度")
max_distance = st.sidebar.slider("允许偏离 20日线最大幅度 (%)", min_value=0.0, max_value=5.0, value=2.0, step=0.5) / 100

# ==========================================
# 3. 数据接口 A：获取全市场股票与市值 (东方财富)
# ==========================================
@st.cache_data(ttl=3600) # 缓存1小时，避免频繁请求
def fetch_all_stocks():
    """从东方财富获取沪深A股实时列表及市值"""
    # 这是东方财富的公开API，获取全部A股（沪市+深市）
    url = "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    try:
        res = requests.get(url, timeout=5).json()
        raw_data = res['data']['diff']
        
        stock_list = []
        for item in raw_data:
            code = item['f12'] # 股票代码，如 600519
            name = item['f14'] # 股票名称
            mcap = item['f20'] # 总市值 (元)
            
            # 过滤掉没有市值数据的（停牌或退市）和北交所/科创板（按需保留，这里过滤掉 8 和 4 开头的）
            if mcap == "-" or not mcap: continue
            if code.startswith('8') or code.startswith('4'): continue
                
            # 转换代码格式为新浪格式：sh600519 或 sz000858
            prefix = 'sh' if code.startswith('6') else 'sz'
            sina_code = f"{prefix}{code}"
            
            # 市值转换为 亿元
            mcap_yi = round(float(mcap) / 100000000, 2)
            
            stock_list.append({
                "symbol": sina_code,
                "name": name,
                "market_cap": mcap_yi
            })
        return pd.DataFrame(stock_list)
    except Exception as e:
        st.error(f"获取全市场数据失败: {e}")
        return pd.DataFrame()

# ==========================================
# 4. 数据接口 B：底层请求新浪财经 K线
# ==========================================
def fetch_sina_data(stock_info):
    """从新浪财经获取最近120天日K线数据"""
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=120"
    
    try:
        response = requests.get(url, timeout=3)
        text = response.text
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', text) 
        data = json.loads(text)
        
        if not data:
            return None, stock_info
            
        df = pd.DataFrame(data)
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        return df, stock_info
    except Exception:
        return None, stock_info

# ==========================================
# 5. 核心策略：慢牛扫地僧算法
# ==========================================
def check_stealth_bull(df, stock_info, max_dist):
    if df is None or len(df) < 120:
        return False, None
    
    # 1. 提前计算
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()
    df['MA120'] = df['close'].rolling(window=120).mean()
    df['pct_change'] = df['close'].pct_change()
    
    current = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 条件A：完美均线多头
    if not (current['close'] > current['MA20'] > current['MA60'] > current['MA120']):
        return False, None
    if not (current['MA60'] > prev['MA60']):
        return False, None
        
    last_15 = df.tail(15)
    last_20 = df.tail(20)
    
    # 条件B：碎步小阳，拒绝暴涨
    positive_days = len(last_15[last_15['close'] > last_15['open']])
    if positive_days < 9:
        return False, None
        
    pump_days = len(last_20[last_20['pct_change'] > 0.06])
    if pump_days > 2:
        return False, None
        
    # 条件C：买点确认 - 缩量回踩 20 日线附近
    dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
    if not (0 <= dist_to_ma20 <= max_dist):
        return False, None
        
    # 返回完整数据 (加入了股票名称和市值)
    result_data = {
        '代码': stock_info['symbol'],
        '名称': stock_info['name'],
        '总市值(亿)': stock_info['market_cap'],
        '现价': round(current['close'], 2),
        'MA20': round(current['MA20'], 2),
        '偏离20日线': f"{round(dist_to_ma20 * 100, 2)}%"
    }
    return True, result_data

# ==========================================
# 6. 执行逻辑 与 渲染UI
# ==========================================
if st.button("🚀 开始全市场深度扫描", type="primary"):
    # 步骤 1: 获取并过滤全市场股票
    st.info("📡 正在连接东方财富获取全市场实时市值数据...")
    all_stocks_df = fetch_all_stocks()
    
    if all_stocks_df.empty:
        st.error("无法获取市场数据，请稍后再试。")
        st.stop()
        
    # 按市值过滤
    min_cap, max_cap = market_cap_range
    filtered_df = all_stocks_df[(all_stocks_df['market_cap'] >= min_cap) & (all_stocks_df['market_cap'] <= max_cap)]
    
    # 限制扫描数量，按市值从小到大排序截取
    pool_to_scan = filtered_df.sort_values('market_cap').head(max_scan_num).to_dict('records')
    
    st.write(f"✅ 市值 {min_cap}亿 - {max_cap}亿 的股票共有 {len(filtered_df)} 只。")
    st.write(f"🕵️‍♂️ 正在为您深度扫描其中的 {len(pool_to_scan)} 只，请耐心等待 1-2 分钟...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    matched_stocks = []
    historical_data_dict = {}
    
    # 步骤 2: 多线程扫描 K 线 (稍微降低并发数到 8，防新浪封锁)
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_stock = {executor.submit(fetch_sina_data, stock): stock for stock in pool_to_scan}
        
        for i, future in enumerate(as_completed(future_to_stock)):
            df, stock_info = future.result()
            
            if df is not None:
                historical_data_dict[stock_info['symbol']] = df
                is_match, info = check_stealth_bull(df, stock_info, max_distance)
                if is_match:
                    matched_stocks.append(info)
                    
            # 进度更新
            progress_bar.progress((i + 1) / len(pool_to_scan))
            status_text.text(f"已扫描: {i+1} / {len(pool_to_scan)} | 当前发现: {len(matched_stocks)} 只")
            
    st.success("🎉 全市场扫描完成！")
    
    # ==========================================
    # 7. 结果展示
    # ==========================================
    if matched_stocks:
        st.subheader(f"🎯 极度稀缺！在 {len(pool_to_scan)} 只股票中，仅发现 {len(matched_stocks)} 只符合【慢牛扫地僧】形态：")
        results_df = pd.DataFrame(matched_stocks)
        st.dataframe(results_df, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📊 点击查看 K 线形态确认")
        
        # 将代码和名称合并在下拉列表里方便看
        results_df['显示名称'] = results_df['名称'] + " (" + results_df['代码'] + ")"
        selected_display = st.selectbox("选择股票绘制趋势图：", results_df['显示名称'].tolist())
        
        if selected_display:
            # 提取真实代码画图
            selected_sym = results_df[results_df['显示名称'] == selected_display].iloc[0]['代码']
            chart_df = historical_data_dict[selected_sym]
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=chart_df['day'], open=chart_df['open'], high=chart_df['high'],
                low=chart_df['low'], close=chart_df['close'], name='K线'
            ))
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='MA20'))
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA60'], line=dict(color='blue', width=1.5), name='MA60'))
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA120'], line=dict(color='purple', width=1.5), name='MA120'))
            
            fig.update_layout(
                title=f"{selected_display} 近120日走势",
                yaxis_title="价格",
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                height=600
            )
            st.plotly_chart(fig, use_container_width=True)
            
    else:
        st.warning("😭 当前行情下，在您选择的市值范围内没有找到符合条件的股票。说明现在可能不是操作此类个股的时机，或者可以尝试放宽左侧的【市值范围】和【偏离度】。")
