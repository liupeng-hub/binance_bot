# 软件现状总结（简版）

## 概览
- 项目目标：量化交易 SaaS 平台（账户、实例、行情/日志、优化、图表）。
- 前端双栈：Streamlit 参考版（[app_lite.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/app_lite.py)）、NiceGUI 专业版（[app_pro.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/app_pro.py)）。
- 后端与数据：SQLAlchemy ORM、Redis 实时/缓存、策略进程管理、指标计算；新增统一 WS/REST 服务（[ws_server.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/ws_server.py)）。

## 架构
- 层次：前端页面 → 应用逻辑 → 数据/消息（PostgreSQL/Redis） → 运行时（策略/优化/监控）。
- 实时链路：策略发布到 Redis → WS/REST 服务提供首屏历史与实时 → 前端浏览器侧增量更新烛图。

## 前后端配合
- Streamlit：使用 Lightweight Charts + `components.html` 注入 JS，首屏 REST 拉历史、WS 增量更新，避免 rerun 全局重绘。
- NiceGUI：SPA 导航与布局已修复；图表建议切换为浏览器 WS 增量，保留 Highcharts 初始化（[app_pro.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/app_pro.py)）。

## 优点
- 模块化清晰：ORM、Redis、策略装载、进程管理职责明确。
- 双前端：验证快速、界面可专业化。
- 统一 WS/REST：实时渲染性能和稳定性提升，数据契约更清晰。

## 不足
- 双前端维护成本高、易产出差异。
- NiceGUI 仍有服务端定时器驱动的整图刷新残留。
- 实例状态与 Redis 通知可能出现不一致，缺少统一纠错。
- 安全与配置需加强；测试缺 E2E 与前端集成覆盖。

## 合理性与扩展性
- 现有栈适合中小规模与快速迭代；统一 WS/REST 是正确演进。
- 可横向扩展 WS 服务与策略进程；多交易所/标的通过统一数据契约支持。

## 改进建议
- 前端增量统一：NiceGUI 图表改为浏览器 WS 增量（Highcharts `addPoint/update`）。
- 状态一致性：定义权威源、心跳与断线补数；异常回写纠正。
- 数据模型：Pydantic 统一消息（K 线/日志/状态），严禁 `NaN/inf`。
- 任务队列化：优化/回测/聚合进入队列，提供订阅接口。
- 安全与配置：密钥滚动、权限最小化、审计；统一 `.env` 校验。
- 观测性与测试：结构化日志、Prometheus 指标；E2E 与前端集成测试。

## 近期改动
- 修复登录与 SPA 导航；`EquityRecord.equity` → `total_value`；`ui.html` `sanitize=False`。
- Streamlit 图表改为“首屏 REST + 前端 WS 增量”；新增统一 WS/REST 服务。

## 参考文件
- [app_lite.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/app_lite.py)
- [app_pro.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/app_pro.py)
- [ws_server.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/ws_server.py)
- [redis_client.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/src/utils/redis_client.py)
- [data_helper.py](file:///Users/liupeng/Documents/trae_projects/mybot/binance_bot/src/utils/data_helper.py)
