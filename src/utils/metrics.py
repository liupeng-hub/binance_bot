import pandas as pd
import numpy as np

def calculate_metrics(df, initial_capital=10000.0, risk_free_rate=0.0, annual_factor=252*24):
    """
    计算策略绩效指标 (升级版)
    
    Args:
        df: 包含 'datetime' 和 'value' (权益) 列的 DataFrame
        initial_capital: 初始资金
        risk_free_rate: 无风险利率 (年化)
        annual_factor: 年化因子 (日线=252, 小时=252*24, 分钟=252*24*60)
    
    Returns:
        dict: 绩效指标
    """
    if df.empty:
        return {}

    # 1. 基础指标
    final_value = df['value'].iloc[-1]
    net_profit = final_value - initial_capital
    total_return = net_profit / initial_capital
    
    # 2. 收益序列
    df['returns'] = df['value'].pct_change().fillna(0)
    
    # 3. 风险调整收益
    if len(df) > 1:
        mean_return = df['returns'].mean() * annual_factor
        std_return = df['returns'].std() * np.sqrt(annual_factor)
        
        # Sharpe Ratio
        sharpe = (mean_return - risk_free_rate) / std_return if std_return != 0 else 0
        
        # Sortino Ratio (只考虑下行波动)
        downside_returns = df.loc[df['returns'] < 0, 'returns']
        std_downside = downside_returns.std() * np.sqrt(annual_factor)
        sortino = (mean_return - risk_free_rate) / std_downside if std_downside != 0 else 0
    else:
        sharpe = 0
        sortino = 0
        
    # 4. 最大回撤 (Max Drawdown)
    df['cummax'] = df['value'].cummax()
    df['drawdown'] = (df['cummax'] - df['value']) / df['cummax']
    max_drawdown = df['drawdown'].max()
    
    # Calmar Ratio (年化收益 / 最大回撤)
    calmar = mean_return / max_drawdown if max_drawdown != 0 else 0
    
    return {
        "net_profit": net_profit,
        "total_return": total_return,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "max_drawdown": max_drawdown,
        "volatility": std_return if 'std_return' in locals() else 0,
        "final_value": final_value
    }

def analyze_trade_list(trades):
    """
    分析交易列表
    trades: list of dict {'pnl': 100, ...}
    """
    if not trades:
        return {}
        
    pnls = [t.pnl if hasattr(t, 'pnl') else t.get('pnl', 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    
    # Kelly Criterion (Simple)
    # f = p - q / b (p=win_rate, q=loss_rate, b=odds)
    # b = avg_win / abs(avg_loss)
    if avg_loss != 0:
        b = avg_win / abs(avg_loss)
        q = 1 - win_rate
        kelly = win_rate - (q / b)
    else:
        kelly = 0
    
    return {
        "total_trades": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "kelly_criterion": max(0, kelly) # Kelly typically bounded at 0
    }
