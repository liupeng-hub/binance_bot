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
from src.utils.account_helper import get_account_balance, get_exchange_connection
from src.utils.settings_page import settings_page

from streamlit_lightweight_charts import renderLightweightCharts

# 页面配置
st.set_page_config(page_title="量化 SaaS 平台", layout="wide", page_icon="🚀")

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
def get_kline_data(symbol, start_ts=None, end_ts=None, limit=1000, timeframe=None):
    return load_kline_data(symbol, start_ts, end_ts, limit=limit, timeframe=timeframe)

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
        <h1>🔐 量化 SaaS 平台</h1>
        <p>专业多租户量化交易系统</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录")
            
            if submitted:
                session = db_manager.get_session()
                user = session.query(User).filter_by(username=username).first()
                if user:
                    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
                    if user.password_hash == pwd_hash:
                        st.session_state.user_id = user.id
                        st.session_state.role = user.role
                        st.session_state.username = user.username
                        st.success("登录成功！")
                        st.rerun()
                    else:
                        st.error("密码错误")
                else:
                    st.error("用户不存在")
                session.close()
    
    st.markdown("---")
    with st.expander("创建新账户"):
        new_user = st.text_input("新用户名")
        new_pass = st.text_input("新密码", type="password")
        if st.button("注册"):
            session = db_manager.get_session()
            if session.query(User).filter_by(username=new_user).first():
                st.error("用户名已存在")
            else:
                pwd_hash = hashlib.sha256(new_pass.encode()).hexdigest()
                new_user_obj = User(username=new_user, password_hash=pwd_hash)
                session.add(new_user_obj)
                session.commit()
                st.success("注册成功！请登录。")
            session.close()

# --- 用户功能模块 ---
def user_settings():
    st.header("🔑 交易所配置")
    st.info("您的 API 密钥将被加密并安全存储。")
    
    with st.form("config_form"):
        api_key = st.text_input("币安 API Key", type="password")
        secret_key = st.text_input("币安 Secret Key", type="password")
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
        source_tag = '<span style="color:#69f0ae; font-size:0.8em;">(Redis 实时推送)</span>' if is_from_redis else '<span style="color:#888; font-size:0.8em;">(文件读取)</span>'
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

@st.dialog("➕ 创建新策略实例")
def create_instance_modal(default_mode='backtest'):
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    session = db_manager.get_session()
    
    # Load Accounts
    accounts = db_manager.get_exchange_accounts(session, st.session_state.user_id)
    
    # 自动加载优选配置
    applied = st.session_state.get('applied_opt_config')
    default_strat_idx = 0
    default_symbol = "BTC/USDT"
    
    if applied:
        s_keys = list(strategies.keys())
        if applied['strategy'] in s_keys:
            default_strat_idx = s_keys.index(applied['strategy'])
        default_symbol = applied.get('symbol', "BTC/USDT")
        st.info(f"✨ 已自动加载优选参数 (来自策略 {applied['strategy']})")

    col1, col2 = st.columns(2)
    
    def strategy_formatter(name):
        return strategies[name].get('display_name', name)
    
    strategy_name = col1.selectbox("选择策略", list(strategies.keys()), index=default_strat_idx, format_func=strategy_formatter, key="modal_strat_select")
    symbol = col2.text_input("交易标的", default_symbol, key="modal_symbol_input")
    
    # Mode Selection
    mode_map = {
        "📉 模拟回测 (Backtest)": "backtest",
        "🧪 测试网实盘 (Testnet)": "testnet", 
        "💰 正式网实盘 (Live)": "live"
    }
    
    # Set default index
    def_mode_idx = 0
    if default_mode == 'live': def_mode_idx = 2
    elif default_mode == 'testnet': def_mode_idx = 1
    
    selected_mode_label = st.selectbox("执行模式", list(mode_map.keys()), index=def_mode_idx, key="modal_mode_select")
    selected_mode = mode_map[selected_mode_label]
    
    # Account Selection
    selected_account_id = None
    if selected_mode in ['live', 'testnet']:
        # Filter accounts
        valid_accounts = [a for a in accounts if a.account_type == ('testnet' if selected_mode == 'testnet' else 'live')]
        if not valid_accounts:
            st.warning(f"⚠️ 您尚未配置 {selected_mode} 类型的账户。请先去 [系统设置] 添加。")
        else:
            acc_opts = {a.id: f"{a.alias} ({a.exchange})" for a in valid_accounts}
            selected_account_id = st.selectbox("选择交易账户", list(acc_opts.keys()), format_func=lambda x: acc_opts[x])
            
    if selected_mode == 'live':
        st.warning("⚠️ 正式网实盘模式：将使用真实资金！")

    if strategy_name:
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
                    config[key] = st.number_input(label, value=int(default_val), step=1, help=help_text, key=f"modal_p_{key}")
                elif isinstance(val, float):
                    config[key] = st.number_input(label, value=float(default_val), format="%.4f", help=help_text, key=f"modal_p_{key}")
                else:
                    config[key] = st.text_input(label, value=str(default_val), help=help_text, key=f"modal_p_{key}")
            i += 1
            
        st.divider()
        st.subheader("⚙️ 系统配置")
        c1, c2, c3 = st.columns(3)
        
        def_tf_idx = 5
        def_days = 30
        def_cap = 10000.0
        if applied:
            sys_app = applied.get('sys', {})
            tfs = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
            if sys_app.get('timeframe') in tfs:
                def_tf_idx = tfs.index(sys_app.get('timeframe'))
            def_days = int(sys_app.get('days', 30))
            def_cap = float(sys_app.get('capital', 10000.0))
            
        timeframe = c1.selectbox("K线周期", ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"], index=def_tf_idx, key="modal_tf")
        days = c2.number_input("历史天数", min_value=1, value=def_days, key="modal_days")
        capital = c3.number_input("初始资金 (USDT)", min_value=10.0, value=def_cap, step=100.0, key="modal_cap")
        
        # Validation
        can_launch = True
        if selected_mode != 'backtest' and not selected_account_id:
            can_launch = False
        
        if st.button("🚀 立即启动实例", type="primary", use_container_width=True, disabled=not can_launch):
            instance_id = str(uuid.uuid4())
            # For backtest, is_testnet doesn't matter much, but let's set it
            is_testnet = (selected_mode == 'testnet')
            
            full_config = {
                'params': config,
                'sys': {'timeframe': timeframe, 'days': days, 'capital': capital, 'testnet': is_testnet}
            }
            
            # Determine actual mode string for DB
            db_mode = 'backtest' if selected_mode == 'backtest' else 'live'
            
            new_instance = StrategyInstance(
                id=instance_id, 
                user_id=st.session_state.user_id, 
                account_id=selected_account_id, # Link Account
                symbol=symbol,
                strategy_name=strategy_name, 
                config_json=json.dumps(full_config),
                mode=db_mode, 
                status='PENDING'
            )
            session.add(new_instance)
            session.commit()
            
            # Reset applied config
            if 'applied_opt_config' in st.session_state:
                del st.session_state['applied_opt_config']
                
            # Start Process
            success, msg = process_manager.start_instance(instance_id)
            if success:
                st.success(f"启动成功! ID: {instance_id}")
                st.session_state.selected_instance_id = instance_id # Auto select
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"启动失败: {msg}")
    session.close()

