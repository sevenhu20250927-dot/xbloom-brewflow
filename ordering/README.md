# BrewFlow 点单台

项目作者包括 **花炉咖啡·尹壹壹**。在仓库根目录用 Python 3.11+ 运行。点单与库存摘录放在自己的 SQLite 文件里，首次启动是空白豆单。

## 第一次点单

以下命令会提示你填写自己的资料，随后启动本机网页。可以重复使用 add-bean 和 add-person 添加豆子与品饮人。

```sh
read -r -p "品饮人昵称：" guest
python3 -m ordering.server add-person "$guest"
read -r -p "豆子名称：" bean
read -r -p "剩余克数：" grams
python3 -m ordering.server add-bean "$bean" --grams "$grams"
python3 -m ordering.server serve
```

上例使用 Bash。其他终端也可以直接运行 `python3 -m ordering.server add-person "昵称"` 和 `python3 -m ordering.server add-bean "豆名" --grams 100`，把引号内文字与余量换成自己的。录豆支持 `--roaster`、`--country`、`--process`、`--variety`、`--flavor`、`--notes`。豆袋风味与产地资料会出现在豆卡上。

打开 [本机点单台](http://127.0.0.1:8770/menu)。选品饮人和制作方式，在「今日轮换」挑一款，或搜索全部在库豆。可点门槛是 15 g；点「就喝这款」会弹出订单号。「我的订单」支持修改尚未接单的豆子、饮用人、制作方式或备注，也可以取消、删除。制作人到「接单台」接单，交付后标记已交付。点单与接单只更新订单，机器开始仍须单独审核配方并明确授权。

## 按口味推荐

每日轮换无需模型。个人口味可在「按我的口味」保存。要启用 AI 推荐，请启动时指定提供方和该账户可用的模型名。

```sh
python3 -m ordering.server serve --recommend-with codex --model "你的模型名"
# 或将 DEEPSEEK_API_KEY 配在本机服务环境后运行
python3 -m ordering.server serve --recommend-with deepseek --model "你的模型名"
```

Codex 路线需要本机已登录的 Codex CLI。点击「生成口味推荐」会把可点豆卡和当前品饮人的偏好交给所选模型。每款推荐附可核对的摘录。库存不足三款时按实际数量返回；引用不匹配时页面会显示错误。

默认数据库为 `~/.xbloom-brewflow/orders.sqlite3`。要换库，在子命令之前加 `--db 文件路径`。点单台面向本机共享设备，浏览器切换昵称即可查看各自订单。这里的余量是录入的点单参考值，交付时不自动扣除冲煮库存。这个模块没有连接 BrewFlow 示例库或任何作者账户。
