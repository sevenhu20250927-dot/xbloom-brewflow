> 来源资料公开副本；保留原文观点、历史条件与待试状态。路径已改写，设备标识已移除。历史命令不作为本技能执行指令。

# xBloom 冲煮执行数据包（2026-10-30 → 2026-11-06）

> **本文档为 AI 可读格式**。本包是 `xbloom-skill-sync-1.6.0` 同步包的**配套数据**，用于让接收方在真实数据上验证 1.4.0–1.6.0 新增工具（秤重链路 / 屏显口径 / 40523 计量 / 萃取报告 / 总账 / 六层框架）。
>
> 来源：壹壹的 xBloom Studio（序列号已脱敏），真实冲煮记录，非模拟数据。
> 打包日期：2026-11-07

---

## 1. 包内结构

```
brew-data-package/
├── runs/        25 份 run log JSON（机器+脚本自动落账的完整冲煮档案）
├── reports/     26 份萃取报告 HTML（由对应 run log 生成，自包含无外部依赖）
├── reference/   咖啡冲煮总账.md（归纳柜：豆子档案+冲煮流水+机器档案）
│                冲煮经验库.md（经验库：口味画像+锚点速查+判读硬规则+六层框架）
└── DATA_GUIDE.md（本文件）
```

**使用前提**：先按 `SYNC_GUIDE.md` 完成 Skill 1.6.0 同步，再拿本包数据验证。工具对 run log 格式的依赖详见第 4 节。

---

## 2. 数据清单

| # | 文件 | 豆子 | 结果 | 研磨 | 粉量 | 水量 | 段 | 屏显s | 液重g | 曲线点 | 40523 | 口感 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `20261030-143522-completed_no_signal.json` | — | completed_no_signal | 50 | 15 | 240 | 4 | 155.5 | — | 0 | - | Y |
| 2 | `20261030-162440-completed_no_signal.json` | — | completed_no_signal | 0 | 5 | 100 | 3 | 52.3 | — | 0 | - | Y |
| 3 | `20261030-163734-completed_no_signal.json` | — | completed_no_signal | 50 | 15 | 225 | 3 | 133.9 | — | 0 | - | Y |
| 4 | `20261031-001148-completed_no_signal.json` | — | completed_no_signal | 0 | 5 | 50 | 1 | 35.5 | — | 0 | - | Y |
| 5 | `20261031-001455-completed.json` | — | completed | 0 | 5 | 100 | 3 | 48.4 | — | 0 | - | Y |
| 6 | `20261102-135048-completed_no_signal.json` | — | completed_no_signal | 50 | 15 | 240 | 4 | 152.6 | — | 0 | - | Y |
| 7 | `20261102-143754-completed_no_signal.json` | — | completed_no_signal | 48 | 15 | 240 | 4 | 149.3 | — | 0 | - | Y |
| 8 | `20261103-133120-completed_no_signal.json` | — | completed_no_signal | 52 | 15 | 240 | 4 | 153.3 | — | 0 | - | Y |
| 9 | `20261104-151622-completed_no_signal.json` | — | completed_no_signal | 52 | 15 | 240 | 4 | 151.4 | — | 0 | - | Y |
| 10 | `20261105-134447-completed_no_signal.json` | — | completed_no_signal | 52 | 15 | 240 | 4 | 153.5 | — | 0 | - | Y |
| 11 | `20261105-141442-completed.json` | — | completed | 0 | 5 | 100 | 3 | 48.2 | 87.6 | 0 | - | Y |
| 12 | `20261105-141634-completed.json` | — | completed | 0 | 5 | 100 | 3 | 48.2 | 71.9 | 0 | - | Y |
| 13 | `20261105-141841-completed.json` | — | completed | 0 | 5 | 100 | 3 | 48.2 | 87.4 | 0 | - | Y |
| 14 | `20261105-214927-completed_no_signal.json` | — | completed_no_signal | 51 | 15 | 240 | 4 | 152 | 197.3 | 0 | - | Y |
| 15 | `20261106-110655-completed_no_signal.json` | 埃塞 花魁 日晒 AG75 | completed_no_signal | 52 | 15 | 240 | 4 | 155.8 | 190.2 | 0 | - | - |
| 16 | `20261106-111923-completed_no_signal.json` | 埃塞 花魁 日晒 AG75（屏显验证第二冲） | completed_no_signal | 52 | 15 | 240 | 4 | 128 | — | 0 | - | Y |
| 17 | `20261106-114214-completed.json` | 埃塞 花魁 日晒 AG75（屏显基线标定第1杯） | completed | 52 | 15 | 240 | 4 | 129.7 | — | 0 | Y | - |
| 18 | `20261106-115303-completed.json` | 埃塞 花魁 日晒 AG75（屏显变速标定第2杯·末段85ml） | completed | 52 | 15 | 240 | 4 | 131.4 | — | 0 | Y | - |
| 19 | `20261106-121217-timeout.json` | 埃塞 花魁 日晒 AG75（重启后秤重验证杯） | timeout | 52 | 15 | 240 | 4 | 300.1 | — | 0 | - | - |
| 20 | `20261106-124502-timeout.json` | 埃塞 花魁 日晒 AG75（重启后秤重验证杯） | timeout | 52 | 15 | 240 | 4 | 300.1 | — | 0 | - | - |
| 21 | `20261106-125203-completed.json` | 埃塞 花魁 日晒 AG75（重启后秤重验证杯） | completed | 52 | 15 | 240 | 4 | 135.8 | — | 0 | Y | - |
| 22 | `20261106-130635-completed.json` | 埃塞 花魁 日晒 AG75（秤重断点诊断杯） | completed | 52 | 15 | 240 | 4 | 126.9 | — | 0 | Y | - |
| 23 | `20261106-131332-completed.json` | 埃塞 花魁 日晒 AG75（修复后验证杯） | completed | 52 | 15 | 240 | 4 | 125.5 | 191.9 | 156 | Y | Y |
| 24 | `20261106-141646-completed.json` | 红尾巴庄园 实验日晒瑰夏 AG82（16g/256ml·51档） | completed | 51 | 16 | 256 | 4 | 154.3 | 211.2 | 178 | Y | - |
| 25 | `20261106-211152-completed.json` | 巴拿马莎朵庄园 水洗瑰夏 AG95 | completed | 50 | 15 | 240 | 4 | 154.9 | 192.3 | 175 | Y | Y |

