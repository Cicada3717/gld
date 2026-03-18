import backtrader as bt
import yfinance as yf
import pandas as pd
import datetime
import itertools
import calendar
from strategies.gld_godmode import GLDGodMode

def get_last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]

def run_monthly_optimization():
    print("Downloading 18 months of GLD data...")
    # Get enough data to cover warmup for March 2025
    df = yf.download('GLD', start='2024-01-01', end='2026-03-01', interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    months_to_run = []
    start_date = datetime.date(2025, 3, 1)
    for i in range(12):
        month = (start_date.month + i - 1) % 12 + 1
        year = start_date.year + (start_date.month + i - 1) // 12
        last_day = get_last_day_of_month(year, month)
        start_str = f"{year}-{month:02d}-01"
        end_str = f"{year}-{month:02d}-{last_day:02d}"
        months_to_run.append((start_str, end_str))

    # We will test different parameter combinations
    fast_emas = [3, 5, 8]
    slow_emas = [20, 30, 40]
    trailing_mults = [3.0, 4.0, 5.0, 6.0]
    
    best_roi = -1000
    best_params = None
    
    combinations = list(itertools.product(fast_emas, slow_emas, trailing_mults))
    print(f"Testing {len(combinations)} combinations across 12 months...")
    
    for fast, slow, tr_mult in combinations:
        if fast >= slow:
            continue
            
        aggregate_roi = 0.0
        
        for start_str, end_str in months_to_run:
            cerebro = bt.Cerebro()
            
            # Slice data for this month plus warmup
            month_start = pd.Timestamp(start_str)
            warmup_start = (month_start - pd.DateOffset(months=14)).strftime('%Y-%m-%d')
            
            # Filter the already-downloaded dataframe to speed up!
            mask = (df.index >= warmup_start) & (df.index <= end_str)
            month_df = df.loc[mask]
            
            if month_df.empty:
                continue
                
            data = bt.feeds.PandasData(dataname=month_df)
            cerebro.adddata(data)
            
            cerebro.addstrategy(
                GLDGodMode,
                fast_ema=fast,
                slow_ema=slow,
                atr_period=14,
                trailing_stop_mult=tr_mult,
                leverage=5.0,
                trade_start=datetime.date.fromisoformat(start_str)
            )
            
            cerebro.broker.setcash(1000000.0)
            cerebro.broker.set_shortcash(False)
            cerebro.broker.set_coc(True)
            cerebro.broker.setcommission(commission=0.005)
            
            try:
                cerebro.run()
                final_val = cerebro.broker.getvalue() - 900000.0
                roi = ((final_val - 100000.0) / 100000.0) * 100
                aggregate_roi += roi
            except Exception as e:
                pass

        if aggregate_roi > best_roi:
            best_roi = aggregate_roi
            best_params = (fast, slow, tr_mult)
            print(f"New Best Aggregate ROI (sum): {aggregate_roi:.2f}% | Fast:{fast} Slow:{slow} Mult:{tr_mult}")

    print("\n------------------------------")
    print(f"Optimal 12-Month Parameters:")
    print(f"Fast EMA: {best_params[0]}")
    print(f"Slow EMA: {best_params[1]}")
    print(f"Trailing Stop Mult: {best_params[2]}")
    print(f"Peak Aggregate ROI (Sum): {best_roi:.2f}%")

if __name__ == '__main__':
    run_monthly_optimization()
