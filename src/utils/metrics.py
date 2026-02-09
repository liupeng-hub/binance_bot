import pandas as pd
import numpy as np

def calculate_metrics(df, initial_capital=10000.0, risk_free_rate=0.0):
    """
    计算策略绩效指标
    
    Args:
        df: 包含 'datetime' 和 'value' (权益) 列的 DataFrame
        initial_capital: 初始资金
        risk_free_rate: 无风险利率 (年化)
    
    Returns:
        dict: 绩效指标
    """
    if df.empty:
        return {}

    # 1. 基础指标
    total_return = (df['value'].iloc[-1] - initial_capital) / initial_capital
    
    # 2. 收益序列
    df['returns'] = df['value'].pct_change().fillna(0)
    
    # 3. 夏普比率 (Sharpe Ratio)
    # 假设数据是日线的，如果是分钟线需要调整
    # 年化因子: 日线=252, 小时=252*24, 分钟=252*24*60
    # 这里简单假设日线
    annual_factor = 252 
    if len(df) > 1:
        mean_return = df['returns'].mean() * annual_factor
        std_return = df['returns'].std() * np.sqrt(annual_factor)
        sharpe = (mean_return - risk_free_rate) / std_return if std_return != 0 else 0
    else:
        sharpe = 0
        
    # 4. 最大回撤 (Max Drawdown)
    df['cummax'] = df['value'].cummax()
    df['drawdown'] = (df['cummax'] - df['value']) / df['cummax']
    max_drawdown = df['drawdown'].max()
    
    # 5. 胜率 (Win Rate)
    # 需要交易记录才能精确计算，这里仅基于日收益
    positive_days = len(df[df['returns'] > 0])
    total_days = len(df)
    win_rate = positive_days / total_days if total_days > 0 else 0
    
    return {
        "Total Return": f"{total_return:.2%}",
        "Sharpe Ratio": f"{sharpe:.2f}",
        "Max Drawdown": f"{max_drawdown:.2%}",
        "Win Rate (Daily)": f"{win_rate:.2%}"
    }

def analyze_trade_list(trades):
    """
    分析交易列表
    trades: list of dict {'pnl': 100, ...}
    """
    if not trades:
        return {}
        
    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    
    return {
        "Total Trades": len(trades),
        "Win Rate": f"{win_rate:.2%}",
        "Profit Factor": f"{profit_factor:.2f}",
        "Avg Win": f"{avg_win:.2f}",
        "Avg Loss": f"{avg_loss:.2f}"
    }
