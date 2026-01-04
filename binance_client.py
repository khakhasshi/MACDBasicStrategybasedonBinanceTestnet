import os
from dotenv import load_dotenv
from binance.spot import Spot
from binance.um_futures import UMFutures

# 加载环境变量
load_dotenv()

class BinanceSimulator:
    """币安模拟账户客户端 (现货监控 + 合约交易)"""
    
    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')
        
        # 支持独立的合约 API Key (测试网环境下现货和合约 Key 是分开的)
        self.futures_api_key = os.getenv('BINANCE_FUTURES_API_KEY', self.api_key)
        self.futures_api_secret = os.getenv('BINANCE_FUTURES_API_SECRET', self.api_secret)
        
        self.mode = os.getenv('BINANCE_MODE', 'testnet')
        
        # 检查API密钥是否已配置
        if not self.api_key or self.api_key == 'your_testnet_api_key_here':
            print("⚠️  警告: 未配置现货 API 密钥")
        
        # 初始化现货客户端 (用于监控)
        if self.mode == 'testnet':
            self.spot_client = Spot(
                api_key=self.api_key,
                api_secret=self.api_secret,
                base_url="https://testnet.binance.vision"
            )
            # 初始化合约客户端 (用于下单)
            self.futures_client = UMFutures(
                key=self.futures_api_key,
                secret=self.futures_api_secret,
                base_url="https://testnet.binancefuture.com"
            )
        else:
            self.spot_client = Spot(
                api_key=self.api_key,
                api_secret=self.api_secret
            )
            self.futures_client = UMFutures(
                key=self.futures_api_key,
                secret=self.futures_api_secret
            )
        
        # 默认使用现货客户端进行行情获取 (兼容旧代码)
        self.client = self.spot_client
    
    def init_futures_settings(self, symbol, leverage=10):
        """初始化合约设置：杠杆和全仓模式"""
        try:
            # 设置杠杆
            self.futures_client.change_leverage(symbol=symbol, leverage=leverage)
            # 设置边际模式 (ISOLATED 或 CROSSED)
            try:
                self.futures_client.change_margin_type(symbol=symbol, marginType="ISOLATED")
            except Exception as e:
                # 如果已经是该模式会报错，忽略即可
                pass
            print(f"合约设置完成: {symbol} 杠杆={leverage}, 模式=ISOLATED")
        except Exception as e:
            print(f"初始化合约设置失败: {e}")
        """获取合约账户信息"""
        try:
            account = self.futures_client.account()
            return account
        except Exception as e:
            print(f"获取合约账户信息失败: {e}")
            return None
    
    def get_balance(self):
        """获取合约账户余额"""
        try:
            balances = self.futures_client.balance()
            result = {}
            for b in balances:
                asset = b['asset']
                free = float(b['withdrawAvailable'])
                total = float(b['balance'])
                if total > 0:
                    result[asset] = {
                        'free': free,
                        'total': total
                    }
            return result
        except Exception as e:
            print(f"获取合约余额失败: {e}")
            return {}
    
    def get_current_price(self, symbol='BTCUSDT'):
        """获取现货当前价格 (用于信号监控)"""
        try:
            ticker = self.spot_client.ticker_price(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"获取现货价格失败: {e}")
            return None

    def get_futures_price(self, symbol='BTCUSDT'):
        """获取合约当前价格 (用于交易对齐)"""
        try:
            ticker = self.futures_client.ticker_price(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"获取合约价格失败: {e}")
            return None
    
    def place_order(self, symbol, side, order_type, quantity, price=None):
        """在永续合约市场下单
        
        Args:
            symbol: 交易对，如 'BTCUSDT'
            side: 'BUY' 或 'SELL'
            order_type: 'LIMIT' 或 'MARKET'
            quantity: 数量
            price: 价格（仅限 LIMIT 订单）
        """
        try:
            params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity
            }
            
            if order_type == 'LIMIT' and price:
                params['price'] = price
                params['timeInForce'] = 'GTC'
            
            # 打印下单参数以便调试
            print(f"发送合约订单: {params}")
            
            order = self.futures_client.new_order(**params)
            return order
        except Exception as e:
            error_msg = str(e)
            print(f"合约下单失败: {error_msg}")
            
            # 针对测试网常见的 Key 错误进行友好提示
            if "Invalid API-key" in error_msg or "-2015" in error_msg:
                if self.mode == 'testnet':
                    error_msg = "合约 API Key 无效。请注意：币安测试网的现货(Spot)和合约(Futures)使用不同的 API Key。请前往 https://testnet.binancefuture.com 获取合约专用 Key 并配置 BINANCE_FUTURES_API_KEY。"
                else:
                    error_msg = "API Key 无效或没有合约交易权限。请检查 API Key 是否正确且已在后台勾选 'Enable Futures'。"
            
            return {'status': 'FAILED', 'error': error_msg}
    
    def get_open_orders(self, symbol=None):
        """获取开仓订单"""
        try:
            if symbol:
                orders = self.client.get_open_orders(symbol=symbol)
            else:
                # 获取所有交易对的开仓订单，需要逐个查询
                orders = []
            return orders
        except Exception as e:
            print(f"获取订单失败: {e}")
            return []
    
    def cancel_order(self, symbol, order_id):
        """取消订单"""
        try:
            result = self.client.cancel_order(symbol=symbol, orderId=order_id)
            return result
        except Exception as e:
            print(f"取消订单失败: {e}")
            return None

if __name__ == '__main__':
    simulator = BinanceSimulator()
    print("币安模拟账户客户端已初始化")
