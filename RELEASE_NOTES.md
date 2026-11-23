# Texture Rebake 1.3.1

修复 Blender 5.3 中 BaseColor 烘焙过亮的问题。

## 修复内容

原先 sRGB 烘焙目标中的像素已经过颜色编码，导出时又编码了一次，造成输出偏亮。现在中间烘焙图统一保存线性数值，仅在导出 BaseColor 时进行一次 sRGB 编码。Normal、ORM 和诊断图保留数据值，输出仍为每通道 8 位 PNG。

## 下载与安装

下载本 Release 附件中的 **TextureRebake-1.3.1.zip**，无需解压。
Blender → 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择 ZIP 并启用 Texture Rebake。
3D 视图按 N → Rebake。

请使用上述安装附件；GitHub 自动生成的 Source code 压缩包是开发源码，不是插件安装包。
更新前保存工作，先移除旧插件，再安装 ZIP 并重启 Blender。

此前已导出且偏亮的 BaseColor 需要重新烘焙；在 UE 中重新导入新贴图。从旧结果文件夹恢复预览不会修复旧贴图。

## 兼容性与验证

- Blender 5.3.0 / Cycles CPU 完整功能回归通过，覆盖法线、ORM、预览、Cage、投射诊断及场景清理。
- 使用独立 PNG 解码检查实际文件像素，0–255 全灰阶通过 Cycles 和旋转 UV 后误差不超过 1 个 8 位码值。
- 验证 Standard / AgX、场景曝光和 Gamma 不影响导出颜色。
- 最低声明 Blender 4.2，本次未重新测试旧版本。
- 不需额外安装 Python 依赖，使用 Blender 自带 NumPy。

## 发布附件

- `TextureRebake-1.3.1.zip`
- `TextureRebake-1.3.1.zip.sha256`
