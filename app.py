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

st.title("📈 A股机构慢牛扫地僧 (纯新浪数据版)")
st.markdown("""
**策略逻辑**：寻找脱离散户视线、机构控盘的“碎步小阳”慢牛股。
**数据源**：市值筛选 + K线获取 **全部采用新浪财经 API**，完美兼容云端部署。
*(扫描全市场可能需要 1-3 分钟，请耐心等待)*
""")

# ==========================================
# 2. 侧边栏：参数调节 UI
# ==========================================
st.sidebar.header("⚙️ 1. 基础过滤池 (新浪数据)")
# 默认筛选 50亿 到 300亿 的股票，这是最容易出慢牛的区间
market_cap_range = st.sidebar.slider("总市值范围 (亿元)", min_value=10, max_value=3000, value=(50, 300), step=10)
max_scan_num = st.sidebar.number_input("最多扫描多少只符合市值的股票？", min_value=100, max_value=3000, value=1000)

st.sidebar.header("⚙️ 2. 形态严苛度")
max_distance = st.sidebar.slider("允许偏离 20日线最大幅度 (%)", min_value=0.0, max_value=5.0, value=2.0, step=0.5) / 100

# ==========================================
# 3. 数据接口 A：获取全市场股票与市值 (纯新浪)
# ==========================================
@st.cache_data(ttl=3600) # 缓存1小时，避免频繁请求被封
def fetch_all_stocks_sina():
    """从新浪财经节点API获取沪深A股列表及市值"""
    all_stocks = []
    # A股大约5000多只，每次取100只，最多翻页80次足够覆盖全市场
    for page in range(1, 80):
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        try:
            res = requests.get(url, timeout=3)
            text = res.text
            
            # 新浪返回的是不带引号的类JSON格式，需要用正则修复为标准JSON
            text = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', text)
            data = json.loads(text)
            
            if not data or len(data) == 0:
                break # 已经翻到最后一页了
                
            for item in data:
                symbol = item.get("symbol", "")
                name = item.get("name", "")
                mktcap_wan = item.get("mktcap", 0) # 新浪的市值单位是“万元”
                
                # 过滤掉停牌或没有市值的股票
                if not symbol or mktcap_wan == 0:
                    continue
                # 可选：过滤掉北交所(bj)
                if symbol.startswith('bj'):
                    continue
                    
                # 将万元转换为亿元 (1亿元 = 10000万元)
                mktcap_yi = round(float(mktcap_wan) / 10000, 2)
                
                all_stocks.append({
                    "symbol": symbol,
                    "name": name,
                    "market_cap": mktcap_yi
                })
        except Exception:
            pass # 忽略单页错误，继续下一页
            
        time.sleep(0.05) # 稍微停顿，防止被新浪封禁
        
    return pd.DataFrame(all_stocks)

# ==========================================
# 4. 数据接口 B：底层请求新浪财经 K线
# ==========================================
def fetch_sina_kline(stock_info):
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
    
    # 步骤 1: 获取并过滤全市场股票 (使用纯新浪接口)
    with st.spinner("📡 正在通过新浪财经读取全市场 5000 只股票最新市值 (仅首次需 5-10 秒)..."):
        all_stocks_df = fetch_all_stocks_sina()
    
    if all_stocks_df.empty:
        st.error("无法获取新浪市场数据，请稍后再试。")
        st.stop()
        
    # 按市值过滤
    min_cap, max_cap = market_cap_range
    filtered_df = all_stocks_df[(all_stocks_df['market_cap'] >= min_cap) & (all_stocks_df['market_cap'] <= max_cap)]
    
    # 限制扫描数量，按市值从小到大排序截取 (防止扫太多被新浪封锁)
    pool_to_scan = filtered_df.sort_values('market_cap').head(max_scan_num).to_dict('records')
    
    st.write(f"✅ 市值 {min_cap}亿 - {max_cap}亿 的股票共有 {len(filtered_df)} 只。")
    st.write(f"🕵️‍♂️ 正在为您深度扫描其中的 {len(pool_to_scan)} 只，请耐心等待...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    matched_stocks = []
    historical_data_dict = {}
    
    # 步骤 2: 多线程扫描 K 线 (并发控制在 8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_stock = {executor.submit(fetch_sina_kline, stock): stock for stock in pool_to_scan}
        
        for i, future in enumerate(as_completed(future_to_stock)):
            df, stock_info = future.result()
            
            if df is not None:
                historical_data_dict[stock_info['symbol']] = df
                is_match, info = check_stealth_bull(df, stock_info, max_distance)
                if is_match:
                    matched_stocks.append(info)
                    
            # 进度更新
            progress_bar.progress((i + 1) / len(pool_to_scan))
            status_text.text(f"已请求新浪K线: {i+1} / {len(pool_to_scan)} | 当前发现: {len(matched_stocks)} 只")
            
    st.success("🎉 全市场扫描完成！")
    
    # ==========================================
    # 7. 结果展示
    # ==========================================
    if matched_stocks:
        st.subheader(f"🎯 极度稀缺！在 {len(pool_to_scan)} 只股票中，发现 {len(matched_stocks)} 只符合【慢牛扫地僧】形态：")
        results_df = pd.DataFrame(matched_stocks)
        st.dataframe(results_df, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📊 点击查看 K 线形态确认")
        
        results_df['显示名称'] = results_df['名称'] + " (" + results_df['代码'] + ")"
        selected_display = st.selectbox("选择股票绘制趋势图：", results_df['显示名称'].tolist())
        
        if selected_display:
            selected_sym = results_df[results_df['显示名称'] == selected_display].iloc[0]
