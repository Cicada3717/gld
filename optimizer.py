import backtrader as bt
import yfinance as yf
import pandas as pd
import datetime
import itertools
from strategies.gld_godmode import GLDGodMode

def run_optimization():
    print("Downloading data for optimization...")
    start_date = '2026-01-01'
    end_date = '2026-03-14'
    warmup_start = (pd.Timestamp(start_date) - pd.DateOffset(months=6)).strftime('%Y-%m-%d')
    
    df = yf.download('GLD', start=warmup_start, end=end_date, interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    fast_emas = [3, 4, 5, 8]
    slow_emas = [10, 15, 20, 25, 30]
    atr_periods = [5, 10, 14]
    trailing_mults = [2.0, 3.0, 4.0, 5.0, 6.0]
    
    best_roi = -100
    best_params = None
    
    combinations = list(itertools.product(fast_emas, slow_emas, atr_periods, trailing_mults))
    print(f"Testing {len(combinations)} combinations...")
    
    for fast, slow, atr, tr_mult in combinations:
        if fast >= slow:
            continue
            
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        
        cerebro.addstrategy(
            GLDGodMode,
            fast_ema=fast,
            slow_ema=slow,
            atr_period=atr,
            trailing_stop_mult=tr_mult,
            leverage=5.0,
            trade_start=datetime.date.fromisoformat('2026-01-01')
        )
        
        cerebro.broker.setcash(1000000.0) # $1M padding
        cerebro.broker.set_shortcash(False)
        cerebro.broker.set_coc(True)
        cerebro.broker.setcommission(commission=0.005)
        
        cerebro.addsizer(bt.sizers.PercentSizer, percents=90)
        
        try:
            cerebro.run()
            final_val = cerebro.broker.getvalue() - 900000.0
            roi = ((final_val - 100000.0) / 100000.0) * 100
            
            if roi > best_roi:
                best_roi = roi
                best_params = (fast, slow, atr, tr_mult)
                print(f"New Best: ROI {roi:.2f}% | Fast:{fast} Slow:{slow} ATR:{atr} Mult:{tr_mult}")
        except Exception as e:
            pass

    print("\n------------------------------")
    print(f"Optimal 5x Leverage Parameters:")
    print(f"Fast EMA: {best_params[0]}")
    print(f"Slow EMA: {best_params[1]}")
    print(f"ATR Period: {best_params[2]}")
    print(f"Trailing Stop Mult: {best_params[3]}")
    print(f"Peak ROI: {best_roi:.2f}%")

if __name__ == '__main__':
    run_optimization()
