# ⚔️ 策略竞技场 (Strategy PK) 设计方案

## 1. 核心概念
策略竞技场 (Tournament) 是一个多维度的策略组合评估系统，旨在通过标准化的回测环境，横向对比不同策略、不同标的、不同时间周期下的表现，从而筛选出最优的交易组合。

### 1.1 关键实体
*   **锦标赛 (Tournament)**: 一次完整的比拼任务，包含名称、配置、状态和最终结果。
*   **选手 (Contestant)**: 具体的 [策略 + 标的 + 周期] 组合。
*   **赛制 (Mode)**:
    *   **快速比拼 (Quick Match)**: 使用策略默认参数，仅对比策略本身逻辑的适应性。
    *   **深度优化 (Deep Optimization)**: 先对每个选手进行参数优选 (Grid/Bayesian)，取最佳参数结果参与最终排名。

## 2. 功能模块设计

### 2.1 发起竞技 (Setup)
用户界面提供以下配置项：
*   **基本信息**: 竞技场名称 (e.g. "2024 Q1 主流币趋势策略海选")。
*   **选手池 (多选)**:
    *   **策略**: SMA, MACD, DualThrust, R-Breaker...
    *   **标的**: BTC/USDT, ETH/USDT, SOL/USDT...
    *   **周期**: 15m, 1h, 4h, 1d...
*   **环境参数 (统一)**:
    *   **资金**: 初始本金 (e.g. 10,000 USDT)。
    *   **时间**: 回测开始时间 ~ 结束时间。
    *   **费率**: 手续费率 (e.g. 0.04%)。
*   **赛制选择**: 默认参数 vs 深度优化。

### 2.2 任务执行 (Execution)
后台将根据选手池生成笛卡尔积任务列表：
`Total Tasks = Strategies × Symbols × Timeframes`

*   **并行/串行**: 依据服务器资源，支持多进程并行回测。
*   **状态追踪**: 实时更新每个选手的回测进度 (Pending -> Running -> Completed/Failed)。

### 2.3 结果分析 (Analysis)
提供多维度的可视化分析工具：
*   **🏆 排行榜 (Leaderboard)**: 支持按 净利润、夏普比率、回撤 等字段排序。
*   **🔥 适应性热力图**: X轴标的，Y轴策略，颜色代表收益。快速识别 "BTC适合趋势，ETH适合震荡" 等特征。
*   **📈 净值赛跑**: 选定 Top 5 选手，在同一张图表中绘制资金曲线，直观对比稳定性。
*   **📊 风险收益散点图**: X轴最大回撤，Y轴年化收益。寻找 "低风险高收益" 的左上角区域。

### 2.4 跨赛对比 (Meta-Analysis)
*   支持勾选多个历史锦标赛，将其中的优胜选手提取出来进行二次对比。
*   用于验证策略在不同市场环境 (如 2023 牛市 vs 2022 熊市) 下的鲁棒性。

## 3. 评价指标体系升级 (Metrics Upgrade)
为了支持专业的金融策略评估，系统将计算并存储以下指标：

| 维度 | 指标 | 说明 |
| :--- | :--- | :--- |
| **收益** | **Net Profit** | 净利润 (绝对值) |
| | **ROI** | 投资回报率 (%) |
| | **Annualized Return** | 年化收益率 |
| **风险** | **Max Drawdown** | 最大回撤 (%) |
| | **Drawdown Duration** | 最长回撤持续时间 |
| | **Volatility** | 收益波动率 |
| **风险调整收益** | **Sharpe Ratio** | 夏普比率 (承受每单位总风险带来的超额回报) |
| | **Sortino Ratio** | 索提诺比率 (仅考虑下行风险) |
| | **Calmar Ratio** | 卡玛比率 (年化收益 / 最大回撤) |
| **交易特征** | **Win Rate** | 胜率 (%) |
| | **Profit/Loss Ratio** | 盈亏比 (平均盈利 / 平均亏损) |
| | **Trade Count** | 总交易次数 |
| | **Avg Holding Bars** | 平均持仓周期 |

## 4. 数据库设计 (Schema)

### 4.1 Tournament 表 (新增)
```sql
CREATE TABLE tournament (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER,
    name VARCHAR(100),
    config_json TEXT, -- 存储选定的策略、标的、周期、资金等配置
    status VARCHAR(20), -- PENDING, RUNNING, COMPLETED, PARTIAL_FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 4.2 TournamentResult 表 (新增)
用于存储每个选手的详细比赛结果，与 Tournament 一对多关联。
*注：为了数据隔离，我们不直接复用 OptimizationJob 表，而是建立专用的结果表，但底层计算逻辑复用。*

```sql
CREATE TABLE tournament_result (
    id VARCHAR(36) PRIMARY KEY,
    tournament_id VARCHAR(36) REFERENCES tournament(id),
    strategy_name VARCHAR(50),
    symbol VARCHAR(20),
    timeframe VARCHAR(10),
    params_json TEXT, -- 使用的具体参数
    metrics_json TEXT, -- 存储上述所有评价指标
    equity_curve_json TEXT, -- 简化的资金曲线点 (用于绘图)
    status VARCHAR(20), -- COMPLETED, ERROR
    error_msg TEXT
);
```

## 5. 开发计划与进度

- [ ] **Phase 1: 基础设施**
    - [ ] 数据库模型迁移 (SQLAlchemy Models)
    - [ ] 核心回测引擎升级：集成 `quantstats` 或自行实现高级指标计算逻辑
    - [ ] 任务分发器：支持 Tournament 批量任务生成

- [ ] **Phase 2: 后端逻辑**
    - [ ] 实现 `start_tournament` API
    - [ ] 实现结果聚合与排名逻辑

- [ ] **Phase 3: 前端实现**
    - [ ] 锦标赛创建向导 (Wizard)
    - [ ] 实时进度看板
    - [ ] 交互式结果分析仪表盘 (AgGrid, Plotly)

- [ ] **Phase 4: 跨赛对比**
    - [ ] 历史锦标赛选择与数据合并
    - [ ] 综合对比视图
