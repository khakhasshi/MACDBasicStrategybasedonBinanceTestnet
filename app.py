import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import threading
from apscheduler.schedulers.background import BackgroundScheduler
import logging

from binance_client import BinanceSimulator
from macd_strategy import MultiSymbolMACDStrategy, MACDSignal
from trading_engine import TradingEngine, PositionSide, OrderStatus
from data_collector import KlineCollector

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建Flask应用
app = Flask(__name__)
CORS(app)

# 全局变量
binance_client = None
macd_strategy = None
trading_engine = None
data_collector = None
scheduler = None

# 策略配置
STRATEGY_CONFIG = {
    'initial_capital': 3000.0,
    'symbols': ['BTCUSDT'],
    'max_positions': 1,  # 最多同时持仓数
    'enabled': False,     # 策略是否启用
    'start_time': None,
    'stop_time': None
}

def initialize_components():
    """初始化所有组件"""
    global binance_client, macd_strategy, trading_engine, data_collector, scheduler
    
    binance_client = BinanceSimulator()
    macd_strategy = MultiSymbolMACDStrategy()
    trading_engine = TradingEngine(binance_client, STRATEGY_CONFIG['initial_capital'])
    data_collector = KlineCollector(binance_client, kline_interval=30)
    
    # 添加要监控的交易对
    for symbol in STRATEGY_CONFIG['symbols']:
        data_collector.add_symbol(symbol)
        macd_strategy.add_symbol(symbol)
    
    # 初始化历史K线数据并喂给策略
    for symbol in STRATEGY_CONFIG['symbols']:
        # 初始化合约设置 (杠杆等)
        binance_client.init_futures_settings(symbol, leverage=10)
        
        data_collector.fetch_historical_klines(symbol, num_candles=100)
        klines = data_collector.get_klines(symbol)
        for k in klines:
            macd_strategy.update_kline(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(k['open_time']/1000),
                open_price=k['open'],
                high=k['high'],
                low=k['low'],
                close=k['close'],
                volume=k['volume']
            )
    
    # 启动数据采集
    data_collector.start_collection()
    
    # 启动后台任务调度器
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=strategy_check_signals, trigger="interval", seconds=2)
    # 添加网络延迟检查任务
    scheduler.add_job(func=trading_engine._measure_network_latency, trigger="interval", seconds=10)
    scheduler.start()
    
    logger.info("所有组件初始化完成并启动采集")


def strategy_check_signals():
    """策略检查信号并执行交易"""
    if not STRATEGY_CONFIG['enabled']:
        return
    
    try:
        # 获取最新K线
        latest_klines = data_collector.get_all_latest_klines()
        
        # 更新MACD策略
        for symbol in STRATEGY_CONFIG['symbols']:
            kline = latest_klines.get(symbol)
            if not kline:
                continue
            
            # 更新MACD
            signal = macd_strategy.strategies[symbol].add_kline(
                timestamp=datetime.now(),
                open_price=kline['open'],
                high=kline['high'],
                low=kline['low'],
                close=kline['close'],
                volume=kline['volume']
            )
            
            # 检查是否有活跃持仓
            has_position = symbol in trading_engine.active_positions
            
            # 金叉：开仓（多头）
            if signal.signal_type == 'GOLDEN_CROSS' and not has_position:
                if len(trading_engine.active_positions) < STRATEGY_CONFIG['max_positions']:
                    trade = trading_engine.open_position(
                        symbol=symbol,
                        side=PositionSide.LONG,
                        macd_signal=signal.signal_type
                    )
                    if trade:
                        logger.info(f"[{symbol}] 金叉信号，开仓多头: {trade.entry_price}")
            
            # 死叉：平仓（多头）
            elif signal.signal_type == 'DEAD_CROSS' and has_position:
                trade = trading_engine.close_position(symbol=symbol, macd_signal=signal.signal_type)
                if trade:
                    logger.info(f"[{symbol}] 死叉信号，平仓: P&L={trade.profit_loss:.2f}")
    
    except Exception as e:
        logger.error(f"策略检查失败: {e}")


# ==================== API 端点 ====================

@app.route('/', methods=['GET'])
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/strategy/status', methods=['GET'])
def get_strategy_status():
    """获取策略状态"""
    return jsonify({
        'enabled': STRATEGY_CONFIG['enabled'],
        'symbols': STRATEGY_CONFIG['symbols'],
        'max_positions': STRATEGY_CONFIG['max_positions'],
        'initial_capital': STRATEGY_CONFIG['initial_capital'],
        'start_time': STRATEGY_CONFIG['start_time'],
        'stop_time': STRATEGY_CONFIG['stop_time']
    })


@app.route('/api/strategy/start', methods=['POST'])
def start_strategy():
    """启动策略"""
    STRATEGY_CONFIG['enabled'] = True
    STRATEGY_CONFIG['start_time'] = datetime.now().isoformat()
    
    if not data_collector.is_collecting:
        data_collector.start_collection()
    
    return jsonify({
        'status': 'started',
        'start_time': STRATEGY_CONFIG['start_time']
    })


@app.route('/api/strategy/stop', methods=['POST'])
def stop_strategy():
    """停止策略"""
    STRATEGY_CONFIG['enabled'] = False
    STRATEGY_CONFIG['stop_time'] = datetime.now().isoformat()
    
    # 平仓所有活跃持仓
    for symbol in list(trading_engine.active_positions.keys()):
        trading_engine.close_position(symbol)
    
    return jsonify({
        'status': 'stopped',
        'stop_time': STRATEGY_CONFIG['stop_time']
    })


