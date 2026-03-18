import subprocess

def run_multi_stock_test():
    tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'TSLA']
    strategies = ['ClaudeGoldAlpha', 'ClaudeGoldOmega', 'UniversalGodMode']
    
    start_date = '2025-03-01'
    end_date = '2026-02-28'
    
    print("==================================================")
    print(f"MULTI-STOCK 1-YEAR TEST ({start_date} to {end_date})")
    print("==================================================")
    
    for ticker in tickers:
        print(f"\n--- Testing Ticker: {ticker} ---")
        
        with open("5_stock_results.md", "a") as f:
            f.write(f"## {ticker}\n")
            f.write("| Strategy | ROI | Max Drawdown | Trades |\n")
            f.write("| :--- | :--- | :--- | :--- |\n")
            
        for strategy in strategies:
            cmd = [
                r"venv\Scripts\python", "backtest.py", 
                "--ticker", ticker, 
                "--start", start_date, 
                "--end", end_date, 
                "--strategy", strategy
            ]
            
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                
                final_val = 100000.0
                max_dd = 0.0
                trades = 0
                
                for line in output.split("\n"):
                    if "Final Portfolio Value:" in line:
                        final_val = float(line.split(":")[1].strip())
                    elif "Max Drawdown:" in line:
                        max_dd = float(line.split(":")[1].strip().replace('%', ''))
                    elif "Total Trades:" in line:
                        trades = int(line.split(":")[1].strip())
                
                roi = ((final_val - 100000.0) / 100000.0) * 100
                res_str = f"| {strategy} | {roi:.2f}% | {max_dd:.2f}% | {trades} |\n"
                print(f"{strategy:<15} | ROI: {roi:>7.2f}% | Max DD: {max_dd:>5.2f}% | Trades: {trades}")
                
                with open("5_stock_results.md", "a") as f:
                    f.write(res_str)
                
            except subprocess.CalledProcessError as e:
                print(f"Error running {strategy} on {ticker}:")
                # print(e.output)
                print("Failed to execute.")

if __name__ == '__main__':
    # Initialize the markdown file
    with open("5_stock_results.md", "w") as f:
        f.write("# 5-Stock Generalization Test (2025-03-01 to 2026-02-28)\n\n")
        f.write("Testing the GodMode and Claude strategies on 5 diverse tickers (5.0x Leverage)\n\n")
    
    run_multi_stock_test()
