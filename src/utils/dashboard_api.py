from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import json
import os
import sys

# 假设该文件位于 src/utils/，需要添加项目根目录到 path 以导入其他模块
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.utils.db_manager import db_manager
from src.utils.db_models import StrategyInstance, EquityRecord

app = FastAPI(title="Quant Dashboard API")

class InstanceStatus(BaseModel):
    id: str
    symbol: str
    strategy: str
    status: str
    pnl: float
    roi: float

class EquityPoint(BaseModel):
    timestamp: str
    total_value: float
    cash: float

@app.get("/instances", response_model=List[InstanceStatus])
def get_instances(user_id: int):
    """
    获取指定用户的实例列表及其实时状态
    """
    session = db_manager.get_session()
    try:
        instances = session.query(StrategyInstance).filter_by(user_id=user_id).all()
        result = []
        for inst in instances:
            # 获取最新净值
            latest_eq = session.query(EquityRecord).filter_by(instance_id=inst.id).order_by(EquityRecord.timestamp.desc()).first()
            
            pnl = 0.0
            roi = 0.0
            if latest_eq:
                # 尝试解析初始资金
                initial_capital = 100000.0
                try:
                    cfg = json.loads(inst.config_json)
                    if 'sys' in cfg:
                        initial_capital = float(cfg['sys'].get('capital', 100000.0))
                except:
                    pass
                
                current_val = latest_eq.total_value
                pnl = current_val - initial_capital
                roi = (pnl / initial_capital) * 100.0
            
            result.append(InstanceStatus(
                id=inst.id,
                symbol=inst.symbol,
                strategy=inst.strategy_name,
                status=inst.status,
                pnl=round(pnl, 2),
                roi=round(roi, 2)
            ))
        return result
    finally:
        session.close()

@app.get("/equity/{instance_id}", response_model=List[EquityPoint])
def get_equity_curve(instance_id: str):
    """
    获取指定实例的资金曲线
    """
    session = db_manager.get_session()
    try:
        recs = session.query(EquityRecord).filter_by(instance_id=instance_id).order_by(EquityRecord.timestamp.asc()).all()
        return [
            EquityPoint(
                timestamp=r.timestamp.strftime("%Y-%m-%d %H:%M:%S"), 
                total_value=r.total_value,
                cash=r.cash
            ) for r in recs
        ]
    finally:
        session.close()

# 注意: 此文件旨在作为独立 API 服务运行，或者集成到现有应用中。
# 运行方式: uvicorn src.utils.dashboard_api:app --reload
