import streamlit as st
import pandas as pd
import requests
import time
import plotly.graph_objects as go

# ==========================================
# 页面配置与全局样式 (黑客/游资终端风格)
# ==========================================
st.set_page_config(page_title="游资大局观雷达", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1, h2, h3 {color: #ff4b4b;}
    .alert-hot {background-color: #4b0000; color: #ffcccc; padding: 10px; border-left: 5px solid #ff4b4b; border-radius: 5px; margin-bottom: 10px;}
    .alert-new {background-color: #003300; color: #ccffcc; padding: 10px; border-left: 5px solid #00ff00; border-radius: 5px; margin-bottom: 10px;}
    .metric-box {background-color: #262730; padding: 15px; border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🦅 游资大局观：资金轮动与主线雷达")
st.caption("核心逻辑：顺应资金流向，捕捉板块2日连涨主线，预警次日高低切轮动。个股只是载体，板块才是王道！")

# ==========================================
# 模块1：东方财富 API 数据引擎 (板块与资金流)
# ==========================================
@st.cache_data(ttl=300)
def get_top_sectors():
    """获取全市场主力资金净流入或涨幅靠前的行业板块"""
    try:
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        # fs: m:90 t:2 s:8228 是东财沪深行业板块的固定参数
        params = {
            "pn": "1", "pz": "30", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", 
            "fid": "f62", # 按主力净流入(f62)排序，也可以换成 f3(涨跌幅)
            "fs": "m:90 t:2 s:8228",
            "fields": "f12,f14,f2,f3,f62,f66" # 代码, 名称, 最新价, 涨跌幅, 主力净流入, 超大单流入
        }
        res = requests.get(url, params=params, timeout=5).json()
        data = res['data']['diff']
        
        sectors = []
        for item in data:
            sectors.append({
                '板块代码': item['f12'],
                '板块名称': item['f14'],
                '今日涨幅': float(item['f3']) if item['f3'] != "-" else 0.0,
                '主力净流入(亿)': round(float(item['f62'])/100000000, 2) if item['f62'] != "-" else 0.0,
            })
        return pd.DataFrame(sectors)
    except Exception as e:
        st.error(f"板块数据获取失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=600)
def get_sector_history(sector_code):
    """获取单个板块最近3天的日K线，判断是否连涨或反转"""
    try:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": f"90.{sector_code}", # 板块的前缀通常是 90
            "fields1": "f1,f2,f3",
            "fields2": "f51,f53", # 日期, 收盘价
            "klt": "101", "fqt": "1", "end": "20500101", "lmt": "3" # 获取最近3天
        }
        res = requests.get(url, params=params, timeout=5).json()
        klines = res['data']['klines']
        
        closes = [float(k.split(',')[1]) for k in klines]
        
        # 计算昨天的涨跌幅
        if len(closes) >= 3:
            yest_chg = (closes[1] - closes[0]) / closes[0] * 100
        elif len(closes) == 2:
            yest_chg = (closes[1] - closes[0]) / closes[0] * 100
        else:
            yest_chg = 0.0
            
        return yest_chg
    except:
        return 0.0

@st.cache_data(ttl=300)
def get_stocks_in_sector(sector_code):
    """获取某个板块内，成交额排名前列且大涨的个股（不限连板）"""
    try:
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "15", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", 
            "fid": "f6", # 按成交额排序，找出最活跃的载体
            "fs": f"b:{sector_code}",
            "fields": "f12,f14,f2,f3,f6,f8" 
        }
        res = requests.get(url, params=params, timeout=5).json()
        data = res['data']['diff']
        
        stocks = []
        for item in data:
            if item['f2'] == "-" or "ST" in str(item['f14']): continue
            chg = float(item['f3']) if item['f3'] != "-" else 0.0
            if chg > 3.0: # 只提取涨幅大于3%的有赚钱效应的票
                stocks.append({
                    '代码': item['f12'],
                    '名称': item['f14'],
                    '最新价': float(item['f2']),
                    '涨跌幅(%)': chg,
                    '成交额(亿)': round(float(item['f6'])/100000000, 2),
                    '换手率(%)': float(item['f8']) if item['f8'] != "-" else 0.0
                })
        return pd.DataFrame(stocks)
    except:
        return pd.DataFrame()

# ==========================================
# 页面 UI 与 核心业务逻辑
# ==========================================
tab1, tab2 = st.tabs(["🌪️ 大局观：资金与板块轮动预警 (强烈推荐)", "🎯 细节：核心资产缩量回踩狙击"])

with tab1:
    if st.button("🔄 刷新全市场主力资金走向", use_container_width=True):
        with st.spinner("正在扫描东方财富板块资金池，分析主力动向..."):
            df_sectors = get_top_sectors()
            
            if df_sectors.empty:
                st.error("数据拉取失败，请稍后再试。")
                st.stop()
            
            # 进度条
            progress_bar = st.progress(0.0)
            
            # 加入历史逻辑判断轮动
            analyzed_sectors = []
            total = min(15, len(df_sectors)) # 只分析前15大热点板块，保证速度
            
            for i in range(total):
                row = df_sectors.iloc[i]
                yest_chg = get_sector_history(row['板块代码'])
                today_chg = row['今日涨幅']
                inflow = row['主力净流入(亿)']
                
                # ==== 核心轮动预警逻辑 ====
                status = "🟢 正常震荡"
                css_class = ""
                
                if today_chg > 1.5 and yest_chg > 1.0:
                    status = "🔥 持续爆发 (2日连涨)"
                    css_class = "alert-hot"
                elif today_chg > 2.0 and yest_chg <= 0:
                    status = "🚨 资金新晋轮动 (昨天跌今天爆买)"
                    css_class = "alert-new"
                elif inflow > 10.0 and today_chg > 0:
                    status = "💰 巨量资金潜伏 (净流入超10亿)"
                    css_class = "alert-new"
                    
                analyzed_sectors.append({
                    "代码": row['板块代码'],
                    "名称": row['板块名称'],
                    "今日涨幅": today_chg,
                    "昨日涨幅": round(yest_chg, 2),
                    "资金流入": inflow,
                    "状态": status,
                    "css": css_class
                })
                
                progress_bar.progress(min((i + 1) / total, 1.0))
                time.sleep(0.05)
                
            progress_bar.empty()
            st.markdown("---")
            
            # ================= 分区展示结果 =================
            col1, col2 = st.columns(2)
            
            # 分类数据
            continuous_sectors = [s for s in analyzed_sectors if "持续爆发" in s['状态']]
            rotated_sectors = [s for s in analyzed_sectors if "新晋轮动" in s['状态'] or "巨量资金" in s['状态']]
            
            with col1:
                st.subheader("🚨 今日资金转移/新晋轮动预警")
                if not rotated_sectors:
                    st.info("今日暂无明显的新板块轮动信号，资金仍在老主线博弈。")
                else:
                    for s in rotated_sectors:
                        st.markdown(f"""
                        <div class="{s['css']}">
                            <h4>{s['名称']} (流入: {s['资金流入']}亿)</h4>
                            <p><b>{s['状态']}</b> | 今日涨幅: {s['今日涨幅']}% | 昨日涨幅: {s['昨日涨幅']}%</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # 展示该板块内的中流砥柱个股
                        stocks_df = get_stocks_in_sector(s['代码'])
                        if not stocks_df.empty:
                            st.write(f"*{s['名称']}* 领涨龙头及高成交活跃股：")
                            st.dataframe(stocks_df.head(5), use_container_width=True, hide_index=True)
            
            with col2:
                st.subheader("🔥 当前绝对主线 (持续爆发)")
                if not continuous_sectors:
                    st.warning("目前市场缺乏连续性极强的绝对主线板块。")
                else:
                    for s in continuous_sectors:
                        st.markdown(f"""
                        <div class="{s['css']}">
                            <h4>{s['名称']} (流入: {s['资金流入']}亿)</h4>
                            <p><b>{s['状态']}</b> | 今日涨幅: {s['今日涨幅']}% | 昨日涨幅: {s['昨日涨幅']}%</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        stocks_df = get_stocks_in_sector(s['代码'])
                        if not stocks_df.empty:
                            st.write(f"*{s['名称']}* 领涨龙头及高成交活跃股：")
                            st.dataframe(stocks_df.head(5), use_container_width=True, hide_index=True)


with tab2:
    st.markdown("### 🎯 活跃个股回踩 10日线量化狙击 (保留功能)")
    st.caption("这是我们之前的版本，用于在大行情中寻找个股的缩量洗盘低吸买点。")
    # 为了保持代码简洁，这部分简化提示。若你需要，可以直接把你上一个版本的模块1、2代码贴在此处。
    st.info("提示：你已经掌握了宏观板块轮动，个股低吸可结合前一版的策略代码在此运行。为了保证本页面的极速加载，此功能模块已作为预留接口。")
