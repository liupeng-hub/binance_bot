from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import json
from typing import List
import time

import os
import sys

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

from src.utils.redis_client import redis_client
from src.utils.db_manager import db_manager
from src.utils.db_models import StrategyInstance, TradeRecord
from src.utils.data_helper import load_kline_data

app = FastAPI()

# CORS for Streamlit/NiceGUI
origins = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5173", # Vite Dev Server
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve local static assets (JS libs)
static_dir = os.path.join(current_dir, 'static')
os.makedirs(static_dir, exist_ok=True)
app.mount('/static', StaticFiles(directory=static_dir), name='static')

@app.on_event('startup')
def _download_lightweight_charts_assets():
    try:
        import requests
        candidates = {
            'lightweight-charts.esm.production.js': [
                'https://unpkg.com/lightweight-charts/dist/lightweight-charts.esm.production.js',
                'https://cdn.jsdelivr.net/npm/lightweight-charts@latest/dist/lightweight-charts.esm.production.js',
            ],
            'lightweight-charts.standalone.production.js': [
                'https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js',
                'https://cdn.jsdelivr.net/npm/lightweight-charts@latest/dist/lightweight-charts.standalone.production.js',
            ],
        }
        for fname, urls in candidates.items():
            fpath = os.path.join(static_dir, fname)
            if os.path.exists(fpath):
                continue
            ok = False
            for url in urls:
                try:
                    r = requests.get(url, timeout=10)
                    if r.ok:
                        with open(fpath, 'wb') as f:
                            f.write(r.content)
                        ok = True
                        break
                    else:
                        print(f"⚠️ Download {url} failed: {r.status_code}")
                except Exception as e:
                    print(f"⚠️ Download error {url}: {e}")
            if not ok:
                print(f"⚠️ Could not fetch {fname} from any mirror")
    except Exception as e:
        print(f"⚠️ Could not prepare LightweightCharts assets: {e}")

@app.get("/api/candles")
def get_initial_candles(inst_id: str = Query(...), limit: int = Query(500), timeframe: str = Query(None)):
    session = db_manager.get_session()
    try:
        inst = session.query(StrategyInstance).filter_by(id=inst_id).first()
        if not inst:
            return {"candles": [], "indicators": {"main": [], "sub": []}}
        try:
            cfg = json.loads(inst.config_json) if inst.config_json else {}
            # If timeframe provided via Query, use it; otherwise fallback to config
            if not timeframe:
                timeframe = cfg.get('sys', {}).get('timeframe')
        except Exception:
            if not timeframe:
                timeframe = None
        
        # Load Candle Data
        df = load_kline_data(inst.symbol, timeframe=timeframe, limit=limit)
        if df.empty:
            return {"candles": [], "indicators": {"main": [], "sub": []}}
            
        candles = [{
            'time': int(row['time']),
            'open': float(row['open']) if row['open'] is not None else None,
            'high': float(row['high']) if row['high'] is not None else None,
            'low': float(row['low']) if row['low'] is not None else None,
            'close': float(row['close']) if row['close'] is not None else None,
            'volume': float(row['volume']) if row['volume'] is not None else None,
        } for _, row in df.iterrows()]

        # Calculate Indicators
        from src.utils.data_helper import calculate_indicators
        main_overlays, sub_charts = calculate_indicators(df, inst.strategy_name, inst.config_json)
        
        return {
            "candles": candles,
            "indicators": {
                "main": main_overlays,
                "sub": sub_charts
            }
        }
    finally:
        session.close()

@app.get("/api/trades")
def get_instance_trades(inst_id: str = Query(...)):
    session = db_manager.get_session()
    try:
        trades = session.query(TradeRecord).filter_by(instance_id=inst_id).order_by(TradeRecord.timestamp).all()
        return [{
            'id': t.id,
            'time': int(t.timestamp.timestamp()),
            'side': t.side,
            'price': t.price,
            'size': t.size,
            'pnl': t.pnl
        } for t in trades]
    finally:
        session.close()

