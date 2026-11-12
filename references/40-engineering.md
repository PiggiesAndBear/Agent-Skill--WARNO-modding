# 工程规范：改动落地 + 编译 + 验收 + 回滚

> 本文件由两份旧文档合并：`patch-workflow.md`（工程规范）与 `fatal-catalog.md`（Fatal 对照）。
> 两者重叠部分（编译守卫 / 行尾编码 / 回滚）以本文件前部为准，后部保留 Fatal 报错原文索引。
> 单一来源原则：主 SKILL 不复制本文件内容。

---

## A. 改动落地工程规范（原 patch-workflow.md）
# 改动落地工程规范：换行、幂等、守卫、编译、验收、回滚

> 适用场景：任何要往 `.ndf` 写改动的活（造单位、加武器、调参数、批量换装）。
> 来源：`Mods/ShowCase-FPV Strike` 30+ 个补丁脚本的实践。**这一节讲的是「怎么写」，不是「写什么」。**
> 核心目标：**任何一次改动都能被证明只动了想动的那几行，且能一键退回去。**

---

## 1. 五条铁律

| # | 铁律 | 违反后的样子 |
|---|---|---|
| 1 | **只改 `GameData/Generated/**/*.ndf`，永不手改 `Gen/NDF/*.ndfbin`** | 下次编译静默覆盖（除非你就是要用 `.ndfbin` 直编，见 10-army-general.md §6） |
| 2 | **一律末尾追加**；少数必须插块的（`DivisionRules`）走带守卫的插入 | 改动点散落，diff 不可读，回滚困难 |
| 3 | **新对象名全局唯一、GUID 全库 0 命中** | 编译期冲突，或运行期串对象 |
| 4 | **脚本必须幂等 + 可 `--dry-run`** | 重跑一次就重复插入，第二次把文件写坏 |
| 5 | **改前必备份，命名带时间戳与用途** | 出事只能整目录回滚，连累当天其他改动 |

备份约定（本库通用）：

```
.workbuddy/backup/<文件名>.<YYYYmmdd_HHMMSS>.before_<标签>
# 例：DivisionRules.ndf.20261027_143145.before_jammer
```
标签写**这次改动的语义**，不写序号——半年后靠文件名就能判断该回滚哪一个。

---

## 2. 换行风格：一个能让 71 万行全变红的坑

**Eugen 的 NDF 混用 CRLF 与 LF，同一目录下都可能不一致。**

| 文件 | 实测 |
|---|---|
| `Gfx/UniteDescriptor.ndf`（71 万行）、`Gfx/Ammunition.ndf`、`Gfx/OrderAvailability_Tactic.ndf`、`Decks/*.ndf` | **纯 CRLF** |
| `Gfx/WeaponDescriptor.ndf`、`Gfx/DepictionAerialUnits.ndf`、`Effects/EffetsSurUnite.ndf` | **纯 LF** |

Python 的 `Path.read_text()` / `write_text()` 默认做换行归一化。在 71 万行的 CRLF 文件上写一次，
**整个文件全部变更**，`git diff` / `diff -u` 直接爆（曾产出 55 MB 假 diff），行数/括号/md5 全对不上，
看起来像把文件写坏了。

```python
def detect_eol(path):
    with open(path, "rb") as f:
        head = f.read(200000)
    return "\r\n" if head.count(b"\r\n") > head.count(b"\n") / 2 else "\n"

def rd(path):                      # universal newlines：读进来全是 \n，正则好写
    with open(path, "r", encoding="utf-8", newline=None) as f:
        return f.read(), detect_eol(path)

def wr(path, text, eol):            # 写回按原风格还原
    if eol != "\n":
        text = text.replace("\n", eol)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
```

⚠ `newline=""` 是必须的：否则 `\r` 会被再翻译一次，变成 `\r\r\n`。

**验收（二进制口径，别用 `wc -l` 判断）**：

```python
raw = open(p, "rb").read()
crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
pure = "纯CRLF" if crlf == lf else ("纯LF" if crlf == 0 else "混行！")
```

