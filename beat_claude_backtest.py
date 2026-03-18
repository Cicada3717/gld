import argparse
import datetime
import matplotlib
matplotlib.use('Agg')
import backtrader as bt
import yfinance as yf
import pandas as pd
from strategies.aggressive_momentum import AggressiveMomentum

def run_multi_backtest(tickers, start_date, end_date, cash):
    print(f"Starting aggressive backtest from {start_date} to {end_date}")
    print(f"Universe: {tickers}")
    
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)

    for ticker in tickers:
        print(f"Downloading data for {ticker}...")
        df = yf.download(ticker, start=start_date, end=end_date, interval='1d', progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        if not df.empty:
            data = bt.feeds.PandasData(dataname=df, name=ticker)
            cerebro.adddata(data)

    cerebro.addstrategy(AggressiveMomentum)

    # Need to allow shortcash / margin for 2x to 3x leverage
    cerebro.broker.set_coc(True)
    cerebro.broker.set_shortcash(False)

    # Analyzers
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
    total_trades = trades.get('total', {}).get('closed', 0) if isinstance(trades, dict) else 0
    print(f"Total Trades: {total_trades}")

if __name__ == '__main__':
    # We will use high-beta stocks and crypto/tech proxies
    universe = ['NVDA', 'SMCI', 'MSTR', 'AMD', 'COIN', 'TQQQ', 'SOXL']
    
    run_multi_backtest(universe, '2026-01-14', '2026-03-14', 100000.0)