@app.websocket("/ws/candles/{inst_id}")
async def ws_candles(ws: WebSocket, inst_id: str):
    await ws.accept()
    last_ts = None
    tick = 0
    
    # Load Strategy Info Once
    session = db_manager.get_session()
    strategy_name = None
    strategy_config = {}
    try:
        inst = session.query(StrategyInstance).filter_by(id=inst_id).first()
        if inst:
            strategy_name = inst.strategy_name
            strategy_config = inst.config_json
    except:
        pass
    finally:
        session.close()

    from src.utils.data_helper import calculate_indicators
    import pandas as pd

    try:
        while True:
            # 1. Get latest candles from Redis (usually 1m candles)
            # Note: Redis might store only the latest few candles or raw ticks.
            # Assuming get_latest_market_data returns a list of recent candles dicts.
            data_list: List[dict] = redis_client.get_latest_market_data(inst_id)
            
            if data_list:
                # 2. Construct DataFrame for Indicator Calculation
                # We need enough history to calculate indicators (e.g. MA20 needs 20 bars).
                # Redis usually stores limited history. If it's too short, indicators won't be accurate.
                # For a production system, we should cache a larger window in memory or query DB + Redis.
                # Here we assume Redis returns enough data or we accept "approximation" for the latest bar.
                
                # Simplified: Just send the latest candle update
                last = data_list[-1]
                payload = {
                    'time': int(last.get('time') or int(last.get('t', 0) / 1000)),
                    'open': float(last.get('open') or last.get('o') or 0),
                    'high': float(last.get('high') or last.get('h') or 0),
                    'low': float(last.get('low') or last.get('l') or 0),
                    'close': float(last.get('close') or last.get('c') or 0),
                    'volume': float(last.get('volume') or last.get('v') or 0),
                }

                # 3. Calculate Real-time Indicators (On the fly)
                # We construct a small DataFrame from the Redis list to calculate the latest point
                try:
                    df_live = pd.DataFrame(data_list)
                    # Normalize columns
                    cols_map = {'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}
                    df_live.rename(columns=cols_map, inplace=True)
                    
                    # Ensure numeric
                    for c in ['open', 'high', 'low', 'close', 'volume']:
                        if c in df_live.columns:
                            df_live[c] = pd.to_numeric(df_live[c])
                    
                    if 'time' in df_live.columns:
                         # Handle time format if needed (ms to s)
                         pass

                    if len(df_live) > 0:
                        main_inds, sub_inds = calculate_indicators(df_live, strategy_name, strategy_config)
                        
                        # Extract the LAST value for each indicator
                        # main_inds structure: [{ type, data: [...], options }]
                        
                        updates = {}
                        
                        # Main Indicators
                        for i, ind in enumerate(main_inds):
                            if ind['data']:
                                updates[f'main-{i}'] = ind['data'][-1] # Last point
                        
                        # Sub Indicators
                        # sub_inds structure: [{ series: [{ type, data... }] }]
                        for i, sub in enumerate(sub_inds):
                            for j, ser in enumerate(sub['series']):
                                if ser['data']:
                                    updates[f'sub-{i}-{j}'] = ser['data'][-1]

                        # Add indicators to payload
                        payload['indicators'] = updates

                except Exception as e:
                    print(f"RT Indicator Calc Error: {e}")

                # Send Update
                if payload['time'] != last_ts:
                    # New Bar
                    await ws.send_text(json.dumps({'type': 'candle', 'data': payload}))
                    last_ts = payload['time']
                else:
                    # Update Current Bar
                    await ws.send_text(json.dumps({'type': 'candle', 'data': payload}))
            
            tick += 1
            if tick % 10 == 0:
                hb = {'type': 'heartbeat', 'data': {'ts': int(time.time() * 1000), 'inst_id': inst_id}}
                await ws.send_text(json.dumps(hb))
            await asyncio.sleep(1.0)
    except Exception as e:
        print(f"WS Error: {e}")
        try:
            await ws.close()
        except Exception:
            pass
