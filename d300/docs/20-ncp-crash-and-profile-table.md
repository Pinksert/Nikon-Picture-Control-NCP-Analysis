# 闪退的真凶：一个查不到就返回「表长」的查找函数

> 状态（2026-11-02 11:40，**已结案**）：闪退机制彻底查清，结论是「此路不通」。
> 第一次 `_probe_batch`（含 B8）、第二次 `_probe_batch_fix`（去掉 B8）、
> 第三次 `_probe_kind8`（第 38 字节写 0x08）——**三次同一崩溃签名**
> （`Rome2.dll 2.9.1.3000`，`0xc0000005`，偏移 `0x13d8f2`）。
> 第三次反汇编把调用链走到底：`kind` 取自 `[profile+0x1b0]`，**不是从文件某个字节
> 读的**，写第 38 字节改变不了它。
> ⇒ **08xx 创意底子在 NCP 里无法表达**，16 支「创意底·彩色」的底子这一层永远拿不到。
> 完整实测与处置见 [21-namespace-byte.md](21-namespace-byte.md) 第八节；
> 对整条路线的影响见 [22-in-camera-ceiling-locked.md](22-in-camera-ceiling-locked.md)。
>
> 本文第二~四节的反汇编与注册表 dump **仍然有效**（查表函数、38 项、就地失守），
> 第五节「第 38 字节是什么」的三选一已由 19 的第八节判为 B。
>
> 原始记录（2026-11-02 11:20）：已定位到指令级。`_probe_batch` 让 NX Studio 闪退，
> 不是文件坏了、不是文件名、不是扫描时序，而是我们写了一个**它注册表里不存在的底子编号**：
> `0x0813`。查不到之后 NX Studio 没有做边界检查，直接拿「表长」当索引去取指针，
> 取到空指针后解引用 —— `Rome2.dll` 里访问冲突，进程当场死。
>
> 顺带把整张注册表 dump 出来了，得到 3 个命名空间、38 个合法编号。
> 其中默认命名空间只有 **9** 个 —— 我们过去只用了 2 个。

---

## 一、现象与第一手证据

打开 `D300固件\_probe_batch`（8 张同一底片、恒等曲线、只换底子编号）→ NX Studio 直接退出。

Windows 事件日志（`Application`）抓到两次，签名完全一致：

```
错误应用程序名称: NXStudio.exe，版本: 1.7.1.3000
错误模块名称: Rome2.dll，版本: 2.9.1.3000
异常代码: 0xc0000005           ← 访问冲突
错误偏移量: 0x000000000013d8f2   ← 两次都是同一个偏移
```

同一偏移复现两次，说明是**数据触发的确定性崩溃**，不是随机故障。

## 二、反汇编：崩在哪一行

把 `0x13D8F2` 从 RVA 映射到文件偏移（`.text` 段，va=0x1000 / raw=0x400），
用 capstone 反汇编出上下文：

```asm
0013D8A7  call 0x13d180                     ; 取 profile 对象
0013D8AC  mov  edx, ebx                     ; 参数：命名空间
0013D8AE  mov  ecx, edi                     ; 参数：底子编号
0013D8B0  call 0x13a170                     ; ← 查表，返回索引
0013D8B5  movsxd r8, eax                    ; r8 = 索引（没有检查返回值！）
0013D8B8  lea  rcx, [rip + 0x1a30b1]         ; 表基址 = 0x2E0970
0013D8BF  imul r9, r8, 0x68                 ; 索引 × 104 字节
0013D8E8  mov  rax, [r9 + rcx + 0x40]       ; 取表项 +0x40 的指针
0013D8F2  movups xmm0, [rax]                ; ← 崩在这里：rax 是垃圾/NULL
```

`0x13A170` 本身是个干净的线性搜索：

```asm
0013A1B0  cmp  edx, [rax - 0x68]        ; 每轮展开比较 4 项
0013A1B5  cmp  edx, [rax]
0013A1B9  cmp  edx, [rax + 0x68]
0013A1BE  cmp  edx, [rax + 0xd0]
0013A1C6  add  rax, 0x1a0               ; 步进 4 × 0x68
0013A1CC  add  ecx, 4
0013A1CF  cmp  rax, r8                  ; 表尾 = 0x2E18F8
0013A1D2  jl   0x13a1b0
0013A1D4  mov  eax, ecx                 ; ← 没找到：返回「条目计数」，不是 -1
0013A1D6  ret
```

