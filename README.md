# BookReader

一个基于 [Flet](https://flet.dev/) 构建的跨平台电子书阅读器，支持打开本地 `.txt`、`.epub`、`.pdf` 书籍，并带有仿真 3D 翻页效果。

## 功能

- 书架式管理，通过系统文件选择器添加书籍。
- 支持 TXT / EPUB / PDF 三种格式（均为纯 Python 解析，便于打包到 Android）。
- 阅读界面点击右侧翻下一页、点击左侧翻回上一页。
- 3D 透视翻页动画（Y 轴旋转 + 动态阴影）。
- 顶部跳转页码、返回书架。

## 项目结构

```
BookReader/
├── main.py              # 应用入口
├── requirements.txt     # 依赖
├── reader/              # 书籍解析器
│   ├── base.py
│   ├── txt_reader.py
│   ├── epub_reader.py   # 纯标准库实现
│   └── pdf_reader.py    # 基于 pypdf 纯 Python
├── ui/                  # Flet UI
│   ├── bookshelf.py
│   └── book_viewer.py   # 阅读器 + 翻页动画
├── assets/              # 示例书籍
│   ├── sample.txt
│   ├── sample.pdf
│   └── sample.epub
└── smoke_test.py        # 解析器与 UI 构造测试
```

## 本地运行

### Windows (PowerShell)

```powershell
cd D:\DiskD\GitHub\BookReader
.venv\Scripts\python.exe main.py
```

或使用启动脚本：

```powershell
cd D:\DiskD\GitHub\BookReader
.\run.bat
```

### Linux/Mac

```bash
cd /path/to/BookReader
.venv/bin/python main.py
```

### 手动安装依赖

如果 .venv 不存在，先创建虚拟环境：

```bash
cd D:\DiskD\GitHub\BookReader
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 运行测试

```bash
.venv\Scripts\python.exe smoke_test.py
```

## 打包 Android APK（需要 Android 环境）

1. 安装 Flutter SDK、Android SDK / NDK、Java。
2. 确保 `flet-cli` 已安装：

```bash
.venv\Scripts\python.exe -m pip install flet-cli
```

3. 构建 APK：

```bash
.venv\Scripts\flet.exe build apk --project BookReader --product BookReader --org com.example
```

4. 输出位于 `build/apk/`。

## 依赖说明

- `flet`：跨平台 UI 框架。
- `pypdf`：纯 Python PDF 解析器，无需原生扩展，Android 打包友好。
- EPUB 与 TXT 使用 Python 标准库解析。

## 注意事项

- 首次在桌面运行时，文件选择器会弹出系统对话框。
- 在 Android 上，文件选择器会调用系统 SAF / 文件选择器。
- 翻页动画使用 Flet 的 `Transform` + `Matrix4` 实现 3D 透视旋转。
