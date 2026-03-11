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
# 1. 全局页面配置
# ==========================================
st.set_page_config(page_title="A股全景雷达(防弹存储版)", page_icon="📡", layout="wide")

# ==========================================
# 2. 核心黑科技：全局服务器级内存数据库
# (完美解决点击菜单清零、刷新网页数据丢失的问题)
# ==========================================
@st.cache_resource
def get_global_db():
    """这是全局唯一的数据仓库，只要Python没关，数据绝对不丢"""
    return {
        'results': {'swing_short': [], 'swing_long': [], 'first_board': [], 'slow_bull': []},
        'kline_cache': {},
        'scan_pool': [],
        'scanned_count': 0
    }

# 获取数据库实例
db = get_global_db()

# 控制扫描引擎开关的临时状态(只需要放在session里)
if 'is_scanning' not in st.session_state:
    st.session_state['is_scanning'] = False

# ==========================================
# 3. 核心数据接口 (带防封号机制)
# ==========================================
@st.cache_data(ttl=43200)
def fetch_all_stocks():
    all_stocks = []
    for page in range(1, 65): 
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        try:
            res = requests.get(url, timeout=5)
            text = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', res.text)
            data = json.loads(text)
            if not data: break
            for item in data:
                symbol = item.get("symbol", "")
                mktcap_wan = item.get("mktcap", 0) 
                if not symbol or mktcap_wan == 0 or symbol.startswith('bj'): continue
                all_stocks.append({"symbol": symbol, "name": item.get("name", ""), "market_cap": round(float(mktcap_wan) / 10000, 2)})
        except: pass
    return all_stocks

def fetch_kline(stock_info, datalen=140):
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        time.sleep(random.uniform(0.1, 0.2)) # 防封
        res = requests.get(url, timeout=5)
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', res.text) 
        data = json.loads(text)
        if not data or len(data) < 30: return None, stock_info
        
        df = pd.DataFrame(data)
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        df['pct_change'] = df['close'].pct_change().fillna(0)
        
        df['MA20'] = df['close'].rolling(20).mean()
        df['MA60'] = df['close'].rolling(60).mean()
        df['MA120'] = df['close'].rolling(120).mean()
        return df, stock_info
    except: return None, stock_info

# ==========================================
# 4. 四维鉴定逻辑
# ==========================================
def logic_swing_short(df, info):
    if len(df) < 30: return False, None
    last_20 = df.tail(20)
    current = df.iloc[-1]
    box_high, box_low = last_20['high'].max(), last_20['low'].min()
    if box_low == 0 or (box_high - box_low)/box_low < 0.08: return False, None
    if not (0.0 <= (current['close'] - box_low) / (box_high - box_low) <= 0.35): return False, None
    if current['close'] < current['MA20'] * 0.985: return False, None
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '箱底': round(box_low, 2)}

def logic_swing_long(df, info):
    if len(df) < 120: return False, None
    current = df.iloc[-1]
    if pd.isna(current['MA120']) or current['MA120'] < df['MA120'].iloc[-20]: return False, None
    long_low = df.tail(120)['low'].min()
    if (current['close'] - long_low) / long_low > 0.08: return False, None
    if df['volume'].tail(10).mean() > df.tail(120)['volume'].mean() * 0.8: return False, None
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '半年最低': round(long_low, 2)}

def logic_first_board(df, info):
    if len(df) < 120: return False, None
    today = df.iloc[-1]
    if today['pct_change'] < 0.093: return False, None 
    if df.iloc[-121:-1]['pct_change'].max() >= 0.093: return False, None
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': today['close'], '市值(亿)': info['market_cap'], '信号': "🚨首板"}

def logic_slow_bull(df, info):
    if len(df) < 120: return False, None
    current = df.iloc[-1]
    if pd.isna(current['MA120']) or not (current['MA20'] > current['MA60'] > current['MA120']): return False, None
    if df.tail(20)['pct_change'].max() > 0.08: return False, None
    dist = (current['close'] - current['MA20']) / current['MA20']
    if not (-0.02 <= dist <= 0.05): return False, None
    return True, {'代码': info['symbol'], '名称': info['name'], '现价': current['close'], '市值(亿)': info['market_cap'], '偏离20日': f"{round(dist*100, 2)}%"}

# ==========================================
# 5. 侧边栏控制台
# ==========================================
st.sidebar.title("🕹️ 战术雷达引擎")

# 初始化全市场股票池(存入全局数据库)
if len(db['scan_pool']) == 0:
    db['scan_pool'] = fetch_all_stocks()

total_stocks = len(db['scan_pool'])
current_count = db['scanned_count']

st.sidebar.progress(current_count / total_stocks if total_stocks > 0 else 0)
st.sidebar.markdown(f"**总扫描进度**: `{current_count}` / `{total_stocks}`")

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("▶️ 开始/继续", type="primary"):
        st.session_state['is_scanning'] = True
with col2:
    if st.button("⏸️ 暂停扫描"):
        st.session_state['is_scanning'] = False

