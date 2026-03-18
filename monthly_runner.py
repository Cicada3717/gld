import subprocess
import calendar
import datetime
import pandas as pd

def get_last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]

def run_monthly_sprints():
    strategies = ['ClaudeGoldAlpha', 'GLDGodMode', 'GLDQuantum']
    months_to_run = []
    
    # Generate past 12 months (March 2025 to Feb 2026)
    start_date = datetime.date(2025, 3, 1)
    
    for i in range(12):
        month = (start_date.month + i - 1) % 12 + 1
        year = start_date.year + (start_date.month + i - 1) // 12
        last_day = get_last_day_of_month(year, month)
        
        start_str = f"{year}-{month:02d}-01"
        end_str = f"{year}-{month:02d}-{last_day:02d}"
        months_to_run.append((start_str, end_str, f"{year}-{month:02d}"))

    results = {s: [] for s in strategies}

    for start_str, end_str, month_label in months_to_run:
        print(f"\n{'='*40}")
        print(f"Running Sprint: {month_label} ({start_str} to {end_str})")
        print(f"{'='*40}")
        
        for strategy in strategies:
            cmd = [
                r"venv\Scripts\python", "backtest.py", 
                "--ticker", "GLD", 
                "--start", start_str, 
                "--end", end_str, 
                "--strategy", strategy
            ]
            
            try:
                # Run the backtest and capture output
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                
                # Parse output to find ROI
                # Usually final portfolio value is printed like "Final Portfolio Value: 109923.97"
                # For 5x leverage strings, backtest.py pads with 900,000 cash, so it parses it properly
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
                
                initial_val = 100000.0
                roi = ((final_val - initial_val) / initial_val) * 100
                
                results[strategy].append({
                    "month": month_label,
                    "roi": roi,
                    "max_dd": max_dd,
                    "trades": trades
                })
                
                print(f"{strategy:<15} | ROI: {roi:>7.2f}% | Max DD: {max_dd:>5.2f}% | Trades: {trades}")
                
            except subprocess.CalledProcessError as e:
                print(f"Error running {strategy} for {month_label}: \n{e.output}")

    # Summary
    print("\n\n" + "="*50)
    print("12-MONTH AGGREGATE RESULTS (COMPOUNDED)")
    print("="*50)
    
    for strategy in strategies:
        compounded_multiplier = 1.0
        total_trades = 0
        for res in results[strategy]:
            compounded_multiplier *= (1 + (res['roi'] / 100.0))
            total_trades += res['trades']
            
        total_roi = (compounded_multiplier - 1.0) * 100
        print(f"Strategy: {strategy}")
        print(f"Total Compounded ROI: {total_roi:.2f}%")
        print(f"Total Trades: {total_trades}")
        print("-" * 30)

if __name__ == '__main__':
    run_monthly_sprints()
