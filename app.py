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
# 1. 全局页面配置 & 强力状态记忆 (杜绝丢失)
# ==========================================
st.set_page_config(page_title="A股波段与首板雷达", page_icon="📡", layout="wide")

# 初始化所有模式的缓存字典
modes = ['swing_short', 'swing_long', 'first_board', 'slow_bull']
if 'data_cache' not in st.session_state:
    st.session_state['data_cache'] = {
        mode: {'results': None, 'history': {}} for mode in modes
    }

# ==========================================
# 2. 侧边栏：系统导航
# ==========================================
st.sidebar.title("📡 雷达导航")
app_mode = st.sidebar.radio(
    "请选择扫描引擎：",
    [
        "📊 模式一：短线区间波段 (不破20日线支撑)", 
        "📈 模式二：长线大底波段 (半年级别支撑)",
        "🚀 模式三：半年首板挖掘 (新题材/新资金起爆)",
        "🐢 模式四：机构慢牛扫描 (原保留模式)"
    ]
)
st.sidebar.markdown("---")
st.sidebar.success("✅ 状态记忆已开启。切换菜单不会丢失扫描结果。")

# ==========================================
# 3. 数据获取引擎
# ==========================================
@st.cache_data(ttl=3600)
def fetch_all_stocks():
    """获取全市场 A 股列表"""
    all_stocks = []
    for page in range(1, 60): # 扫全市场约 5000+ 股票
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
                if not symbol or mktcap_wan == 0 or symbol.startswith('bj'): continue
                all_stocks.append({"symbol": symbol, "name": name, "market_cap": round(float(mktcap_wan) / 10000, 2)})
        except: pass
        time.sleep(0.05)
    return pd.DataFrame(all_stocks)

def fetch_kline(stock_info, datalen=130):
    """获取个股 K 线 (首板和长线需要至少半年120天数据)"""
    symbol = stock_info['symbol']
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        time.sleep(random.uniform(0.05, 0.15)) # 防封
        res = requests.get(url, timeout=5)
        text = re.sub(r'([a-zA-Z_]+):', r'"\1":', res.text) 
        data = json.loads(text)
        if not data: return None, stock_info
        df = pd.DataFrame(data)
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df['pct_change'] = df['close'].pct_change() # 计算每日涨跌幅
        return df.sort_values('day').reset_index(drop=True), stock_info
    except: return None, stock_info

# ==========================================
# 4. 绘图引擎
# ==========================================
def plot_kline(df, title, ma_list=[20, 60, 120]):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.7])
    fig.add_trace(go.Candlestick(x=df['day'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='K线'), row=1, col=1)
    colors = ['yellow', 'magenta', 'cyan']
    for i, ma in enumerate(ma_list):
        df[f'MA{ma}'] = df['close'].rolling(window=ma).mean()
        fig.add_trace(go.Scatter(x=df['day'], y=df[f'MA{ma}'], line=dict(color=colors[i%len(colors)], width=1.5), name=f'{ma}日线'), row=1, col=1)
    vol_colors = ['red' if c > o else 'green' for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(x=df['day'], y=df['volume'], marker_color=vol_colors, name='成交量'), row=2, col=1)
    fig.update_layout(template="plotly_dark", title=title, xaxis_rangeslider_visible=False, height=500, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 5. 通用扫描执行引擎
# ==========================================
def run_scanner(mode_key, pool, check_logic, kline_days=130):
    st.session_state['data_cache'][mode_key]['results'] = []
    st.session_state['data_cache'][mode_key]['history'] = {}
    
    pb = st.progress(0)
    st_txt = st.empty()
    matches = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_kline, s, kline_days): s for s in pool}
        for i, future in enumerate(as_completed(futures)):
            df, info = future.result()
            if df is not None:
                st.session_state['data_cache'][mode_key]['history'][info['symbol']] = df
                is_match, res = check_logic(df, info)
                if is_match: matches.append(res)
            
            pb.progress((i + 1) / len(pool))
            st_txt.text(f"📡 正在扫描全市场: {i+1} / {len(pool)} | 🎯 发现目标: {len(matches)} 只")
            
    st.session_state['data_cache'][mode_key]['results'] = matches
    pb.empty()
    st_txt.success(f"扫描完成！共发现 {len(matches)} 只符合条件的标的。")

