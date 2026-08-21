"""碳核算核心能力（三账分离）。

企业清单账：范围一(CH4/N2O工艺)+范围二(关口净购电×EF_report)+范围三(选报)。
项目减排账：基准情景BE 与 项目情景PE 的差值，扣减泄漏LE。
LCA账：储能设备全生命周期隐含碳与净生命周期减排。
"""

import numpy as np
import pandas as pd

import config as C
from emission_factors import price_to_carbon_intensity, mock_price_curve


class CarbonAccounting:
    def __init__(self, df_hourly: pd.DataFrame, ef_opt: pd.Series = None):
        """df_hourly 需含列：timestamp, load, pv, pv_self, pv_sell, p_bat, p_grid, soc。"""
        self.df = df_hourly.copy()
        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])
        # 逐时碳因子：优先外部传入，缺省用 mock 电价代理
        if ef_opt is not None:
            self.df["ef_opt"] = ef_opt.values
        else:
            price = mock_price_curve(self.df["timestamp"].dt.hour.values)
            self.df["ef_opt"] = price_to_carbon_intensity(pd.Series(price)).values
        self.results = {}

    # ================= 范围一 =================
    def scope1_process(self, q_day: float = C.Q_DAY) -> dict:
        """CH4 与 N2O 工艺过程直接排放。"""
        q_year = q_day * 365.0  # m3/y

        cod_removed = (C.COD_IN - C.COD_EFF) * q_year / 1000.0  # kg/y (mg/L*m3*1000)
        cod_sludge = cod_removed * C.COD_SLUDGE_RATIO
        ch4_mass = (cod_removed - cod_sludge) * C.B0 * C.MCF  # kgCH4/y
        e_ch4_co2e = ch4_mass * C.GWP_CH4  # kgCO2e/y

        tn_removed = (C.TN_IN - C.TN_EFF) * q_year / 1000.0  # kgN/y
        n2o_n = tn_removed * C.EF_N2O  # kgN2O-N/y
        n2o_mass = n2o_n * C.MOL_N2O_N  # kgN2O/y
        e_n2o_co2e = n2o_mass * C.GWP_N2O  # kgCO2e/y

        return {
            "q_year_m3": q_year,
            "cod_removed_kg": cod_removed,
            "cod_sludge_kg": cod_sludge,
            "ch4_mass_kg": ch4_mass,
            "ch4_co2e_kg": e_ch4_co2e,
            "tn_removed_kg": tn_removed,
            "n2o_mass_kg": n2o_mass,
            "n2o_co2e_kg": e_n2o_co2e,
            "scope1_kg": e_ch4_co2e + e_n2o_co2e,
        }

    # ================= 范围二 =================
    def scope2_grid(self) -> dict:
        """企业清单口径范围二：关口净购电 × EF_report。"""
        e_grid = self.df["p_grid"].sum()  # kWh
        c2_report = e_grid * C.EF_REPORT       # kgCO2
        return {
            "e_grid_kwh": e_grid,
            "scope2_kg": c2_report,
            "ef_report": C.EF_REPORT,
        }

    # ================= 项目减排账 =================
    def project_reduction(self) -> dict:
        """基准情景(无储能、光伏仍自用抵消) vs 项目情景。"""
        load = self.df["load"].values
        ef_opt = self.df["ef_opt"].values

        # 基准：无储能，负荷全部由电网 + 光伏自用不足部分
        baseline_grid = np.clip(load - self.df["pv_self"].values, 0, None)
        be = (baseline_grid * ef_opt).sum()

        # 项目：实际净购电
        pe = (self.df["p_grid"] * ef_opt).sum()

        # 泄漏：储能辅助电耗排放
        e_aux = self.df["p_aux"].sum() if "p_aux" in self.df else 0.0
        le = e_aux * C.EF_REPORT

        er = be - pe - le
        return {
            "baseline_grid_kwh": baseline_grid.sum(),
            "project_grid_kwh": self.df["p_grid"].sum(),
            "BE_kg": be,
            "PE_kg": pe,
            "LE_kg": le,
            "ER_kg": er,
            "ER_t": er * C.T_PER_KG,
        }

    # ================= LCA 账 =================
    def lca(self) -> dict:
        """储能设备全生命周期隐含碳与净减排。"""
        sys_cf = C.SYS_EMBODIED  # kgCO2e/kWh
        # 寿命总可放电量 kWh = 容量 * DoD * 循环次数 * 放电效率 * 可用系数
        e_life = (C.BATTERY_CAPACITY * C.DOD * C.N_EFC * np.sqrt(C.ETA_RT) * C.K_AVAIL)
        embodied_total = C.BATTERY_CAPACITY * sys_cf  # kgCO2e
        embodied_net = embodied_total * (1 - C.RECYCLING_RATIO)

        er_op = self.project_reduction()["ER_kg"]
        # 单年隐含碳分摊（寿命年数按循环寿命/年循环次数近似，这里按12年折旧）
        life_years = 12.0
        embodied_annual = embodied_net / life_years

        return {
            "e_life_kwh": e_life,
            "embodied_total_kg": embodied_total,
            "embodied_net_kg": embodied_net,
            "life_years": life_years,
            "embodied_annual_kg": embodied_annual,
            "er_net_yearly_kg": er_op - embodied_annual,
        }

    # ================= 汇总 =================
    def run_all(self) -> dict:
        s1 = self.scope1_process()
        s2 = self.scope2_grid()
        pr = self.project_reduction()
        lc = self.lca()
        self.results = {
            "scope1": s1,
            "scope2": s2,
            "project": pr,
            "lca": lc,
            "total_plant_kg": s1["scope1_kg"] + s2["scope2_kg"],
        }
        return self.results


def mock_hourly_df(n_hours: int = 8760) -> pd.DataFrame:
    """无真实负荷文件时的占位逐时明细。"""
    ts = pd.date_range("2025-07-01", periods=n_hours, freq="h")
    h = ts.hour.values
    load = 8000 + 2000 * np.sin(2 * np.pi * (h - 6) / 24) + np.random.normal(0, 300, n_hours)
    load = np.clip(load, 4000, 12000)
    pv = np.where((h >= 6) & (h <= 18),
                  np.sin(np.pi * (h - 6) / 12) * 5000 * np.random.uniform(0.7, 1.0, n_hours), 0)
    pv_self = pv * 0.94
    pv_sell = pv - pv_self
    p_bat = np.zeros(n_hours)
    df = pd.DataFrame({
        "timestamp": ts,
        "load": load,
        "pv": pv,
        "pv_self": pv_self,
        "pv_sell": pv_sell,
        "p_bat": p_bat,
        "soc": np.zeros(n_hours),
    })
    df["p_aux"] = 0.0
    df["p_grid"] = np.clip(load - pv_self, 0, None)
    return df
