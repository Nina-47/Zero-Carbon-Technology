# SPEC: Tab 1 天气总览 — 日照时长 → 太阳总辐射

> **创建日期**: 2026-08-01 | **状态**: 已确认，待实施

---

## 一、改动概述

将 Tab 1 天气总览中的「日照时长 (sunshine_duration)」面积图替换为「太阳总辐射 (shortwave_radiation)」面积图，连带清理所有相关引用。

**核心变更**：`sunshine_duration` → `shortwave_radiation`，单位 **W/m²**（全链路统一）。

---

## 二、影响文件清单（6 个文件）

| # | 文件 | 改动类型 | 说明 |
|---|------|:---:|------|
| 1 | `config.py` | ✏️ 修改 | VIS_PARAMS / EXPORT_PARAMS / AGGREGATION_SUM_PARAMS / convert_units() |
| 2 | `app.py` | ✏️ 修改 | 导入、侧边栏默认、Tab 1 图表渲染、Tab 3 默认列 |
| 3 | `src/charts/weather_charts.py` | ✏️ 修改 | 删 plot_sunshine()，新增 plot_shortwave_radiation() |
| 4 | `src/charts/cards.py` | ✏️ 修改 | 概览卡片中 sunshine_duration → shortwave_radiation |
| 5 | `src/aggregation/province_avg.py` | ✏️ 修改 | 删除注释中对 sunshine_duration 的引用 |
| 6 | `data/weather.db` | ⚠️ 可能重建 | 若缺 shortwave_radiation 列需重建 |

---

## 三、逐文件改动明细

### 3.1 `config.py`

#### A. VIS_PARAMS（第 42 行）
```python
# 删除
"sunshine_duration": {"cn": "日照时长", "unit": "h", "chart": "area"},
# 新增
"shortwave_radiation":     {"cn": "太阳总辐射",    "unit": "W/m²",  "chart": "area"},
```

#### B. EXPORT_PARAMS（第 64 行）
```python
# 删除
"sunshine_duration": {"cn": "日照时长", "unit": "s"},
# 新增（注意按字母顺序插入，约在 snowfall 和 wind_speed_10m 之间）
"shortwave_radiation":      {"cn": "太阳总辐射",         "unit": "W/m²"},
```

#### C. AGGREGATION_SUM_PARAMS（第 83 行）
```python
# 删除 sunshine_duration，不新增 shortwave_radiation（辐射是强度量，取平均）
AGGREGATION_SUM_PARAMS = {
    "precipitation", "rain", "showers", "snowfall",
    "evapotranspiration",
}
```

#### D. convert_units() docstring（第 213 行）
```python
# 删除
- sunshine_duration: 秒 → 小时
```

#### E. convert_units() 函数体（第 219-224 行）
```python
# 整段删除（6 行）
if "sunshine_duration" in df.columns:
    df["sunshine_duration"] = pd.to_numeric(df["sunshine_duration"], errors="coerce")
    max_val = df["sunshine_duration"].max()
    if pd.notna(max_val) and max_val > 100:
        df["sunshine_duration"] = df["sunshine_duration"] / 3600.0  # 秒 → 小时
```

> **注意**：`FORECAST_PARAMS_STR` 和 `ARCHIVE_PARAMS_STR` 是自动从 EXPORT_PARAMS keys 拼接的，无需手动改。

---

### 3.2 `app.py`

#### A. 导入（第 51 行）
```python
# 删除
plot_sunshine,
# 新增
plot_shortwave_radiation,
```

#### B. 侧边栏默认勾选（第 207-211 行）
```python
# sunshine_duration → shortwave_radiation
default_checked = param in [
    "temperature_2m", "apparent_temp_cn",
    "precipitation", "wind_speed_10m", "shortwave_radiation",
]
```

#### C. Tab 1 图表渲染（第 331-336 行）
```python
# 删除日照区块，替换为：
# 太阳辐射
if vis_selection.get("shortwave_radiation", True):
    st.plotly_chart(
        plot_shortwave_radiation(primary_data, primary_label),
        use_container_width=True,
    )
```

#### D. Tab 3 默认列（第 461 行）
```python
# sunshine_duration → shortwave_radiation
default=["temperature_2m", "precipitation", "wind_speed_10m", "shortwave_radiation"][:4],
```

---

### 3.3 `src/charts/weather_charts.py`

#### A. 删除 `plot_sunshine()`（第 165-221 行）
整段删除，约 57 行。

