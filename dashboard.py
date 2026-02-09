import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine
import os
import time
from streamlit_lightweight_charts import renderLightweightCharts
import glob

# 页面配置
st.set_page_config(
    page_title="Binance Bot Dashboard",
    page_icon="📊",
    layout="wide",
)

# 数据库连接
@st.cache_resource
def get_db_engine():
    # 假设数据库在 data/trades.db
    root_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(root_dir, 'data', 'trades.db')
    return create_engine(f'sqlite:///{db_path}')

engine = get_db_engine()

def load_data():
    try:
        trades = pd.read_sql("SELECT * FROM trades ORDER BY timestamp DESC", engine)
        equity = pd.read_sql("SELECT * FROM equity ORDER BY timestamp ASC", engine)
        
        # 显式转换为 datetime 对象，解决 SQLite 读取为 str 的问题
        if not trades.empty:
            trades['timestamp'] = pd.to_datetime(trades['timestamp'])
        if not equity.empty:
            equity['timestamp'] = pd.to_datetime(equity['timestamp'])
            
        return trades, equity
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

def load_kline_data(symbol):
    # 查找 data 目录下最新的 CSV 文件
    root_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(root_dir, 'data')
    safe_symbol = symbol.replace('/', '')
    
    # 优先查找 CSV
    pattern = os.path.join(data_dir, f"{safe_symbol}_*_*.csv")
    files = glob.glob(pattern)
    
    if not files:
        return pd.DataFrame()
        
    # 取最新的一个文件
    latest_file = max(files, key=os.path.getctime)
    
    try:
        df = pd.read_csv(latest_file)
        # 兼容不同的列名
        if 'datetime' in df.columns:
            df['time'] = pd.to_datetime(df['datetime'])
        elif 'timestamp' in df.columns: # Binance API raw data
             df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
             
        # 转换为 Unix Timestamp (seconds)
        df['time'] = df['time'].astype('int64') // 10**9 
        
        # 筛选所需列
        required_cols = ['time', 'open', 'high', 'low', 'close']
        if all(col in df.columns for col in required_cols):
             # 限制数据量，防止前端卡顿 (取最近 2000 根)
             return df[required_cols].tail(2000)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# 侧边栏
st.sidebar.title("🤖 控制台")
auto_refresh = st.sidebar.checkbox("自动刷新", value=True)
refresh_rate = st.sidebar.slider("刷新间隔 (秒)", 5, 60, 10)

# 主标题
st.title("📊 Binance Bot 实时监控")

# 加载数据
trades_df, equity_df = load_data()

if equity_df.empty:
    st.warning("暂无数据，请先启动交易机器人。")
