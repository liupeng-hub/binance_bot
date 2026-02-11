
import asyncio
import json
import os
import sys
import time
import hashlib
import uuid
import html
import glob
import psutil
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from nicegui import ui, app

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

from src.utils.db_manager import db_manager
from src.utils.db_models import User, StrategyInstance, ExchangeConfig, EquityRecord, TradeRecord, OptimizationJob
from src.utils.redis_client import redis_client
from src.utils.process_manager import process_manager
from src.utils.strategy_loader import StrategyLoader
from src.utils.data_helper import load_kline_data, calculate_indicators
from src.utils.account_helper import get_account_balance

# --- Global Config ---
# ui.colors moved to main_page to avoid conflict with @ui.page

# --- State Management ---
class AppState:
    def __init__(self):
        self.user = None
        self.active_page = 'dashboard'
        self.expanded_instances = set()
        self.applied_opt_config = None # Store optimized config for new instance

state = AppState()

# --- Helpers ---
def get_strategies():
    loader = StrategyLoader(os.path.join(current_dir, 'src', 'strategies'))
    return loader.load_strategies()

def format_currency(value):
    return f"${value:,.2f}"

# --- Navigation Helpers (Global) ---
def refresh_ui():
    """Force a page reload to update state/UI"""
    ui.open('/')

def navigate_to(page_name):
    """Global navigation helper (triggers reload)"""
    app.storage.client['active_page'] = page_name
    ui.open('/')

def logout():
    state.user = None
    app.storage.user.clear()
    ui.open('/')

# --- Auth Pages ---

def login_page():
    with ui.card().classes('absolute-center w-[400px] p-8 bg-[#262730] border border-gray-800'):
        ui.label('Quant SaaS Platform').classes('text-2xl font-bold text-center w-full mb-2 text-white')
        ui.label('专业量化交易系统').classes('text-sm text-center w-full mb-6 text-gray-400')
        
        with ui.tabs().classes('w-full text-white') as tabs:
            ui.tab('登录', icon='login')
            ui.tab('注册', icon='person_add')
        
        with ui.tab_panels(tabs, value='登录').classes('w-full bg-transparent'):
            # Login Panel
            with ui.tab_panel('登录'):
                username = ui.input('用户名').props('rounded outlined w-full dark').classes('mb-4')
                password = ui.input('密码', password=True).props('rounded outlined w-full dark').classes('mb-6')
                
                def try_login():
                    session = db_manager.get_session()
                    user = session.query(User).filter_by(username=username.value).first()
                    session.close()
                    if user:
                        # Simple hash check
                        pwd_hash = hashlib.sha256(password.value.encode()).hexdigest()
                        if user.password_hash == pwd_hash:
                            state.user = user
                            app.storage.user['user_id'] = user.id
                            ui.open('/') # Reload
                        else:
                            ui.notify('密码错误', type='negative')
                    else:
                        ui.notify('用户不存在', type='negative')

                ui.button('登录', on_click=try_login).props('w-full size=lg color=primary unelevated')

            # Register Panel
            with ui.tab_panel('注册'):
                new_user = ui.input('新用户名').props('rounded outlined w-full dark').classes('mb-4')
                new_pass = ui.input('设置密码', password=True).props('rounded outlined w-full dark').classes('mb-6')
                
                def try_register():
                    if not new_user.value or not new_pass.value:
                        ui.notify('请输入用户名和密码', type='warning')
                        return
                    
                    session = db_manager.get_session()
                    if session.query(User).filter_by(username=new_user.value).first():
                        ui.notify('用户名已存在', type='negative')
                    else:
                        pwd_hash = hashlib.sha256(new_pass.value.encode()).hexdigest()
                        user = User(username=new_user.value, password_hash=pwd_hash)
                        session.add(user)
                        session.commit()
                        ui.notify('注册成功！请登录', type='positive')
                        tabs.value = '登录'
                    session.close()
                
                ui.button('注册账号', on_click=try_register).props('w-full size=lg color=secondary unelevated')

# --- Layout & Navigation (SPA) ---