---

## 3. 锚点截断：本库最阴的一次事故（同类已发生 2 次）

**症状**：往 `DivisionRules.ndf` 插一条新规则，锚点取到
`... NumberOfUnitInPack = 55` 就停了，于是插入点落在**上一条规则的中间**：

```
    NumberOfUnitInPack = 55          ← 锚点止于此
TDeckUniteRule                       ← 新规则从这开始
( ... )
    XPMultiplier = ...               ← 本该属于上一条，被切到了新规则尾部
    ...
```

**为什么难发现**：括号总数**仍然平衡**，`-generatemod` **照常通过**，只是前一条规则少了一个字段、
新规则多了一个字段——**只能肉眼看出来**。

**三条守卫（缺一不可）**：

```python
# ① 锚点必须包含「规则收尾」的全部特征，不只是最后一个感兴趣字段
ANCHOR = ("NumberOfUnitInPack          = 55\n"
          "        NumberOfUnitInPackXPMultiplier = [1.0, 1.0, 1.0, 0.0]\n"
          "        XPMultiplier                = 1.0\n"
          "    ),\n")
assert text.count(ANCHOR) == 1, "锚点不唯一或已被改动"

# ② 括号净值必须与改动前一致（插入完整对象才为 0）
assert new.count("(") - new.count(")") == old.count("(") - old.count(")")

# ③ 对象数与「对象收尾行」数必须相等（结构完整性的独立证明）
assert len(re.findall(r"(?m)^TDeckUniteRule\s*$", new)) == len(re.findall(r"(?m)^    \),$", new))
```

守卫 ③ 是「换一个角度重数一遍」：括号平衡只证明**总数**对，③ 证明**每个对象都闭合了**。

---

## 3.5 全局 `str.replace` 会打穿原版同名 token

锚点截断的反面：**token 在文件里不唯一时，一把替换会把原版单位一起改掉**。

实测（Ka-58 换机炮）：`DepictionAerialUnits.ndf` 里 `Weapon_AutoCanon_AP_30mm_24A2` 出现 **3 次**
——`Ka_50_SOV`、`Ka_50_AA_SOV`、本项目各一次。`text.replace(old, new)` 全改，
结果**两个原版 Ka-50 的机炮外观全变成了 23mm**。

最阴的地方：编译通过、加载正常、开火正常、本机也正常。**只有拿原版 Ka-50 进场对比才能发现**。

**纪律三条**：

```python
# ① 先数，和后数量都必须是预期值
assert t.count(TOKEN) == 3, "token 出现 %d 次，与预期不符" % t.count(TOKEN)

# ② 只改自己那一块：按行号定位后用切片替换，不做全文 replace
i = lines.index(owner_line);  j = i + span
lines[i:j] = [ln.replace(TOKEN, NEW) if TOKEN in ln else ln for ln in lines[i:j]]

# ③ 改完做「按块 md5」，确认只有自己的块变了（§6 第 5 件）
```

> 同类坑还有一个变体：`str.replace(..., 1)` 只改第一处，但**第一处未必是你的**。
> 本项目把 `PylonSet_DefaultNoPOD` 改成 `PylonSet_DoesNotExistZZZ` 做负向验证时，
> 命中的是文件里第 157 行原有的 `PylonSet_DefaultNoPODx2`——负向验证本身失败了，报错行号还误导了排查。

---

## 4. 补丁脚本骨架

一个改动 = 一个脚本 = N 个 `step_xx()`。每个 step 独立：自己 `rd` / 自己判断幂等 / 自己守卫 / 自己 `wr`。

