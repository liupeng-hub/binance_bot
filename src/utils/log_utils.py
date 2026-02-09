import json
from datetime import datetime
import logging
import os
from logging.handlers import RotatingFileHandler

def format_log(dt, symbol, msg, level='INFO', component='Strategy'):
    """
    生成结构化 JSON 日志 (保留向后兼容)
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

def setup_logger(name, log_file=None, level=logging.INFO):
    """
    配置并获取 Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 Handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console Handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File Handler (Rotating)
    if log_file:
        # 确保目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        fh = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