**这就是 bug**：查不到时它返回循环计数（= 表长 38），调用方拿 38 × 0x68 去索引，
落在表外，读到垃圾指针，然后无条件解引用。Nikon 这里少了一个 `if (idx >= count) return;`。

对比一下命中路径（`0x13A1D7` / `0x13A1DD` / `0x13A1E3` / `0x13A1E5`）都是
`add ecx, 1..3; mov eax, ecx; ret`，正常。所以只有「找不到」这一支会炸。

## 三、表里有什么：38 项 / 3 个命名空间

表的首地址 `0x2E0970`（`lea rax,[rip+0x1a6834]` 的下一条指令 `0x13A1A4` 加上 0x1A6834），
表尾 `0x2E18F8`，每项 0x68 字节。项的布局：

| 偏移 | 内容 |
|---|---|
| +0x00 | `dword` 键 = `(命名空间 << 16) \| 底子编号` |
| +0x40 | 指向 Picture Control 定义结构的指针（首个字段就是名字） |

键的构造在 `0x13A190`~`0x13A1A4`：

```asm
cmp edx, 8   ; 命名空间 ≥ 8 → 8
cmp edx, 2   ; ≥ 2 → 2，否则 → 1
shl edx, 0x10
add edx, ecx ; key = (kind << 16) + number
```

把 38 项全部 dump 出来（`name` 直接从 `+0x40` 指针读）：

| # | kind | num | 名字 | | # | kind | num | 名字 |
|---|---|---|---|---|---|---|---|---|
| 0 | 1 | 0001 | STANDARD | | 19 | 8 | 00C3 | VIVID |
| 1 | 1 | 03C2 | NEUTRAL | | 20 | 8 | 064D | MONOCHROME |
| 2 | 1 | 00C3 | VIVID | | 21 | 8 | 0486 | PORTRAIT |
| 3 | 1 | 064D | MONOCHROME | | 22 | 8 | 04C7 | LANDSCAPE |
| 4 | 1 | 0486 | PORTRAIT | | 23 | 8 | 028E | FLAT |
| 5 | 1 | 04C7 | LANDSCAPE | | 24 | 8 | 02CF | AUTO |
| 6 | 1 | 0014 | D2XMODEI | | 25 | 8 | 0801 | DREAM |
| 7 | 1 | 03D5 | D2XMODEII | | 26 | 8 | 0802 | MORNING |
| 8 | 1 | 00D6 | D2XMODEIII | | 27 | 8 | 0803 | POP |
| 9 | 2 | 0001 | STANDARD | | 28 | 8 | 0804 | SUNDAY |
| 10 | 2 | 03C2 | NEUTRAL | | 29 | 8 | 0805 | SOMBER |
| 11 | 2 | 00C3 | VIVID | | 30 | 8 | 0806 | DRAMA |
| 12 | 2 | 064D | MONOCHROME | | 31 | 8 | 0807 | SILENCE |
| 13 | 2 | 0486 | PORTRAIT | | 32 | 8 | 0808 | BLEACH |
| 14 | 2 | 04C7 | LANDSCAPE | | 33 | 8 | 0809 | MELANCHOLIC |
| 15 | 2 | 028E | FLAT | | 34 | 8 | 080A | PURE |
| 16 | 2 | 02CF | AUTO | | 35 | 8 | 080B | DENIM |
| 17 | 8 | 0001 | STANDARD | | 36 | 8 | 080C | TOY |
| 18 | 8 | 03C2 | NEUTRAL | | 37 | 8 | 080D | SEPIA |

三组的关系很清楚：

- **kind=1**：9 项，D 时代的基础底子（含 D2X 模式 I/II/III）
- **kind=2**：9 项里的 6 项 + FLAT/AUTO，即 Picture Control 2.0 的相机内建组
- **kind=8**：8 项基础 + **创意底子 0x0801–0x080D（13 支）**

## 四、根因

`_probe_batch` 的 8 张里，**只有 B8_BINARY 是必然崩溃点**：