```python
DRY = "--dry-run" in sys.argv or "--dry" in sys.argv

def step_unit():
    print("\n[1/8] UniteDescriptor.ndf -> 新单位块")
    t, eol = rd(P_UNIT)
    if re.search(r"(?m)^export " + NEW + r" is TEntityDescriptor", t):
        ok("已存在，跳过（幂等）"); CACHE["text"] = t; return
    seg = block_of(t, TEMPLATE)
    new = transform(seg)
    for s in MUST:      assert s in new, "缺少 %r" % s          # 必须有
    for b in MUST_NOT:  assert b not in new, "残留 %r" % b      # 必须没有
    assert new.count("\n") == seg.count("\n"), "块行数变了"
    if not DRY:
        print("    备份:", backup(P_UNIT, "fpv_satchel_us"))
        wr(P_UNIT, t.replace(seg, new), eol)
```

四条实现要点（都踩过）：

1. **`--dry-run` 不能写盘，但下游 step 要能看到上游结果** → 用进程内 `CACHE` 传递文本，
   别让第 8 步去读还没落盘的文件（否则 dry-run 的结果和真跑不一致）。
2. **块定位一律用「到下一个 `\nexport ` 为止」**，不要用固定行数或固定缩进：
   `nxt = text.find("\nexport ", m.end())`。
3. **`must-not` 清单比 `must` 更有用**：克隆类改动只查「该有的有了」，很容易漏掉「旧的还在」
   （`_SOV` / `PACT` / `Pero_UAV` 残留）。
4. **正则替换前先数出现次数**：`assert b.count("TraitsToken") == 1`。
   曾用 `TraitsToken(\s*=\s*\[)\s*'STAT','HE','IND',` 这种把值放进捕获组的写法，
   结果整段被替换成 `        = [ 'STAT', 'HE', ]`——**标签名被吃掉**。
   写法：**捕获组只包标签名，或用 `\b` 锚定后做精确子串替换**，并在替换后断言字段名仍存在。

---

## 5. 编译：异常自动捕获（四条通道，只有一条有用）

### 5.1 通道盘点

| 通道 | 覆盖什么 | 可靠性 |
|---|---|---|
| `GenerateMod.py` 退出码 | 成功/失败 | ❌ **失败也返回 0**（内层 python 报错，`cmd.exe` 仍 0） |
| `WARNO.exe` stdout | 进度行 `Generating mod...` | ⚠️ python 默认**块缓冲**，进程被 kill 时**一个字节都没落盘**（实测日志 0 字节）。加 `-u` 才看得到进度 |
| 磁盘日志 | `WME` 构建时的 `Process output:`（`<WARNO根>/wme.log`） | ⚠️ 只有走 WME 才有；事后可查 return code，但拿不到语法错原文 |
| **`#32770` 模态框** | **语法/解析/启动期 Fatal error 的原文** | ✅ 唯一 |

**关键推论**：语法错时 stdout 是空的，**报错只存在于弹窗里**。
读不到弹窗 = 拿不到任何线索，只能看着进程 CPU 归零干等（实测空等 25 分钟）。

### 5.2 捕获机制（Win32，已实测）

```
EnumWindows  →  筛 class == "#32770"
             →  EnumChildWindows 逐个子控件 GetWindowTextW
```

实测结论（用 `MessageBoxTimeoutW` 造一个与真实报错同形的弹窗验证）：

- **多行正文是单个 static 控件**，一次读取即完整，`\n` 保留；
- **第一个子控件是按钮文字**（`确定` / `OK`），会混进正文 → 必须按按钮白名单滤掉，
  否则「取第一段文字」拿到的是「确定」；
- 正文取**最长的那一段**（按钮名都很短）。

判定是否报错：标题含 `parsing error` / `Fatal error`，**或**正文含
`error|NDF|Invalid|Failed|cannot|must be|too long` 之一。
只按键名标题匹配太窄 —— 启动期/加载期弹窗标题并不统一。

### 5.3 把原文加工成「能行动的信息」

`scripts/genmod_guard.py` 在拦截后做三段加工，落盘
`.workbuddy/tmp/genmod_last_error.txt`：

