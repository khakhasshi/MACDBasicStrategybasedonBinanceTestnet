import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

@dataclass
class MACDSignal:
    """MACD信号数据类"""
    timestamp: datetime
    close: float
    macd: float
    signal: float
    histogram: float
    signal_type: str  # 'NONE', 'GOLDEN_CROSS', 'DEAD_CROSS'
    
class MACDStrategy:
    """MACD策略引擎 - 参数(5, 10, 3)"""
    
    def __init__(self, fast_period=5, slow_period=10, signal_period=3):
        """
        初始化MACD策略
        
        Args:
            fast_period: 快速EMA周期（默认5）
            slow_period: 慢速EMA周期（默认10）
            signal_period: 信号线EMA周期（默认3）
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        
        self.klines_history = []  # K线历史数据
        self.macd_history = []    # MACD历史数据
        self.prev_histogram = None  # 上一个MACD柱子值
    
    def _ema(self, data: List[float], period: int) -> List[float]:
        """计算EMA（指数移动平均）"""
        if len(data) < period:
            return [None] * len(data)
        
        ema = []
        multiplier = 2 / (period + 1)
        
        # 第一个EMA是简单平均
        sma = sum(data[:period]) / period
        ema.extend([None] * (period - 1))
        ema.append(sma)
        
        # 后续使用EMA公式
        for i in range(period, len(data)):
            ema_value = data[i] * multiplier + ema[-1] * (1 - multiplier)
            ema.append(ema_value)
        
        return ema
    
    def add_kline(self, timestamp: datetime, open_price: float, high: float, 
                  low: float, close: float, volume: float) -> MACDSignal:
        """
        添加一条K线，计算MACD信号
        
        Args:
            timestamp: K线时间戳
            open_price: 开盘价
            high: 最高价
            low: 最低价
            close: 收盘价
            volume: 成交量
            
        Returns:
            MACDSignal 对象包含MACD数据和交易信号
        """
        self.klines_history.append({
            'timestamp': timestamp,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        })
        
        closes = [k['close'] for k in self.klines_history]
        
        # 需要足够的数据来计算MACD
        if len(closes) < self.slow_period + self.signal_period - 1:
            return MACDSignal(
                timestamp=timestamp,
                close=close,
                macd=0,
                signal=0,
                histogram=0,
                signal_type='NONE'
            )
        
        # 计算EMA
        ema_fast = self._ema(closes, self.fast_period)
        ema_slow = self._ema(closes, self.slow_period)
        
        # 计算MACD线 (DIF)
        macd_line = [
            fast - slow if fast is not None and slow is not None else None
            for fast, slow in zip(ema_fast, ema_slow)
        ]
        
        # 移除None值后计算信号线
        macd_values = [v for v in macd_line if v is not None]
        
        if len(macd_values) < self.signal_period:
            return MACDSignal(
                timestamp=timestamp,
                close=close,
                macd=0,
                signal=0,
                histogram=0,
                signal_type='NONE'
            )
        
        # 计算信号线 (DEA)
        signal_line = self._ema(macd_values, self.signal_period)
        
        current_macd = macd_values[-1]
        current_signal = signal_line[-1] if signal_line[-1] is not None else 0
        current_histogram = current_macd - current_signal
        
        # 判断交叉信号
        signal_type = 'NONE'
        if self.prev_histogram is not None:
            # 金叉：从负数变正数（MACD > 信号线且前一根柱子 MACD <= 信号线）
            if self.prev_histogram < 0 and current_histogram >= 0:
                signal_type = 'GOLDEN_CROSS'  # 买入信号
            # 死叉：从正数变负数（MACD < 信号线且前一根柱子 MACD >= 信号线）
            elif self.prev_histogram >= 0 and current_histogram < 0:
                signal_type = 'DEAD_CROSS'  # 卖出信号
        
        self.prev_histogram = current_histogram
        
        macd_data = MACDSignal(
            timestamp=timestamp,
            close=close,
            macd=round(current_macd, 8),
            signal=round(current_signal, 8),
            histogram=round(current_histogram, 8),
            signal_type=signal_type
        )
        
        self.macd_history.append(macd_data)
        return macd_data
    
    def get_latest_signal(self) -> MACDSignal:
        """获取最新的MACD信号"""
        if self.macd_history:
            return self.macd_history[-1]
        return None
    
    def get_macd_history(self, limit: int = None) -> List[MACDSignal]:
        """获取MACD历史数据"""
        if limit:
            return self.macd_history[-limit:]
        return self.macd_history
    
    def reset(self):
        """重置策略"""
        self.klines_history = []
        self.macd_history = []
        self.prev_histogram = None


class MultiSymbolMACDStrategy:
    """多交易对MACD策略管理器"""
    
    def __init__(self):
        self.strategies: Dict[str, MACDStrategy] = {}
    
    def add_symbol(self, symbol: str) -> MACDStrategy:
        """为交易对添加MACD策略"""
        if symbol not in self.strategies:
            self.strategies[symbol] = MACDStrategy()
        return self.strategies[symbol]
    
    def get_strategy(self, symbol: str) -> MACDStrategy:
        """获取指定交易对的策略"""
        return self.strategies.get(symbol)
    
    def update_kline(self, symbol: str, timestamp: datetime, open_price: float, 
                     high: float, low: float, close: float, volume: float) -> MACDSignal:
        """更新交易对K线数据"""
        if symbol not in self.strategies:
            self.add_symbol(symbol)
        return self.strategies[symbol].add_kline(
            timestamp, open_price, high, low, close, volume
        )
    
    def get_signals(self) -> Dict[str, MACDSignal]:
        """获取所有交易对的最新信号"""
        signals = {}
        for symbol, strategy in self.strategies.items():
            latest = strategy.get_latest_signal()
            if latest:
                signals[symbol] = latest
        return signals
    
    def get_buy_signals(self) -> List[Tuple[str, MACDSignal]]:
        """获取所有买入信号（金叉）"""
        buy_signals = []
        for symbol, strategy in self.strategies.items():
            latest = strategy.get_latest_signal()
            if latest and latest.signal_type == 'GOLDEN_CROSS':
                buy_signals.append((symbol, latest))
        return buy_signals
    
    def get_sell_signals(self) -> List[Tuple[str, MACDSignal]]:
        """获取所有卖出信号（死叉）"""
        sell_signals = []
        for symbol, strategy in self.strategies.items():
            latest = strategy.get_latest_signal()
            if latest and latest.signal_type == 'DEAD_CROSS':
                sell_signals.append((symbol, latest))
        return sell_signals
