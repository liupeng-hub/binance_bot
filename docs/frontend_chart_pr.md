# 独立前端 K 线页面需求与技术方案

## 1. 目标
- 解决 Streamlit iframe/srcdoc + CSP 导致的脚本加载失败、API 不可用、整页刷新闪烁问题
- 提供稳定、高性能、可扩展的专业级 K 线展示，支持首屏历史数据 + WebSocket 增量更新
- 与后端 REST/WS 接口保持兼容，零侵入现有 Python 服务

## 2. 功能范围 (MVP)
1. 主图：蜡烛图 (Candlestick)，支持缩放、平移、十字光标、图例
2. 副图：指标面板 (Histogram/Line，如 MACD/成交量)
3. 交易标记：箭头 + 文字标注买卖点
4. 数据获取：
   - 首屏：GET /api/candles?inst_id={id}&limit=500
   - 实时：WS /ws/candles/{inst_id} 推送最新一根或新 bar
5. 断线重连：WebSocket 自动重连，指数退避
6. 错误兜底：网络异常时展示 Plotly 静态图按钮，保证“必有图”

## 3. 非功能要求
- 同源部署：前后端统一域名，CSP 以 'self' 为主，禁止外链脚本
- 性能：5 万根 K 线拖动流畅；内存占用稳定，路由切换时销毁图表实例
- 兼容：Chrome/Firefox/Safari/Edge 近 2 年版本；移动端适配
- 打包体积：gzip < 300 KB (不含数据)

## 4. 技术选型
- 构建：Vite + React + TypeScript
- 图表：lightweight-charts 4.x (MIT) — 金融级性能，体积小
- 状态：Zustand (轻量) 管理全局实例与数据流
- 路由：React-Router v6 — 支持多实例多图页
- UI：Tailwind CSS — 快速样式，按需打包
- 代理：开发期 Vite proxy → http://localhost:8000；生产 Nginx 统一端口

## 5. 接口约定
### 5.1 REST — 历史数据
GET /api/candles?inst_id={id}&limit={n}
→ 200
[
  { "time": 1700000000, "open": 1, "high": 2, "low": 0.9, "close": 1.8, "volume": 1234 }, ...
]
- time：Unix 秒整数；按 time 升序
- 空数组返回 []，前端展示“暂无历史数据”

### 5.2 WebSocket — 实时增量
ws://host/ws/candles/{inst_id}
客户端发：无（连接即订阅）
服务端推：
{ "type": "candle", "data": { "time": 1700000100, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ... } }
- 同一根更新多次：前端用 series.update() 覆盖最后一根
- 新 bar：time 递增，自动追加

### 5.3 错误格式
HTTP 非 200 或 WS close code ≠ 1000 → 前端弹提示并尝试重连/降级

## 6. 前端架构
```
src/
  main.tsx          — 入口，路由与全局样式
  pages/
    ChartPage.tsx   — 单图页：接收 inst_id 参数，挂载图表
  components/
    ChartWidget.tsx — 封装 lightweight-charts 容器、resize、主题
    IndicatorPane.tsx — 副图指标面板
    TradeMarkers.tsx  — 买卖点标记转换
  hooks/
    useChartData.ts   — REST 首屏 + WS 订阅逻辑，返回 [candles, updateLast]
    useWS.ts          — 通用 WebSocket 钩子（自动重连、心跳）
  stores/
    chartStore.ts     — Zustand：保存 series 实例、指标数据、加载态
  utils/
    http.ts           — fetch 封装，超时/重试
    formatters.ts     — 价格、时间格式化
  types/
    api.ts            — 接口类型定义
```

## 7. 关键实现要点
- 容器尺寸：CSS grid 或 flex 保证图表自适应；监听 resize → chart.applyOptions({ width, height })
- 数据对齐：REST 与 WS 时间戳单位一致（秒）；更新前对比最后一根 time，避免重复插入
- 指标渲染：后端返回指标数组 { time, value }，前端用 addLineSeries/addHistogramSeries 叠加
- 标记渲染：后端返回 { time, position, color, shape, text }，用 setMarkers() 一次性写入
- 主题切换：提供 light/dark 两套 chartOptions，通过 store 切换
- 销毁清理：组件卸载时 chart.remove() 并关闭 WS，防止内存泄漏

## 8. 部署与构建
### 8.1 开发
npm run dev → Vite 启动 https://localhost:5173，代理 /api 与 /ws 到 8000
访问示例：http://localhost:5173/chart/078b47c6-8081-4f89-b1dc-6fbc6c9ad873

### 8.2 生产
npm run build → dist/ 静态资源
Nginx 配置：
```
location / {
  root /path/to/dist;
  try_files $uri $uri/ /index.html;
}
location /api/ {
  proxy_pass http://localhost:8000;
}
location /ws/ {
  proxy_pass http://localhost:8000;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
}
```
统一域名后 CSP 可设为：
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://yourdomain wss://yourdomain;

## 9. 验收标准
✅ 首屏 500 根 K 线 1 秒内渲染完成，拖动无掉帧
✅ WS 断网 5 秒内自动重连，重连后数据无缺口
✅ 切换实例路由 < 300 ms，旧实例销毁无内存上涨
✅ 移动端横屏适配，双指缩放流畅
✅ 关闭外链脚本后图表正常加载（Lighthouse CSP 无错误）

## 10. 后续扩展（可选）
- 多图对比：同一页面多实例 grid 布局，共享时间轴
- 回放模式：历史滑块控制，模拟实时推送
- 画线工具：通过 lightweight-charts 插件或自研 overlay 实现
- 导出：PNG/SVG 截图、CSV 数据下载
- 键盘快捷键：← → 缩放/移动，Ctrl+S 截图

---
文档版本：v1.0
维护人：Web Dev Agent
更新日期：2026-02-11