import yfinance as yf
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
import itertools

def find_cointegrated_pairs(tickers, start_date, end_date, p_value_threshold=0.05):
    """
    Downloads historical data for a list of tickers and 
    finds cointegrated pairs using the Engle-Granger test.
    """
    print(f"Downloading data for {len(tickers)} tickers...")
    data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']
    
    # Drop columns with all NaNs to prevent errors
    data.dropna(axis=1, how='all', inplace=True)
    # Forward fill missing values
    data.ffill(inplace=True)
    data.bfill(inplace=True)
    
    available_tickers = data.columns.tolist()
    print(f"Testing {len(available_tickers)} available tickers for pairs...")

    n = data.shape[1]
    keys = data.keys()
    pairs = []

    # Get all combinations of length 2
    ticker_combinations = list(itertools.combinations(available_tickers, 2))
    
    for i, (t1, t2) in enumerate(ticker_combinations):
        if i % 50 == 0:
            print(f"Processing combo {i}/{len(ticker_combinations)}")
            
        S1 = data[t1]
        S2 = data[t2]
        
        # Test for cointegration
        score, pvalue, _ = coint(S1, S2)
        
        if pvalue < p_value_threshold:
            # We found a pair! Let's calculate the correlation too
            correlation = S1.corr(S2)
            pairs.append((t1, t2, pvalue, correlation))

    # Sort pairs by p-value (smallest is best)
    pairs.sort(key=lambda x: x[2])
    
    return pairs

if __name__ == "__main__":
    # A mix of stocks from similar sectors (banking, tech, energy, telecom)
    tech_tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'AMD', 'INTC', 'CRM', 'ORCL']
    banking_tickers = ['JPM', 'BAC', 'C', 'WFC', 'GS', 'MS', 'USB', 'PNC']
    telecom_tickers = ['T', 'VZ', 'TMUS', 'CMCSA', 'CHTR']
    consumer_staples = ['KO', 'PEP', 'PG', 'KMB', 'CL', 'WMT', 'TGT', 'COST']
    
    # We will test consumer staples as they tend to be highly cointegrated
    test_universe = consumer_staples
    
    print(f"Testing universe: {test_universe}")
    found_pairs = find_cointegrated_pairs(test_universe, start_date='2019-01-01', end_date='2024-01-01')
    
    print("\n--- Found Cointegrated Pairs ---")
    if not found_pairs:
        print("No pairs found under the p-value threshold.")
    else:
        for t1, t2, pval, corr in found_pairs:
            print(f"Pair: {t1} - {t2} | P-Value: {pval:.4f} | Correlation: {corr:.2f}")