```
[2026-10-28 19:39:04] 编译被弹窗拦下
dialog : NDF parsing error. Retry?
object : $/GFX/Unit/Descriptor_Unit_FPV_Satchel_US
type   : TEntityDescriptor
file   : GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf:713140
message: Value is too long for a TLocalisationToken: 'FPVSATCHELUS'
hint   : NameToken 超长：上限 10 字符，且要同步 Localisation/*/UNITS.csv 的键

--- 弹窗原文 ---
...
```

- `file`：拿 `Object <$/GFX/.../符号 : 类型>` 里的符号，在**热区文件**（UniteDescriptor、
  WeaponDescriptor、Ammunition、DivisionRules…）里定位到 `文件:行号`。先查热区，
  不要全库扫 4500 个 `.ndf`。
- `hint`：内置「报错原文 → 已知成因」表（见 5.4）。
- **落盘的意义**：弹窗原文只存在于一次性 stdout 里。不落盘，上下文一压缩就永久丢失，
  下次只能凭记忆复述报错——而本库所有硬约束都是靠原文定位的。

**取值顺序有个坑（实测踩过）**：弹窗**首行往往就是标题本身**
（`NDF parsing error. Retry?`）。若按「取第一段够长的文字」当报错句，会把它当消息，
于是永远匹配不到已知成因。正确顺序：① 逐行按已知成因正则匹配；② 都不中再退化为最长行。

### 5.4 报错原文 → 处置对照表

| 弹窗原文（去变量） | 成因 | 处置 |
|---|---|---|
| `Value is too long for a TLocalisationToken: 'X'` | `NameToken` 超 10 字符 | 改短到 ≤10，并同步 `Localisation/*/UNITS.csv` 的键 |
| `Property 'X' must be equal to 'Y'` | 该属性被别的字段**强制**决定 | 不要硬设，去找决定它的那个字段（如弹道 → `PitchForParabolic`） |
| `Weapon with parabolic trajectory cannot be embedded on planes or helicos` | 抛物线弹道不能挂飞机/直升机 | **不是禁间瞄**，禁的是弹道类型 `Artillerie`；换 `Obus` |
| `tag list incompatible` / `TagSet` | 承运方与被运方标签无交集 | 修 `TagSet`，否则游戏启动即 Fatal error |
| `No unit name dictionnary found for nationality ''`（原文双 n） | 实体缺 `MotherCountry`（空串），而它已具备「可选单位」身份 | 内联 `TTypeUnitModuleDescriptor(Coalition=..., MotherCountry='SOV')`，见 5.6 |
| `Invalid property` | 字段名错、或该模块不接受此字段 | 查该模块的真实字段表（多为加载期报错） |
| `@file:…@(行:列): Invalid character` + `syntax error, unexpected $end` | **新建对象的 `DescriptorId` 写成裸 `{uuid}`**，不是合法 NDF token（LOSAT 2026-11-11 实测） | 必须写 `GUID:{uuid}`。改完**回滚 `.bak_*` 全部备份再重跑幂等补丁**，不要只在成品文件里补前缀 |
| `Invalid property in object '<anonymous> (TMissileCarriageSubDepictionGenerator)': Property 'ReferenceMesh' must be defined` | 战场版挂架子生成器缺 `ReferenceMesh`（加载期硬校验，编译期不查） | 补 `Pylons = ~/DepictionPylonSet_ATGM` + `ReferenceMesh = $/GFX/DepictionResources/Modele_<单位>`，见 `21-depiction.md §4.3` |

### 5.5 三条安全纪律（每条都是事故换来的）

1. **绝不 `taskkill /F /IM WARNO.exe`。** 玩家可能正开着游戏，一条命令把游戏连存档一起杀。
   正确做法：`GetWindowThreadProcessId(hwnd)` 取**弹窗所属 PID**，只杀那一个；
   超时分支也只清理「本次新起」的 PID（开跑前先记一遍进程快照做差集）。
   实测两进程并存时精确定位到弹窗进程，未波及另一个。
2. **开跑前若已挂着报错弹窗 → 直接中止。** 那多半是上一次失败留下的，
   分不清是谁的错，会得出错误归因。同时把已有的对话框加入忽略名单。