# =====================================================================
# 模块 1：短线区间波段 (20日线支撑位)
# =====================================================================
def logic_swing_short(df, info):
    if df is None or len(df) < 30: return False, None
    df['MA20'] = df['close'].rolling(20).mean()
    last_20 = df.tail(20)
    current = df.iloc[-1]
    
    # 找近20天的最高点和最低点构成箱体
    box_high = last_20['high'].max()
    box_low = last_20['low'].min()
    box_amplitude = (box_high - box_low) / box_low
    
    # 条件1：箱体要有一定幅度（比如上下至少有 8% 的空间才值得做波段）
    if box_amplitude < 0.08: return False, None
    
    # 条件2：当前价格在箱体的下半部分（接近支撑）
    current_pos = (current['close'] - box_low) / (box_high - box_low)
    if not (0.0 <= current_pos <= 0.35): return False, None # 处于底部35%区域
    
    # 条件3：不能跌破20日线太多，确保趋势没有彻底走坏 (收盘价需在 20日线 -1.5% 以上)
    if current['close'] < current['MA20'] * 0.985: return False, None
    
    return True, {
        '代码': info['symbol'], '名称': info['name'], '市值(亿)': info['market_cap'], 
        '现价': current['close'], '近期箱底': round(box_low, 2), '近期箱顶': round(box_high, 2),
        '波段空间': f"{round(box_amplitude*100, 1)}%"
    }

if app_mode.startswith("📊"):
    st.title("📊 短线区间波段 (低吸支撑位)")
    st.markdown("💡 **逻辑**：扫描近一个月（20个交易日）形成明显上下边界的股票。目前股价回踩到**箱体底部区域**，且未跌破关键均线，适合做高抛低吸。")
    if st.button("🚀 扫描短线波段机会", type="primary"):
        pool = fetch_all_stocks().head(1000).to_dict('records') # 为速度测试，扫前1000
        run_scanner('swing_short', pool, logic_swing_short, 60)
        
    cache = st.session_state['data_cache']['swing_short']
    if cache['results'] is not None and len(cache['results']) > 0:
        res_df = pd.DataFrame(cache['results'])
        st.dataframe(res_df, use_container_width=True)
        sel = st.selectbox("查看波段 K 线 (看黄色20日线支撑)：", res_df['名称'] + " (" + res_df['代码'] + ")")
        sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
        plot_kline(cache['history'][sym], sel, [5, 10, 20])

# =====================================================================
# 模块 2：长线大底波段 (半年级别筑底)
# =====================================================================
def logic_swing_long(df, info):
    if df is None or len(df) < 120: return False, None
    df['MA120'] = df['close'].rolling(120).mean()
    last_120 = df.tail(120)
    current = df.iloc[-1]
    
    # 找近半年的极值
    long_low = last_120['low'].min()
    
    # 条件1：120日线必须走平或者微抬头 (当前120日线 大于 20天前的120日线)
    if current['MA120'] < df['MA120'].iloc[-20]: return False, None
    
    # 条件2：当前价格距离半年最低点不超过 10% (证明在底部趴着)
    if (current['close'] - long_low) / long_low > 0.10: return False, None
    
    # 条件3：近期必须极其缩量，表明跌无可跌
    recent_vol = df['volume'].tail(10).mean()
    past_vol = last_120['volume'].mean()
    if recent_vol > past_vol * 0.8: return False, None
    
    return True, {
        '代码': info['symbol'], '名称': info['name'], '市值(亿)': info['market_cap'], 
        '现价': current['close'], '半年最低': round(long_low, 2), 
        '状态': "半年大底, 极致缩量"
    }

if app_mode.startswith("📈"):
    st.title("📈 长线大底波段 (半年级别筑底)")
    st.markdown("💡 **逻辑**：寻找半年内跌无可跌、120日长线均线已经走平、且当前处于极其缩量的大底区域的股票。适合长线建仓。")
    if st.button("🚀 扫描长线底部建仓机会", type="primary"):
        pool = fetch_all_stocks().head(1500).to_dict('records') 
        run_scanner('swing_long', pool, logic_swing_long, 150)
        
    cache = st.session_state['data_cache']['swing_long']
    if cache['results'] is not None and len(cache['results']) > 0:
        res_df = pd.DataFrame(cache['results'])
        st.dataframe(res_df, use_container_width=True)
        sel = st.selectbox("查看长线 K 线 (看青色120日大底)：", res_df['名称'] + " (" + res_df['代码'] + ")")
        sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
        plot_kline(cache['history'][sym], sel, [20, 60, 120])


