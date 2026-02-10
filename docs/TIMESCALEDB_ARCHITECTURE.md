# TimescaleDB 架构设计指南

**文档版本**: v1.0
**创建时间**: (2026-02-09)
**目标**: 了解 TimescaleDB 的技术架构和使用场景

---

## �回答核心问题

**Q: 支持时间序列扩展（TimescaleDB），要求PostgreSQL数据库吗？**

**A: 是的，TimescaleDB 必须基于 PostgreSQL，不能单独使用。**

---

## 📊 TimescaleDB 技术架构

### TimescaleDB 是什么？

**TimescaleDB** 是一个 **PostgreSQL 的扩展（Extension）**，专门优化时间序列数据。

```
┌─────────────────────────────────────┐
│         TimescaleDB                │  ← 扩展层
│  (时间序列优化功能)                 │
└─────────────────────────────────────┘
              ↑ 依赖
┌─────────────────────────────────────┐
│         PostgreSQL                 │  ← 基础数据库
│  (关系型数据库核心)                 │
└─────────────────────────────────────┘
```

### 关键特性

| 特性 | 说明 |
|------|------|
| **依赖关系** | 必须安装在 PostgreSQL 上 |
| **兼容性** | 完全兼容 PostgreSQL SQL |
| **安装方式** | `CREATE EXTENSION timescaledb;` |
| **数据类型** | 在 PostgreSQL 表基础上创建 Hypertables |

---

## 🔄 SQLite vs PostgreSQL + TimescaleDB

### 当前项目状态

```
┌─────────────────────────────────────┐
│         当前使用 SQLite            │
│  - 单文件存储                      │
│  - 无需独立数据库服务              │
│  - 适合小规模应用                  │
└─────────────────────────────────────┘
```

### 迁移到 PostgreSQL + TimescaleDB

```
┌─────────────────────────────────────┐
│         PostgreSQL + TimescaleDB  │
│  - 独立数据库服务                  │
│  - 支持高并发                     │
│  - 时间序列自动分区               │
│  - 历史数据压缩                   │
└─────────────────────────────────────┘
```

---

## 🎯 为什么要使用 TimescaleDB？

### 1. 时间序列数据优化

量化交易系统产生大量时间序列数据：

| 数据类型 | 示例 | 每日数据量 |
|----------|------|-----------|
| **K线数据** | BTC/USDT 1m | 1440 条 |
| **净值曲线** | 账户权益 | 1440 条 |
| **交易记录** | 订单/成交 | 10-1000 条 |
| **信号记录** | 策略信号 | 10-1000 条 |

**单日数据量估算**（10 个交易对）：
```
K线: 10 × 1440 = 14,400 条
净值: 10 × 1440 = 14,400 条
交易: 100 条
信号: 100 条
总计：~29,000 条/天
```

**月度数据量**：
```
29,000 × 30 = 870,000 条
```

### 2. TimescaleDB 核心优势

#### A. 自动分区

```sql
-- 创建普通表
CREATE TABLE klines (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume FLOAT
);

-- 转换为 Hypertable（自动按时间分区）
SELECT create_hypertable('klines', 'time');
```

**效果**：
- 自动按时间范围分区（如每 7 天一个分区）
- 查询时自动扫描相关分区，跳过不相关数据
- 删除历史数据只需 `DROP PARTITION`，无需逐条删除

#### B. 高效时间范围查询

```sql
-- 查询最近 7 天的 K 线
SELECT * FROM klines
WHERE symbol = 'BTCUSDT'
  AND time > NOW() - INTERVAL '7 days';
```

**性能对比**：
| 数据库 | 1 年数据查询 | 5 年数据查询 |
|--------|-------------|-------------|
| SQLite | 50-100ms | 500-1000ms |
| PostgreSQL | 30-50ms | 200-300ms |
| **PostgreSQL + TimescaleDB** | **10-20ms** | **50-100ms** |

#### C. 连续聚合

```sql
-- 预计算每日 K 线
CREATE MATERIALIZED VIEW daily_klines
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    symbol,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM klines
GROUP BY day, symbol;
```

