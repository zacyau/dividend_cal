from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
import threading
import time

app = FastAPI()

# 跨域配置，允许前端本地开发访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 股票列表缓存及过期时间（30分钟）
stock_list_cache = None
stock_list_last_update = 0
STOCK_LIST_CACHE_TTL = 1800
# baostock 登录状态标志
bs_logged_in = False
# 线程锁，保证 baostock 操作的线程安全
bs_lock = threading.RLock()


def bs_login():
    """登录 baostock，如果已登录则跳过"""
    global bs_logged_in
    with bs_lock:
        if not bs_logged_in:
            bs.logout()  # 先清理可能残留的旧会话
            lg = bs.login()
            if lg.error_code == '0':
                bs_logged_in = True
                print("Baostock login success")
            else:
                print(f"Baostock login failed: {lg.error_msg}")
        return bs_logged_in


def bs_relogin():
    """强制重新登录 baostock（会话过期时使用）"""
    global bs_logged_in
    with bs_lock:
        bs.logout()
        bs_logged_in = False
        lg = bs.login()
        if lg.error_code == '0':
            bs_logged_in = True
            print("Baostock re-login success")
        else:
            print(f"Baostock re-login failed: {lg.error_msg}")
        return bs_logged_in


def bs_logout():
    """登出 baostock"""
    global bs_logged_in
    with bs_lock:
        if bs_logged_in:
            bs.logout()
            bs_logged_in = False


def get_stock_list():
    """获取沪深A股列表，带缓存和重试机制"""
    global stock_list_cache, stock_list_last_update, bs_logged_in
    current_time = time.time()

    with bs_lock:
        # 缓存过期或不存在时重新获取
        if stock_list_cache is None or (current_time - stock_list_last_update) > STOCK_LIST_CACHE_TTL:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"Fetching stock list from baostock... (attempt {attempt + 1}/{max_retries})")

                    if not bs_logged_in:
                        bs.logout()
                        lg = bs.login()
                        if lg.error_code == '0':
                            bs_logged_in = True
                            print("Baostock login success")
                        else:
                            print(f"Baostock login failed: {lg.error_msg}")
                    if not bs_logged_in:
                        if attempt < max_retries - 1:
                            time.sleep(2)
                        continue

                    # 尝试最近7天的日期，找到有数据的交易日
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
                                # 只保留沪深A股：沪市6开头、深市0和3开头
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
    """后台线程：定期刷新股票列表缓存"""
    while True:
        time.sleep(STOCK_LIST_CACHE_TTL)
        get_stock_list()


# 启动后台缓存刷新线程
cache_thread = threading.Thread(target=refresh_stock_list_periodically, daemon=True)
cache_thread.start()

# 应用启动时初始化登录并加载股票列表
with bs_lock:
    bs_login()
get_stock_list()


def convert_stock_code(code):
    """将简写股票代码转换为 baostock 格式：6开头为沪市sh，其余为深市sz"""
    if code.startswith('6'):
        return f"sh.{code}"
    else:
        return f"sz.{code}"


