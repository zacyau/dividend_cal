from flask import Flask, jsonify, request
from flask_cors import CORS
import akshare as ak
import pandas as pd
from datetime import datetime
import threading
import time

app = Flask(__name__)
CORS(app)

stock_list_cache = None
stock_list_last_update = 0
STOCK_LIST_CACHE_TTL = 300

def get_stock_list():
    global stock_list_cache, stock_list_last_update
    current_time = time.time()
    
    if stock_list_cache is None or (current_time - stock_list_last_update) > STOCK_LIST_CACHE_TTL:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Fetching stock list from akshare... (attempt {attempt + 1}/{max_retries})")
                df = ak.stock_zh_a_spot_em()
                stock_list_cache = df
                stock_list_last_update = current_time
                print(f"Stock list cached, {len(df)} stocks")
                break
            except Exception as e:
                print(f"Error fetching stock list (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                if stock_list_cache is None:
                    return pd.DataFrame()
    
    return stock_list_cache

def refresh_stock_list_periodically():
    while True:
        time.sleep(STOCK_LIST_CACHE_TTL)
        get_stock_list()

cache_thread = threading.Thread(target=refresh_stock_list_periodically, daemon=True)
cache_thread.start()

get_stock_list()

def get_stock_dividend_history(stock_code):
    try:
        df = ak.stock_dividend_cninfo(symbol=stock_code)
        if df.empty:
            return None
        df = df.sort_values(by='实施方案公告日期', ascending=True)
        return df
    except Exception as e:
        print(f"Error fetching dividend data: {e}")
        return None

def get_stock_price_history(stock_code, start_year):
    try:
        start_date = f"{start_year}0101"
        end_date = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty:
            return None
        df['日期'] = pd.to_datetime(df['日期'])
        return df
    except Exception as e:
        print(f"Error fetching price data: {e}")
        return None

def calculate_dividend_payback(stock_code, buy_year, buy_price=None, buy_shares=1000):
    dividend_df = get_stock_dividend_history(stock_code)
    if dividend_df is None or dividend_df.empty:
        return {"error": "无法获取分红数据"}
    
    price_df = None
    if buy_price is None:
        price_df = get_stock_price_history(stock_code, buy_year)
        if price_df is None or price_df.empty:
            return {"error": "无法获取股价数据"}
        
        year_start = pd.Timestamp(f"{buy_year}-01-01")
        year_end = pd.Timestamp(f"{buy_year}-12-31")
        year_data = price_df[(price_df['日期'] >= year_start) & (price_df['日期'] <= year_end)]
        if year_data.empty:
            year_data = price_df[price_df['日期'].dt.year == buy_year]
        
        if not year_data.empty:
            buy_price = float(year_data.iloc[0]['收盘'])
        else:
            buy_price = float(price_df.iloc[0]['收盘'])
    else:
        price_df = get_stock_price_history(stock_code, buy_year)
    
    dividends = []
    for _, row in dividend_df.iterrows():
        try:
            announce_date = str(row['实施方案公告日期'])
            year = int(announce_date[:4])
            if year >= buy_year:
                cash_dividend = float(row['派息比例']) / 10 if pd.notna(row['派息比例']) else 0
                stock_dividend = float(row['送股比例']) / 10 if pd.notna(row['送股比例']) else 0
                stock_transfer = float(row['转增比例']) / 10 if pd.notna(row['转增比例']) else 0
                
                if cash_dividend > 0 or stock_dividend > 0 or stock_transfer > 0:
                    dividends.append({
                        'year': year,
                        'cash_dividend': cash_dividend,
                        'stock_dividend': stock_dividend,
                        'stock_transfer': stock_transfer,
                        'total_dividend_per_share': cash_dividend,
                        'date': announce_date
                    })
        except Exception as e:
            print(f"Error processing row: {e}")
            continue
    
    dividends.sort(key=lambda x: x['year'])
    
    if not dividends:
        return {"error": "该股票在指定年份后没有分红记录"}
    
    total_cost = buy_price * buy_shares
    result_without_reinvest = calculate_without_reinvest(dividends, buy_price, buy_shares, total_cost)
    result_with_reinvest = calculate_with_reinvest(dividends, buy_price, buy_shares, total_cost, price_df)
    
    return {
        "stock_code": stock_code,
        "buy_year": buy_year,
        "buy_price": buy_price,
        "buy_shares": buy_shares,
        "total_cost": round(total_cost, 2),
        "dividends": dividends,
        "without_reinvest": result_without_reinvest,
        "with_reinvest": result_with_reinvest
    }

def calculate_without_reinvest(dividends, buy_price, buy_shares, total_cost):
    total_cash_dividend = 0
    current_shares = float(buy_shares)
    years_to_payback = None
    yearly_data = []
    
    for div in dividends:
        cash_dividend = div['cash_dividend'] * current_shares
        total_cash_dividend += cash_dividend
        
        stock_bonus = int(current_shares * div['stock_dividend'])
        stock_transfer = int(current_shares * div['stock_transfer'])
        new_shares_from_bonus = stock_bonus
        new_shares_from_transfer = stock_transfer
        
        yearly_data.append({
            'year': div['year'],
            'cash_per_share': div['cash_dividend'],
            'stock_bonus_per_share': div['stock_dividend'],
            'stock_transfer_per_share': div['stock_transfer'],
            'yearly_cash_dividend': round(cash_dividend, 2),
            'total_cash_dividend': round(total_cash_dividend, 2),
            'shares_before': int(current_shares),
            'new_shares_from_bonus': new_shares_from_bonus,
            'new_shares_from_transfer': new_shares_from_transfer,
            'shares_after': int(current_shares + new_shares_from_bonus + new_shares_from_transfer),
            'payback_ratio': round(total_cash_dividend / total_cost * 100, 2)
        })
        
        current_shares += new_shares_from_bonus + new_shares_from_transfer
        
        if years_to_payback is None and total_cash_dividend >= total_cost:
            years_to_payback = div['year'] - dividends[0]['year'] + 1
    
    return {
        "years_to_payback": years_to_payback,
        "total_dividend": round(total_cash_dividend, 2),
        "final_shares": int(current_shares),
        "payback_ratio": round(total_cash_dividend / total_cost * 100, 2),
        "yearly_data": yearly_data
    }

def calculate_with_reinvest(dividends, buy_price, buy_shares, total_cost, price_df):
    current_shares = float(buy_shares)
    total_cash_dividend = 0
    total_cash_used_for_reinvest = 0
    years_to_payback = None
    yearly_data = []
    cash_balance = 0.0
    
    for div in dividends:
        year = div['year']
        cash_dividend = current_shares * div['cash_dividend']
        total_cash_dividend += cash_dividend
        
        stock_bonus = int(current_shares * div['stock_dividend'])
        stock_transfer = int(current_shares * div['stock_transfer'])
        current_shares += stock_bonus + stock_transfer
        
        cash_balance += cash_dividend
        shares_from_reinvest = 0
        cash_used_this_year = 0
        
        if price_df is not None and cash_balance > 0:
            year_prices = price_df[price_df['日期'].dt.year == year]
            if not year_prices.empty:
                avg_price = float(year_prices['收盘'].mean())
                if avg_price > 0:
                    shares_can_buy = int(cash_balance / avg_price / 100) * 100
                    if shares_can_buy >= 100:
                        cash_needed = shares_can_buy * avg_price
                        shares_from_reinvest = shares_can_buy
                        cash_used_this_year = cash_needed
                        cash_balance -= cash_needed
                        current_shares += shares_from_reinvest
                        total_cash_used_for_reinvest += cash_used_this_year
        
        yearly_data.append({
            'year': year,
            'cash_per_share': div['cash_dividend'],
            'stock_bonus_per_share': div['stock_dividend'],
            'stock_transfer_per_share': div['stock_transfer'],
            'yearly_cash_dividend': round(cash_dividend, 2),
            'total_cash_dividend': round(total_cash_dividend, 2),
            'shares_before_dividend': int(current_shares - stock_bonus - stock_transfer - shares_from_reinvest),
            'new_shares_from_bonus': stock_bonus,
            'new_shares_from_transfer': stock_transfer,
            'new_shares_from_reinvest': shares_from_reinvest,
            'cash_used_for_reinvest': round(cash_used_this_year, 2),
            'cash_balance': round(cash_balance, 2),
            'shares_after': int(current_shares),
            'payback_ratio': round(total_cash_dividend / total_cost * 100, 2)
        })
        
        if years_to_payback is None and total_cash_dividend >= total_cost:
            years_to_payback = year - dividends[0]['year'] + 1
    
    return {
        "years_to_payback": years_to_payback,
        "total_dividend": round(total_cash_dividend, 2),
        "total_reinvested": round(total_cash_used_for_reinvest, 2),
        "remaining_cash": round(cash_balance, 2),
        "final_shares": int(current_shares),
        "payback_ratio": round(total_cash_dividend / total_cost * 100, 2),
        "yearly_data": yearly_data
    }

@app.route('/api/search_stock', methods=['GET'])
def search_stock():
    keyword = request.args.get('keyword', '')
    try:
        df = get_stock_list()
        if df.empty:
            return jsonify({"success": False, "error": "股票列表未加载，请稍后重试"})
        if keyword:
            df = df[df['代码'].str.contains(keyword, case=False, na=False) | 
                    df['名称'].str.contains(keyword, case=False, na=False)]
        stocks = df[['代码', '名称']].head(20).to_dict('records')
        return jsonify({"success": True, "data": stocks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/calculate', methods=['POST'])
def calculate():
    data = request.json
    stock_code = data.get('stock_code')
    buy_year = data.get('buy_year')
    buy_price = data.get('buy_price')
    buy_shares = data.get('buy_shares', 1000)
    
    if not stock_code or not buy_year:
        return jsonify({"success": False, "error": "请提供股票代码和买入年份"})
    
    try:
        buy_year = int(buy_year)
        buy_shares = int(buy_shares)
        if buy_shares <= 0:
            return jsonify({"success": False, "error": "买入股数必须大于0"})
        if buy_price:
            buy_price = float(buy_price)
    except ValueError:
        return jsonify({"success": False, "error": "参数格式错误"})
    
    result = calculate_dividend_payback(stock_code, buy_year, buy_price, buy_shares)
    
    if "error" in result:
        return jsonify({"success": False, "error": result["error"]})
    
    return jsonify({"success": True, "data": result})

@app.route('/api/stock_info/<stock_code>', methods=['GET'])
def get_stock_info(stock_code):
    try:
        df = get_stock_list()
        if df.empty:
            return jsonify({"success": False, "error": "股票列表未加载"})
        stock = df[df['代码'] == stock_code]
        if stock.empty:
            return jsonify({"success": False, "error": "股票不存在"})
        
        info = stock.iloc[0]
        return jsonify({
            "success": True,
            "data": {
                "code": info['代码'],
                "name": info['名称'],
                "price": float(info['最新价']) if pd.notna(info['最新价']) else 0,
                "change_percent": float(info['涨跌幅']) if pd.notna(info['涨跌幅']) else 0
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
