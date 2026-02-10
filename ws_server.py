from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from typing import List

import os
import sys

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

from src.utils.redis_client import redis_client
from src.utils.db_manager import db_manager
from src.utils.db_models import StrategyInstance
from src.utils.data_helper import load_kline_data

app = FastAPI()

# CORS for Streamlit/NiceGUI
origins = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/candles")
def get_initial_candles(inst_id: str = Query(...), limit: int = Query(500)):
    session = db_manager.get_session()
    try:
        inst = session.query(StrategyInstance).filter_by(id=inst_id).first()
        if not inst:
            return []
        try:
            cfg = json.loads(inst.config_json) if inst.config_json else {}
            tf = cfg.get('sys', {}).get('timeframe')
        except Exception:
            tf = None
        df = load_kline_data(inst.symbol, timeframe=tf, limit=limit)
        if df.empty:
            return []
        return [{
            'time': int(row['time']),
            'open': float(row['open']) if row['open'] is not None else None,
            'high': float(row['high']) if row['high'] is not None else None,
            'low': float(row['low']) if row['low'] is not None else None,
            'close': float(row['close']) if row['close'] is not None else None,
            'volume': float(row['volume']) if row['volume'] is not None else None,
        } for _, row in df.iterrows()]
    finally:
        session.close()

@app.websocket("/ws/candles/{inst_id}")
async def ws_candles(ws: WebSocket, inst_id: str):
    await ws.accept()
    last_ts = None
    try:
        while True:
            data_list: List[dict] = redis_client.get_latest_market_data(inst_id)
            if data_list:
                last = data_list[-1]
                payload = {
                    'time': int(last.get('time') or int(last.get('t', 0) / 1000)),
                    'open': last.get('open') or last.get('o'),
                    'high': last.get('high') or last.get('h'),
                    'low': last.get('low') or last.get('l'),
                    'close': last.get('close') or last.get('c'),
                    'volume': last.get('volume') or last.get('v'),
                }
                if payload['time'] and payload['time'] != last_ts:
                    await ws.send_text(json.dumps(payload))
                    last_ts = payload['time']
                else:
                    await ws.send_text(json.dumps(payload))
            await asyncio.sleep(1.0)
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass

