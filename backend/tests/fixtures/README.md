# Edax 真实输出

`edax-4.6-macos-initial-hint.txt` 是用户于 2026-10-11 提供的终端记录中，`hint 4` 返回内容及下一提示符的摘录。未改写候选、分数、深度、变化或耗时。

- 环境：macOS ARM64，clang 编译，Edax v4.6 源码 `713a434f13b3d15fb69c61b9ba3641aed82c496c`，已应用仓库内哈希表分配补丁。
- 版本输出：`Edax version 4.6 Oct 11 2026 22:43:24 for Apple`。
- 启动参数：`-eval-file ./deploy/edax/eval.dat -level 8 -n-tasks 1 -book-usage off`。
- 棋盘：默认初始棋盘，黑方行棋；未执行 `setboard`。
- 命令：`version`、`hint 4`、`quit`。

`edax-4.6-macos-quiet-initial-hint.txt` 是同日用户提供的第二份记录中 `hint 4` 返回内容及下一提示符的摘录。使用后端完整参数：`-eval-file ./deploy/edax/eval.dat -level 8 -n-tasks 1 -book-usage off -ponder off -auto-store off -mode 3 -verbose 0 -width 250`。执行 `version`、`setboard ...........................OX......XO........................... X`、`hint 4`、`quit`，四个候选仍为深度 8、分数 -3。用户此前单独输入不带棋盘参数的 `setboard` 得到警告，随后使用完整命令成功。

`edax-4.6-macos-adapter-check.json` 是用户执行 `check-edax` 后生成的 `eval/results/edax-check.json` 的原样副本。报告状态为 passed，四个局面在同一个真实进程中通过：初始黑方、d3 后白方、强制跳过的两空格残局以及跳过后的单空格残局。残局精确分数 +64 与规则引擎计算出的终局子差相同；原始输出中的 `PA` 被解析为 `pass`。

这些记录证明上述本地管道与局面评分检查通过。解析回归测试尚未执行；批量生成、更多残局、异常与超时恢复仍需验证。记录中的单次搜索耗时不代表后端端到端性能。
