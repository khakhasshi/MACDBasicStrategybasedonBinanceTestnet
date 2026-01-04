from binance_client import BinanceSimulator

def main():
    # 初始化模拟器
    simulator = BinanceSimulator()
    
    print("=" * 50)
    print("币安模拟账户测试")
    print("=" * 50)
    
    # 1. 获取账户信息
    print("\n1. 获取账户信息...")
    account = simulator.get_account_info()
    if account:
        print(f"账户 UID: {account.get('uid', 'N/A')}")
        print(f"成功连接到币安API")
    else:
        print("✗ 获取账户信息失败 - 请检查API密钥配置")
        print("  访问 https://testnet.binance.vision 获取测试网密钥")
    
    # 2. 获取余额
    print("\n2. 获取账户余额...")
    balance = simulator.get_balance()
    if balance:
        print(f"账户余额数量: {len(balance)} 种资产")
        for symbol, amounts in list(balance.items())[:5]:
            print(f"  {symbol}: 可用={amounts['free']}, 锁定={amounts['locked']}")
    else:
        print("✗ 获取余额失败或账户为空")
    
    # 3. 获取BTC当前价格
    print("\n3. 获取当前价格...")
    price = simulator.get_current_price('BTCUSDT')
    if price:
        print(f"✓ BTC/USDT 当前价格: ${price:,.2f}")
    else:
        print("✗ 获取价格失败")
    
    # 4. 获取开仓订单
    print("\n4. 获取开仓订单...")
    orders = simulator.get_open_orders()
    if orders:
        print(f"✓ 开仓订单数: {len(orders)}")
        for order in orders[:3]:  # 显示前3个
            print(f"  - {order['symbol']}: {order['side']} {order['origQty']} @ {order['price']}")
    else:
        print("✓ 无开仓订单")
    
    print("\n" + "=" * 50)
    print("✓ 测试完成！")
    print("=" * 50)

if __name__ == '__main__':
    main()
