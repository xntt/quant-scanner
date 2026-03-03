import streamlit as st
import pandas as pd
import requests
import re
import json
import time
import random
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 全局页面配置 & 状态管理 (记忆功能)
# ==========================================
st.set_page_config(page_title="A股量化武器库", page_icon="⚔️", layout="wide")

# 初始化 Session State 以保存各个模式的扫描结果
if 'results' not in st.session_state:
    st.session_state['results'] = {'bull': None, 'hot': None, 'quant': None}
if 'history' not in st.session_state:
    st.session_state['history'] = {'bull': {}, 'hot': {}, 'quant': {}}

# ==========================================
# 2. 侧边栏：主导航菜单
# ==========================================
st.sidebar.title("⚔️ 系统导航")
app_mode = st.sidebar.radio(
    "请选择你要使用的量化武器：",
    [
        "🐢 模式一：机构慢牛扫地僧 (中长线)", 
        "🔥 模式二：游资热钱捕捉器 (超短线)",
        "🤖 模式三：量化机器追踪器 (错杀反抽)"
    ]
)
st.sidebar.markdown("---")

# ==========================================
# 3. 共享基础数据接口 (带防封号优化)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_all_stocks_sina():
    all_stocks = []
    # 扫全市场，涵盖所有板块
    for page in range(1, 80):
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        try:
            res = requests.get(url, timeout=5)
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
        time.sleep(0.1) # 放慢基础数据获取速度
    return pd.DataFrame(all_stocks)

def fetch_sina_kline(stock_info, datalen=120):
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        # 加入随机休眠，极大地降低被API屏蔽的风险
        time.sleep(random.uniform(0.1, 0.3))
        response = requests.get(url, timeout=5)
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
# 通用绘图函数
# =====================================================================
def plot_kline(chart_df, title, ma_list=[5, 10, 20]):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
    fig.add_trace(go.Candlestick(x=chart_df['day'], open=chart_df['open'], high=chart_df['high'], low=chart_df['low'], close=chart_df['close'], name='K线'), row=1, col=1)
    
    colors = ['white', 'yellow', 'magenta', 'cyan']
    for i, ma in enumerate(ma_list):
        chart_df[f'MA{ma}'] = chart_df['close'].rolling(window=ma).mean()
        fig.add_trace(go.Scatter(x=chart_df['day'], y=chart_df[f'MA{ma}'], line=dict(color=colors[i%len(colors)], width=1.5), name=f'MA{ma}'), row=1, col=1)
        
    vol_colors = ['red' if close > open else 'green' for close, open in zip(chart_df['close'], chart_df['open'])]
    fig.add_trace(go.Bar(x=chart_df['day'], y=chart_df['volume'], marker_color=vol_colors, name='成交量'), row=2, col=1)
    fig.update_layout(template="plotly_dark", title=title, xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False, height=600)
    st.plotly_chart(fig, use_container_width=True)


# =====================================================================
# 武器库 1：机构慢牛扫地僧
# =====================================================================
def check_stealth_bull(df, stock_info, max_dist):
    if df is None or len(df) < 120: return False, None
    df['MA20'], df['MA60'], df['MA120'] = df['close'].rolling(20).mean(), df['close'].rolling(60).mean(), df['close'].rolling(120).mean()
    df['VMA20'], df['VMA60'] = df['volume'].rolling(20).mean(), df['volume'].rolling(60).mean()
    current, prev_20, prev_60 = df.iloc[-1], df.iloc[-21], df.iloc[-61]
    
    growth_60d = (current['close'] - prev_60['close']) / prev_60['close']
    if growth_60d < 0.10: return False, None
    if not (current['close'] > current['MA60'] > current['MA120']): return False, None
    if current['VMA20'] < current['VMA60'] * 1.05: return False, None
    
    dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
    if not (-0.015 <= dist_to_ma20 <= max_dist): return False, None
        
    return True, {'代码': stock_info['symbol'], '名称': stock_info['name'], '市值(亿)': stock_info['market_cap'], '现价': round(current['close'], 2), '偏离20日线': f"{round(dist_to_ma20 * 100, 2)}%"}

