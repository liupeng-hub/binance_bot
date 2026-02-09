# 🤖 Binance Bot (Pro)

专业级币安量化交易机器人，基于 **Backtrader** 框架构建，支持 **WebSocket 实时行情**、**多策略管理**及**模拟/实盘交易**。

## 🚀 核心特性

*   **专业引擎**: 采用 Backtrader 作为核心回测与交易引擎，稳定可靠。
*   **实时驱动**: 支持 WebSocket 毫秒级行情推送，拒绝轮询延迟。
*   **多策略支持**: 内置网格 (Martingale)、振幅分布、概率统计等多种策略。
*   **双模式运行**: 
    *   `sim`: 模拟盘模式，使用真实历史数据 + 实时行情进行无风险测试。
    *   `live`: 实盘模式，对接币安合约 API 进行真实交易。
*   **数据管理**: 自动下载并缓存历史 K 线数据，支持离线分析。

## 📂 项目结构

```text
binance_bot/
├── config/                  # ⚙️ 策略配置文件
│   └── strategies/          # 生成的 JSON 策略参数
├── src/                     # 🚀 核心代码
│   ├── engine_backtrader/   # Backtrader 扩展 (Broker, Feed, Store)
│   ├── strategies/          # 策略实现 (Python 类)
│   ├── generators/          # 策略参数生成器 (离线分析)
│   └── utils/               # 工具函数 (数据下载, 通知)
├── data/                    # 💾 本地数据缓存 (CSV)
├── archive/                 # 📦 旧代码归档
├── main.py                  # 🏁 统一 CLI 入口
├── requirements.txt         # 依赖清单
└── .env                     # 🔐 环境变量 (API Key)
```

## 🛠️ 安装与配置

1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **配置环境变量**:
    复制 `.env.example` (如有) 或新建 `.env` 文件，填入您的币安 API Key：
    ```env
    BINANCE_API_KEY='your_api_key'
    BINANCE_SECRET_KEY='your_secret_key'
    # 可选: WebSocket 代理
    HTTP_PROXY='http://127.0.0.1:1087'
    HTTPS_PROXY='http://127.0.0.1:1087'
    ```

## 🖥️ 使用指南

所有操作均通过 `main.py` 统一入口执行。

### 1. 生成策略配置
基于历史数据分析，生成最优的网格参数：
```bash
python3 main.py gen --symbol BTC/USDT --days 180
```
*生成的配置将保存在 `config/strategies/` 目录下。*

### 2. 运行交易 (模拟/实盘)

**启动模拟盘 (推荐)**:
```bash
python3 main.py trade --strategy martingale --symbol BTC/USDT --mode sim
```

**启动实盘 (谨慎)**:
```bash
python3 main.py trade --strategy martingale --symbol BTC/USDT --mode live
```

**参数说明**:
*   `--strategy`: 选择策略 (`martingale`, `amplitude_distribution`, `probability`, `monitor`)
*   `--symbol`: 交易标的 (默认 `BTC/USDT`)
*   `--mode`: `sim` (模拟) 或 `live` (实盘)
*   `--days`: 初始化加载的历史天数 (默认 30)
*   `--no-ws`: 禁用 WebSocket (仅在网络受限时使用 HTTP 轮询)

## 📈 策略说明

*   **Martingale (网格)**: 经典的马丁格尔策略，分批建仓，拉低均价。
*   **Amplitude Distribution**: 基于历史振幅分布动态调整网格间距。
*   **Probability**: 基于统计概率寻找高胜率入场点。

## ⚠️ 风险提示

量化交易存在风险，实盘交易请务必做好风控。本项目仅供学习与研究使用，不构成投资建议。