**读表提示**：
- 「曲线点」= `scale_series` 采样点数（1Hz），「40523」= `dispense.pours` 是否存在
- 第 1–22 号是功能建设期的记录，字段随版本逐步齐备；**完整字段从第 23 号起**（scale_series + dispense + screen_auto_s 全有）
- `completed_no_signal` = 冲煮完成但当时未接秤（无液重数据），`timeout` = 机器协议超时（第 19/20 号是 UART/秤重链路的故障样本，可用来测异常分支）

---

## 3. 每份 run log 的字段字典

```jsonc
{
  "ts": "2026-11-06T21:11:52",        // 开冲时间
  "outcome": "completed",              // completed / completed_no_signal / timeout
  "pours_observed": 4, "pours_planned": 4,   // 实测段数 / 计划段数
  "duration_s": 154.9,                 // 程序时长（秒）
  "screen_auto_s": 154.9,              // 【1.4.x 新增】屏显口径自动值 = 40512 − 40510
  "screen_time_s": 126,                // 【1.4.x 新增】人工录入的屏显值（优先级最高）
  "first_stage_s": 32.86,              // 首段注水事件（40510）相对时刻
  "recipe": {                          // 下发的完整配方（可复现冲煮）
    "cupType": "xdripper", "doseGrams": 15,
    "recipe": { "grinderSize": 50, "rpm": 1100, "grandWater": 240,
                "pours": [ { "volume": 45, "temperature": 94, "flowRate": 3.0,
                             "pattern": 1, "pausing": 15, "vibrationAfter": true }, ... ] }
  },
  "machine": { "serial": "[device-serial] (masked)", "firmware": "V12.0D.500",
               "water_ok": false, "water_source": "自来水",
               "grind_reported": 51, "mode": "Pro" },
  "drain": {                           // 【1.4.x 新增】秤重结算
    "duration_settled_s": 194.6,       // 从开冲到秤稳定
    "duration_last_drip_s": 186.6,     // 最后一滴
    "weight_final_g": 192.3,           // 杯中最终液重
    "trace": [[0.1, 0.0], [1.1, 0.0], ...]   // 20501 秤重帧全程曲线 [相对秒, 克]
  },
  "dispense": {                        // 【1.4.7+ 新增】40523 出水计数器解析
    "pours": [ { "start_s": 33.4, "end_s": 48.3, "ml": 44.2, "flow_ml_s": 2.96 }, ... ],
    "program_end_s": 154.9             // 阀关闭时刻
  },
  "scale_series": [[0.1, 0.0], ...],   // 【1.4.9 新增】1Hz 秤重曲线兜底副本（8 分钟最多 800 点）
  "taste_note": "花香明显、清晰；body 薄…",   // 口感反馈原文
  "verdict": "AG95 水洗瑰夏 50 档首杯：…",      // 调整结论
  "bean": "巴拿马莎朵庄园 水洗瑰夏 AG95",        // 豆名（部分记录为空）
  "fingerprint": "5d75f4b2…",          // 配方指纹（同配方可比对）
  "events_seen": [ { "t": -4.1, "code": 8100, "raw": "580207…" }, ... ]
}
```