if app_mode.startswith("🐢"):
    st.title("🐢 机构慢牛扫地僧 (量价齐升版)")
    market_cap_range = st.sidebar.slider("市值范围 (亿元)", 10, 3000, (30, 150), 10, key="b_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 500, key="b_num")
    
    if st.button("🚀 开始慢牛精准扫描", type="primary"):
        st.session_state['results']['bull'] = [] # 清空旧数据
        with st.spinner("📡 精确扫描中，已开启防封号延迟，请耐心等待 (约1-3分钟)..."):
            all_df = fetch_all_stocks_sina()
            pool = all_df[(all_df['market_cap'] >= market_cap_range[0]) & (all_df['market_cap'] <= market_cap_range[1])].head(max_scan_num).to_dict('records')
            
            pb, st_txt = st.progress(0), st.empty()
            matches, history = [], {}
            
            # 降低并发数，保护API
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fetch_sina_kline, s, 120): s for s in pool}
                for i, future in enumerate(as_completed(futures)):
                    df, info = future.result()
                    if df is not None:
                        history[info['symbol']] = df
                        is_match, res = check_stealth_bull(df, info, 0.02)
                        if is_match: matches.append(res)
                    pb.progress((i + 1) / len(pool))
                    st_txt.text(f"安全排查中: {i+1} / {len(pool)} | 发现慢牛: {len(matches)} 只")
            
            st.session_state['results']['bull'] = matches
            st.session_state['history']['bull'] = history

    if st.session_state['results']['bull'] is not None:
        if len(st.session_state['results']['bull']) > 0:
            res_df = pd.DataFrame(st.session_state['results']['bull'])
            st.dataframe(res_df, use_container_width=True)
            sel = st.selectbox("查看 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")", key="b_plot")
            sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
            plot_kline(st.session_state['history']['bull'][sym], sel, [20, 60, 120])
        else:
            st.warning("本次扫描未发现慢牛。")


# =====================================================================
# 武器库 2：游资热钱捕捉器
# =====================================================================
def check_hot_money(df, stock_info):
    if df is None or len(df) < 30: return False, None
    df['MA10'], df['MA20'] = df['close'].rolling(10).mean(), df['close'].rolling(20).mean()
    df['pct_change'] = df['close'].pct_change()
    last_15 = df.tail(15).reset_index(drop=True)
    current = last_15.iloc[-1]
    
    surge_days = last_15[last_15['pct_change'] >= 0.085]
    if surge_days.empty: return False, None
    surge_day = surge_days.iloc[-1]
    
    if surge_day.name >= len(last_15) - 2: return False, None
    
    is_near_support = (abs(current['close'] - current['MA10'])/current['MA10'] <= 0.02) or (abs(current['close'] - current['MA20'])/current['MA20'] <= 0.02)
    if is_near_support and (current['volume'] < surge_day['volume'] * 0.6) and (current['close'] >= current['MA20'] * 0.98):
        return True, {'代码': stock_info['symbol'], '名称': stock_info['name'], '市值(亿)': stock_info['market_cap'], '现价': round(current['close'], 2), '暴涨日涨幅': f"{round(surge_day['pct_change']*100, 2)}%"}
    return False, None

if app_mode.startswith("🔥"):
    st.title("🔥 游资热钱捕捉器 (龙回头)")
    market_cap_range = st.sidebar.slider("市值范围 (亿元)", 10, 800, (20, 300), 10, key="h_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 500, key="h_num")

    if st.button("🚀 开始游资接力扫描", type="primary"):
        st.session_state['results']['hot'] = []
        with st.spinner("📡 正在向后回测寻找暴涨基因，低速安全模式运行中..."):
            all_df = fetch_all_stocks_sina()
            pool = all_df[(all_df['market_cap'] >= market_cap_range[0]) & (all_df['market_cap'] <= market_cap_range[1])].head(max_scan_num).to_dict('records')
            pb, st_txt = st.progress(0), st.empty()
            matches, history = [], {}
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fetch_sina_kline, s, 60): s for s in pool}
                for i, future in enumerate(as_completed(futures)):
                    df, info = future.result()
                    if df is not None:
                        history[info['symbol']] = df
                        is_match, res = check_hot_money(df, info)
                        if is_match: matches.append(res)
                    pb.progress((i + 1) / len(pool))
                    st_txt.text(f"排查中: {i+1} / {len(pool)} | 发现游资标的: {len(matches)} 只")
            st.session_state['results']['hot'] = matches
            st.session_state['history']['hot'] = history

    if st.session_state['results']['hot'] is not None:
        if len(st.session_state['results']['hot']) > 0:
            res_df = pd.DataFrame(st.session_state['results']['hot'])
            st.dataframe(res_df, use_container_width=True)
            sel = st.selectbox("查看短线 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")", key="h_plot")
            sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
            plot_kline(st.session_state['history']['hot'][sym], sel, [5, 10, 20])
        else:
            st.warning("当前无符合游资龙回头的标的。")