if st.sidebar.button("🔄 重置清空所有数据 (慎点)"):
    st.session_state['is_scanning'] = False
    # 彻底清空全局数据库中的记录
    db['scanned_count'] = 0
    db['results'] = {'swing_short': [], 'swing_long': [], 'first_board': [], 'slow_bull': []}
    db['kline_cache'] = {}
    st.rerun()

st.sidebar.markdown("---")
app_mode = st.sidebar.radio(
    "📊 任意切换板块 (绝不丢数据)：",
    ["1️⃣ 短线区间波段", "2️⃣ 长线大底波段", "3️⃣ 半年首板挖掘", "4️⃣ 机构慢牛池"]
)

# ==========================================
# 6. 后台稳态批处理引擎
# ==========================================
if st.session_state['is_scanning']:
    if current_count >= total_stocks:
        st.session_state['is_scanning'] = False
        st.success("🎉 全市场扫描已全部完成！")
        st.balloons()
    else:
        st.warning("⏳ **雷达后台轰鸣中... (切换板块、看K线不影响后台扫描！)**")
        # 扩大单批次处理量，减少网页刷新频率，让前端点击更丝滑
        batch_size = 50 
        batch_pool = db['scan_pool'][current_count : current_count + batch_size]
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch_kline, s): s for s in batch_pool}
            for future in as_completed(futures):
                df, info = future.result()
                if df is not None:
                    matched = False
                    if logic_swing_short(df, info)[0]:
                        db['results']['swing_short'].append(logic_swing_short(df, info)[1])
                        matched = True
                    if logic_swing_long(df, info)[0]:
                        db['results']['swing_long'].append(logic_swing_long(df, info)[1])
                        matched = True
                    if logic_first_board(df, info)[0]:
                        db['results']['first_board'].append(logic_first_board(df, info)[1])
                        matched = True
                    if logic_slow_bull(df, info)[0]:
                        db['results']['slow_bull'].append(logic_slow_bull(df, info)[1])
                        matched = True
                    
                    if matched: 
                        db['kline_cache'][info['symbol']] = df
                        
        # 稳稳地更新数据库进度
        db['scanned_count'] += len(batch_pool)
        current_count = db['scanned_count']

# ==========================================
# 7. UI 页面成果展示大屏
# ==========================================
st.markdown("### 🏆 实时捕获成果 (全局数据库固化)")
metric_cols = st.columns(4)
# 数据从防弹数据库 db 中读取
metric_cols[0].metric("短线波段", len(db['results']['swing_short']))
metric_cols[1].metric("长线大底", len(db['results']['swing_long']))
metric_cols[2].metric("半年首板", len(db['results']['first_board']))
metric_cols[3].metric("机构慢牛", len(db['results']['slow_bull']))
st.markdown("---")

# ==========================================
# 8. K线图查看器
# ==========================================
def render_view(mode_key, title, ma_list):
    results = db['results'][mode_key]
    if len(results) == 0:
        st.info(f"🤷‍♂️ 【{title}】暂无标的。雷达正在深海探测中，请稍候...")
        return
        
    res_df = pd.DataFrame(results)
    st.dataframe(res_df, use_container_width=True)
    
    sel = st.selectbox(f"📊 选择查看【{title}】的 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")")
    sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
    
    if sym in db['kline_cache']:
        df = db['kline_cache'][sym].copy()
        for ma in ma_list:
            if f'MA{ma}' not in df.columns:
                df[f'MA{ma}'] = df['close'].rolling(ma).mean()
                
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
        fig.add_trace(go.Candlestick(x=df['day'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='K线'), row=1, col=1)
        colors = ['yellow', 'magenta', 'cyan']
        for i, ma in enumerate(ma_list):
            fig.add_trace(go.Scatter(x=df['day'], y=df[f'MA{ma}'], line=dict(color=colors[i%len(colors)], width=1.5), name=f'{ma}日线'), row=1, col=1)
        vol_colors = ['red' if c >= o else 'green' for c, o in zip(df['close'], df['open'])]
        fig.add_trace(go.Bar(x=df['day'], y=df['volume'], marker_color=vol_colors, name='成交量'), row=2, col=1)
        fig.update_layout(template="plotly_dark", title=sel, xaxis_rangeslider_visible=False, height=550)
        st.plotly_chart(fig, use_container_width=True)

if app_mode.startswith("1️⃣"): render_view('swing_short', "短线区间波段", [5, 10, 20])
elif app_mode.startswith("2️⃣"): render_view('swing_long', "长线大底波段", [20, 60, 120])
elif app_mode.startswith("3️⃣"): render_view('first_board', "半年首板挖掘", [5, 10, 20])
elif app_mode.startswith("4️⃣"): render_view('slow_bull', "机构慢牛池", [20, 60, 120])

# ==========================================
# 9. 引擎自动心跳触发器
# ==========================================
if st.session_state['is_scanning'] and db['scanned_count'] < total_stocks:
    # 停顿1秒让用户有充足的时间点击按钮或下拉框
    time.sleep(1.0) 
    st.rerun()
