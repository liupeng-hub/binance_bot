import streamlit as st
import pandas as pd
import plotly.express as px
import hashlib
import json
import uuid
import os
import sys
import time
import glob
import html
from streamlit_lightweight_charts import renderLightweightCharts
from src.utils.data_helper import load_kline_data, calculate_indicators

# 添加 src 到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

from src.utils.db_manager import db_manager
from src.utils.db_models import User, ExchangeConfig, StrategyInstance, TradeRecord, EquityRecord, OptimizationJob
from src.utils.strategy_loader import StrategyLoader
from src.utils.process_manager import process_manager

# 页面配置
st.set_page_config(page_title="Quant SaaS Platform", layout="wide", page_icon="🚀")

# 初始化数据库 (确保表存在)
db_manager.init_db()

# 初始化 Session State
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'role' not in st.session_state:
    st.session_state.role = None
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'user'
if 'expanded_instances' not in st.session_state:
    st.session_state.expanded_instances = set()

from datetime import timezone, timedelta

# --- 缓存优化 ---
@st.cache_data(ttl=60)
def get_kline_data(symbol, start_ts=None, end_ts=None, timeframe=None):
    return load_kline_data(symbol, start_ts, end_ts, timeframe=timeframe)

@st.cache_data
def get_indicators(df, strategy_name, config_json):
    return calculate_indicators(df, strategy_name, config_json)

# --- 策略加载器缓存 ---
# 使用 cache_resource 缓存 Loader 实例，但可以通过 clear_cache 强制刷新
@st.cache_resource
def get_strategy_loader():
    return StrategyLoader(os.path.join(current_dir, 'src', 'strategies'))

def reload_strategies():
    st.cache_resource.clear()
    st.success("策略库已重新加载！")

