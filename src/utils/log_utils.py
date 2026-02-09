import json
from datetime import datetime

def format_log(dt, symbol, msg, level='INFO', component='Strategy'):
    """
    生成结构化 JSON 日志
    """
    if isinstance(dt, datetime):
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        dt_str = str(dt)
        
    log_entry = {
        "timestamp": dt_str,
        "symbol": str(symbol),
        "level": level,
        "component": component,
        "message": str(msg)
    }
    return json.dumps(log_entry, ensure_ascii=False)
