"""东方财富极速数据抓取引擎 - 纯直连版 (彻底摒弃 akshare)"""

import pandas as pd
import requests
import json
import streamlit as st

class EastMoneyFetcher:
    """纯粹基于东方财富底层接口的数据抓取核心类"""

    LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/"
        })

    def _get_board_code(self, board_name: str, board_type: str) -> str:
        df = self.get_concept_boards() if board_type == "concept" else self.get_industry_boards()
        if df.empty: return ""
        match = df[df["board_name"] == board_name]
        return str(match.iloc[0]["board_code"]) if not match.empty else ""

    # ==========================================
    # 1. 获取板块列表 & 行情
    # ==========================================
    @st.cache_data(ttl=300, show_spinner=False)
    def get_concept_boards(_self) -> pd.DataFrame:
        return _self._fetch_board_list("concept")

    @st.cache_data(ttl=300, show_spinner=False)
    def get_industry_boards(_self) -> pd.DataFrame:
        return _self._fetch_board_list("industry")

    def _fetch_board_list(self, b_type: str) -> pd.DataFrame:
        fs_str = "m:90+t:3+f:!50" if b_type == "concept" else "m:90+t:2+f:!50"
        params = {
            "pn": 1, "pz": 500, "po": 1, "np": 1, 
            "fltt": 2, "invt": 2, "fid": "f3", 
            "fs": fs_str,
            "fields": "f12,f14,f2,f3,f20,f8,f104,f105"
        }
        try:
            resp = self.session.get(self.LIST_URL, params=params, timeout=10)
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

    # ==========================================
    # 2. 获取板块历史 K 线
    # ==========================================
    @st.cache_data(ttl=600, show_spinner=False)
    def get_board_history(_self, board_name: str, board_type: str = "concept", days: int = 10) -> pd.DataFrame:
        board_code = _self._get_board_code(board_name, board_type)
        if not board_code:
            return pd.DataFrame()

        params = {
            "secid": f"90.{board_code}", "klt": "101", "fqt": "1", "lmt": str(days),
            "end": "20500000", "iscca": "1",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        }
        try:
            # 这里的 _self 已经彻底修复，不会再报 self not defined
            resp = _self.session.get(_self.KLINE_URL, params=params, timeout=10)
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

    # ==========================================
    # 3. 获取板块资金流 (核心数据)
    # ==========================================
    @st.cache_data(ttl=300, show_spinner=False)
    def get_sector_fund_flow(_self, sector_type: str = "concept") -> pd.DataFrame:
        fs_map = {"concept": "m:90+t:3+f:!50", "industry": "m:90+t:2+f:!50"}
        params = {
            "pn": 1, "pz": 200, "po": 1, "np": 1, 
            "fltt": 2, "invt": 2, "fid": "f62",
            "fs": fs_map.get(sector_type, fs_map["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
        }
        try:
            # 这里的 _self 已经彻底修复
            resp = _self.session.get(_self.LIST_URL, params=params, timeout=10)
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

    # ==========================================
    # 4. 获取板块成分股
    # ==========================================
    @st.cache_data(ttl=600, show_spinner=False)
    def get_board_constituents(_self, board_name: str, board_type: str = "concept") -> pd.DataFrame:
        board_code = _self._get_board_code(board_name, board_type)
        if not board_code:
            return pd.DataFrame()

        params = {
            "pn": 1, "pz": 500, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": f"b:{board_code}+f:!50",
            "fields": "f12,f14,f2,f3,f6,f8"
        }
        try:
            # 这里的 _self 已经彻底修复
            resp = _self.session.get(_self.LIST_URL, params=params, timeout=10)
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

# 全局单例
fetcher = EastMoneyFetcher()
