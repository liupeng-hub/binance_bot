#!/bin/bash

# 设置数据库连接环境变量
# 对应 docker-compose.yml 中的配置
export DATABASE_URL="postgresql://postgres:password@localhost:5432/mybot_db"

echo "🚀 Starting Binance Bot with TimescaleDB..."
echo "Database URL: $DATABASE_URL"

# 1. 检查是否需要迁移数据 (可选)
# python tools/migrate_csv_to_db.py

# 2. 启动 Web 应用
streamlit run web_app.py
