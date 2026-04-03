# data_fetcher.py
"""东方财富数据抓取引擎 - 板块资金流/行情/成分股"""

import akshare as ak
import pandas as pd
import requests
import json
import time
from datetime import datetime, timedelta
from functools import lru_cache
import streamlit as st


class EastMoneyFetcher:
    """东方财富数据抓取核心类"""

    # 东方财富板块资金流API
    SECTOR_FLOW_URL = "https://push2.eastmoney.com/api/qt/clist/get"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/"
        })

    # ------------------------------------------------------------------
    #  板块列表 & 实时行情
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300, show_spinner=False)
    def get_concept_boards(_self) -> pd.DataFrame:
        """获取概念板块列表 + 实时行情"""
        try:
            df = ak.stock_board_concept_name_em()
            df = df.rename(columns={
                "板块名称": "board_name",
                "板块代码": "board_code",
                "最新价": "latest_price",
                "涨跌幅": "change_pct",
                "总市值": "total_mv",
                "换手率": "turnover_rate",
                "上涨家数": "up_count",
                "下跌家数": "down_count",
            })
            df["board_type"] = "concept"
            return df
        except Exception as e:
            st.warning(f"概念板块数据获取失败: {e}")
            return pd.DataFrame()

    @st.cache_data(ttl=300, show_spinner=False)
    def get_industry_boards(_self) -> pd.DataFrame:
        """获取行业板块列表 + 实时行情"""
        try:
            df = ak.stock_board_industry_name_em()
            df = df.rename(columns={
                "板块名称": "board_name",
                "板块代码": "board_code",
                "最新价": "latest_price",
                "涨跌幅": "change_pct",
                "总市值": "total_mv",
                "换手率": "turnover_rate",
                "上涨家数": "up_count",
                "下跌家数": "down_count",
            })
            df["board_type"] = "industry"
            return df
        except Exception as e:
            st.warning(f"行业板块数据获取失败: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  板块历史行情（用于连续涨幅判定）
    # ------------------------------------------------------------------
    @st.cache_data(ttl=600, show_spinner=False)
    def get_board_history(_self, board_name: str, board_type: str = "concept",
                          days: int = 10) -> pd.DataFrame:
        """获取板块历史K线数据"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

            if board_type == "concept":
                df = ak.stock_board_concept_hist_em(
                    symbol=board_name, period="日k",
                    start_date=start_date, end_date=end_date, adjust=""
                )
            else:
                df = ak.stock_board_industry_hist_em(
                    symbol=board_name, period="日k",
                    start_date=start_date, end_date=end_date, adjust=""
                )

            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "涨跌幅": "change_pct", "涨跌额": "change_amt",
                "换手率": "turnover_rate"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df
        except Exception as e:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  板块资金流（核心数据）
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300, show_spinner=False)
    def get_sector_fund_flow(_self, sector_type: str = "concept") -> pd.DataFrame:
        """
        获取板块资金流向排名
        sector_type: 'concept' 概念 / 'industry' 行业
        """
        try:
            if sector_type == "concept":
                df = ak.stock_concept_fund_flow_hist(symbol="即时")
            else:
                df = ak.stock_sector_fund_flow_rank(indicator="今日")

            return df
        except Exception:
            pass

        # 备用方案：直接请求东方财富API
        try:
            return _self._fetch_sector_flow_raw(sector_type)
        except Exception as e:
            st.warning(f"板块资金流数据获取失败: {e}")
            return pd.DataFrame()

    def _fetch_sector_flow_raw(self, sector_type: str) -> pd.DataFrame:
        """直接请求东方财富板块资金流API"""
        fs_map = {
            "concept": "m:90+t:3+f:!50",
            "industry": "m:90+t:2+f:!50"
        }
        params = {
            "cb": "jQuery_callback",
            "pn": 1, "pz": 200,
            "po": 1,  # 降序
            "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2,
            "fid": "f62",  # 按主力净流入排序
            "fs": fs_map.get(sector_type, fs_map["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
        }
        resp = self.session.get(self.SECTOR_FLOW_URL, params=params, timeout=10)
        text = resp.text
        json_str = text[text.index("(") + 1: text.rindex(")")]
        data = json.loads(json_str)

        if not data.get("data") or not data["data"].get("diff"):
            return pd.DataFrame()

        records = data["data"]["diff"]
        df = pd.DataFrame(records)
        df = df.rename(columns={
            "f12": "board_code", "f14": "board_name",
            "f2": "latest_price", "f3": "change_pct",
            "f62": "main_net_inflow",       # 主力净流入(元)
            "f184": "main_net_inflow_pct",   # 主力净流入占比(%)
            "f66": "super_large_inflow",     # 超大单净流入
            "f69": "super_large_inflow_pct",
            "f72": "large_inflow",           # 大单净流入
            "f75": "large_inflow_pct",
            "f78": "medium_inflow",          # 中单净流入
            "f81": "medium_inflow_pct",
            "f84": "small_inflow",           # 小单净流入
            "f87": "small_inflow_pct",
        })

        # 转换为亿元
        money_cols = ["main_net_inflow", "super_large_inflow", "large_inflow",
                      "medium_inflow", "small_inflow"]
        for col in money_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce") / 1e8

        df["board_type"] = sector_type
        return df

    # ------------------------------------------------------------------
    #  板块历史资金流（多日）
    # ------------------------------------------------------------------
    @st.cache_data(ttl=600, show_spinner=False)
    def get_sector_fund_flow_history(_self, board_name: str,
                                      sector_type: str = "concept") -> pd.DataFrame:
        """获取板块多日资金流向"""
        try:
            if sector_type == "concept":
                df = ak.stock_concept_fund_flow_hist(symbol=board_name)
            else:
                df = ak.stock_sector_fund_flow_hist(symbol=board_name)
            return df
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  板块成分股
    # ------------------------------------------------------------------
    @st.cache_data(ttl=600, show_spinner=False)
    def get_board_constituents(_self, board_name: str,
                                board_type: str = "concept") -> pd.DataFrame:
        """获取板块成分股列表 + 实时行情"""
        try:
            if board_type == "concept":
                df = ak.stock_board_concept_cons_em(symbol=board_name)
            else:
                df = ak.stock_board_industry_cons_em(symbol=board_name)

            df = df.rename(columns={
                "代码": "stock_code", "名称": "stock_name",
                "最新价": "latest_price", "涨跌幅": "change_pct",
                "涨跌额": "change_amt", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "最高": "high", "最低": "low",
                "今开": "open", "昨收": "pre_close",
                "换手率": "turnover_rate",
            })
            return df
        except Exception as e:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  个股资金流
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300, show_spinner=False)
    def get_stock_fund_flow(_self, stock_code: str) -> pd.DataFrame:
        """获取个股资金流向"""
        try:
            df = ak.stock_individual_fund_flow(stock=stock_code, market="sh"
                                                if stock_code.startswith("6") else "sz")
            return df
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  涨停板数据
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300, show_spinner=False)
    def get_limit_up_stocks(_self, date: str = None) -> pd.DataFrame:
        """获取涨停股列表"""
        try:
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_em(date=date)
            return df
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    #  连板股数据
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300, show_spinner=False)
    def get_continuous_limit_up(_self, date: str = None) -> pd.DataFrame:
        """获取连板股列表"""
        try:
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_zbgc_em(date=date)
            return df
        except Exception:
            return pd.DataFrame()


# 全局单例
fetcher = EastMoneyFetcher()
