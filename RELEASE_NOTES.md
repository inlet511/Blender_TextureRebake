# Texture Rebake 1.3.0

将旧模型纹理转移到编辑后模型的新 UV，输出 BaseColor、切线空间 Normal、ORM 及投射诊断图。

## 本版内容

- 可直接安装的 Blender ZIP 插件包，包含使用说明和更新记录。
- Cage 实时视口预览：线框、半透明表面、颜色与透明度调整，不创建场景对象。
- 自动 Cage 投射及独立 Coverage / Misses 检查，可在完整烘焙前定位漏投区域。
- 可重复构建的打包脚本，以及 SHA-256 校验文件。

## 下载与安装

下载本 Release 附件中的 **TextureRebake-1.3.0.zip**，无需解压。
Blender → 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择 ZIP 并启用 Texture Rebake。
3D 视图按 N → Rebake。

请使用上述安装附件；GitHub 自动生成的 Source code 压缩包是开发源码，不是插件安装包。
若已安装单文件旧版，先移除旧版，再安装 ZIP 并重启 Blender。

## 兼容性与验证

- 最低声明版本 Blender 4.2；既有功能验证记录为 Blender 5.1.0 / Cycles CPU。
- 本次在 Blender 5.3.0 验证 ZIP 安装、启用、反复禁用与启用、卸载通过。
- 已知问题：现有烘焙源码在 Blender 5.3.0 的 BaseColor sRGB 往返回归失败，输出偏亮，尚未完成该版本的烘焙兼容性验证。本次打包未修改烘焙算法。
- 不需额外安装 Python 依赖，使用 Blender 自带 NumPy。

## 发布附件

- `TextureRebake-1.3.0.zip`
- `TextureRebake-1.3.0.zip.sha256`