@ui.page('/')
def main_page():
    ui.colors(primary='#5898d4', secondary='#26a69a', accent='#ef5350', dark='#1e1e1e')
    
    # Global Error Handler for this client
    def handle_exception(e):
        ui.notify(f"Error: {str(e)}", type='negative')
        print(f"Runtime Error: {e}")
        import traceback
        traceback.print_exc()

    # Auth Check
    if not state.user:
        uid = app.storage.user.get('user_id')
        if uid:
            session = db_manager.get_session()
            try:
                user = session.query(User).filter_by(id=uid).first()
                if user: state.user = user
            except Exception as e:
                handle_exception(e)
            finally:
                session.close()

    if not state.user:
        login_page()
        return

    # Start Global Monitor (Only once per server ideally, but here per client connection is okay-ish or check if running)
    ui.timer(5.0, instance_monitor_task)

    # --- Navigation Logic ---
    # Use app.storage.client for tab-specific state
    if 'active_page' not in app.storage.client:
        app.storage.client['active_page'] = 'dashboard'

    content_container = None

    def navigate_spa(page_name):
        app.storage.client['active_page'] = page_name
        refresh_content()

    def refresh_content():
        if content_container:
            content_container.clear()
            page = app.storage.client.get('active_page', 'dashboard')
            try:
                with content_container:
                    if page == 'dashboard': dashboard_page()
                    elif page == 'trading_desk': trading_desk_page()
                    elif page == 'strategies': strategies_page()
                    elif page == 'optimization': optimization_page()
                    elif page == 'settings': settings_page()
                    else: ui.label('404 Page Not Found')
            except Exception as e:
                with content_container:
                    ui.label(f"Page Load Error: {e}").classes('text-red-500')
                handle_exception(e)

    def logout_handler():
        state.user = None
        app.storage.user.clear()
        ui.open('/') # Reload to show login

    # --- Layout Structure ---
    # Header
    with ui.header().classes('bg-[#262730] p-4 flex justify-between items-center border-b border-gray-700'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('show_chart', size='md', color='white')
            ui.label('Binance Quant Bot').classes('text-xl font-bold tracking-tight text-white')
        
        with ui.row().classes('items-center gap-4'):
            if state.user:
                ui.label(f'User: {state.user.username}').classes('text-sm text-gray-300 font-medium')
                ui.button('注销', on_click=logout_handler, icon='logout').props('flat round dense text-color=white')

    # Body
    with ui.row().classes('w-full h-screen bg-[#0e1117] text-white p-0 m-0 gap-0 no-wrap'):
        # Sidebar
        with ui.column().classes('w-64 h-full bg-[#262730] p-4 gap-2 pt-6 flex-shrink-0'):
            def nav_btn(label, icon, page_name):
                # Simple functional buttons
                btn = ui.button(icon=icon, on_click=lambda: navigate_spa(page_name))
                btn.props('flat align=left')
                btn.classes('text-left w-full rounded-md px-4 py-2 text-gray-300 hover:bg-[#31333F] hover:text-white transition-colors duration-200')
                with btn:
                    ui.label(label).classes('ml-3 text-sm')
            
            nav_btn('仪表盘', 'dashboard', 'dashboard')
            nav_btn('交易台', 'computer', 'trading_desk')
            nav_btn('策略库', 'library_books', 'strategies')
            nav_btn('参数调优', 'tune', 'optimization')
            nav_btn('设置', 'settings', 'settings')

        # Content Area
        with ui.column().classes('flex-grow h-full overflow-auto p-8 bg-[#0e1117]') as container:
            content_container = container
            refresh_content()

# --- Feature Pages ---

def dashboard_page():
    with ui.column().classes('w-full max-w-7xl mx-auto'):
        ui.label('仪表盘').classes('text-3xl font-bold mb-8 tracking-tight')
        
        session = db_manager.get_session()
        try:
            instances = session.query(StrategyInstance).filter_by(user_id=state.user.id).all()
            total_bots = len(instances)
            running_bots = sum(1 for i in instances if i.status == 'RUNNING')
            
            total_equity = 0.0
            initial_capital = 0.0
            
            for inst in instances:
                eq = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.desc()).first()
                try:
                    cfg = json.loads(inst.config_json)
                    cap = float(cfg.get('sys', {}).get('capital', 10000))
                except:
                    cap = 10000.0
                
                initial_capital += cap
                if eq:
                    total_equity += eq.total_value
                else:
                    total_equity += cap
            
            total_pnl = total_equity - initial_capital
            pnl_percent = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0
            
            # Fix: Filter trades by user_id
            recent_trades = session.query(TradeRecord).filter(TradeRecord.user_id == state.user.id).order_by(TradeRecord.timestamp.desc()).limit(10).all()
            
        except Exception as e:
            ui.notify(f"Dashboard Error: {e}", type='negative')
            total_bots, running_bots, total_equity, total_pnl, pnl_percent = 0, 0, 0, 0, 0
            recent_trades = []
        finally:
            session.close()

        # Metrics
        with ui.grid(columns=4).classes('w-full gap-6 mb-8'):
            def metric_card(title, value, sub_value=None, color='white'):
                with ui.card().classes('bg-[#262730] border border-gray-800 p-4 gap-1 shadow-sm'):
                    ui.label(title).classes('text-xs font-bold text-gray-400 uppercase tracking-wider')
                    ui.label(value).classes(f'text-2xl font-bold text-{color}')
                    if sub_value:
                        ui.label(sub_value).classes(f'text-xs text-{color} opacity-80')
            
            pnl_color = 'green-400' if total_pnl >= 0 else 'red-400'
            metric_card('总权益', format_currency(total_equity))
            metric_card('总盈亏', format_currency(total_pnl), f'{pnl_percent:+.2f}%', color=pnl_color)
            metric_card('活跃实例', str(running_bots), f'总计: {total_bots}')
            metric_card('风险敞口', '$0.00', 'Coming Soon')

        # Recent Activity
        ui.label('最近交易').classes('text-xl font-bold mb-4 tracking-tight')
        if recent_trades:
            with ui.row().classes('w-full px-4 py-2 bg-[#262730] border-b border-gray-700 text-gray-400 text-sm font-bold'):
                ui.label('时间').classes('w-1/5')
                ui.label('标的').classes('w-1/5')
                ui.label('方向').classes('w-1/5')
                ui.label('价格').classes('w-1/5')
                ui.label('数量').classes('w-1/5 text-right')
            
            for t in recent_trades:
                side_color = 'green-400' if t.side == 'BUY' else 'red-400'
                with ui.row().classes('w-full px-4 py-3 border-b border-gray-800 hover:bg-[#1e1e1e] transition-colors items-center text-sm'):
                    ui.label(t.timestamp.strftime('%Y-%m-%d %H:%M')).classes('w-1/5 text-gray-300')
                    # We can't access t.instance.symbol easily here due to session close.
                    # Simplified for now.
                    ui.label('Unknown').classes('w-1/5 text-white') 
                    ui.label(t.side).classes(f'w-1/5 font-bold text-{side_color}')
                    ui.label(f'{t.price:.4f}').classes('w-1/5 text-gray-300')
                    ui.label(f'{t.size:.4f}').classes('w-1/5 text-right text-gray-300')
        else:
            ui.label('暂无近期交易').classes('text-gray-500 italic')

def trading_desk_page():
    with ui.column().classes('w-full max-w-7xl mx-auto'):
        ui.label('交易台').classes('text-3xl font-bold mb-8 tracking-tight')
        
        # --- Part 0: Debug Info (System Log) ---
        with ui.expansion('🐞 Debug Console (系统日志)', icon='bug_report').classes('w-full mb-4 bg-[#262730] border border-gray-800 rounded'):
            log_dir = os.path.join(current_dir, 'logs', 'instances')
            if os.path.exists(log_dir):
                log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
                if log_files:
                    latest_log = log_files[0]
                    ui.label(f"最新日志: {os.path.basename(latest_log)}").classes('text-xs text-gray-400 mb-2')
                    try:
                        with open(latest_log, 'r') as f:
                            lines = f.readlines()[-20:]
                            ui.code("".join(lines), language='text').classes('w-full text-xs max-h-40 overflow-auto')
                    except Exception as e:
                        ui.label(f"无法读取日志: {e}").classes('text-red-500')
                else:
                    ui.label("暂无日志文件").classes('text-gray-500')
            else:
                ui.label("日志目录不存在").classes('text-yellow-500')

        # Action Bar
        with ui.row().classes('w-full mb-8 justify-between'):
            ui.button('创建新实例', icon='add', on_click=open_create_dialog).props('color=primary unelevated')
            ui.button('刷新列表', icon='refresh', on_click=refresh_ui).props('outline text-color=white')

        # Instance List
        session = db_manager.get_session()
        instances = session.query(StrategyInstance).filter_by(user_id=state.user.id).order_by(StrategyInstance.created_at.desc()).all()
        session.close()

        if not instances:
            with ui.column().classes('w-full items-center justify-center p-12 bg-[#262730] rounded-lg border border-gray-800'):
                ui.icon('inbox', size='4rem', color='grey-7')
                ui.label('暂无实例').classes('text-xl font-medium mt-4 text-gray-400')
            return

        for inst in instances:
            instance_card(inst)