def render_live_dashboard(user_id):
    """
    Renders the aggregated live portfolio dashboard.
    Fetches balances for all LIVE accounts and displays total assets and PnL.
    """
    session = db_manager.get_session()
    accounts = db_manager.get_exchange_accounts(session, user_id)
    live_accounts = [a for a in accounts if a.account_type == 'live']
    
    if not live_accounts:
        st.warning("您尚未配置实盘账户。")
        session.close()
        return

    # Aggregate Data
    total_assets = 0.0
    account_stats = []
    
    # We use a thread pool or simple loop. Since it's network IO, simple loop might be slow if many accounts.
    # For now, simple loop with spinner.
    
    with st.spinner("正在同步实盘资产数据..."):
        for acc in live_accounts:
            api_key = db_manager.decrypt_secret(acc.api_key_enc)
            secret_key = db_manager.decrypt_secret(acc.secret_key_enc)
            
            # Use cached balance if available? No, live dashboard should be fresh or short cache.
            # We can use st.cache_data for 30s?
            
            # Direct fetch for now
            bal = get_account_balance(api_key, secret_key, testnet=False)
            total_assets += bal
            
            account_stats.append({
                'alias': acc.alias,
                'exchange': acc.exchange,
                'balance': bal
            })
    
    session.close()
    
    # --- Display Dashboard ---
    with st.container(border=True):
        st.subheader("💰 实盘总览")
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.metric("总资产估值 (USDT)", f"${total_assets:,.2f}")
            
        with c2:
            # Breakdown Chart?
            if account_stats:
                df_acc = pd.DataFrame(account_stats)
                if not df_acc.empty and df_acc['balance'].sum() > 0:
                    fig = px.pie(df_acc, values='balance', names='alias', hole=0.4, title="账户资产分布")
                    fig.update_layout(height=200, margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)

    st.divider()

