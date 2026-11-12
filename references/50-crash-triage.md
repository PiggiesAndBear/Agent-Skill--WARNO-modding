# 游戏内崩溃（CTD）：从 dump 到「能行动的结论」

编译通过、进游戏也没事，但某个动作一做就闪退。这时 NDF 层面已经没有信息了，
唯一的一手证据是引擎自己写的崩溃转储。

## 1. 先找对文件：WARNO 用 CrashRpt，不是 WER

```
%LOCALAPPDATA%\CrashRpt\UnsentCrashReports\WARGAME_<appid>\<guid>\
    crashdump.dmp     ← 精简转储，通常只有几百 KB
    crashrpt.xml      ← 元数据，最省时间的就是这个
    dxdiag.log
```

`WARGAME_201602` 这类数字是 exe 的应用号，换版本会变（本机还有 `WARGAME_193438`、
`WARGAME_197351` 两个更老的）。**别去 `Windows/WER` 找**——Unreal/自绘引擎那套
WER 目录里往往什么都没有，`Application` 事件日志里也不会有 `Application Error`。

### `crashrpt.xml` 里只要看四个字段

| 字段 | 用途 |
|---|---|
| `FriendlyExceptionName` | `ACCESS VIOLATION (Reading 0x20)` —— 已经告诉你读还是写、读多大 |
| `ExceptionAddress` + `ExceptionModuleBase` | 两者相减 = **RVA**，不需要解析 dump 就能定位 |
| `IsInGame` / `Map` / `ElapsedTime` | 分清是**启动期**还是**游戏内**：`Map` 全零 + 存活 <10 s = 加载期 |
| `CustomProps` | 有 `ActivatedMods`、`Map`、`NbPlayer/NbIA`、`SHA1`，便于确认「哪次构建、哪张图」 |

`ElapsedTime` 这一条最容易被忽略：加载期崩溃和游戏内崩溃是**两套完全不同的排查路径**，
先按这个字段分流，再去解 dump。

## 2. 再算 RVA，别急着上调试器

本机通常没有 cdb/WinDbg，也没有 PDB（Eugen 不发布符号）。但 RVA 足以回答「崩在哪条指令」：

```
RVA = ExceptionAddress - ExceptionModuleBase
```

然后拿 `scripts/analyze_crashdump.py` 解析 dump：

```bash
python scripts/analyze_crashdump.py <crashdump.dmp> --exe <WARNO根>/WARNO.exe --top 25
```

它输出四段：模块基址与 ASLR 偏移、异常码与访问方式、`.pdata` 命中的函数区间、
崩溃线程寄存器与栈上的代码地址链（每个地址都折算成「函数起点 + 偏移」）。

**两个必须踩对的细节**（第一版两个都错了，白读一轮）：

1. **寄存器要取 ExceptionStream 里的 ThreadContext，不是 ThreadList 里那份。**
   ThreadList 的 context 是「抓 dump 那一刻」的，已经落在异常处理函数里，
   Rip 会指向 ntdll/KERNELBASE，看着完全不像崩溃点。
2. **数据目录索引：`Exception` 是第 3 项（0=Export,1=Import,2=Resource,3=Exception）。**
   写成 4 会解析到 Certificate（通常为空），`.pdata` 全乱，函数区间会出现
   `0x1c48049..0x67831dde` 这种一眼假的跨度。

## 3. 没有符号，怎么手工解码崩溃指令

`.pdata` 给出函数边界后，把崩溃点前后 0x30 字节 hexdump 出来，逐条按 x64 编码解：

| 字节模式 | 含义 | 判读价值 |
|---|---|---|
| `48 8b 04 c7` | `mov rax, [rdi+rax*8]` | 从数组里取元素 |
| `48 83 e0 fe` | `and rax, -2` | **抹低位 tag** → 元素是 tag 化指针 |
| `83 78 20 00` | `cmp dword [rax+0x20], 0` | 直接读成员 → 若 rax=0 则报「Reading 0x20」 |
| `85 c9` + `cmovs` | `test ecx,ecx` / `cmovs rdi,rbx` | MSVC 容器「长度编码 + 内联缓冲」惯用序列 |
| `8b 4d cc` `c1 e8 08` `25 ff ff 7f 00` | 取 size：`shr 8; and 0x7fffff` | 同上，确认这是容器而不是别的结构 |

**关键推论**：`读 0x20` 几乎总等于「基址寄存器为 0」。再往上一两条就能看出零是怎么来的
（本例：取了容器里的空元素，没有判空就解引用）。

## 4. 能读到哪一层，读不到哪一层（务必先认清）

