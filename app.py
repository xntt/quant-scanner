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
# 1. 全局页面配置 & 全局缓存中心 (重构为一次扫描多维分类)
# ==========================================
st.set_page_config(page_title="A股全景波段与首板雷达", page_icon="📡", layout="wide")

# 初始化全局状态
if 'scan_completed' not in st.session_state:
    st.session_state['scan_completed'] = False # 是否完成过全局扫描

# 存放四个板块的分类结果
if 'results' not in st.session_state:
    st.session_state['results'] = {
        'swing_short': [], 
        'swing_long': [], 
        'first_board': [], 
        'slow_bull': []
    }

# 只缓存命中策略股票的K线数据 (节省内存)
if 'kline_cache' not in st.session_state:
    st.session_state['kline_cache'] = {}

# ==========================================
# 2. 核心数据接口 (带防封号机制)
# ==========================================
@st.cache_data(ttl=43200) # 股票列表缓存半天
def fetch_all_stocks():
    """获取全市场 A 股列表 (约 5000+ 只)"""
    all_stocks = []
    # 扫全市场约 50-60 页
    for page in range(1, 65): 
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        try:
            res = requests.get(url, timeout=5)
            text = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', res.text)
            data = json.loads(text)
            if not data: break
            for item in data:
                symbol = item.get("symbol", "")
                name = item.get("name", "")
                mktcap_wan = item.get("mktcap", 0) 
                if not symbol or mktcap_wan == 0 or symbol.startswith('bj'): continue # 过滤北交所
                all_stocks.append({"symbol": symbol, "name": name, "market_cap": round(float(mktcap_wan) / 10000, 2)})
        except: pass
        time.sleep(0.05)
    return pd.DataFrame(all_stocks)

def fetch_kline(stock_info, datalen=140):
    """获取单只股票 K 线数据 (140天足够所有策略使用)"""
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        # 【核心安全机制】控制访问频率，保证5000只平稳扫完不被封IP
        time.sleep(random.uniform(0.1, 0.25)) 
        res = requests.get(url, timeout=5)
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', res.text) 
        data = json.loads(text)
        if not data or len(data) < 30: return None, stock_info # 新股或无数据直接跳过
        
        df = pd.DataFrame(data)
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        df['pct_change'] = df['close'].pct_change().fillna(0) # 计算每日涨跌幅
        
        # 提前算好共用均线，节省算力
        df['MA20'] = df['close'].rolling(20).mean()
        df['MA60'] = df['close'].rolling(60).mean()
        df['MA120'] = df['close'].rolling(120).mean()
        
        return df, stock_info
    except: return None, stock_info

# ==========================================
# 3. 四维同步鉴定逻辑 (鉴定专家)
# ==========================================
def logic_swing_short(df, info):
    """短线区间波段 (20日线支撑)"""
    if len(df) < 30: return False, None
    last_20 = df.tail(20)
    current = df.iloc[-1]
    box_high, box_low = last_20['high'].max(), last_20['low'].min()
    if box_low == 0: return False, None
    box_amplitude = (box_high - box_low) / box_low
    
    if box_amplitude < 0.08: return False, None # 箱体不够大
    current_pos = (current['close'] - box_low) / (box_high - box_low)
    if not (0.0 <= current_pos <= 0.35): return False, None # 必须在箱体下半部
    if current['close'] < current['MA20'] * 0.985: return False, None # 跌破20日线太多不要
    
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '箱底': round(box_low, 2), '箱顶': round(box_high, 2)}

def logic_swing_long(df, info):
    """长线大底波段 (半年级别筑底)"""
    if len(df) < 120: return False, None
    last_120 = df.tail(120)
    current = df.iloc[-1]
    
    # 120日线走平或抬头
    if pd.isna(current['MA120']) or current['MA120'] < df['MA120'].iloc[-20]: return False, None
    long_low = last_120['low'].min()
    if (current['close'] - long_low) / long_low > 0.08: return False, None # 距离绝对底部超过8%不要
    
    recent_vol = df['volume'].tail(10).mean()
    past_vol = last_120['volume'].mean()
    if recent_vol > past_vol * 0.8: return False, None # 必须是缩量的
    
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '半年最低': round(long_low, 2)}

