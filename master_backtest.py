import argparse
import datetime
import matplotlib
matplotlib.use('Agg')
import backtrader as bt
import yfinance as yf
import pandas as pd
from strategies.master_strategy import MasterProtocol

UNIVERSE = ['SPY', 'QQQ', 'XLE', 'XLK', 'XLV', 'XLU', 'GLD', 'IEF']
COMPETITION_START = '2026-01-14'
COMPETITION_END   = '2026-03-14'
# Need 126 days for Momentum + 14 for ATR. We grab 8 months to be safe.
WARMUP_MONTHS     = 8  
STARTING_CASH     = 100000.0

def run_master_backtest():
    print(f"Starting Master Protocol backtest from {COMPETITION_START} to {COMPETITION_END}")
    
    warmup_start = (pd.Timestamp(COMPETITION_START) - pd.DateOffset(months=WARMUP_MONTHS)).strftime('%Y-%m-%d')

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(STARTING_CASH)
    cerebro.broker.setcommission(commission=0.001)

    for ticker in UNIVERSE:
        print(f"Downloading {ticker}...")
        df = yf.download(ticker, start=warmup_start, end=COMPETITION_END, interval='1d', progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        if not df.empty:
            data = bt.feeds.PandasData(dataname=df, name=ticker)
            cerebro.adddata(data, name=ticker)

    cerebro.addstrategy(
        MasterProtocol,
        trade_start=datetime.date(2026, 1, 14)
    )

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')

    results = cerebro.run()

    print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
    
    # Extract analyzers
    strat = results[0]
    sharpe = strat.analyzers.sharpe.get_analysis()
    print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
    
    drawdown = strat.analyzers.drawdown.get_analysis()
    print(f"Max Drawdown: {drawdown.max.drawdown:.2f}%")
    
    trades = strat.analyzers.trades.get_analysis()
    
    # Use robust dict getting to avoid KeyErrors
    total_trades = trades.get('total', {}).get('closed', 0) if isinstance(trades, dict) else 0
    print(f"Total Trades: {total_trades}")
    
    print("Plotting results...")
    try:
        fig = cerebro.plot(style='candlestick')[0][0]
        fig.savefig(f'MasterProtocol_backtest.png', dpi=300)
    except Exception as e:
        print(f"Could not generate plot: {e}")

if __name__ == '__main__':
    run_master_backtest()