3. **不要对着真工程试跑守卫。** 用 1 秒超时「试一下参数」也会真的起一次编译，
   把 `Gen/` 写到一半就杀。验证走两条零风险分支：假路径（应立刻退出 5）、
   假弹窗（`MessageBoxTimeoutW`，自闭合）。

退出码可编程判别：`0` 成功 / `3` 被弹窗拦下 / `4` 超时（无弹窗无完成，通常是逻辑或资源问题，
**不是语法**）/ `5` 环境问题 / 其他 = 真实返回码。

```bash
python scripts/genmod_guard.py --mod "D:/Steam/.../Mods/<Mod>" --name "<Mod>" 1800

# 报错已经弹出来了（走 WME / 手动双击 GenerateMod.bat），守卫没在跑：
# 只读捞一把 —— 不发起编译、不杀任何进程
python scripts/genmod_guard.py --probe
```

- 超时给 **300~1800 秒**（单次构建实测 45~65 秒；资产烘焙更久）。
- **超时后不要 `close()` 管道**，那会杀掉子进程并丢掉日志。
- 失败时**照抄弹窗原文**再判断，别凭经验猜。

### 5.6 第五条通道：编译成功 ≠ 游戏能加载【实测】

`Mod Generation Success` + `rc=0` 只证明 **NDF 能解析、引用能解析、对象能构造**。
有一类校验**只在游戏启动时跑**，编译期完全不报：

> `Fatal error: No unit name dictionnary found for nationality ''`

实测时序：11:56 编译成功、产物落地 → 12:15 启动游戏 → 12:16 弹 Fatal。
`GenerateMod` 全程无异常，`Gen/` 产物完好。

**判据**：这类错误发生在 `EugGame.lock` 生成之后、进主菜单之前。
排查顺序是「先看 `EugGame.lock` / `PerfLog.bin` 时间戳，确认是启动期还是编译期」，
不要回头怀疑 NDF 语法。

**已知的启动期校验**（描述符数据库完整性，编译期不查）：

| 校验 | 触发条件 | 报文 |
|---|---|---|
| 国籍 → 名词典 | 实体带 `Selection` / `UnitUI`，但 `MotherCountry` 为空 | `No unit name dictionnary found for nationality '%1'` |
| 词典空 | 同上，词典存在但 0 条目 | `Empty unit name dictionnary for nationality '%1'` |
| 词典重复注册 | 两个 mod 抢同名 DicoToken | `Dico %1 already registered for nationality '%2'` |

**纪律**：凡新增「可选单位 / 可操控实体」，**编译通过只能算走了一半**，
必须让用户启动一次游戏（到主菜单即可）才算验证通过。别在编译通过后就报「完成」。

---

### 5.7 编译范围：哪些 ndf 会被编进 ndfbin（推翻一条旧结论）

旧结论：「`GameData/Gameplay/**` 运行时直读、不进 ndfbin」——**错的**，而且害了两次。

实测：把 `GameData/Gameplay/Gfx/Units/DepictionCoatingPantry.ndf`（纯数据，看起来像"配置表"）里的角度
从 150 改成 120，**进游戏完全没变化、也不报错**；跑一次 GenerateMod 后
`Gen/NDF/GFX/Depiction.ndfbin` 从 602092 → 602044，再进游戏才生效。

| 判据 | 是否可靠 |
|---|---|
| 源文件 mtime | ✗ 不算生效 |
| `touch` 触发重编 | ✗ **不认**（增量判定有时同秒跳过） |
| `ndfbin` 体积变化 | ✗ 改注释也变、改引用不变 |
| **`ndfbin` 的 mtime 变新** | ✓ 唯一可靠 |

**推论**：凡「改了没生效、又没有报错」的问题，第一嫌疑永远是**没编译**，不是参数写错。
本项目为此白改了两次符号（用户看到的始终是旧姿态），一度以为是引擎方向判断错了。

