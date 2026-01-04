import time
import json
from math import floor
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, field, asdict
import uuid
from binance_client import BinanceSimulator


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"      # 待下单
    OPEN = "open"            # 已开仓
    CLOSED = "closed"        # 已平仓
    CANCELLED = "cancelled"  # 已取消
    FAILED = "failed"        # 下单失败


class PositionSide(Enum):
    """持仓方向"""
    LONG = "BUY"     # 多头
    SHORT = "SELL"   # 空头


@dataclass
class Trade:
    """交易记录"""
    trade_id: str
    symbol: str
    side: PositionSide
    entry_price: float
    entry_quantity: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_quantity: Optional[float] = None
    exit_time: Optional[datetime] = None
    profit_loss: float = 0.0
    profit_loss_pct: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    macd_signal: str = ""  # 触发信号
    
    def to_dict(self):
        return {
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'entry_price': self.entry_price,
            'entry_quantity': self.entry_quantity,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_price': self.exit_price,
            'exit_quantity': self.exit_quantity,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'profit_loss': round(self.profit_loss, 2),
            'profit_loss_pct': round(self.profit_loss_pct, 4),
            'status': self.status.value,
            'macd_signal': self.macd_signal
        }


@dataclass
class StrategyStats:
    """策略统计数据"""
    initial_capital: float = 0.0
    current_capital: float = 0.0
    available_balance: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit_loss: float = 0.0
    profit_loss_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    roi: float = 0.0
    sharpe_ratio: float = 0.0
    
    def to_dict(self):
        return {
            'initial_capital': round(self.initial_capital, 2),
            'current_capital': round(self.current_capital, 2),
            'available_balance': round(self.available_balance, 2),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'total_profit_loss': round(self.total_profit_loss, 2),
            'profit_loss_pct': round(self.profit_loss_pct, 4),
            'win_rate': round(self.win_rate, 4),
            'max_drawdown': round(self.max_drawdown, 4),
            'roi': round(self.roi, 4),
            'sharpe_ratio': round(self.sharpe_ratio, 4)
        }