def trading_desk(mode_filter=None):
    # --- CSS Styles for Compact Layout ---
    st.markdown("""
    <style>
    /* Card-like button styling */
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] {
        gap: 0.5rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # --- Live Dashboard (Only for Live Mode) ---
    target_uid = st.session_state.get('viewing_user_id', st.session_state.user_id)
    if mode_filter == 'live':
        render_live_dashboard(target_uid)

    if 'selected_instance_id' not in st.session_state:
        st.session_state.selected_instance_id = None

    # --- Master-Detail Layout ---
    # Left: 25% (List), Right: 75% (Workspace)
    col_list, col_detail = st.columns([1, 3])
    
    # --- Left Column: Instance List ---
    with col_list:
        c_head, c_add = st.columns([3, 1])
        
        # Dynamic Title
        title_map = {'live': '实盘任务', 'backtest': '策略实验', None: '所有任务'}
        c_head.subheader(title_map.get(mode_filter, '任务列表'))
        
        if c_add.button("➕", help="创建新实例"):
            # Pass default mode to modal
            def_mode = mode_filter if mode_filter in ['live', 'testnet'] else 'backtest'
            create_instance_modal(default_mode=def_mode)
            
        session = db_manager.get_session()
        
        # Query Filtering
        target_uid = st.session_state.get('viewing_user_id', st.session_state.user_id)
        query = session.query(StrategyInstance).filter_by(user_id=target_uid)
        all_instances = query.order_by(StrategyInstance.created_at.desc()).all()
        
        filtered_instances = []
        for inst in all_instances:
            # Check Mode Logic
            if mode_filter == 'live':
                # Must be mode='live' AND account is live
                if inst.mode == 'live' and inst.account and inst.account.account_type == 'live':
                    filtered_instances.append(inst)
            elif mode_filter == 'backtest': # This is 'Strategy Lab'
                # Must be mode='backtest' OR (mode='live' AND account is testnet)
                if inst.mode == 'backtest':
                    filtered_instances.append(inst)
                elif inst.mode == 'live' and inst.account and inst.account.account_type == 'testnet':
                    filtered_instances.append(inst)
            else:
                filtered_instances.append(inst)
        
        instances = filtered_instances
        
        if not instances:
            st.info("暂无符合条件的实例")
        else:
            # Pre-load strategies for names
            loader = get_strategy_loader()
            strategies = loader.load_strategies()
            
            for inst in instances:
                # Get Status from Redis
                cached_status = redis_client.get_status(inst.id)
                status = inst.status
                if cached_status:
                    status = cached_status.get('status', status)

                is_selected = (inst.id == st.session_state.selected_instance_id)
                with st.container(border=True):
                    # --- Row 1: Basic Info (Symbol & Strategy) ---
                    # 标的 (Bold) -- 策略名 (Small)
                    strat_name = strategies.get(inst.strategy_name, {}).get('display_name', inst.strategy_name)
                    if len(strat_name) > 12: strat_name = strat_name[:11] + ".."
                    
                    st.markdown(f"**{inst.symbol}** <span style='color:#888; font-size:0.9em'>· {strat_name}</span>", unsafe_allow_html=True)

                    # --- Row 2: Mode & PnL & Status ---
                    # 测试类型 -- 盈亏
                    mode_label = "回测"
                    mode_color = "blue"
                    if inst.mode == 'live':
                        if 'testnet' in inst.config_json and '"testnet": true' in inst.config_json:
                            mode_label = "测试网"
                            mode_color = "orange"
                        else:
                            mode_label = "实盘"
                            mode_color = "red"
                    
                    # PnL
                    latest_eq = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.desc()).first()
                    pnl_str = "--"
                    pnl_color = "#888"
                    if latest_eq:
                        try:
                            cfg = json.loads(inst.config_json)
                            cap = float(cfg.get('sys', {}).get('capital', 10000000.0))
                            pnl = latest_eq.total_value - cap
                            roi = (pnl / cap) * 100
                            pnl_str = f"{roi:+.1f}%"
                            pnl_color = "#4caf50" if pnl >= 0 else "#ef5350"
                        except:
                            pass
                            
                    status_icon = "🟢" if status == 'RUNNING' else "🔴" if status in ['STOPPED', 'ERROR'] else "⚪"
                    
                    st.markdown(f"""
                    <div style='font-size:0.85em; margin-bottom:8px'>
                        <span style='color:{mode_color}; background:#333; padding:2px 4px; border-radius:3px'>{mode_label}</span>
                        &nbsp; <span style='color:{pnl_color}; font-weight:bold'>{pnl_str}</span>
                        &nbsp; <span style='float:right'>{status_icon} {status}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # --- Row 3: Actions (Start/Stop/Delete | Details) ---
                    # 布局: [操作按钮区] [详情按钮]
                    c_acts, c_det = st.columns([3, 1])
                    
                    with c_acts:
                        # Dynamic Buttons based on Status
                        if status == 'RUNNING':
                            if st.button("⏹ 停止", key=f"stop_btn_{inst.id}", help="停止运行", use_container_width=True):
                                process_manager.stop_instance(inst.id)
                                st.rerun()
                        else:
                            # Stopped/Error/Pending
                            ca1, ca2 = st.columns(2)
                            with ca1:
                                if st.button("▶ 启动", key=f"start_btn_{inst.id}", help="启动实例", use_container_width=True):
                                    process_manager.start_instance(inst.id)
                                    st.rerun()
                            with ca2:
                                if st.button("🗑 删除", key=f"del_btn_{inst.id}", help="删除实例数据", use_container_width=True):
                                    if db_manager.delete_instance_cascade(session, inst.id):
                                        st.success("已删除")
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error("删除失败")
                    
                    with c_det:
                        # Highlight if selected
                        # Streamlit button type only supports "primary" or "secondary"
                        btn_type = "primary" if is_selected else "secondary"
                        if st.button("详情", key=f"sel_btn_{inst.id}", type=btn_type, use_container_width=True):
                            st.session_state.selected_instance_id = inst.id
                            st.rerun()
        
        session.close()

    # --- Right Column: Detail Workspace ---
    with col_detail:
        if not st.session_state.selected_instance_id:
            # Empty State / Dashboard Overview
            st.markdown("""
            <div style='text-align: center; padding: 50px; color: #666;'>
                <h1>👋 欢迎来到量化工作台</h1>
                <p>请从左侧列表选择一个策略实例，或点击 ➕ 创建新实例。</p>
            </div>
            """, unsafe_allow_html=True)
            return

        # Fetch Selected Instance
        session = db_manager.get_session()
        inst = session.query(StrategyInstance).filter_by(id=st.session_state.selected_instance_id).first()
        session.close()
        
        if not inst:
            st.error("实例不存在或已被删除")
            st.session_state.selected_instance_id = None
            st.rerun()
            return

        # --- Detail View ---
        # 1. Minimal Header (Just Actions)
        # The Context is now fully on the left, so we just need controls here.
        with st.container():
            c_title, c_act = st.columns([6, 1])
            with c_title:
                 # Optional: Breadcrumb or minimal title if needed
                 # st.caption(f"Workspace: {inst.symbol}")
                 pass
            with c_act:
                 render_actions_fragment(inst.id)
        
        # 2. Main Chart Area
        if inst.mode == 'live':
            render_chart_fragment_static(inst.id, inst.symbol, inst.config_json, inst.strategy_name, inst.mode, inst.created_at)
        else:
            render_chart_fragment_static(inst.id, inst.symbol, inst.config_json, inst.strategy_name, inst.mode, inst.created_at)
            
        # 3. Metrics & Logs (Tabs)
        tab1, tab2, tab3, tab4 = st.tabs(["📊 绩效分析", "📈 核心指标", "📜 运行日志", "📋 交易明细"])
        
        with tab1:
            # --- Professional Performance Report Style ---
            session = db_manager.get_session()
            equity_recs = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.asc()).all()
            session.close()

            if equity_recs:
                df_eq = pd.DataFrame([{'Time': e.timestamp, 'Total': e.total_value} for e in equity_recs])
                df_eq['Time'] = pd.to_datetime(df_eq['Time'])
                df_eq.set_index('Time', inplace=True)
                
                # 1. Metrics Banner
                try:
                    cfg = json.loads(inst.config_json)
                    initial_cap = float(cfg.get('sys', {}).get('capital', 10000000.0))
                except:
                    initial_cap = df_eq['Total'].iloc[0] if not df_eq.empty else 10000.0

                current_eq = df_eq['Total'].iloc[-1]
                total_profit = current_eq - initial_cap
                total_return = (total_profit / initial_cap) * 100
                
                # Calculate Max Drawdown
                df_eq['Peak'] = df_eq['Total'].cummax()
                df_eq['Drawdown'] = (df_eq['Total'] - df_eq['Peak']) / df_eq['Peak']
                max_dd = df_eq['Drawdown'].min() * 100 # percentage

                # Layout Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("累计收益", f"${total_profit:,.2f}", f"{total_return:.2f}%")
                m2.metric("当前净值", f"${current_eq:,.2f}")
                m3.metric("最大回撤", f"{max_dd:.2f}%", help="历史最大回撤幅度")
                # m4.metric("夏普比率", "N/A", help="需更多数据计算") # Placeholder
                
                # 2. Equity Curve (Main Chart)
                st.markdown("#### 📈 收益率曲线")
                # Normalize to percentage return
                df_eq['ReturnPct'] = ((df_eq['Total'] - initial_cap) / initial_cap) * 100
                
                fig = px.line(df_eq, y='ReturnPct', x=df_eq.index, labels={'ReturnPct': '累计收益率 (%)', 'Time': '日期'})
                fig.update_traces(line_color='#ef5350', line_width=2) # Red line like the screenshot
                # Add Area for Drawdown? Or just simple line first
                fig.update_layout(
                    height=350, 
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="",
                    yaxis_title="收益率 (%)",
                    hovermode="x unified",
                    plot_bgcolor="#1e1e1e",
                    paper_bgcolor="#1e1e1e",
                    font=dict(color="#d1d4dc")
                )
                fig.update_xaxes(showgrid=True, gridcolor="#333")
                fig.update_yaxes(showgrid=True, gridcolor="#333")
                st.plotly_chart(fig, use_container_width=True)

                # 3. Monthly Returns Heatmap (The Table)
                st.markdown("#### 📅 月度收益表")
                
                # Resample to Monthly
                # Calculate monthly open and close
                monthly_df = df_eq['Total'].resample('ME').last()
                # Need to handle the first month correctly (compare to initial cap or prev month)
                # Simple approach: pct_change on monthly ends
                monthly_ret = monthly_df.pct_change().fillna(0) * 100
                
                # Handle first month explicitly if needed, but pct_change is okay for now
                # Pivot: Year vs Month
                monthly_data = []
                for dt, val in monthly_ret.items():
                    monthly_data.append({
                        "Year": dt.year,
                        "Month": dt.month,
                        "Return": val
                    })
                
                if monthly_data:
                    df_month = pd.DataFrame(monthly_data)
                    df_pivot = df_month.pivot(index='Year', columns='Month', values='Return')
                    
                    # Fill missing months
                    for m in range(1, 13):
                        if m not in df_pivot.columns:
                            df_pivot[m] = float('nan')
                    
                    # Reorder columns 1-12
                    df_pivot = df_pivot[sorted(df_pivot.columns)]
                    # Sort years desc
                    df_pivot = df_pivot.sort_index(ascending=False)
                    
                    # Add "Year Total"
                    # Approximate by summing monthly returns (simple) or calc from equity (accurate)
                    # Let's use simple sum for display
                    df_pivot['合计'] = df_pivot.sum(axis=1)

                    # Rename columns to 1月, 2月...
                    col_map = {m: f"{m}月" for m in range(1, 13)}
                    df_pivot.rename(columns=col_map, inplace=True)

                    # Styling
                    def color_return(val):
                        if pd.isna(val): return ""
                        color = "#4caf50" if val >= 0 else "#ef5350" # Green/Red
                        return f'color: {color}; font-weight: bold'

                    st.dataframe(
                        df_pivot.style.format("{:+.2f}%", na_rep="-").applymap(color_return),
                        use_container_width=True
                    )
                else:
                    st.info("数据不足以生成月报")

            else:
                st.info("暂无资金记录，策略运行一段时间后将生成报告。")

        with tab2:
            # PnL & Positions (Reuse logic but cleaner)
            c_pnl, c_pos = st.columns(2)
            with c_pnl:
                 render_pnl_fragment(inst.id, inst.config_json)
                 # Equity Chart
                 session = db_manager.get_session()
                 equity_recs = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.asc()).all()
                 if equity_recs:
                     df_eq = pd.DataFrame([{'Time': e.timestamp, 'Total': e.total_value} for e in equity_recs])
                     fig = px.line(df_eq, x='Time', y='Total')
                     fig.update_layout(height=250, margin=dict(l=0, r=0, t=20, b=0))
                     st.plotly_chart(fig, use_container_width=True)
                 session.close()
            
            with c_pos:
                 # Pie Chart logic
                 session = db_manager.get_session()
                 equity_recs = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.desc()).first()
                 if equity_recs:
                     pos_val = max(0, equity_recs.total_value - equity_recs.cash)
                     df_alloc = pd.DataFrame({'Asset': ['Cash', 'Position'], 'Value': [equity_recs.cash, pos_val]})
                     fig_pie = px.pie(df_alloc, values='Value', names='Asset', hole=0.6)
                     fig_pie.update_layout(height=250, margin=dict(l=0, r=0, t=20, b=0))
                     st.plotly_chart(fig_pie, use_container_width=True)
                 session.close()

        with tab2:
            render_log_fragment(inst.id, inst.log_path)
            
        with tab3:
            # Trades Table (Simplified)
            session = db_manager.get_session()
            trades = session.query(TradeRecord).filter_by(instance_id=inst.id).order_by(TradeRecord.timestamp.desc()).limit(100).all()
            if trades:
                df_t = pd.DataFrame([{
                    'Time': t.timestamp, 'Symbol': t.symbol, 'Side': t.side, 
                    'Price': t.price, 'Size': t.size, 'PnL': t.pnl
                } for t in trades])
                st.dataframe(df_t, use_container_width=True, height=300)
            else:
                st.info("暂无交易")
            session.close()

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
        
        with st.container(border=True):
            c_head, c_btn = st.columns([4, 1])
            c_head.markdown(f"### 📌 {display_name}")
            c_head.caption(f"Strategy ID: `{name}`")
            
            with st.expander("📖 查看详情与参数", expanded=False):
                st.markdown("#### 📝 策略说明")
                st.markdown(desc)
                st.divider()
                
                params_config = info.get('params_config', {})
                if params_config:
                    st.markdown("#### ⚙️ 参数定义")
                    p_data = [{"参数名": k, "显示名称": v.get('label', '-'), "说明": v.get('help', '-')} for k, v in params_config.items()]
                    st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)
                else:
                    st.info("该策略未定义详细参数元数据")

