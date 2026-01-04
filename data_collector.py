import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from binance_client import BinanceSimulator


class KlineCollector:
    """30秒K线数据采集器"""
    
    def __init__(self, binance_client: BinanceSimulator, kline_interval: int = 30):
        """
        初始化K线采集器
        
        Args:
            binance_client: 币安客户端
            kline_interval: K线周期（秒），默认30秒
        """
        self.client = binance_client
        self.kline_interval = kline_interval
        
        self.klines: Dict[str, List[Dict]] = defaultdict(list)  # 交易对 -> K线列表
        self.current_kline: Dict[str, Dict] = {}  # 当前K线
        self.last_update: Dict[str, datetime] = {}  # 最后更新时间
        
        self.is_collecting = False
        self.collection_thread = None
        self.symbols = set()  # 监控的交易对集合
    
    def add_symbol(self, symbol: str):
        """添加要监控的交易对"""
        self.symbols.add(symbol)
    
    def remove_symbol(self, symbol: str):
        """移除监控的交易对"""
        self.symbols.discard(symbol)
    
    def get_latest_kline(self, symbol: str) -> Optional[Dict]:
        """获取最新K线"""
        if symbol in self.klines and self.klines[symbol]:
            return self.klines[symbol][-1]
        return None
    
    def get_klines(self, symbol: str, limit: int = None) -> List[Dict]:
        """获取K线历史数据"""
        klines = self.klines.get(symbol, [])
        if limit:
            return klines[-limit:]
        return klines
    
    def fetch_historical_klines(self, symbol: str, num_candles: int = 20):
        """
        从币安API获取历史K线（用于初始化）
        
        Args:
            symbol: 交易对
            num_candles: 获取的蜡烛数量
        """
        try:
            # 使用币安REST API获取历史K线（使用1分钟间隔）
            klines = self.client.client.klines(
                symbol=symbol,
                interval='1m',  # 1分钟K线
                limit=num_candles
            )
            
            for kline in klines:
                k = {
                    'open_time': int(kline[0]),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[7]),
                    'close_time': int(kline[6])
                }
                self.klines[symbol].append(k)
            
            if self.klines[symbol]:
                self.last_update[symbol] = datetime.now()
            
        except Exception as e:
            print(f"获取历史K线失败 {symbol}: {e}")
    
    def _fetch_current_price(self, symbol: str) -> Optional[Dict]:
        """获取当前价格信息"""
        try:
            ticker = self.client.client.ticker_24hr(symbol=symbol)
            
            return {
                'timestamp': datetime.now().timestamp() * 1000,
                'open': float(ticker.get('openPrice', 0)),
                'high': float(ticker.get('highPrice', 0)),
                'low': float(ticker.get('lowPrice', 0)),
                'close': float(ticker.get('lastPrice', 0)),
                'volume': float(ticker.get('volume', 0))
            }
        except Exception as e:
            print(f"获取价格失败 {symbol}: {e}")
            return None
    
    def _update_kline(self, symbol: str):
        """更新单个交易对的K线"""
        try:
            price_data = self._fetch_current_price(symbol)
            if not price_data:
                return
            
            now = datetime.now()
            
            # 初始化当前K线或检查是否需要新建K线
            if symbol not in self.current_kline:
                self.current_kline[symbol] = {
                    'open_time': int(now.timestamp() * 1000),
                    'open': price_data['close'],
                    'high': price_data['close'],
                    'low': price_data['close'],
                    'close': price_data['close'],
                    'volume': 0,
                    'close_time': int(now.timestamp() * 1000)
                }
                self.last_update[symbol] = now
            else:
                last_update = self.last_update.get(symbol, now)
                time_diff = (now - last_update).total_seconds()
                
                # 如果超过K线周期，保存当前K线并开始新的
                if time_diff >= self.kline_interval:
                    # 保存完整的K线
                    self.current_kline[symbol]['close_time'] = int(last_update.timestamp() * 1000)
                    self.klines[symbol].append(self.current_kline[symbol].copy())
                    
                    # 限制历史记录大小（只保留最近1000条）
                    if len(self.klines[symbol]) > 1000:
                        self.klines[symbol] = self.klines[symbol][-1000:]
                    
                    # 创建新K线
                    self.current_kline[symbol] = {
                        'open_time': int(now.timestamp() * 1000),
                        'open': price_data['close'],
                        'high': price_data['close'],
                        'low': price_data['close'],
                        'close': price_data['close'],
                        'volume': 0,
                        'close_time': int(now.timestamp() * 1000)
                    }
                    self.last_update[symbol] = now
                else:
                    # 更新当前K线
                    self.current_kline[symbol]['high'] = max(
                        self.current_kline[symbol]['high'],
                        price_data['close']
                    )
                    self.current_kline[symbol]['low'] = min(
                        self.current_kline[symbol]['low'],
                        price_data['close']
                    )
                    self.current_kline[symbol]['close'] = price_data['close']
                    self.current_kline[symbol]['close_time'] = int(now.timestamp() * 1000)
        
        except Exception as e:
            print(f"更新K线失败 {symbol}: {e}")
    
    def _collection_loop(self):
        """数据采集主循环"""
        while self.is_collecting:
            try:
                for symbol in self.symbols:
                    self._update_kline(symbol)
                
                # 每秒更新一次数据
                time.sleep(1)
            
            except Exception as e:
                print(f"采集循环错误: {e}")
                time.sleep(5)
    
    def start_collection(self):
        """启动数据采集"""
        if self.is_collecting:
            return
        
        self.is_collecting = True
        self.collection_thread = threading.Thread(
            target=self._collection_loop,
            daemon=True
        )
        self.collection_thread.start()
    
    def stop_collection(self):
        """停止数据采集"""
        self.is_collecting = False
        if self.collection_thread:
            self.collection_thread.join(timeout=5)
    
    def get_all_latest_klines(self) -> Dict[str, Optional[Dict]]:
        """获取所有交易对的最新K线"""
        result = {}
        for symbol in self.symbols:
            result[symbol] = self.get_latest_kline(symbol)
        return result
    
    def get_status(self) -> Dict:
        """获取采集器状态"""
        return {
            'is_collecting': self.is_collecting,
            'symbols_monitored': list(self.symbols),
            'kline_interval': self.kline_interval,
            'latest_klines_count': {
                symbol: len(self.klines.get(symbol, []))
                for symbol in self.symbols
            }
        }
