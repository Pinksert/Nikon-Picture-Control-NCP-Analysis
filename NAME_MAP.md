# 尼康优化校准中英对照表

NCP 文件的名字区是 20 字节 ASCII，装不下中文，所以本仓库生成的 NCP 全部用英文名。
这张表用来把「尼康软件/相机菜单里的中文名」对应到「文件名」。

## 一、20 个创意优化校准（Creative Picture Control）

菜单里的编号 01–20 与文件里的底子编号 0801–0814 一一对应（0x14 = 20）。

| 编号 | 中文名 | 文件名 | 底子编号 | 生成的 NCP | 类别 |
|---|---|---|---|---|---|
| 01 | 梦幻 | DREAM | 0801 | DREAM_curve.NCP | 彩色 |
| 02 | 清晨 | MORNING | 0802 | MORNING_curve.NCP | 彩色 |
| 03 | 流行 | POP | 0803 | POP_curve.NCP | 彩色 |
| 04 | 星期天 | SUNDAY | 0804 | SUNDAY_curve.NCP | 彩色 |
| 05 | 低沉 | SOMBER | 0805 | SOMBER_curve.NCP | 彩色 |
| 06 | 戏剧 | DRAMA | 0806 | DRAMA_curve.NCP | 低饱和 |
| 07 | 静寂 | SILENCE | 0807 | SILENCE_curve.NCP | 低饱和 |
| 08 | 漂白 | BLEACH | 0808 | BLEACH_curve.NCP | 低饱和 |
| 09 | 忧郁 | MELANCHOLIC | 0809 | MELANCHOLIC_curve.NCP | 彩色 |
| 10 | 纯净 | PURE | 080A | PURE_curve.NCP | 彩色 |
| 11 | 牛仔布 | DENIM | 080B | DENIM_curve.NCP | 彩色 |
| 12 | 玩具 | TOY | 080C | TOY_curve.NCP | 彩色 |
| 13 | 棕褐色 | SEPIA | 080D | SEPIA_curve.NCP | 单色+调色 |
| 14 | 蓝色 | BLUE | 080E | BLUE_curve.NCP | 单色+调色 |
| 15 | 红色 | RED | 080F | RED_curve.NCP | 单色+调色 |
| 16 | 粉色 | PINK | 0810 | PINK_curve.NCP | 单色+调色 |
| 17 | 木炭 | CHARCOAL | 0811 | CHARCOAL_curve.NCP | 单色 |
| 18 | 石墨 | GRAPHITE | 0812 | GRAPHITE_curve.NCP | 单色 |
| 19 | 双色 | BINARY | 0813 | BINARY_curve.NCP | 单色 |
| 20 | 黑碳 | CARBON | 0814 | CARBON_curve.NCP | 单色 |

说明：第 20 项尼康官方页面有「黑碳」「黑炭」两种写法，这里取影像库中文帮助的写法。

## 二、最新优化校准系统的基础预设

| 缩写 | 中文名 | 文件名 | 底子编号 | 生成的 NCP |
|---|---|---|---|---|
| SD | 标准 | STANDARD | 0001 | STANDARD_curve.NCP |
| NL | 自然（中性） | NEUTRAL | 03C2 | NEUTRAL_curve.NCP |
| VI | 鲜艳 | VIVID | 00C3 | VIVID_curve.NCP |
| MC | 单色 | MONOCHROME | 064D | MONOCHROME_curve.NCP |
| FM | 平面单色 | FLAT_MONOCHROME | 0654 | FLAT_MONOCHROME_curve.NCP |
| DM | 深色调单色 | DEEPTONE_MONOCHROME | 0655 | DEEPTONE_MONOCHROME_curve.NCP |
| PT | 人像 | PORTRAIT | 0486 | （单独校准版：PORTRAIT_curve_v3.NCP） |
| RP | 丰富色调人像 | RICH_TONE_PORTRAIT | 0493 | RICH_TONE_PORTRAIT_curve.NCP |
| LS | 风景 | LANDSCAPE | 04C7 | LANDSCAPE_curve.NCP |
| FL | 平面 | FLAT | 028E | FLAT_curve.NCP |
| FC | 灵活颜色 | FLEXIBLE_COLOR | 0020 | FLEXIBLE_COLOR_curve.NCP |
| A | 自动 | AUTO | 02CF | （参数全为"不适用"，只能落到标准） |

## 三、NCP 时代（D300/D300S/D90）认得的六个

老机身的 NCP 只认这六个底子，它们也是转换时用来"落地"的载体：

| 中文名 | 文件名 | 底子编号 |
|---|---|---|
| 标准 | STANDARD | 0001 |
| 中性 | NEUTRAL | 03C2 |
| 鲜艳 | VIVID | 00C3 |
| 人像 | PORTRAIT | 0486 |
| 风景 | LANDSCAPE | 04C7 |
| 单色 | MONOCHROME | 064D |

## 四、单色滤镜与调色（NCP 里的枚举值）

单色滤镜：0 关、1 黄、2 橙、3 红、4 绿

单色调色：0 黑白、1 棕褐、2 青、3 红、4 黄、5 绿、6 蓝绿、7 蓝、8 紫蓝、9 红紫
（棕褐/蓝/红已确认；粉色按 9 红紫处理，未实测）

## 五、为什么文件里不能写中文

NCP 的名字区是 20 字节 ASCII，且老机身（D300）的界面也不显示中文预设名。
所以本机内看到的仍然是英文名——这张表是给你对照用的。
若要改显示名，只能自己编辑 NCP 的第 16–35 字节，且只能用 ASCII。
