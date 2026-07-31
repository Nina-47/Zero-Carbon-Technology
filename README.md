# 🌤️ 天气负荷分析平台

面向电力负荷预测的天气数据查询与分析工具。

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动应用
streamlit run app.py
```

## 功能

- **天气总览** — 温度/降水/风/日照 时序图表 + 实时概览卡片
- **负荷叠加** — 上传负荷CSV，降水-负荷叠加图 + 温度-负荷散点 + 多因子对比 + Pearson相关性
- **数据导出** — 全量气象参数 CSV/JSON 导出，支持自定义列选择
- **多地点** — 中山市 + 广东省平均（5代表城市聚合）

## 数据源

| 数据源 | 用途 | 
|--------|------|
| Open-Meteo (主) | 历史 ERA5-Land + 预报，免费，无需Key |
| 和风天气 (备) | Open-Meteo 超时时自动切换 |

## 项目结构

```
weather-load-platform/
├── app.py                  # Streamlit 主入口
├── config.py               # 全局配置
├── requirements.txt
├── .streamlit/
│   ├── config.toml         # 主题/服务器配置
│   └── secrets.toml        # API密钥
├── src/
│   ├── api/                # Open-Meteo + 和风天气 + Fallback
│   ├── db/                 # SQLite 持久化
│   ├── aggregation/        # 广东省平均计算
│   ├── charts/             # Plotly 图表 (天气 + 负荷叠加)
│   ├── export/             # CSV + JSON 导出
│   └── utils/              # 时间工具 + CSV解析
└── data/
    └── weather.db          # SQLite 数据文件
```

## 部署

推送到 GitHub 后在 [Streamlit Community Cloud](https://share.streamlit.io) 关联仓库即可自动部署。

配合 [cron-job.org](https://cron-job.org) 或 [UptimeRobot](https://uptimerobot.com) 每30分钟 ping 应用 URL 保持数据新鲜。
