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
# 1. 全局页面配置
# ==========================================
st.set_page_config(page_title="A股量化武器库", page_icon="⚔️", layout="wide")

# ==========================================
# 2. 侧边栏：主导航菜单
# ==========================================
st.sidebar.title("⚔️ 系统导航")
app_mode = st.sidebar.radio(
    "请选择你要使用的量化武器：",
    ["🐢 模式一：机构慢牛扫地僧 (中长线)", "🔥 模式二：游资热钱捕捉器 (超短线)"]
)

st.sidebar.markdown("---")

# ==========================================
# 3. 共享基础数据接口 (带缓存)
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
                if not symbol or mktcap_wan == 0 or symbol.startswith('bj'): continue
                mktcap_yi = round(float(mktcap_wan) / 10000, 2)
                all_stocks.append({"symbol": symbol, "name": name, "market_cap": mktcap_yi})
        except Exception:
            pass
        time.sleep(0.05)
    return pd.DataFrame(all_stocks)

# 获取单只股票K线 (支持传入需要的K线长度)
def fetch_sina_kline(stock_info, datalen=120):
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
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


# =====================================================================
# 武器库 1：机构慢牛扫地僧 (量价齐升过滤版)
# =====================================================================
def check_stealth_bull(df, stock_info, max_dist):
    if df is None or len(df) < 120: return False, None
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()
    df['MA120'] = df['close'].rolling(window=120).mean()
    df['VMA20'] = df['volume'].rolling(window=20).mean()
    df['VMA60'] = df['volume'].rolling(window=60).mean()
    df['pct_change'] = df['close'].pct_change()
    current = df.iloc[-1]
    prev_20 = df.iloc[-21]
    prev_60 = df.iloc[-61]
    
    # 涨幅与斜率过滤
    growth_60d = (current['close'] - prev_60['close']) / prev_60['close']
    if growth_60d < 0.10: return False, None
    if not (current['close'] > current['MA60'] > current['MA120']): return False, None
    if current['MA60'] <= prev_20['MA60'] or current['MA120'] <= prev_20['MA120']: return False, None
    
    # 温和放量与碎步小阳
    if current['VMA20'] < current['VMA60'] * 1.05: return False, None
    last_15, last_20 = df.tail(15), df.tail(20)
    if len(last_15[last_15['close'] >= last_15['open']]) < 8: return False, None
    if len(last_20[last_20['pct_change'] > 0.07]) > 2: return False, None
    
    # 回踩20日线买点
    dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
    if not (-0.015 <= dist_to_ma20 <= max_dist): return False, None
        
    return True, {
        '代码': stock_info['symbol'], '名称': stock_info['name'], '总市值(亿)': stock_info['market_cap'],
        '现价': round(current['close'], 2), '近60日涨幅': f"{round(growth_60d * 100, 2)}%", '偏离20日线': f"{round(dist_to_ma20 * 100, 2)}%"
    }