def instance_card(inst):
    with ui.card().classes('w-full mb-6 bg-[#262730] border border-gray-800 p-0 rounded-lg shadow-none'):
        # Header
        with ui.row().classes('w-full p-5 items-center justify-between'):
            with ui.row().classes('items-center gap-4'):
                status_color = 'green-500' if inst.status == 'RUNNING' else ('red-500' if inst.status in ['STOPPED', 'ERROR'] else 'gray-500')
                with ui.row().classes(f'rounded-full px-2 py-1 bg-{status_color}/10 border border-{status_color}/20 items-center gap-2'):
                    ui.icon('circle', color=status_color.replace('-500', '')).classes('text-[8px]')
                    ui.label(inst.status).classes(f'text-xs font-bold text-{status_color}')
                
                with ui.column().classes('gap-0'):
                    with ui.row().classes('items-baseline gap-2'):
                        ui.label(inst.symbol).classes('text-lg font-bold tracking-wide')
                        ui.label(f'ID: {inst.id[:8]}').classes('text-xs text-gray-500 font-mono')
                    mode_color = 'text-red-400' if inst.mode == 'live' else 'text-blue-400'
                    ui.label(f'{inst.strategy_name} • {inst.mode.upper()}').classes(f'text-xs font-medium {mode_color}')
            
            with ui.row().classes('items-center gap-2'):
                if inst.status == 'RUNNING':
                    ui.button('停止', icon='stop', color='negative', on_click=lambda i=inst: stop_instance(i)).props('flat dense')
                else:
                    ui.button('启动', icon='play_arrow', color='positive', on_click=lambda i=inst: start_instance(i)).props('flat dense')
                ui.button('删除', icon='delete', color='grey', on_click=lambda i=inst: delete_instance(i)).props('flat dense')

        # Expansion
        with ui.expansion('详情 / 实时图表', icon='analytics').classes('w-full border-t border-gray-800') as expansion:
            expansion.props('header-class="bg-[#262730] text-gray-300 hover:text-white"')
            with ui.column().classes('w-full p-4 bg-[#1e1e1e]'):
                with ui.tabs().classes('w-full text-gray-400') as tabs:
                    ui.tab('图表', icon='show_chart')
                    ui.tab('资金', icon='attach_money')
                    ui.tab('交易', icon='list')
                    ui.tab('日志', icon='article')
                
                with ui.tab_panels(tabs, value='图表').classes('w-full bg-transparent'):
                    with ui.tab_panel('图表').classes('p-0 pt-4'):
                        render_highchart(inst)
                    with ui.tab_panel('资金').classes('p-0 pt-4'):
                        render_equity_chart(inst)
                    with ui.tab_panel('交易').classes('p-0 pt-4'):
                        render_trade_history(inst)
                    with ui.tab_panel('日志').classes('p-0 pt-4'):
                        render_logs(inst)

def strategies_page():
    with ui.column().classes('w-full max-w-7xl mx-auto'):
        ui.label('策略库').classes('text-3xl font-bold mb-8 tracking-tight')
        
        strategies = get_strategies()
        if not strategies:
            ui.label('暂无可用策略').classes('text-gray-500')
            return
            
        for name, info in strategies.items():
            with ui.card().classes('w-full mb-4 bg-[#262730] border border-gray-800 p-6'):
                with ui.row().classes('items-center justify-between mb-4'):
                    ui.label(info.get('display_name', name)).classes('text-xl font-bold text-white')
                    ui.label(name).classes('text-xs font-mono text-gray-500 bg-gray-900 px-2 py-1 rounded')
                
                desc = info.get('algo_description') or info.get('doc', '暂无说明')
                ui.markdown(desc).classes('text-gray-400 text-sm mb-4')
                
                with ui.expansion('参数说明', icon='settings').classes('w-full border border-gray-700 rounded'):
                    params_config = info.get('params_config', {})
                    if params_config:
                        with ui.grid(columns=3).classes('w-full p-4 gap-4'):
                            for k, v in params_config.items():
                                with ui.column().classes('bg-[#1e1e1e] p-2 rounded'):
                                    ui.label(k).classes('text-xs font-bold text-primary')
                                    ui.label(v.get('label', '-')).classes('text-sm text-white')
                                    ui.label(v.get('help', '-')).classes('text-xs text-gray-500')

