# iOS 26 离线网球复盘

原生 SwiftUI + AVFoundation + Core ML + SQLite 源码。界面为中文；视频、检测和复盘均在本机执行，无账户、服务端或网络请求。最低 iOS 26，目标 iPhone / iPad。

## 生成与安装

先安装并由本人接受 Xcode 许可与所需 iOS 平台组件，再执行：

```sh
cd ios
./install_model.sh ../mobile-toolchain/exports/yolo26s-640-fp16
open TennisOffline.xcodeproj
```

`install_model.sh` 复制配套 `ModelManifest.json` 与 `Detector.mlpackage`，调用无需第三方依赖的 Python 项目生成器。模型资源和生成工程均已忽略，不提交到 Git。项目将 `.mlpackage` 放入 **Sources build phase**，由 Xcode 编译为 `Detector.mlmodelc`；JSON 清单放入 Resources。清单兼容实际导出的 `[1,300,6] / var_1443`，类别为人、球、球拍，不依赖 Vision object 输出假设。尚未放入模型时，`./generate_project.sh` 也能生成项目；开始检测会明确提示缺模型，已有分析仍能复盘。

在 Xcode 选择自己的 Team、唯一 bundle identifier 和真实设备，运行 TennisOffline。首次安装、签名、开发者模式及设备信任由 Xcode / iOS 引导。源代码不包含签名凭据。`project.yml` 是可选 XcodeGen 描述；默认使用 Python 生成器。

## 操作

1. 导入本机视频（最长两小时）或含原视频与必要记录的已完成 v2 分析文件夹，选择单打/双打；导入在后台复制到私有资料库并校验 SHA-256；未完成包需在来源设备完成分析后再导出。
2. 打开比赛，开始或继续离线分析。视频按真实 PTS 逐帧读取；每 60 帧原子提交 SQLite 与跟踪上下文。暂停、离开页面、应用转入后台均保存当前批次。高温/空间不足会停止。重新启动仅接续匹配媒体、模型、参数和运行时的记录。
3. 播放、慢放、跳时间、按分析帧步进；叠加球员框与短轨迹。未检测到球的间隙不会连接虚构轨迹。
4. 人工场地校准按远左、远右、近左、近右选四个双打外角，保存透视映射；可按 ID 修正显示名称。
5. 添加或编辑击球、落点、回合，修改时间、球员、动作、落点米数，复核、排除、收藏。统计仅纳入人工/已复核且未排除事件。自动动作类型保持“未确定”。
6. 对事件导出前后各两秒 MP4 片段并分享；保留原视频的音频轨道。导出文件在比赛 Clips 目录内，删除比赛一并清理。
7. “更新可互操作分析文件”将 SQLite 输出为 v2 `manifest.json / frames.jsonl / events.json / corrections.json`。导入 v1 summary 时要求原视频在包内，不修改输入包。

## 实现与边界

- 解码始终只有一个 sample buffer，最多 60 个紧凑记录及短跟踪状态。不会把整场视频加载进内存。读取原始分辨率的一帧再缩放到分析坐标，4K 输入的瞬时解码内存仍需真机测量。
- 为保持可变帧率 PTS 的精确恢复，当前恢复从视频起始解码并跳过已提交时间；跳过部分不执行模型推理。长片恢复会花时间，尚未实现 GOP 随机定位加速。
- 当前面向固定机位、连续画面；未实现可靠自动切镜/运动相机判定。长遮挡可能创建新球员 ID。球场校准是人工功能；后续帧使用该映射，已完成帧不自动重算。
- 自动击球、落点和回合是保守的轨迹规则候选，必须人工复核；不是经过真实比赛数据验证的准确率承诺。落点手动输入米数，不将画面位置直接当作真实落地。
- Core ML 使用本机计算单元；没有模型下载行为。权重的准确率、速度、耗电、温度以及发布许可由模型交接文档和真机验收单独判定。
- 当前导入为系统文件选择器；不直接枚举照片库。应用进入后台暂停分析，不承诺后台连续推理。

## 验证状态（2026-09-08 / 09）

- Xcode 27 beta（27A5252f），iOS / Simulator 27 SDK；最低部署版本保留 iOS 26。仅在命令中指定 `DEVELOPER_DIR`，未修改全局工具链。
- `swift test --package-path ios`：12 项 XCTest 全部通过，包括符号链接路径限制。
- 正式应用模拟器构建与未签名 iOS 设备构建通过；`Detector.mlmodelc` 与清单进入应用资源，模拟器应用启动成功。
- `check_simulator.py`：独立临时检查应用实际调用生产导入、Core ML、分析、SQLite 复盘、事件及导出代码。合成 H.264 B 帧加音轨视频的 12 帧全部处理，0.4 秒导出保留时长与一条音轨，已确认事件及分析包往返一致。真实转播三秒节选也通过：179 帧与 FFmpeg 一致，2.1 秒片段保留音轨，拒绝未完成、缺少文件及超时长包。修复了时间起点及空编辑段带来的漏帧或多帧。另有姿态点、球拍归属导出保留及 reviewed 统计回归测试。
- 上述集成检查不等于完成系统文件选择器与所有 SwiftUI 按钮的逐项操作验收；该项与真机签名安装、两小时素材、温控、性能及电量仍未验证。

复现模拟器集成检查（需先启动一个模拟器，并安装模型资源）：

```sh
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer python3 ios/check_simulator.py SIMULATOR_UDID
```

脚本使用 FFmpeg 生成合成视频，不需要私人比赛素材；临时检查应用有独立 bundle ID，并在结束后卸载。结果仅说明运行链路正确，不是检测准确率证据。

核心测试覆盖共享 Python fixtures、字段往返、路径穿越/符号链接、v1 迁移、透视校准、SQLite 原子回滚、恢复标识拒绝、连续与恢复跟踪一致、事件修改不改变原始帧、导出和统计。正式验收请执行：

```sh
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test --package-path ios
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcodebuild \
  -project ios/TennisOffline.xcodeproj -scheme TennisOffline \
  -sdk iphoneos -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

以上从仓库根目录运行。真机至少验证横竖屏/旋转视频、可变帧率、无音轨、两小时素材、低存储、暂停及杀进程恢复、后台暂停、热状态、人工修改持久化、片段边界及音画同步。编译成功也不能替代这些验收。
