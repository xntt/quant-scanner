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
st.set_page_config(page_title="A股全天候量化武器库", page_icon="⚔️", layout="wide")

# 初始化 Session State 以保存各个模式的扫描结果，保证切换不丢失
if 'results' not in st.session_state:
    st.session_state['results'] = {'bull': None, 'hot': None, 'quant': None, 'resonance': None, 'monster': None}
if 'history' not in st.session_state:
    st.session_state['history'] = {'bull': {}, 'hot': {}, 'quant': {}, 'resonance': {}, 'monster': {}}

# ==========================================
# 2. 侧边栏：主导航菜单
# ==========================================
st.sidebar.title("⚔️ 系统导航")
app_mode = st.sidebar.radio(
    "请选择你要使用的量化武器：",
    [
        "🐢 模式一：机构慢牛扫地僧 (中长线)", 
        "🔥 模式二：游资热钱捕捉器 (龙回头)",
        "🤖 模式三：量化机器追踪器 (错杀反抽)",
        "🏛️ 模式四：国家队共振起爆 (黄金坑底)",
        "🐉 模式五：纯情绪妖股探测器 (连板接力)" 
    ]
)
st.sidebar.markdown("---")
st.sidebar.info("💡 提示：系统已开启【扫描记忆】和【防封号延迟】功能。切换菜单不会丢失之前的数据！")

# ==========================================
# 3. 共享基础数据接口 (带防封号机制)
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
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    df['MA120'] = df['close'].rolling(120).mean()
    df['VMA20'] = df['volume'].rolling(20).mean()
    df['VMA60'] = df['volume'].rolling(60).mean()
    
    current = df.iloc[-1]
    prev_60 = df.iloc[-61]
    
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
        st.session_state['results']['bull'] = []
        with st.spinner("📡 精确扫描中，已开启防封号延迟，请耐心等待..."):
            all_df = fetch_all_stocks_sina()
            pool = all_df[(all_df['market_cap'] >= market_cap_range[0]) & (all_df['market_cap'] <= market_cap_range[1])].head(max_scan_num).to_dict('records')
            
            pb, st_txt = st.progress(0), st.empty()
            matches, history = [], {}
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
    df['MA10'] = df['close'].rolling(10).mean()
    df['MA20'] = df['close'].rolling(20).mean()
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
# 武器库 3：量化机器追踪器 
# =====================================================================
def check_quant_tracker(df, stock_info):
    if df is None or len(df) < 30: return False, None
    df['VMA5'] = df['volume'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) 
    
    last_8 = df.tail(8).reset_index(drop=True)
    current = df.iloc[-1]
    
    ignition_days = last_8[(last_8['volume'] > 2.5 * last_8['VMA5'].shift(1)) & (last_8['amplitude'] > 0.08)]
    if ignition_days.empty: return False, None
    
    ignition_day = ignition_days.iloc[-1]
    if ignition_day.name >= len(last_8) - 1: return False, None 
    
    if current['volume'] < ignition_day['volume'] * 0.5:
        dist_to_ma20 = (current['close'] - current['MA20']) / current['MA20']
        if -0.03 <= dist_to_ma20 <= 0.03: 
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


# =====================================================================
# 武器库 4：国家队共振起爆 (抄底神针)
# =====================================================================
def check_national_resonance(df, stock_info):
    if df is None or len(df) < 40: return False, None
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA10'] = df['close'].rolling(10).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['VMA5'] = df['volume'].rolling(5).mean()
    df['pct_change'] = df['close'].pct_change()
    
    last_15 = df.tail(15).reset_index(drop=True)
    current = df.iloc[-1]
    
    lowest_idx = last_15['low'].idxmin()
    lowest_day = last_15.iloc[lowest_idx]
    
    if (lowest_day['MA20'] - lowest_day['low']) / lowest_day['MA20'] < 0.10: 
        return False, None 
        
    pivot_day = last_15.iloc[lowest_idx]
    next_day = last_15.iloc[lowest_idx + 1] if lowest_idx + 1 < len(last_15) else pivot_day
    
    is_massive_volume = pivot_day['volume'] > 1.8 * pivot_day['VMA5'] or next_day['volume'] > 1.8 * next_day['VMA5']
    is_strong_reversal = pivot_day['pct_change'] > 0.05 or next_day['pct_change'] > 0.05 or (min(pivot_day['open'], pivot_day['close']) - pivot_day['low'] > abs(pivot_day['close'] - pivot_day['open']) * 2)
    
    if not (is_massive_volume and is_strong_reversal): return False, None
    
    if current['close'] > current['MA5'] and current['close'] > current['MA10']:
        return True, {
            '代码': stock_info['symbol'], '名称': stock_info['name'], 
            '市值(亿)': stock_info['market_cap'], '现价': round(current['close'], 2), 
            '深坑最大偏离': f"{round((lowest_day['MA20'] - lowest_day['low'])/lowest_day['MA20']*100, 1)}%",
            '逻辑': '黄金坑暴涨，短期均线已收复'
        }
    return False, None