**纪律**：改完任何 `GameData/**` 下的 ndf，**先跑 GenerateMod 再让人进游戏**；
只有确认 `Depiction.ndfbin` 的 mtime 变新，才轮到讨论参数。

**UI 还有独立的一簇**：`Gen/NDF/UI/Components.ndfbin` 承载 `GameData/Generated/UserInterface/` 的资源
（纹理 bank 等）。2026-11-05 实测：新增的 `Texture_Button_Unit_T90A_SOV` 在该文件里命中 1 次、
单位侧引用在 `Gen/NDF/GFX/Unit.ndfbin` 命中 1 次。
`find Gen -name "*.ndfbin"` 的结果里 `UI/` 排在 `GFX/` 之后，**容易只看 GFX 就下结论**；
判「UI 改了没生效」必须单独看这个文件的 mtime。

---

## 6. 验收五件套（每改一次都跑，10 秒内完成）

| # | 检查 | 判据 | 抓什么 |
|---|---|---|---|
| 1 | 行数增量 | `new_lines - old_lines == 预期`（如 +3 边 / +255 块 +11 注释） | 插错位置、多插/少插 |
| 2 | 换行形态 | 纯 CRLF 文件仍 `crlf == lf`；纯 LF 仍 `crlf == 0` | §2 的整文件重写 |
| 3 | 括号净值 | 与备份文件**相同** | 少写一个 `)`（编译能过的情况也有） |
| 4 | `)export ` 粘连 | 计数 **0** | 插入块尾部缺换行 → 与前一个 `)` 或后一个 `export` 粘在一行 |
| 5 | 按块 md5 | 2902 块里只有预期那几块不同 | **误伤别的单位**（最有效的一条） |

按块 md5：

```python
parts = re.split(r'(?m)^(export \w+ is )', t)     # [前言, 'export X is ', body, ...]
# 对 (name, body) 求 md5，与备份逐块比；输出「只有 N 块不同 + 分别是哪些」
```
在 71 万行文件上这比 `diff -u` 快得多，而且能一句话回答「有没有误伤别的单位」。

再补两条：

- **产物时间戳**：`Gen/NDF/GFX/*.ndfbin` 里**该变的变了、不该变的没动**（例：只改单位 → 只有 `Unit.ndfbin` 重建）。
- **源→产物先后**：源文件 mtime 必须**早于**对应 `.ndfbin`，否则说明用的是上一版产物。

---

## 7. 回滚

三档，按代价从低到高：

| 档 | 做法 | 何时用 |
|---|---|---|
| **单维度** | 只把某个字段改回原值（一行） | 参数不合适（`HasDeploymentTime`、`AltitudeMinGRU`） |
| **单文件** | 用 `.workbuddy/backup/*.before_<标签>` 覆盖该文件 | 本次改动整体不对 |
| **整目录** | 只在「当天多次改动交织」时用 | 最后手段；会连带退掉同日其他改动 |

⚠ 整文件回滚的**前提是备份本身就包含当天更早的改动**。回滚后必须验证残留：

```bash
grep -c "Satchel_US" GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf   # 应为 0
```

⚠ **`.ndf.bak` 不是原版基线**——它是工具自动备份，往往**已经包含上一轮编辑**。
判断「原版长什么样」只认 `Mods/ModData/base.zip`（见 00-recon.md §6）。

---

## 8. 交付前自检（照抄这张表）

- [ ] 脚本幂等：**再跑一遍全部走「跳过」**，无一行写入
- [ ] `--dry-run` 输出与真跑一致（含下游 step 的读取结果）
- [ ] 备份齐全，标签能自解释
- [ ] 五件套全过（行数 / 换行 / 括号 / 粘连 / 块 md5）
- [ ] 编译 `rc=0` + `Mod Generation Success`，产物只重建该重建的
- [ ] 编译失败时：先读 `.workbuddy/tmp/genmod_last_error.txt` 的 `file:行号` 与 `hint`，再动数据
- [ ] 弹窗里的 `Warning:` 逐条看过（有的警告是「字段无意义」的预告）
- [ ] 文档记录了：改了什么、为什么、备份在哪、脚本叫什么、进游戏看哪几条
- [ ] 若推翻了旧结论：**保留错因**，别只改成正确答案（错因对后来者最有价值）


