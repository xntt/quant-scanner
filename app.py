import streamlit as st
import pandas as pd
import requests
import time

# ==========================================
# 页面与全局样式配置 (极客/专业终端风格)
# ==========================================
st.set_page_config(page_title="游资大局观：资金转移矩阵", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1, h2, h3 {color: #ff4b4b;}
    /* 资金转移/新晋板块的高亮警报盒 */
    .rotation-alert {
        background: linear-gradient(90deg, #1a4a1a 0%, #0e1117 100%);
        border-left: 8px solid #00ff00;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
    /* 连续爆发/绝对主线的高亮警报盒 */
    .continuous-alert {
        background: linear-gradient(90deg, #4a1a1a 0%, #0e1117 100%);
        border-left: 8px solid #ff4b4b;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
    .metric-text {font-size: 1.1em; color: #ccc;}
    .highlight-red {color: #ff4b4b; font-weight: bold;}
    .highlight-green {color: #00ff00; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

st.title("🦅 游资大局观：板块资金轮动与核心载体拆解")
st.markdown("**(深度定制版)** 核心逻辑：精准捕捉【资金次日转移路线】与【2日连涨主线】，并深度拆解板块内**涨停先锋**与**高成交趋势中军**（不限连板）。")

# ==========================================
# 核心数据引擎 (直连东方财富底层 API)
# ==========================================
def get_sector_pool():
    """获取今日所有行业板块的宏观数据（按资金流入和涨幅双向评估）"""
    try:
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "60", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f62", # 优先按主力净流入排序
            "fs": "m:90 t:2 s:8228",
            "fields": "f12,f14,f2,f3,f62" 
        }
        res = requests.get(url, params=params, timeout=5).json()
        data = res['data']['diff']
        sectors = []
        for item in data:
            sectors.append({
                '代码': item['f12'],
                '名称': item['f14'],
                '今日涨幅': float(item['f3']) if item['f3'] != "-" else 0.0,
                '主力净流入(亿)': round(float(item['f62'])/100000000, 2) if item['f62'] != "-" else 0.0,
            })
        return pd.DataFrame(sectors)
    except:
        return pd.DataFrame()

def get_sector_history(sector_code):
    """获取板块近3日K线，用于精准判断是'连涨延续'还是'资金新晋突袭(轮动)'"""
    try:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": f"90.{sector_code}",
            "fields1": "f1,f2,f3", "fields2": "f51,f53", 
            "klt": "101", "fqt": "1", "end": "20500101", "lmt": "3" 
        }
        res = requests.get(url, params=params, timeout=5).json()
        klines = res['data']['klines']
        closes = [float(k.split(',')[1]) for k in klines]
        
        yest_chg = 0.0
        if len(closes) >= 3:
            yest_chg = (closes[1] - closes[0]) / closes[0] * 100
        elif len(closes) == 2:
            yest_chg = (closes[1] - closes[0]) / closes[0] * 100
            
        return round(yest_chg, 2)
    except:
        return 0.0

def get_sector_core_stocks(sector_code):
    """深度提取板块内部个股：不仅看涨停，重点看成交额大、涨幅明显的游资趋势载体"""
    try:
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "30", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f6", # 按成交额(活跃度)排序，提取容纳大资金的票
            "fs": f"b:{sector_code}",
            "fields": "f12,f14,f2,f3,f6,f8,f62" 
        }
        res = requests.get(url, params=params, timeout=5).json()
        data = res['data']['diff']
        
        stocks = []
        for item in data:
            if item['f2'] == "-" or "ST" in str(item['f14']): continue
            chg = float(item['f3']) if item['f3'] != "-" else 0.0
            amount = round(float(item['f6'])/100000000, 2) if item['f6'] != "-" else 0.0
            inflow = round(float(item['f62'])/100000000, 2) if item['f62'] != "-" else 0.0
            
            # 只提取：要么涨幅大于3%，要么成交额极大(大于10亿)的核心活跃股
            if chg > 3.0 or amount > 10.0: 
                stocks.append({
                    '代码': item['f12'],
                    '名称': item['f14'],
                    '最新价': float(item['f2']),
                    '涨跌幅(%)': chg,
                    '成交额(亿)': amount,
                    '主力净流入(亿)': inflow,
                    '换手率(%)': float(item['f8']) if item['f8'] != "-" else 0.0,
                    '形态标签': '🔥 涨停/逼近涨停' if chg >= 9.5 else ('📈 趋势大涨' if chg >= 5.0 else '🌊 活跃震荡')
                })
        df = pd.DataFrame(stocks)
        if not df.empty:
            df = df.sort_values(by=['涨跌幅(%)', '成交额(亿)'], ascending=[False, False])
        return df
    except:
        return pd.DataFrame()

# ==========================================
# Pandas 数据高亮渲染函数
# ==========================================
def style_dataframe(df):
    if df.empty: return df
    
    def highlight_cols(s):
        if s.name == '涨跌幅(%)':
            return ['color: #ff4b4b; font-weight: bold' if v > 0 else 'color: #00ff00' for v in s]
        elif s.name == '主力净流入(亿)':
            return ['color: #ff4b4b' if v > 0 else 'color: #00ff00' for v in s]
        return ['' for _ in s]

    return df.style.apply(highlight_cols).format({
        '最新价': "{:.2f}",
        '涨跌幅(%)': "{:.2f}%",
        '成交额(亿)': "{:.2f}",
        '主力净流入(亿)': "{:.2f}",
        '换手率(%)': "{:.2f}%"
    }).set_properties(**{'background-color': '#1e1e1e', 'border-color': '#333'})

# ==========================================
# 系统主执行逻辑
# ==========================================
if st.button("🚀 执行全景深度扫描：捕捉资金路线与核心载体", use_container_width=True):
    with st.spinner("正在扫描宏观板块数据并比对历史资金路线..."):
        df_sectors = get_sector_pool()
        if df_sectors.empty:
            st.error("无法获取板块数据，请检查网络。")
            st.stop()
            
        progress_bar = st.progress(0.0)
        total_scan = 25  # 扫描最活跃的前25个板块
        
        rotated_sectors = []    # 新晋轮动/资金转移
        continuous_sectors = [] # 持续发酵/绝对主线
        
        for i in range(total_scan):
            row = df_sectors.iloc[i]
            code = row['代码']
            name = row['名称']
            today_chg = row['今日涨幅']
            inflow = row['主力净流入(亿)']
            
            yest_chg = get_sector_history(code)
            
            # === 核心判定逻辑 ===
            # 1. 发现资金转移 (高低切): 昨天弱(<=1%)，今天强(>1.5%)且资金大幅流入
            if today_chg > 1.5 and yest_chg <= 1.0 and inflow > 5.0:
                rotated_sectors.append({
                    "name": name, "code": code, "today_chg": today_chg, "yest_chg": yest_chg, "inflow": inflow
                })
            # 2. 发现持续主线 (2日连涨): 昨天强(>1.5%)，今天继续强(>1.5%)
            elif today_chg > 1.5 and yest_chg > 1.5:
                continuous_sectors.append({
                    "name": name, "code": code, "today_chg": today_chg, "yest_chg": yest_chg, "inflow": inflow
                })
                
            progress_bar.progress(min((i + 1) / total_scan, 1.0))
            time.sleep(0.05)
            
        progress_bar.empty()
        
        # ==========================================
        # 结果渲染：极其详尽的细节展示
        # ==========================================
        
        # 模块A：资金转移预警 (游资最爱打的新周期第一天)
        st.markdown("### 🚨 第一阵营：今日资金猛烈转移 / 新晋轮动预警")
        st.markdown("<span style='color:gray;'>逻辑特征：昨日该板块处于冷板凳或分歧下跌，今日突遭主力资金巨量突袭，爆发拉升。这往往预示着资金从老主线高低切换，**是介入新周期的极佳观察点！**</span>", unsafe_allow_html=True)
        
        if not rotated_sectors:
            st.info("今日未检测到明显的板块高低切和资金大举转移，资金可能在观望或继续抱团。")
        else:
            for sec in rotated_sectors:
                st.markdown(f"""
                <div class="rotation-alert">
                    <h3 style="margin-top:0;">{sec['name']} <span style="font-size:16px; font-weight:normal; color:#ccc;">(代码: {sec['code']})</span></h3>
                    <p class="metric-text">
                        昨日涨跌: <span class="{'highlight-red' if sec['yest_chg']>0 else 'highlight-green'}">{sec['yest_chg']}%</span> 
                        &nbsp;➡️&nbsp; 
                        今日爆发: <span class="highlight-red">{sec['today_chg']}%</span> 
                        &nbsp;&nbsp;|&nbsp;&nbsp; 
                        今日主力暴击流入: <span class="highlight-red">{sec['inflow']} 亿</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                # 深度拆解个股
                df_stocks = get_sector_core_stocks(sec['code'])
                if not df_stocks.empty:
                    st.markdown(f"**【{sec['name']}】内部核心活跃载体拆解 (按热度与涨幅降序)：**")
                    st.dataframe(style_dataframe(df_stocks), use_container_width=True, height=250)
                st.markdown("<br>", unsafe_allow_html=True)
                
        st.markdown("---")
        
        # 模块B：持续主线预警 (游资抱团的深水区)
        st.markdown("### 🔥 第二阵营：连续 2 日以上爆发 / 绝对主线")
        st.markdown("<span style='color:gray;'>逻辑特征：昨日大涨，今日继续大涨。说明该板块是当下市场的绝对主线，资金抱团极深。**切忌盲目追高缩量一字板，重点观察下方表格中【成交额极大且涨幅在5%-8%的趋势中军】**。</span>", unsafe_allow_html=True)
        
        if not continuous_sectors:
            st.info("今日未检测到具备强烈连续性的板块。市场可能处于混沌期或快速轮动期。")
        else:
            for sec in continuous_sectors:
                st.markdown(f"""
                <div class="continuous-alert">
                    <h3 style="margin-top:0;">{sec['name']} <span style="font-size:16px; font-weight:normal; color:#ccc;">(代码: {sec['code']})</span></h3>
                    <p class="metric-text">
                        昨日涨跌: <span class="highlight-red">{sec['yest_chg']}%</span> 
                        &nbsp;➡️&nbsp; 
                        今日涨跌: <span class="highlight-red">{sec['today_chg']}%</span> 
                        &nbsp;&nbsp;|&nbsp;&nbsp; 
                        主力净流入维持: <span class="{'highlight-red' if sec['inflow']>0 else 'highlight-green'}">{sec['inflow']} 亿</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                # 深度拆解个股
                df_stocks = get_sector_core_stocks(sec['code'])
                if not df_stocks.empty:
                    st.markdown(f"**【{sec['name']}】内部核心活跃载体拆解 (趋势中军与领涨先锋)：**")
                    st.dataframe(style_dataframe(df_stocks), use_container_width=True, height=250)
                st.markdown("<br>", unsafe_allow_html=True)

else:
    st.info("👆 请点击上方【执行全景深度扫描】按钮，获取今日市场游资最新动向。")
