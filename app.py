import streamlit as st
import pandas as pd
import time

# 导入你的配置和数据引擎
from config import *
from data_fetcher import fetcher

# ==========================================
# 页面与全局样式配置 (极客/专业终端风格)
# ==========================================
st.set_page_config(page_title="游资大局观：资金转移矩阵", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
    <style>
    .main {{background-color: #0e1117;}}
    h1, h2, h3 {{color: #ff4b4b;}}
    /* 资金转移/新晋板块的高亮警报盒 */
    .rotation-alert {{
        background: linear-gradient(90deg, #1a4a1a 0%, #0e1117 100%);
        border-left: 8px solid {ROTATION_IN_COLOR};
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }}
    /* 连续爆发/绝对主线的高亮警报盒 */
    .continuous-alert {{
        background: linear-gradient(90deg, #4a1a1a 0%, #0e1117 100%);
        border-left: 8px solid {ALERT_COLOR_HIGH};
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }}
    .metric-text {{font-size: 1.1em; color: #ccc;}}
    .highlight-red {{color: {ALERT_COLOR_HIGH}; font-weight: bold;}}
    .highlight-green {{color: {ROTATION_IN_COLOR}; font-weight: bold;}}
    </style>
    """, unsafe_allow_html=True)

st.title("🦅 游资大局观：板块资金轮动与核心载体拆解")
st.markdown("**(东方财富极速版)** 核心逻辑：精准捕捉【资金次日转移路线】与【2日连涨主线】，深度拆解板块内涨停先锋与趋势中军。")

# ==========================================
# 侧边栏：引擎参数面板 (直接读取 config.py)
# ==========================================
st.sidebar.header("⚙️ 核心引擎参数 (来自 config.py)")
board_type = st.sidebar.radio("选择扫描板块类型", ["industry", "concept"], format_func=lambda x: "🏢 行业板块" if x == "industry" else "💡 概念板块")
st.sidebar.markdown("---")
st.sidebar.metric("连续上涨天数阈值", f"{CONSECUTIVE_DAYS} 天")
st.sidebar.metric("板块异动涨幅阈值", f"{SECTOR_GAIN_THRESHOLD}%")
st.sidebar.metric("资金轮入预警线", f"{ROTATION_INFLOW_THRESHOLD} 亿元")
st.sidebar.metric("个股显著涨幅阈值", f"{STOCK_GAIN_THRESHOLD}%")
st.sidebar.metric("游资中军成交额线", "10.0 亿元")

# ==========================================
# 辅助函数：安全解析数据字段 (兼容 akshare 和 raw_api)
# ==========================================
def normalize_flow_df(df, b_type):
    """标准化资金流数据格式，兼容 akshare 和 东方财富原始API字段"""
    if df.empty: return df
    
    # 如果是 raw_api 跑出来的数据，自带 board_name 和 main_net_inflow
    if "board_name" in df.columns and "main_net_inflow" in df.columns:
        return df
        
    # 如果是 akshare 跑出来的数据，需要转换列名
    rename_map = {}
    if b_type == "industry":
        rename_map = {
            "板块名称": "board_name", 
            "今日涨跌幅": "change_pct", 
            "今日主力净流入-净额": "main_net_inflow"
        }
    else:
        rename_map = {
            "行业": "board_name", # 有时概念也叫行业列
            "板块名称": "board_name",
            "涨跌幅": "change_pct", 
            "主力净流入-净额": "main_net_inflow"
        }
    
    df = df.rename(columns=rename_map)
    # akshare 返回的主力净流入可能是 元，需要转成 亿
    if "main_net_inflow" in df.columns and df["main_net_inflow"].abs().max() > 10000:
        df["main_net_inflow"] = df["main_net_inflow"] / 1e8
        
    return df

# ==========================================
# Pandas 样式渲染
# ==========================================
def style_dataframe(df):
    if df.empty: return df
    
    def highlight_cols(s):
        if s.name == '涨跌幅(%)':
            return ['color: #ff4b4b; font-weight: bold' if v > 0 else 'color: #00ff00' for v in s]
        elif s.name == '今日换手率(%)':
            return ['color: #FFCC00' if v > 15 else '' for v in s] # 换手率大于15%高亮
        return ['' for _ in s]

    return df.style.apply(highlight_cols).format({
        '最新价': "{:.2f}",
        '涨跌幅(%)': "{:.2f}%",
        '成交额(亿)': "{:.2f}",
        '今日换手率(%)': "{:.2f}%"
    }).set_properties(**{'background-color': '#1e1e1e', 'border-color': '#333'})

# ==========================================
# 主体执行逻辑
# ==========================================
if st.button("🚀 启动大局观全景扫描", use_container_width=True):
    with st.spinner(f"正在通过 EastMoneyFetcher 抓取【{board_type}】资金池..."):
        # 1. 获取全市场板块资金流
        raw_flow_df = fetcher.get_sector_fund_flow(board_type)
        flow_df = normalize_flow_df(raw_flow_df, board_type)
        
        if flow_df.empty or "board_name" not in flow_df.columns:
            st.error("数据拉取失败，请检查网络或 akshare 接口状态。")
            st.stop()
            
        # 按资金流入降序，取前 N 个热点板块
        top_sectors = flow_df.sort_values("main_net_inflow", ascending=False).head(TOP_N_SECTORS)
        
        progress_bar = st.progress(0.0)
        
        rotated_sectors = []    # 资金轮动阵营
        continuous_sectors = [] # 持续发酵阵营
        
        for i, (idx, row) in enumerate(top_sectors.iterrows()):
            b_name = row['board_name']
            today_chg = float(row.get('change_pct', 0.0))
            inflow = float(row.get('main_net_inflow', 0.0))
            
            # 2. 调用引擎：获取历史K线，判定昨日涨跌幅
            hist_df = fetcher.get_board_history(b_name, board_type, days=5)
            yest_chg = 0.0
            if not hist_df.empty and len(hist_df) >= 2:
                # 倒数第二条数据即为昨天
                yest_chg = hist_df.iloc[-2]['change_pct']
                
            # === 核心轮动预警逻辑 (基于 config.py 参数) ===
            # 【新晋轮动】今天大涨且资金狂涌，但昨天没涨甚至在跌
            is_rotation = (today_chg >= SECTOR_GAIN_THRESHOLD) and (yest_chg <= 1.0) and (inflow >= ROTATION_INFLOW_THRESHOLD)
            
            # 【持续主线】今天涨，昨天也涨
            is_continuous = (today_chg >= SECTOR_GAIN_THRESHOLD) and (yest_chg >= SECTOR_GAIN_THRESHOLD)
            
            if is_rotation:
                rotated_sectors.append({
                    "name": b_name, "today_chg": today_chg, "yest_chg": yest_chg, "inflow": inflow
                })
            elif is_continuous:
                continuous_sectors.append({
                    "name": b_name, "today_chg": today_chg, "yest_chg": yest_chg, "inflow": inflow
                })
                
            progress_bar.progress(min((i + 1) / TOP_N_SECTORS, 1.0))
            time.sleep(0.02) # 防封控延迟
            
        progress_bar.empty()
        
        # ==========================================
        # 结果渲染：极其详尽的细节展示
        # ==========================================
        
        # --------- 模块A：资金转移预警 ---------
        st.markdown(f"### 🚨 第一阵营：今日资金猛烈转移 / 新晋轮动预警")
        st.markdown("<span style='color:gray;'>逻辑特征：昨日冷板凳，今日主力资金突袭流入。介入新周期的极佳观察点！</span>", unsafe_allow_html=True)
        
        if not rotated_sectors:
            st.info("今日未检测到符合阈值的板块高低切，资金可能在观望或死守老主线。")
        else:
            for sec in rotated_sectors:
                st.markdown(f"""
                <div class="rotation-alert">
                    <h3 style="margin-top:0;">{sec['name']}</h3>
                    <p class="metric-text">
                        昨日表现: <span class="{'highlight-red' if sec['yest_chg']>0 else 'highlight-green'}">{sec['yest_chg']:.2f}%</span> 
                        &nbsp;➡️&nbsp; 
                        今日爆发: <span class="highlight-red">{sec['today_chg']:.2f}%</span> 
                        &nbsp;&nbsp;|&nbsp;&nbsp; 
                        今日主力抢筹: <span class="highlight-red">{sec['inflow']:.2f} 亿</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                # 调用引擎：拉取板块成分股
                cons_df = fetcher.get_board_constituents(sec['name'], board_type)
                if not cons_df.empty:
                    # 数据清洗与游资大局观过滤
                    cons_df['amount'] = pd.to_numeric(cons_df.get('amount', 0), errors='coerce') / 1e8 # 转为亿元
                    cons_df['change_pct'] = pd.to_numeric(cons_df.get('change_pct', 0), errors='coerce')
                    cons_df['turnover_rate'] = pd.to_numeric(cons_df.get('turnover_rate', 0), errors='coerce')
                    
                    # 过滤条件：涨幅 > STOCK_GAIN_THRESHOLD 或 成交额巨大(>10亿)
                    core_stocks = cons_df[(cons_df['change_pct'] >= STOCK_GAIN_THRESHOLD) | (cons_df['amount'] >= 10.0)].copy()
                    
                    if not core_stocks.empty:
                        # 打形态标签
                        core_stocks['形态标签'] = core_stocks['change_pct'].apply(
                            lambda x: '🔥 涨停先锋' if x >= STOCK_LIMIT_UP_THRESHOLD else ('📈 趋势大涨' if x >= STOCK_GAIN_THRESHOLD else '🌊 容量中军')
                        )
                        
                        # 重命名以便展示
                        display_df = core_stocks[['stock_code', 'stock_name', 'latest_price', 'change_pct', 'amount', 'turnover_rate', '形态标签']]
                        display_df.columns = ['代码', '名称', '最新价', '涨跌幅(%)', '成交额(亿)', '今日换手率(%)', '形态标签']
                        display_df = display_df.sort_values(by=['涨跌幅(%)', '成交额(亿)'], ascending=[False, False]).head(TOP_N_STOCKS)
                        
                        st.markdown(f"**【{sec['name']}】内部核心游资载体拆解：**")
                        st.dataframe(style_dataframe(display_df), use_container_width=True, hide_index=True)
                st.markdown("<br>", unsafe_allow_html=True)
                
        st.markdown("---")
        
        # --------- 模块B：持续主线预警 ---------
        st.markdown(f"### 🔥 第二阵营：连续 {CONSECUTIVE_DAYS} 日爆发 / 绝对主线")
        st.markdown("<span style='color:gray;'>逻辑特征：连续大涨，资金抱团极深。切忌追高，重点观察内部的大成交趋势中军。</span>", unsafe_allow_html=True)
        
        if not continuous_sectors:
            st.info("今日未检测到具备强烈连续性的主线板块。")
        else:
            for sec in continuous_sectors:
                st.markdown(f"""
                <div class="continuous-alert">
                    <h3 style="margin-top:0;">{sec['name']}</h3>
                    <p class="metric-text">
                        昨日大涨: <span class="highlight-red">{sec['yest_chg']:.2f}%</span> 
                        &nbsp;➡️&nbsp; 
                        今日大涨: <span class="highlight-red">{sec['today_chg']:.2f}%</span> 
                        &nbsp;&nbsp;|&nbsp;&nbsp; 
                        主力净流入: <span class="{'highlight-red' if sec['inflow']>0 else 'highlight-green'}">{sec['inflow']:.2f} 亿</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                cons_df = fetcher.get_board_constituents(sec['name'], board_type)
                if not cons_df.empty:
                    cons_df['amount'] = pd.to_numeric(cons_df.get('amount', 0), errors='coerce') / 1e8
                    cons_df['change_pct'] = pd.to_numeric(cons_df.get('change_pct', 0), errors='coerce')
                    cons_df['turnover_rate'] = pd.to_numeric(cons_df.get('turnover_rate', 0), errors='coerce')
                    
                    core_stocks = cons_df[(cons_df['change_pct'] >= STOCK_GAIN_THRESHOLD) | (cons_df['amount'] >= 10.0)].copy()
                    
                    if not core_stocks.empty:
                        core_stocks['形态标签'] = core_stocks['change_pct'].apply(
                            lambda x: '🔥 涨停先锋' if x >= STOCK_LIMIT_UP_THRESHOLD else ('📈 趋势大涨' if x >= STOCK_GAIN_THRESHOLD else '🌊 容量中军')
                        )
                        display_df = core_stocks[['stock_code', 'stock_name', 'latest_price', 'change_pct', 'amount', 'turnover_rate', '形态标签']]
                        display_df.columns = ['代码', '名称', '最新价', '涨跌幅(%)', '成交额(亿)', '今日换手率(%)', '形态标签']
                        display_df = display_df.sort_values(by=['涨跌幅(%)', '成交额(亿)'], ascending=[False, False]).head(TOP_N_STOCKS)
                        
                        st.markdown(f"**【{sec['name']}】内部核心游资载体拆解：**")
                        st.dataframe(style_dataframe(display_df), use_container_width=True, hide_index=True)
                st.markdown("<br>", unsafe_allow_html=True)
else:
    st.info("👆 请点击上方【启动大局观全景扫描】按钮。系统将调度 `EastMoneyFetcher` 读取实时行情。")