---

## B. Fatal 报错对照与失败定位（原 fatal-catalog.md）

# Fatal 对照表与失败定位

## 1. 先分清「编译期」与「加载期」

| 阶段 | 查什么 | 报错长相 |
|---|---|---|
| 编译期（`generatemod`） | NDF 语法、引用是否可解析 | `#32770` 弹窗，`NDF parsing error. Retry?`；**退出码仍可能是 0** |
| 加载期（游戏启动 / 读 ndfbin） | 描述符数据库完整性、时间粒度、注册键、攻击策略 | 启动即崩或记事本弹 Fatal，**`generatemod` 完全不报** |

> **「编译通过」只算一半。** 新增单位或改攻击策略后，必须让用户**启动一次游戏到主菜单**。

## 2. 报错 → 根因 → 修法

| 报错 / 症状 | 根因 | 修法 |
|---|---|---|
| 启动即崩、`Fatal -17` | mod 名含非 ASCII（全角冒号等） | 全 ASCII 重命名；同步 `Localisation/<mod>/`、`ResourcePacks/<mod>/` 与 2 个 ndf 硬编码路径 |
| `No suitable weapon for DiveBombAttackStrategyDescriptor` | 单位带 `DiveBomb` 但**没有炸弹类武器**（连残骸实体也校验） | 无炸弹机型只留 `Dogfight, Dive` |
| `happening 'X' requested and missing in Mimetic World Descriptor` | 步兵 `FireEffectTag` 键未注册 | 在 `InfanterieWeaponsUnites.ndf` 末尾注册表补 `( 'FireEffect_<弹药去Ammo_>', FXWeapon_<同名> )` |
| `No unit name dictionnary found for nationality ''` | 实体缺 `MotherCountry` | 补国籍（**只在启动期报**） |
| `Unit 'X', Transport '(None)', Exp 0 doesn't match division rule` | 硬建了独立 pack 却当运输用 | 改走组合包 `Transport=<车> Unit=<步兵>` |
| `Weapon with parabolic trajectory cannot be embedded on planes or helicos` | 飞机/直升机挂抛物线弹道 | 换 `ProjectileType` |
| `Value is too long for a TLocalisationToken` | token > 10 字符 | 缩到 10（CSV 引号不计） |
| 时间粒度 Fatal（无明确原文） | `TimeBetweenTwoShots < 0.1` / `TimeBetweenTwoFx < 0.05` | 提到下限 |
| `XPMultiplier[0] == 0` 相关 Fatal | 首档倍率为 0 | 写 `[1.0,0,0,0]` |
| `NDF collection length mismatch` | 改 list 长度没同步 `length`（仅 `.ndfbin` 层编辑会碰到） | 同步字段 |
| `File not found: UNITS-SC.dic.tag` | 刚改过 `UNITS.csv` 的编码 | **重跑一次即过** |
| 括号/对象数对不上但编译通过 | 锚点把上一条对象从中间劈开 | 锚点必须含「收尾」特征 + `),`；守卫「对象数 == 收尾行数」 |

## 3. 编译：只用守卫脚本

```bash
"<python>" <skill>/scripts/genmod_guard.py            # 默认在工程根目录下跑
```

| rc | 含义 |
|---|---|
| 0 | 成功（日志必须有 `Mod Generation Success`） |
| 3 | 被弹窗拦下（守卫已落盘报错原文到 `genmod_last_error.txt`） |
| 4 | 超时（**没有弹窗**，不是语法错，别去翻弹窗） |
| 5 | 环境问题 |
| 1（无弹窗） | 最常见是**游戏开着** |

