# 残差 LUT 使用说明（26 张）

这套表是**两段式的第二段**：机内的 NCP 管影调，这张表管颜色。顺序不能反。

| 项目 | 内容 |
|---|---|
| 来源 | 同底片（`DSC_4484`）、同机、同 NX Studio 的一对成片（我们的 NCP / 官方 NP3） |
| 拟合 | 13³ 三线性网格，信任域 ±40 级，2×2 分块留出验证 |
| 格式 | `.cube`（33³，Resolve / Premiere / PS / Affinity / FCP 通用） |
| 效果 | 26 支平均 ΔE00 **5.36 → 2.10**，平均差 **6.45 → 3.18 级**；留出 2.13 |
| 前提 | 必须配 `ncp/release/NIKON/CUSTOMPC/PICCONnn.NCP` 同槽号的成片 |

## 一、流程

```
① 卡里装 ncp/release 的 PICCON01…30
② 机身（或 NX Studio「与照相机兼容」）出图 —— 这一步已经拿到影调
③ 把成片套上同名 .cube —— 这一步把颜色补齐
```

```bash
# 单张
python d300/tools/lut_fit.py --apply d300/lut/11_DENIM.cube in.jpg out.jpg

# 整目录
python d300/tools/lut_fit.py --apply-dir d300/lut/11_DENIM.cube in/ out/
```

Resolve / PS / Affinity 里就是「加载 3D LUT」→ 选同名文件，不需要任何调参。

## 二、三条硬约束

1. **表在 NCP 之后**。换回 v1/v2 的 NCP，或改了机内饱和度/色相，这张表就失效
   （它是对着 v3 的残差拟合的）。
2. **槽号必须配对**：`11_DENIM.cube` 只配 `PICCON11.NCP`。
3. **三张是恒等表**（18 GRAPHITE / 19 BINARY / 20 CARBON）：套了画面不会变。
   这三支本来就在可辨阈值附近，拟合没有收益，脚本按「宁可不动」处理。

## 三、逐支一览

`ncp/release` 的槽号 → 表文件名 → 效果（ΔE00 从 → 到）。

| 槽 | 滤镜 | 表 | ΔE00 |
|---|---|---|---|
| 1 | DREAM | `01_DREAM.cube` | 7.93 → 0.93 |
| 2 | MORNING | `02_MORNING.cube` | 11.94 → 0.73 |
| 3 | POP | `03_POP.cube` | 2.92 → 1.51 |
| 4 | SUNDAY | `04_SUNDAY.cube` | 2.06 → 1.49 |
| 5 | SOMBER | `05_SOMBER.cube` | 3.19 → 1.38 |
| 6 | DRAMA | `06_DRAMA.cube` | 4.02 → 1.26 |
| 7 | SILENCE | `07_SILENCE.cube` | 3.83 → 0.86 |
| 8 | BLEACH | `08_BLEACH.cube` | 6.57 → 0.94 |
| 9 | MELANCHOLIC | `09_MELANCHOLIC.cube` | 6.95 → 1.03 |
| 10 | PURE | `10_PURE.cube` | 9.09 → 0.82 |
| 11 | DENIM | `11_DENIM.cube` | 13.78 → 1.45 |
| 12 | TOY | `12_TOY.cube` | 10.39 → 2.03 |
| 13 | SEPIA | `13_SEPIA.cube` | 7.04 → 4.60 |
| 14 | BLUE | `14_BLUE.cube` | 6.42 → 4.73 |
| 15 | RED | `15_RED.cube` | 10.51 → 6.42 |
| 16 | PINK | `16_PINK.cube` | 8.32 → 5.82 |
| 17 | CHARCOAL | `17_CHARCOAL.cube` | 1.08 → 0.83 |
| 18 | GRAPHITE | `18_GRAPHITE.cube` | 恒等 |
| 19 | BINARY | `19_BINARY.cube` | 恒等（影调问题，该由曲线管） |
| 20 | CARBON | `20_CARBON.cube` | 恒等 |
| 21 | FLAT | `21_FLAT.cube` | 2.67 → 0.96 |
| 26 | LANDSCAPE | `26_LANDSCAPE.cube` | 2.42 → 1.33 |
| 27 | MONOCHROME | `27_MONOCHROME.cube` | 1.19 → 1.09 |
| 28 | NEUTRAL | `28_NEUTRAL.cube` | 2.11 → 1.10 |
| 29 | STANDARD | `29_STANDARD.cube` | 1.53 → 1.21 |
| 30 | VIVID | `30_VIVID.cube` | 2.83 → 1.47 |

`00_共用_global.cube` 是**反证用的**：所有支汇总拟合一张，结果平均差 7.02 级
（不套是 6.45），比不套还差 —— 所以必须逐支。

方法与全部数据见 [../docs/18-residual-lut.md](../docs/18-residual-lut.md)。
