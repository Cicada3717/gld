import yfinance as yf
import pandas as pd
import datetime

def analyze_losses():
    print("Downloading GLD data...")
    df = yf.download('GLD', start='2025-05-01', end='2025-08-01', interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
    
    # Specifically print info on the start of June and July
    print("First few days of June:")
    print(df['2025-06-01':'2025-06-05'][['Close', 'EMA5', 'EMA30']])
    
    print("\nFirst few days of July:")
    print(df['2025-07-01':'2025-07-05'][['Close', 'EMA5', 'EMA30']])
    
    print("\nEnd of June:")
    print(df['2025-06-25':'2025-06-30'][['Close', 'EMA5', 'EMA30']])

if __name__ == '__main__':
    analyze_losses()