`analyze_crashdump.py` 额外做一件事：扫函数体的 `48 8D 05` 型 RIP 相对 LEA，
把目标当字符串打印出来——引擎没有导出符号，但**字段名/模块名/断言文案都以字面量留在 exe 里**，
这等于给函数贴标签（例：某函数认识 `TSelectionModuleDescriptor` / `IsSelectable`，
那它就是该模块的 NDF 属性读取器）。

但要知道它的**上限**：

| 想知道的 | 能不能 |
|---|---|
| 崩在哪条指令、读写了哪个地址 | ✅ |
| 调用了哪些函数（RVA 级） | ✅ 栈扫描 + `E8` 调用点 |
| 函数属于哪个子系统 | ⚠️ 只有它引用字符串、或出现在 vtable 里才行 |
| 空指针是哪次分配漏掉的 | ❌ 需要完整 dump + 符号 |

**两种情况一定读不出来**：
- 函数体内**零字符串引用、且没有被任何 vtable 引用**（纯静态辅助函数）→ 无法命名；
- 精简转储里没有堆内存 → 连 `Descriptor_...` 这类名字都搜不到（本例 689 KB，
  搜 `TEST_Controllable` / 词条 token 全部 0 命中）。**不要拿「搜不到」当「没关系」的证据**。

## 5. 拿不到语义时的正确下一步：做对照组，不要继续反汇编

dump 只能把范围缩到「某类容器查找」，缩不到「哪个描述符」。此时最省时间的是**二分实验**，
原则是「一次只改一个变量，且对照组必须能独立解释」：

1. **先切责任方**：把「新实体」换回原版实体，其余一字不改（弹药字段、指令、武器全留）——
   崩 → 责任在弹药/指令侧；不崩 → 责任在新实体。
2. **再切模块**：在实体上成组增删（选择/UI/状态机/指令），不要一次一个模块。
3. 每次实验都记 **RVA**：同一 RVA 重复 = 确定性崩溃，可放心二分；RVA 乱跳 = 先怀疑随机性/并发。

本项目实例：`toggle_ammo_target.py --control / --restore` 就是这个「切责任方」开关，
只改 `MissileDescriptor` 的指向，弹药参数一个不动。

## 5.5 先分清「弹窗 Fatal」与「CTD」

不是所有实机报错都要解 dump。WARNO 有两类，处置完全不同：

| | 弹窗 Fatal | CTD（CrashRpt） |
|---|---|---|
| 形态 | `Fatal error` 小窗 + 一句英文 | 进程消失，`%LOCALAPPDATA%\…\CrashRpt` 出 dump |
| 时机 | 加载期 / 特定游戏事件（首次开火、命中瞬间、切换姿态） | 任意 |
| 信息量 | **报错原文就是答案**，直接字符串搜 NDF | 只有 RVA，要 §2~§4 那套 |
| 处置 | 按原文改数据，别碰 dump | 按 §5 做对照组二分 |

近年实测的弹窗 Fatal 都长这个形状（都是**硬校验**，编译期零报错）：

```text
Invalid property in object '<anonymous> (TMissileCarriageSubDepictionGenerator)':
    Property 'ReferenceMesh' must be defined            ← 缺字段（21-depiction.md §4.3）
Can't load 'Glad:/NDF/GFX/Depiction.ndfbin':
    * Missing subdepiction anchor bone 'driver'         ← FBX 缺骨（20-unit-authoring.md §3.4）
happening 'MissileATGMGen4' requested and missing in
    Mimetic World Descriptor                            ← 枚举值不在表里（22-ammo.md §3.1）
@file:…AmmunitionMissiles.ndf@(15697:41): Invalid character   ← 语法（40-engineering.md §5.4）
```

**判据**：弹窗里出现 `Missing` / `must be defined` / `requested and missing` 这三个词，
100% 是「你写了引擎找不到的东西」，属于数据侧硬契约，不要去反汇编。

⚠ **注意报错里被点名的文件常常不是肇事文件**。`driver` 那条报的是 17 个外观算子和
`Depiction.ndfbin`，真因是「多挂了一条乘员子描绘」；`requested and missing` 报的是
mimetic 表，真因是弹药里一个枚举字符串。**顺着「谁引用了谁」往回找，不要就地改被点名的对象。**

## 6. 一条纪律

**崩溃转储的时间戳是分流的唯一依据。** 同一个 mod 目录下可能同时挂着「加载期崩溃」
（启动 5 秒、Map 全零）和「游戏内崩溃」（活了一分钟、Map 已加载、有玩家数）两种报告，
它们几乎不可能是同一个原因。先看 `ElapsedTime` / `Map` / `IsInGame`，再决定要不要解 dump。