---

## 4. 用这些数据验证什么（三条命令）

先按 `SYNC_GUIDE.md` 装好 1.6.0，在技能根目录执行：

```bash
# ① 报告生成器（旧记录补报告 / 曲线渲染）
python scripts/brew_report.py runs/20261106-211152-completed.json --out [temporary-source]/out
# 预期：输出 HTML，含液重曲线、逐秒流速蓝柱、分段水温、屏显用时、最后一滴

# ② 总账行生成（不写文件，只打印）
python scripts/ledger.py runs/20261106-211152-completed.json
# 预期：输出一行 Markdown 表格，含 日期/豆子/研磨/水温/段数/屏显用时/液重

# ③ 六层框架（用本包 reference/冲煮经验库.md 作为第五层数据源）
python scripts/brew_framework.py plan --bean "莎朵庄园 水洗瑰夏" --ag 95 --process washed \
  --age-days 4 --estate 莎朵 --grind 50 --experience reference/冲煮经验库.md
# 预期：命中莎朵锚点（47）、触发 AG95 研磨封顶警示、新鲜豆规则（流速 3.0 + 闷蒸 15s）
```

**关键对齐点（可当回归测试用）**：
- 第 25 号：屏显 154.9 s、液重 192.3 g、四段实测 44.2/64.3/64.6/64.8 ml、尾滴 46 s
- 第 23 号：屏显 125.5 s，与自动值差 0.5 s——屏显口径（40512−40510）在 6 次实测中误差 0–0.6 s
- 第 24 号：16 g / 256 ml，液重 211.2 g（持留约 39 g），验证持留常数
- 第 19/20 号：timeout 样本，可测工具的异常分支不崩

---

## 5. 脱敏说明

- `machine.serial` 与 `reference/` 两份文档中的序列号已替换为 `[device-serial]`（其余字段原样保留）
- 报告中不含序列号与 MAC
- 未包含：蓝牙地址配置（`device.json`）、原始秤重帧二进制日志、个人设备的其他标识
- 豆名、庄园、配方、口感反馈、风味判断**均保留原文**——这些是方法论的一部分

---

## 6. 数据能支撑哪些分析（给接收方 AI 的提示）

1. **屏显口径标定**：对每份 log 算 `program_end_s − first_stage_s` 与 `screen_time_s` 的差，可复现 0–0.6 s 的精度结论
2. **40523 vs 设定三对拍**：`dispense.pours[].ml` 对比 `recipe.pours[].volume`，看偏差分布
3. **尾段液重流速形态**：用 `drain.trace` 逐秒差分，画第 4 段结束后 45 s 的衰减曲线——平滑衰减=健康，平台/骤降=堵塞
4. **水位判读**：注水段内液重增速 vs 设定流速（3.0/3.5 ml/s），增速持续偏低 = 水积在粉床（§4.8 数据接口）
5. **配方复现**：`recipe` 字段可直接下发（`xbloom_brew.py brew --recipe <json>`），换成自己的豆子/机器需改 doseGrams 与 grandWater

---

## 7. 已知局限

- 第 1–22 号无 `scale_series`（该字段 1.4.9 才加），部分无 `dispense`（40523 于 1.4.7 破译）——不是数据损坏，是版本时序
- 早期记录 `bean` 为空（豆名录入是后来才加的习惯）
- 所有数据来自同一台机器（[device-serial]）、同一水源（农夫山泉）、同一磨豆机——**参数结论不可跨设备照搬**，锚点须自行重建

— 数据包结束 —