# =====================================================================
# 模块 3：半年首板挖掘机 (抓热点板块启动)
# =====================================================================
def logic_first_board(df, info):
    # 必须要有至少120天数据来证明是"半年首板"
    if df is None or len(df) < 120: return False, None
    
    today = df.iloc[-1]
    # 条件1：今天必须是涨停 (A股普通股涨停一般大于 9.5%)
    # 剔除ST股(5%)和创业板科创板(20%)，这里设为 9.5% 抓主板，如果想抓创业板可改为 19.5%
    if today['pct_change'] < 0.095: return False, None
    
    # 条件2：往前推算 120 个交易日（近半年），绝对不能出现过涨停
    history_120 = df.iloc[-121:-1] # 去掉今天
    max_history_pct = history_120['pct_change'].max()
    
    # 如果过去120天有过 >= 9.5% 的涨停记录，直接过滤
    if max_history_pct >= 0.095: return False, None
    
    return True, {
        '代码': info['symbol'], '名称': info['name'], '市值(亿)': info['market_cap'], 
        '现价': round(today['close'], 2), 
        '今日涨幅': f"{round(today['pct_change']*100, 2)}%",
        '异动信号': "🚨 半年内首次涨停！"
    }

if app_mode.startswith("🚀"):
    st.title("🚀 半年首板挖掘机 (新题材 / 新资金起爆)")
    st.markdown("""
    💡 **实战应用**：
    1. 这个模型会帮你抓出**沉寂了半年以上，今天突然拔出第一个涨停**的标的。
    2. **资金流向反推**：如果你发现扫出来的 10 只票里，有 5 只是“医药股”，说明今天**大资金在突袭医药板块**。首板代表的是从0到1的增量资金介入！
    """)
    if st.button("🚀 扫描今日全市场首板异动", type="primary"):
        # 抓首板必须扫全市场
        pool = fetch_all_stocks().to_dict('records') 
        run_scanner('first_board', pool, logic_first_board, 130)
        
    cache = st.session_state['data_cache']['first_board']
    if cache['results'] is not None and len(cache['results']) > 0:
        res_df = pd.DataFrame(cache['results'])
        st.success("🎯 扫描发现以下股票出现半年内首次涨停！请观察它们属于哪些行业板块！")
        st.dataframe(res_df, use_container_width=True)
        sel = st.selectbox("查看首板拔地起 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")")
        sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
        plot_kline(cache['history'][sym], sel, [5, 10, 20])


# =====================================================================
# 模块 4：机构慢牛扫描 (优化宽松版)
# =====================================================================
def logic_slow_bull(df, info):
    if df is None or len(df) < 120: return False, None
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    df['MA120'] = df['close'].rolling(120).mean()
    current = df.iloc[-1]
    
    # 慢牛条件：均线多头排列
    if not (current['MA20'] > current['MA60'] > current['MA120']): return False, None
    
    # 慢牛条件：最近 20 天内没有出现过涨停（稳步上涨，无游资爆炒）
    if df.tail(20)['pct_change'].max() > 0.08: return False, None
    
    # 当前价格乖离率不能太大（离20日线不超过 5%）
    dist = (current['close'] - current['MA20']) / current['MA20']
    if not (-0.02 <= dist <= 0.05): return False, None
    
    return True, {
        '代码': info['symbol'], '名称': info['name'], '市值(亿)': info['market_cap'], 
        '现价': round(current['close'], 2), '距20日线': f"{round(dist*100, 2)}%"
    }

if app_mode.startswith("🐢"):
    st.title("🐢 机构慢牛扫描 (保留版)")
    st.markdown("💡 **逻辑**：均线多头排列（20>60>120），近期未见涨停板暴起，走势极其稳健。")
    if st.button("🚀 扫描机构慢牛", type="primary"):
        pool = fetch_all_stocks().head(1000).to_dict('records') 
        run_scanner('slow_bull', pool, logic_slow_bull, 150)
        
    cache = st.session_state['data_cache']['slow_bull']
    if cache['results'] is not None and len(cache['results']) > 0:
        res_df = pd.DataFrame(cache['results'])
        st.dataframe(res_df, use_container_width=True)
        sel = st.selectbox("查看慢牛 K 线图：", res_df['名称'] + " (" + res_df['代码'] + ")")
        sym = res_df[res_df['名称'] + " (" + res_df['代码'] + ")" == sel].iloc[0]['代码']
        plot_kline(cache['history'][sym], sel, [20, 60, 120])
