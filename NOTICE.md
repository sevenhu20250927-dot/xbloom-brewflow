# 来源与许可

项目作者为花炉咖啡·尹壹壹和 SevenMeds。

本包从testCoffee中已使用的独立xBloom桥接模块抽取，保留协议、会话与日志核心。提取只做发布所需的路径解耦、指定目录总账和文档整理；发布版报告补充了缺40512时采用ready的显式候选口径。

- 命令编码参考 [ryunana/xbloom-studio-recipe-skill](https://github.com/ryunana/xbloom-studio-recipe-skill) 1.3.2 的 `scripts/xbloom_proto.py`，MIT，Copyright 2026 chengway.wang。
- 状态与重量解释参考 [Janczykkkko/xbloom-ble](https://github.com/Janczykkkko/xbloom-ble) 的 `xbloom_ble/telemetry.py`，MIT，Copyright 2026 Janczykkkko。
- 旁通沿用原编码器的8102结构，并参考花炉咖啡烘焙师一一的扩展传参方式：float32水量、float32摄氏度、整数粉量。
- 拟方与复盘方法参考一一的六层框架及本地知识闭环实践：目标、解释工具、参数影响、类型起点、个人偏好、反馈。0.2.0补入完整经验库、总账、品鉴卡和25条运行资料，并适配知识闭环技能。另获发布者同意加入其冲煮和品饮数据。来源归属与改写记录见`knowledge/catalog.json`；不宣称一一审核过本包或每条建议，也不把来源文本中转述的第三方观点说成本项目原创。

完整上游许可保存在[scripts/xbloom_bridge/PROTOCOL_LICENSE.txt](scripts/xbloom_bridge/PROTOCOL_LICENSE.txt)，本包遵循[MIT License](LICENSE)。测试中的固定字节是软件编码对照，不是实机接受证明；示例JSON与模拟通知不带真实用户身份。

本工具不由xBloom官方提供、认可或担保。协议解释中未核实的字段继续标为provisional。Bleak为运行时依赖，其许可证按该依赖自身分发。
