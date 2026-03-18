import backtrader as bt

class TrendMACDRSIStrategy(bt.Strategy):
    """
    A strategy that combines a lagging trend indicator (SMA),
    momentum (MACD), and a leading indicator (RSI).
    """
    params = (
        ('sma_period', 200),
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('rsi_period', 14),
        ('rsi_upper', 70),
        ('rsi_lower', 30),
        ('trade_start', None),   # date: only trade on/after this date
    )

    def __init__(self):
        # Lagging Indicator: Trend filter
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.sma_period
        )
        
        # Lagging/Hybrid Indicator: MACD for Momentum
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        
        # Leading Indicator: RSI for overbought/oversold and entry timing
        self.rsi = bt.indicators.RSI(
            self.data.close, period=self.params.rsi_period
        )

    def next(self):
        # Wait until we have enough data for the SMA 200
        if len(self) < self.params.sma_period:
            return
        # Wait until competition start date
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        if not self.position:
            # Entry rules
            # 1. Price is above SMA 200 (Long Term Uptrend)
            # 2. MACD crosses above Signal Line (Bullish Momentum)
            # 3. RSI is recovering from oversold or exhibiting bullish action (< 50)
            if self.data.close[0] > self.sma[0]:
                if self.macd.macd[0] > self.macd.signal[0] and self.macd.macd[-1] <= self.macd.signal[-1]:
                    if self.rsi[0] < 60:  # Not overbought
                        self.buy()
        else:
            # Exit rules
            # MACD crosses below Signal or RSI becomes extremely overbought
            if self.macd.macd[0] < self.macd.signal[0] and self.macd.macd[-1] >= self.macd.signal[-1]:
                self.close()
            elif self.rsi[0] > self.params.rsi_upper:
                self.close()

class MeanReversionBollingerRSI(bt.Strategy):
    """
    A mean reversion strategy using Bollinger Bands (lagging) 
    and RSI (leading). Best for sideways markets.
    """
    params = (
        ('bband_period', 20),
        ('bband_devfactor', 2.0),
        ('rsi_period', 14),
        ('trade_start', None),   # date: only trade on/after this date
    )

    def __init__(self):
        self.bband = bt.indicators.BollingerBands(
            self.data.close, 
            period=self.params.bband_period, 
            devfactor=self.params.bband_devfactor
        )
        self.rsi = bt.indicators.RSI(
            self.data.close, period=self.params.rsi_period
        )

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return
        if not self.position:
            # Buy when price closes below lower band and RSI is oversold
            if self.data.close[0] < self.bband.lines.bot[0] and self.rsi[0] < 30:
                self.buy()
        else:
            # Sell when price hits the middle band (SMA) or upper band
            if self.data.close[0] > self.bband.lines.mid[0]:
                self.close()
