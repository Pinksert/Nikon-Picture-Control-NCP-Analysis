# 用 sidecar 一次导出 30 张（免手点 30 次）

> 状态（2026-10-31 17:30 更新）：**模板已拿到并解析完毕，30 份批次 A 已生成**。
> V4 失败的真因找到了：**套用自定义滤镜时 sidecar 要写两处数据，只改一处会回落 STANDARD**。
> 详见下面「五·0」。
> 回退方案永远是 [12-render-new-samples.md](12-render-new-samples.md) 里的人工逐个套用。

---

## 一、为什么需要这条路

NX Studio **没有批处理功能**。这不是没找到菜单，是查过安装目录里全部 10 个语言文件（`.nlf`）后的结论：
`Batch` 只出现在一条警告文案里（`IDS_WARNING_MESSAGE_CONFLICTPROCESS_IMPOSSIBLE_BATCH_MAIN`
「您尝试导出的文件正在由另一进程使用」），没有任何菜单项叫批处理/批量转换。

所以按常规做法，30 个滤镜就是「套一个 → 导出一次」重复 30 遍。

---

## 二、sidecar 里有什么

NX Studio 的调整文件（`*.NEF.nksc`）是 XMP 文本，其中 `nikon::PictureControl` 过滤器长这样：

```xml
<filter id="nikon::PictureControl">
  <active>true</active>
  <parameters>
    <Export>
      <ExportData>TkNQAAAAAQAAAAAE...</ExportData>   ← 滤镜文件本体，base64
      <ExportDataSize>533</ExportDataSize>
    </Export>
    <SelectedPictureControl>0</SelectedPictureControl>
    <PictureControl>14</PictureControl>
    ...
```

**关键实测结论（2026-10-31）**：

| 观察 | 结果 |
|---|---|
| `<ExportData>` 里是什么 | **滤镜文件本体**，不是私有序列化格式。内嵌的 392 字节与磁盘 `滤镜/DREAM.NP3` 前 80 字节**逐字节相同**（只差版本串 `0300` / `0310`） |
| sidecar 是否与文件名绑定 | **否**。`rdf:about=""`，也没有 `OriginalFileName`/`documentID` 一类字段 |
| `<PictureControl>` 编号 | 已知两个：DREAM=14、PORTRAIT=10。NCP（自定义优化校准）的编号未知 |

sidecar 不与文件名绑定，意味着：**同一张 NEF 复制 N 份，每份配一个只改了 `<ExportData>` 的 sidecar，
全选 → 导出一次，就能得到 N 张套了不同滤镜的图。**

### 补齐公式（fixup）—— 直接塞磁盘文件为什么会失败

第一版验证里「磁盘文件直接塞进去」不生效，原因找到了：

```
磁盘滤镜文件    卡 0x01 … 0x16        （22 张，截止在 244 字节）
NX Studio 存的  卡 0x01 … 0x20        （32 张，392 字节）
                                 └── 多出卡 0x17–0x20，共 144 字节
```

这 144 字节在 DREAM 和 PORTRAIT 两个样例里**完全相同**，是固定补齐段。
加上它、再把版本串 `0300` 改成 `0310`：

```python
sidecar_bytes = disk[:244] + FIX144 + b'\x00\x00\x00\x00'   # 并把 [14] 改成 '1'
```

实测：**DREAM、PORTRAIT 两支构造结果与 NX Studio 亲生的字节逐字节完全一致（0 差异）**，
28 个磁盘 NP3 全部适用。函数 `sidecar_batch.fixup()`。

⚠️ 该公式只对 **NP3 布局**有效。NCP（我们的产物）是另一套：2 张大卡（638 字节），
卡编号体系都不一样（`00000001` vs `00000100`），能不能直接塞**待验**（见 V4）。

---

## 三、前提（不设对整条路都不通）

`编辑` → `首选项` → 勾上 **「将调整、标签和评级内容保存到附属文件(照片编辑历史记录)」**
（原文 `IDS_PREFERENCES_SAVE_FORMAT_SIDECAR`）。

不勾的话 NX Studio 会把调整写回 NEF 内部，sidecar 根本不会被读。

---

## 四、第一步：判定（4 张验证包，零风险）

工具已经生成好了：

```
C:\Users\admin\WorkBuddy\D300固件\_sidecar_probe\
    V1.NEF + V1.NEF.nksc   模板原样，NX Studio 亲生的 DREAM（392 字节）
    V2.NEF + V2.NEF.nksc   磁盘 DREAM.NP3 经 fixup 补齐（392 字节，与 V1 逐字节相同）
    V3.NEF + V3.NEF.nksc   磁盘 MONOCHROME.NP3 经 fixup（黑白，一眼可辨）
    V4.NEF + V4.NEF.nksc   我们的 v3 NCP（PICCON01，638 字节），直接塞本体
```