def optimization_lab():
    st.header("🛠️ 参数调优实验室")
    st.info("利用网格搜索 (Grid Search) 自动寻找策略的历史最优参数组合。")
    loader = get_strategy_loader()
    strategies = loader.load_strategies()
    with st.container(border=True):
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
            with st.container(border=True):
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

def admin_dashboard():
    st.title("🛡️ 管理员控制台")
    session = db_manager.get_session()
    
    # Global Tournament Stats
    st.subheader("⚔️ 锦标赛统计")
    with st.container(border=True):
        tm1, tm2, tm3 = st.columns(3)
        tm1.metric("锦标赛总数", session.query(Tournament).count())
        tm2.metric("运行中锦标赛", session.query(Tournament).filter_by(status='RUNNING').count())
        tm3.metric("待定锦标赛", session.query(Tournament).filter_by(status='PENDING').count())
    
    st.markdown("---")
    
    st.subheader("👥 用户与实例统计")
    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        m1.metric("用户总数", session.query(User).count())
        m2.metric("实例总数", session.query(StrategyInstance).count())
        m3.metric("运行中实例", session.query(StrategyInstance).filter_by(status='RUNNING').count())
    st.markdown("---")
    users = session.query(User).all()
    selected_username = st.sidebar.selectbox("选择用户", [u.username for u in users])
    user_obj = session.query(User).filter_by(username=selected_username).first()
    st.subheader(f"管理用户: {selected_username}")
    instances = session.query(StrategyInstance).filter_by(user_id=user_obj.id).all()
    if instances:
        df = pd.DataFrame([{'ID': i.id, 'Symbol': i.symbol, 'Strategy': i.strategy_name, 'Status': i.status, 'PID': i.pid} for i in instances])
        st.dataframe(df, use_container_width=True)
        target_id = st.selectbox("选择实例 ID", [i.id for i in instances])
        c1, c2 = st.columns(2)
        if c1.button("强制停止"):
            process_manager.stop_instance(target_id)
            st.success("停止信号已发送。")
        if c2.button("强制删除"):
            i_to_del = session.query(StrategyInstance).filter_by(id=target_id).first()
            if i_to_del:
                session.delete(i_to_del)
                session.commit()
                st.rerun()
    else:
        st.info("该用户无实例。")
    session.close()

