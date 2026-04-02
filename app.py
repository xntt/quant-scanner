import streamlit as st
import pandas as pd
import requests
import pandas_ta as ta
import plotly.graph_objects as go
from datetime import datetime
import time

# ==========================================
# 页面配置
# ==========================================
st.set_page_config(page_title="A股游资量化狙击系统", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1, h2, h3 {color: #ff4b4b;}
    .stAlert {background-color: #262730; color: white;}
    </style>
    """, unsafe_allow_html=True)

st.title("🎯 A股游资量化狙击雷达 (原生API版)")
st.caption("基于 东方财富直连API + Pandas-TA 构建：只做核心资产，只等缩量回踩！")

# ==========================================
# 模块1：原生数据引擎 (直接对接东方财富底层API)
# ==========================================
@st.cache_data(ttl=600)
def get_active_stock_pool(top_n=50):
    """通过东方财富API，获取全市场成交额排名前N的股票"""
    try:
        url = "http://82.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": str(top_n * 2),  # 多取一点以备过滤
            "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f6", 
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048", 
            "fields": "f12,f14,f2,f3,f6,f8" 
        }
        res = requests.get(url, params=params, timeout=5).json()
        data = res['data']['diff']
        
        stock_list = []
        for item in data:
            if item['f2'] == "-" or "ST" in str(item['f14']) or "退" in str(item['f14']):
                continue
            stock_list.append({
                '代码': item['f12'],
                '名称': item['f14'],
                '最新价': float(item['f2']),
                '涨跌幅': float(item['f3']),
                '成交额': float(item['f6']),
                '换手率': float(item['f8'])
            })
            
        df = pd.DataFrame(stock_list)
        df = df[(df['最新价'] >= 2) & (df['最新价'] <= 300)]
        return df.head(top_n) 
    except Exception as e:
        st.error(f"东方财富API获取核心股票池失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_historical_data(code, days=150):
    """通过东方财富API，获取单只股票历史K线"""
    try:
        market = "1" if str(code).startswith('6') else "0"
        secid = f"{market}.{code}"
        
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57", 
            "klt": "101", 
            "fqt": "1",   
            "end": "20500101", 
            "lmt": str(days)   
        }
        
        res = requests.get(url, params=params, timeout=5).json()
        klines = res['data']['klines']
        
        parsed_data = []
        for k in klines:
            parts = k.split(',')
            parsed_data.append({
                '日期': parts[0],
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5]),
                'amount': float(parts[6])
            })
            
        df = pd.DataFrame(parsed_data)
        df['日期'] = pd.to_datetime(df['日期'])
        df.set_index('日期', inplace=True)
        return df
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# 模块2 & 3：技术面分析与回测
# ==========================================
def analyze_stock(df_hist):
    if len(df_hist) < 30:
        return df_hist, None

    df_hist.ta.sma(length=5, append=True)
    df_hist.ta.sma(length=10, append=True)
    df_hist.ta.sma(length=20, append=True)
    df_hist['vol_ma5'] = df_hist['volume'].rolling(5).mean()

    buy_signals = []
    for i in range(len(df_hist)):
        if i < 20:
            buy_signals.append(False)
            continue
            
        row = df_hist.iloc[i]
        trend_ok = (row['SMA_20'] > df_hist.iloc[i-1]['SMA_20']) and (row['close'] > row['SMA_20'])
        touch_10ma = (row['low'] <= row['SMA_10'] * 1.01) and (row['SMA_10'] * 0.98 <= row['close'] <= row['SMA_10'] * 1.03)
        wash_out = (row['close'] < row['open']) and (row['volume'] < row['vol_ma5'] * 0.95)
        
        if trend_ok and touch_10ma and wash_out:
            buy_signals.append(True)
        else:
            buy_signals.append(False)
            
    df_hist['Buy_Signal'] = buy_signals
    
    df_hist['future_return_3d'] = (df_hist['close'].shift(-3) - df_hist['close']) / df_hist['close'] * 100
    
    signal_days = df_hist[df_hist['Buy_Signal'] == True]
    total_signals = len(signal_days)
    if total_signals > 0:
        valid_signals = signal_days.dropna(subset=['future_return_3d'])
        if len(valid_signals) > 0:
            wins = len(valid_signals[valid_signals['future_return_3d'] > 0])
            win_rate = (wins / len(valid_signals)) * 100
            avg_return = valid_signals['future_return_3d'].mean()
            stats = {"触发次数": total_signals, "持股3天胜率": win_rate, "平均收益": avg_return}
        else:
            stats = {"触发次数": total_signals, "持股3天胜率": 0, "平均收益": 0}
    else:
        stats = {"触发次数": 0, "持股3天胜率": 0, "平均收益": 0}

    return df_hist, stats

# ==========================================
# 页面 UI 渲染
# ==========================================
st.sidebar.header("⚙️ 引擎控制台")
top_n = st.sidebar.slider("扫描全市场成交额 Top 股票数量", 20, 100, 40)

if st.sidebar.button("🚀 启动量化扫描 (原生直连版)"):
    with st.spinner("正在直连东方财富API，提取全市场核心资金池..."):
        pool_df = get_active_stock_pool(top_n=top_n)
        
        if pool_df.empty:
            st.error("数据源获取失败，请检查网络。")
            st.stop()
            
        st.success(f"⚡ API直连成功！已极速锁定 {len(pool_df)} 只绝对核心资产，正在进行技术面计算...")
        
        target_stocks = []
        progress_bar = st.progress(0.0)
        
        total_stocks = len(pool_df)
        for i, (idx, row) in enumerate(pool_df.iterrows()):
            code = row['代码']
            name = row['名称']
            
            hist_data = get_historical_data(code)
            if not hist_data.empty:
                processed_data, stats = analyze_stock(hist_data)
                
                if processed_data is not None:
                    is_trigger_today = processed_data.iloc[-1]['Buy_Signal']
                    
                    if is_trigger_today:
                        target_stocks.append({
                            "代码": code,
                            "名称": name,
                            "最新价": row['最新价'],
                            "今日成交额": f"{row['成交额']/100000000:.2f} 亿",
                            "历史触发次数": stats["触发次数"],
                            "持股3天胜率": f"{stats['持股3天胜率']:.1f}%",
                            "平均预期收益": f"{stats['平均收益']:.2f}%",
                            "K线数据": processed_data
                        })
            
            # 【终极进度条安全防御】确保数值严格在 0.0 到 1.0 之间
            safe_progress = float(i + 1) / float(total_stocks)
            safe_progress = max(0.0, min(safe_progress, 1.0))
            progress_bar.progress(safe_progress)
            
            time.sleep(0.05)
            
        st.markdown("---")
        st.subheader("🚨 量化雷达：今日【缩量回踩10日线】低吸狙击名单")
        
        if len(target_stocks) > 0:
            st.balloons()
            st.info(f"太棒了！在最活跃的资金池中，发现了 **{len(target_stocks)}** 只符合游资买点逻辑的股票。")
            
            for stock in target_stocks:
                with st.expander(f"🔥 {stock['名称']} ({stock['代码']}) - 历史胜率: {stock['持股3天胜率']}", expanded=True):
                    cols = st.columns(4)
                    cols[0].metric("最新价", stock['最新价'])
                    cols[1].metric("今日成交额", stock['今日成交额'])
                    cols[2].metric("出现此信号次数", stock['历史触发次数'])
                    cols[3].metric("持股3天平均收益", stock['平均预期收益'])
                    
                    df_plot = stock['K线数据'].tail(60)
                    
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['open'], high=df_plot['high'], low=df_plot['low'], close=df_plot['close'], name='K线'))
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_10'], line=dict(color='orange', width=2), name='10日均线 (生命支撑)'))
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_20'], line=dict(color='blue', width=2), name='20日均线 (趋势线)'))
                    
                    buy_points = df_plot[df_plot['Buy_Signal'] == True]
                    if not buy_points.empty:
                        fig.add_trace(go.Scatter(
                            x=buy_points.index, 
                            y=buy_points['low'] * 0.98,
                            mode='markers+text', 
                            marker=dict(symbol='triangle-up', size=16, color='#ff4b4b', line=dict(width=2, color='white')),
                            text=["低吸买点"] * len(buy_points),
                            textposition="bottom center",
                            name='量化买点'
                        ))
                        
                    fig.update_layout(
                        title=f"{stock['名称']} - 核心资产回踩逻辑分析", 
                        height=500, 
                        xaxis_rangeslider_visible=False, 
                        template="plotly_dark",
                        margin=dict(l=20, r=20, t=50, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.markdown("""
                    **💡 游资交易策略提示**：
                    该股属于近期市场高热度核心票。今日出现典型的 **缩量洗盘 + 精准回踩 10日均线**。
                    *   **买入点**：明日开盘在 10日线附近分批低吸，切勿追高大阳线。
                    *   **防守线**：若有效跌破 20日均线，说明主力彻底弃盘，必须无条件止损。
                    *   **进攻线**：持股等待 2-3 天，大概率会有反包或冲击前高动作，逢高获利了结。
                    """)
        else:
            st.warning("🧐 今日核心资金池内，未检测到完美的【缩量回踩10日线】洗盘动作。游资战法核心是‘宁可错过，绝不接盘’，耐心等待明天的数据。")
else:
    st.info("👈 请点击左侧【启动量化扫描】按钮。系统将直接调用东方财富API获取最新数据。")
