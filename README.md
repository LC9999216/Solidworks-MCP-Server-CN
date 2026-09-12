# 🧩 SolidWorks MCP Server 中文适配版

让 Claude、Codex、ChatGPT Desktop 等 AI 编码助手通过 MCP 直接调用 SolidWorks，完成草图、三维特征、装配、检查与导出。🤖📐

本项目基于 [HarrierPigeon/Solidworks-MCP-Server](https://github.com/HarrierPigeon/Solidworks-MCP-Server) 修改，保留原项目的 MIT 许可证。

## ✨ 中文版适配

- ✅ 识别英文和中文标准基准面名称；名称不可用时，按特征树顺序回退识别。
- ✅ 创建草图尺寸时通过 SolidWorks API 临时关闭尺寸输入对话框，不依赖英文界面的 `Modify` 窗口；结束后恢复原有设置。
- ✅ 重新打开零件后，可经 SolidWorks COM 直接读取草图内的直线、圆和圆弧，不依赖 MCP 会话缓存。
- ✅ 已在中文版 SolidWorks 2024 验证草图尺寸创建、原生零件重新打开和草图实体读取。

## 🚀 快速使用

把下面这句话交给其他编码 Agent，它就能下载本仓库、注册 `solidworks` MCP，并通过该 MCP 操作本机 SolidWorks。🤝

> 🤖 请在 Windows 上安装并配置中文版 SolidWorks MCP：运行 `powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/LC9999216/Solidworks-MCP-Server-CN/main/scripts/install.ps1 | iex"`，完成后重启编码客户端；启动 SolidWorks 后，即可使用 `solidworks_*` 工具创建和编辑三维模型。🛠️✅

也可以直接在 PowerShell 中运行一键安装命令：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/LC9999216/Solidworks-MCP-Server-CN/main/scripts/install.ps1 | iex"
```

### 手动安装 🛠️

前置条件：

- Windows 10/11 🪟
- 已安装并激活 SolidWorks 2022 或更高版本
- Python 3.10+ 🐍
- Git（或下载 ZIP）
- Codex、Claude Desktop 或 ChatGPT Desktop 🤖

```powershell
git clone https://github.com/LC9999216/Solidworks-MCP-Server-CN.git
cd Solidworks-MCP-Server-CN
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 注册到 Codex / ChatGPT Desktop ⚙️

```powershell
codex mcp add solidworks -- "C:\path\to\Solidworks-MCP-Server-CN\.venv\Scripts\python.exe" "C:\path\to\Solidworks-MCP-Server-CN\server.py"
```

随后完全重启客户端，先启动 SolidWorks，再让 Agent 执行：

```text
在 SolidWorks 中创建一个 50 mm 立方体，并返回等轴测视图截图。
```

### 注册到 Claude Desktop ⚙️

在 `%APPDATA%\Claude\claude_desktop_config.json` 中加入：

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "C:\\path\\to\\Solidworks-MCP-Server-CN\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Solidworks-MCP-Server-CN\\server.py"]
    }
  }
}
```

> 💡 如果 SolidWorks 以管理员身份运行，Claude 或 Codex 也必须以管理员身份运行；COM 无法跨越权限边界。

## 🧰 能做什么？

| 类别 | 能力 |
|---|---|
| ✏️ 草图 | 直线、圆、圆弧、样条、椭圆、多边形、槽、文字、尺寸、几何约束、偏移和圆角 |
| 🧱 三维特征 | 拉伸、切除、旋转、扫描、放样、边界、圆角、倒角、抽壳、拔模、筋和包覆 |
| 🔁 阵列与孔 | 线性阵列、圆周阵列、镜像、孔向导和装饰螺纹 |
| 📐 参数化 | 尺寸参数、方程式、配置和配置专属尺寸 |
| 🔍 模型检查 | 面、边、顶点、包围盒、质量属性、模型截图和状态查询 |
| 🗂️ 文档与导出 | 保存、打开、STEP / IGES / Parasolid / ACIS / STL 导入与导出、PNG 视图 |
| 🧩 装配 | 插入零件、配合、干涉检查、组件管理和装配质量属性 |
| 🌳 特征树 | 查询、重命名、分组和整理特征树 |

## 🧪 给 Agent 的提示示例

提供明确尺寸会得到更可靠的结果。📏

```text
创建一个 100 mm × 60 mm × 6 mm 的底板，四角各开一个直径 6 mm 的通孔。
```

```text
建立一个 L 形支架：底板 80 × 50 × 6 mm，长边处拉伸 40 mm 高的竖板；连接处倒 R5，底板开四个 Ø6 通孔。
```

```text
创建一个两零件装配：一块带 Ø20 孔的板和一根 Ø20 销轴；保存零件后，将销轴与孔做同心配合。
```

```text
请读取当前零件的质量属性、特征树和等轴测视图，检查是否只有一个实体且没有明显错误。
```

## 🧩 MCP 工具速览

所有工具均以 `solidworks_` 开头；长度单位是 **毫米**，角度单位是 **度**。内部会自动转换为 SolidWorks COM API 所需的米和弧度。

<details>
<summary><strong>✏️ 草图</strong></summary>

| 工具 | 作用 |
|---|---|
| `create_sketch` / `exit_sketch` | 在基准面或实体面上创建、退出草图 |
| `sketch_line` / `sketch_centerline` / `sketch_arc` | 直线、中心线和圆弧 |
| `sketch_rectangle` / `sketch_circle` / `sketch_ellipse` | 矩形、圆和椭圆 |
| `sketch_spline` / `sketch_polygon` / `sketch_slot` | 样条、多边形和直槽 |
| `sketch_profile` | 一次创建连续封闭轮廓，支持直线和圆弧 |
| `sketch_point` / `sketch_text` | 参考点和草图文字 |
| `sketch_fillet` / `sketch_offset` | 草图圆角和偏移 |
| `sketch_dimension` / `set_dimension_value` | 新建和修改驱动尺寸 |
| `sketch_constraint` / `sketch_toggle_construction` | 几何约束与构造几何 |
</details>

<details>
<summary><strong>🧱 零件与特征</strong></summary>

| 工具 | 作用 |
|---|---|
| `new_part` / `create_extrusion` / `create_cut_extrusion` | 新建零件、拉伸和切除拉伸 |
| `revolve` / `cut_revolve` | 旋转与旋转切除 |
| `sweep` / `cut_sweep` | 扫描与扫描切除 |
| `loft` / `cut_loft` / `boundary_boss` / `boundary_cut` | 放样和边界特征 |
| `fillet` / `chamfer` / `shell` / `draft` / `rib` / `wrap` | 圆角、倒角、抽壳、拔模、筋和包覆 |
| `combine_bodies` / `intersect` | 多实体布尔运算 |
| `set_material` / `get_mass_properties` | 材料与质量属性 |
| `set_parameter` / `list_parameters` | 参数化尺寸读取和修改 |
| `suppress_feature` / `delete_feature` / `list_features` | 特征管理 |
</details>

<details>
<summary><strong>🔁 阵列、孔和基准</strong></summary>

| 工具 | 作用 |
|---|---|
| `linear_pattern` / `circular_pattern` / `mirror` | 线性阵列、圆周阵列和镜像 |
| `hole_wizard` / `thread` | 孔向导与装饰螺纹 |
| `ref_plane` / `ref_axis` / `ref_point` | 基准面、基准轴和基准点 |
| `coordinate_system` | 创建坐标系 |
</details>

<details>
<summary><strong>🔍 模型查看与状态</strong></summary>

| 工具 | 作用 |
|---|---|
| `get_body_info` / `get_faces` / `get_edges` / `get_vertices` | 读取实体、面、边和顶点信息 |
| `get_face_edges` / `find_face` | 通过坐标或描述定位面与边 |
| `look_at_model` / `capture_views` | 对话内截图和导出标准视图 PNG |
| `get_state` / `get_entity` / `get_sketch_entities` | 查询会话、实体和草图数据 |
</details>

<details>
<summary><strong>🗂️ 文档、装配与设计树</strong></summary>

| 工具 | 作用 |
|---|---|
| `save_document` / `open_document` / `activate_document` / `close_document` / `list_documents` | 文档保存和多文档管理 |
| `import_file` / `recognize_features` | 中性格式导入和 FeatureWorks 特征识别 |
| `new_assembly` / `insert_component` | 新建装配和插入零件 |
| `add_mate` / `edit_mate` / `check_interference` | 配合编辑与干涉检查 |
| `suppress_component` / `list_components` / `list_mates` | 装配组件与配合管理 |
| `get_feature_tree` / `rename_feature` / `create_feature_folder` / `move_to_folder` | 特征树查询、命名和分组 |
</details>

<details>
<summary><strong>⚙️ 配置、方程与批处理</strong></summary>

| 工具 | 作用 |
|---|---|
| `add_configuration` / `switch_configuration` / `list_configurations` | 配置管理 |
| `set_config_parameter` | 配置专属尺寸 |
| `add_equation` / `list_equations` / `delete_equation` | 尺寸方程式 |
| `batch` | 单次执行最多 25 个彼此独立的 MCP 调用 |
</details>

## 🔗 工作原理

```text
编码 Agent  →  MCP 调用  →  server.py  →  solidworks/ 模块  →  SolidWorks COM API
```

- 服务器通过 `pywin32` 连接已启动的 SolidWorks，必要时可启动新实例。
- 每个创建对象都有稳定 ID，例如 `feat:Boss-Extrude1`、`sketch:Sketch1`、`comp:bracket-1`，方便 Agent 跨多零件和装配持续引用。
- 工具返回结构化 JSON；几何查询返回的坐标可直接用于圆角、草图和选择类工具。

## 🩺 常见问题

### Agent 无法连接 SolidWorks

- 确认 SolidWorks 已安装并激活；建议先启动 SolidWorks，再启动编码客户端。
- 若 SolidWorks 以管理员身份运行，客户端也须以管理员身份运行。

### MCP 没有出现在客户端中

- 完全退出并重启 Claude、Codex 或 ChatGPT Desktop。
- 检查注册命令中的 Python 路径和 `server.py` 路径。
- Claude Desktop 请检查 `%APPDATA%\Claude\claude_desktop_config.json` 是否为合法 JSON。

### 提示找不到零件模板

默认从 `C:\ProgramData\SOLIDWORKS\SOLIDWORKS <year>\templates\` 查找模板。若模板在其他位置，请调整 `solidworks/connection.py` 中的查找路径。

### 孔向导卡住或报错

部分环境会弹出阻塞式对话框。可让 Agent 改用“草图圆 + 切除拉伸”创建孔。🕳️

### 其他问题

检查 `server.py` 同目录下的 `solidworks_mcp.log`，并在本仓库提交 Issue。🐛

## 👩‍💻 开发与测试

```powershell
python test.py            # 完整测试，需要正在运行的 SolidWorks
python test.py --list     # 查看可运行测试
python dev_server.py      # 热重载开发服务器，需要 watchdog
python clean.py           # 关闭打开的 SolidWorks 文档
python -m unittest tests.test_state_query_live_sketch -v
```

COM 层没有完整模拟器，部分测试会驱动真实 SolidWorks。`tests/agent_capability_tests.md` 还提供了可直接交给 Agent 的端到端提示词。

欢迎提交 Issue 和 PR！🌟

## ⚠️ 已知限制

- 尚未实现二维工程图自动生成。
- `hole_wizard` 在部分安装环境可能触发阻塞对话框。
- 设计树文件夹不能嵌套；将特征加入文件夹通常需要在创建文件夹时一次性指定完整特征列表。
- `recognize_features` 只能部分恢复导入模型的参数化特征树，适合作为起点，不能代替完整重建。
- 尚未实现 WIDTH 配合，也未集成 PDM、PDM Pro 或 3DExperience。

## 📄 许可证

[MIT](LICENSE)

---

> ⚖️ 本项目与 Dassault Systèmes SolidWorks Corporation 无关联，也未获其认可。SolidWorks 是 Dassault Systèmes 的注册商标。请在制造或正式使用前复核生成的几何模型。🥤 长时间建模请记得喝水并调整坐姿。