def settings_page():
    st.header("⚙️ 系统设置")
    
    # --- Tab 1: Account Management ---
    st.subheader("🔑 交易所账户管理")
    st.info("配置您的交易所 API Key，用于实盘交易或测试网模拟。所有密钥均加密存储。")
    
    session = db_manager.get_session()
    user_id = st.session_state.get('viewing_user_id', st.session_state.user_id)
    
    # 1. List Existing Accounts
    accounts = db_manager.get_exchange_accounts(session, user_id)
    
    if accounts:
        for acc in accounts:
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 2, 1])
                c1.markdown(f"**{acc.alias}**")
                c2.markdown(f"`{acc.exchange}`")
                
                type_color = "orange" if acc.account_type == 'testnet' else "red"
                type_label = "测试网" if acc.account_type == 'testnet' else "实盘"
                c3.markdown(f":{type_color}[{type_label}]")
                
                c4.markdown(f"API Key: `***{acc.api_key_enc[-4:] if acc.api_key_enc else '****'}`")
                
                if c5.button("🗑 删除", key=f"del_acc_{acc.id}"):
                    try:
                        if db_manager.delete_exchange_account(session, acc.id, user_id):
                            st.success(f"账户 {acc.alias} 已删除")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("删除失败")
                    except ValueError as e:
                        st.error(str(e))
    else:
        st.info("暂无绑定的交易所账户。请在下方添加。")
    
    st.divider()
    
    # 2. Add New Account Form
    with st.expander("➕ 添加新账户", expanded=not accounts):
        with st.form("add_account_form"):
            c_alias, c_ex = st.columns(2)
            alias = c_alias.text_input("账户别名 (Alias)", placeholder="例如：Binance主号, 策略测试号1")
            exchange = c_ex.selectbox("交易所 (Exchange)", ["binance", "okx"], index=0)
            
            c_type, c_key = st.columns(2)
            acc_type = c_type.selectbox("账户类型", ["实盘 (Live)", "测试网 (Testnet)"])
            account_type_val = 'live' if "实盘" in acc_type else 'testnet'
            
            api_key = st.text_input("API Key", type="password")
            secret_key = st.text_input("Secret Key", type="password")
            
            submitted = st.form_submit_button("🔗 绑定账户")
            
            if submitted:
                if not alias or not api_key or not secret_key:
                    st.error("请填写完整信息")
                else:
                    try:
                        db_manager.add_exchange_account(
                            session, 
                            user_id, 
                            alias, 
                            api_key, 
                            secret_key, 
                            account_type=account_type_val, 
                            exchange=exchange
                        )
                        st.success(f"账户 {alias} 绑定成功！")
                        session.commit()
                        time.sleep(1)
                        st.rerun()
                    except ValueError as ve:
                        st.error(f"错误: {ve}")
                    except Exception as e:
                        st.error(f"系统错误: {e}")
    
    session.close()