def optimization_page():
    with ui.column().classes('w-full max-w-7xl mx-auto'):
        ui.label('参数调优实验室').classes('text-3xl font-bold mb-8 tracking-tight')
        ui.label('利用网格搜索或贝叶斯优化寻找策略的最佳参数组合。').classes('text-gray-400 mb-6')

        # --- Job List & Results ---
        with ui.card().classes('w-full bg-[#262730] border border-gray-800 p-0 mb-8'):
            with ui.row().classes('p-4 border-b border-gray-700 justify-between items-center'):
                ui.label('任务列表').classes('text-lg font-bold')
                ui.button('刷新', icon='refresh', on_click=refresh_ui).props('flat dense')
            
            session = db_manager.get_session()
            jobs = session.query(OptimizationJob).filter_by(user_id=state.user.id).order_by(OptimizationJob.created_at.desc()).all()
            session.close()

            if not jobs:
                ui.label('暂无优化任务').classes('p-8 text-center text-gray-500 w-full')
            else:
                with ui.column().classes('w-full p-0 gap-0'):
                    for job in jobs:
                        with ui.expansion('').classes('w-full border-b border-gray-800') as exp:
                            # Header
                            with exp.add_slot('header'):
                                with ui.row().classes('w-full items-center justify-between'):
                                    with ui.row().classes('items-center gap-4'):
                                        status_color = 'green-500' if job.status == 'COMPLETED' else ('blue-500' if job.status == 'RUNNING' else 'red-500')
                                        ui.icon('circle', color=status_color.replace('-500', '')).classes('text-[8px]')
                                        
                                        with ui.column().classes('gap-0'):
                                            ui.label(f"{job.symbol} - {job.strategy_name}").classes('font-bold text-md')
                                            sys_cfg = json.loads(job.sys_config)
                                            algo = 'Bayesian' if sys_cfg.get('algorithm') == 'optuna' else 'Grid Search'
                                            ui.label(f"{algo} • {sys_cfg.get('timeframe')} • {sys_cfg.get('days')} Days").classes('text-xs text-gray-400')
                                    
                                    ui.label(job.created_at.strftime('%Y-%m-%d %H:%M')).classes('text-xs text-gray-500')
                            
                            # Content
                            with ui.column().classes('w-full p-4 bg-[#1e1e1e]'):
                                if job.status == 'RUNNING':
                                    ui.linear_progress(value=float(job.progress or 0)/100.0).classes('w-full mb-2')
                                    ui.label(f'Progress: {job.progress}%').classes('text-xs text-blue-400')
                                elif job.status == 'COMPLETED' and job.result_json:
                                    results = json.loads(job.result_json)
                                    if results:
                                        best = results[0]
                                        metrics = best['metrics']
                                        params = best['params']
                                        
                                        with ui.row().classes('w-full gap-4 mb-4 items-start'):
                                            with ui.card().classes('bg-green-900/20 border border-green-500/30 p-4 flex-1'):
                                                ui.label('最佳收益').classes('text-xs text-green-400')
                                                ui.label(f"${metrics['net_profit']:.2f} ({metrics['return_rate']:.2f}%)").classes('text-xl font-bold text-white')
                                            
                                            with ui.card().classes('bg-gray-800 p-4 flex-[2]'):
                                                ui.label('最佳参数').classes('text-xs text-gray-400')
                                                ui.label(", ".join([f"{k}={v}" for k, v in params.items()])).classes('text-sm font-mono text-white break-all')
                                            
                                            def apply_params(j=job, p=params, s=sys_cfg):
                                                state.applied_opt_config = {
                                                    'strategy': j.strategy_name,
                                                    'symbol': j.symbol,
                                                    'params': p,
                                                    'sys': s
                                                }
                                                ui.notify('参数已应用！请前往“交易台”创建新实例', type='positive')
                                                # Optional: redirect
                                                # navigate_to('trading_desk') 

                                            with ui.row().classes('h-full gap-2'):
                                                ui.button('应用参数', icon='input', on_click=apply_params).props('outline color=primary').classes('h-full')
                                                
                                                def download_csv(j=job, r=results):
                                                    df = pd.DataFrame([dict(x['params'], **x['metrics']) for x in r])
                                                    # Rename columns to match Lite
                                                    df.rename(columns={'net_profit': '净利润', 'return_rate': '收益率(%)', 'max_drawdown': '最大回撤(%)', 'win_rate': '胜率', 'total_trades': '交易次数'}, inplace=True)
                                                    csv_bytes = df.to_csv(index=False).encode('utf-8')
                                                    ui.download(csv_bytes, f"opt_results_{j.id[:8]}.csv")

                                                ui.button('下载 CSV', icon='download', on_click=download_csv).props('outline').classes('h-full')

                                        # Table of top results
                                        df_res = pd.DataFrame([dict(r['params'], **r['metrics']) for r in results])
                                        # Rename for display
                                        df_res.rename(columns={'net_profit': 'Profit', 'return_rate': 'Return%', 'max_drawdown': 'MaxDD%', 'win_rate': 'WinRate'}, inplace=True)
                                        
                                        ui.label('Top Results').classes('text-sm font-bold mb-2')
                                        ui.aggrid({
                                            'columnDefs': [{'field': c} for c in df_res.columns],
                                            'rowData': df_res.head(20).to_dict('records'),
                                            'defaultColDef': {'flex': 1, 'resizable': True}
                                        }).classes('w-full h-64 theme-ag-theme-balham-dark')

        # --- Create New Job ---
        with ui.expansion('新建调优任务', icon='add_circle', value=True).classes('w-full bg-[#262730] border border-gray-800 rounded'):
            with ui.column().classes('w-full p-6 gap-6'):
                strategies = get_strategies()
                strat_names = list(strategies.keys())
                
                with ui.grid(columns=2).classes('w-full gap-6'):
                    s_select = ui.select(strat_names, label='选择策略').props('outlined dark').classes('w-full')
                    symbol_input = ui.input('交易标的', value='BTC/USDT').props('outlined dark').classes('w-full')
                
                algo_select = ui.radio(['Grid Search (网格搜索)', 'Bayesian (贝叶斯优化 - Optuna)'], value='Grid Search (网格搜索)').props('row')
                
                # Dynamic Params Config
                params_container = ui.column().classes('w-full gap-2 border border-gray-700 p-4 rounded')
                opt_config_store = {} # Store refs to inputs

                def update_opt_ui(strat_name):
                    params_container.clear()
                    opt_config_store.clear()
                    
                    if not strat_name or strat_name not in strategies: return
                    
                    info = strategies[strat_name]
                    default_params = info.get('params', {})
                    p_config = info.get('params_config', {})
                    
                    with params_container:
                        ui.label('参数范围配置').classes('text-sm font-bold text-primary mb-2')
                        for key, val in default_params.items():
                            if isinstance(val, (int, float)):
                                label = p_config.get(key, {}).get('label', key)
                                with ui.row().classes('w-full items-center gap-2'):
                                    ui.label(f"{label} ({key})").classes('w-32 text-sm')
                                    start = ui.number('Start', value=val).props('outlined dense dark').classes('w-24')
                                    end = ui.number('End', value=val).props('outlined dense dark').classes('w-24')
                                    step = ui.number('Step', value=1 if isinstance(val, int) else 0.1).props('outlined dense dark').classes('w-24')
                                    
                                    opt_config_store[key] = {'start': start, 'end': end, 'step': step, 'type': type(val)}

                s_select.on_value_change(lambda e: update_opt_ui(e.value))

                # Sys Config
                with ui.row().classes('w-full gap-4'):
                    tf_select = ui.select(['1h', '4h', '1d', '15m'], value='1h', label='K线周期').props('outlined dark').classes('w-32')
                    days_input = ui.number('历史天数', value=30).props('outlined dark').classes('w-32')
                    trials_input = ui.number('试验次数 (Optuna)', value=50).props('outlined dark').classes('w-40')
                    # Hide trials if Grid
                    algo_select.on_value_change(lambda e: trials_input.set_visibility('Optuna' in e.value))
                    trials_input.set_visibility(False) # Default Grid

                def start_opt():
                    if not s_select.value:
                        ui.notify('请选择策略', type='warning')
                        return
                    
                    # Build Config
                    opt_conf = {}
                    is_optuna = 'Optuna' in algo_select.value
                    
                    for k, inputs in opt_config_store.items():
                        s, e, st = inputs['start'].value, inputs['end'].value, inputs['step'].value
                        if s != e:
                            opt_conf[k] = {
                                'start': s, 'end': e, 
                                'step': st if not is_optuna else None,
                                'type': 'int' if inputs['type'] is int else 'float'
                            }
                    
                    if not opt_conf:
                        ui.notify('请至少配置一个变化的参数', type='warning')
                        return

                    session = db_manager.get_session()
                    job_id = str(uuid.uuid4())
                    sys_cfg = {
                        'timeframe': tf_select.value, 
                        'days': int(days_input.value), 
                        'capital': 10000.0,
                        'algorithm': 'optuna' if is_optuna else 'grid',
                        'n_trials': int(trials_input.value)
                    }
                    
                    job = OptimizationJob(
                        id=job_id, user_id=state.user.id, strategy_name=s_select.value, symbol=symbol_input.value,
                        params_config=json.dumps(opt_conf), sys_config=json.dumps(sys_cfg), status='PENDING'
                    )
                    session.add(job)
                    session.commit()
                    session.close()
                    
                    process_manager.start_optimization(job_id)
                    ui.notify('优化任务已提交', type='positive')
                    refresh_ui()

                ui.button('🚀 开始优选', on_click=start_opt).props('color=primary unelevated').classes('w-full mt-4')

