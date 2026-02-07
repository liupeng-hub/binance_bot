# Binance Bot

这是一个基于 [CCXT](https://github.com/ccxt/ccxt) 的自动化量化交易机器人，专为 Binance Futures (合约) 设计。

## 📂 工程结构 (Project Structure)

```text
binance_bot/
├── run_strategy_gen.py         # 🚀 策略生成器：基于全周期回测生成最优网格策略
├── run_bot.py                  # 🤖 机器人启动器：支持单Bot或多Bot组合运行
├── run_dashboard.py            # 📊 账户看板：实时监控资金、持仓与订单
├── run_param.json              # 📜 配置文件：组合运行示例
├── requirements.txt            # 📦 依赖清单
├── core/                       # 🧩 核心功能模块 (Core Modules)
│   ├── bot_realtime.py         # [交易] BotRealtime：实时价格监听与网格交易
│   ├── bot_gridmaker.py        # [交易] BotGridMaker：批量限价挂单 (Grid Maker)
│   ├── data_provider.py        # [数据] 数据服务：K线数据获取与本地缓存
│   ├── strategy_calculator.py  # [算法] 策略计算：回测分析与权重计算
│   └── notifier_wechat.py      # [服务] 消息通知：企业微信通知
├── strategies/                 # 📂 策略配置库 (Auto-Generated)
│   ├── amplitude_distribution/ # 振幅分布策略配置 (基于历史回测动态计算)
│   ├── martingale/             # 马丁格尔策略配置 (左侧交易/倒金字塔)
│   └── probability/            # 概率分布策略配置 (右侧交易/正态分布)
└── data/                       # 💾 本地数据缓存 (CSV)
```

## 📝 核心功能说明

### 1. 入口与配置
- **[run_strategy_gen.py]**
  - **功能**: 自动拉取历史数据，生成三种策略配置文件（Martingale, Probability, Amplitude Distribution）。其中 Amplitude Distribution 会执行真实的全周期 (1m~1d) 回测以寻找最优参数。
  - **用法**: `python run_strategy_gen.py --symbols BTCUSDT`

- **[run_bot.py]**
  - **功能**: 启动交易机器人。
  - **用法**: 
    - 单标的: `python run_bot.py BTCUSDT`
    - 多标的: `python run_bot.py BTCUSDT,ETHUSDT`
    - 组合运行: `python run_bot.py run_param.json`

- **[run_dashboard.py]**
  - **功能**: 终端实时看板。
  - **用法**: `python run_dashboard.py`

### 2. 核心模块 (Core)
- **[core/bot_realtime.py]**
  - **逻辑**: 实时轮询价格，触发网格买入，成交后自动挂止盈单。
  - **特点**: 灵活性高，适合捕捉瞬间插针。

- **[core/bot_gridmaker.py]**
  - **逻辑**: 预先批量挂出限价单 (Limit Orders) 到交易所，由交易所撮合。
  - **特点**: 确保成交，减少滑点，适合震荡行情。

### 3. 策略库 (Strategies)
系统生成的 JSON 配置文件均存放于此。
- **Amplitude Distribution**: 基于过去一年真实波动率计算出的最优权重。
- **Martingale**: 越跌买入越多的策略。
- **Probability**: 在高频成交区间重仓的策略。

## 📈 组合运行配置指南 (Run Config Guide)

`run_param.json` 是一个强大的编排文件，允许您通过一个命令同时启动多个不同类型的机器人，并为它们分配不同的策略和标的。

### 文件结构示例

JSON 文件的顶层键是 **机器人类型 (Bot Type)**，第二层键是 **策略类型 (Strategy Type)**，值是 **标的列表 (Symbol List)**。

```json
{
    "bot_realtime": {  // <--- 机器人类型 1: 实时成交驱动机器人
        "martingale": ["BTCUSDT", "ETHUSDT"],  // 使用马丁策略的标的
        "probability": ["BNBUSDT"]             // 使用概率分布策略的标的
    },
    "bot_gridmaker": { // <--- 机器人类型 2: 预埋单网格机器人
        "amplitude_distribution": ["SOLUSDT", "DOGEUSDT"] // 使用振幅分布策略的标的
    }
}
```

### 字段详解

1. **机器人类型 (Bot Type)**
    *   **`bot_realtime`**: 实时监听市场成交流，适合高频交易。
    *   **`bot_gridmaker`**: 预埋单网格机器人，适合震荡行情。

2. **策略类型 (Strategy Type)**
    *   **`amplitude_distribution`**: 振幅分布策略。
    *   **`martingale`**: 马丁格尔策略。
    *   **`probability`**: 概率分布策略。

3. **标的列表 (Symbol List)**
    *   必须先使用 `run_strategy_gen.py` 生成了对应的策略文件。

## 🚀 快速开始

1.  **安装依赖**

    ```bash
    pip install -r requirements.txt
    ```

2.  **配置环境变量**
    创建 `.env` 文件：
    ```env
    BINANCE_API_KEY="your_api_key"
    BINANCE_SECRET_KEY="your_secret_key"
    WECHAT_WEBHOOK_URL="your_webhook_url" # 可选
    ```

3.  **生成标的策略配置json** (关键步骤)
    
    机器人运行依赖策略文件，必须先生成：
    ```bash
    python run_strategy_gen.py --symbols BTCUSDT
    ```
    *系统会自动下载数据、回测并保存最优配置到 `strategies/` 目录下。*

4.  **运行交易机器人**

    ```bash
    python run_bot.py run_param.json
    ```

5.  **监控交易账户**

    ```bash
    python run_dashboard.py
    ```