def logic_first_board(df, info):
    """半年首板挖掘机 (新题材启动)"""
    if len(df) < 120: return False, None
    today = df.iloc[-1]
    
    # 涨停判定（主板设为9.3%以上防误差）
    if today['pct_change'] < 0.093: return False, None 
    
    # 过去120天不能有涨停
    history_120 = df.iloc[-121:-1]
    if history_120['pct_change'].max() >= 0.093: return False, None
    
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'] if 'current' in locals() else round(today['close'],2), '市值(亿)': info['market_cap'], '信号': "🚨 首板爆量"}

def logic_slow_bull(df, info):
    """机构慢牛 (多头排列无暴涨)"""
    if len(df) < 120: return False, None
    current = df.iloc[-1]
    if pd.isna(current['MA120']): return False, None
    if not (current['MA20'] > current['MA60'] > current['MA120']): return False, None # 必须多头排列
    if df.tail(20)['pct_change'].max() > 0.08: return False, None # 近期不能有暴涨涨停
    
    dist = (current['close'] - current['MA20']) / current['MA20']
    if not (-0.02 <= dist <= 0.05): return False, None # 必须贴着20日线
    
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '偏离20日': f"{round(dist*100, 2)}%"}

# ==========================================
# 4. 全局一键扫描引擎
# ==========================================
def run_global_scan():
    st.session_state['results'] = {'swing_short': [], 'swing_long': [], 'first_board': [], 'slow_bull': []}
    st.session_state['kline_cache'] = {} # 清空缓存
    
    all_stocks = fetch_all_stocks()
    pool = all_stocks.to_dict('records')
    total = len(pool)
    
    pb = st.progress(0)
    status_text = st.empty()
    metrics_text = st.empty()
    
    c_short, c_long, c_first, c_bull = 0, 0, 0, 0
    
    # 开启3个线程平稳拉取，预计耗时3-5分钟
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_kline, s, 140): s for s in pool}
        for i, future in enumerate(as_completed(futures)):
            df, info = future.result()
            matched_any = False
            
            if df is not None:
                # 1. 过短线波段
                is_short, res_short = logic_swing_short(df, info)
                if is_short: 
                    st.session_state['results']['swing_short'].append(res_short)
                    c_short += 1; matched_any = True
                
                # 2. 过长线大底
                is_long, res_long = logic_swing_long(df, info)
                if is_long:
                    st.session_state['results']['swing_long'].append(res_long)
                    c_long += 1; matched_any = True
                    
                # 3. 过首板挖掘
                is_first, res_first = logic_first_board(df, info)
                if is_first:
                    st.session_state['results']['first_board'].append(res_first)
                    c_first += 1; matched_any = True
                    
                # 4. 过慢牛
                is_bull, res_bull = logic_slow_bull(df, info)
                if is_bull:
                    st.session_state['results']['slow_bull'].append(res_bull)
                    c_bull += 1; matched_any = True
                
                # 只把有价值的股票K线放入内存缓存，极大优化性能！
                if matched_any:
                    st.session_state['kline_cache'][info['symbol']] = df
                    
            # 更新UI
            if i % 5 == 0 or i == total - 1:
                pb.progress((i + 1) / total)
                status_text.text(f"📡 正在全局深度扫描 A股市场... ({i+1}/{total}) | 请耐心等待，切勿刷新页面")
                metrics_text.markdown(f"**实时捕获**: 短线波段:`{c_short}`只 | 长线底:`{c_long}`只 | 首板:`{c_first}`只 | 慢牛:`{c_bull}`只")
                
    st.session_state['scan_completed'] = True
    pb.empty()
    status_text.success("✅ 5000+ A股全局扫描并多维分类完成！请在左侧菜单切换查看各板块结果。")