class TradingEngine:
    """交易执行引擎"""
    
    def __init__(self, binance_client: BinanceSimulator, initial_capital: float = 3000.0):
        """
        初始化交易引擎
        
        Args:
            binance_client: 币安客户端
            initial_capital: 初始资金（USDT）
        """
        self.client = binance_client
        self.initial_capital = initial_capital
        self.available_balance = initial_capital  # 可用余额
        self.total_capital = initial_capital      # 总资本
        
        self.trades: Dict[str, List[Trade]] = {}  # 交易对->交易列表
        self.active_positions: Dict[str, Trade] = {}  # 活跃持仓
        self.closed_trades = []  # 已平仓交易
        
        self.equity_curve = []  # 资金曲线
        self.equity_curve.append({
            'timestamp': datetime.now(),
            'equity': self.total_capital,
            'available': self.available_balance
        })
        
        self.stats = StrategyStats(
            initial_capital=initial_capital,
            current_capital=initial_capital,
            available_balance=initial_capital
        )
        
        self.network_latency = 0.0  # 网络延迟（毫秒）
        self.last_error = None      # 最近一次错误信息
    
    def _allocate_position_size(self, symbol: str, percentage: float = 0.5) -> float:
        """
        计算持仓大小（基于可用余额的百分比）
        
        Args:
            symbol: 交易对
            percentage: 使用比例（0-1，默认0.5）
            
        Returns:
            可用于此交易的USDT数量
        """
        allocation = self.available_balance * percentage
        return allocation
    
    def _measure_network_latency(self):
        """测量网络延迟"""
        start = time.time()
        try:
            # 获取服务器时间作为延迟测试
            if hasattr(self.client, 'client') and hasattr(self.client.client, 'time'):
                self.client.client.time()
            self.network_latency = (time.time() - start) * 1000  # 转换为毫秒
        except Exception as e:
            self.network_latency = 0  # 测量失败时设为0，不影响业务
    
    def _format_quantity(self, symbol: str, quantity: float) -> float:
        """根据合约交易对的精度要求格式化数量"""
        # 币安合约 BTCUSDT 的数量精度通常为 3 位 (stepSize: 0.001)
        precisions = {
            'BTCUSDT': 3,
            'ETHUSDT': 3,
            'BNBUSDT': 2,
            'LTCUSDT': 3
        }
        p = precisions.get(symbol, 3)
        return floor(quantity * (10**p)) / (10**p)

    def open_position(self, symbol: str, side: PositionSide, macd_signal: str) -> Optional[Trade]:
        """
        开仓
        
        Args:
            symbol: 交易对（如 'BTCUSDT'）
            side: 多头(BUY) 或 空头(SELL)
            macd_signal: 触发信号（'GOLDEN_CROSS' 或 'DEAD_CROSS'）
            
        Returns:
            Trade 对象或 None（如果失败）
        """
        try:
            self._measure_network_latency()
            self.last_error = None
            
            # 获取当前合约价格
            current_price = self.client.get_futures_price(symbol)
            if not current_price:
                self.last_error = f"无法获取 {symbol} 的当前合约价格"
                return None
            
            # 分配持仓大小（每次使用50%可用USDT）
            allocation_usdt = self._allocate_position_size(symbol, 0.5)
            if allocation_usdt < 10: # 币安最小交易额通常为10 USDT
                self.last_error = f"可用余额不足 (需 >10 USDT, 当前分配: {allocation_usdt:.2f})"
                return None
                
            entry_quantity = self._format_quantity(symbol, allocation_usdt / current_price)
            
            # 在实盘中下单
            order = self.client.place_order(
                symbol=symbol,
                side=side.value,
                order_type='MARKET',
                quantity=entry_quantity
            )
            
            if not order or order.get('status') == 'FAILED':
                self.last_error = order.get('error', '下单请求无响应') if order else '下单请求无响应'
                return None
            
            # 创建交易记录
            trade = Trade(
                trade_id=str(uuid.uuid4())[:8],
                symbol=symbol,
                side=side,
                entry_price=current_price,
                entry_quantity=entry_quantity,
                entry_time=datetime.now(),
                macd_signal=macd_signal,
                status=OrderStatus.OPEN
            )
            
            # 更新余额
            self.available_balance -= allocation_usdt
            
            # 保存交易
            if symbol not in self.trades:
                self.trades[symbol] = []
            self.trades[symbol].append(trade)
            self.active_positions[symbol] = trade
            
            # 更新统计
            self.stats.total_trades += 1
            
            return trade
            
        except Exception as e:
            print(f"开仓失败 {symbol}: {e}")
            return None
    
    def close_position(self, symbol: str, macd_signal: str = "") -> Optional[Trade]:
        """
        平仓
        
        Args:
            symbol: 交易对
            macd_signal: 触发信号
            
        Returns:
            更新后的 Trade 对象或 None（如果没有活跃持仓）
        """
        try:
            self.last_error = None
            if symbol not in self.active_positions:
                self.last_error = f"{symbol} 没有活跃持仓"
                return None
            
            self._measure_network_latency()
            
            trade = self.active_positions[symbol]
            
            # 获取当前合约价格
            current_price = self.client.get_futures_price(symbol)
            if not current_price:
                self.last_error = f"无法获取 {symbol} 的当前合约价格"
                return None
            
            # 下单平仓
            opposite_side = PositionSide.SHORT if trade.side == PositionSide.LONG else PositionSide.LONG
            order = self.client.place_order(
                symbol=symbol,
                side=opposite_side.value,
                order_type='MARKET',
                quantity=self._format_quantity(symbol, trade.entry_quantity)
            )
            
            if not order or order.get('status') == 'FAILED':
                self.last_error = order.get('error', '平仓下单失败') if order else '平仓下单无响应'
                return None
            
            # 更新交易记录
            trade.exit_price = current_price
            trade.exit_quantity = trade.entry_quantity
            trade.exit_time = datetime.now()
            trade.status = OrderStatus.CLOSED
            
            # 计算利润
            if trade.side == PositionSide.LONG:
                profit_loss = (current_price - trade.entry_price) * trade.entry_quantity
            else:
                profit_loss = (trade.entry_price - current_price) * trade.entry_quantity
            
            trade.profit_loss = profit_loss
            trade.profit_loss_pct = (profit_loss / (trade.entry_price * trade.entry_quantity)) * 100
            
            # 更新余额和总资本
            exit_amount = current_price * trade.entry_quantity
            self.available_balance += exit_amount
            self.total_capital += profit_loss
            
            # 更新统计
            if profit_loss > 0:
                self.stats.winning_trades += 1
            elif profit_loss < 0:
                self.stats.losing_trades += 1
            
            self.stats.total_profit_loss += profit_loss
            self.stats.profit_loss_pct = (self.stats.total_profit_loss / self.initial_capital) * 100
            
            if self.stats.total_trades > 0:
                self.stats.win_rate = self.stats.winning_trades / self.stats.total_trades
            
            # 移出活跃持仓
            del self.active_positions[symbol]
            self.closed_trades.append(trade)
            
            # 添加到资金曲线
            self.equity_curve.append({
                'timestamp': datetime.now(),
                'equity': self.total_capital,
                'available': self.available_balance
            })
            
            # 更新统计数据
            self._update_stats()
            
            return trade
            
        except Exception as e:
            print(f"平仓失败 {symbol}: {e}")
            return None
    
    def _update_stats(self):
        """更新策略统计数据"""
        self.stats.current_capital = self.total_capital
        self.stats.available_balance = self.available_balance
        self.stats.roi = ((self.total_capital - self.initial_capital) / self.initial_capital) * 100
        
        # 计算最大回撤
        if self.equity_curve:
            peak = self.equity_curve[0]['equity']
            max_dd = 0
            for eq in self.equity_curve:
                if eq['equity'] > peak:
                    peak = eq['equity']
                dd = (peak - eq['equity']) / peak
                if dd > max_dd:
                    max_dd = dd
            self.stats.max_drawdown = max_dd
    
    def get_active_positions(self) -> List[Dict]:
        """获取活跃持仓"""
        return [trade.to_dict() for trade in self.active_positions.values()]
    
    def get_closed_trades(self, limit: int = None) -> List[Dict]:
        """获取已平仓交易"""
        trades = self.closed_trades[-limit:] if limit else self.closed_trades
        return [trade.to_dict() for trade in trades]
    
    def get_all_trades(self, symbol: str = None) -> List[Dict]:
        """获取所有交易"""
        if symbol:
            return [trade.to_dict() for trade in self.trades.get(symbol, [])]
        
        all_trades = []
        for trades in self.trades.values():
            all_trades.extend(trades)
        return [trade.to_dict() for trade in all_trades]
    
    def get_equity_curve(self, limit: int = None) -> List[Dict]:
        """获取资金曲线"""
        curve = self.equity_curve[-limit:] if limit else self.equity_curve
        return [
            {
                'timestamp': point['timestamp'].isoformat(),
                'equity': round(point['equity'], 2),
                'available': round(point['available'], 2)
            }
            for point in curve
        ]
    
    def get_stats(self) -> Dict:
        """获取策略统计数据"""
        self._update_stats()
        return self.stats.to_dict()
    
    def get_network_latency(self) -> Dict:
        """获取网络延迟信息"""
        return {
            'latency_ms': round(self.network_latency, 2),
            'status': 'OK' if self.network_latency >= 0 else 'ERROR'
        }
    
    def get_summary(self) -> Dict:
        """获取完整摘要"""
        return {
            'stats': self.get_stats(),
            'active_positions': self.get_active_positions(),
            'recent_closed_trades': self.get_closed_trades(limit=10),
            'equity_curve': self.get_equity_curve(),
            'network_latency': self.get_network_latency()
        }
