import streamlit as st
import pandas as pd
import requests
import re
import json
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 页面UI配置
# ==========================================
st.set_page_config(page_title="A股机构慢牛扫地僧", page_icon="📈", layout="wide")

st.title("📈 A股机构慢牛扫地僧 (量价齐升过滤版)")
st.markdown("""
**策略逻辑升级**：拒绝长期横盘的“死鱼”！要求底部温和放量，且近3个月必须有>10%的实际上涨空间。
*(扫描全市场可能需要 1-3 分钟，请耐心等待)*
""")

# ==========================================
# 2. 侧边栏：参数调节 UI
# ==========================================
st.sidebar.header("⚙️ 1. 基础过滤池 (新浪数据)")
market_cap_range = st.sidebar.slider("总市值范围 (亿元)", min_value=10, max_value=3000, value=(30, 150), step=10)
max_scan_num = st.sidebar.number_input("最多扫描多少只符合市值的股票？", min_value=100, max_value=3000, value=800)

st.sidebar.header("⚙️ 2. 形态严苛度")
max_distance = st.sidebar.slider("允许偏离 20日线最大幅度 (%)", min_value=0.0, max_value=5.0, value=2.0, step=0.5) / 100

# ==========================================
# 3. 数据接口 A：获取全市场股票与市值 (纯新浪)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_all_stocks_sina():
    all_stocks = []
    for page in range(1, 80):
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        try:
            res = requests.get(url, timeout=3)
            text = res.text
            text = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', text)
            data = json.loads(text)
            
            if not data or len(data) == 0: break
                
            for item in data:
                symbol = item.get("symbol", "")
                name = item.get("name", "")
                mktcap_wan = item.get("mktcap", 0) 
                
                if not symbol or mktcap_wan == 0: continue
                if symbol.startswith('bj'): continue
                    
                mktcap_yi = round(float(mktcap_wan) / 10000, 2)
                all_stocks.append({"symbol": symbol, "name": name, "market_cap": mktcap_yi})
        except Exception:
            pass
        time.sleep(0.05)
    return pd.DataFrame(all_stocks)

# ==========================================
# 4. 数据接口 B：底层请求新浪财经 K线
# ==========================================
def fetch_sina_kline(stock_info):
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=120"
    try:
        response = requests.get(url, timeout=3)
        text = response.text
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', text) 
        data = json.loads(text)
        if not data: return None, stock_info
            
        df = pd.DataFrame(data)
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        return df, stock_info
    except Exception:
        return None, stock_info

# ==========================================
# 5. 核心策略：量价齐升慢牛算法 (终极升级版)
# ==========================================
def check_stealth_bull(df, stock_info, max_dist):
    if df is None or len(df) < 120:
        return False, None
    
    # 价格均线
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()
    df['MA120'] = df['close'].rolling(window=120).mean()
    
    # 成交量均线 (新增)
    df['VMA20'] = df['volume'].rolling(window=20).mean()
    df['VMA60'] = df['volume'].rolling(window=60).mean()
    
    df['pct_change'] = df['close'].pct_change()
    
    current = df.iloc[-1]
    prev_20 = df.iloc[-21] # 20天前的数据
    prev_60 = df.iloc[-61] # 60天前的数据
    
    # --- 过滤防线 1：拒绝长期横盘“死鱼” ---
    # 过去60天（约3个月）的真实涨幅必须 > 10%
    growth_60d = (current['close'] - prev_60['close']) / prev_60['close']
    if growth_60d < 0.10: 
        return False, None
        
    # --- 过滤防线 2：均线必须“向上倾斜”而不仅是排列 ---
    if not (current['close'] > current['MA60'] > current['MA120']):
        return False, None
    # 现在的60日/120日线 必须高于 20天前的60日/120日线
    if current['MA60'] <= prev_20['MA60'] or current['MA120'] <= prev_20['MA120']:
        return False, None
        
    # --- 过滤防线 3：量价配合 (主力资金建仓迹象) ---
    # 近 1 个月平均成交量 必须大于 近 3 个月平均成交量的 1.05 倍 (温和放量)
    if current['VMA20'] < current['VMA60'] * 1.05:
        return False, None
        
    # --- 过滤防线 4：K线碎步小阳，拒绝游资爆炒 ---
    last_15 = df.tail(15)
    last_20 = df.tail(20)
    
    positive_days = len(last_15[last_15['close'] >= last_15['open']]) # 阳线天数
    if positive_days < 8: # 15天至少8天阳线或十字星
        return False, None
        
    pump_days = len(last_20[last_20['pct_change'] > 0.07]) # 单日涨幅超7%算暴涨
    if pump_days > 2:
        return False, None
        
    # --- 过滤防线 5：买点确认 - 回踩20日线附近 ---
    dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
    # 允许跌破20日线一点点（洗盘），最高偏离不超过设定值
    if not (-0.015 <= dist_to_ma20 <= max_dist):
        return False, None
        
    result_data = {
        '代码': stock_info['symbol'],
        '名称': stock_info['name'],
        '总市值(亿)': stock_info['market_cap'],
        '现价': round(current['close'], 2),
        '近60日涨幅': f"{round(growth_60d * 100, 2)}%",
        '偏离20日线': f"{round(dist_to_ma20 * 100, 2)}%"
    }
    return True, result_data

