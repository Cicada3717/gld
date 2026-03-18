import argparse
import datetime
import matplotlib
matplotlib.use('Agg')
import backtrader as bt
import yfinance as yf
import pandas as pd
from strategies.pairs_strategy import PairsTradingStrategy

def run_pairs_backtest(ticker1, ticker2, start_date, end_date, cash):
    print(f"Starting pairs backtest for {ticker1} and {ticker2} from {start_date} to {end_date}")
    
    # Initialize Cerebro engine
    cerebro = bt.Cerebro()

    # Set initial cash
    cerebro.broker.setcash(cash)

    # Download data from yfinance for both tickers
    print(f"Downloading data for {ticker1}...")
    df1 = yf.download(ticker1, start=start_date, end=end_date, interval='1d', progress=False)
    
    if isinstance(df1.columns, pd.MultiIndex):
        df1.columns = df1.columns.droplevel(1)
        
    print(f"Downloading data for {ticker2}...")
    df2 = yf.download(ticker2, start=start_date, end=end_date, interval='1d', progress=False)

    if isinstance(df2.columns, pd.MultiIndex):
        df2.columns = df2.columns.droplevel(1)
        
    if df1.empty or df2.empty:
        print("Missing data for one or both tickers.")
        return

    # Add the data feeds
    data1 = bt.feeds.PandasData(dataname=df1, name=ticker1)
    data2 = bt.feeds.PandasData(dataname=df2, name=ticker2)
    
    cerebro.adddata(data1)
    cerebro.adddata(data2)

    # Add the strategy
    cerebro.addstrategy(PairsTradingStrategy)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Allow fractional shares for exact sizing if needed
    # but normally IB doesn't support shorting fractionals optimally.
    # We will let backtrader trade fractions for now to enforce our simplified 50/50 sizing logic.
    cerebro.broker.set_coc(True)
    
    # Very important: we need to allow short selling (negative balances or borrowing)
    # Cerebro handles this mostly automatically, but we need to ensure we don't hit cash limits.
    cerebro.broker.set_shortcash(False)

    # Print starting conditions
    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')

    # Run backtest
    results = cerebro.run()

    # Print final conditions
    print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
    
    # Extract and print analyzers
    strat = results[0]
    
    sharpe = strat.analyzers.sharpe.get_analysis()
    print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
    
    drawdown = strat.analyzers.drawdown.get_analysis()
    print(f"Max Drawdown: {drawdown.max.drawdown:.2f}%")
    
    trades = strat.analyzers.trades.get_analysis()
    total_trades = trades.total.closed if hasattr(trades, 'total') else 0
    print(f"Total Trades: {total_trades}")
    
    # Plot results
    print("Plotting results...")
    # Plotting multiple data feeds can be visually noisy, but we'll try
    try:
        fig = cerebro.plot(style='candlestick')[0][0]
        fig.savefig(f'{ticker1}_{ticker2}_pairstrading_backtest.png', dpi=300)
        print(f"Plot saved to {ticker1}_{ticker2}_pairstrading_backtest.png")
    except Exception as e:
        print(f"Could not generate plot: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run Pairs Trading Backtrader Backtest')
    parser.add_argument('--t1', type=str, default='KO', help='Ticker 1')
    parser.add_argument('--t2', type=str, default='PEP', help='Ticker 2')
    parser.add_argument('--start', type=str, default='2026-01-14', help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, default='2026-03-14', help='End date YYYY-MM-DD')
    parser.add_argument('--cash', type=float, default=100000.0)

    args = parser.parse_args()
    
    run_pairs_backtest(args.t1, args.t2, args.start, args.end, args.cash)
