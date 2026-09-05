# Sources and local asset provenance

This implementation is new application code. It does not bundle upstream repository source, model weights, sample media or datasets in the wheel.

- Ultralytics YOLO26: https://github.com/ultralytics/ultralytics and https://docs.ultralytics.com/models/yolo26 . Installed dependency: 8.4.140. Its published licensing options are AGPL-3.0 and Enterprise. Confirm the appropriate terms before distributing a product built with it.
- TennisCourtDetector: https://github.com/yastrebksv/TennisCourtDetector . Pinned revision `e5cd4f1ce26b15361700d3d89e068cbf0e82749e`. The upstream architecture and checkpoint are fetched to ignored local paths. No root LICENSE was found in the inspected tree. Do not infer redistribution permission from public GitHub visibility.
- Tennis analysis reference: https://github.com/abdullahtarek/tennis_analysis . Pinned revision `d557527793820f1e6b06872256824255facd47fd`. Used as workflow/data reference, not vendored application code. No root LICENSE was found in the inspected tree.
- Ball data: https://universe.roboflow.com/viren-dhanwani/tennis-ball-detection/dataset/6 . The repository's dataset metadata states CC BY 4.0 and 578 images. `prepare_ball` retains the original README attribution alongside the derived split.
- Court data: https://drive.google.com/file/d/1lhAaeQCmk2y440PmagA0KmIVBIysVMwu/view . Dataset/license terms should be checked before redistribution; the notebook downloads it for local experimentation.
- Product inspiration: https://xhslink.cn/o/7iCfOhBAnji . No UI assets or model code from the post are copied.

`models/provenance.json` records the actual downloaded asset checksums. The local demonstration clip comes from the referenced tennis-analysis repository and remains ignored under `data/`; it is not part of the distributable wheel. No commercial clearance is represented by this demo.