def settings_page():
    with ui.column().classes('w-full max-w-7xl mx-auto'):
        ui.label('系统设置').classes('text-3xl font-bold mb-8 tracking-tight')
        
        with ui.card().classes('w-full max-w-3xl bg-[#262730] border border-gray-800 p-8'):
            ui.label('交易所 API 配置').classes('text-xl font-bold mb-6 text-white')
            
            # Load existing config
            session = db_manager.get_session()
            config = session.query(ExchangeConfig).filter_by(user_id=state.user.id).first()
            
            has_real = bool(config and config.api_key_enc)
            has_test = bool(config and config.testnet_api_key_enc)
            session.close()

            # Real Net
            ui.label('实盘交易 (Real Trading)').classes('text-sm font-bold text-primary mb-2')
            api_key = ui.input('API Key').props('outlined rounded dense dark').classes('w-full mb-2')
            secret_key = ui.input('Secret Key', password=True).props('outlined rounded dense dark').classes('w-full mb-2')
            if has_real:
                ui.label('✅ 已配置实盘 Key').classes('text-xs text-green-500 mb-4')
            else:
                ui.label('⚠️ 未配置').classes('text-xs text-gray-500 mb-4')

            # Test Net
            ui.separator().classes('my-4 bg-gray-700')
            ui.label('测试网 (Testnet)').classes('text-sm font-bold text-secondary mb-2')
            test_api_key = ui.input('Testnet API Key').props('outlined rounded dense dark').classes('w-full mb-2')
            test_secret_key = ui.input('Testnet Secret Key', password=True).props('outlined rounded dense dark').classes('w-full mb-2')
            if has_test:
                ui.label('✅ 已配置测试网 Key').classes('text-xs text-green-500 mb-4')

            def save_keys():
                session = db_manager.get_session()
                cfg = session.query(ExchangeConfig).filter_by(user_id=state.user.id).first()
                if not cfg:
                    cfg = ExchangeConfig(user_id=state.user.id)
                    session.add(cfg)
                
                if api_key.value: cfg.api_key_enc = db_manager.encrypt_secret(api_key.value)
                if secret_key.value: cfg.secret_key_enc = db_manager.encrypt_secret(secret_key.value)
                if test_api_key.value: cfg.testnet_api_key_enc = db_manager.encrypt_secret(test_api_key.value)
                if test_secret_key.value: cfg.testnet_secret_key_enc = db_manager.encrypt_secret(test_secret_key.value)
                
                session.commit()
                session.close()
                ui.notify('配置已保存', type='positive')
                # Clear inputs for security
                api_key.value = ''
                secret_key.value = ''
                refresh_ui()

            ui.button('保存配置', on_click=save_keys).props('color=primary unelevated').classes('mt-4')

# --- Dialogs ---

def open_create_dialog():
    with ui.dialog() as dialog, ui.card().classes('w-[800px] bg-[#1e1e1e] border border-gray-700 p-6'):
        with ui.row().classes('w-full items-center justify-between mb-4'):
            ui.label('创建新策略实例').classes('text-xl font-bold text-white')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense text-color=white')
        
        strategies = get_strategies()
        strat_names = list(strategies.keys())
        
        # Check for applied config
        applied = state.applied_opt_config
        def_strat = strat_names[0] if strat_names else None
        def_symbol = 'BTC/USDT'
        def_tf = '1m'
        def_days = 30
        
        if applied:
            if applied['strategy'] in strat_names:
                def_strat = applied['strategy']
            def_symbol = applied.get('symbol', 'BTC/USDT')
            def_tf = applied.get('sys', {}).get('timeframe', '1m')
            def_days = int(applied.get('sys', {}).get('days', 30))
            ui.notify('已加载优化参数', type='info')
        
        # Grid Layout
        with ui.grid(columns=2).classes('w-full gap-8'):
            # Left Col: Selection & Basic
            with ui.column().classes('w-full gap-4'):
                s_select = ui.select(strat_names, value=def_strat, label='选择策略').props('outlined dark').classes('w-full')
                symbol_input = ui.input('交易标的', value=def_symbol).props('outlined dark').classes('w-full')
                
                # Execution Mode (Match Lite)
                mode_map = {
                    "📉 模拟回测 (历史数据)": ('backtest', True),
                    "🧪 测试网实盘 (虚拟资金)": ('live', True),
                    "💰 正式网实盘 (真实资金)": ('live', False)
                }
                mode_keys = list(mode_map.keys())
                exec_mode = ui.select(mode_keys, value=mode_keys[0], label='执行模式').props('outlined dark').classes('w-full')
                
                # Real Trading Warning
                warning_banner = ui.row().classes('w-full bg-red-900/30 border border-red-500/50 p-3 rounded items-center gap-2 hidden')
                with warning_banner:
                    ui.icon('warning', color='red-400')
                    ui.label('注意：您选择了正式网实盘模式，将使用真实资金交易！').classes('text-red-400 text-sm font-bold')

                def on_mode_change(e):
                    mode, is_test = mode_map[e.value]
                    # Show warning only for Real Live
                    warning_banner.set_visibility(not is_test and mode == 'live')
                
                exec_mode.on_value_change(on_mode_change)
                
                # Dynamic Description Area
                with ui.expansion('策略说明', icon='description', value=True).classes('w-full border border-gray-800 rounded'):
                    desc_area = ui.markdown('请选择策略...').classes('text-sm text-gray-400 p-2')

            # Right Col: Config
            with ui.column().classes('w-full gap-4'):
                with ui.tabs().classes('w-full text-gray-300') as conf_tabs:
                    ui.tab('系统参数', icon='settings')
                    ui.tab('策略参数', icon='tune')
                
                with ui.tab_panels(conf_tabs).classes('w-full bg-transparent border border-gray-800 rounded p-4 h-[350px] overflow-auto'):
                    # Sys Params
                    with ui.tab_panel('系统参数'):
                        tf_select = ui.select(['1m', '5m', '15m', '1h', '4h', '1d'], value=def_tf, label='K线周期').props('outlined dark').classes('w-full mb-2')
                        days_input = ui.number('历史天数', value=def_days, precision=0).props('outlined dark').classes('w-full mb-2')
                        
                        # Capital & Balance Fetch
                        capital_input = ui.number('初始资金 (USDT)', value=10000).props('outlined dark').classes('w-full mb-2')
                        # is_testnet checkbox removed, controlled by mode select
                        
                        async def fetch_balance():
                            session = db_manager.get_session()
                            cfg = session.query(ExchangeConfig).filter_by(user_id=state.user.id).first()
                            session.close()
                            
                            current_mode, current_is_test = mode_map[exec_mode.value]
                            
                            ak, sk = None, None
                            if cfg:
                                if current_is_test:
                                    ak = db_manager.decrypt_secret(cfg.testnet_api_key_enc)
                                    sk = db_manager.decrypt_secret(cfg.testnet_secret_key_enc)
                                else:
                                    ak = db_manager.decrypt_secret(cfg.api_key_enc)
                                    sk = db_manager.decrypt_secret(cfg.secret_key_enc)
                            
                            if not ak or not sk:
                                ui.notify('未配置 API Key', type='warning')
                                return

                            ui.notify('正在获取余额...', type='info')
                            bal = await asyncio.to_thread(get_account_balance, ak, sk, current_is_test)
                            if bal > 0:
                                capital_input.value = bal
                                ui.notify(f'已更新余额: {bal:.2f} USDT', type='positive')
                            else:
                                ui.notify('余额为 0 或获取失败', type='warning')

                        ui.button('从交易所读取余额', on_click=fetch_balance, icon='account_balance_wallet').props('outline text-color=primary').classes('w-full mt-2')

                    # Strat Params
                    with ui.tab_panel('策略参数'):
                        params_container = ui.column().classes('w-full gap-2')
        
        current_params = {}

        def update_ui(strat_name):
            if not strat_name or strat_name not in strategies:
                return
            
            info = strategies[strat_name]
            desc = info.get('algo_description') or info.get('doc', '暂无说明')
            desc_area.set_content(desc)
            
            params_container.clear()
            current_params.clear()
            
            default_params = info.get('params', {})
            params_config = info.get('params_config', {})
            
            # Check if we should use applied params
            use_applied = (applied and applied['strategy'] == strat_name)
            
            with params_container:
                for key, val in default_params.items():
                    label = params_config.get(key, {}).get('label', key)
                    help_txt = params_config.get(key, {}).get('help', '')
                    
                    final_val = val
                    if use_applied and key in applied['params']:
                        final_val = applied['params'][key]
                    
                    if isinstance(val, bool):
                        sw = ui.switch(text=label, value=final_val).tooltip(help_txt)
                        sw.bind_value(current_params, key)
                        current_params[key] = final_val
                    elif isinstance(val, (int, float)):
                        num = ui.number(label=label, value=final_val).props('outlined dark dense').tooltip(help_txt).classes('w-full')
                        num.bind_value(current_params, key)
                        current_params[key] = final_val
                    else:
                        inp = ui.input(label=label, value=str(final_val)).props('outlined dark dense').tooltip(help_txt).classes('w-full')
                        inp.bind_value(current_params, key)
                        current_params[key] = final_val

        s_select.on_value_change(lambda e: update_ui(e.value))
        # Initial trigger
        update_ui(s_select.value)

        def create():
            if not s_select.value:
                ui.notify('请选择策略', type='warning')
                return
            
            session = db_manager.get_session()
            new_id = str(uuid.uuid4())
            
            final_mode, final_is_test = mode_map[exec_mode.value]
            
            conf = {
                'params': current_params,
                'sys': {
                    'timeframe': tf_select.value,
                    'days': int(days_input.value),
                    'capital': float(capital_input.value),
                    'testnet': final_is_test
                }
            }
            
            inst = StrategyInstance(
                id=new_id,
                user_id=state.user.id,
                symbol=symbol_input.value,
                strategy_name=s_select.value,
                config_json=json.dumps(conf),
                mode=final_mode,
                status='PENDING'
            )
            session.add(inst)
            session.commit()
            session.close()
            
            ui.notify('实例创建成功！正在后台启动...', type='positive')
            dialog.close()
            
            # Clear applied config
            state.applied_opt_config = None
            
            # Async start
            asyncio.create_task(async_start(new_id, inst.symbol))
            refresh_ui()

        async def async_start(inst_id, symbol):
            success, msg = await asyncio.to_thread(process_manager.start_instance, inst_id)
            if success:
                ui.notify(f'{symbol} 启动成功', type='positive')
            else:
                ui.notify(f'{symbol} 启动失败: {msg}', type='negative')

        ui.button('立即创建并运行', on_click=create).props('color=primary unelevated').classes('w-full mt-6')
    
    dialog.open()