if app_mode == "🐢 模式一：机构慢牛扫地僧 (中长线)":
    st.title("🐢 机构慢牛扫地僧 (量价齐升版)")
    st.markdown("**策略逻辑**：拒绝长期横盘的死鱼，要求底部温和放量，近3个月有实质爬坡上涨，K线呈现碎步小阳，回踩 20 日均线时潜伏。")
    
    st.sidebar.header("⚙️ 慢牛参数设置")
    market_cap_range = st.sidebar.slider("总市值范围 (亿元)", 10, 3000, (30, 150), 10, key="bull_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 800, key="bull_num")
    max_distance = st.sidebar.slider("允许偏离 20日线最大幅度 (%)", 0.0, 5.0, 2.0, 0.5) / 100

    if st.button("🚀 开始慢牛全市场扫描", type="primary"):
        with st.spinner("📡 正在获取行情并深度过滤 (可能需要1-2分钟)..."):
            all_stocks_df = fetch_all_stocks_sina()
            filtered_df = all_stocks_df[(all_stocks_df['market_cap'] >= market_cap_range[0]) & (all_stocks_df['market_cap'] <= market_cap_range[1])]
            pool_to_scan = filtered_df.sort_values('market_cap').head(max_scan_num).to_dict('records')
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            matched_stocks, historical_data_dict = [], {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                # 慢牛需要 120 天K线
                future_to_stock = {executor.submit(fetch_sina_kline, stock, 120): stock for stock in pool_to_scan}
                for i, future in enumerate(as_completed(future_to_stock)):
                    df, stock_info = future.result()
                    if df is not None:
                        historical_data_dict[stock_info['symbol']] = df
                        is_match, info = check_stealth_bull(df, stock_info, max_distance)
                        if is_match: matched_stocks.append(info)
                    progress_bar.progress((i + 1) / len(pool_to_scan))
                    status_text.text(f"已排查: {i+1} / {len(pool_to_scan)} | 发现慢牛: {len(matched_stocks)} 只")
            
        if matched_stocks:
            st.success(f"🎉 发现 {len(matched_stocks)} 只符合慢牛形态！")
            results_df = pd.DataFrame(matched_stocks)
            st.dataframe(results_df, use_container_width=True)
            
            results_df['显示名称'] = results_df['名称'] + " (" + results_df['代码'] + ")"
            selected_display = st.selectbox("查看专业 K 线图：", results_df['显示名称'].tolist(), key="bull_plot")
            
            if selected_display:
                sym = results_df[results_df['显示名称'] == selected_display].iloc[0]['代码']
                chart_df = historical_data_dict[sym]
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
                fig.add_trace(go.Candlestick(x=chart_df['day'], open=chart_df['open'], high=chart_df['high'], low=chart_df['low'], close=chart_df['close'], name='K线'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA60'], line=dict(color='blue', width=1.5), name='MA60'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA120'], line=dict(color='purple', width=1.5), name='MA120'), row=1, col=1)
                colors = ['red' if close > open else 'green' for close, open in zip(chart_df['close'], chart_df['open'])]
                fig.add_trace(go.Bar(x=chart_df['day'], y=chart_df['volume'], marker_color=colors, name='成交量'), row=2, col=1)
                fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False, height=600)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("无符合慢牛条件的股票，请放宽条件或等待市场企稳。")


# =====================================================================
# 武器库 2：游资热钱捕捉器 (超短/波段)
# =====================================================================
def check_hot_money_pattern(df, stock_info, strategy):
    if df is None or len(df) < 30: return False, None
    df['MA5'], df['MA10'], df['MA20'] = df['close'].rolling(5).mean(), df['close'].rolling(10).mean(), df['close'].rolling(20).mean()
    df['pct_change'] = df['close'].pct_change()
    
    last_15 = df.tail(15).reset_index(drop=True)
    current = last_15.iloc[-1]
    surge_days = last_15[last_15['pct_change'] >= 0.085]
    if surge_days.empty: return False, None
    
    surge_day = surge_days.iloc[-1]
    surge_idx = surge_day.name
    if surge_idx >= len(last_15) - 2: return False, None
    post_surge_df = last_15.iloc[surge_idx+1:]
    
    if strategy == "🐉 龙回头 (缩量回踩均线反抽)":
        is_near_support = (abs(current['close'] - current['MA10'])/current['MA10'] <= 0.02) or (abs(current['close'] - current['MA20'])/current['MA20'] <= 0.02)
        if is_near_support and (current['volume'] < surge_day['volume'] * 0.6) and (current['close'] >= current['MA20'] * 0.98):
            return True, {'代码': stock_info['symbol'], '名称': stock_info['name'], '现价': round(current['close'], 2), '暴涨日涨幅': f"{round(surge_day['pct_change']*100, 2)}%", '状态': '缩量回踩，潜伏反抽'}
            
    elif strategy == "✈️ 空中加油 (大阳线后高位横盘)":
        half_line = surge_day['open'] + (surge_day['close'] - surge_day['open']) / 2
        if all(post_surge_df['low'] >= half_line * 0.98) and (post_surge_df['close'].max() <= surge_day['close'] * 1.12) and (current['volume'] < surge_day['volume'] * 0.8):
            return True, {'代码': stock_info['symbol'], '名称': stock_info['name'], '现价': round(current['close'], 2), '暴涨日涨幅': f"{round(surge_day['pct_change']*100, 2)}%", '状态': '高位横盘，即将变盘'}
            
    return False, None