def get_stock_dividend_history(stock_code, start_year=None):
    """获取股票分红历史数据，从 start_year 到当前年份"""
    global bs_logged_in
    max_retries = 2
    for attempt in range(max_retries):
        with bs_lock:
            try:
                bs_code = convert_stock_code(stock_code)

                if not bs_logged_in:
                    bs.logout()
                    lg = bs.login()
                    if lg.error_code == '0':
                        bs_logged_in = True
                    else:
                        print(f"Baostock login failed: {lg.error_msg}")
                if not bs_logged_in:
                    if attempt < max_retries - 1:
                        print(f"Dividend: login failed, re-login retry ({attempt + 1}/{max_retries})")
                        continue
                    return None

                current_year = datetime.now().year
                all_dividends = []
                query_error = False

                # 逐年查询分红数据（baostock 按年查询）
                for year in range(start_year or 1990, current_year + 1):
                    rs = bs.query_dividend_data(code=bs_code, year=str(year), yearType="report")
                    if rs.error_code != '0':
                        query_error = True
                        print(f"Dividend query error on year {year}: {rs.error_msg}")
                        break
                    data_list = []
                    while (rs.error_code == '0') & rs.next():
                        data_list.append(rs.get_row_data())
                    if data_list:
                        df = pd.DataFrame(data_list, columns=rs.fields)
                        all_dividends.append(df)

                if query_error:
                    if attempt < max_retries - 1:
                        print(f"Dividend query failed, re-login and retry ({attempt + 1}/{max_retries})")
                        bs.logout()
                        bs_logged_in = False
                        continue
                    return None

                if not all_dividends:
                    return pd.DataFrame()

                result_df = pd.concat(all_dividends, ignore_index=True)
                return result_df
            except Exception as e:
                print(f"Error fetching dividend data (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    bs.logout()
                    bs_logged_in = False
                    continue
                return None
    return None


def get_stock_price_history(stock_code, start_year):
    """获取股票日线行情数据（不复权），用于再投入时的买入价计算"""
    global bs_logged_in
    max_retries = 2
    for attempt in range(max_retries):
        with bs_lock:
            try:
                bs_code = convert_stock_code(stock_code)

                if not bs_logged_in:
                    bs.logout()
                    lg = bs.login()
                    if lg.error_code == '0':
                        bs_logged_in = True
                    else:
                        print(f"Baostock login failed: {lg.error_msg}")
                if not bs_logged_in:
                    if attempt < max_retries - 1:
                        print(f"Price: login failed, re-login retry ({attempt + 1}/{max_retries})")
                        continue
                    return None

                start_date = f"{start_year}-01-01"
                end_date = datetime.now().strftime("%Y-%m-%d")

                # adjustflag="3" 表示不复权，获取原始交易价格
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
                    if attempt < max_retries - 1:
                        print(f"Re-login and retry ({attempt + 1}/{max_retries})")
                        bs.logout()
                        bs_logged_in = False
                        continue
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
                print(f"Error fetching price data (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    bs.logout()
                    bs_logged_in = False
                    continue
                return None
    return None


def calculate_dividend_payback(stock_code, buy_year, buy_price=None, buy_shares=1000):
    """
    分红回本计算主函数
    流程：获取分红数据 → 获取股价数据 → 解析买入价 → 解析分红记录 → 分别计算两种策略
    """
    # 获取分红历史
    dividend_df = get_stock_dividend_history(stock_code, buy_year)
    if dividend_df is None or dividend_df.empty:
        return {"error": "无法获取分红数据"}

    # 获取股价历史（用于自动获取买入价和再投入计算）
    price_df = get_stock_price_history(stock_code, buy_year)
    if price_df is None or price_df.empty:
        return {"error": "无法获取股价数据"}

    if buy_price is not None and buy_price <= 0:
        return {"error": "买入价格必须大于0"}

    # 如果未手动输入买入价，取买入年份第一个交易日的收盘价
    if buy_price is None:
        year_data = price_df[price_df['date'].dt.year == buy_year]
        if not year_data.empty:
            year_data = year_data.sort_values('date')
            buy_price = float(year_data.iloc[0]['close'])
        else:
            # 买入年份无数据时，取整个数据集的最早价格
            buy_price = float(price_df.iloc[0]['close'])

    if buy_price <= 0:
        return {"error": "获取的股价无效（≤0），请手动输入买入价格"}

    # 解析每条分红记录，提取年份、每股现金分红、每股送股、每股转增
    dividends = []
    for _, row in dividend_df.iterrows():
        try:
            # 优先从除权除息日提取年份，回退到预案公告日
            oper_date = str(row.get('dividOperateDate', ''))
            if oper_date and len(oper_date) >= 4:
                divid_year = int(oper_date[:4])
            else:
                plan_date = str(row.get('dividPlanDate', ''))
                if plan_date and len(plan_date) >= 4:
                    divid_year = int(plan_date[:4])
                else:
                    continue

            # 只保留买入年份及之后的分红
            if divid_year >= buy_year:
                # 每股税前现金分红
                cash_ps = row.get('dividCashPsBeforeTax', 0)
                cash_div = float(cash_ps) if pd.notna(cash_ps) and cash_ps != '' else 0

                # 每股送股（红股）
                stock_ps = row.get('dividStocksPs', 0)
                stock_div = float(stock_ps) if pd.notna(stock_ps) and stock_ps != '' else 0

                # 每股资本公积转增股本
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

    # 同一年多次分红时合并（求和每股分红、送股、转增）
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

    # 总成本 = 买入价 × 买入股数
    total_cost = buy_price * buy_shares
    # 分别计算"不再投入"和"再投入"两种策略
    result_without_reinvest = calculate_without_reinvest(dividends, buy_price, buy_shares, total_cost, buy_year)
    result_with_reinvest = calculate_with_reinvest(dividends, buy_price, buy_shares, total_cost, price_df, buy_year)

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


def calculate_without_reinvest(dividends, buy_price, buy_shares, total_cost, buy_year):
    """
    计算策略一：现金分红不再投入
    - 每年收到的现金分红累计，不用于买入更多股票
    - 送股和转增会增加持股数量，但不计入回本金额
    - 回本判定：累计现金分红 >= 买入总成本
    """
    total_cash_dividend = 0
    current_shares = float(buy_shares)
    years_to_payback = None
    yearly_data = []

    for div in dividends:
        # 当年现金分红 = 每股现金分红 × 当前持股数
        cash_dividend = div['cash_dividend'] * current_shares

        # 送股：取整后为实际获得股数，小数部分为零股
        total_bonus_shares = current_shares * div['stock_dividend']
        stock_bonus = int(total_bonus_shares)
        fractional_bonus = total_bonus_shares - stock_bonus

        # 转增：同上处理
        total_transfer_shares = current_shares * div['stock_transfer']
        stock_transfer = int(total_transfer_shares)
        fractional_transfer = total_transfer_shares - stock_transfer

        # 零股按面值1元/股折算为现金补偿（A股惯例）
        fractional_cash = (fractional_bonus + fractional_transfer) * 1.0
        cash_dividend += fractional_cash
        total_cash_dividend += cash_dividend

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

        # 更新持股数（送股+转增）
        current_shares += stock_bonus + stock_transfer

        # 回本判定：从买入年份开始计算的年数
        if years_to_payback is None and total_cash_dividend >= total_cost:
            years_to_payback = div['year'] - buy_year

    return {
        "years_to_payback": years_to_payback,
        "total_dividend": round(total_cash_dividend, 2),
        "final_shares": int(current_shares),
        "payback_ratio": round(total_cash_dividend / total_cost * 100, 2),
        "yearly_data": yearly_data
    }


def calculate_with_reinvest(dividends, buy_price, buy_shares, total_cost, price_df, buy_year):
    """
    计算策略二：现金分红再投入
    - 每年收到的现金分红累积后，以当期股价买入更多股票（必须为100的整数倍）
    - 买入价格优先使用除权除息日当天的收盘价，无法获取时回退到该年均价
    - 回本判定：累计现金分红 >= 买入总成本（注意：已用于再投入的现金仍计入回本）
    """
    current_shares = float(buy_shares)
    total_cash_dividend = 0
    total_cash_used_for_reinvest = 0
    years_to_payback = None
    yearly_data = []
    cash_balance = 0.0

    for div in dividends:
        year = div['year']
        # 当年现金分红 = 每股现金分红 × 当前持股数
        cash_dividend = current_shares * div['cash_dividend']

        # 送股：取整后为实际获得股数，小数部分为零股
        total_bonus_shares = current_shares * div['stock_dividend']
        stock_bonus = int(total_bonus_shares)
        fractional_bonus = total_bonus_shares - stock_bonus

        # 转增：同上处理
        total_transfer_shares = current_shares * div['stock_transfer']
        stock_transfer = int(total_transfer_shares)
        fractional_transfer = total_transfer_shares - stock_transfer

        # 零股按面值1元/股折算为现金补偿（A股惯例）
        fractional_cash = (fractional_bonus + fractional_transfer) * 1.0
        cash_dividend += fractional_cash
        total_cash_dividend += cash_dividend

        # 先处理送股和转增，更新持股数
        current_shares += stock_bonus + stock_transfer

        # 现金分红计入余额，用于再投入
        cash_balance += cash_dividend
        shares_from_reinvest = 0
        cash_used_this_year = 0

        # 再投入逻辑：用累计现金余额买入股票
        if price_df is not None and cash_balance > 0:
            reinvest_price = None
            # 优先使用除权除息日当天的收盘价
            divid_date = div.get('date', '')
            if divid_date and len(divid_date) >= 10:
                try:
                    ex_date = pd.to_datetime(divid_date[:10])
                    # 找除权日或之后的最近交易日
                    after_ex = price_df[price_df['date'] >= ex_date]
                    if not after_ex.empty:
                        reinvest_price = float(after_ex.iloc[0]['close'])
                except Exception:
                    pass
            # 回退：使用该年均价
            if reinvest_price is None:
                year_prices = price_df[price_df['date'].dt.year == year]
                if not year_prices.empty:
                    reinvest_price = float(year_prices['close'].mean())

            # A股买入必须为100股的整数倍（1手=100股）
            if reinvest_price and reinvest_price > 0:
                shares_can_buy = int(cash_balance / reinvest_price / 100) * 100
                if shares_can_buy >= 100:
                    cash_needed = shares_can_buy * reinvest_price
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

        # 回本判定：从买入年份开始计算的年数
        if years_to_payback is None and total_cash_dividend >= total_cost:
            years_to_payback = year - buy_year

    return {
        "years_to_payback": years_to_payback,
        "total_dividend": round(total_cash_dividend, 2),
        "total_reinvested": round(total_cash_used_for_reinvest, 2),
        "remaining_cash": round(cash_balance, 2),
        "final_shares": int(current_shares),
        "payback_ratio": round(total_cash_dividend / total_cost * 100, 2),
        "yearly_data": yearly_data
    }


class CalculateRequest(BaseModel):
    """计算请求参数模型"""
    stock_code: str        # 股票代码（简写，如 600519）
    buy_year: int          # 买入年份
    buy_price: Optional[float] = None  # 买入价格（可选，留空取首日收盘价）
    buy_shares: int = 1000             # 买入股数，默认1000


@app.get('/api/search_stock')
def search_stock(keyword: str = Query(default='')):
    """股票搜索接口：按代码或名称模糊搜索，返回最多20条"""
    try:
        df = get_stock_list()
        if df.empty:
            return {"success": False, "error": "股票列表未加载，请稍后重试"}
        if keyword:
            df = df[df['代码'].str.contains(keyword, case=False, na=False) |
                    df['名称'].str.contains(keyword, case=False, na=False)]
        stocks = df[['代码', '名称']].head(20).to_dict('records')
        return {"success": True, "data": stocks}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post('/api/calculate')
def calculate(req: CalculateRequest):
    """分红回本计算接口：接收参数后调用主计算函数"""
    if not req.stock_code or not req.buy_year:
        return {"success": False, "error": "请提供股票代码和买入年份"}

    if req.buy_shares <= 0:
        return {"success": False, "error": "买入股数必须大于0"}

    result = calculate_dividend_payback(req.stock_code, req.buy_year, req.buy_price, req.buy_shares)

    if "error" in result:
        return {"success": False, "error": result["error"]}

    return {"success": True, "data": result}


@app.get('/api/stock_info/{stock_code}')
def get_stock_info(stock_code: str):
    """股票信息查询接口：根据代码获取股票名称"""
    try:
        df = get_stock_list()
        if df.empty:
            return {"success": False, "error": "股票列表未加载"}
        stock = df[df['代码'] == stock_code]
        if stock.empty:
            return {"success": False, "error": "股票不存在"}

        info = stock.iloc[0]
        return {
            "success": True,
            "data": {
                "code": info['代码'],
                "name": info['名称']
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