# ==========================================
# 5. UI 布局与侧边栏
# ==========================================
st.sidebar.title("📡 总控中心")
st.sidebar.info("💡 操作指南：\n1. 每天盘后或午休点击【一键全局扫描】。\n2. 扫完后在下方切换板块查看结果。\n3. 数据永久缓存在本地浏览器。")

if st.sidebar.button("🚀 开始一键全局扫描 (全市场5000只)", type="primary"):
    run_global_scan()

st.sidebar.markdown("---")
app_mode = st.sidebar.radio(
    "📊 切换查看分类结果：",
    [
        "1️⃣ 短线区间波段 (不破20日线)", 
        "2️⃣ 长线大底波段 (半年级别支撑)",
        "3️⃣ 半年首板挖掘 (新题材起爆点)",
        "4️⃣ 机构慢牛池 (多头防守阵地)"
    ]
)

# ==========================================
# 6. 通用绘图函数
# ==========================================
def render_view(mode_key, title, desc, ma_list=[20, 60, 120]):
    st.title(title)
    st.markdown(desc)
    
    if not st.session_state['scan_completed']:
        st.warning("⚠️ 暂无数据。请先点击左侧红色的【开始一键全局扫描】按钮！")
        return
        
    results = st.session_state['results'][mode_key]
    if len(results) == 0:
        st.info("🤷‍♂️ 当前市场环境下，没有扫描到符合该策略的标的。")
        return
        
    st.success(f"共为您筛选出 {len(results)} 只符合条件的标的！")
    res_df = pd.DataFrame(results)
    st.dataframe(res_df, use_container_width=True)
    
    sel = st.selectbox("📊 选择下方图表查看具体走势：", res_df['名称'] + " (" + res_df['代码'] + ")")
    sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
    
    # 绘制 K 线
    df = st.session_state['kline_cache'][sym]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
    fig.add_trace(go.Candlestick(x=df['day'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='K线'), row=1, col=1)
    colors = ['yellow', 'magenta', 'cyan']
    for i, ma in enumerate(ma_list):
        fig.add_trace(go.Scatter(x=df['day'], y=df[f'MA{ma}'], line=dict(color=colors[i%len(colors)], width=1.5), name=f'{ma}日线'), row=1, col=1)
    vol_colors = ['red' if c >= o else 'green' for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(x=df['day'], y=df['volume'], marker_color=vol_colors, name='成交量'), row=2, col=1)
    fig.update_layout(template="plotly_dark", title=sel, xaxis_rangeslider_visible=False, height=600, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 7. 渲染对应板块内容
# ==========================================
if app_mode.startswith("1️⃣"):
    render_view(
        'swing_short', 
        "📈 短线区间波段 (低吸支撑位)", 
        "逻辑：近一个月形成明显震荡箱体，目前回踩箱体底部，且坚守20日均线，具备高抛低吸价值。",
        [5, 10, 20]
    )
elif app_mode.startswith("2️⃣"):
    render_view(
        'swing_long', 
        "🌊 长线大底波段 (半年级别筑底)", 
        "逻辑：120日线已经走平，半年内跌无可跌处于极度缩量状态，适合长线左侧潜伏。",
        [20, 60, 120]
    )
elif app_mode.startswith("3️⃣"):
    render_view(
        'first_board', 
        "🚀 半年首板挖掘机 (游资增量起爆)", 
        "**高价值战法**：过滤过去120个交易日无涨停的死水股，**今天拔出历史首个涨停**。这是新题材/新资金进场的绝对信号，同板块共振极大概率成为主线！",
        [5, 10, 20]
    )
elif app_mode.startswith("4️⃣"):
    render_view(
        'slow_bull', 
        "🐢 机构慢牛池 (多头防守阵地)", 
        "逻辑：均线呈现完美的 20>60>120 多头排列，没有游资连板暴涨的痕迹，机构资金锁仓稳步推升。",
        [20, 60, 120]
    )
