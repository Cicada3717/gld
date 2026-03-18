import argparse
import datetime
import matplotlib
matplotlib.use('Agg')
import backtrader as bt
import yfinance as yf
import pandas as pd
from strategies.combo_strategy import TrendMACDRSIStrategy, MeanReversionBollingerRSI
from strategies.gld_strategy import GLDAggressive
from strategies.claude_gld_breakout import CLDonchianBreakout
from strategies.claude_gold_alpha import ClaudeGoldAlpha
from strategies.claude_gold_omega import ClaudeGoldOmega
from strategies.gld_godmode import GLDGodMode
from strategies.gld_quantum import GLDQuantum
from strategies.universal_godmode import UniversalGodMode

WARMUP_MONTHS = 14   # Enough history for SMA(200) to initialise before competition start

def run_backtest(ticker, start_date, end_date, strategy_name, cash, args_plot=False):
    print(f"Starting backtest for {ticker} from {start_date} to {end_date} using {strategy_name}")

    # Extend download window backwards for indicator warmup
    warmup_start = (
        pd.Timestamp(start_date) - pd.DateOffset(months=WARMUP_MONTHS)
    ).strftime('%Y-%m-%d')
    trade_start = datetime.date.fromisoformat(start_date)

    # Initialize Cerebro engine
    cerebro = bt.Cerebro()

    # Set initial cash
    if strategy_name in ('GLDGodMode', 'ClaudeGoldAlpha', 'ClaudeGoldOmega', 'GLDQuantum', 'UniversalGodMode'):
        cerebro.broker.setcash(cash * 10.0) # 1M padding to avoid margin rejections
    else:
        cerebro.broker.setcash(cash)
    
    # Enable margin trading (allow positions larger than cash balance for GodMode)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.set_coc(True)

    # Download data from yfinance (includes warmup period)
    print(f"Downloading data (warmup from {warmup_start})...")
    df = yf.download(ticker, start=warmup_start, end=end_date, interval='1d', progress=False)
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    
    if df.empty:
        print(f"No data found for {ticker} in the given date range.")
        return

    # Backtrader format requires specific column naming (Open, High, Low, Close, Volume)
    # yfinance already provides this but we'll feed it using pandas data feed
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Add the strategy
    if strategy_name == 'TrendMACDRSI':
        cerebro.addstrategy(TrendMACDRSIStrategy, trade_start=trade_start)
    elif strategy_name == 'MeanReversion':
        cerebro.addstrategy(MeanReversionBollingerRSI, trade_start=trade_start)
    elif strategy_name == 'GLDAggressive':
        cerebro.addstrategy(GLDAggressive)
    elif strategy_name == 'CLDonchianBreakout':
        cerebro.addstrategy(CLDonchianBreakout, trade_start=trade_start)
    elif strategy_name == 'ClaudeGoldAlpha':
        cerebro.addstrategy(ClaudeGoldAlpha, trade_start=trade_start,
                            leverage=5.0, real_cash=cash)
    elif strategy_name == 'ClaudeGoldOmega':
        cerebro.addstrategy(ClaudeGoldOmega, trade_start=trade_start,
                            leverage=5.0, real_cash=cash)
    elif strategy_name == 'GLDGodMode':
        cerebro.addstrategy(GLDGodMode, trade_start=trade_start)
    elif strategy_name == 'GLDQuantum':
        cerebro.addstrategy(GLDQuantum, trade_start=trade_start)
    elif strategy_name == 'UniversalGodMode':
        cerebro.addstrategy(UniversalGodMode, trade_start=trade_start)
    else:
        print(f"Unknown strategy: {strategy_name}")
        return

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Set commission (IBKR roughly $1 per trade)
    cerebro.broker.setcommission(commission=0.005) # Assume 0.5% for simulation or flat fee

    # Add sizers
    cerebro.addsizer(bt.sizers.PercentSizer, percents=90) # Invest 90% of portfolio on each signal

    # Print starting conditions
    print(f'Starting Portfolio Value: {cash:.2f}')

    # Run backtest
    results = cerebro.run()

    # Print final conditions
    final_value = cerebro.broker.getvalue()
    if strategy_name in ('GLDGodMode', 'ClaudeGoldAlpha', 'ClaudeGoldOmega', 'GLDQuantum', 'UniversalGodMode'):
        final_value -= (cash * 9.0)
    print(f'Final Portfolio Value: {final_value:.2f}')
    
    # Extract analyzers
    if results:
        strat = results[0]
        sharpe = strat.analyzers.sharpe.get_analysis()
        print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
        
        drawdown = strat.analyzers.drawdown.get_analysis()
        print(f"Max Drawdown: {drawdown.max.drawdown:.2f}%")
        
        trades = strat.analyzers.trades.get_analysis()
        total_trades = trades.get('total', {}).get('closed', 0) if isinstance(trades, dict) else 0
        print(f"Total Trades: {total_trades}")
    
    # Requires matplotlib
    if args_plot:
        print("Plotting results...")
        try:
            fig = cerebro.plot(style='candlestick', barup='green', bardown='red')[0][0]
            fig.savefig(f'{ticker}_{strategy_name}_backtest.png', dpi=300)
            print(f"Plot saved to {ticker}_{strategy_name}_backtest.png")
        except Exception as e:
            print(f"Plot error (non-fatal): {e}")
    else:
        print("Plot skipped (use --plot to enable).")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run Python Backtrader Backtest')
    parser.add_argument('--ticker', type=str, default='GLD', help='Ticker symbol to backtest')
    parser.add_argument('--start', type=str, default='2026-01-01', help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, default='2026-03-14', help='End date YYYY-MM-DD')
    parser.add_argument('--strategy', type=str, default='GLDGodMode', choices=['TrendMACDRSI', 'MeanReversion', 'GLDAggressive', 'CLDonchianBreakout', 'ClaudeGoldAlpha', 'ClaudeGoldOmega', 'GLDGodMode', 'GLDQuantum', 'UniversalGodMode'])
    parser.add_argument('--cash', type=float, default=100000.0)
    parser.add_argument('--plot', action='store_true', help='Save a chart PNG after backtest')

    args = parser.parse_args()

    run_backtest(args.ticker, args.start, args.end, args.strategy, args.cash, args_plot=args.plot)