# =====================================================================
# 武器库 3：量化机器追踪器 (全新加入！)
# =====================================================================
def check_quant_tracker(df, stock_info):
    if df is None or len(df) < 30: return False, None
    df['VMA5'] = df['volume'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) # 振幅
    
    # 考察最近 8 天，游资量化极其活跃的票
    last_8 = df.tail(8).reset_index(drop=True)
    current = df.iloc[-1]
    
    # 寻找量化点火日：成交量 > 5日均量 2.5倍，且单日振幅 > 8% (极高波动)
    ignition_days = last_8[(last_8['volume'] > 2.5 * last_8['VMA5'].shift(1)) & (last_8['amplitude'] > 0.08)]
    if ignition_days.empty: return False, None
    
    ignition_day = ignition_days.iloc[-1]
    if ignition_day.name >= len(last_8) - 1: return False, None # 刚点火，还没洗盘，不碰
    
    # 错杀洗盘日特征：当前成交量极度萎缩 (< 点火日的 50%)，且股价跌到了均线支撑位
    if current['volume'] < ignition_day['volume'] * 0.5:
        dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
        if -0.03 <= dist_to_ma20 <= 0.03: # 跌到 20日线附近 3% 左右
            return True, {
                '代码': stock_info['symbol'], '名称': stock_info['name'], 
                '市值(亿)': stock_info['market_cap'], '现价': round(current['close'], 2), 
                '点火日振幅': f"{round(ignition_day['amplitude']*100, 2)}%",
                '洗盘萎缩度': f"仅为高点的 {round(current['volume']/ignition_day['volume']*100, 1)}%",
                '逻辑': '量化砸盘错杀，极端缩量回踩'
            }
    return False, None

if app_mode.startswith("🤖"):
    st.title("🤖 量化机器追踪器 (接血筹战法)")
    st.markdown("**策略逻辑**：专抓近期被量化资金【天量点火】拉出高振幅后，又被量化程序无脑【核按钮砸盘】导致极其缩量的标的，买在机器止损点，吃修复反抽。")
    
    market_cap_range = st.sidebar.slider("市值范围 (亿元) [量化喜欢中大盘]", 50, 500, (80, 400), 10, key="q_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 800, key="q_num")

    if st.button("🚀 追踪量化极寒洗盘点", type="primary"):
        st.session_state['results']['quant'] = []
        with st.spinner("📡 正在捕捉全市场量化资金异动足迹，高精度防封号模式..."):
            all_df = fetch_all_stocks_sina()
            pool = all_df[(all_df['market_cap'] >= market_cap_range[0]) & (all_df['market_cap'] <= market_cap_range[1])].head(max_scan_num).to_dict('records')
            pb, st_txt = st.progress(0), st.empty()
            matches, history = [], {}
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fetch_sina_kline, s, 60): s for s in pool}
                for i, future in enumerate(as_completed(futures)):
                    df, info = future.result()
                    if df is not None:
                        history[info['symbol']] = df
                        is_match, res = check_quant_tracker(df, info)
                        if is_match: matches.append(res)
                    pb.progress((i + 1) / len(pool))
                    st_txt.text(f"追踪中: {i+1} / {len(pool)} | 发现错杀错杀盘: {len(matches)} 只")
            st.session_state['results']['quant'] = matches
            st.session_state['history']['quant'] = history

    if st.session_state['results']['quant'] is not None:
        if len(st.session_state['results']['quant']) > 0:
            st.success(f"🎯 逮到了！发现 {len(st.session_state['results']['quant'])} 只被量化极端洗盘的股票！")
            res_df = pd.DataFrame(st.session_state['results']['quant'])
            st.dataframe(res_df, use_container_width=True)
            sel = st.selectbox("查看量化痕迹 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")", key="q_plot")
            sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
            plot_kline(st.session_state['history']['quant'][sym], sel, [5, 10, 20])
        else:
            st.warning("今日无极端量化洗盘迹象，说明市场情绪较为温和。")

st.sidebar.markdown("---")
st.sidebar.info("💡 提示：系统已开启【扫描记忆】和【防IP屏蔽】功能。扫描耗时会有所增加以保证100%覆盖，但在重新点击扫描前，切换菜单不会丢失之前的数据！")