**效果**：
- 实时维护聚合结果
- 查询每日数据时无需实时计算
- 性能提升 10-100 倍

#### D. 数据压缩

```sql
-- 启用自动压缩（7 天前的数据）
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);

-- 设置压缩策略
SELECT add_compression_policy('klines', INTERVAL '7 days');
```

**效果**：
- 历史数据压缩率：10:1
- 存储成本降低 90%
- 查询性能提升（读取压缩数据更快）

---

## 📈 规模建议

### 什么时候迁移到 PostgreSQL？

| 数据规模 | 推荐方案 | 理由 |
|---------|---------|------|
| **< 10 GB** | SQLite | SQLite 足够 |
| **10-100 GB** | PostgreSQL | 并发性能需求 |
| **100 GB - 1 TB** | PostgreSQL + TimescaleDB | 时间序列优化 |
| **> 1 TB** | PostgreSQL + TimescaleDB + 分片 | 分布式存储 |

### 量化交易场景推荐

**当前项目分析**：

```
假设场景：
- 交易对数量：10 个
- 时间周期：1m, 5m, 15m, 1h, 4h, 1d（6 个周期）
- 历史数据：1 年
- 用户数量：5 个

数据量估算：
K线：10 × 6 × 1440 × 365 = 31,536,000 条
净值：5 × 1440 × 365 = 2,628,000 条
交易：假设每天 100 笔 × 365 = 36,500 条

总数据量：~3500 万条
存储空间：约 5-10 GB（未压缩）
```

**建议**：
- **短期（< 6 个月）**: SQLite 足够
- **中期（6-18 个月）**: 建议迁移到 PostgreSQL
- **长期（> 18 个月）**: PostgreSQL + TimescaleDB

---

## 🛠️ 迁移步骤（如果选择迁移）

### 1. 安装 PostgreSQL + TimescaleDB

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-14
sudo apt-get install timescaledb-2-postgresql-14

# 启用 TimescaleDB
sudo -u postgres psql -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

### 2. 导出 SQLite 数据

```bash
# 使用 pgloader 迁移
pgloader sqlite:///binance_bot.db postgresql://user:pass@localhost/binance_bot
```

### 3. 修改数据库配置

```python
# config.py
DATABASE_URL = "postgresql://user:pass@localhost/binance_bot"
```

### 4. 创建 Hypertables

```sql
-- K 线数据表
SELECT create_hypertable('klines', 'time');

-- 净值曲线表
SELECT create_hypertable('equity_records', 'timestamp');

-- 交易记录表
SELECT create_hypertable('trades', 'timestamp');
```

### 5. 启用数据压缩

```sql
-- 30 天前数据自动压缩
SELECT add_compression_policy('klines', INTERVAL '30 days');
SELECT add_compression_policy('equity_records', INTERVAL '30 days');
SELECT add_compression_policy('trades', INTERVAL '30 days');
```

---

## 💡 总结

### 回答你的问题

**Q: 支持时间序列扩展（TimescaleDB），要求PostgreSQL数据库吗？**

**A: 是的，TimescaleDB 必须基于 PostgreSQL。**

```
TimeScaleDB = PostgreSQL + 扩展
```

### 迁移建议

**当前项目**：
- ✅ 数据规模：小（< 10 GB）
- ✅ 用户数量：少（< 10 个）
- ✅ 建议：**短期内继续使用 SQLite**

**何时迁移**：
- 📊 数据量 > 10 GB
- 👥 用户数 > 50
- ⚡ 需要高并发查询
- 📅 需要保留多年历史数据

### 迁移成本

- ⏱️ 时间：1-2 天
- 💰 成本：需要独立的数据库服务器
- 🔧 复杂度：中等

---

## 📚 参考资源

- [TimescaleDB 官方文档](https://docs.timescale.com/)
- [PostgreSQL 官方文档](https://www.postgresql.org/docs/)
- [pgloader 迁移工具](https://pgloader.readthedocs.io/)

---

**文档结束**

如有任何问题，请联系技术支持。