else:
    # 1. 关键指标 (KPI)
    latest_equity = equity_df.iloc[-1]
    start_equity = equity_df.iloc[0]
    
    total_pnl = latest_equity['total_value'] - start_equity['total_value']
    pnl_pct = (total_pnl / start_equity['total_value']) * 100
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("当前净值 (USDT)", f"{latest_equity['total_value']:.2f}", f"{pnl_pct:.2f}%")
    col2.metric("可用现金", f"{latest_equity['cash']:.2f}")
    col3.metric("总交易次数", len(trades_df))
    col4.metric("运行时间", f"{(latest_equity['timestamp'] - start_equity['timestamp']).days} 天")

    # 2. 净值曲线图
    st.subheader("📈 账户净值曲线")
    fig = px.line(equity_df, x='timestamp', y='total_value', title='Total Equity Over Time')
    fig.update_layout(xaxis_title="时间", yaxis_title="净值 (USDT)")
    st.plotly_chart(fig, use_container_width=True)

    # 3. K线图与买卖点
    st.subheader("🕯️ 实时 K 线与买卖点")
    
    # 获取所有交易过的标的
    symbols = trades_df['symbol'].unique() if not trades_df.empty else ['BTC/USDT']
    selected_symbol = st.selectbox("选择标的", symbols)
    
    if selected_symbol:
        # --- 新增：分品种策略表现统计 ---
        symbol_trades = trades_df[trades_df['symbol'] == selected_symbol]
        
        if not symbol_trades.empty:
            # 仅统计已结平的交易 (PnL != 0 或明确标记)
            closed_trades = symbol_trades[symbol_trades['pnl'].notna() & (symbol_trades['pnl'] != 0)]
            
            if not closed_trades.empty:
                total_pnl = closed_trades['pnl'].sum()
                trade_count = len(closed_trades)
                win_count = len(closed_trades[closed_trades['pnl'] > 0])
                win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
                
                # 盈亏比
                gross_profit = closed_trades[closed_trades['pnl'] > 0]['pnl'].sum()
                gross_loss = abs(closed_trades[closed_trades['pnl'] < 0]['pnl'].sum())
                profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
                
                st.markdown(f"#### 📊 {selected_symbol} 策略收益统计")
                m1, m2, m3, m4 = st.columns(4)
                # 使用 delta_color="normal" 让正负数颜色自动显示 (绿/红)
                m1.metric("累计盈亏 (USDT)", f"{total_pnl:.2f}", delta=f"{total_pnl:.2f}") 
                m2.metric("胜率 (Win Rate)", f"{win_rate:.1f}%", f"{win_count}/{trade_count} 笔")
                m3.metric("盈亏比 (PF)", f"{profit_factor:.2f}")
                m4.metric("单笔平均", f"{total_pnl/trade_count:.2f}")
                st.divider()
            else:
                st.info(f"{selected_symbol} 暂无已结平收益 (当前可能仅有持仓)")
        
        # --- K线图渲染 ---
        kline_df = load_kline_data(selected_symbol)
        if not kline_df.empty:
            # 准备 Chart 数据
            candle_data = kline_df.to_dict('records')
            
            # 准备 Markers
            markers = []
            if not trades_df.empty:
                symbol_trades = trades_df[trades_df['symbol'] == selected_symbol]
                for _, t in symbol_trades.iterrows():
                    # 转换时间为 timestamp
                    ts = int(t['timestamp'].timestamp())
                    
                    # 简化颜色逻辑: BUY=Green, SELL=Red
                    # 注意: 这里假设 side 已经是 LONG/SHORT 或 BUY/SELL
                    # 我们根据 side 和 size 进一步推断开平
                    is_buy = t['side'] in ['LONG', 'BUY'] or (t['side'] == 'SHORT' and t['size'] > 0) # 逻辑可能需要根据实际记录调整
                    
                    # 更简单的逻辑：根据 Price 相对于前一笔？不，直接读 side
                    color = '#ef5350' if t['side'] in ['SHORT', 'SELL'] else '#26a69a'
                    text = f"{t['side']} @ {t['price']}"
                    shape = 'arrowDown' if color == '#ef5350' else 'arrowUp'
                    position = 'aboveBar' if color == '#ef5350' else 'belowBar'
                    
                    markers.append({
                        'time': ts,
                        'position': position,
                        'color': color,
                        'shape': shape,
                        'text': text
                    })
            
            # 配置图表
            chartOptions = {
                "layout": {
                    "textColor": 'black',
                    "background": {
                        "type": 'solid',
                        "color": 'white'
                    }
                },
                "height": 500
            }
            
            series = [
                {
                    "type": 'Candlestick',
                    "data": candle_data,
                    "options": {
                        "upColor": '#26a69a',
                        "downColor": '#ef5350',
                        "borderVisible": False,
                        "wickUpColor": '#26a69a',
                        "wickDownColor": '#ef5350'
                    },
                    "markers": markers
                }
            ]
            
            renderLightweightCharts([
                {
                    "chart": chartOptions,
                    "series": series
                }
            ], key='multi_chart')
            
        else:
            st.warning(f"未找到 {selected_symbol} 的历史数据文件")

    # 4. 交易记录与详情
    col_left, col_right = st.columns([2, 1])
    
    with col_left:
        st.subheader("📝 最近交易记录")
        if not trades_df.empty:
            # 格式化显示
            display_df = trades_df[['timestamp', 'symbol', 'side', 'price', 'size', 'pnl', 'strategy_id']].copy()
            st.dataframe(display_df, use_container_width=True, height=400)
        else:
            st.info("暂无交易记录")
            
    with col_right:
        st.subheader("📊 策略分布")
        if not trades_df.empty:
            strategy_counts = trades_df['strategy_id'].value_counts()
            fig_pie = px.pie(values=strategy_counts.values, names=strategy_counts.index, title="交易策略占比")
            st.plotly_chart(fig_pie, use_container_width=True)

# 自动刷新逻辑
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