@app.route('/api/strategy/stats', methods=['GET'])
def get_stats():
    """获取策略统计数据"""
    return jsonify(trading_engine.get_stats())


@app.route('/api/positions/active', methods=['GET'])
def get_active_positions():
    """获取活跃持仓"""
    return jsonify({
        'count': len(trading_engine.active_positions),
        'positions': trading_engine.get_active_positions()
    })


@app.route('/api/trades/closed', methods=['GET'])
def get_closed_trades():
    """获取已平仓交易"""
    limit = request.args.get('limit', 50, type=int)
    return jsonify({
        'count': len(trading_engine.closed_trades),
        'trades': trading_engine.get_closed_trades(limit=limit)
    })


@app.route('/api/trades/all', methods=['GET'])
def get_all_trades():
    """获取所有交易"""
    symbol = request.args.get('symbol')
    return jsonify({
        'trades': trading_engine.get_all_trades(symbol=symbol)
    })


@app.route('/api/equity/curve', methods=['GET'])
def get_equity_curve():
    """获取资金曲线"""
    limit = request.args.get('limit', 1000, type=int)
    return jsonify({
        'curve': trading_engine.get_equity_curve(limit=limit)
    })


@app.route('/api/orders/klines/<symbol>', methods=['GET'])
def get_klines(symbol):
    """获取K线数据"""
    limit = request.args.get('limit', 50, type=int)
    klines = data_collector.get_klines(symbol, limit=limit)
    
    return jsonify({
        'symbol': symbol,
        'klines': klines,
        'count': len(klines)
    })


@app.route('/api/macd/signals/<symbol>', methods=['GET'])
def get_macd_signals(symbol):
    """获取MACD信号"""
    limit = request.args.get('limit', 50, type=int)
    strategy = macd_strategy.get_strategy(symbol)
    
    if not strategy:
        return jsonify({'error': 'Symbol not found'}), 404
    
    signals = strategy.get_macd_history(limit=limit)
    
    return jsonify({
        'symbol': symbol,
        'signals': [
            {
                'timestamp': sig.timestamp.isoformat(),
                'close': sig.close,
                'macd': sig.macd,
                'signal': sig.signal,
                'histogram': sig.histogram,
                'signal_type': sig.signal_type
            }
            for sig in signals
        ],
        'count': len(signals)
    })


@app.route('/api/network/latency', methods=['GET'])
def get_network_latency():
    """获取网络延迟"""
    return jsonify(trading_engine.get_network_latency())


@app.route('/api/data/collector/status', methods=['GET'])
def get_collector_status():
    """获取数据采集器状态"""
    return jsonify(data_collector.get_status())


@app.route('/api/summary', methods=['GET'])
def get_summary():
    """获取完整摘要"""
    summary = trading_engine.get_summary()
    
    # 包装活跃持仓以匹配前端期望
    summary['active_positions'] = {
        'count': len(trading_engine.active_positions),
        'positions': summary['active_positions']
    }
    
    summary['strategy'] = {
        'enabled': STRATEGY_CONFIG['enabled'],
        'symbols': STRATEGY_CONFIG['symbols'],
        'max_positions': STRATEGY_CONFIG['max_positions'],
        'initial_capital': STRATEGY_CONFIG['initial_capital'],
        'start_time': STRATEGY_CONFIG['start_time'],
        'stop_time': STRATEGY_CONFIG['stop_time']
    }
    summary['collector'] = data_collector.get_status()
    
    # 添加最新信号
    summary['latest_signals'] = {}
    for symbol in STRATEGY_CONFIG['symbols']:
        strategy = macd_strategy.get_strategy(symbol)
        if strategy:
            latest = strategy.get_latest_signal()
            if latest:
                summary['latest_signals'][symbol] = {
                    'close': latest.close,
                    'macd': latest.macd,
                    'signal': latest.signal,
                    'histogram': latest.histogram,
                    'signal_type': latest.signal_type
                }
    
    return jsonify(summary)


@app.route('/api/manual/position/<symbol>/<action>', methods=['POST'])
def manual_position(symbol, action):
    """手动开仓/平仓"""
    try:
        if action == 'open':
            # 检查是否已有持仓
            if symbol in trading_engine.active_positions:
                return jsonify({'status': 'failed', 'error': f'{symbol} 已有持仓'}), 400
                
            side_str = request.json.get('side', 'BUY')
            side = PositionSide.LONG if side_str == 'BUY' else PositionSide.SHORT
            
            trade = trading_engine.open_position(symbol, side, 'MANUAL')
            if trade:
                return jsonify({
                    'status': 'success',
                    'trade': trade.to_dict()
                })
            else:
                error_msg = trading_engine.last_error or '开仓失败'
                return jsonify({'status': 'failed', 'error': error_msg}), 400
        
        elif action == 'close':
            if symbol not in trading_engine.active_positions:
                return jsonify({'status': 'failed', 'error': f'{symbol} 没有活跃持仓'}), 400
                
            trade = trading_engine.close_position(symbol, 'MANUAL')
            if trade:
                return jsonify({
                    'status': 'success',
                    'trade': trade.to_dict()
                })
            else:
                error_msg = trading_engine.last_error or '平仓失败'
                return jsonify({'status': 'failed', 'error': error_msg}), 400
    
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    """404 处理"""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(error):
    """500 处理"""
    return jsonify({'error': 'Server error'}), 500


if __name__ == '__main__':
    # 初始化组件
    initialize_components()
    
    # 启动Flask应用
    app.run(
        host='0.0.0.0',
        port=5431,
        debug=True,
        use_reloader=False  # 禁用重新加载器，避免重复初始化
    )