def strategy_pk_arena():
    st.header("⚔️ 策略竞技场 (Strategy Arena)")
    st.info("通过多维度回测比拼，筛选出最优的 [策略 + 标的 + 周期] 组合。支持参数网格搜索与贝叶斯优化。")
    
    # --- 1. 发起挑战 ---
    session = db_manager.get_session()
    try:
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
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        session.close()
        
    st.divider()
    st.subheader("📊 历史战绩")
    session = db_manager.get_session()
    try:
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
    finally:
        session.close()

def market_page():
    # --- Top Bar: Title + Symbol Select ---
    with st.container():
        # Compact Header Layout
        c_title, c_sel, c_spacer = st.columns([1.5, 2, 8])
        
        with c_title:
            # Align with selectbox
            st.markdown("""
            <h3 style='
                margin: 0;
                padding: 0;
                line-height: 1.6;
                white-space: nowrap;
            '>📈 行情交易</h3>
            """, unsafe_allow_html=True)
            
        with c_sel:
            symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT", "XRP/USDT"]
            
            if 'market_selected_symbol' not in st.session_state:
                st.session_state.market_selected_symbol = symbols[0]
                
            def on_sym_change():
                st.session_state.market_selected_symbol = st.session_state.market_symbol_input
                
            selected_symbol = st.selectbox(
                "标的", 
                symbols, 
                index=symbols.index(st.session_state.market_selected_symbol) if st.session_state.market_selected_symbol in symbols else 0,
                label_visibility="collapsed",
                key="market_symbol_input",
                on_change=on_sym_change
            )
            st.session_state.market_selected_symbol = selected_symbol

    st.divider()

    # --- Main Content: Chart (Left) + Trading (Right) ---
    # Maximize Chart Space: 5:1 ratio (approx 83% vs 17%)
    c_chart, c_trade = st.columns([5, 1])
    
    # --- Chart Area ---
    with c_chart:
        import urllib.parse
        encoded_symbol = urllib.parse.quote(selected_symbol, safe='')
        frontend_url = f"http://localhost:5173/#/market/{encoded_symbol}"
        
        st.markdown(f"""
        <iframe src="{frontend_url}" width="100%" height="700" frameborder="0" style="border-radius: 5px; background-color: #1e1e1e;" sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe>
        """, unsafe_allow_html=True)

    # --- Trading Area ---
    with c_trade:
        st.subheader("下单操作")
        
        from src.utils.db_manager import db_manager
        session = db_manager.get_session()
        target_uid = st.session_state.get('viewing_user_id', st.session_state.user_id)
        accounts = db_manager.get_exchange_accounts(session, target_uid)
        session.close()
        
        if not accounts:
            st.error("请先配置账户")
        else:
            acc_opts = {a.id: f"{a.alias} ({a.account_type})" for a in accounts}
            sel_acc_id = st.selectbox("账户", list(acc_opts.keys()), format_func=lambda x: acc_opts[x])
            
            if sel_acc_id:
                sel_acc = next((a for a in accounts if a.id == sel_acc_id), None)
                if sel_acc:
                    # Helper to get exchange instance
                    def get_exchange_instance():
                        import ccxt
                        api_key = db_manager.decrypt_secret(sel_acc.api_key_enc)
                        secret_key = db_manager.decrypt_secret(sel_acc.secret_key_enc)
                        if api_key: api_key = api_key.strip()
                        if secret_key: secret_key = secret_key.strip()
                        is_testnet = (sel_acc.account_type == 'testnet')
                        exchange_id = sel_acc.exchange or 'binanceusdm'
                        if exchange_id == 'binance': exchange_class = ccxt.binanceusdm
                        else: exchange_class = getattr(ccxt, exchange_id)
                        
                        exchange_config = {
                            'apiKey': api_key, 'secret': secret_key,
                            'enableRateLimit': True, 'options': {'defaultType': 'future'}
                        }
                        # Proxy
                        import os
                        http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
                        https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
                        if http_proxy or https_proxy:
                            exchange_config['proxies'] = {'http': http_proxy, 'https': https_proxy}
                            
                        exchange = exchange_class(exchange_config)
                        if is_testnet: 
                            # Binance Futures Testnet (Manual Override)
                            # Explicitly set fapi endpoints to avoid sapi errors
                            exchange.urls['api'] = {
                                'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                                'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                                'public': 'https://testnet.binancefuture.com/fapi/v1',
                                'private': 'https://testnet.binancefuture.com/fapi/v1',
                                # Dummy sapi to pass CCXT checks
                                'sapi': 'https://testnet.binancefuture.com/fapi/v1',
                                'sapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                                'sapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                            }
                            # Disable fetchCurrencies to prevent calling Spot endpoints with Futures keys
                            exchange.has['fetchCurrencies'] = False
                        return exchange

                    with st.spinner("刷新余额..."):
                        try:
                            api_key = db_manager.decrypt_secret(sel_acc.api_key_enc)
                            secret_key = db_manager.decrypt_secret(sel_acc.secret_key_enc)
                            if api_key: api_key = api_key.strip()
                            if secret_key: secret_key = secret_key.strip()
                            is_testnet = (sel_acc.account_type == 'testnet')
                            bal = get_account_balance(api_key, secret_key, testnet=is_testnet)
                            st.caption(f"可用权益: **${bal:,.2f}**")
                        except Exception:
                                st.caption("余额获取失败")
                    
                    # --- Contract Settings (Leverage & Margin) ---
                    # Always expanded for visibility
                    with st.expander("⚙️ 杠杆/模式", expanded=True):
                        # Margin Type: Radio with Chinese labels (Horizontal)
                        margin_map = {"逐仓": "ISOLATED", "全仓": "CROSSED"}
                        margin_label = st.radio("保证金模式", list(margin_map.keys()), index=0, key="margin_type_radio", horizontal=True)
                        margin_type = margin_map[margin_label]
                        
                        # Leverage: Number Input
                        leverage = st.number_input("杠杆倍数 (x)", min_value=1, max_value=125, value=20, key="leverage_input")
                        
                        if st.button("应用设置", use_container_width=True, key="apply_settings_btn"):
                            try:
                                exchange = get_exchange_instance()
                                # Use standard CCXT Unified Symbol (BTC/USDT)
                                # exchange.load_markets() will handle the mapping
                                
                                # Set Leverage
                                exchange.set_leverage(leverage, selected_symbol)
                                # Set Margin Type
                                try:
                                    exchange.set_margin_type(margin_type, selected_symbol)
                                except Exception as e:
                                    # Ignore if already set or not supported
                                    pass
                                st.success(f"已设置: {margin_label} {leverage}x")
                            except Exception as e:
                                st.error(f"设置失败: {e}")
        
            tab_limit, tab_market = st.tabs(["限价", "市价"])
            
            with tab_limit:
                price = st.number_input("价格", min_value=0.0, step=0.1)
                qty = st.number_input("数量", min_value=0.001, step=0.001)
                
                c_buy, c_sell = st.columns(2)
                if c_buy.button("🟢 买入", use_container_width=True):
                    try:
                        ex = get_exchange_instance()
                        order = ex.create_limit_buy_order(selected_symbol, qty, price)
                        st.toast(f"Limit Buy {qty} @ {price} sent!", icon="🚀")
                    except Exception as e:
                        st.error(f"下单失败: {e}")
                        
                if c_sell.button("🔴 卖出", use_container_width=True):
                    try:
                        ex = get_exchange_instance()
                        order = ex.create_limit_sell_order(selected_symbol, qty, price)
                        st.toast(f"Limit Sell {qty} @ {price} sent!", icon="🔻")
                    except Exception as e:
                        st.error(f"下单失败: {e}")
                    

            with tab_market:
                qty_m = st.number_input("数量 (Market)", min_value=0.001, step=0.001)
                c_buy_m, c_sell_m = st.columns(2)
                if c_buy_m.button("🟢 市价买入", use_container_width=True):
                    try:
                        ex = get_exchange_instance()
                        order = ex.create_market_buy_order(selected_symbol, qty_m)
                        st.toast(f"Market Buy {qty_m} sent!", icon="🚀")
                    except Exception as e:
                        st.error(f"下单失败: {e}")
                        
                if c_sell_m.button("🔴 市价卖出", use_container_width=True):
                    try:
                        ex = get_exchange_instance()
                        order = ex.create_market_sell_order(selected_symbol, qty_m)
                        st.toast(f"Market Sell {qty_m} sent!", icon="🔻")
                    except Exception as e:
                        st.error(f"下单失败: {e}")

    st.divider()

    # --- Bottom: Order & Trade History ---
    # Compact Header with small Refresh Button
    c_head, c_btn, c_spacer = st.columns([1.5, 1, 8])
    with c_head:
        st.markdown("<h4 style='margin:0; padding-top:5px;'>📋 订单信息</h4>", unsafe_allow_html=True)
    with c_btn:
        # Small button next to header
        do_refresh = st.button("🔄 刷新", key="refresh_orders_btn")

    # Check if account selected
    if 'sel_acc' not in locals() or not sel_acc:
        st.info("请在右侧选择账户以查看订单信息")
    else:
        tab_open, tab_history = st.tabs(["当前委托 (Open Orders)", "历史成交 (Trade History)"])
        
        # Prepare API connection if needed
        def get_exchange():
            import ccxt
            api_key = db_manager.decrypt_secret(sel_acc.api_key_enc)
            secret_key = db_manager.decrypt_secret(sel_acc.secret_key_enc)
            
            if api_key: api_key = api_key.strip()
            if secret_key: secret_key = secret_key.strip()
            
            is_testnet = (sel_acc.account_type == 'testnet')
            
            # Default to binanceusdm if not specified
            exchange_id = sel_acc.exchange or 'binanceusdm'
            # Ensure we use the correct class
            if exchange_id == 'binance': 
                exchange_class = ccxt.binanceusdm
            else:
                exchange_class = getattr(ccxt, exchange_id)
            
            exchange_config = {
                'apiKey': api_key,
                'secret': secret_key,
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            }
            # Proxy
            import os
            http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
            https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
            if http_proxy or https_proxy:
                exchange_config['proxies'] = {'http': http_proxy, 'https': https_proxy}
                
            exchange = exchange_class(exchange_config)
            
            if is_testnet:
                # Binance Futures Testnet (Manual Override)
                exchange.urls['api'] = {
                    'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                    'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                    'public': 'https://testnet.binancefuture.com/fapi/v1',
                    'private': 'https://testnet.binancefuture.com/fapi/v1',
                    'sapi': 'https://testnet.binancefuture.com/fapi/v1',
                    'sapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                    'sapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                }
                exchange.has['fetchCurrencies'] = False
            return exchange

        with tab_open:
            if do_refresh or 'orders_cache' not in st.session_state:
                try:
                    exchange = get_exchange()
                    orders = exchange.fetch_open_orders(selected_symbol)
                    st.session_state.orders_cache = orders
                except Exception as e:
                    st.session_state.orders_cache = None
                    if do_refresh: st.error(f"获取委托失败: {e}")
            
            if st.session_state.get('orders_cache'):
                import pandas as pd
                df_orders = pd.DataFrame(st.session_state.orders_cache)
                cols = ['id', 'datetime', 'symbol', 'type', 'side', 'price', 'amount', 'filled', 'status']
                cols = [c for c in cols if c in df_orders.columns]
                st.dataframe(df_orders[cols], use_container_width=True)
            else:
                st.info("暂无活动委托")

        with tab_history:
            if do_refresh or 'trades_cache' not in st.session_state:
                try:
                    exchange = get_exchange()
                    trades = exchange.fetch_my_trades(selected_symbol, limit=20)
                    st.session_state.trades_cache = trades
                except Exception as e:
                    st.session_state.trades_cache = None
                    if do_refresh: st.error(f"获取成交失败: {e}")

            if st.session_state.get('trades_cache'):
                import pandas as pd
                df_trades = pd.DataFrame(st.session_state.trades_cache)
                cols = ['id', 'datetime', 'symbol', 'side', 'price', 'amount', 'cost', 'fee']
                cols = [c for c in cols if c in df_trades.columns]
                st.dataframe(df_trades[cols], use_container_width=True)
            else:
                st.info("近期无成交记录")


