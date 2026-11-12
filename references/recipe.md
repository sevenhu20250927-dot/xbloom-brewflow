# 可执行配方合同

权威校验入口是`scripts/xbloom_bridge/protocol.py`的`load_recipe`、`build_recipe_frames`。这描述本包支持范围，不等同厂家全部物理限制，也不是已验证的官方App导入格式。JSON仅存机器参数，豆名、理由与评分进入record.md。

根必填`cupType`、`doseGrams`、`recipe`；可选`bypassMl`、`bypassTempC`必须成对。`recipe`必填`grinderSize`、`rpm`、`grandWater`、`pours`。每段必填`volume`、`temperature`、`flowRate`、`pattern`、`pausing`、`vibBefore`、`vibAfter`。未知字段、重复键、缺字段均拒绝。

| 字段 | 本包约束 |
| --- | --- |
| cupType | 仅`xdripper`，机磨＋标准滤杯路径 |
| doseGrams | JSON整数5–18g |
| grinderSize | 整数1–80，数字越小越细 |
| rpm | 60–120，以10为步长 |
| pours | 1–9段 |
| volume／grandWater | 整数1–500ml，分段合计必须等于grandWater |
| temperature | 整数40–95℃；特殊20=RT、98=BP，不保证实际室温或沸点 |
| flowRate | 3.0–3.5ml/s，以0.1为步长，不接受近似修正 |
| pattern | 0中心、1环绕、2螺旋 |
| pausing | 整数0–59秒，为该段之后的停顿，不等于闷蒸总时间 |
| vibBefore／vibAfter | JSON布尔值 |
| bypassMl／bypassTempC | 开启：整数1–500ml与40–95℃；关闭：均省略或0／0 |

过粉＋旁通总量≤500ml。`grandWater`始终只计过粉水；总饮用配比按`(grandWater+bypassMl)/doseGrams`展示。旁通单独配置，不伪装成第五段普通注水。

过粉水量×10÷粉量必须精确得到1–255的整数，float32既有编码还原也必须精确；不接受偷偷缩放。例如15g、215ml过粉不满足该规则，不能自动改成216ml；15g、210ml过粉＋15ml旁通是另一份需用户审核的方案。

文件为UTF-8普通文件，最多64KiB。整数位不能写15.0、字符串或布尔值；非有限数、深嵌套解析失败与类型错误均拒绝。离线预览打印三条配置帧与内容SHA256，不含启动命令。

协议顺序：8102（旁通float32 ml、旁通float32摄氏度、粉量整数）→ 8104（杯型）→ 8001（完整分段、研磨及配比）。用户授权后另发8002启动。普通段温度和旁通温度采用不同字段编码，不凭字段名相同推断表示相同。