# --- Charting Logic ---

# Global background task to monitor instances
def instance_monitor_task():
    session = db_manager.get_session()
    try:
        instances = session.query(StrategyInstance).filter_by(status='RUNNING').all()
        for inst in instances:
            # Check Redis status first
            cached = redis_client.get_status(inst.id)
            if cached and cached.get('status') != 'RUNNING':
                inst.status = cached.get('status')
                session.commit()
                continue
            
            # Check PID
            if inst.pid:
                if not psutil.pid_exists(inst.pid):
                    inst.status = 'STOPPED' if inst.mode == 'live' else 'COMPLETED'
                    inst.pid = None
                    session.commit()
                    redis_client.publish_status(inst.id, {'status': inst.status, 'pid': None})
    except Exception as e:
        print(f"Monitor error: {e}")
    finally:
        session.close()

# ui.timer(5.0, instance_monitor_task) # Cannot define global UI element with @ui.page

def render_highchart(inst):
    try:
        config = json.loads(inst.config_json)
        tf = config.get('sys', {}).get('timeframe', '1m')
    except:
        tf = '1m'
    df = load_kline_data(inst.symbol, limit=500, timeframe=tf)
    if df.empty:
        ui.label('暂无 K 线数据').classes('text-gray-500')
        return
    main_overlays, sub_charts = calculate_indicators(df, inst.strategy_name, inst.config_json)
    session = db_manager.get_session()
    trades = session.query(TradeRecord).filter_by(instance_id=inst.id).all()
    session.close()
    markers = []
    for t in trades:
        color = '#ef5350' if t.side in ['SHORT', 'SELL'] else '#26a69a'
        text = f"{t.side} @ {t.price}"
        shape = 'arrowDown' if color == '#ef5350' else 'arrowUp'
        position = 'aboveBar' if color == '#ef5350' else 'belowBar'
        ts = int(t.timestamp.timestamp())
        markers.append({'time': ts, 'position': position, 'color': color, 'shape': shape, 'text': text})
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
    overlays_json = json.dumps(_normalize(main_overlays))
    subcharts_json = json.dumps(_normalize(sub_charts))
    markers_json = json.dumps(_normalize(markers))
    cid = inst.id
    html_tpl = """
    <div id=\"lc_main___CID__\" style=\"height: 420px;\"></div>
    <div id=\"lc_sub___CID__\" style=\"height: 160px; margin-top:6px;\"></div>
    __LC_BOOTSTRAP__
    <script>
    const LC = window.LightweightCharts;
    if(!LC || typeof LC.createChart !== 'function'){ console.error('LightweightCharts not available'); return; }
    const mEl = document.getElementById('lc_main___CID__');
    const chart = LC.createChart(mEl, { layout: { background: { color: '#0e1117' }, textColor: '#d1d4dc' }, grid: { vertLines: { color: '#31333F' }, horzLines: { color: '#31333F' } }, height: 400 });
    if(!chart){ console.error('Chart instance unavailable'); return; }
    let series;
    if (typeof chart.addCandlestickSeries === 'function') {
      series = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
    } else if (typeof chart.addBarSeries === 'function') {
      console.warn('Candlestick not available, falling back to BarSeries');
      series = chart.addBarSeries({ upColor: '#26a69a', downColor: '#ef5350' });
    } else if (typeof chart.addLineSeries === 'function') {
      console.warn('Candlestick/Bar not available, falling back to LineSeries');
      series = chart.addLineSeries({ color: '#26a69a', lineWidth: 2 });
    } else {
      console.error('Chart API unavailable');
      return;
    }
    const initialFallback = __INITIAL__;
    if (initialFallback && initialFallback.length) {
      series.setData(initialFallback);
    }
    fetch('http://localhost:8000/api/candles?inst_id=__CID__&limit=500').then(r => r.json()).then(data => {
      const initial = data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }));
      console.log('LC initial candles', initial.length, initial[0], initial[initial.length-1]);
      if (initial.length) { series.setData(initial); }
      const overlays = __OVERLAYS__;
      overlays.forEach(ov => {
        const color = (ov.options && ov.options.color) ? ov.options.color : '#ffeb3b';
        const lw = (ov.options && ov.options.lineWidth) ? ov.options.lineWidth : 1;
        const ls = chart.addLineSeries({ color: color, lineWidth: lw });
        const data = ov.data.map(d => ({ time: d.time, value: d.value })).filter(p => p.value !== null && p.value !== undefined);
        ls.setData(data);
      });
      const markers = __MARKERS__;
      try { series.setMarkers(markers); } catch (e) {}
      const subs = __SUBS__;
      if (subs && subs.length) {
        const sEl = document.getElementById('lc_sub___CID__');
        const chart2 = LC.createChart(sEl, { layout: { background: { color: '#0e1117' }, textColor: '#d1d4dc' }, grid: { vertLines: { color: '#31333F' }, horzLines: { color: '#31333F' } }, height: subs[0].height || 150 });
        subs.forEach(sub => {
          sub.series.forEach(s => {
            const scolor = (s.options && s.options.color) ? s.options.color : (s.type === 'Histogram' ? '#26a69a' : '#fff');
            const slw = (s.options && s.options.lineWidth) ? s.options.lineWidth : 1;
            const ss = s.type === 'Histogram' ? chart2.addHistogramSeries({ color: scolor }) : chart2.addLineSeries({ color: scolor, lineWidth: slw });
            const data = s.data.map(d => ({ time: d.time, value: d.value })).filter(p => p.value !== null && p.value !== undefined);
            ss.setData(data);
          });
        });
        try { chart.timeScale().fitContent(); } catch(e) {}
      }
    });
    let ws;
    function connectWS() {
      ws = new WebSocket('ws://localhost:8000/ws/candles/__CID__');
      ws.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        if (d && d.type === 'candle' && d.data) {
          const c = d.data;
          if (series.update) {
            if (c.open !== undefined) {
              series.update({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });
            } else if (c.value !== undefined) {
              series.update({ time: c.time, value: c.value });
            }
          }
        }
      };
      ws.onclose = () => { setTimeout(connectWS, 2000); };
      ws.onerror = () => { try { ws.close(); } catch (e) {} };
    }
    connectWS();
    </script>
    """
    # Inline Lightweight Charts to avoid network/CSP issues
    lc_bootstrap = ""
    try:
        lc_path = os.path.join(current_dir, 'static', 'lightweight-charts.standalone.production.js')
        with open(lc_path, 'r', encoding='utf-8') as f:
            lc_js = f.read()
        lc_bootstrap = f"<script>\n{lc_js}\n</script>"
    except Exception:
        lc_bootstrap = "<script src=\"https://cdn.jsdelivr.net/npm/lightweight-charts@latest/dist/lightweight-charts.standalone.production.js\"></script>"
    # 构造初始数据作为后备
    try:
        # 重用 DF 构造
        initial_arr = []
        for x in df.to_dict('records'):
            initial_arr.append({ 'time': int(x['time']), 'open': float(x['open']), 'high': float(x['high']), 'low': float(x['low']), 'close': float(x['close']) })
    except Exception:
        initial_arr = []
    initial_json = json.dumps(_normalize(initial_arr))
    html_str = (html_tpl
                .replace('__CID__', cid)
                .replace('__LC_BOOTSTRAP__', lc_bootstrap)
                .replace('__INITIAL__', initial_json)
                .replace('__OVERLAYS__', overlays_json)
                .replace('__MARKERS__', markers_json)
                .replace('__SUBS__', subcharts_json))
    ui.html(html_str, sanitize=False).classes('w-full')
    with ui.expansion('🧪 数据探针 (REST)', value=False).classes('w-full'):
        def run_probe():
            import requests
            try:
                url = 'http://localhost:8000/api/candles'
                params = {'inst_id': cid, 'limit': 10}
                r = requests.get(url, params=params, timeout=5)
                data = r.json() if r.ok else []
                ui.label(f"status={r.status_code}, count={len(data)}, sample={data[0] if data else None}")
            except Exception as e:
                ui.label(f"探针失败: {e}").classes('text-red-400')
        ui.button('测试 /api/candles 返回', on_click=run_probe).classes('mt-2')

