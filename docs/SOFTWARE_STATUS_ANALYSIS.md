# 软件现状总结分析报告

**日期**: 2026-02-10
**版本**: v1.0

## 1. 系统概述
本系统是一个基于 **Python + Streamlit + Backtrader + PostgreSQL + Redis** 的多租户量化交易 SaaS 平台。支持策略回测、测试网模拟交易及实盘交易。系统采用了前后端解耦的设计架构，通过 Redis 实现实时通信，PostgreSQL/TimescaleDB 存储核心业务与时序数据。

## 2. 核心功能模块

### 2.1 交易工作台 (Trading Desk)
- **多模式支持**：支持 **回测 (Backtest)**、**测试网 (Testnet)** 和 **实盘 (Live)** 三种模式。
- **动态实例管理**：用户可随时创建、启动、停止、删除交易实例。
- **可视化监控**：
    - **K 线图表**：基于 Lightweight Charts，支持主图指标（MA, Bollinger）和副图指标（RSI, MACD, Volume）。
    - **资金曲线**：基于 Plotly 的动态净值曲线。
    - **持仓分布**：饼图展示现金与持仓占比。
- **实时交互**：
    - 集成 Redis Pub/Sub，实现毫秒级日志流推送。
    - 状态自动刷新与异常检测。

### 2.2 策略文库 (Strategy Library)
- **插件化架构**：通过 `StrategyLoader` 动态加载 `src/strategies` 目录下的策略文件。
- **自适应参数**：自动解析策略参数配置，生成对应的 UI 表单。
- **文档集成**：自动读取策略 Docstring 或 `algo_description` 字段展示策略说明。

### 2.3 参数调优实验室 (Optimization Lab)
- **多算法支持**：
    - **网格搜索 (Grid Search)**：穷举所有参数组合。
    - **贝叶斯优化 (Optuna)**：智能搜索全局最优解，效率更高。
- **异步任务处理**：调优任务在后台独立进程运行，不阻塞前端操作。
- **结果分析**：提供 Top 50 参数组合的详细指标（净利润、回撤、胜率），支持一键应用最优参数。

## 3. 技术架构与性能分析

### 3.1 架构设计
- **前端 (Frontend)**: Streamlit (Web App)
- **后端 (Backend)**: 
    - `instance_runner.py`: 独立的策略执行进程（基于 Backtrader）。
    - `process_manager.py`: 进程生命周期管理。
- **中间件 (Middleware)**:
    - **Redis**: 实时消息总线（日志、状态、实时行情缓存）。
    - **PostgreSQL**: 持久化存储（用户、配置、实例、交易记录）。
    - **TimescaleDB**: 优化的时序数据存储（K 线）。

### 3.2 性能表现
- **优点**:
    - **高并发**: 各交易实例独立进程，互不干扰，理论上支持单机数十个实例并发（受 CPU/内存限制）。
    - **实时性**: Redis 的引入解决了传统数据库轮询导致的 UI 卡顿和延迟问题。
    - **稳定性**: 数据库连接池 (`pool_pre_ping`, `pool_recycle`) 机制有效防止了远程连接超时。
- **瓶颈**:
    - **Streamlit 渲染机制**: Streamlit 的每次交互都会触发脚本重运行 (`Rerun`)，导致组件（尤其是图表）在刷新时有视觉闪烁。
    - **数据加载**: 长周期回测时，从 DB 加载大量 K 线数据可能会有延迟。

## 4. 优化与升级 Roadmap

### 4.1 实时 K 线优化 (High Priority)
- **现状**: K 线图表主要依赖已结单的历史数据，实时性依赖页面刷新，且刷新时有闪烁。
- **目标**: 实现秒级（Tick 级）K 线更新，且消除视觉闪烁。
- **方案**:
    1. **Redis 实时行情**: 在策略端将当前未完结的 Bar (Open, High, Low, Close) 实时推送到 Redis。
    2. **Streamlit Fragment**: 使用 `@st.fragment` (Streamlit 1.37+) 实现局部渲染，仅更新图表容器，避免全页刷新。

### 4.2 数据存储优化
- **TimescaleDB 连续聚合**: 利用数据库原生能力自动维护多周期 (5m, 1h, 4h) K 线，减少应用层计算压力。

### 4.3 交互体验提升
- **参数热更新**: 允许在不停止策略的情况下动态调整止损止盈参数（通过 Redis 信号）。
- **报警通知**: 集成 Webhook (Telegram/钉钉)，在发生 Error 或关键交易时推送消息。

### 4.4 部署与运维
- **Docker 化**: 提供 `docker-compose.yml`，一键拉起 Web + DB + Redis + Worker。
- **日志归档**: 增加日志轮转和归档策略，防止磁盘空间耗尽。
