# 本机蓝牙执行

第一版支持macOS。先确认Python环境、蓝牙适配器开启和运行应用获蓝牙权限，再用扫描发现目标。连接前让机器亮屏，手机xBloom App退出或断开；环境已有明确确认时不重复问。首次机器地址须结合名称及现场确认，多个候选不能任选第一个。

以下变量由Agent填入本机真实路径；`SKILL_ROOT`为技能根，`COFFEE_WORK`为外部个人工作目录，`BREW_DIR`为当前杯次目录。环境只需首次创建，后续复用：

```sh
BREW_PY="$SKILL_ROOT/.venv/bin/python"
"$BREW_PY" "$SKILL_ROOT/scripts/xbloom.py" preview --recipe "$BREW_DIR/recipe-v1.json"
"$BREW_PY" "$SKILL_ROOT/scripts/xbloom.py" scan --seconds 8 --output "$COFFEE_WORK/discovery"
"$BREW_PY" "$SKILL_ROOT/scripts/xbloom.py" observe --address "$XBLOOM_ADDRESS" --seconds 15 --output "$COFFEE_WORK/discovery"
```

读取标准GATT信息有时为空；需收到当次握手的machine_info才确认通信。模式或研磨信息只作诊断。UUID为本机发现值，不使用仓库里的示例串；水箱状态仍须结合实际设备核对。

用户审核完整配方，明确设备准备就绪并发出当次开始指令之后，使用preview返回的准确指纹：

```sh
"$BREW_PY" "$SKILL_ROOT/scripts/xbloom.py" brew \
  --address "$XBLOOM_ADDRESS" --recipe "$BREW_DIR/recipe-v1.json" \
  --confirm-start --reviewed-sha256 "$REVIEWED_SHA256" \
  --seconds 300 --output "$BREW_DIR/logs" \
  --report-title "$BREW_TITLE" --brewer 'xBloom标准滤杯'
```

300秒是开始信号之后的采集窗口，可在执行前根据方案选择，最大3600秒，不等于冲煮时长。机器按完整配方自主运行，Agent不能逐段发猜测指令。无需先单独load再断开，brew会完成握手→确认idle→三条配置→确认armed→唯一启动→采集。

仅装载用`load --address ... --recipe ... --seconds ... --output ...`，断开不等于取消。取消必须单独获授权后用`cancel --confirm-cancel --address ... --output ...`；它不是紧急停止按钮替代品。

| 失败位置 | 已知边界与后续 |
| --- | --- |
| 校验失败 | 不连接；修订另存、重新审核，不绕过编码器 |
| 无权限／发现失败 | 不推断机器坏；核对本机蓝牙与权限 |
| 已连但握手无回复 | 不发配方；保留日志，核对亮屏及占用，用户授权后新尝试 |
| 装载后无armed | 配置可能已收到；不重复装载或试用其他协议 |
| 启动后未知状态／超时 | 可能已经物理动作；先核对机器，不能盲目再启动 |
| 运行中断线或未知通知 | 留原始记录，说明缺失；不自动重连或补发控制 |
| 采集结束但完成未确认 | 报告可用事实；主机计时、ready、末滴不能混为一项 |

程序超时和未知状态以非零退出或原始日志呈现；不同命令的返回不是机器成功证据。既有设备锁保留`testcoffee-xbloom-`前缀，用于与原桥接器互斥；同机同地址可互斥，不能跨不同电脑保证独占。

每次尝试结束自动生成报告和本日志目录的index.html。失败也计入，报告失败时输出report_error，总账失败时输出history_error，均不因此重启机器。
