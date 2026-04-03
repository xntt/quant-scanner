"""东方财富极速数据抓取引擎 - 终极纯净版 (0 akshare, 0 self报错)"""
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 核心请求配置 (全局拦截)
# ==========================================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/"
})
LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# ==========================================
# 纯函数数据抓取 (彻底避开类的 self 缓存问题)
# ==========================================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_board_list(b_type: str) -> pd.DataFrame:
    fs_str = "m:90+t:3+f:!50" if b_type == "concept" else "m:90+t:2+f:!50"
    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1, 
        "fltt": 2, "invt": 2, "fid": "f3", 
        "fs": fs_str,
        "fields": "f12,f14,f2,f3,f20,f8,f104,f105"
    }
    try:
        resp = SESSION.get(LIST_URL, params=params, timeout=10)
        data = resp.json()
        if not data or not data.get("data") or not data["data"].get("diff"):
            return pd.DataFrame()
        df = pd.DataFrame(data["data"]["diff"])
        df = df.rename(columns={
            "f12": "board_code", "f14": "board_name",
            "f2": "latest_price", "f3": "change_pct",
            "f20": "total_mv", "f8": "turnover_rate",
            "f104": "up_count", "f105": "down_count"
        })
        df["board_type"] = b_type
        return df
    except Exception:
        return pd.DataFrame()

def get_board_code(board_name: str, board_type: str) -> str:
    df = fetch_board_list(board_type)
    if df.empty: return ""
    match = df[df["board_name"] == board_name]
    return str(match.iloc[0]["board_code"]) if not match.empty else ""

@st.cache_data(ttl=600, show_spinner=False)
def fetch_board_history(board_name: str, board_type: str = "concept", days: int = 10) -> pd.DataFrame:
    board_code = get_board_code(board_name, board_type)
    if not board_code:
        return pd.DataFrame()

    params = {
        "secid": f"90.{board_code}", "klt": "101", "fqt": "1", "lmt": str(days),
        "end": "20500000", "iscca": "1",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    }
    try:
        resp = SESSION.get(KLINE_URL, params=params, timeout=10)
        data = resp.json()
        if not data or not data.get("data") or not data["data"].get("klines"):
            return pd.DataFrame()
        klines = data["data"]["klines"]
        parsed_data = [k.split(",") for k in klines]
        df = pd.DataFrame(parsed_data, columns=[
            "date", "open", "close", "high", "low", "volume", 
            "amount", "amplitude", "change_pct", "change_amt", "turnover_rate"
        ])
        df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def fetch_sector_fund_flow(sector_type: str = "concept") -> pd.DataFrame:
    fs_map = {"concept": "m:90+t:3+f:!50", "industry": "m:90+t:2+f:!50"}
    params = {
        "pn": 1, "pz": 200, "po": 1, "np": 1, 
        "fltt": 2, "invt": 2, "fid": "f62",
        "fs": fs_map.get(sector_type, fs_map["concept"]),
        "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
    }
    try:
        resp = SESSION.get(LIST_URL, params=params, timeout=10)
        data = resp.json()
        if not data or not data.get("data") or not data["data"].get("diff"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"]["diff"])
        df = df.rename(columns={
            "f12": "board_code", "f14": "board_name",
            "f2": "latest_price", "f3": "change_pct",
            "f62": "main_net_inflow"
        })
        if "main_net_inflow" in df.columns:
            df["main_net_inflow"] = pd.to_numeric(df["main_net_inflow"], errors="coerce") / 1e8
        df["board_type"] = sector_type
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def fetch_board_constituents(board_name: str, board_type: str = "concept") -> pd.DataFrame:
    board_code = get_board_code(board_name, board_type)
    if not board_code:
        return pd.DataFrame()

    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": f"b:{board_code}+f:!50",
        "fields": "f12,f14,f2,f3,f6,f8"
    }
    try:
        resp = SESSION.get(LIST_URL, params=params, timeout=10)
        data = resp.json()
        if not data or not data.get("data") or not data["data"].get("diff"):
            return pd.DataFrame()

        df = pd.DataFrame(data["data"]["diff"])
        df = df.rename(columns={
            "f12": "stock_code", "f14": "stock_name",
            "f2": "latest_price", "f3": "change_pct",
            "f6": "amount", "f8": "turnover_rate"
        })
        return df
    except Exception:
        return pd.DataFrame()

# ==========================================
# 兼容 app.py 的无脑包装类
# ==========================================
class EastMoneyFetcher:
    def get_concept_boards(self):
        return fetch_board_list("concept")
    
    def get_industry_boards(self):
        return fetch_board_list("industry")
        
    def get_board_history(self, board_name: str, board_type: str = "concept", days: int = 10):
        return fetch_board_history(board_name, board_type, days)
        
    def get_sector_fund_flow(self, sector_type: str = "concept"):
        return fetch_sector_fund_flow(sector_type)
        
    def get_board_constituents(self, board_name: str, board_type: str = "concept"):
        return fetch_board_constituents(board_name, board_type)

fetcher = EastMoneyFetcher()
