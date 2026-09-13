# 升级实施进度与证据

依据 `plans/2026-09-11-1411-feat-tennis-coaching-intelligence-plan.md`。
代码测试与真实数据/设备晋级分别记录；本文件不是准确率证明。

| 单元 | 实施状态 | 验证与剩余项 |
|---|---|---|
| U0 评估基础 | 已增加内容防泄漏、比赛级球指标区间、协议与上下文快照 | Python 85 tests；真实比赛、双人标注与其他指标区间待补 |
| U1 v3 数据合同 | 读写、迁移、事件审计、资料库删除已实现 | Python/Swift 共享样例与导出校验通过；空间/身份编辑随 U3/U4 接入 |
| U2 球与质量 | 已接入可选运动过滤实验、画面质量和禁止跨移动插值 | 基线保持默认；真实测试集对比与模型晋级待完成 |
| U3 球员与站位 | Python 站位估计、角色歧义、身份审核 CLI 和 Swift 审核读取已实现 | 原生身份编辑界面、站位导出整合和实测误差待完成 |
| U4 接触/动作/落点 | 待实施 | 未训练动作分类器 |
| U5 统计与指导 | 待实施 | 教练试用依赖未满足 |
| U6 App | 待实施 | 实体设备门槛未满足 |
| U7 发布 | 开发产物 CI 与发布条件检查已实现 | 78e649f 的两项 CI 和开发产物已验证；签名、受保护发布环境与真实数据/设备条件未满足 |

## 当前证据

- `tests/test_events_benchmark.py`：哈希不匹配和跨 split 内容别名拒绝；同一比赛多片段
  合并后 bootstrap 区间保持一致；缺少比赛与零分母不伪造区间。
- `tests/test_context_snapshot.py`：快照最多 120 行，排除私有视频和环境文件，拒绝越界来源。
- `docs/EVALUATION_PROTOCOL.md`：采集、标签、晋级、设备和用户试用协议。
- `benchmarks/acquisition.json`：手机真实验证比赛尚未提供。
- 2026-09-12 基础批次：Python 103 tests、Swift 15 tests、Swift→Python 四组导出校验、
  wheel 资源读取和 unsigned simulator build 均通过。详见 `docs/data/development-2026-09-12.json`。
- 2026-09-13 增量：Python 112 tests、Swift 19 tests 通过；身份/回合共用审核样例
  验证两端恢复与重复打开行为。完整独立审核未完成，不能据此宣称整个升级已交付。