**为什么不用退出码**：`GenerateMod.py` 语法错也返回 0；`WARNO.exe` stdout 默认块缓冲，被 kill 时 0 字节。
**报错原文只存在于 `#32770` 模态框里。**

三条纪律：
1. 绝不 `taskkill /IM WARNO.exe` —— 会杀掉玩家正开着的游戏。按弹窗所属 PID 杀。
2. 开跑前若已挂着报错弹窗，先关掉（分不清谁的错）。
3. 别对着真工程用短超时「试参数」，那会真的把 `Gen/` 写到一半。

## 4. 无弹窗 exit 1 的三步定位

1. **回滚到已知 good 状态编译一次** —— 通过 = 环境无碍，问题在本次改动。
2. **二分**：按变体或按文件减半复现（多文件改动时先按文件，再看是哪个对象）。
3. 复现时守卫多半能抓到弹窗原文；抓不到就逐个对象与同型原版做归一化 diff。

## 5. 「改了没生效」的排查顺序

| # | 查什么 | 怎么查 |
|---|---|---|
| 0 | 改动真的落盘了吗 | 目标文件与备份的 mtime + **逐对象 diff**（不是整文件） |
| 1 | 用户选的就是他以为的那个吗 | **`NameToken` → 词典还原显示名**，不要拿对象名判断 |
| 2 | `Gen/` 的时间戳 | 所有 `Gen/` 文件（含 `Version.ndf`）的 mtime = 最后一次成功生成时间 |
| 3 | 构建脚本到底说了什么 | 看日志里的 `Process output:`；最高频是 `Error: Mod outdated. Update required.`（游戏更新后 `<mod>/base.zip` 与 `ModData/base.zip` 不一致 → 跑官方 `UpdateMod.bat`，必须双击运行，会 `input()` 等冲突处理） |
| 4 | 这个数据真的被游戏用到吗 | 编辑器列出的对象 ≠ 游戏引用的对象 |
| 5 | 才怀疑写入逻辑 | 与预期模型 diff |

## 6. 行尾与编码（假 diff 的主要来源）

| 陷阱 | 后果 | 做法 |
|---|---|---|
| 见 CRLF 就把整文件按 CRLF 写回 | 把 LF 文件整份转成 CRLF（几十万行假 diff） | 按 **bareLF 与 CRLF 孰多**判定；写回用原行尾 |
| `Path.read_text()/write_text()` 改大 `.ndf` | 整文件换行被重写 → 71 万行全变更 | 二进制读写，`newline=""` 语义自己控制 |
| 台账/本地化不探编码 | `UNITS.csv` 被存成 GBK → 管线字节直传 → 中文乱码 | 写前探测 BOM + CRLF；发现 GBK 转回 UTF-8 并告知 |
| 台账备注裸双引号 | `csv.reader` 拆成 16 列 | 转义 `""`；写完复核列数 |

**编码切换的副作用**：改过 `UNITS.csv` 编码后，首次构建可能 rc=1 报 `File not found: UNITS-SC.dic.tag`，**重跑一次即过**。

## 7. 产物与时间戳

- `Gen/NDF/GFX/*.ndfbin` 全哈希无明文 → 只能看**字节增量 + mtime** 判断内容。
- 构建是**增量的**：没改武器则 `Weapon.ndfbin` 不动 —— 这是最省事的「我改到哪层了」信号。
- 产物两处：`Mods/<Mod>/Gen`（部署版，游戏读这里，有 `.tag`）与
  `Saved Games/EugenSystems/WARNO/mod/<Mod>/Gen`（ModGen 工作区）。`CopyModGenData.py` 回拷时才补 `.tag`。

## 8. 备份与回滚

- 改任何 NDF 前备份到 `.workbuddy/backup/<文件>.<时间戳>.before_<标签>`。
- 回滚三档：**单维度**（撤一个字段）→ **单文件**（恢复备份）→ **整目录**（回滚全部改动再编译）。
- 脚本必须**幂等 + `--dry-run`**：重跑应全部走「跳过」，而不是再插一遍。
