import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import hashlib
import json
import uuid
import os
import sys
import time
import glob
import html
import streamlit.components.v1 as components
from src.utils.data_helper import load_kline_data, calculate_indicators

# 添加 src 到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

from src.utils.db_manager import db_manager
from src.utils.db_models import User, ExchangeConfig, StrategyInstance, TradeRecord, EquityRecord, OptimizationJob, Tournament, TournamentResult
from src.utils.redis_client import redis_client
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

from datetime import timezone, timedelta, datetime

# --- 缓存优化 ---
@st.cache_data(ttl=5) # 降低缓存时间以支持实时更新
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
import json
import requests

# --- Fragment for Live Chart ---
def _render_chart_content(instance_id, symbol, config_json, strategy_name, mode, created_at):
    session = db_manager.get_session()
    try:
        # --- 新版渲染：嵌入独立 React 前端 (无条件渲染) ---
        # 将其移至最上方，确保即使后端数据加载失败/为空，前端页面也能加载
        # 使用 HashRouter，路径变为 /#/chart/{id}
        frontend_url = f"http://localhost:5173/#/chart/{instance_id}"
        st.markdown(f"""
        <iframe src="{frontend_url}" width="100%" height="600" frameborder="0" style="border-radius: 5px; background-color: #1e1e1e;" sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe>
        """, unsafe_allow_html=True)

        # 1. 先获取交易记录
        trades = session.query(TradeRecord).filter_by(instance_id=instance_id).all()
        
        # 2. 计算时间范围
        start_ts = None
        end_ts = None
        target_timeframe = None
        
        if trades:
            ts_list = [t.timestamp.replace(tzinfo=timezone.utc).timestamp() for t in trades]
            if ts_list:
                start_ts = min(ts_list) - 86400 * 2
                end_ts = max(ts_list) + 86400 * 2
                
        # 尝试获取配置中的 timeframe
        try:
            cfg = json.loads(config_json)
            target_timeframe = cfg.get('sys', {}).get('timeframe')
            
            if mode == 'backtest' and not trades:
                days = int(cfg.get('sys', {}).get('days', 30))
                end_dt = created_at.replace(tzinfo=timezone.utc)
                start_dt = end_dt - timedelta(days=days + 5)
                end_ts = end_dt.timestamp()
                start_ts = start_dt.timestamp()
        except:
            pass
                
        # 3. 获取 K 线数据
        if mode == 'live' and start_ts is None:
            now = time.time()
            try:
                cfg = json.loads(config_json)
                days_to_load = int(cfg.get('sys', {}).get('days', 7))
            except:
                days_to_load = 7
            
            start_ts = now - 86400 * days_to_load
            end_ts = now + 3600 
            
        kline_df = get_kline_data(symbol, start_ts, end_ts, timeframe=target_timeframe)
        
        # --- Redis Realtime Merge ---
        if mode == 'live':
            live_candles = redis_client.get_latest_market_data(instance_id)
            if live_candles:
                # Convert to DataFrame
                live_df = pd.DataFrame(live_candles)
                
                # Filter valid columns
                valid_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
                for col in valid_cols:
                    if col not in live_df.columns:
                        live_df[col] = 0
                live_df = live_df[valid_cols]

                if kline_df.empty:
                    kline_df = live_df
                else:
                    # Merge and deduplicate by 'time'
                    # 1. Concat
                    merged = pd.concat([kline_df, live_df], ignore_index=True)
                    # 2. Drop duplicates (keep last)
                    # We convert 'time' to int just in case
                    merged['time'] = merged['time'].astype(int)
                    kline_df = merged.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
        # ----------------------------

        
        if not kline_df.empty:
            candle_data = kline_df.to_dict('records')
            
            markers = []
            has_orders = any(t.side in ['BUY', 'SELL'] for t in trades)
            
            for t in trades:
                if has_orders and t.side in ['LONG', 'SHORT', 'ROUNDTRIP_LONG', 'ROUNDTRIP_SHORT']:
                    continue
                    
                color = '#ef5350' if t.side in ['SHORT', 'SELL'] else '#26a69a'
                text = f"{t.side} @ {t.price}"
                shape = 'arrowDown' if color == '#ef5350' else 'arrowUp'
                position = 'aboveBar' if color == '#ef5350' else 'belowBar'
                ts = t.timestamp.replace(tzinfo=timezone.utc).timestamp()
                markers.append({'time': int(ts), 'position': position, 'color': color, 'shape': shape, 'text': text})
                
            chartOptions = {
                "layout": {"textColor": '#d1d4dc', "background": {"type": 'solid', "color": 'transparent'}}, 
                "height": 400,
                "crosshair": {
                    "mode": 0,
                    "vertLine": {
                        "visible": True,
                        "labelVisible": True,
                        "color": '#555555',
                        "width": 1,
                        "style": 3,
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
        
            main_overlays, sub_charts_data = get_indicators(kline_df.copy(), strategy_name, config_json)
            
            main_series = [{
                "type": 'Candlestick', 
                "data": candle_data, 
                "options": {"upColor": '#26a69a', "downColor": '#ef5350', "borderVisible": False, "wickUpColor": '#26a69a', "wickDownColor": '#ef5350'}, 
                "markers": markers
            }] + main_overlays 
            
            charts_to_render = [{"chart": chartOptions, "series": main_series}]
            
            for sub in sub_charts_data:
                sub_chart_options = {
                    "layout": {"textColor": '#d1d4dc', "background": {"type": 'solid', "color": 'transparent'}}, 
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
            
            # 改为浏览器侧 WS 增量更新：首屏通过 REST 拉取历史，随后用 WS 更新最后一根或追加新一根
            # 为防止 numpy 类型在序列化时报错，这里做一次纯 Python 类型归一化
            def _normalize(o):
                try:
                    import numpy as np
                except Exception:
                    np = None
                if isinstance(o, dict):
                    return {k: _normalize(v) for k, v in o.items()}
                if isinstance(o, list):
                    return [_normalize(v) for v in o]
                if np:
                    if isinstance(o, np.integer):
                        return int(o)
                    if isinstance(o, np.floating):
                        return float(o)
                if isinstance(o, float):
                    import math
                    if math.isnan(o) or math.isinf(o):
                        return None
                return o


            
            # --- 旧版 HTML 生成逻辑已移除，改为使用上述 iframe ---
            # 原有的 Plotly 后备渲染保留在下方

    finally:
        session.close()

@st.fragment
def render_chart_fragment_static(instance_id, symbol, config_json, strategy_name, mode, created_at):
    _render_chart_content(instance_id, symbol, config_json, strategy_name, mode, created_at)

@st.fragment(run_every=2)
def render_chart_fragment_live(instance_id, symbol, config_json, strategy_name, mode, created_at):
    # Use a session state key to store data and prevent full re-renders if possible
    # But Streamlit Lightweight Charts component handles diffing internally mostly.
    # The key issue is `key=f"chart_{instance_id}"` being recreated.
    # We should ensure the key is stable.
    _render_chart_content(instance_id, symbol, config_json, strategy_name, mode, created_at)

# --- Fragment for Live Logs ---
@st.fragment(run_every=5) # 降低刷新频率：2s -> 5s
def render_log_fragment(instance_id, log_path):
    redis_logs = redis_client.get_latest_logs(instance_id)
    if redis_logs:
        log_lines = redis_logs
        is_from_redis = True
    elif log_path and os.path.exists(log_path):
        with open(log_path, 'r') as f:
            log_lines = f.readlines()
        is_from_redis = False
    else:
        log_lines = []
        is_from_redis = False

    if log_lines:
        parsed_lines = []
        # 减少渲染行数：500 -> 100，提高前端性能
        for line in log_lines[-100:]:
            try:
                line_str = line.strip()
                if not line_str: continue
                try:
                    log_obj = json.loads(line_str)
                    ts = log_obj.get('timestamp', '')
                    lvl = log_obj.get('level', 'INFO')
                    sym = log_obj.get('symbol', '-')
                    msg = log_obj.get('message', '')
                    color = "#d4d4d4"
                    if lvl == 'ERROR': color = "#ff5252"
                    elif lvl == 'WARNING': color = "#ffb74d"
                    elif lvl == 'ORDER': color = "#69f0ae"
                    elif lvl == 'TRADE': color = "#40c4ff"
                    formatted_line = f'<span style="color:{color}">[{ts}] [{lvl}] [{sym}] {html.escape(msg)}</span>'
                    parsed_lines.append(formatted_line)
                except json.JSONDecodeError:
                    parsed_lines.append(html.escape(line_str))
            except Exception:
                continue
        
        log_content = "<br>".join(parsed_lines)
        source_tag = '<span style="color:#69f0ae; font-size:0.8em;">(Live via Redis)</span>' if is_from_redis else '<span style="color:#888; font-size:0.8em;">(From File)</span>'
        st.markdown(f"**实时日志** {source_tag}", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="max-height: 400px; overflow-y: auto; background-color: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; font-size: 0.85em; line-height: 1.4;">
        {log_content}
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("暂无日志 (实例可能正在启动或 Redis 未连接)")

# --- Fragment for Status ---
@st.fragment(run_every=5)
def render_status_fragment(instance_id, initial_status, initial_pid, mode):
    # Try Redis first
    cached = redis_client.get_status(instance_id)
    
    current_status = initial_status
    current_pid = initial_pid
    
    if cached:
        current_status = cached.get('status', initial_status)
        current_pid = cached.get('pid', initial_pid)
    
    # Check PID if running
    if current_status == 'RUNNING':
        if current_pid and not psutil.pid_exists(current_pid):
            current_status = 'STOPPED' if mode == 'live' else 'COMPLETED'
            # Note: We don't update DB here to avoid concurrency issues in fragment, 
            # just display. DB update happens on main refresh or action.
    
    if current_status == 'RUNNING':
        # Progress for backtest could be fetched here too if needed
        st.markdown("🟢 **运行中**")
    elif current_status == 'COMPLETED':
        st.markdown(":green[**✅ 完成**]")
    elif current_status == 'STOPPED':
        st.markdown(":red[**⛔ 停止**]")
    else:
        st.markdown(f"**⚠️ {current_status}**")

# --- Fragment for PnL ---
@st.fragment(run_every=5)
def render_pnl_fragment(instance_id, config_json):
    session = db_manager.get_session()
    try:
        latest_eq = session.query(EquityRecord).filter_by(instance_id=instance_id).order_by(EquityRecord.timestamp.desc()).first()
        
        if latest_eq:
            initial_capital = 10000000.0
            try:
                cfg = json.loads(config_json)
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
            st.markdown(f":{color}[**${current_val:,.0f}**   ({sign}{roi:.2f}%) ]")
        else:
            st.markdown("-")
    finally:
        session.close()

@st.fragment(run_every=5)
def render_actions_fragment(instance_id):
    session = db_manager.get_session()
    try:
        # 获取最新状态 (优先 Redis)
        cached = redis_client.get_status(instance_id)
        inst = session.query(StrategyInstance).filter_by(id=instance_id).first()
        
        if not inst:
            st.error("实例不存在")
            return

        status = inst.status
        if cached:
            status = cached.get('status', status)
            
        # 渲染按钮
        if status == 'RUNNING':
            if st.button("⏹ 停止", key=f"stop_{instance_id}", use_container_width=True):
                process_manager.stop_instance(instance_id)
                st.rerun()
        elif status in ['STOPPED', 'ERROR', 'COMPLETED', 'PENDING']:
            c_start, c_del = st.columns(2)
            if c_start.button("▶ 启动", key=f"start_{instance_id}", use_container_width=True):
                process_manager.start_instance(instance_id)
                st.rerun()
            if c_del.button("🗑 删除", key=f"del_{instance_id}", use_container_width=True):
                ok = db_manager.delete_instance_cascade(session, instance_id)
                if not ok:
                    st.error("删除失败：请稍后重试或检查数据库约束")
                st.rerun()
    finally:
        session.close()

def instance_monitor():
    st.subheader("📡 运行中实例")
    session = db_manager.get_session()
    try:
        instances = session.query(StrategyInstance).filter_by(user_id=st.session_state.user_id).order_by(StrategyInstance.created_at.desc()).all()
        
        if not instances:
            st.info("暂无运行实例。请在上方创建。")
        else:
            # Load strategies for display names
            loader = get_strategy_loader()
            strategies = loader.load_strategies()

            # --- Control Bar ---
            col_ctrl_1, col_ctrl_2 = st.columns([1, 5])
            with col_ctrl_1:
                if st.button("🔄 刷新列表", key="refresh_instances"):
                    st.rerun()
            with col_ctrl_2:
                if st.button("🔽 全部折叠", key="collapse_all_instances"):
                    st.session_state.expanded_instances = set()
                    st.rerun()
            
            for inst in instances:
                # --- 0. 尝试从 Redis 获取实时状态 ---
                cached_status = redis_client.get_status(inst.id)
                if cached_status:
                    inst.status = cached_status.get('status', inst.status)
                    inst.pid = cached_status.get('pid', inst.pid)

                # 1. 自动状态检查
                if inst.status == 'RUNNING':
                    if inst.pid and not psutil.pid_exists(inst.pid):
                        # 如果是实盘，进程消失通常意味着异常停止
                        inst.status = 'STOPPED' if inst.mode == 'live' else 'COMPLETED'
                        inst.pid = None
                        session.commit()
                
                # --- 布局重构 (v4) ---
                with st.container():
                    # 定义列宽: [模式, 信息, 状态, 盈亏, 操作, 详情]
                    cols = st.columns([1.3, 3, 1.2, 2, 2.5, 1])
                    
                    # 1. 模式 (Badge)
                    with cols[0]:
                        if inst.mode == 'live':
                            if inst.config_json and 'testnet' in inst.config_json and '"testnet": true' in inst.config_json:
                                st.markdown(":orange[**[测试网实盘]**]") # Orange for Testnet
                            else:
                                st.markdown(":red[**[正式网实盘]**]")
                        else:
                            st.markdown(":blue[**[模拟回测]**]")
                    
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
                                for k, v in sys_cfg.items():
                                    if k in ['timeframe', 'capital', 'days']:
                                        s_items.append(f"{k}={v}")
                                sys_info = ", ".join(s_items)
                        except:
                            pass
                            
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
                        # 使用 Fragment
                        render_status_fragment(inst.id, inst.status, inst.pid, inst.mode)
    
                    # 4. 盈亏 (PnL)
                    with cols[3]:
                        render_pnl_fragment(inst.id, inst.config_json)
    
                    # 5. 操作区
                    with cols[4]:
                        render_actions_fragment(inst.id)
    
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
                        if inst.mode == 'live':
                            # 改为前端 WS 增量更新，避免 Streamlit 端定时重绘
                            render_chart_fragment_static(
                                inst.id,
                                inst.symbol,
                                inst.config_json,
                                inst.strategy_name,
                                inst.mode,
                                inst.created_at,
                            )
                        else:
                            # 回测模式：静态显示，不刷新
                            render_chart_fragment_static(
                                inst.id, 
                                inst.symbol, 
                                inst.config_json, 
                                inst.strategy_name, 
                                inst.mode, 
                                inst.created_at
                            )
    
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
                                    fig = px.line(df_eq, x='Time', y='Total', title='总资产净值 (USDT)')
                                    fig.update_layout(height=350)
                                    st.plotly_chart(fig, use_container_width=True, key=f"equity_chart_{inst.id}")
                                    
                                with col_eq2:
                                    st.subheader("🍰 当前持仓")
                                    if not df_eq.empty:
                                        latest = df_eq.iloc[-1]
                                        pos_val = max(0, latest['Value'])
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
                                round_trips = []
                                orders = []
                                for t in trades_q:
                                    if t.side in ['LONG', 'SHORT', 'ROUNDTRIP_LONG', 'ROUNDTRIP_SHORT']:
                                        round_trips.append(t)
                                    else:
                                        orders.append(t)
                                
                                processed_rows = []
                                rt_map = {}
    
                                from dateutil import parser
                                for rt in round_trips:
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
    
                                for o in orders:
                                    group_id = "-"
                                    matched_rt_id = None
                                    for rid, info in rt_map.items():
                                        if info['open_dt'] and info['close_dt']:
                                            if (info['open_dt'] - timedelta(seconds=1)) <= o.timestamp <= (info['close_dt'] + timedelta(seconds=1)):
                                                matched_rt_id = rid
                                                break
                                        elif info['close_dt']:
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
                                
                                df_temp = pd.DataFrame(processed_rows)
                                if not df_temp.empty:
                                    group_max_time = df_temp.groupby('TradeID')['sort_time'].max()
                                    df_temp['group_sort_key'] = df_temp['TradeID'].map(group_max_time)
                                    
                                    df_temp = df_temp.sort_values(
                                        by=['group_sort_key', 'TradeID', 'sort_time', 'is_header'],
                                        ascending=[True, True, True, True]
                                    )
                                    
                                    data_list = []
                                    row_styles = []
                                    unique_groups = [g for g in df_temp['TradeID'].unique() if g != '-']
                                    group_color_idx = {gid: i for i, gid in enumerate(unique_groups)}
                                    df_temp = df_temp.reset_index(drop=True)
                                    
                                    for idx, row in df_temp.iterrows():
                                        t = row['raw']
                                        bg_color = ''
                                        if row['TradeID'] != '-':
                                            c_idx = group_color_idx.get(row['TradeID'], 0)
                                            bg_color = 'background-color: #f5f5f5' if c_idx % 2 == 0 else 'background-color: #ffffff'
                                        else:
                                            bg_color = 'background-color: #ffffff'
                                        
                                        if row['is_header']:
                                            bg_color = 'background-color: #e3f2fd'
                                        
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
                                    c1, c2 = st.columns([2, 1])
                                    with c1:
                                        type_filter = st.multiselect(
                                            "筛选记录类型", 
                                            options=df_display['记录类型'].unique(),
                                            default=df_display['记录类型'].unique(),
                                            key=f"filter_{inst.id}"
                                        )
                                    
                                    if type_filter:
                                        style_map = {i: s for i, s in zip(df_display.index, row_styles)}
                                        df_final = df_display[df_display['记录类型'].isin(type_filter)].copy()
                                    else:
                                        style_map = {i: s for i, s in zip(df_display.index, row_styles)}
                                        df_final = df_display.copy()
    
                                    def style_rows(row):
                                        s = style_map.get(row.name, "")
                                        return [s] * len(row)
    
                                    styler = df_final.style.format({
                                        '价格': '{:.4f}',
                                        '数量': '{:.4f}',
                                        '盈亏': '{:.2f}'
                                    }).apply(style_rows, axis=1)
                                    
                                    st.dataframe(styler, use_container_width=True)
                                else:
                                    st.info("暂无交易记录")
                            else:
                                st.info("暂无交易记录")
    
                        # Tab 4: Log
                        with tabs[3]:
                            redis_logs = redis_client.get_latest_logs(inst.id)
                            if redis_logs:
                                log_lines = redis_logs
                                is_from_redis = True
                            elif inst.log_path and os.path.exists(inst.log_path):
                                with open(inst.log_path, 'r') as f:
                                    log_lines = f.readlines()
                                is_from_redis = False
                            else:
                                log_lines = []
                                is_from_redis = False
    
                            if log_lines:
                                parsed_lines = []
                                for line in log_lines[-500:]:
                                    try:
                                        line_str = line.strip()
                                        if not line_str: continue
                                        try:
                                            log_obj = json.loads(line_str)
                                            ts = log_obj.get('timestamp', '')
                                            lvl = log_obj.get('level', 'INFO')
                                            sym = log_obj.get('symbol', '-')
                                            msg = log_obj.get('message', '')
                                            color = "#d4d4d4"
                                            if lvl == 'ERROR': color = "#ff5252"
                                            elif lvl == 'WARNING': color = "#ffb74d"
                                            elif lvl == 'ORDER': color = "#69f0ae"
                                            elif lvl == 'TRADE': color = "#40c4ff"
                                            formatted_line = f'<span style="color:{color}">[{ts}] [{lvl}] [{sym}] {html.escape(msg)}</span>'
                                            parsed_lines.append(formatted_line)
                                        except json.JSONDecodeError:
                                            parsed_lines.append(html.escape(line_str))
                                    except Exception:
                                        continue
                                
                                log_content = "<br>".join(parsed_lines)
                                source_tag = '<span style="color:#69f0ae; font-size:0.8em;">(Live via Redis)</span>' if is_from_redis else '<span style="color:#888; font-size:0.8em;">(From File)</span>'
                                st.markdown(f"**实时日志** {source_tag}", unsafe_allow_html=True)
                                st.markdown(f"""
                                <div style="max-height: 400px; overflow-y: auto; background-color: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; font-size: 0.85em; line-height: 1.4;">
                                {log_content}
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                st.info("暂无日志 (实例可能正在启动或 Redis 未连接)")
                        
                        st.divider() # Bottom divider
                        
    finally:
        session.close()

def trading_desk():
    try:
        st.header("🖥️ 量化交易工作台")
        
        # --- Part 0: Debug Info ---
        with st.expander("🐞 Debug Console (系统日志)", expanded=False):
            log_dir = os.path.join(current_dir, 'logs', 'instances')
            if os.path.exists(log_dir):
                log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
                if log_files:
                    latest_log = log_files[0]
                    st.write(f"最新日志: `{os.path.basename(latest_log)}`")
                    try:
                        with open(latest_log, 'r') as f:
                            lines = f.readlines()[-20:]
                            st.code("".join(lines), language='text')
                    except Exception as e:
                        st.error(f"无法读取日志: {e}")
                else:
                    st.info("暂无日志文件")
            else:
                st.warning("日志目录不存在")
        
        # --- Part 1: Strategy Launcher ---
        with st.expander("➕ 创建新策略实例", expanded=False):
            loader = get_strategy_loader()
            strategies = loader.load_strategies()
            
            if st.button("🔄 刷新策略列表", help="如果上传了新策略文件，点击此按钮加载"):
                reload_strategies()
                st.rerun()
            
            col1, col2, col3 = st.columns(3)
            
            def strategy_formatter(name):
                return strategies[name].get('display_name', name)
            
            default_strat_idx = 0
            default_symbol = "BTC/USDT"
            
            applied = st.session_state.get('applied_opt_config')
            if applied:
                s_keys = list(strategies.keys())
                if applied['strategy'] in s_keys:
                    default_strat_idx = s_keys.index(applied['strategy'])
                default_symbol = applied.get('symbol', "BTC/USDT")
                st.info(f"✨ 已自动加载优选参数 (来自策略 {applied['strategy']})")
            
            strategy_name = col1.selectbox("选择策略", list(strategies.keys()), index=default_strat_idx, format_func=strategy_formatter)
            symbol = col2.text_input("交易标的 (e.g. BTC/USDT)", default_symbol)
            
            mode_options = ["📉 模拟回测 (历史数据)", "🧪 测试网实盘 (虚拟资金)", "💰 正式网实盘 (真实资金)"]
            selected_mode = col3.selectbox("执行模式", mode_options)
            
            if selected_mode == "📉 模拟回测 (历史数据)":
                mode_val = 'backtest'
                is_testnet = True
            elif selected_mode == "🧪 测试网实盘 (虚拟资金)":
                mode_val = 'live'
                is_testnet = True
            else:
                mode_val = 'live'
                is_testnet = False
                st.warning("⚠️ 您选择了正式网实盘模式，系统将使用您的真实资金进行交易，请务必确认风控配置！")
            
            if strategy_name:
                desc = strategies[strategy_name].get('algo_description') or strategies[strategy_name].get('doc')
                if desc:
                    with st.expander("📖 策略说明", expanded=False):
                        st.markdown(desc)

                params = strategies[strategy_name]['params']
                p_config = strategies[strategy_name].get('params_config', {})
                applied_params = applied.get('params', {}) if applied and applied['strategy'] == strategy_name else {}
                
                config = {}
                st.subheader("⚙️ 策略参数")
                p_cols = st.columns(3)
                i = 0
                for key, val in params.items():
                    col = p_cols[i % 3]
                    with col:
                        label = p_config.get(key, {}).get('label', key)
                        help_text = p_config.get(key, {}).get('help')
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
                c1, c2, c3 = st.columns(3)
                
                def_tf_idx = 5
                def_days = 30
                def_cap = 10000000.0
                if applied:
                    sys_app = applied.get('sys', {})
                    tfs = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
                    if sys_app.get('timeframe') in tfs:
                        def_tf_idx = tfs.index(sys_app.get('timeframe'))
                    def_days = int(sys_app.get('days', 30))
                    def_cap = float(sys_app.get('capital', 10000000.0))
                
                # Check if we have a fetched balance to override
                if 'fetched_balance' in st.session_state:
                    def_cap = st.session_state.pop('fetched_balance')
                    st.toast(f"✅ 已自动填充账户余额: {def_cap} USDT")
                
                timeframe = c1.selectbox("K线周期", ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"], index=def_tf_idx)
                days = c2.number_input("历史天数", min_value=1, value=def_days)
                
                # --- Capital Input with Auto-Fetch ---
                cap_container = c3.container()
                capital = cap_container.number_input("初始资金 (USDT)", min_value=10.0, value=def_cap, step=100.0)
                
                if mode_val == 'live':
                    if cap_container.button("🏦 读取账户余额", help="从交易所获取当前可用 USDT 余额"):
                        from src.utils.account_helper import get_account_balance
                        
                        # Get keys
                        session = db_manager.get_session()
                        user_config = session.query(ExchangeConfig).filter_by(user_id=st.session_state.user_id).first()
                        
                        ak, sk = None, None
                        if user_config:
                            if is_testnet:
                                ak = db_manager.decrypt_secret(user_config.testnet_api_key_enc)
                                sk = db_manager.decrypt_secret(user_config.testnet_secret_key_enc)
                            else:
                                ak = db_manager.decrypt_secret(user_config.api_key_enc)
                                sk = db_manager.decrypt_secret(user_config.secret_key_enc)
                        session.close()

                        # Fallback to env vars if not found in DB
                        if not ak or not sk:
                            if is_testnet:
                                ak = ak or os.environ.get('BINANCE_TESTNET_API_KEY')
                                sk = sk or os.environ.get('BINANCE_TESTNET_SECRET_KEY')
                            else:
                                ak = ak or os.environ.get('BINANCE_API_KEY')
                                sk = sk or os.environ.get('BINANCE_SECRET_KEY')
                        
                        if ak and sk:
                            with st.spinner("正在连接交易所..."):
                                bal = get_account_balance(ak, sk, is_testnet)
                                if bal > 0:
                                    st.success(f"账户余额: {bal:.2f} USDT")
                                    # Update session state to pre-fill next time or just show info
                                    # Unfortunately, st.number_input value can't be updated easily without rerun
                                    # We'll use session_state trick
                                    st.session_state[f'fetched_balance'] = bal
                                    st.rerun()
                                else:
                                    st.warning("余额为 0 或无法获取")
                        else:
                            st.error("未配置 API Key")
                            
                # Apply fetched balance if available
                if 'fetched_balance' in st.session_state:
                    capital = st.session_state.pop('fetched_balance')
                    # Re-render number input with new value (requires unique key or rerun logic which we did)
                    # Ideally we should have used key in number_input and updated state
                    # But here we just override the variable for the start logic below
                    # To visually update, we need the rerun above to re-render the input with value=capital
                    # So we need to handle the default value logic carefully.
                    # Simplified: We just show the balance message above, and user types it?
                    # Better: The st.rerun() will re-execute this script.
                    # We need to make sure `def_cap` uses the fetched value.
                    pass 
                
                # To make the update stick in the UI, we need to pass it to `value` of number_input
                # We can do this by updating `def_cap` before the widget is rendered
                # But widget is already rendered above.
                # So the pattern is:
                # 1. Button click -> Fetch -> Save to Session -> Rerun
                # 2. Rerun -> Check Session -> Update default -> Render Widget
                
                # Let's fix the order in next turn or just leave it as message for now?
                # The code above renders widget FIRST, then button.
                # So the update will only happen on NEXT interaction unless we force it.
                # Correct pattern:
                # Check session state for override BEFORE rendering widget.
                
                # But `def_cap` is calculated from `applied`.
                # Let's refine this block.
                
                    
                if st.button("🚀 启动实例", type="primary"):
                    session = db_manager.get_session()
                    instance_id = str(uuid.uuid4())
                    full_config = {
                        'params': config,
                        'sys': {'timeframe': timeframe, 'days': days, 'capital': capital, 'testnet': is_testnet}
                    }
                    new_instance = StrategyInstance(
                        id=instance_id, user_id=st.session_state.user_id, symbol=symbol,
                        strategy_name=strategy_name, config_json=json.dumps(full_config),
                        mode=mode_val, status='PENDING'
                    )
                    session.add(new_instance)
                    session.commit()
                    session.close()
                    if 'applied_opt_config' in st.session_state:
                        del st.session_state['applied_opt_config']
                    with st.spinner("正在启动后台进程..."):
                        success, msg = process_manager.start_instance(instance_id)
                        if success:
                            st.success(f"实例启动成功! ID: {instance_id}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"启动失败: {msg}")

        st.divider()
        instance_monitor()

    except Exception as e:
        st.error(f"系统严重错误: {e}")
        import traceback
        st.code(traceback.format_exc())

def strategy_library():
    st.header("📘 策略算法文库")
    st.markdown("这里汇集了平台支持的所有量化交易策略及其详细算法说明。")
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    if st.button("🔄 刷新策略库"):
        reload_strategies()
        st.rerun()
    st.divider()
    if not strategies:
        st.info("暂无可用策略。")
        return
    for name, info in strategies.items():
        display_name = info.get('display_name', name)
        desc = info.get('algo_description') or info.get('doc', '暂无说明')
        with st.expander(f"📌 **{display_name}** ({name})", expanded=False):
            st.markdown(desc)
            params_config = info.get('params_config', {})
            if params_config:
                st.markdown("#### ⚙️ 参数说明")
                p_data = [{"参数名": k, "显示名称": v.get('label', '-'), "说明": v.get('help', '-')} for k, v in params_config.items()]
                st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)

def optimization_lab():
    st.header("🛠️ 参数调优实验室")
    st.info("利用网格搜索 (Grid Search) 自动寻找策略的历史最优参数组合。")
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    with st.expander("➕ 新建调优任务", expanded=True):
        col1, col2 = st.columns(2)
        def strategy_formatter(name):
            return strategies[name].get('display_name', name)
        strategy_name = col1.selectbox("选择策略", list(strategies.keys()), format_func=strategy_formatter, key="opt_strat_select")
        symbol = col2.text_input("交易标得", "BTC/USDT", key="opt_symbol")
        if strategy_name:
            st.subheader("配置参数")
            opt_algo = st.radio("优化算法", ["Grid Search (网格搜索)", "Bayesian (贝叶斯优化 - Optuna)"], horizontal=True)
            is_optuna = "Optuna" in opt_algo
            params = strategies[strategy_name]['params']
            p_config = strategies[strategy_name].get('params_config', {})
            st.caption("为每个参数设定 起始值(Start) 和 结束值(End)。" + ("" if is_optuna else " 以及步长(Step)。"))
            opt_config = {}
            for key, val in params.items():
                if isinstance(val, (int, float)):
                    label = p_config.get(key, {}).get('label', key) + f" ({key})"
                    with st.container():
                        cols = st.columns([2, 1, 1] + ([] if is_optuna else [1]))
                        cols[0].markdown(f"**{label}**")
                        start = cols[1].number_input("Start", value=val, key=f"opt_start_{key}")
                        end = cols[2].number_input("End", value=val, key=f"opt_end_{key}")
                        if not is_optuna:
                            step = cols[3].number_input("Step", value=1 if isinstance(val, int) else 0.01, key=f"opt_step_{key}")
                        else:
                            step = 1 if isinstance(val, int) else None
                        if start != end:
                            opt_config[key] = {'start': start, 'end': end, 'step': step, 'type': 'int' if isinstance(val, int) else 'float'}
            st.markdown("---")
            c_sys1, c_sys2, c_sys3 = st.columns(3)
            timeframe = c_sys1.selectbox("K线周期", ["1h", "4h", "1d", "15m"], key="opt_tf")
            days = c_sys2.number_input("历史天数", value=30, key="opt_days")
            capital = c_sys3.number_input("初始资金", value=10000000.0, key="opt_cap")
            n_trials = 50
            if is_optuna:
                n_trials = st.number_input("试验次数 (Trials)", value=50, min_value=10, max_value=1000)
            can_start = len(opt_config) > 0
            if not is_optuna:
                total_comb = 1
                for k, v in opt_config.items():
                    s = v['step'] or 1
                    total_comb *= int((v['end'] - v['start']) / s) + 1
                st.info(f"预计计算组合数: **{total_comb}** 组")
                can_start = can_start and total_comb >= 1
            else:
                st.info(f"将执行贝叶斯优化，最大尝试次数: **{n_trials}** 次")
            if st.button("🚀 开始优选", type="primary", disabled=not can_start):
                session = db_manager.get_session()
                job_id = str(uuid.uuid4())
                sys_cfg = {'timeframe': timeframe, 'days': days, 'capital': capital, 'algorithm': 'optuna' if is_optuna else 'grid', 'n_trials': n_trials}
                new_job = OptimizationJob(id=job_id, user_id=st.session_state.user_id, strategy_name=strategy_name, symbol=symbol, params_config=json.dumps(opt_config), sys_config=json.dumps(sys_cfg), status='PENDING')
                session.add(new_job)
                session.commit()
                session.close()
                success, msg = process_manager.start_optimization(job_id)
                if success:
                    st.success("任务已提交后台运行！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"启动失败: {msg}")

    st.divider()
    st.subheader("📑 任务列表")
    session = db_manager.get_session()
    jobs = session.query(OptimizationJob).filter_by(user_id=st.session_state.user_id).order_by(OptimizationJob.created_at.desc()).all()
    if not jobs:
        st.info("暂无优化任务")
    else:
        if st.button("🔄 刷新任务列表", key="refresh_jobs"):
            st.rerun()
        for job in jobs:
            with st.container():
                status_color = {"RUNNING": "blue", "COMPLETED": "green", "ERROR": "red"}.get(job.status, "grey")
                sys_cfg = json.loads(job.sys_config)
                algo_label = "贝叶斯 (Optuna)" if sys_cfg.get('algorithm') == 'optuna' else "网格搜索"
                detail_str = f"**算法**: {algo_label} | **周期**: {sys_cfg.get('timeframe')} | **历史**: {sys_cfg.get('days')}天"
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{job.symbol}** - `{job.strategy_name}`  [:{status_color}[{job.status}]]")
                c1.caption(detail_str)
                c2.markdown(f"_{job.created_at.strftime('%Y-%m-%d %H:%M')}_")
                if job.status == 'RUNNING':
                    st.progress(int(job.progress or 0) / 100.0)
                elif job.status == 'COMPLETED':
                    st.progress(1.0)
                if job.status == 'COMPLETED' and job.result_json:
                    with st.expander("查看优选结果", expanded=True):
                        results = json.loads(job.result_json)
                        if results:
                            df_res = pd.DataFrame([dict(r['params'], **r['metrics']) for r in results])
                            df_res.rename(columns={'net_profit': '净利润', 'return_rate': '收益率(%)', 'max_drawdown': '最大回撤(%)', 'win_rate': '胜率', 'total_trades': '交易次数'}, inplace=True)
                            best = results[0]
                            c_apply, c_metrics, c_params, c_dl = st.columns([1.2, 2, 3, 1])
                            if c_apply.button("✨ 应用此参数", key=f"apply_{job.id}"):
                                st.session_state['applied_opt_config'] = {'strategy': job.strategy_name, 'symbol': job.symbol, 'params': best['params'], 'sys': {'timeframe': sys_cfg.get('timeframe', '1h'), 'days': sys_cfg.get('days', 30), 'capital': sys_cfg.get('capital', 10000000.0)}}
                                st.success("参数已加载！请切换到 [量化工作台] 创建实例。")
                            profit, ret = best['metrics']['net_profit'], best['metrics']['return_rate']
                            c_metrics.markdown(f"预期收益: :{'green' if profit >= 0 else 'red'}[**${profit:.2f}** ({ret:.2f}%)]")
                            c_params.markdown(f"**最佳参数**: `{', '.join([f'{k}={v}' for k, v in best['params'].items()])}`")
                            c_dl.download_button("📥 下载 CSV", df_res.to_csv(index=False).encode('utf-8'), f"opt_results_{job.id[:8]}.csv", "text/csv", key=f"dl_{job.id}")
                            with st.expander("📊 查看所有组合详情 (Top 50)", expanded=False):
                                st.dataframe(df_res.style.format({'净利润': '{:.2f}', '收益率(%)': '{:.2f}', '最大回撤(%)': '{:.2f}', '胜率': '{:.2%}'}, na_rep="-"), use_container_width=True)
                elif job.status == 'ERROR':
                    st.error("任务运行出错，请检查后台日志。")
                st.divider()
    session.close()

def user_dashboard():
    menu = st.sidebar.radio("菜单", ["量化工作台", "参数调优", "策略文库", "系统设置"])
    if menu == "量化工作台":
        trading_desk()
    elif menu == "参数调优":
        optimization_lab()
    elif menu == "策略文库":
        strategy_library()
    elif menu == "系统设置":
        settings_page()

def admin_dashboard():
    st.title("🛡️ Admin Console")
    session = db_manager.get_session()
    
    # Global Tournament Stats
    st.subheader("⚔️ Tournament Statistics")
    tm1, tm2, tm3 = st.columns(3)
    tm1.metric("Total Tournaments", session.query(Tournament).count())
    tm2.metric("Running Tournaments", session.query(Tournament).filter_by(status='RUNNING').count())
    tm3.metric("Pending Tournaments", session.query(Tournament).filter_by(status='PENDING').count())
    
    st.markdown("---")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Users", session.query(User).count())
    m2.metric("Total Instances", session.query(StrategyInstance).count())
    m3.metric("Running Instances", session.query(StrategyInstance).filter_by(status='RUNNING').count())
    st.markdown("---")
    users = session.query(User).all()
    selected_username = st.sidebar.selectbox("Select User", [u.username for u in users])
    user_obj = session.query(User).filter_by(username=selected_username).first()
    st.subheader(f"Managing User: {selected_username}")
    instances = session.query(StrategyInstance).filter_by(user_id=user_obj.id).all()
    if instances:
        df = pd.DataFrame([{'ID': i.id, 'Symbol': i.symbol, 'Strategy': i.strategy_name, 'Status': i.status, 'PID': i.pid} for i in instances])
        st.dataframe(df, use_container_width=True)
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
                st.rerun()
    else:
        st.info("User has no instances.")
    session.close()

def settings_page():
    st.header("⚙️ 系统设置")
    
    with st.container():
        st.subheader("🔑 交易所配置")
        st.info("您的 API Key 将被加密存储，仅用于与交易所进行通信。")
        
        with st.form("settings_config_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 💰 实盘交易 (Live Trading)")
                api_key = st.text_input("Binance API Key", type="password")
                secret_key = st.text_input("Binance Secret Key", type="password")
            
            with col2:
                st.markdown("#### 🧪 测试网 (Futures Testnet)")
                testnet_api_key = st.text_input("Testnet API Key", type="password")
                testnet_secret_key = st.text_input("Testnet Secret Key", type="password")
            
            st.markdown("---")
            submitted = st.form_submit_button("💾 保存所有配置", type="primary")
            
            if submitted:
                session = db_manager.get_session()
                config = session.query(ExchangeConfig).filter_by(user_id=st.session_state.user_id).first()
                if not config:
                    config = ExchangeConfig(user_id=st.session_state.user_id)
                    session.add(config)
                
                # Update Real Keys if provided
                if api_key:
                    config.api_key_enc = db_manager.encrypt_secret(api_key)
                if secret_key:
                    config.secret_key_enc = db_manager.encrypt_secret(secret_key)
                    
                # Update Testnet Keys if provided
                if testnet_api_key:
                    config.testnet_api_key_enc = db_manager.encrypt_secret(testnet_api_key)
                if testnet_secret_key:
                    config.testnet_secret_key_enc = db_manager.encrypt_secret(testnet_secret_key)
                    
                session.commit()
                st.success("配置已成功保存！")
                session.close()

def strategy_pk_arena():
    st.header("⚔️ 策略竞技场 (Strategy Arena)")
    st.info("通过多维度回测比拼，筛选出最优的 [策略 + 标的 + 周期] 组合。支持参数网格搜索与贝叶斯优化。")
    
    # --- 1. 发起挑战 ---
    with st.container(border=True):
        st.subheader("🏆 发起挑战")
        
        # --- Step 1: Base Config (Interactive) ---
        col1, col2 = st.columns(2)
        with col1:
            pk_name = st.text_input("锦标赛名称", value=f"PK-{datetime.now().strftime('%Y%m%d')}")
            # Load available strategies
            loader = get_strategy_loader()
            strategies = loader.load_strategies()
            avail_strategies = list(strategies.keys())
            
            # Determine safe defaults
            default_strats = []
            possible_defaults = ["SMACrossStrategy", "MACDStrategy", "SMA", "MACD"]
            for name in possible_defaults:
                if name in avail_strategies:
                    default_strats.append(name)
            
            # If still empty, pick the first 2 available
            if not default_strats and avail_strategies:
                default_strats = avail_strategies[:2]
                
            selected_strats = st.multiselect("参赛策略 (Strategies)", avail_strategies, default=default_strats)
            
            selected_symbols = st.multiselect("参赛标的 (Symbols)", ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"], default=["BTC/USDT", "ETH/USDT"])
            
        with col2:
            selected_tfs = st.multiselect("时间周期 (Timeframes)", ["15m", "1h", "4h", "1d"], default=["1h", "4h"])
            initial_cash = st.number_input("每局初始资金 (USDT)", value=10000.0)
            
            d1, d2 = st.columns(2)
            start_date = d1.date_input("开始日期", value=datetime(2023, 1, 1))
            end_date = d2.date_input("结束日期", value=datetime.now())
        
        st.divider()
        st.subheader("2. 策略深度配置")
        
        # --- Step 2: Per-Strategy Config (Interactive) ---
        strategies_config = {}
        
        if not selected_strats:
            st.info("请先选择至少一个策略。")
        else:
            for strat in selected_strats:
                with st.expander(f"⚙️ 配置: {strat}", expanded=True):
                    s_info = strategies.get(strat, {})
                    s_params = s_info.get('params', {})
                    s_params_config = s_info.get('params_config', {})
                    
                    c_mode, c_opt = st.columns([1, 3])
                    mode = c_mode.radio("参数模式", ["使用默认", "自定义/优化"], key=f"mode_{strat}")
                    
                    strat_cfg = {'mode': mode}
                    
                    if mode == "自定义/优化":
                        opt_algo = c_opt.selectbox("优化算法", ["Grid Search (网格搜索)", "Bayesian (Optuna)"], key=f"algo_{strat}")
                        strat_cfg['algorithm'] = 'optuna' if "Optuna" in opt_algo else 'grid'
                        
                        st.markdown("#### 参数范围设置")
                        opt_config = {}
                        
                        # Dynamic Inputs based on Strategy Params
                        for p_name, p_default in s_params.items():
                            p_meta = s_params_config.get(p_name, {})
                            p_label = p_meta.get('label', p_name)
                            p_help = p_meta.get('help', '')
                            
                            # Only handle numeric params for optimization usually
                            if isinstance(p_default, (int, float)):
                                with st.container():
                                    if "Grid" in opt_algo:
                                        # Grid Search: Input comma-separated list
                                        val_str = st.text_input(
                                            f"{p_label} ({p_name}) - 候选值 (逗号分隔)", 
                                            value=str(p_default),
                                            help=f"默认值: {p_default}. {p_help}",
                                            key=f"grid_{strat}_{p_name}"
                                        )
                                        try:
                                            # Parse input
                                            vals = [float(x.strip()) if '.' in x else int(x.strip()) for x in val_str.split(',') if x.strip()]
                                            if vals:
                                                opt_config[p_name] = vals
                                        except:
                                            st.error(f"无法解析参数 {p_name} 的输入值")
                                            
                                    else:
                                        # Optuna: Min, Max, (Step)
                                        c_min, c_max, c_step = st.columns(3)
                                        p_min = c_min.number_input(f"{p_label} Min", value=float(p_default), key=f"opt_min_{strat}_{p_name}")
                                        p_max = c_max.number_input(f"{p_label} Max", value=float(p_default)*2 if p_default!=0 else 10.0, key=f"opt_max_{strat}_{p_name}")
                                        
                                        # Step is optional for Optuna but useful for int
                                        is_int = isinstance(p_default, int)
                                        step_default = 1.0 if is_int else 0.1
                                        p_step = c_step.number_input(f"Step (步长)", value=step_default, key=f"opt_step_{strat}_{p_name}")
                                        
                                        if p_max > p_min:
                                            opt_config[p_name] = {
                                                "start": p_min, 
                                                "end": p_max, 
                                                "step": p_step, 
                                                "type": "int" if is_int else "float"
                                            }
                        
                        strat_cfg['opt_config'] = opt_config
                        
                        # Show JSON preview for verification
                        with st.expander("查看生成的配置 JSON", expanded=False):
                            st.json(opt_config)
                    
                    strategies_config[strat] = strat_cfg

        st.divider()
        
        # --- Step 3: Confirmation & Submit ---
        # Calculate Estimated Tasks
        total_tasks = 0
        if selected_strats and selected_symbols and selected_tfs:
            base_count = len(selected_symbols) * len(selected_tfs)
            for strat in selected_strats:
                cfg = strategies_config.get(strat, {})
                if cfg.get('mode') == '使用默认':
                    total_tasks += base_count
                else:
                    # Estimate based on algo
                    # For Grid: Multiply combinations
                    algo = cfg.get('algorithm', 'grid')
                    opt_c = cfg.get('opt_config', {})
                    
                    if algo == 'grid':
                        combos = 1
                        for k, v in opt_c.items():
                            if isinstance(v, list):
                                combos *= len(v)
                        total_tasks += base_count * combos
                    else:
                        # Optuna is treated as 1 optimization task per environment
                        total_tasks += base_count * 1 
                        
        st.markdown(f"### 🎯 任务预估: `{total_tasks}` 个独立的后台回测/优化进程")
        
        if st.button("🚀 创建锦标赛 (Create Tournament)", type="primary", disabled=total_tasks==0):
            # Create Record
            config = {
                "strategies": selected_strats,
                "symbols": selected_symbols,
                "timeframes": selected_tfs,
                "initial_cash": initial_cash,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "strategies_config": strategies_config
            }
            
            new_tour = Tournament(
                id=str(uuid.uuid4()),
                user_id=st.session_state.user_id,
                name=pk_name,
                config_json=json.dumps(config),
                status='PENDING',
                progress=0.0,
                total_tasks=total_tasks
            )
            session.add(new_tour)
            session.commit()
            st.success("锦标赛已创建！")
            time.sleep(1)
            st.rerun()

    # --- 2. 历史战绩 ---
    st.divider()
    st.subheader("📊 历史战绩")
    
    # Load User Tournaments
    tours = session.query(Tournament).filter_by(user_id=st.session_state.user_id).order_by(Tournament.created_at.desc()).all()
    
    if not tours:
        st.info("暂无历史记录")
    else:
        if st.button("🔄 刷新状态"):
            st.rerun()
            
        for tour in tours:
            with st.expander(f"{tour.name}  [{tour.status}]  (进度: {tour.completed_tasks}/{tour.total_tasks})", expanded=True):
                # Status & Progress
                st.progress(tour.progress)
                
                # Controls
                c1, c2, c3, c4, c5 = st.columns(5)
                
                # Check PID
                is_running = False
                if tour.pid and psutil.pid_exists(tour.pid):
                    is_running = True
                
                if tour.status == 'PENDING' or tour.status == 'STOPPED' or tour.status == 'PAUSED':
                    if c1.button("▶ 启动/继续", key=f"start_{tour.id}"):
                        # Start or Resume
                        success, msg = process_manager.start_tournament(tour.id)
                        if success:
                            st.success(f"已启动: {msg}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"启动失败: {msg}")
                
                if tour.status == 'RUNNING':
                    if c2.button("⏸ 暂停", key=f"pause_{tour.id}"):
                        # Pause just updates DB, runner checks it
                        tour.status = 'PAUSED'
                        session.commit()
                        st.success("已发送暂停信号 (等待当前任务完成)")
                        st.rerun()
                        
                    if c3.button("⏹ 停止", key=f"stop_{tour.id}"):
                            # Stop kills process
                            process_manager.stop_tournament(tour.id)
                            st.success("已停止后台进程")
                            st.rerun()
                
                if c5.button("🗑 删除记录", key=f"del_{tour.id}"):
                        session.delete(tour)
                        session.commit()
                        st.rerun()

                st.divider()

                # Show Results
                if tour.completed_tasks > 0:
                    results = session.query(TournamentResult).filter_by(tournament_id=tour.id).all()
                    if results:
                        # 1. Prepare DataFrame for Leaderboard
                        data = []
                        for r in results:
                            m = json.loads(r.metrics_json) if r.metrics_json else {}
                            data.append({
                                "Strategy": r.strategy_name,
                                "Symbol": r.symbol,
                                "TF": r.timeframe,
                                "Net Profit": m.get('net_profit', 0),
                                "Sharpe": m.get('sharpe_ratio', 0),
                                "Max DD": m.get('max_drawdown', 0),
                                "Win Rate": m.get('win_rate', 0) if 'win_rate' in m else 0, 
                                "Total Return": m.get('total_return', 0)
                            })
                        
                        df_res = pd.DataFrame(data)
                        
                        # 2. Leaderboard
                        st.subheader("🏆 排行榜")
                        st.dataframe(
                            df_res.style.format({
                                "Net Profit": "{:.2f}",
                                "Sharpe": "{:.2f}",
                                "Max DD": "{:.2%}",
                                "Total Return": "{:.2%}"
                            }).background_gradient(subset=['Net Profit'], cmap='Greens'),
                            use_container_width=True
                        )
                        
                        # 3. Visualization
                        st.subheader("📊 深度分析")
                        v_tab1, v_tab2 = st.tabs(["收益对比", "风险分布"])
                        
                        with v_tab1:
                            if not df_res.empty:
                                st.bar_chart(df_res, x="Strategy", y="Net Profit", color="Symbol")
                        
                        with v_tab2:
                            if not df_res.empty:
                                import plotly.express as px
                                fig = px.scatter(
                                    df_res, 
                                    x="Max DD", 
                                    y="Total Return", 
                                    color="Strategy", 
                                    hover_data=["Symbol", "TF"],
                                    title="Risk (Max DD) vs Reward (Return)"
                                )
                                st.plotly_chart(fig, use_container_width=True)
                    
    session.close()

def user_dashboard():
    menu = st.sidebar.radio("菜单", ["量化工作台", "策略竞技场", "参数调优", "策略文库", "系统设置"])
    
    if menu == "量化工作台":
        trading_desk()
    elif menu == "策略竞技场":
        strategy_pk_arena()
    elif menu == "参数调优":
        optimization_lab()
    elif menu == "策略文库":
        strategy_library()
    elif menu == "系统设置":
        settings_page()

def main():
    if not st.session_state.user_id:
        login_page()
    else:
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