def render_equity_chart(inst):
    container = ui.column().classes('w-full')
    
    def refresh_equity():
        container.clear()
        session = db_manager.get_session()
        try:
            equity_recs = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.asc()).all()
            if not equity_recs:
                with container:
                    ui.label('暂无资金记录').classes('text-gray-500')
                return

            df_eq = pd.DataFrame([{
                'Time': e.timestamp, 
                'Total': e.total_value, 
                'Cash': e.cash,
                'Value': e.total_value - e.cash
            } for e in equity_recs])
            
            latest = df_eq.iloc[-1]
            
            with container:
                with ui.row().classes('w-full gap-4'):
                    # Left: Line Chart
                    with ui.card().classes('flex-grow h-[400px] bg-[#1e1e1e] border border-gray-800 p-0'):
                        fig = px.line(df_eq, x='Time', y='Total', title='总资产净值 (USDT)', template='plotly_dark')
                        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=20, r=20, t=40, b=20))
                        ui.plotly(fig).classes('w-full h-full')
                    
                    # Right: Pie Chart & Metrics
                    with ui.column().classes('w-1/3 h-[400px] gap-4'):
                        # Metrics
                        with ui.card().classes('w-full bg-[#262730] border border-gray-800 p-4'):
                            ui.label('当前净值').classes('text-xs text-gray-400')
                            ui.label(f"${latest['Total']:,.2f}").classes('text-xl font-bold text-green-400')
                            ui.separator().classes('my-2 bg-gray-700')
                            ui.label('当前现金').classes('text-xs text-gray-400')
                            ui.label(f"${latest['Cash']:,.2f}").classes('text-lg text-white')

                        # Pie Chart
                        pos_val = max(0, latest['Value'])
                        cash_val = max(0, latest['Cash'])
                        df_alloc = pd.DataFrame({
                            'Asset': ['Cash (USDT)', 'Position'],
                            'Value': [cash_val, pos_val]
                        })
                        
                        with ui.card().classes('w-full flex-grow bg-[#1e1e1e] border border-gray-800 p-0'):
                            fig_pie = px.pie(df_alloc, values='Value', names='Asset', hole=0.4, template='plotly_dark')
                            fig_pie.update_layout(
                                paper_bgcolor='rgba(0,0,0,0)', 
                                plot_bgcolor='rgba(0,0,0,0)', 
                                margin=dict(l=10, r=10, t=10, b=10),
                                showlegend=True,
                                legend=dict(orientation="h", yanchor="bottom", y=0, xanchor="center", x=0.5)
                            )
                            ui.plotly(fig_pie).classes('w-full h-full')

        finally:
            session.close()

    refresh_equity()
    # Auto refresh every 10s
    # ui.timer(10.0, refresh_equity) # Optional: might be too heavy for Plotly redraw