# ==========================================
# 6. 执行逻辑 与 渲染UI
# ==========================================
if st.button("🚀 开始全市场深度扫描", type="primary"):
    with st.spinner("📡 正在获取全市场最新市值..."):
        all_stocks_df = fetch_all_stocks_sina()
    
    if all_stocks_df.empty:
        st.error("数据拉取失败，请重试。")
        st.stop()
        
    min_cap, max_cap = market_cap_range
    filtered_df = all_stocks_df[(all_stocks_df['market_cap'] >= min_cap) & (all_stocks_df['market_cap'] <= max_cap)]
    pool_to_scan = filtered_df.sort_values('market_cap').head(max_scan_num).to_dict('records')
    
    st.write(f"✅ 市值 {min_cap}亿 - {max_cap}亿 的股票共有 {len(filtered_df)} 只。")
    st.write(f"🕵️‍♂️ 正在深度扫描 {len(pool_to_scan)} 只，重点排查【量价齐升】形态...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    matched_stocks = []
    historical_data_dict = {}
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_stock = {executor.submit(fetch_sina_kline, stock): stock for stock in pool_to_scan}
        for i, future in enumerate(as_completed(future_to_stock)):
            df, stock_info = future.result()
            if df is not None:
                historical_data_dict[stock_info['symbol']] = df
                is_match, info = check_stealth_bull(df, stock_info, max_distance)
                if is_match:
                    matched_stocks.append(info)
                    
            progress_bar.progress((i + 1) / len(pool_to_scan))
            status_text.text(f"已排查: {i+1} / {len(pool_to_scan)} | 发现真·慢牛: {len(matched_stocks)} 只")
            
    st.success("🎉 扫描完成！")
    
    # ==========================================
    # 7. 结果展示 (新增带成交量的专业图表)
    # ==========================================
    if matched_stocks:
        st.subheader(f"🎯 经过【量价配合】严格过滤，发现 {len(matched_stocks)} 只真·慢牛：")
        results_df = pd.DataFrame(matched_stocks)
        st.dataframe(results_df, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📊 专业 K 线及成交量确认")
        
        results_df['显示名称'] = results_df['名称'] + " (" + results_df['代码'] + ")"
        selected_display = st.selectbox("选择股票绘制趋势图：", results_df['显示名称'].tolist())
        
        if selected_display:
            selected_sym = results_df[results_df['显示名称'] == selected_display].iloc[0]['代码']
            chart_df = historical_data_dict[selected_sym]
            
            # 创建带成交量副图的专业走势图
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, subplot_titles=(f"{selected_display} 走势", "成交量"),
                                row_width=[0.2, 0.7]) # K线占70%，成交量占30%
            
            # K 线与均线 (第一张图)
            fig.add_trace(go.Candlestick(
                x=chart_df['day'], open=chart_df['open'], high=chart_df['high'],
                low=chart_df['low'], close=chart_df['close'], name='K线'
            ), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA60'], line=dict(color='blue', width=1.5), name='MA60'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA120'], line=dict(color='purple', width=1.5), name='MA120'), row=1, col=1)
            
            # 成交量柱状图 (第二张图)
            colors = ['red' if close > open else 'green' for close, open in zip(chart_df['close'], chart_df['open'])]
            fig.add_trace(go.Bar(x=chart_df['day'], y=chart_df['volume'], marker_color=colors, name='成交量'), row=2, col=1)
            # 成交量均线
            fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['VMA20'], line=dict(color='orange', width=1), name='量MA20'), row=2, col=1)
            
            fig.update_layout(
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                xaxis2_rangeslider_visible=False,
                height=700,
                showlegend=True
            )
            st.plotly_chart(fig, use_container_width=True)
            
    else:
        st.warning("😭 当前行情下，没有找到符合【量价齐升+碎步小阳+回踩20日线】的极品股票。这说明市场目前可能缺乏机构建仓的独立行情，请耐心等待或放宽过滤条件。")
