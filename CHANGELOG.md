# Changelog

## 1.1.2

- 输出固定为每通道 8 位 PNG，保持 BaseColor 的 sRGB 编码，不应用场景曝光或视图变换。
- 法线和 ORM 保持数据通道数值。

## 1.1.1

- Metallic 缺图时可设置 0–1 默认值，初始为 0。
- 精简设置面板说明。

## 1.1.0

- 通用源模型、目标模型和 UV 选择。
- BaseColor、AO、Roughness、Metallic 独立选择输入图像及 R/G/B/A/RGB 通道。
- RGB 数据图按亮度转灰度，法线使用完整 RGB。
- 修复中文翻译节点名称导致预览创建失败的问题。
- 支持从已有输出目录恢复预览，无需再次烘焙。
- 提供投射覆盖率报告、DirectX/OpenGL 法线和固定 ORM 输出。