def render_trade_history(inst):
    container = ui.column().classes('w-full')
    
    def refresh_history():
        container.clear()
        session = db_manager.get_session()
        try:
            trades = session.query(TradeRecord).filter_by(instance_id=inst.id).order_by(TradeRecord.timestamp.desc()).limit(200).all()
            if not trades:
                with container:
                    ui.label('暂无交易记录').classes('text-gray-500')
                return
            
            # Grouping Logic (Match Lite)
            round_trips = []
            orders = []
            for t in trades:
                if t.side in ['LONG', 'SHORT', 'ROUNDTRIP_LONG', 'ROUNDTRIP_SHORT']:
                    round_trips.append(t)
                else:
                    orders.append(t)
            
            rows = []
            rt_map = {}
            
            # Process RoundTrips
            for rt in round_trips:
                open_dt, close_dt = None, None
                try:
                    extra = json.loads(rt.extra_data) if rt.extra_data else {}
                    # Try simple replacement for 'Z' if needed, or use dateutil if available
                    # Here we assume ISO format
                    if 'open_dt' in extra: open_dt = datetime.fromisoformat(extra['open_dt'].replace('Z', '+00:00'))
                    if 'close_dt' in extra: close_dt = datetime.fromisoformat(extra['close_dt'].replace('Z', '+00:00'))
                except: pass
                
                if not close_dt: close_dt = rt.timestamp
                
                rt_map[rt.order_id] = {'open': open_dt, 'close': close_dt}
                
                rows.append({
                    'Time': rt.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'Symbol': rt.symbol,
                    'Type': 'RoundTrip',
                    'Side': rt.side,
                    'Price': float(f"{rt.price:.4f}"),
                    'Size': float(f"{rt.size:.4f}"),
                    'PnL': float(f"{rt.pnl:.2f}") if rt.pnl else 0.0,
                    'Fee': float(f"{rt.commission:.4f}") if rt.commission else 0.0,
                    'GroupID': rt.order_id,
                    'SortTime': rt.timestamp.timestamp(),
                    'IsHeader': True
                })
                
            # Process Orders
            for o in orders:
                group_id = "-"
                for rid, info in rt_map.items():
                    # Time window matching logic
                    if info['open'] and info['close']:
                        if (info['open'] - timedelta(seconds=1)) <= o.timestamp <= (info['close'] + timedelta(seconds=1)):
                            group_id = rid
                            break
                    elif info['close']:
                        if abs((o.timestamp - info['close']).total_seconds()) < 5:
                            group_id = rid
                            break
                            
                rows.append({
                    'Time': o.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'Symbol': o.symbol,
                    'Type': 'Order',
                    'Side': o.side,
                    'Price': float(f"{o.price:.4f}"),
                    'Size': float(f"{o.size:.4f}"),
                    'PnL': float(f"{o.pnl:.2f}") if o.pnl else 0.0,
                    'Fee': float(f"{o.commission:.4f}") if o.commission else 0.0,
                    'GroupID': group_id,
                    'SortTime': o.timestamp.timestamp(),
                    'IsHeader': False
                })
            
            # Sort: Grouped items together
            # Assign a sort key for groups based on max time in group
            df_temp = pd.DataFrame(rows)
            if not df_temp.empty:
                group_max_time = df_temp.groupby('GroupID')['SortTime'].max()
                df_temp['GroupSortKey'] = df_temp['GroupID'].map(group_max_time)
                # If GroupID is '-', use its own SortTime
                df_temp.loc[df_temp['GroupID'] == '-', 'GroupSortKey'] = df_temp.loc[df_temp['GroupID'] == '-', 'SortTime']
                
                df_temp = df_temp.sort_values(by=['GroupSortKey', 'GroupID', 'SortTime'], ascending=[False, True, False])
                final_rows = df_temp.to_dict('records')
            else:
                final_rows = []

            with container:
                ui.aggrid({
                    'columnDefs': [
                        {'headerName': 'Time', 'field': 'Time', 'sortable': True, 'width': 160},
                        {'headerName': 'Type', 'field': 'Type', 'width': 100},
                        {'headerName': 'Side', 'field': 'Side', 'width': 100, 'cellStyle': {'styleConditions': [
                            {'condition': '["BUY", "LONG"].includes(params.value)', 'style': {'color': '#4ade80'}},
                            {'condition': '["SELL", "SHORT"].includes(params.value)', 'style': {'color': '#f87171'}}
                        ]}},
                        {'headerName': 'Price', 'field': 'Price', 'width': 100},
                        {'headerName': 'Size', 'field': 'Size', 'width': 100},
                        {'headerName': 'PnL', 'field': 'PnL', 'width': 100, 'cellStyle': {'styleConditions': [
                            {'condition': 'params.value > 0', 'style': {'color': '#4ade80'}},
                            {'condition': 'params.value < 0', 'style': {'color': '#f87171'}}
                        ]}},
                        {'headerName': 'Fee', 'field': 'Fee', 'width': 80},
                        {'headerName': 'Group', 'field': 'GroupID', 'hide': True}
                    ],
                    'rowData': final_rows,
                    'defaultColDef': {'flex': 1, 'resizable': True},
                    'rowClassRules': {
                        'bg-blue-900/20': 'data.IsHeader == true',
                    },
                    'domLayout': 'autoHeight'
                }).classes('w-full h-full theme-ag-theme-balham-dark')
                
        finally:
            session.close()

    refresh_history()

def render_logs(inst):
    log_area = ui.html('', sanitize=False).classes('w-full h-96 bg-[#0e1117] text-xs font-mono p-4 border border-gray-800 rounded overflow-y-auto')
    
    async def update_logs():
        logs = redis_client.get_latest_logs(inst.id, count=100)
        if logs:
            content = ""
            for line in logs:
                try:
                    l = json.loads(line)
                    ts = l.get('timestamp', '')
                    lvl = l.get('level', 'INFO')
                    msg = html.escape(l.get('message', ''))
                    
                    color = "#d4d4d4"
                    if lvl == 'ERROR': color = "#ff5252"
                    elif lvl == 'WARNING': color = "#ffb74d"
                    elif lvl == 'ORDER': color = "#69f0ae"
                    elif lvl == 'TRADE': color = "#40c4ff"
                    
                    content += f'<div style="color:{color}; margin-bottom:2px;"><span style="opacity:0.5">[{ts}]</span> <span style="font-weight:bold">[{lvl}]</span> {msg}</div>'
                except:
                    content += f'<div style="color:#d4d4d4">{html.escape(line)}</div>'
            
            log_area.content = content
            
    ui.timer(2.0, update_logs)

# --- Actions ---
def start_instance(inst):
    success, msg = process_manager.start_instance(inst.id)
    if success: ui.notify(f'启动成功: {inst.symbol}', type='positive'); refresh_ui()
    else: ui.notify(f'启动失败: {msg}', type='negative')

def stop_instance(inst):
    success, msg = process_manager.stop_instance(inst.id)
    if success: ui.notify(f'已停止: {inst.symbol}', type='info'); refresh_ui()
    else: ui.notify(f'错误: {msg}', type='negative')

def delete_instance(inst):
    if inst.status == 'RUNNING': process_manager.stop_instance(inst.id)
    session = db_manager.get_session()
    ok = db_manager.delete_instance_cascade(session, inst.id)
    session.close()
    ui.notify('实例已删除' if ok else '实例删除失败', type='info' if ok else 'negative'); refresh_ui()

# --- Main ---
db_manager.init_db()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title='Binance Bot Pro', storage_secret='super-secret-key', dark=True, port=8080)