def user_dashboard():
    # --- Top Navigation ---
    # 使用 Radio 模拟顶部导航栏
    st.markdown("""
    <style>
    div.row-widget.stRadio > div {
        flex-direction: row;
        justify-content: flex-start;
        gap: 10px;
        padding-bottom: 10px;
        border-bottom: 1px solid #333;
        margin-bottom: 20px;
        overflow-x: auto;
    }
    div.row-widget.stRadio > div > label {
        background-color: #1e1e1e;
        border: 1px solid #333;
        padding: 5px 12px;
        border-radius: 5px;
        cursor: pointer;
        font-size: 0.9em;
        white-space: nowrap;
    }
    div.row-widget.stRadio > div > label:hover {
        border-color: #666;
        color: #4caf50;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # --- Admin User Switcher ---
    if st.session_state.role == 'admin':
        session = db_manager.get_session()
        users = db_manager.get_all_users(session)
        session.close()
        
        # Create a map of username -> id
        user_map = {u.username: u.id for u in users}
        user_options = list(user_map.keys())
        
        # Find current selection index
        current_view_id = st.session_state.get('viewing_user_id', st.session_state.user_id)
        # Find username for this id
        current_username = next((u for u, uid in user_map.items() if uid == current_view_id), st.session_state.username)
        
        try:
            idx = user_options.index(current_username)
        except ValueError:
            idx = user_options.index(st.session_state.username) if st.session_state.username in user_options else 0
            
        c_adm_1, c_adm_2 = st.columns([3, 1])
        with c_adm_1:
             st.info(f"🛡️ 管理员模式: 正在查看用户 [{current_username}] 的工作台")
        with c_adm_2:
             selected_user_name = st.selectbox("切换用户视图", user_options, index=idx, key="admin_user_switch")
             st.session_state.viewing_user_id = user_map[selected_user_name]
    else:
        # Reset if not admin
        if 'viewing_user_id' in st.session_state:
            del st.session_state['viewing_user_id']
    
    menu_map = {
        "📈 行情": "market",
        "🤖 实盘运行": "live",
        "🧪 策略实验": "lab",
        "🛠️ 策略调优": "opt",
        "⚔️ 策略PK": "arena",
        "📚 策略文库": "lib",
        "⚙️ 系统设置": "sys",
        "👤 账号信息": "account"
    }
    
    # Persist selection
    if 'top_nav' not in st.session_state:
        st.session_state.top_nav = "📈 行情"
        
    selected_label = st.radio("Main Menu", list(menu_map.keys()), label_visibility="collapsed", horizontal=True, key="top_nav_radio")
    page = menu_map[selected_label]
    
    # Helper to get target user ID
    target_uid = st.session_state.get('viewing_user_id', st.session_state.user_id)
    
    if page == "market":
        market_page()
    elif page == "live":
        trading_desk(mode_filter='live')
    elif page == "lab":
        trading_desk(mode_filter='backtest')
    elif page == "opt":
        optimization_lab()
    elif page == "arena":
        strategy_pk_arena()
    elif page == "lib":
        strategy_library()
    elif page == "sys":
        settings_page()
    elif page == "account":
        st.header("👤 账号信息")
        if st.session_state.role == 'admin':
             st.warning(f"当前登录: {st.session_state.username} (Admin)")
             st.info(f"当前查看: User ID {target_uid}")
        else:
             st.write(f"当前用户: **{st.session_state.username}**")
             st.write(f"角色: `{st.session_state.role}`")
        
        st.divider()
        if st.button("退出登录", type="primary"):
            st.session_state.user_id = None
            st.session_state.role = None
            if 'viewing_user_id' in st.session_state: del st.session_state['viewing_user_id']
            st.rerun()

def main():
    if not st.session_state.user_id:
        login_page()
    else:
        st.sidebar.markdown(f"### 👤 {st.session_state.username}")
        st.sidebar.markdown(f"Role: `{st.session_state.role}`")
        
        if st.sidebar.button("Logout"):
            st.session_state.user_id = None
            st.session_state.role = None
            if 'viewing_user_id' in st.session_state: del st.session_state['viewing_user_id']
            st.rerun()
        st.sidebar.markdown("---")
        
        user_dashboard()

if __name__ == '__main__':
    main()
