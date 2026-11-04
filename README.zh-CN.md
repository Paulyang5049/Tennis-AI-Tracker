<p align="center">
  <img src="docs/images/hero.svg" alt="Tennis AI Local：你的比赛，你的回忆，留在你的设备上。" width="100%">
</p>

<h3 align="center">在自己的 Mac 或 iPhone 上离线分析网球视频。<br>跟踪球、球员和场地，然后逐拍复盘。</h3>

<p align="center"><a href="README.md">English</a> · <b>简体中文</b></p>

---

## 为什么用它

- **视频不离开你的设备。** 首次下载模型之后，分析全部在本机完成（Apple Silicon、CPU 或 CUDA）。不需要账号，不上传，没有服务器。
- **面向真实比赛。** 单打或双打，固定机位的全场手机录像或转播片段。
- **结论可以核对。** 自动检测结果一律标为"候选"。只有你确认过的事件才进入统计，每个数字都能回到对应的画面。
- **全部开源。** 模型、训练 Notebook、数据格式和验证结果都在这个仓库里。

## 现在能做什么

| 功能 | 状态 |
|---|---|
| 球员检测、跟踪和身体姿态（单打、双打） | ✅ 可用。长时间遮挡后 ID 仍可能切换 |
| 球的检测与轨迹 | ✅ 可用。远端小球仍有难度，可试用多帧 TrackNet 模型（`--ball-model tracknet-v2`） |
| 场地关键点与小地图 | ✅ 可用，模型失败时可手动点四个角校准 |
| 同步回放、逐帧复盘、带声音导出片段 | ✅ 可用 |
| 长视频暂停与续跑；分析文件夹可整体搬移 | ✅ 可用 |
| 击球、落地、回合候选 | 🧪 实验中。确认后才计入统计；可试 `--event-detector contact-v2` |
| 击球类型（发球、正手、反手、截击、高压）与旋转（上旋、切削、平击） | ✍️ 手动标注；🧪 可选切削/上旋候选 `--spin-detector wrist-v1` |
| 原生 iPhone App（SwiftUI、AVFoundation、Core ML） | 🧪 需从源码构建的开发版，未上架 App Store |
| 手机实拍素材上的准确率 | 🔜 需要带标注的比赛。[欢迎参与](#参与) |

## 快速开始（macOS）

```sh
git clone https://github.com/Paulyang5049/Tennis-AI-Tracker.git
cd Tennis-AI-Tracker
brew install ffmpeg uv
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/tennis-ai setup   # 首次下载模型
.venv/bin/tennis-ai app     # 打开 http://127.0.0.1:7860
```

上传视频，选择单打或双打，点击 **Analyze video**。也可以用命令行：

```sh
.venv/bin/tennis-ai analyze my-match.mp4 --output outputs/my-match
```

更多：[使用指南（英文）](docs/USAGE.md) · [iPhone 构建说明](ios/README.md) · [在 Colab 训练球检测模型](notebooks/01_train_ball_yolo26.ipynb)

## 工作原理

1. **检测**：YOLO26 逐帧找出球员、球拍和球，姿态模型补充身体关键点。
2. **跟踪**：ByteTrack 保持球员身份，时间门控挑出唯一的球；只在相邻观测之间补短缺口。
3. **场地映射**：热图模型找到 14 个场地关键点并拟合几何，把位置画到小地图上。
4. **复盘**：击球、落地和回合候选对齐到视频上。由你确认、修改或排除，只有确认过的事实进入统计。

## 参与

- **会打网球**：描述清楚的失败案例就很有价值，不需要写代码。提交录像须征得画面中所有可识别人员的同意，请用 [录像提交表](https://github.com/Paulyang5049/Tennis-AI-Tracker/issues/new?template=footage_contribution.yml)。
- **愿意标注**：[标注指南](docs/ANNOTATION.md) 说明球、击球和落地标注如何进入评测。
- **会写代码**：先看 [CONTRIBUTING.md](CONTRIBUTING.md) 和标记为 [good first issue](https://github.com/Paulyang5049/Tennis-AI-Tracker/labels/good%20first%20issue) 的问题。

觉得有用的话，点个 ⭐ 能帮更多球友找到它。

## 许可

本项目采用 [GNU AGPL v3](LICENSE)。下载的模型、数据集和第三方仓库遵循各自条款，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
