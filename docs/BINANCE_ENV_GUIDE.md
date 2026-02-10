# 币安测试环境使用指南

在进行量化机器人开发和实盘测试时，币安提供了两种主要的测试环境。为了确保机器人能够正常连接并运行，请根据下表选择正确的环境和配置。

---

## 1. 环境对比

| 特性 | **模拟交易 (Mock/Demo)** | **期货测试网 (Futures Testnet)** |
| :--- | :--- | :--- |
| **官方网址** | [demo.binance.com](https://demo.binance.com) | [testnet.binancefuture.com](https://testnet.binancefuture.com) |
| **账号体系** | 使用**主站账号**直接登录 | 需要**独立注册**（建议用新邮箱） |
| **主要用途** | 手动交易练习、熟悉界面 | **量化 API 开发、机器人实盘模拟** |
| **API 域名** | `fapi.binance.com` (带模拟标志) | `testnet.binancefuture.com` |
| **WS 域名** | `wss://fstream.binance.com` | `wss://stream.binancefuture.com` |
| **推荐等级** | ⭐⭐ (手动交易者) | ⭐⭐⭐⭐⭐ (**开发者首选**) |

---

## 2. 为什么建议使用 Futures Testnet？

对于本项目（Binance Bot），我们深度适配了 **Futures Testnet**，原因如下：

1. **完全隔离**：测试网账号与真实资金账号完全独立，没有任何误操作真实资金的风险。
2. **标准支持**：CCXT 库和币安官方文档对 Testnet 有最标准的支持。
3. **连接稳定**：测试网域名 `binancefuture.com` 在大多数海外服务器（如香港）上连接非常顺畅，无需复杂代理。

---

## 3. 如何配置并启动机器人？

### 第一步：获取 API Key
1. 访问 [https://testnet.binancefuture.com/](https://testnet.binancefuture.com/)。
2. 注册并登录。
3. 在页面底部的 **"API Key"** 区域点击 **"Create API Key"**。
4. 复制并保存您的 `API Key` 和 `Secret Key`。

### 第二步：在 Web 页面配置
1. 打开机器人的 Dashboard 页面。
2. 展开 **"🔑 交易所配置 (API Key)"**，填入刚才获取的测试网 Key 并保存。
3. 在 **"➕ 创建新策略实例"** 中：
   - 执行模式选择：`实盘接入`。
   - 勾选：`使用币安测试网 (Futures Testnet)`。
4. 点击 **"🚀 启动实例"**。

---

## 4. 常见问题排查

*   **Connection refused (Errno 61)**：
    *   检查是否在 HK 服务器上设置了错误的 `http_proxy` 环境变量。
    *   执行 `unset http_proxy` 后再次尝试。
*   **API Key Invalid**：
    *   确认您没有把正式网的 Key 填入到测试网模式中。
    *   确认在 Web 页面启动时勾选了“使用币安测试网”选项。
