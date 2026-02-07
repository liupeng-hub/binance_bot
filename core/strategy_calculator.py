from collections import defaultdict

def analyze_strategy(df, leverage=10, fee_rate=0.0004):
    """
    策略分析逻辑
    fee_rate: 默认 0.04% (Binance Futures Taker)
    """
    print(f"正在分析策略表现 (杠杆: {leverage}x)...")
    
    # 1. 计算振幅 (High-Low)/Open
    df = df[df['open'] > 0].copy()
    df['amplitude'] = (df['high'] - df['low']) / df['open']
    
    total_count = len(df)
    if total_count == 0:
        return {}, {}
        
    # 2. 分桶统计
    # 桶 1: 0%~1%, 桶 2: 1%~2% ...
    bins = defaultdict(int)
    for amp in df['amplitude']:
        amp_pct = amp * 100
        # 简单分桶: 1% 一个台阶，最高 10%+
        if amp_pct >= 10:
            bin_idx = 10
        else:
            bin_idx = int(amp_pct) + 1
        bins[bin_idx] += 1
        
    # 3. 计算期望收益
    total_adj_ret = 0
    calculated_bins = []
    decay = 0.5 # 衰减因子
    
    for i in range(1, 11):
        count = bins[i]
        prob = count / total_count
        
        if i == 10:
            lev_return = -1.0 # 爆仓风险
        else:
            gross_return = (i / 100.0) * leverage
            # 扣除手续费 (基于名义价值)
            effective_fee = fee_rate * leverage * 2 # 双边
            net_return = gross_return - effective_fee
            
            # 如果利润不够覆盖手续费，则视为负收益
            if net_return < 0: net_return = -effective_fee
            lev_return = net_return
            
        exp_ret = lev_return * prob
        adj_ret = decay * exp_ret * prob
        
        calculated_bins.append({
            "amp_bin": i,
            "prob": prob,
            "adj_ret": adj_ret
        })
        
        if adj_ret > 0:
            total_adj_ret += adj_ret
            
    # 4. 生成权重
    strategy_weights = {}
    for item in calculated_bins:
        if item["adj_ret"] > 0:
            weight = item["adj_ret"] / total_adj_ret if total_adj_ret > 0 else 0
            strategy_weights[item["amp_bin"]] = weight
            
    metrics = {
        "total_adj_ret": total_adj_ret,
        "total_count": total_count,
        "strategy_weights": strategy_weights
    }
    
    return strategy_weights, metrics