#### B. 新增 `plot_shortwave_radiation()`
```python
def plot_shortwave_radiation(df: pd.DataFrame, location_label: str = "") -> go.Figure:
    """
    太阳总辐射面积图（左Y轴，W/m²）+ 云量折线（右Y轴，%）。
    双Y轴，各自独立刻度，云量不反转。
    """
    if "shortwave_radiation" not in df.columns or "datetime" not in df.columns or df.empty:
        return go.Figure()

    has_cloud = "cloud_cover" in df.columns

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 左Y轴：太阳总辐射面积图
    fig.add_trace(
        go.Scatter(
            x=df["datetime"], y=df["shortwave_radiation"],
            mode="none", name="太阳总辐射",
            fill="tozeroy",
            fillcolor="rgba(243, 156, 18, 0.35)",
        ),
        secondary_y=False,
    )

    # 辐射边界线
    fig.add_trace(
        go.Scatter(
            x=df["datetime"], y=df["shortwave_radiation"],
            mode="lines", name="辐射值",
            line=dict(color="#F39C12", width=1.5),
            showlegend=False,
        ),
        secondary_y=False,
    )

    # 右Y轴：云量折线（不反转，独立刻度）
    if has_cloud:
        fig.add_trace(
            go.Scatter(
                x=df["datetime"], y=df["cloud_cover"],
                mode="lines", name="云量",
                line=dict(color="#7F8C8D", width=1.5, dash="dot"),
            ),
            secondary_y=True,
        )

    fig.update_layout(
        title=f"☀️ 太阳总辐射 {location_label}",
        xaxis_title="时间",
        hovermode="x unified",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="太阳总辐射 (W/m²)", secondary_y=False)
    if has_cloud:
        fig.update_yaxes(title_text="云量 (%)", secondary_y=True, range=[0, 100])

    return fig
```

---

### 3.4 `src/charts/cards.py`

第 86 行概览卡片改字段名：
```python
# 删除
sunshine = latest.get("sunshine_duration", "—")
# 新增
shortwave = latest.get("shortwave_radiation", "—")
```
> 需同步修改对应的卡片渲染行中引用该变量的位置。读文件后确认具体渲染逻辑再精确替换。

---

### 3.5 `src/aggregation/province_avg.py`

第 133 行注释删除：
```python
# 删除此行
# sunshine_duration 已在小时单位，聚合后无需再次换算
```

---

### 3.6 数据库兼容（`data/weather.db`）

**策略**：启动时自动检测 `weather_hourly` 表是否含 `shortwave_radiation` 列。

实现位置：`app.py` 初始化区域或 `src/db/models.py` 的 `init_db()` 中。

```python
# 伪代码 — 插入 init_db() 或 app.py 初始化区域
import sqlite3
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "weather.db")
conn = sqlite3.connect(DB_PATH)
cursor = conn.execute("PRAGMA table_info(weather_hourly)")
cols = [row[1] for row in cursor.fetchall()]
conn.close()

if "shortwave_radiation" not in cols:
    st.warning(
        "⚠️ 数据库缺少 `shortwave_radiation` 列。"
        "请删除 `data/weather.db` 后刷新页面以重新拉取天气数据。"
    )
```

> **注意**：仅提示，不自动删库。用户手动删除后重启 Streamlit 即自动重建。

---

## 四、不做的事

- ❌ 不新增 MJ/m² 单位换算 — 全链路统一 W/m²
- ❌ 不保留 `plot_sunshine()` 备份 — 完全删除
- ❌ 不自动删除数据库 — 仅提示用户
- ❌ 不修改 API 参数拼接逻辑 — `FORECAST_PARAMS_STR` / `ARCHIVE_PARAMS_STR` 自动适配

---

## 五、测试检查清单

- [ ] Tab 1 不再显示「日照时长」图表
- [ ] Tab 1 显示「太阳总辐射」面积图（左Y W/m² + 右Y 云量%）
- [ ] 侧边栏默认勾选含 shortwave_radiation，不含 sunshine_duration
- [ ] 侧边栏取消勾选 shortwave_radiation → 图表消失
- [ ] Tab 3 数据表格默认列含 shortwave_radiation，不含 sunshine_duration
- [ ] Tab 3 导出 CSV/JSON 含 shortwave_radiation 列（W/m²）
- [ ] 概览卡片不再显示日照时长
- [ ] 无 `NameError: name 'plot_sunshine' is not defined` 错误
- [ ] 无 `KeyError: 'sunshine_duration'` 错误
- [ ] 广东省平均（聚合）正常工作
- [ ] 数据库缺列时显示 warning 提示

---

## 六、实施顺序

```
1. config.py      → 改 VIS_PARAMS / EXPORT_PARAMS / AGGREGATION / convert_units()
2. weather_charts.py → 删 plot_sunshine() + 新增 plot_shortwave_radiation()
3. cards.py       → sunshine_duration → shortwave_radiation
4. province_avg.py → 删注释
5. app.py         → 改导入、侧边栏、Tab 1、Tab 3
6. DB 检测        → 在 app.py 或 models.py 加列检测 + warning
7. 启动测试       → streamlit run app.py
```

---

*本 SPEC 基于 3 轮 AskUserQuestion 访谈确认，所有设计决策已锁定。*
