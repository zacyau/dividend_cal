from flask import Flask, jsonify, request
from flask_cors import CORS
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
CORS(app)

stock_list_cache = None
stock_list_last_update = 0
STOCK_LIST_CACHE_TTL = 300
bs_logged_in = False

def bs_login():
    global bs_logged_in
    if not bs_logged_in:
        lg = bs.login()
        if lg.error_code == '0':
            bs_logged_in = True
            print("Baostock login success")
        else:
            print(f"Baostock login failed: {lg.error_msg}")
    return bs_logged_in

def bs_logout():
    global bs_logged_in
    if bs_logged_in:
        bs.logout()
        bs_logged_in = False

def get_stock_list():
    global stock_list_cache, stock_list_last_update
    current_time = time.time()
    
    if stock_list_cache is None or (current_time - stock_list_last_update) > STOCK_LIST_CACHE_TTL:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Fetching stock list from baostock... (attempt {attempt + 1}/{max_retries})")
                
                if not bs_login():
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    continue
                
                # 尝试多个日期，因为当天可能没有数据
                dates_to_try = []
                for i in range(7):
                    dates_to_try.append((datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"))
                
                for date in dates_to_try:
                    rs = bs.query_all_stock(day=date)
                    if rs.error_code == '0':
                        data_list = []
                        while (rs.error_code == '0') & rs.next():
                            data_list.append(rs.get_row_data())
                        
                        if data_list:
                            df = pd.DataFrame(data_list, columns=rs.fields)
                            df = df[df['code'].str.startswith(('sh.6', 'sz.0', 'sz.3'))]
                            df['代码'] = df['code'].str.replace('sh.', '').str.replace('sz.', '')
                            df['名称'] = df['code_name']
                            
                            stock_list_cache = df
                            stock_list_last_update = current_time
                            print(f"Stock list cached from {date}, {len(df)} stocks")
                            return stock_list_cache
                
                print(f"No stock data available for recent dates")
                if attempt < max_retries - 1:
                    time.sleep(2)
            except Exception as e:
                print(f"Error fetching stock list (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
    
    return stock_list_cache if stock_list_cache is not None else pd.DataFrame()

def refresh_stock_list_periodically():
    while True:
        time.sleep(STOCK_LIST_CACHE_TTL)
        get_stock_list()

cache_thread = threading.Thread(target=refresh_stock_list_periodically, daemon=True)
cache_thread.start()

bs_login()
get_stock_list()

def convert_stock_code(code):
    if code.startswith('6'):
        return f"sh.{code}"
    else:
        return f"sz.{code}"

def get_stock_dividend_history(stock_code, start_year=None):
    try:
        bs_code = convert_stock_code(stock_code)
        
        if not bs_login():
            return None
        
        current_year = datetime.now().year
        all_dividends = []
        
        for year in range(start_year or 1990, current_year + 1):
            rs = bs.query_dividend_data(code=bs_code, year=str(year), yearType="report")
            if rs.error_code == '0':
                data_list = []
                while (rs.error_code == '0') & rs.next():
                    data_list.append(rs.get_row_data())
                if data_list:
                    df = pd.DataFrame(data_list, columns=rs.fields)
                    all_dividends.append(df)
        
        if not all_dividends:
            return pd.DataFrame()
        
        result_df = pd.concat(all_dividends, ignore_index=True)
        return result_df
    except Exception as e:
        print(f"Error fetching dividend data: {e}")
        return None

def get_stock_price_history(stock_code, start_year):
    try:
        bs_code = convert_stock_code(stock_code)
        
        if not bs_login():
            return None
        
        start_date = f"{start_year}-01-01"
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        rs = bs.query_history_k_data_plus(
            code=bs_code,
            fields="date,code,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3"
        )
        
        if rs.error_code != '0':
            print(f"Error fetching price data: {rs.error_msg}")
            return None
        
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
        
        if not data_list:
            return None
        
        df = pd.DataFrame(data_list, columns=rs.fields)
        df['date'] = pd.to_datetime(df['date'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        
        return df
    except Exception as e:
        print(f"Error fetching price data: {e}")
        return None

def calculate_dividend_payback(stock_code, buy_year, buy_price=None, buy_shares=1000):
    dividend_df = get_stock_dividend_history(stock_code, buy_year)
    if dividend_df is None or dividend_df.empty:
        return {"error": "无法获取分红数据"}
    
    price_df = None
    if buy_price is None:
        price_df = get_stock_price_history(stock_code, buy_year)
        if price_df is None or price_df.empty:
            return {"error": "无法获取股价数据"}
        
        year_start = pd.Timestamp(f"{buy_year}-01-01")
        year_end = pd.Timestamp(f"{buy_year}-12-31")
        year_data = price_df[(price_df['date'] >= year_start) & (price_df['date'] <= year_end)]
        
        if year_data.empty:
            year_data = price_df[price_df['date'].dt.year == buy_year]
        
        if not year_data.empty:
            buy_price = float(year_data.iloc[0]['close'])
        else:
            buy_price = float(price_df.iloc[0]['close'])
    else:
        price_df = get_stock_price_history(stock_code, buy_year)
    
    dividends = []
    for _, row in dividend_df.iterrows():
        try:
            oper_date = str(row.get('dividOperateDate', ''))
            if oper_date and len(oper_date) >= 4:
                divid_year = int(oper_date[:4])
            else:
                plan_date = str(row.get('dividPlanDate', ''))
                if plan_date and len(plan_date) >= 4:
                    divid_year = int(plan_date[:4])
                else:
                    continue
            
            if divid_year >= buy_year:
                cash_ps = row.get('dividCashPsBeforeTax', 0)
                cash_div = float(cash_ps) if pd.notna(cash_ps) and cash_ps != '' else 0
                
                stock_ps = row.get('dividStocksPs', 0)
                stock_div = float(stock_ps) if pd.notna(stock_ps) and stock_ps != '' else 0
                
                reserve_ps = row.get('dividReserveToStockPs', '')
                stock_transfer = float(reserve_ps) if pd.notna(reserve_ps) and reserve_ps != '' else 0
                
                cash_dividend = cash_div if cash_div > 0 else 0
                stock_dividend = stock_div if stock_div > 0 else 0
                stock_transfer = stock_transfer if stock_transfer > 0 else 0
                
                if cash_dividend > 0 or stock_dividend > 0 or stock_transfer > 0:
                    dividends.append({
                        'year': divid_year,
                        'cash_dividend': cash_dividend,
                        'stock_dividend': stock_dividend,
                        'stock_transfer': stock_transfer,
                        'date': oper_date
                    })
        except Exception as e:
            print(f"Error processing dividend row: {e}")
            continue
    
    dividends.sort(key=lambda x: x['year'])
    
    merged_dividends = {}
    for div in dividends:
        year = div['year']
        if year not in merged_dividends:
            merged_dividends[year] = {
                'year': year,
                'cash_dividend': 0,
                'stock_dividend': 0,
                'stock_transfer': 0,
                'date': div['date']
            }
        merged_dividends[year]['cash_dividend'] += div['cash_dividend']
        merged_dividends[year]['stock_dividend'] += div['stock_dividend']
        merged_dividends[year]['stock_transfer'] += div['stock_transfer']
    
    dividends = list(merged_dividends.values())
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
        
        yearly_data.append({
            'year': div['year'],
            'cash_per_share': div['cash_dividend'],
            'stock_bonus_per_share': div['stock_dividend'],
            'stock_transfer_per_share': div['stock_transfer'],
            'yearly_cash_dividend': round(cash_dividend, 2),
            'total_cash_dividend': round(total_cash_dividend, 2),
            'shares_before': int(current_shares),
            'new_shares_from_bonus': stock_bonus,
            'new_shares_from_transfer': stock_transfer,
            'shares_after': int(current_shares + stock_bonus + stock_transfer),
            'payback_ratio': round(total_cash_dividend / total_cost * 100, 2)
        })
        
        current_shares += stock_bonus + stock_transfer
        
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
            year_prices = price_df[price_df['date'].dt.year == year]
            if not year_prices.empty:
                avg_price = float(year_prices['close'].mean())
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
                "name": info['名称']
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