```
B8 的底子编号 = 0x0813
注册表 kind=8 组最大只到 0x080D
→ 无论命名空间取 1 / 2 / 8，0x0813 都查不到
→ 返回 38 → 越界 → 崩
```

其余 7 张的编号（0001/03C2/00C3/064D/0801/0808/080B）都在表里，
**但 `0x0801` / `0x0808` / `0x080B` 只存在于 kind=8 组**。所以：

- B1–B7 能打开 ⇒ 说明我们写 NCP 时走的命名空间本来就是 8，08xx 是有效的
- B1–B7 仍然崩 ⇒ 命名空间是 1，08xx 落在 kind=1 组之外，创意底子走不通

`_probe_batch_fix` 就是为这个判别准备的（7 张，去掉 B8）。

## 五、两个结论

### 1. 官方 20 支创意滤镜，有一半在 NCP 里根本无处安放

`kind=8` 的创意底子只登记到 **0x080D = SEPIA**。而官方 NP3 里
`0x080E–0x0814`（含 BINARY=0x0813）一个都没有。这不是我们写错，
是 NX Studio 1.7.1 的 NCP 通道里就不存在这些编号 —— 官方那 6 支
（`0x080E` 之后）走的不是这条路。

顺带解释了 `docs/15-picture-control-base.md` 里那个没解释的疑点：
26 支真渲染里「创意底·彩色」16 支平均差 8.21 级，比基础底那 6 支高一倍多。
如果我们的 NCP 只能落在 kind=1，那 08xx 从来就没生效过，那 16 支一直是
「STANDARD 底子 + 一条曲线」在硬扛官方的「创意底子 + 专属调色」。

### 2. 默认命名空间下还有 5 个底子从没用过

我们过去只用过 `0x0001`（彩色）和 `0x064D`（单色）。表里 kind=1 还有：

| 编号 | 名字 | 状态 |
|---|---|---|
| 0x0486 | PORTRAIT | 从没测过 |
| 0x04C7 | LANDSCAPE | 从没测过 |
| 0x0014 | D2XMODEI | 从没测过 |
| 0x03D5 | D2XMODEII | 从没测过 |
| 0x00D6 | D2XMODEIII | 从没测过 |

这 5 个都在 kind=1 里，写进 NCP 一定查得到，**不会崩**。
D2X 模式 I/II/III 是 D3/D300 时代官方发布的底子，D300 很可能内建。
这是「底子」这一维上唯一还没扫过的格子。

## 六、复现

```bash
# 1) 崩溃事实（Windows 事件日志）
powershell -c "Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddHours(-3)} | ? { \$_.Message -match 'NXStudio' } | select -First 3"

# 2) 反汇编崩溃点
python d300/tools/dump_rome2_table.py --asm 0x13d8f2

# 3) dump 整张注册表
python d300/tools/dump_rome2_table.py

# 4) 生成不会崩的底子探针
python d300/tools/pack_profile_probe.py     # → _probe_profile（7 张，kind=1 全合法）
python d300/tools/pack_sidecar_batch.py \
    --ncp-dir ../_probe_batch_fix_src --out ../_probe_batch_fix   # → 7 张，判别 08xx
```

## 七、下一步

> 2026-11-02 11:35 更新：第 1 条已有答案（`_probe_batch_fix` 仍崩），
> 判别转到 `_probe_kind8`，见 [21-namespace-byte.md](21-namespace-byte.md)。

1. ~~**先开 `_probe_batch_fix`**（7 张）。~~ 已开：仍崩、同偏移 ⇒ 命名空间不是 8。
   现在的判别包是 `python d300/tools/pack_kind_probe.py` → `_probe_kind8`。
2. **再开 `_probe_profile`**（7 张）。P1–P5 里只要有两张不一样，
   说明底子这一层还有的挑，可以把 26 支重跑一遍最优底子组合。
3. `_probe_batch` 那个目录别点了，里面留了 `别打开-会闪退.txt` 说明原因。
4. 如果要试 kind=8，**不要**动 `pack_baseid_probe.py` 的默认输出 ——
   先把 kind 的来源（`profile + 0x1b0`）从 dll 里确认清楚，
   现在只知道它是结构体字段，还没追到由文件哪个字节填充。
