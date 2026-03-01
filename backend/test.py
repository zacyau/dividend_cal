import akshare as ak
import pandas as pd

try:
    df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20230101", end_date="20230110")
    print("Connection OK:", df.head())
except Exception as e:
    print("Connection Failed:", e)