if app_mode == "🔥 模式二：游资热钱捕捉器 (超短线)":
    st.title("🔥 游资热钱捕捉器 (动态溯源版)")
    st.markdown("**策略逻辑**：只看过去15天内【上过涨幅榜】的热门股，在它们洗盘跌到关键支撑位（龙回头），或高位拒绝下跌（空中加油）时捕捉二波机会。")
    
    st.sidebar.header("⚙️ 游资战法设置")
    strategy_choice = st.sidebar.radio("选择接力形态：", ["🐉 龙回头 (缩量回踩均线反抽)", "✈️ 空中加油 (大阳线后高位横盘)"])
    market_cap_range = st.sidebar.slider("总市值范围 (亿元)", 10, 800, (30, 300), 10, key="hot_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 1000, key="hot_num")

    if st.button(f"🚀 开始扫描 [{strategy_choice.split(' ')[1]}] 机会", type="primary"):
        with st.spinner("📡 正在向后回测寻找暴涨基因..."):
            all_stocks_df = fetch_all_stocks_sina()
            filtered_df = all_stocks_df[(all_stocks_df['market_cap'] >= market_cap_range[0]) & (all_stocks_df['market_cap'] <= market_cap_range[1])]
            pool_to_scan = filtered_df.sort_values('market_cap').head(max_scan_num).to_dict('records')
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            matched_stocks, historical_data_dict = [], {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                # 短线战法只需要 60 天K线，速度比慢牛快一倍！
                future_to_stock = {executor.submit(fetch_sina_kline, stock, 60): stock for stock in pool_to_scan}
                for i, future in enumerate(as_completed(future_to_stock)):
                    df, stock_info = future.result()
                    if df is not None:
                        historical_data_dict[stock_info['symbol']] = df
                        is_match, info = check_hot_money_pattern(df, stock_info, strategy_choice)
                        if is_match: matched_stocks.append(info)
                    progress_bar.progress((i + 1) / len(pool_to_scan))
                    status_text.text(f"已排查: {i+1} / {len(pool_to_scan)} | 发现游资标的: {len(matched_stocks)} 只")
            
        if matched_stocks:
            st.success(f"🎉 发现 {len(matched_stocks)} 只符合 {strategy_choice.split(' ')[1]} 的强势股！")
            results_df = pd.DataFrame(matched_stocks)
            st.dataframe(results_df, use_container_width=True)
            
            results_df['显示名称'] = results_df['名称'] + " (" + results_df['代码'] + ")"
            selected_display = st.selectbox("查看游资接力 K 线图：", results_df['显示名称'].tolist(), key="hot_plot")
            
            if selected_display:
                sym = results_df[results_df['显示名称'] == selected_display].iloc[0]['代码']
                chart_df = historical_data_dict[sym]
                chart_df['MA5'], chart_df['MA10'], chart_df['MA20'] = chart_df['close'].rolling(5).mean(), chart_df['close'].rolling(10).mean(), chart_df['close'].rolling(20).mean()
                
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
                fig.add_trace(go.Candlestick(x=chart_df['day'], open=chart_df['open'], high=chart_df['high'], low=chart_df['low'], close=chart_df['close'], name='K线'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA5'], line=dict(color='white', width=1.5), name='MA5 (攻击)'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA10'], line=dict(color='yellow', width=1.5), name='MA10 (操盘)'), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df['MA20'], line=dict(color='magenta', width=1.5), name='MA20 (生命)'), row=1, col=1)
                
                colors = ['red' if close > open else 'green' for close, open in zip(chart_df['close'], chart_df['open'])]
                fig.add_trace(go.Bar(x=chart_df['day'], y=chart_df['volume'], marker_color=colors, name='成交量'), row=2, col=1)
                fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False, height=600)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("近期无符合该形态的热门股，可能市场处于混沌期或缺乏主线。")
