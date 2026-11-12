# xBloom BrewFlow

让每一杯都有依据、有记录、有改进。

An agent skill for xBloom Studio: plan recipes, brew over Bluetooth, capture reports, and refine with tasting feedback.

内置一一完整经验库、六层拟方方法，以及发布者的机冲／手冲与个人反馈，支持有案例可查的冷启动。入口见[知识与案例](knowledge/README.md)。

一个独立的Agent技能：从豆子信息拟定配方，经人审核并明确授权后操作xBloom Studio，自动生成原始日志、逐杯HTML／SVG报告和本地总账，再根据品饮反馈修方。

```text
豆子与个人偏好 → 配方及依据 → 离线校验 → 审核／明确开始
                                                ↓
新版配方 ← 品饮反馈 ← HTML报告／总账 ← 蓝牙执行与JSONL
```

## 安装

第一版面向 **macOS、Python 3.11+、xBloom Studio标准滤杯与机磨流程**。底层使用Bleak；Unix设备锁尚未移植到Windows，Linux硬件流程未验证。其他滤杯、免研磨或模式切换不在本版执行范围。

把整个 `xbloom-brewing` 文件夹放进Agent的技能目录。Codex可使用 `~/.codex/skills/xbloom-brewing`，其他Agent可直接读取本目录的 `SKILL.md`。

从本仓库安装到Codex（目标目录应尚不存在）：

```sh
git clone https://github.com/sevenhu20250927-dot/xbloom-brewflow.git ~/.codex/skills/xbloom-brewing
cd ~/.codex/skills/xbloom-brewing
```

仓库名为`xbloom-brewflow`，技能调用名为`xbloom-brewing`。

在本目录创建Python环境：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/xbloom.py --help
```

首次实际连接时，给运行该Python的应用授予macOS蓝牙权限。将个人数据放在技能目录以外，例如 `~/CoffeeWorkspace`。日常对Agent说：

> 用 xbloom-brewing 帮我拟一杯配方，先给我审核。我使用15g豆、标准滤杯，其他条件如下……

> 这杯入口甜、中温略涩。根据刚才记录提出下一版，说明依据。

## 包含什么

- `SKILL.md`：Agent入口与授权边界。
- `references/`：一一的拟方／修方与知识审核流程、类型模板、参数合同和操作口径。
- `knowledge/`：完整来源经验、总账、按豆案例、个人偏好和迁入证据；无需原库存数据库即可阅读。
- `scripts/xbloom_bridge/`：配方校验、BLE编码与状态处理、追加日志、报告和指定目录的总账。
- `examples/`：无个人信息的格式示例，均需按具体豆子审核。
- `tests/`：离线回归与发布包适配用例，使用模拟设备与临时数据。

无库存数据库、网页服务器、账户、定时器或AI API运行依赖。随包数据是公开的冷启动快照，不连接作者数据库。反馈由Agent写入本地Markdown，总账只读取调用者指定的日志目录。原始通知可能含设备序列号和地址，分享时由使用者选择范围，不自动上传。

## 可靠性与范围

严格拒绝重复键、未知字段、非法类型、不能精确编码的比例，以及水量不一致；不自动取整。装载与启动分离，启动绑定配方指纹；设备锁避免同一Mac上本桥接器并发控制同一地址。每条命令发送前写日志，无自动重试。

BLE核心从已有macOS／Studio固件`V12.0D.500`的实冲项目抽取，包含本机曾观察成功的原生旁通路径；实际旁通温度尚未独立测量。**发布包当前的验证状态见[验证说明](VALIDATION.md)**，原项目的成功不等于裁剪后的包已验证。

`completion=unconfirmed`保持证据边界：收到ready或结束候选、观察窗口结束，均不自动证明屏显时间、物理最后一滴或已喝到咖啡。报告液重是末次有效读数，取杯与秤状态变化可能影响它。用户反馈和人工核对另记。

已知限制：采集时长由调用者设置，暂不自动延长；完整配方读回、实测水温／RPM／粉量、TDS／EY和物理末滴未实现；评分不自动学习数值权重。读取到的研磨快照不能代表装载后的实际档位。

## 开发验证

获得所在环境要求的测试授权后，从本目录执行：

```sh
PYTHONPATH=scripts python3 -B -m unittest discover -s tests -v
```

测试不连接机器。技能结构另可用Codex `skill-creator` 的 `quick_validate.py` 检查（需要PyYAML）。

## 发布到GitHub

将本目录内容作为独立仓库根目录；不把上层咖啡项目一起上传。保留 `LICENSE`、`NOTICE.md` 与协议许可证。`.gitignore`排除本地环境、运行日志、反馈记录和常见数据库；它不替代提交前逐项检查。

公开仓库：[sevenhu20250927-dot/xbloom-brewflow](https://github.com/sevenhu20250927-dot/xbloom-brewflow)。后续修改应完成相应离线验证并如实保留硬件验证范围。使用者的新豆子记录与反馈在个人工作目录中维护，不作为技能更新覆盖。公开的历史种子数据已获提供者同意，新增记录是否公开仍由使用者决定。

本项目为非官方社区工具。协议来源、归属与方法参考见[NOTICE.md](NOTICE.md)。