if app_mode.startswith("🏛️"):
    st.title("🏛️ 国家队共振起爆 (黄金坑底)")
    st.markdown("**策略逻辑**：专抓在系统性暴跌中，跌破20日线超10%砸出黄金坑，随后被神秘大资金爆量V型反转，并迅速收复短线均线的极强共振标的。")
    
    market_cap_range = st.sidebar.slider("市值范围 (亿元) [全盘扫描]", 20, 2000, (30, 800), 10, key="r_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 5000, 1500, key="r_num")

    if st.button("🚀 寻找国家队共振起爆点", type="primary"):
        st.session_state['results']['resonance'] = []
        with st.spinner("📡 正在全市场排查暴跌深V与巨量托底资金痕迹..."):
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
                        is_match, res = check_national_resonance(df, info)
                        if is_match: matches.append(res)
                    pb.progress((i + 1) / len(pool))
                    st_txt.text(f"排查中: {i+1} / {len(pool)} | 发现共振起爆: {len(matches)} 只")
            st.session_state['results']['resonance'] = matches
            st.session_state['history']['resonance'] = history

    if st.session_state['results']['resonance'] is not None:
        if len(st.session_state['results']['resonance']) > 0:
            st.success(f"🚨 重大发现！当前市场有 {len(st.session_state['results']['resonance'])} 只股票触发了【国家队共振起爆】信号！")
            res_df = pd.DataFrame(st.session_state['results']['resonance'])
            st.dataframe(res_df, use_container_width=True)
            sel = st.selectbox("查看深V共振 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")", key="r_plot")
            sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
            plot_kline(st.session_state['history']['resonance'][sym], sel, [5, 10, 20])
        else:
            st.warning("当前市场没有发生系统性的恐慌深V反转。平时无结果属正常现象，请耐心等待极端机会。")


# =====================================================================
# 武器库 5：纯情绪妖股探测器 (连板接力)
# =====================================================================
def check_monster_stock(df, stock_info):
    if df is None or len(df) < 20: return False, None
    df['MA5'] = df['close'].rolling(5).mean()
    df['pct_change'] = df['close'].pct_change()
    
    last_5 = df.tail(5).reset_index(drop=True)
    current = df.iloc[-1]
    
    # 妖股天条 1：绝对不破5日线。破了就死，坚决不看。
    if current['close'] < current['MA5']: 
        return False, None
        
    # 妖股天条 2：寻找近5天内的“涨停基因” (涨幅大于 9.5% 视为涨停)
    limit_up_days = last_5[last_5['pct_change'] >= 0.095]
    limit_count = len(limit_up_days)
    
    # 如果5天内连 2 个涨停都没有，说明没成妖的潜质
    if limit_count < 2: 
        return False, None
        
    # 妖股天条 3：当前状态必须极强 (收盘价离全天最高价不到 2%)
    is_strong_close = (current['high'] - current['close']) / current['close'] < 0.02
    
    # 过滤掉高位巨量阴线 (防止接盘)
    is_not_dumping = not (current['close'] < current['open'] and current['volume'] > last_5['volume'].mean() * 2)

    if is_strong_close and is_not_dumping:
        return True, {
            '代码': stock_info['symbol'], '名称': stock_info['name'], 
            '市值(亿)': stock_info['market_cap'], '现价': round(current['close'], 2), 
            '近5天涨停数': f"{limit_count} 次",
            '状态': '强势连板接力中'
        }
    return False, None

if app_mode.startswith("🐉"):
    st.title("🐉 纯情绪妖股探测器 (无视基本面)")
    st.markdown("""
    **🔥 策略逻辑**：专抓脱离基本面、纯靠资金接力爆炒的连板妖股（如豫能控股、锋龙股份）。
    **⚠️ 妖股铁律**：1. 只买均线多头排列的主升浪； 2. **一旦跌破5日线，无条件清仓止损，绝不抗单！**
    """)
    
    market_cap_range = st.sidebar.slider("市值范围 (亿元) [妖股通常极小]", 10, 100, (15, 60), 5, key="m_cap")
    max_scan_num = st.sidebar.number_input("最多扫描多少只？", 100, 3000, 800, key="m_num")

    if st.button("🚀 扫描连板妖股基因", type="primary"):
        st.session_state['results']['monster'] = []
        with st.spinner("📡 正在捕捉全市场涨停板游资击鼓传花情绪..."):
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
                        is_match, res = check_monster_stock(df, info)
                        if is_match: matches.append(res)
                    pb.progress((i + 1) / len(pool))
                    st_txt.text(f"深度雷达排查中: {i+1} / {len(pool)} | 发现成妖目标: {len(matches)} 只")
            st.session_state['results']['monster'] = matches
            st.session_state['history']['monster'] = history

    if st.session_state['results']['monster'] is not None:
        if len(st.session_state['results']['monster']) > 0:
            st.error(f"🐲 警告：发现 {len(st.session_state['results']['monster'])} 只具有极强成妖潜质的连板股！高收益伴随极高风险！")
            res_df = pd.DataFrame(st.session_state['results']['monster'])
            st.dataframe(res_df, use_container_width=True)
            sel = st.selectbox("查看妖股 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")", key="m_plot")
            sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
            # 妖股只看超短线：5日线和10日线 (已去除慢速均线)
            plot_kline(st.session_state['history']['monster'][sym], sel, [5, 10])
        else:
            st.warning("当前市场情绪低迷，未扫描到符合 5天2板 以上的连板妖股雏形。")
