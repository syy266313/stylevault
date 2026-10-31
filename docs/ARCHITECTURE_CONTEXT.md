# StyleVault Architecture Context

> 面向架构对话、执行 Agent 和 TRAE 的最小可恢复上下文。本文档保存稳定信息；当前阶段状态以 `docs/AGENT_HANDOFF_M3.md` 为准。

## 1. 用户操作环境

- 用户主要使用 iPhone/iOS 上的 OpenMinis。
- OpenMinis 内置 iSH Alpine Linux、Shell、文件工具、浏览器和 Git 操作能力。
- `/var/minis/shared/stylevault/` 是 StyleVault 工作区；共享文件放在 `/var/minis/shared/`。
- 环境变量可保存 API key 和 token；不得读取、打印、写入文档或提交实际值。
- 手机端适合架构设计、代码审查、明确边界的自动化、测试、文档和小型修复。
- 电脑端 TRAE 更适合复杂编码、长时间任务、IDE 导航、大规模重构、视频可视化和真实素材处理。

## 2. 工作分工

### OpenMinis / 手机端

适合：

- 读取项目上下文并制定任务
- 执行小型到中型确定性代码任务
- 运行测试、py_compile、git diff --check
- ffmpeg 小规模验证
- 文档、handoff、回归测试
- 安全 commit、push 和远程 SHA 核验

### TRAE / 电脑端

适合：

- 大规模跨模块重构
- 长时间或批量视频处理
- 真实视频浏览、逐帧检查和人工标注
- 可视化时间轴调试
- OpenCV、PyTorch、TensorFlow 等复杂依赖
- 多分支、PR、IDE 级代码导航
- iOS 后台挂起、内存、CPU 或存储成为限制时

### 架构对话

负责：

- 冻结 schema 和里程碑边界
- 评估是否进入下一阶段
- 审查测试是否证明了目标，而非只证明 synthetic fixture
- 区分确定性 bug、主观产品决策和真实泛化问题
- 决定何时从 OpenMinis 切换 TRAE

## 3. 当前基线

- M3.3 detector：已完成；commit `f4af546`；synthetic acceptance 5/5。
- M3.3.1 benchmark contract：已完成；commit `fd06975`。
- M3.3.1 validator：已完成；commit `5151060`。
- M3.3.1 report-only evaluator：本地已提交，commit `57b35b8`；远程状态须现场核验。
- M4.0 deterministic local search：已完成；commit `74d9a77`。
- M4.0 regression suite：已完成；commit `8eb0fa9`。
- 最新已知远程 main：`637cf99`；本地 `main` 为 `57b35b8`，尚未确认推送。
- 已知测试：视频 78/78；搜索 10/10；benchmark validator 9/9；benchmark evaluator 8/8；M4 regression 8/8。
- frozen schema：`schemas/item.schema.json`，未经架构师明确决定不得修改。
- 真实用户视频泛化：尚未验证。
- 中文同义词和自然语言语义扩展：属于 M4.0 当前边界，不是已确认 bug。

## 4. 架构原则

1. frozen schema 不改；需要扩展时先写设计和迁移方案。
2. synthetic acceptance 与真实泛化 benchmark 必须分离。
3. benchmark evaluator 独立于 milestone acceptance，采用 report-only 设计。
4. 低置信度、缺失媒体或不完整标注不能伪造成事实或指标。
5. M4.0 保持本地、确定性、可解释、稳定排序。
6. 不提前引入 embedding、向量数据库、云端检索、同义词扩展或 Style DNA。
7. 不采集真实用户视频；需要隐私授权时停止并请求明确决定。
8. 代码、测试、文档和数据边界必须清楚；不得把临时任务文件或隐私素材提交。
9. 任何自动化都必须有测试、diff 检查、状态核验和明确停止条件。

## 5. Agent 启动规约

开始任务时依次读取：

- `AGENTS.md`
- `PROJECT.md`
- `PROJECT_CONTEXT.md`
- `docs/ARCHITECTURE_CONTEXT.md`
- `docs/AGENT_HANDOFF_M3.md`
- 当前任务相关的 `docs/DESIGN-*.md`
- 当前 skill 的 `SKILL.md`

然后执行：

```text
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

执行期间：

- 不使用 `git reset --hard` 或破坏性 checkout。
- 先测试再提交；每个逻辑阶段单独 commit。
- 使用 `GITHUB_TOKEN` 时只按变量名引用，不输出值，不写入 remote URL。
- 网络 push 最多尝试一次；失败后记录并继续本地验证，不循环重试。
- 修改前后检查 frozen schema、synthetic fixtures、item.json 和 indexes 是否意外变化。
- 遇到同一失败连续两轮无法定位时停止。

## 6. OpenMinis → TRAE 切换条件

命中任意条件就停止继续扩展，并在 handoff 明确建议切换 TRAE：

- 需要真实视频、逐帧查看或人工标注。
- 需要批量处理大量或长视频。
- 需要桌面可视化时间轴调试。
- 需要 OpenMinis/iSH 难以安装或运行的依赖。
- 需要大规模跨模块重构或 IDE 级导航。
- iOS 后台挂起、CPU、内存、存储导致任务不稳定。
- 上下文窗口或工具协议反复成为限制。
- 同一失败连续两轮无法解决。
- 需要隐私、产品或架构决策，不能安全猜测。

切换时必须写清：当前 commit、未提交修改、失败原因、已运行测试、恢复命令、TRAE 的下一项任务。不得提交半成品或伪造完成。

## 7. 推荐汇报格式

最终汇报使用一个单独的 Markdown 代码块，包含：

```text
【交给架构师】
阶段：
本轮完成：
本地 HEAD：
远程 HEAD：
提交 SHA：
是否已推送：
工作区状态：
修改文件：
测试命令与结果：
真实运行验证：
未验证事项：
阻塞原因：
是否需要架构决策：
是否建议切换 TRAE：
切换 TRAE 的原因：
给 TRAE 的恢复任务：
下一步唯一建议：
```

不要输出完整代码、完整 diff、完整日志、API key、token、cookie、密码或 credential-bearing URL。
