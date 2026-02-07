import argparse
import sys
import os
import json
from datetime import datetime

# Add the current directory to sys.path to allow imports from modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.data_provider import fetch_binance_history
from core.strategy_calculator import analyze_strategy

def generate_strategies(symbols):
    """
    为每个交易对生成 3 种策略配置文件。
    
    策略类型:
    1. Martingale (马丁格尔): 固定权重 (倒金字塔加仓)
    2. Probability (概率分布): 固定权重 (正态分布/高频优先)
    3. Amplitude Distribution (振幅分布): 根据历史数据动态计算权重 (全周期回测最优)
    """
    strategy_types = ["martingale", "probability", "amplitude_distribution"]
    
    for symbol in symbols:
        print(f"\n🚀 开始为 {symbol} 生成策略配置...")
        
        for st_type in strategy_types:
            try:
                if st_type == "amplitude_distribution":
                    # 特殊处理：Binance 的振幅分布策略通过回测生成
                    run_backtest_all_periods(symbol)
                else:
                    # 其他固定逻辑策略
                    config = create_fixed_strategy_config(symbol, st_type)
                    save_strategy_config(symbol, st_type, config)
            except Exception as e:
                print(f"❌ 生成 {st_type} 策略失败: {e}")

def create_fixed_strategy_config(symbol, strategy_type, num_grids=10, profit_amp=0.012, step_drop=0.01):
    grids = []
    weights = []
    
    if strategy_type == "martingale":
        # 马丁: 3层轻(5%), 4层中(10%), 3层重(15%)
        weights = [0.05]*3 + [0.10]*4 + [0.15]*3
        if len(weights) < num_grids:
            weights += [0.15] * (num_grids - len(weights))
            
    elif strategy_type == "probability":
        # 概率: 3层重(15%), 4层中(10%), 3层轻(5%)
        weights = [0.15]*3 + [0.10]*4 + [0.05]*3
        if len(weights) < num_grids:
            weights += [0.05] * (num_grids - len(weights))
            
    else:
        weights = [1.0/num_grids] * num_grids

    # 截断或填充
    if len(weights) > num_grids:
        weights = weights[:num_grids]
    elif len(weights) < num_grids:
        weights += [0.0] * (num_grids - len(weights))

    # 生成网格配置
    for i in range(1, num_grids + 1):
        trigger_drop = round(i * step_drop, 4)
        w = weights[i-1]
        
        grid = {
            "id": i,
            "amplitude_pct": round(profit_amp * 100, 2),
            "trigger_drop": trigger_drop,
            "weight": round(w, 4)
        }
        grids.append(grid)
        
    strategy = {
        "symbol": symbol,
        "leverage": 10, # Binance 默认 10x
        "stop_loss_pct": 0.08, 
        "best_period": f"{strategy_type}_fixed", 
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy_type": strategy_type,
        "grids": grids
    }
    
    return strategy

def run_backtest_all_periods(symbol="BTCUSDT"):
    # 全周期回测，获取1年数据 (逆序下载，先快后慢)
    periods = ["1d", "12h", "6h", "4h", "2h", "1h", "30m", "15m", "1m"] 
    results = {}
    best_period = None
    max_ret = -float('inf')
    
    print(f"   📊 正在执行 {symbol} 全周期回测 (Amplitude Distribution)...")
    
    for p in periods:
        # 获取 1 年数据
        days = 365
        df = fetch_binance_history(symbol, p, days)
        
        if df.empty:
            continue
            
        weights, metrics = analyze_strategy(df, leverage=10)
        total_adj_ret = metrics["total_adj_ret"]
        
        if total_adj_ret > max_ret:
            max_ret = total_adj_ret
            best_period = p
            
        # 格式化网格
        grids = []
        sorted_weights = sorted(weights.items(), key=lambda x: x[0])
        for amp, w in sorted_weights:
            if w < 0.001: continue
            grids.append({
                "id": amp,
                "amplitude_pct": amp,
                "weight": round(w, 4),
                "trigger_drop": amp / 100.0,
                "trigger_rise": amp / 100.0
            })
            
        results[p] = {
            "period": p,
            "total_adj_ret": round(total_adj_ret, 6),
            "sample_count": metrics["total_count"],
            "grids": grids
        }
        
    # 保存配置
    final_config = {
        "symbol": symbol,
        "leverage": 10,
        "stop_loss_pct": 0.08,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_period": best_period,
        "best_period_return": round(max_ret, 6),
        "strategy_type": "amplitude_distribution",
        "strategies": results
    }
    
    save_strategy_config(symbol, "amplitude_distribution", final_config)

def save_strategy_config(symbol, strategy_type, config):
    base_dir = os.path.join(os.path.dirname(__file__), "strategies")
    sub_dir = os.path.join(base_dir, strategy_type)
    os.makedirs(sub_dir, exist_ok=True)
    
    safe_symbol = symbol.replace('/', '')
    file_path = os.path.join(sub_dir, f"{safe_symbol}_{strategy_type}.json")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        
    print(f"   ✅ 已保存: {file_path}")
    
    # 顺便生成 README (如果是第一次)
    # 策略说明已统一到 strategies/README.md，不再单独生成
    pass

def create_readme(dir_path, strategy_type):
    # 已弃用，保留函数体为空或直接删除
    pass

def main():
    parser = argparse.ArgumentParser(description="Generate Binance Bot Strategies")
    parser.add_argument("--symbols", type=str, required=True, help="Comma-separated list of symbols (e.g., BTCUSDT,ETHUSDT)")
    
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",")]
    generate_strategies(symbols)

if __name__ == "__main__":
    main()
