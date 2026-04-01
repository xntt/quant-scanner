import streamlit as st
import pandas as pd
import akshare as ak
import pandas_ta as ta
import plotly.graph_objects as go
from datetime import datetime, timedelta
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

st.title("🎯 A股游资量化狙击雷达 (Quant System)")
st.caption("基于 AkShare + Pandas-TA 构建：只做核心资产，只等缩量回踩，拒绝无脑追高！")

# ==========================================
# 模块1：数据底座 (Fundamental & Sentiment)
# ==========================================
@st.cache_data(ttl=600)
def get_active_stock_pool(top_n=50):
    """
    情报与基本面过滤：获取全市场成交额最大的 N 只股票（游资与机构的绝对主战场）
    过滤掉 ST 股和价格畸形的股票。
    """
    try:
        # 获取A股实时行情
        df = ak.stock_zh_a_spot_em()
        
        # 基础过滤：剔除ST、退市股，剔除股价<2或>300的票
        df = df[~df['名称'].str.contains('ST|退')]
        df = df[(df['最新价'] >= 2) & (df['最新价'] <= 300)]
        
        # 按成交额降序排列，取 Top N（这就是市场最核心的资金抱团股）
        df = df.sort_values(by="成交额", ascending=False).head(top_n)
        return df[['代码', '名称', '最新价', '涨跌幅', '成交额', '换手率']]
    except Exception as e:
        st.error(f"获取核心股票池失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_historical_data(symbol, days=150):
    """获取单只股票的历史日线数据，用于 TA 计算和回测"""
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty: return pd.DataFrame()
        
        df = df[['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额']]
        df['日期'] = pd.to_datetime(df['日期'])
        df.set_index('日期', inplace=True)
        # 转换列名以适应 pandas-ta
        df.rename(columns={'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        return df
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# 模块2 & 3：技术面分析与回测 (Technical & Backtesting)
# ==========================================
def analyze_stock(df_hist):
    """
    核心算法：使用 pandas-ta 计算技术指标，并标记【首阴缩量回踩】买点
    """
    if len(df_hist) < 30:
        return df_hist, None

    # 1. TA 指标计算 (均线、RSI、成交量均线)
    df_hist.ta.sma(length=5, append=True)
    df_hist.ta.sma(length=10, append=True)
    df_hist.ta.sma(length=20, append=True)
    df_hist.ta.rsi(length=14, append=True)
    df_hist['vol_ma5'] = df_hist['volume'].rolling(5).mean()

    # 2. 游资买点逻辑：龙头首阴 / 回踩 10日线缩量
    # 逻辑：
    #   - 趋势要求：20日线上升，收盘价在 20日线之上 (趋势完好)
    #   - 回踩要求：今日最低价触碰或跌破 10日线，但收盘价没有偏离 10日线太远 (支撑有效)
    #   - 洗盘要求：今日收阴线 (close < open)，且今日成交量小于 5日均量 (缩量洗盘，主力没走)
    
    buy_signals = []
    for i in range(len(df_hist)):
        if i < 20:
            buy_signals.append(False)
            continue
            
        row = df_hist.iloc[i]
        
        # 趋势条件
        trend_ok = (row['SMA_20'] > df_hist.iloc[i-1]['SMA_20']) and (row['close'] > row['SMA_20'])
        # 回踩 10日线条件 (最低价砸破/靠近10日线，收盘在10日线附近 -2% 到 +3%)
        touch_10ma = (row['low'] <= row['SMA_10'] * 1.01) and (row['SMA_10'] * 0.98 <= row['close'] <= row['SMA_10'] * 1.03)
        # 缩量收阴条件
        wash_out = (row['close'] < row['open']) and (row['volume'] < row['vol_ma5'] * 0.9)
        
        if trend_ok and touch_10ma and wash_out:
            buy_signals.append(True)
        else:
            buy_signals.append(False)
            
    df_hist['Buy_Signal'] = buy_signals
    
    # 3. 向量化回测 (计算如果出现买点，持有 3 天后的胜率)
    # 计算未来3天的最高涨幅
    df_hist['future_return_3d'] = (df_hist['close'].shift(-3) - df_hist['close']) / df_hist['close'] * 100
    
    # 统计历史触发次数和胜率 (涨幅 > 0 视为胜)
    signal_days = df_hist[df_hist['Buy_Signal'] == True]
    total_signals = len(signal_days)
    if total_signals > 0:
        # 过滤掉最后3天无法计算未来的数据
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
top_n = st.sidebar.slider("扫描全市场成交额 Top 股票数量", 20, 100, 40, help="数值越大耗时越长，建议40以内，保证监控的是绝对核心主线资产。")

if st.sidebar.button("🚀 启动量化扫描 (计算买点)"):
    with st.spinner("正在扫描资金面核心池并进行 TA 量化计算..."):
        pool_df = get_active_stock_pool(top_n=top_n)
        
        if pool_df.empty:
            st.error("数据源获取失败，请稍后再试。")
            st.stop()
            
        st.success(f"已锁定今日 A 股流动性最强的 {len(pool_df)} 只核心资产！正在逐一进行技术面扫描...")
        
        # 存储今日触发买点的股票
        target_stocks = []
        
        # 进度条
        progress_bar = st.progress(0)
        for idx, row in pool_df.iterrows():
            code = row['代码']
            name = row['名称']
            
            # 获取历史数据
            hist_data = get_historical_data(code)
            if not hist_data.empty:
                processed_data, stats = analyze_stock(hist_data)
                
                # 检查最新一天（今天/最近交易日）是否触发了买点
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
                        "K线数据": processed_data # 保存数据用于画图
                    })
                    
            progress_bar.progress((idx + 1) / len(pool_df))
            time.sleep(0.1) # 避免请求过快被断开
            
        st.markdown("---")
        st.subheader("🚨 量化雷达：今日【缩量回踩10日线】狙击目标")
        
        if len(target_stocks) > 0:
            st.balloons()
            st.info(f"太棒了！在最活跃的资金池中，发现了 **{len(target_stocks)}** 只符合低吸买点逻辑的股票。")
            
            # 展示卡片与交互图表
            for stock in target_stocks:
                with st.expander(f"🔥 {stock['名称']} ({stock['代码']}) - 胜率: {stock['持股3天胜率']}", expanded=True):
                    cols = st.columns(4)
                    cols[0].metric("最新价", stock['最新价'])
                    cols[1].metric("今日成交额", stock['今日成交额'])
                    cols[2].metric("历史回测胜率 (3天)", stock['持股3天胜率'])
                    cols[3].metric("回测平均收益", stock['平均预期收益'])
                    
                    # 使用 Plotly 绘制 K线与买点
                    df_plot = stock['K线数据'].tail(60) # 画最近60天
                    
                    fig = go.Figure()
                    # K线图
                    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['open'], high=df_plot['high'], low=df_plot['low'], close=df_plot['close'], name='K线'))
                    # 均线
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_10'], line=dict(color='orange', width=2), name='10日均线 (生命线)'))
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_20'], line=dict(color='blue', width=2), name='20日均线 (趋势线)'))
                    
                    # 标记历史买点
                    buy_points = df_plot[df_plot['Buy_Signal'] == True]
                    if not buy_points.empty:
                        fig.add_trace(go.Scatter(
                            x=buy_points.index, 
                            y=buy_points['low'] * 0.98, # 显示在最低价下方
                            mode='markers+text', 
                            marker=dict(symbol='triangle-up', size=15, color='red'),
                            text=["买点"] * len(buy_points),
                            textposition="bottom center",
                            name='低吸买点'
                        ))
                        
                    fig.update_layout(title=f"{stock['名称']} - 核心资产回踩逻辑分析", height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.markdown("""
                    **💡 交易策略提示**：
                    该股属于近期市场高热度核心票。今日出现【缩量下跌并精准回踩 10 日均线】。
                    1. **买入建议**：可在10日线附近分批低吸（切勿追高）。
                    2. **止损纪律**：若明日收盘有效跌破 20 日均线，说明趋势彻底破坏，必须无条件止损。
                    3. **止盈目标**：持股 2-3 天，若反包大阳线或触及前高，逢高获利了结。
                    """)
        else:
            st.warning("🧐 今日核心资金池内，没有股票触发【缩量回踩】信号。说明目前市场不适合低吸，耐心等待下一次良机！")

else:
    st.info("👈 请点击左侧【启动量化扫描】按钮，开始从全市场捕捉低吸买点。")
    st.markdown("""
    ### 🧠 系统工作流拆解：
    1. **情报/资金底座**：不看板块，直接抓取全市场**成交额最大的 Top 40** 股票（因为在 A 股，最大的成交额 = 最强的逻辑 + 最大的游资机构共识）。
    2. **基本面过滤**：系统底层已自动剔除 ST 股、退市股、低价垃圾股。
    3. **TA量化算法**：调用 `pandas-ta` 对这 40 只股票计算近期趋势。
    4. **信号触发器**：寻找**“过去强势（20日线向上），今天突然大跌回调，但成交量极度萎缩，且刚好砸到 10 日均线支撑位”**的完美潜伏买点（游资战法：龙头首阴/老鸭头）。
    5. **轻量化回测**：不仅给信号，还立刻计算该股过去半年出现此信号时，**无脑持有 3 天的胜率**。
    """)