重新生成：`python d300/tools/sidecar_batch.py probe`

**在 NX Studio 里打开这个文件夹，看四张缩略图显示的「优化校准」名**：

| 看到什么 | 结论 |
|---|---|
| V1 显示 STANDARD | sidecar 没被读取 → **此路不通**，回退人工方案 |
| V1 显示 DREAM，V2/V3 也各自正确 | fixup 补齐公式**实机有效**，NP3 可批量 |
| V1 显示 DREAM，V2 显示 STANDARD | 补齐公式不对（字节层面已验证一致，这种情况概率很低） |
| **V4 显示 DREAM** | **NCP 可直接塞本体 → 整条路通了，不用做模板** |
| **V4 显示 STANDARD** | NCP 需要 NX Studio 生成的模板，见下面情形 B |

V3 顺带告诉我们 `<PictureControl>` 编号和 `<ExportData>` 谁优先：

- 显示 **MONOCHROME** → 以 ExportData 为准，批量时编号沿用模板即可（最省事）
- 显示 **DREAM** → 以编号为准（13 是推测值，猜错就会显示错滤镜）

---

## 五、第二步：批量生成

## 五·0 关键发现：自定义滤镜要写**两处**（V4 失败的真因）

拿到的模板 `lightroom/NKSC_PARAM/DSC_4484.NEF.nksc`（套的是我们导入的 `PICCON01.NCP`，
NX Studio 显示 DREAM）解析结果：

| 项 | 值 |
|---|---|
| `<PictureControl>` | **1** |
| `<ExportData>` | 638 字节，NCP 布局，名字 DREAM，版本串 `0100` |
| `<CustomData>` | 638 字节，**与 ExportData 只差第 38 字节**（Export=0x02，Custom=0x00） |
| `<ExportDataSize>` / `<CustomDataSize>` | 867（= base64 文本长度 852 + 15 个换行，不是字节数） |

对比内置滤镜的 sidecar（V1，392 字节）：**只有 `<ExportData>`，没有 `<Custom>` 节点**。
也就是说 NX Studio 对「内置滤镜」和「导入的自定义滤镜」写的是两套结构 ——
我们之前把 NCP 只塞进 `ExportData`（V4），结构不全，于是直接回落成 STANDARD。

模板与磁盘 `PICCON01.NCP` 逐字节比对：**卡 1、卡 2 头部、全部控制点完全相同**，
只有 LUT 区不同 —— 说明 NX Studio 读入我们的控制点后**按自己的插值重算了 LUT**。
这一点对我们有利：控制点才是曲线的本体，它没被改。

`_embed_one()` 因此做三件事：两处都写、base64 每 60 字符一行（与亲生模板同排版）、
size 字段写成 base64 文本长度。生成的 30 个 sidecar 已校验：
**除两段 base64 外，XML 与模板逐字相同**。

---

### 情形 A（T2 也显示 DREAM）—— 直接用磁盘 NCP

```bash
python d300/tools/sidecar_batch.py make ^
  --template "C:/Users/admin/WorkBuddy/D300固件/lightroom/NKSC_PARAM/DSC_4484.NEF.nksc" ^
  --nef     "<你的 DSC_3891.NEF 路径>" ^
  --filters "d300/ncp/release/NIKON/CUSTOMPC" ^
  --out     "_render_v3"
```

### 情形 B（V4 显示 STANDARD）—— 让 NX Studio 亲自生成一个模板

> 已确认：V4（我们的 638 字节 NCP 直接塞进 `<ExportData>`）在 NX Studio 里**回落成 STANDARD**，
> 说明 NCP 是另一套布局，必须借 NX Studio 自己写出来的字节当模板。

下面每一步都在 NX Studio 界面里做，不需要懂命令行。

#### B-0 开开关（只做一次，没做对整条路都不通）

`编辑` → `首选项` → 勾上 **「将调整、标签和评级内容保存到附属文件(照片编辑历史记录)」**

⚠️ 如果你前面没勾过，现在勾上之后，之前生成的任何 sidecar 都要重来一遍。

#### B-1 导入我们的 NCP（先只导 1 个）

1. NX Studio：`文件` → `导入自定义优化校准(&I)…` → `从文件导入`
2. 选目录 `D300固件\d300\ncp\release\NIKON\CUSTOMPC`，里面 30 个 `PICCON01.NCP … PICCON30.NCP`
3. **先只导 `PICCON01.NCP`**（它就是 01 DREAM）—— 生成模板只需要 1 个
   （槽位有限的话更不要一次导 30 个）
4. 导入后在优化校准下拉里应能看到一个新条目，名字形如 `01 DREAM`，**记下它显示的名字**

