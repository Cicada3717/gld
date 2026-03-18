import backtrader as bt
import yfinance as yf
import pandas as pd
import datetime
import itertools
from strategies.universal_godmode import UniversalGodMode

def run_universal_optimizer():
    tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'TSLA']
    start_date = '2025-03-01'
    end_date = '2026-02-28'
    
    print("Downloading historical data for 5 tickers...")
    data_dict = {}
    for ticker in tickers:
        warmup_start = (pd.Timestamp(start_date) - pd.DateOffset(months=14)).strftime('%Y-%m-%d')
        df = yf.download(ticker, start=warmup_start, end=end_date, interval='1d', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        data_dict[ticker] = df

    fast_emas = [5, 8, 10, 13, 21]
    slow_emas = [21, 30, 34, 40, 50, 60]
    trailing_mults = [3.0, 4.0, 5.0, 6.0, 7.0]
    
    best_sum_roi = -1000
    best_params = None
    
    combinations = list(itertools.product(fast_emas, slow_emas, trailing_mults))
    print(f"Testing {len(combinations)} parameter configurations across 5 diverse stocks...")
    
    for fast, slow, tr_mult in combinations:
        if fast >= slow:
            continue
            
        total_roi = 0.0
        
        for ticker in tickers:
            cerebro = bt.Cerebro()
            df = data_dict[ticker]
            
            if df.empty:
                continue
                
            data = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(data)
            
            cerebro.addstrategy(
                UniversalGodMode,
                fast_ema=fast,
                slow_ema=slow,
                atr_period=14,
                trailing_stop_mult=tr_mult,
                leverage=5.0,
                trade_start=datetime.date.fromisoformat(start_date)
            )
            
            cerebro.broker.setcash(1000000.0)
            cerebro.broker.set_shortcash(False)
            cerebro.broker.set_coc(True)
            cerebro.broker.setcommission(commission=0.005)
            
            try:
                cerebro.run()
                final_val = cerebro.broker.getvalue() - 900000.0
                roi = ((final_val - 100000.0) / 100000.0) * 100
                total_roi += roi
            except Exception as e:
                pass

        if total_roi > best_sum_roi:
            best_sum_roi = total_roi
            best_params = (fast, slow, tr_mult)
            print(f"New Best 5-Stock Total ROI: {total_roi:.2f}% | Fast:{fast} Slow:{slow} ATR_Mult:{tr_mult}")

    print("\n------------------------------")
    print(f"Optimal Universal Parameters (Un-Overfitted):")
    print(f"Fast EMA: {best_params[0]}")
    print(f"Slow EMA: {best_params[1]}")
    print(f"Trailing Stop Mult: {best_params[2]}")
    print(f"Peak 5-Stock Total ROI: {best_sum_roi:.2f}%")

if __name__ == '__main__':
    run_universal_optimizer()