# --- 认证模块 ---
def login_page():
    st.markdown("""
    <div style='text-align: center;'>
        <h1>🔐 Quant SaaS Platform</h1>
        <p>Professional Multi-Tenant Quantitative Trading System</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                session = db_manager.get_session()
                user = session.query(User).filter_by(username=username).first()
                if user:
                    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
                    if user.password_hash == pwd_hash:
                        st.session_state.user_id = user.id
                        st.session_state.role = user.role
                        st.session_state.username = user.username
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error("Invalid password")
                else:
                    st.error("User not found")
                session.close()
    
    st.markdown("---")
    with st.expander("Create new account"):
        new_user = st.text_input("New Username")
        new_pass = st.text_input("New Password", type="password")
        if st.button("Register"):
            session = db_manager.get_session()
            if session.query(User).filter_by(username=new_user).first():
                st.error("Username already exists")
            else:
                pwd_hash = hashlib.sha256(new_pass.encode()).hexdigest()
                new_user_obj = User(username=new_user, password_hash=pwd_hash)
                session.add(new_user_obj)
                session.commit()
                st.success("Registered! Please login.")
            session.close()

# --- 用户功能模块 ---
def user_settings():
    st.header("🔑 Exchange Configuration")
    st.info("Your API Keys are encrypted and stored securely.")
    
    with st.form("config_form"):
        api_key = st.text_input("Binance API Key", type="password")
        secret_key = st.text_input("Binance Secret Key", type="password")
        submitted = st.form_submit_button("Save Configuration")
        
        if submitted:
            session = db_manager.get_session()
            config = session.query(ExchangeConfig).filter_by(user_id=st.session_state.user_id).first()
            if not config:
                config = ExchangeConfig(user_id=st.session_state.user_id)
                session.add(config)
                
            config.api_key_enc = db_manager.encrypt_secret(api_key)
            config.secret_key_enc = db_manager.encrypt_secret(secret_key)
            session.commit()
            st.success("Configuration saved!")
            session.close()

import psutil
from datetime import timezone

def instance_monitor():
    st.subheader("📡 运行中实例")
    session = db_manager.get_session()
    instances = session.query(StrategyInstance).filter_by(user_id=st.session_state.user_id).order_by(StrategyInstance.created_at.desc()).all()
    
    if not instances:
        st.info("暂无运行实例。请在上方创建。")
    else:
        # Load strategies for display names
        loader = get_strategy_loader()
        strategies = loader.load_strategies()

        # 添加自动刷新机制 (降低频率到 5 秒)
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=5000, limit=None, key="instance_monitor_refresh")
        
        # 添加手动刷新按钮
        if st.button("🔄 立即刷新状态", key="refresh_instances"):
            st.rerun()
        
        for inst in instances:
            # 1. 自动状态检查
            if inst.status == 'RUNNING':
                if inst.pid and not psutil.pid_exists(inst.pid):
                    inst.status = 'COMPLETED'
                    inst.pid = None
                    session.commit()
            
            # --- 布局重构 (v4) ---
            with st.container():
                # 定义列宽: [模式, 信息, 状态, 盈亏, 操作, 详情]
                # 垂直方向改为 top 对齐 (默认)
                cols = st.columns([0.8, 3, 1.2, 2, 2.5, 1])
                
                # 1. 模式 (Badge)
                with cols[0]:
                    if inst.mode == 'live':
                        st.markdown(":red[**[实盘]**]")
                    else:
                        st.markdown(":blue[**[回测]**]")
                
                # 2. 信息 (Symbol + Strategy / ID)
                with cols[1]:
                    # 获取中文策略名
                    strat_info = strategies.get(inst.strategy_name, {})
                    display_name = strat_info.get('display_name', inst.strategy_name)
                    
                    st.markdown(f"**{inst.symbol}** · `{display_name}`")
                    
                    # 解析配置获取参数
                    param_info = ""
                    sys_info = ""
                    try:
                        cfg = json.loads(inst.config_json)
                        # 1. 策略参数
                        params = cfg.get('params', {})
                        if params:
                            p_items = []
                            for k, v in params.items():
                                if isinstance(v, (int, float)) or (isinstance(v, str) and len(v) < 10):
                                    p_items.append(f"{k}={v}")
                            param_info = ", ".join(p_items)
                        
                        # 2. 系统配置
                        sys_cfg = cfg.get('sys', {})
                        if sys_cfg:
                            s_items = []
                            # 过滤掉一些不重要的显示
                            for k, v in sys_cfg.items():
                                if k in ['timeframe', 'capital', 'days']:
                                    s_items.append(f"{k}={v}")
                            sys_info = ", ".join(s_items)
                    except:
                        pass
                        
                    # short_id = inst.id.split('-')[0]
                    
                    # 紧凑分行显示 (使用 HTML)
                    html_info = f"""
                    <div style="line-height: 1.2; font-size: 0.8em; color: #666;">
                        <div><b>ID</b>: {inst.id}</div>
                    """
                    if sys_info:
                        html_info += f"<div><b>Sys</b>: {sys_info}</div>"
                    if param_info:
                        html_info += f"<div><b>Params</b>: {param_info}</div>"
                    html_info += "</div>"
                    
                    st.markdown(html_info, unsafe_allow_html=True)

                # 3. 状态/进度
                with cols[2]:
                    # 强制刷新状态
                    session.refresh(inst)
                    
                    if inst.status == 'RUNNING':
                        if inst.mode == 'backtest':
                             # 纯数字进度
                             prog = inst.progress if inst.progress is not None else 0.0
                             st.markdown(f"**{prog:.1f}%**")
                        else:
                             st.markdown("🟢 **运行中**")
                    elif inst.status == 'COMPLETED':
                        st.markdown(":green[**✅ 完成**]")
                    elif inst.status == 'STOPPED':
                        st.markdown(":red[**⛔ 停止**]")
                    else:
                        st.markdown(f"**⚠️ {inst.status}**")

                # 4. 盈亏 (PnL)
                with cols[3]:
                    # 查询最新净值
                    latest_eq = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.desc()).first()
                    
                    if latest_eq:
                        # 尝试获取初始资金
                        initial_capital = 10000000.0 # Default
                        try:
                            cfg = json.loads(inst.config_json)
                            # 兼容新旧结构
                            if 'sys' in cfg:
                                initial_capital = float(cfg['sys'].get('capital', 10000000.0))
                            elif 'capital' in cfg:
                                initial_capital = float(cfg['capital'])
                        except:
                            pass
                            
                        current_val = latest_eq.total_value
                        pnl_val = current_val - initial_capital
                        roi = (pnl_val / initial_capital) * 100.0
                        
                        color = "green" if pnl_val >= 0 else "red"
                        sign = "+" if pnl_val >= 0 else ""
                        # 合并显示在一行
                        st.markdown(f":{color}[**${current_val:,.0f}**   ({sign}{roi:.2f}%) ]")
                        
                        # --- P0: 显示核心指标 (如果存在) ---
                        if inst.metrics_json:
                            try:
                                metrics = json.loads(inst.metrics_json)
                                max_dd = metrics.get('max_drawdown', 0.0)
                                win_rate = metrics.get('win_rate', 0.0)
                                st.caption(f"最大回撤: {max_dd:.2f}% | 胜率: {win_rate:.1%}")
                            except:
                                pass
                        # -------------------------------
                    else:
                        st.markdown("-")

                # 5. 操作区
                with cols[4]:
                    if inst.status == 'RUNNING':
                        if st.button("⏹ 停止", key=f"stop_{inst.id}", use_container_width=True):
                            process_manager.stop_instance(inst.id)
                            st.rerun()
                    elif inst.status in ['STOPPED', 'ERROR', 'COMPLETED', 'PENDING']:
                        c_start, c_del = st.columns(2)
                        if c_start.button("▶ 启动", key=f"start_{inst.id}", use_container_width=True):
                            process_manager.start_instance(inst.id)
                            st.rerun()
                        if c_del.button("🗑 删除", key=f"del_{inst.id}", use_container_width=True):
                            session.delete(inst)
                            session.commit()
                            st.rerun()

                # 6. 详情开关
                with cols[5]:
                    is_expanded = inst.id in st.session_state.expanded_instances
                    btn_label = "🔼 收起" if is_expanded else "📉 详情"
                    if st.button(btn_label, key=f"detail_{inst.id}", use_container_width=True):
                        if is_expanded:
                            st.session_state.expanded_instances.remove(inst.id)
                        else:
                            st.session_state.expanded_instances.add(inst.id)
                        st.rerun()

            # --- 详情面板 (条件渲染) ---
            if inst.id in st.session_state.expanded_instances:
                with st.container():
                     st.divider()
                     # Tabs
                     tabs = st.tabs(["📊 K线与信号", "💲 资金与持仓", "📋 交易记录", "📜 实时日志"])
                     
                     # Tab 1: K-Line
                     with tabs[0]:
                        # 1. 先获取交易记录，用于确定时间范围
                        trades = session.query(TradeRecord).filter_by(instance_id=inst.id).all()
                        
                        # 2. 计算时间范围
                        start_ts = None
                        end_ts = None
                        target_timeframe = None
                        
                        if trades:
                            # 如果有交易，使用交易时间范围 (前后各扩充 2 天)
                            ts_list = [t.timestamp.replace(tzinfo=timezone.utc).timestamp() for t in trades]
                            if ts_list:
                                start_ts = min(ts_list) - 86400 * 2
                                end_ts = max(ts_list) + 86400 * 2
                                
                        # 尝试获取配置中的 timeframe
                        try:
                            cfg = json.loads(inst.config_json)
                            target_timeframe = cfg.get('sys', {}).get('timeframe')
                            
                            # 如果没有交易记录，使用回测配置计算时间范围
                            if inst.mode == 'backtest' and not trades:
                                days = int(cfg.get('sys', {}).get('days', 30))
                                end_dt = inst.created_at.replace(tzinfo=timezone.utc)
                                start_dt = end_dt - timedelta(days=days + 5)
                                end_ts = end_dt.timestamp()
                                start_ts = start_dt.timestamp()
                        except:
                            pass
                                
                        # 3. 获取 K 线数据 (传入 timeframe 以精确匹配文件)
                        # 如果是实盘且没有交易记录，也应该尝试加载数据
                        # 默认加载最近 1 天的数据
                        if inst.mode == 'live' and start_ts is None:
                            now = time.time()
                            start_ts = now - 86400 * 1 # 1 day
                            end_ts = now
                            
                        kline_df = get_kline_data(inst.symbol, start_ts, end_ts, timeframe=target_timeframe)
                        
                        if not kline_df.empty:
                            candle_data = kline_df.to_dict('records')
                            
                            markers = []
                            # 检查是否有新版成交记录 (BUY/SELL)
                            has_orders = any(t.side in ['BUY', 'SELL'] for t in trades)
                            
                            for t in trades:
                                # 过滤逻辑：如果有新版 Order 记录，则忽略旧版 Trade 结算记录，避免图表混乱
                                if has_orders and t.side in ['LONG', 'SHORT', 'ROUNDTRIP_LONG', 'ROUNDTRIP_SHORT']:
                                    continue
                                    
                                color = '#ef5350' if t.side in ['SHORT', 'SELL'] else '#26a69a'
                                text = f"{t.side} @ {t.price}"
                                shape = 'arrowDown' if color == '#ef5350' else 'arrowUp'
                                position = 'aboveBar' if color == '#ef5350' else 'belowBar'
                                # 关键修复: 确保 timestamp 为 UTC 时间戳
                                ts = t.timestamp.replace(tzinfo=timezone.utc).timestamp()
                                markers.append({'time': int(ts), 'position': position, 'color': color, 'shape': shape, 'text': text})
                                
                            chartOptions = {
                                "layout": {"textColor": 'black', "background": {"type": 'solid', "color": 'white'}}, 
                                "height": 400,
                                "crosshair": {
                                    "mode": 0,
                                    "vertLine": {
                                        "visible": True,
                                        "labelVisible": True,
                                        "color": '#555555',
                                        "width": 1,
                                        "style": 3, # Dashed
                                        "labelBackgroundColor": '#555555'
                                    },
                                    "horzLine": {
                                        "visible": True,
                                        "labelVisible": True,
                                        "color": '#555555',
                                        "width": 1,
                                        "style": 3,
                                        "labelBackgroundColor": '#555555'
                                    }
                                },
                                "grid": {
                                    "vertLines": {"color": '#f0f3fa'},
                                    "horzLines": {"color": '#f0f3fa'},
                                },
                                "timeScale": {
                                    "visible": True,
                                    "timeVisible": True,
                                    "secondsVisible": False
                                }
                            }
                            
                            # 计算指标
                            main_overlays, sub_charts_data = get_indicators(kline_df.copy(), inst.strategy_name, inst.config_json)
                            
                            main_series = [{
                                "type": 'Candlestick', 
                                "data": candle_data, 
                                "options": {"upColor": '#26a69a', "downColor": '#ef5350', "borderVisible": False, "wickUpColor": '#26a69a', "wickDownColor": '#ef5350'}, 
                                "markers": markers
                            }] + main_overlays # 添加主图指标
                            
                            charts_to_render = [{"chart": chartOptions, "series": main_series}]
                            
                            # 处理副图
                            for sub in sub_charts_data:
                                sub_chart_options = {
                                    "layout": {"textColor": 'black', "background": {"type": 'solid', "color": 'white'}}, 
                                    "height": sub.get('height', 150),
                                    "crosshair": {
                                        "mode": 0,
                                        "vertLine": {
                                            "visible": True,
                                            "labelVisible": True,
                                            "color": '#555555',
                                            "width": 1,
                                            "style": 3,
                                        },
                                        "horzLine": {
                                            "visible": True,
                                            "labelVisible": True,
                                            "color": '#555555',
                                            "width": 1,
                                            "style": 3,
                                            "labelBackgroundColor": '#555555'
                                        }
                                    },
                                    "grid": {
                                        "vertLines": {"color": '#f0f3fa'},
                                        "horzLines": {"color": '#f0f3fa'},
                                    },
                                    "timeScale": {
                                        "visible": True,
                                        "timeVisible": True,
                                        "secondsVisible": False
                                    }
                                }
                                charts_to_render.append({
                                    "chart": sub_chart_options,
                                    "series": sub['series']
                                })
                            
                            renderLightweightCharts(charts_to_render, key=f"chart_{inst.id}")
                        else:
                            st.warning("暂无 K 线数据 (实例可能正在初始化)")

                     # Tab 2: Equity & Position
                     with tabs[1]:
                        equity_recs = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.asc()).all()
                        if equity_recs:
                            df_eq = pd.DataFrame([{
                                'Time': e.timestamp, 
                                'Total': e.total_value, 
                                'Cash': e.cash,
                                'Value': e.total_value - e.cash
                            } for e in equity_recs])
                            
                            col_eq1, col_eq2 = st.columns([2, 1])
                            
                            with col_eq1:
                                st.subheader("📈 资金曲线")
                                # 绘制资金曲线
                                fig = px.line(df_eq, x='Time', y='Total', title='总资产净值 (USDT)')
                                fig.update_layout(height=350)
                                st.plotly_chart(fig, use_container_width=True, key=f"equity_chart_{inst.id}")
                                
                            with col_eq2:
                                st.subheader("🍰 当前持仓")
                                if not df_eq.empty:
                                    latest = df_eq.iloc[-1]
                                    pos_val = max(0, latest['Value']) # 避免负数
                                    cash_val = max(0, latest['Cash'])
                                    
                                    df_alloc = pd.DataFrame({
                                        'Asset': ['Cash (USDT)', 'Position Value'],
                                        'Value': [cash_val, pos_val]
                                    })
                                    fig_pie = px.pie(df_alloc, values='Value', names='Asset', hole=0.4)
                                    fig_pie.update_layout(height=350, showlegend=True)
                                    st.plotly_chart(fig_pie, use_container_width=True, key=f"pos_pie_{inst.id}")
                                    
                                    st.metric("当前净值", f"${latest['Total']:.2f}")
                                    st.metric("当前现金", f"${latest['Cash']:.2f}")
                        else:
                            st.info("暂无资金记录 (请等待策略运行一段时间)")

                     # Tab 3: History
                     with tabs[2]:
                        trades_q = session.query(TradeRecord).filter_by(instance_id=inst.id).order_by(TradeRecord.timestamp.desc()).all()
                        if trades_q:
                            # 分离 RoundTrip 和 Order
                            round_trips = []
                            orders = []
                            for t in trades_q:
                                if t.side in ['LONG', 'SHORT', 'ROUNDTRIP_LONG', 'ROUNDTRIP_SHORT']:
                                    round_trips.append(t)
                                else:
                                    orders.append(t)
                            
                            processed_rows = []
                            rt_map = {} # order_id (trade_ref) -> info

                            # 1. 处理 RoundTrips，建立组
                            from dateutil import parser
                            
                            for rt in round_trips:
                                # 尝试解析额外数据中的精确时间
                                open_dt = None
                                close_dt = None
                                try:
                                    extra = json.loads(rt.extra_data) if rt.extra_data else {}
                                    if 'open_dt' in extra:
                                        open_dt = parser.parse(extra['open_dt'])
                                    if 'close_dt' in extra:
                                        close_dt = parser.parse(extra['close_dt'])
                                except:
                                    pass
                                
                                # 兜底：如果没有 open_dt，使用 rt.timestamp 作为 close_dt
                                if not close_dt:
                                    close_dt = rt.timestamp
                                
                                rt_map[rt.order_id] = {
                                    'obj': rt,
                                    'open_dt': open_dt,
                                    'close_dt': close_dt
                                }
                                
                                processed_rows.append({
                                    'raw': rt,
                                    'Type': "交易盈亏 (RoundTrip)",
                                    'TradeID': rt.order_id,
                                    'sort_time': rt.timestamp,
                                    'is_header': True
                                })

                            # 2. 处理 Orders 并关联
                            for o in orders:
                                group_id = "-"
                                
                                # 尝试时间匹配
                                # Order 时间 o.timestamp
                                # 检查是否在某个 RT 的 [open_dt, close_dt] 范围内
                                matched_rt_id = None
                                
                                # 优先检查 explicit map (如果将来修复了 bt_db_analyzer)
                                # ...
                                
                                # 时间匹配 fallback
                                if matched_rt_id is None:
                                    for rid, info in rt_map.items():
                                        # 容差匹配：精确到秒
                                        # 如果 open_dt 存在
                                        if info['open_dt'] and info['close_dt']:
                                            # 放宽一点点容差 (e.g. 1秒) 避免浮点误差
                                            if (info['open_dt'] - timedelta(seconds=1)) <= o.timestamp <= (info['close_dt'] + timedelta(seconds=1)):
                                                matched_rt_id = rid
                                                break
                                        elif info['close_dt']:
                                            # 只有 close_dt (旧数据?)
                                            if abs((o.timestamp - info['close_dt']).total_seconds()) < 5:
                                                matched_rt_id = rid
                                                break

                                if matched_rt_id:
                                    group_id = matched_rt_id
                                
                                processed_rows.append({
                                    'raw': o,
                                    'Type': "委托成交 (Order)",
                                    'TradeID': group_id,
                                    'sort_time': o.timestamp,
                                    'is_header': False
                                })
                            
                            # 3. 构建 DataFrame 并排序
                            df_temp = pd.DataFrame(processed_rows)
                            
                            if not df_temp.empty:
                                # 计算每个 Group 的最大时间 (用于组排序)
                                # 注意：Orphan orders (ID='-') 可能会干扰，暂时将 '-' 视为单独的组
                                group_max_time = df_temp.groupby('TradeID')['sort_time'].max()
                                df_temp['group_sort_key'] = df_temp['TradeID'].map(group_max_time)
                                
                                # 排序逻辑:
                                # 1. 组时间 (Asc) -> Group ID 小的（早的）在前面
                                # 2. 组ID (Asc) -> 辅助排序
                                # 3. 组内排序: 按时间正序 (Entry -> Exit -> Summary)
                                #    Header 时间通常等于 Exit 时间。
                                #    若时间相同，通过 is_header (Asc) 让 Order (0) 排在 Header (1) 前面
                                
                                df_temp = df_temp.sort_values(
                                    by=['group_sort_key', 'TradeID', 'sort_time', 'is_header'],
                                    ascending=[True, True, True, True]
                                )
                                
                                # 4. 生成显示列
                                data_list = []
                                row_styles = [] # 存储行样式
                                
                                # 颜色映射
                                unique_groups = [g for g in df_temp['TradeID'].unique() if g != '-']
                                group_color_idx = {gid: i for i, gid in enumerate(unique_groups)}
                                
                                # 重置索引以确保 row.name 与 list index 一致
                                df_temp = df_temp.reset_index(drop=True)
                                
                                for idx, row in df_temp.iterrows():
                                    t = row['raw']
                                    
                                    # 确定颜色
                                    bg_color = ''
                                    if row['TradeID'] != '-':
                                        c_idx = group_color_idx.get(row['TradeID'], 0)
                                        if c_idx % 2 == 0:
                                            bg_color = 'background-color: #f5f5f5' # 浅灰
                                        else:
                                            bg_color = 'background-color: #ffffff' # 白
                                    else:
                                         bg_color = 'background-color: #ffffff'
                                    
                                    # 如果是 RoundTrip 行，使用浅蓝高亮
                                    if row['is_header']:
                                        bg_color = 'background-color: #e3f2fd' # 浅蓝
                                    
                                    # 强制设置黑色字体以适应浅色背景 (解决夜间模式看不清的问题)
                                    style_str = f"{bg_color}; color: black" if bg_color else "color: black"
                                    row_styles.append(style_str)
                                    
                                    data_list.append({
                                        '时间': t.timestamp,
                                        '标的': t.symbol,
                                        '方向': t.side,
                                        '价格': t.price,
                                        '数量': t.size,
                                        '盈亏': t.pnl,
                                        '记录类型': row['Type'],
                                        '交易组ID': row['TradeID']
                                    })
                                
                                df_display = pd.DataFrame(data_list)
                                
                                # 筛选器
                                c1, c2 = st.columns([2, 1])
                                with c1:
                                    type_filter = st.multiselect(
                                        "筛选记录类型", 
                                        options=df_display['记录类型'].unique(),
                                        default=df_display['记录类型'].unique(),
                                        key=f"filter_{inst.id}" # 添加唯一 key
                                    )
                                
                                if type_filter:
                                    # 筛选后索引会变，需要重新对齐样式
                                    # 为了样式对齐，我们不再把样式放入 df，而是通过索引查找
                                    
                                    # 先保存 style 字典： index -> style_str
                                    style_map = {i: s for i, s in zip(df_display.index, row_styles)}
                                    
                                    df_final = df_display[df_display['记录类型'].isin(type_filter)].copy()
                                else:
                                    style_map = {i: s for i, s in zip(df_display.index, row_styles)}
                                    df_final = df_display.copy()

                                # 样式应用函数 (通过 index 查找)
                                def style_rows(row):
                                    # 使用 row.name (即 index) 查找样式
                                    s = style_map.get(row.name, "")
                                    return [s] * len(row)

                                # 1. 应用样式
                                styler = df_final.style.format({
                                    '价格': '{:.4f}',
                                    '数量': '{:.4f}',
                                    '盈亏': '{:.2f}'
                                }).apply(style_rows, axis=1)
                                
                                # 3. 渲染 (不再需要 hide _style)
                                st.dataframe(
                                    styler,
                                    use_container_width=True
                                )
                            else:
                                st.info("暂无交易记录")
                        else:
                            st.info("暂无交易记录")

                     # Tab 4: Log
                     with tabs[3]:
                        if inst.log_path and os.path.exists(inst.log_path):
                            with open(inst.log_path, 'r') as f:
                                lines = f.readlines()
                                # 增加 max-height 和 overflow-y 实现滚动
                                # 解析结构化日志
                                parsed_lines = []
                                for line in lines[-500:]:
                                    try:
                                        log_obj = json.loads(line)
                                        # 格式化: [TIME] [LEVEL] [SYMBOL] MESSAGE
                                        ts = log_obj.get('timestamp', '')
                                        lvl = log_obj.get('level', 'INFO')
                                        sym = log_obj.get('symbol', '-')
                                        msg = log_obj.get('message', '')
                                        
                                        # 简单的颜色高亮
                                        color = "#d4d4d4" # default
                                        if lvl == 'ERROR': color = "#ff5252"
                                        elif lvl == 'WARNING': color = "#ffb74d"
                                        elif lvl == 'ORDER': color = "#69f0ae"
                                        elif lvl == 'TRADE': color = "#40c4ff"
                                        
                                        formatted_line = f'<span style="color:{color}">[{ts}] [{lvl}] [{sym}] {html.escape(msg)}</span>'
                                        parsed_lines.append(formatted_line)
                                    except json.JSONDecodeError:
                                        # Fallback for old logs
                                        parsed_lines.append(html.escape(line.strip()))
                                
                                log_content = "<br>".join(parsed_lines)
                                
                                st.markdown(f"""
                                <div style="max-height: 400px; overflow-y: auto; background-color: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; font-size: 0.85em; line-height: 1.4;">
                                {log_content}
                                </div>
                                """, unsafe_allow_html=True)
                        else:
                            st.info("未找到日志文件")
                     
                     st.divider() # Bottom divider
                        
    session.close()

def trading_desk():
    try:
        st.header("🖥️ 量化交易工作台")
        
        # --- Part 0: Debug Info (Temporary, Moved to Top) ---
        with st.expander("🐞 Debug Console (系统日志)", expanded=True):
            log_dir = os.path.join(current_dir, 'logs', 'instances')
            if os.path.exists(log_dir):
                log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
                if log_files:
                    latest_log = log_files[0]
                    st.write(f"最新日志: `{os.path.basename(latest_log)}`")
                    try:
                        with open(latest_log, 'r') as f:
                            # 只读取最后 20 行
                            lines = f.readlines()[-20:]
                            st.code("".join(lines), language='text')
                    except Exception as e:
                        st.error(f"无法读取日志: {e}")
                else:
                    st.info("暂无日志文件")
            else:
                st.warning("日志目录不存在")
        
        # --- Part 0.5: API Settings (Merged) ---
        with st.expander("🔑 交易所配置 (API Key)", expanded=False):
            st.info("您的 API Key 将被加密存储，仅用于实盘接入。")
            with st.form("config_form"):
                api_key = st.text_input("Binance API Key", type="password")
                secret_key = st.text_input("Binance Secret Key", type="password")
                submitted = st.form_submit_button("保存配置")
                
                if submitted:
                    session = db_manager.get_session()
                    config = session.query(ExchangeConfig).filter_by(user_id=st.session_state.user_id).first()
                    if not config:
                        config = ExchangeConfig(user_id=st.session_state.user_id)
                        session.add(config)
                        
                    config.api_key_enc = db_manager.encrypt_secret(api_key)
                    config.secret_key_enc = db_manager.encrypt_secret(secret_key)
                    session.commit()
                    st.success("配置已保存！")
                    session.close()

        # --- Part 1: Strategy Launcher (可折叠) ---
        with st.expander("➕ 创建新策略实例", expanded=False):
            # Load Strategies
            # loader = StrategyLoader(os.path.join(current_dir, 'src', 'strategies'))
            loader = get_strategy_loader()
            strategies = loader.load_strategies()
            
            # 添加刷新按钮
            if st.button("🔄 刷新策略列表", help="如果上传了新策略文件，点击此按钮加载"):
                reload_strategies()
                st.rerun()
            
            col1, col2, col3 = st.columns(3)
            
            # 使用 format_func 显示中文名称
            def strategy_formatter(name):
                return strategies[name].get('display_name', name)
            
            # --- 自动填充逻辑 ---
            default_strat_idx = 0
            default_symbol = "BTC/USDT"
            
            applied = st.session_state.get('applied_opt_config')
            if applied:
                # 尝试匹配策略索引
                s_keys = list(strategies.keys())
                if applied['strategy'] in s_keys:
                    default_strat_idx = s_keys.index(applied['strategy'])
                default_symbol = applied.get('symbol', "BTC/USDT")
                # 可以在这里显示一个提示
                st.info(f"✨ 已自动加载优选参数 (来自策略 {applied['strategy']})")
            
            strategy_name = col1.selectbox(
                "选择策略", 
                list(strategies.keys()),
                index=default_strat_idx,
                format_func=strategy_formatter
            )
            
            symbol = col2.text_input("交易标的 (e.g. BTC/USDT)", default_symbol)
            mode = col3.selectbox("执行模式", ["模拟回测", "实盘接入"], help="模拟回测使用历史数据。实盘接入连接交易所（目前为模拟环境）。")
            mode_val = 'backtest' if mode == '模拟回测' else 'live'
            
            # 显示策略说明
            if strategy_name:
                desc = strategies[strategy_name].get('algo_description')
                if not desc:
                    # Fallback to docstring if no explicit description
                    desc = strategies[strategy_name].get('doc')
                
                if desc:
                    with st.expander("📖 策略说明", expanded=False):
                        st.markdown(desc)

            # Dynamic Params Form
            if strategy_name:
                params = strategies[strategy_name]['params']
                p_config = strategies[strategy_name].get('params_config', {})
                
                # --- 应用优选参数 ---
                # 如果当前选择的策略与应用的策略一致，则覆盖默认值
                applied_params = {}
                if applied and applied['strategy'] == strategy_name:
                    applied_params = applied.get('params', {})
                
                config = {}
                st.subheader("⚙️ 策略参数")
                
                p_cols = st.columns(3)
                i = 0
                for key, val in params.items():
                    col = p_cols[i % 3]
                    with col:
                        # 获取显示名称和帮助信息
                        label = key
                        help_text = None
                        if key in p_config:
                            label = p_config[key].get('label', key)
                            help_text = p_config[key].get('help', None)
                        
                        # 优先使用 applied_params 中的值
                        default_val = applied_params.get(key, val)
                        
                        if isinstance(val, int):
                            config[key] = st.number_input(label, value=int(default_val), step=1, help=help_text, key=f"p_{key}")
                        elif isinstance(val, float):
                            config[key] = st.number_input(label, value=float(default_val), format="%.4f", help=help_text, key=f"p_{key}")
                        else:
                            config[key] = st.text_input(label, value=str(default_val), help=help_text, key=f"p_{key}")
                    i += 1
                
                st.divider()
                st.markdown("#### ⚙️ 系统配置")
                # New Row for System Config
                c1, c2, c3 = st.columns(3)
                
                # 系统参数默认值
                def_tf_idx = 5 # 1h
                def_days = 30
                def_cap = 10000000.0
                
                if applied:
                    sys_app = applied.get('sys', {})
                    tfs = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
                    if sys_app.get('timeframe') in tfs:
                        def_tf_idx = tfs.index(sys_app.get('timeframe'))
                    def_days = int(sys_app.get('days', 30))
                    def_cap = float(sys_app.get('capital', 10000000.0))
                
                timeframe = c1.selectbox("K线周期", ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"], index=def_tf_idx)
                days = c2.number_input("历史天数", min_value=1, value=def_days)
                capital = c3.number_input("初始资金 (USDT)", min_value=100.0, value=def_cap, step=10000.0)
                    
                if st.button("🚀 启动实例", type="primary"):
                    session = db_manager.get_session()
                    instance_id = str(uuid.uuid4())
                    
                    # Packing config
                    full_config = {
                        'params': config, # Strategy params
                        'sys': {
                            'timeframe': timeframe,
                            'days': days,
                            'capital': capital
                        }
                    }

                    new_instance = StrategyInstance(
                        id=instance_id,
                        user_id=st.session_state.user_id,
                        symbol=symbol,
                        strategy_name=strategy_name,
                        config_json=json.dumps(full_config),
                        mode=mode_val, # backtest or live
                        status='PENDING'
                    )
                    session.add(new_instance)
                    session.commit()
                    session.close()
                    
                    # 清除 applied config
                    if 'applied_opt_config' in st.session_state:
                        del st.session_state['applied_opt_config']
                    
                    # Trigger Process
                    with st.spinner("正在启动后台进程..."):
                        success, msg = process_manager.start_instance(instance_id)
                        if success:
                            st.success(f"实例启动成功! ID: {instance_id}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"启动失败: {msg}")

        st.divider()

        # --- Part 2: Instance Monitor ---
        instance_monitor()

    except Exception as e:
        st.error(f"系统严重错误: {e}")
        import traceback
        st.code(traceback.format_exc())

def strategy_library():
    st.header("📘 策略算法文库")
    st.markdown("这里汇集了平台支持的所有量化交易策略及其详细算法说明。")
    
    # Load Strategies
    # loader = StrategyLoader(os.path.join(current_dir, 'src', 'strategies'))
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    
    if st.button("🔄 刷新策略库"):
        reload_strategies()
        st.rerun()

    st.divider()
    
    if not strategies:
        st.info("暂无可用策略。")
        return

    # 遍历显示
    for name, info in strategies.items():
        display_name = info.get('display_name', name)
        desc = info.get('algo_description')
        if not desc:
            desc = info.get('doc', '暂无说明')
            
        with st.expander(f"📌 **{display_name}** ({name})", expanded=False):
            st.markdown(desc)
            
            # 显示参数说明
            params_config = info.get('params_config', {})
            if params_config:
                st.markdown("#### ⚙️ 参数说明")
                p_data = []
                for k, v in params_config.items():
                    p_data.append({
                        "参数名": k,
                        "显示名称": v.get('label', '-'),
                        "说明": v.get('help', '-')
                    })
                st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)

def optimization_lab():
    st.header("🛠️ 参数调优实验室")
    st.info("利用网格搜索 (Grid Search) 自动寻找策略的历史最优参数组合。")
    
    # Load Strategies
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    
    # 1. 提交新任务
    with st.expander("➕ 新建调优任务", expanded=True):
        col1, col2 = st.columns(2)
        
        def strategy_formatter(name):
            return strategies[name].get('display_name', name)
            
        strategy_name = col1.selectbox(
            "选择策略", 
            list(strategies.keys()),
            format_func=strategy_formatter,
            key="opt_strat_select"
        )
        
        symbol = col2.text_input("交易标的", "BTC/USDT", key="opt_symbol")
        
        if strategy_name:
            st.subheader("配置参数")
            
            # 算法选择
            opt_algo = st.radio("优化算法", ["Grid Search (网格搜索)", "Bayesian (贝叶斯优化 - Optuna)"], horizontal=True)
            is_optuna = "Optuna" in opt_algo
            
            params = strategies[strategy_name]['params']
            p_config = strategies[strategy_name].get('params_config', {})
            
            st.caption("为每个参数设定 起始值(Start) 和 结束值(End)。" + ("" if is_optuna else " 以及步长(Step)。"))
            
            # 动态生成参数范围输入
            opt_config = {}
            
            # 过滤掉不需要优化的参数? 暂时全部列出
            for key, val in params.items():
                if isinstance(val, (int, float)):
                    # 只优化数字类型的参数
                    label = key
                    if key in p_config:
                        label = f"{p_config[key].get('label', key)} ({key})"
                    
                    with st.container():
                        if is_optuna:
                            c1, c2, c3 = st.columns([2, 1, 1])
                        else:
                            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                            
                        c1.markdown(f"**{label}**")
                        
                        if isinstance(val, int):
                            default_start = val
                            default_end = val
                            step_val = 1
                            
                            start = c2.number_input("Start", value=default_start, step=1, key=f"opt_start_{key}")
                            end = c3.number_input("End", value=default_end, step=1, key=f"opt_end_{key}")
                            
                            if not is_optuna:
                                step = c4.number_input("Step", value=step_val, min_value=1, step=1, key=f"opt_step_{key}")
                            else:
                                step = 1 # Optuna int doesn't strictly need step, or assume 1
                            
                            if start != end:
                                # 整数模式
                                opt_config[key] = {'start': start, 'end': end, 'step': step, 'type': 'int'}
                            elif start == end:
                                pass

                        elif isinstance(val, float):
                            default_start = val
                            default_end = val
                            step_val = 0.01 # 默认步长
                            
                            start = c2.number_input("Start", value=default_start, format="%.4f", key=f"opt_start_{key}")
                            end = c3.number_input("End", value=default_end, format="%.4f", key=f"opt_end_{key}")
                            
                            if not is_optuna:
                                step = c4.number_input("Step", value=step_val, format="%.4f", key=f"opt_step_{key}")
                            else:
                                step = None # Optuna float step is optional
                            
                            if start != end:
                                opt_config[key] = {'start': start, 'end': end, 'step': step, 'type': 'float'}

            st.markdown("---")
            c_sys1, c_sys2, c_sys3 = st.columns(3)
            timeframe = c_sys1.selectbox("K线周期", ["1h", "4h", "1d", "15m"], key="opt_tf")
            days = c_sys2.number_input("历史天数", value=30, key="opt_days")
            capital = c_sys3.number_input("初始资金", value=10000000.0, key="opt_cap")
            
            n_trials = 50
            if is_optuna:
                n_trials = st.number_input("试验次数 (Trials)", value=50, min_value=10, max_value=1000, help="Optuna 将尝试寻找最优解的次数。")
            
            # 估算组合数 (仅 Grid)
            can_start = False
            total_comb = 0
            
            if not is_optuna:
                total_comb = 1
                for k, v in opt_config.items():
                    if v['step'] is not None and v['step'] <= 0: continue
                    # Handle float/int step
                    s = v['step'] if v['step'] else 1
                    count = int((v['end'] - v['start']) / s) + 1
                    total_comb *= max(1, count)
                
                can_start = len(opt_config) > 0 and total_comb >= 1
                st.info(f"预计计算组合数: **{total_comb}** 组")
            else:
                can_start = len(opt_config) > 0
                st.info(f"将执行贝叶斯优化，最大尝试次数: **{n_trials}** 次")
                
            if not can_start:
                 st.warning("请至少修改一个参数的 [Start] 或 [End] 值以形成搜索范围。")
            
            if st.button("🚀 开始优选", type="primary", disabled=not can_start):
                if not is_optuna and total_comb > 1000:
                    st.warning("组合数过多，可能会运行很长时间！")
                else:
                    # 创建任务
                    session = db_manager.get_session()
                    job_id = str(uuid.uuid4())
                    
                    sys_cfg = {
                        'timeframe': timeframe,
                        'days': days,
                        'capital': capital,
                        'algorithm': 'optuna' if is_optuna else 'grid',
                        'n_trials': n_trials
                    }
                    
                    new_job = OptimizationJob(
                        id=job_id,
                        user_id=st.session_state.user_id,
                        strategy_name=strategy_name,
                        symbol=symbol,
                        params_config=json.dumps(opt_config),
                        sys_config=json.dumps(sys_cfg),
                        status='PENDING'
                    )
                    session.add(new_job)
                    session.commit()
                    session.close()
                    
                    # 启动后台进程
                    success, msg = process_manager.start_optimization(job_id)
                    if success:
                        st.success("任务已提交后台运行！")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"启动失败: {msg}")

    st.divider()
    
    # 2. 任务列表
    st.subheader("📑 任务列表")
    session = db_manager.get_session()
    jobs = session.query(OptimizationJob).filter_by(user_id=st.session_state.user_id).order_by(OptimizationJob.created_at.desc()).all()
    
    if not jobs:
        st.info("暂无优化任务")
    else:
        # 自动刷新 (降低频率到 10 秒)
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=10000, key="opt_refresh")
        
        # 添加手动刷新按钮
        if st.button("🔄 刷新任务列表", key="refresh_jobs"):
            st.rerun()
        
        for job in jobs:
            with st.container():
                # 状态颜色
                status_color = "grey"
                if job.status == 'RUNNING': status_color = "blue"
                elif job.status == 'COMPLETED': status_color = "green"
                elif job.status == 'ERROR': status_color = "red"
                
                # 解析配置以显示详情
                try:
                    sys_cfg = json.loads(job.sys_config)
                    algo = sys_cfg.get('algorithm', 'grid')
                    algo_label = "贝叶斯 (Optuna)" if algo == 'optuna' else "网格搜索"
                    
                    details = []
                    details.append(f"**算法**: {algo_label}")
                    if algo == 'optuna':
                        details.append(f"**试验次数**: {sys_cfg.get('n_trials', '-')}")
                    else:
                        pass
                        
                    details.append(f"**周期**: {sys_cfg.get('timeframe', '-')}")
                    details.append(f"**历史**: {sys_cfg.get('days', '-')}天")
                    
                    detail_str = " | ".join(details)
                except:
                    detail_str = "配置解析错误"

                # Progress Bar
                prog = job.progress if job.progress is not None else 0.0
                
                # 状态映射
                status_map = {
                    'PENDING': '等待中',
                    'RUNNING': '运行中',
                    'COMPLETED': '已完成',
                    'ERROR': '出错',
                    'STOPPED': '已停止'
                }
                status_display = status_map.get(job.status, job.status)
                
                c1, c2 = st.columns([3, 1])
                # 标题行: Symbol - Strategy [Status]
                c1.markdown(f"**{job.symbol}** - `{job.strategy_name}`  [:{status_color}[{status_display}]]")
                # 详情行: Algo | Trials | TF | Days
                c1.caption(detail_str)
                
                c2.markdown(f"_{job.created_at.strftime('%Y-%m-%d %H:%M')}_")
                
                if job.status == 'RUNNING':
                    st.progress(int(prog) / 100.0)
                    st.caption("正在进行并行回测计算，请稍候... (由于多进程机制，进度条可能在计算完成后一次性跳至 100%)")
                elif job.status == 'COMPLETED':
                    st.progress(1.0)
                
                if job.status == 'COMPLETED' and job.result_json:
                    with st.expander("查看优选结果", expanded=True): # 默认展开，因为重点内容现在在上方了
                        results = json.loads(job.result_json)
                        if results:
                            # 转换为 DataFrame 展示
                            rows = []
                            for r in results:
                                row = r['params'].copy()
                                row.update(r['metrics'])
                                rows.append(row)
                            
                            df_res = pd.DataFrame(rows)
                            
                            # 中文列名映射
                            col_map = {
                                'net_profit': '净利润',
                                'return_rate': '收益率(%)',
                                'max_drawdown': '最大回撤(%)',
                                'win_rate': '胜率',
                                'total_trades': '交易次数'
                            }
                            # 参数列名不需要映射 (或者根据策略配置来映射)
                            
                            # 重命名列
                            df_res.rename(columns=col_map, inplace=True)
                            
                            # --- 摘要行 (一行显示: 应用按钮 | 最佳参数 | 预期收益 | 下载) ---
                            best = results[0]
                            
                            # 使用 columns 布局
                            c_apply, c_metrics, c_params, c_dl = st.columns([1.2, 2, 3, 1])
                            
                            # 1. 应用按钮 (最左侧)
                            if c_apply.button("✨ 应用此参数", key=f"apply_{job.id}", help="将此最佳参数组合填入创建页面"):
                                # 构建要传递的 config
                                applied_config = {
                                    'strategy': job.strategy_name,
                                    'symbol': job.symbol,
                                    'params': best['params'],
                                    'sys': {
                                        # 沿用调优时的环境配置，或者设为默认
                                        'timeframe': sys_cfg.get('timeframe', '1h'),
                                        'days': sys_cfg.get('days', 30),
                                        'capital': sys_cfg.get('capital', 10000000.0)
                                    }
                                }
                                st.session_state['applied_opt_config'] = applied_config
                                st.success("参数已加载！请切换到 [量化工作台] 创建实例。")
                                
                            # 2. 预期收益 (Metric 样式)
                            with c_metrics:
                                # 手动模拟 metric 样式以节省空间
                                profit = best['metrics']['net_profit']
                                ret = best['metrics']['return_rate']
                                color = "green" if profit >= 0 else "red"
                                st.markdown(f"预期收益: :{color}[**${profit:.2f}** ({ret:.2f}%)]")
                                
                            # 3. 参数组合
                            with c_params:
                                # 将参数字典转为紧凑字符串
                                p_str = ", ".join([f"{k}={v}" for k, v in best['params'].items()])
                                st.markdown(f"**最佳参数**: `{p_str}`")
                                
                            # 4. 下载按钮 (最右侧)
                            csv = df_res.to_csv(index=False).encode('utf-8')
                            c_dl.download_button(
                                "📥 下载 CSV",
                                csv,
                                f"opt_results_{job.id[:8]}.csv",
                                "text/csv",
                                key=f"dl_{job.id}"
                            )
                            
                            # --- 结果表格 (默认折叠) ---
                            with st.expander("📊 查看所有组合详情 (Top 50)", expanded=False):
                                # 格式化并展示表格
                                # 构造 format 字典
                                fmt_dict = {
                                    '净利润': '{:.2f}',
                                    '收益率(%)': '{:.2f}',
                                    '最大回撤(%)': '{:.2f}',
                                    '胜率': '{:.2%}'
                                }
                                
                                st.dataframe(df_res.style.format(fmt_dict, na_rep="-"), use_container_width=True)
                                
                        else:
                            st.warning("无结果 (可能所有组合都未成交)")
                elif job.status == 'ERROR':
                    st.error("任务运行出错，请检查后台日志。")
                
                st.divider()
    
    session.close()

def user_dashboard():
    # Sidebar Navigation
    # menu = st.sidebar.radio("Menu", ["Strategy Lab", "My Instances", "Settings"])
    # 合并后的新菜单结构
    menu = st.sidebar.radio("菜单", ["量化工作台", "参数调优", "策略文库"])
    
    if menu == "量化工作台":
        trading_desk()
    elif menu == "参数调优":
        optimization_lab()
    elif menu == "策略文库":
        strategy_library()

# --- 管理员功能模块 ---
def admin_dashboard():
    st.title("🛡️ Admin Console")
    st.warning("You are in Administrator Mode. Changes here affect all users.")
    
    session = db_manager.get_session()
    
    # Metrics
    total_users = session.query(User).count()
    total_instances = session.query(StrategyInstance).count()
    running_instances = session.query(StrategyInstance).filter_by(status='RUNNING').count()
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Users", total_users)
    m2.metric("Total Instances", total_instances)
    m3.metric("Running Instances", running_instances)
    
    st.markdown("---")
    
    # User Management
    users = session.query(User).all()
    selected_username = st.sidebar.selectbox("Select User to Manage", [u.username for u in users])
    user_obj = session.query(User).filter_by(username=selected_username).first()
    
    st.subheader(f"Managing User: {selected_username} (ID: {user_obj.id})")
    
    # Show user's instances
    instances = session.query(StrategyInstance).filter_by(user_id=user_obj.id).all()
    
    if instances:
        inst_data = []
        for i in instances:
            inst_data.append({
                'ID': i.id,
                'Symbol': i.symbol,
                'Strategy': i.strategy_name,
                'Status': i.status,
                'PID': i.pid
            })
        st.dataframe(pd.DataFrame(inst_data), use_container_width=True)
        
        # Admin Actions
        st.write("Force Actions:")
        target_id = st.selectbox("Select Instance ID", [i.id for i in instances])
        c1, c2 = st.columns(2)
        if c1.button("Force Stop"):
            process_manager.stop_instance(target_id)
            st.success("Stop signal sent.")
        if c2.button("Force Delete"):
            i_to_del = session.query(StrategyInstance).filter_by(id=target_id).first()
            if i_to_del:
                session.delete(i_to_del)
                session.commit()
                st.success("Deleted.")
                st.rerun()
    else:
        st.info("User has no instances.")
        
    session.close()

# --- 主程序入口 ---
def main():
    if not st.session_state.user_id:
        login_page()
    else:
        # Sidebar Info
        st.sidebar.markdown(f"### 👤 {st.session_state.username}")
        st.sidebar.markdown(f"Role: `{st.session_state.role}`")
        
        if st.session_state.role == 'admin':
            mode = st.sidebar.radio("View Mode", ["User Mode", "Admin Mode"])
            st.session_state.view_mode = 'admin' if mode == "Admin Mode" else 'user'
            
        if st.sidebar.button("Logout"):
            st.session_state.user_id = None
            st.session_state.role = None
            st.rerun()
            
        st.sidebar.markdown("---")
            
        if st.session_state.view_mode == 'admin':
            admin_dashboard()
        else:
            user_dashboard()

if __name__ == '__main__':
    main()