#### B-2 让 NX Studio 亲手写出一个 sidecar

1. 新建一个空文件夹，比如 `_template`
2. 拷一张 NEF 进去（直接用 `_sidecar_probe\V1.NEF` 也行）
3. NX Studio 打开这个文件夹 → 双击打开那张 NEF
4. 编辑面板 → **优化校准** → 选刚导入的那个自定义滤镜（01 DREAM）
5. 切到别的图 / 直接关闭，让 NX Studio 落盘
6. 回文件夹看，应多出一个 `xxx.NEF.nksc` —— **这就是模板**

顺手目视确认一下：缩略图上显示的优化校准名是不是「01 DREAM」。
如果不是，说明导入那一步没成功，先别往下走。

#### B-3 把模板交给我

模板拷到 `d300/_template/`（或直接把路径发我），我跑：

```bash
python d300/tools/sidecar_batch.py inspect ^
  --template "<模板 .nksc 路径>" ^
  --filter   "d300/ncp/release/NIKON/CUSTOMPC/PICCON01.NCP"
```

它会打印：NX Studio 把我们的 NCP 存成了几张卡、一共多少字节、和磁盘原文件差在哪几个字节。
三种可能：

| 打印结果 | 怎么办 |
|---|---|
| 只是多了补齐段 / 改了版本串 | 我把这个变换抄下来，30 个全适用，最省事 |
| 被重新编码成另一套布局 | 我把变换写成函数逐个套，仍然全自动 |
| 带了槽位号、序号之类上下文 | 无法复现 → 回退人工套 30 次 |

#### B-4 批量生成

```bash
python d300/tools/sidecar_batch.py make ^
  --template "<模板 .nksc 路径>" ^
  --nef      "<你的源 NEF>" ^
  --filters  "d300/ncp/release/NIKON/CUSTOMPC" ^
  --out      "_render_v3"
```

模板只用来提供**骨架和 `<PictureControl>` 编号**，滤镜字节仍然来自磁盘上的 NCP 文件。
脚本不凭空构造字节，只替换 NX Studio 自己写过的东西，所以兼容性由 NX Studio 自己保证。

脚本会逐个打印「往返 OK」，确认嵌进去的和原文件逐字节一致。然后按第六节导出。

---

## 六、第三步：导出

1. 打开 `_render_v3` 文件夹（30 份 NEF + 30 个同名 sidecar，命名规则 `原文件全名 + .nksc`）
2. 缩略图若没变化：找「重新读取调整信息」一类命令，或重启 NX Studio
3. `Ctrl+A` 全选 → `文件` → `导出(&E)...`
4. 设置：**sRGB、长边 600px、质量 ≥90**，文件名选**与源文件同名**
5. 得到 `01_DREAM.jpg` … `30_VIVID.jpg`，正好是 [real_render_check.py](../tools/real_render_check.py) 期望的命名

渲完：

```bash
python d300/tools/real_render_check.py --dir real_v3
```

---

## 七、已知风险与边界

| 项 | 状态 |
|---|---|
| NX Studio 读 sidecar | **已验证**：V1 显示 DREAM，sidecar 会被读取 |
| 磁盘 NP3 直接嵌 | **已验证不行**，但补齐公式 fixup 已还原出与 NX Studio 完全一致的字节，**实机待 V2/V3 确认** |
| 磁盘 **NCP** 能否直接嵌 | **已验证不行**：V4 回落成 STANDARD。NCP 是 2 张大卡的另一套布局，fixup 不适用 → 走情形 B 借模板 |
| 源 NEF | 本机 4 张 D300 NEF（DSC_4484/5658/8100/9308）经结构相关性比对**都不是**原样片 DSC_3891（相关 0.06–0.20）。方案 A 需要你提供 DSC_3891.NEF |
| 磁盘占用 | 30 份 × 约 12 MB ≈ 360 MB |
| 色彩程序 | 仍然必须设「**与照相机兼容**」，两处都要（首选项 + 编辑面板），这一点与 sidecar 无关 |
| 编号 vs 内嵌，谁优先 | **待实机确认**：`<PictureControl>=1` 沿用模板，若 NX Studio 以编号为准，30 张会全显示同一个。打开 `_render_v3` 看缩略图名字即可判定 |
| 底片 | 现有对照 `samples/workshop/` 是 **DSC_3891**（2848×4288 竖构图）渲的，与本次源 `DSC_4484.NEF`（4288×2848 横构图）**不是同一张**，两边都要用 4484 重渲才能比 |

---

## 八、如果这条路走不通

回退到 [12-render-new-samples.md](12-render-new-samples.md)：逐个套用、逐个导出，30 次。
建议仍然**先渲 01 DREAM + 17 CHARCOAL 两张**验证色彩程序设置，别一次渲 30 张白干。
