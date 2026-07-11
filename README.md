# BookReader - TTS 读书应用

基于 Flet 的跨平台电子书阅读器，支持 TTS 语音朗读、句子高亮、自动翻页等功能。

## ✨ 功能特点

### 📚 核心功能
- **多格式支持**：TXT、EPUB、PDF 格式
- **TTS 语音朗读**：离线 TTS 引擎，支持停止/继续
- **句子高亮**：朗读时当前句子显示灰色背景
- **自动翻页**：朗读到页尾自动翻到下一页
- **位置记忆**：关闭书籍时保存阅读位置，下次从此继续

### 🎨 用户体验
- 现代化 UI 设计
- 实时日志窗口（支持多行选择）
- 书籍信息本地持久化
- 响应式布局（根据窗口大小调整字体）

### 🖥️ 平台支持
- ✅ Windows（桌面模式）
- ✅ macOS（桌面模式）
- ✅ Linux（桌面模式）
- 🚧 Web（浏览器模式，部分功能受限）

## 📦 安装和运行

### 前置条件
1. 安装 Python 3.8+
2. 安装依赖：`pip install -r requirements.txt`

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/idea2realClaw/BookReader.git
cd BookReader

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行应用（桌面模式）
python main.py --mode desktop
```

## 🚀 使用说明

1. **添加书籍**：点击左上角文件夹图标，选择 TXT/EPUB/PDF 文件
2. **打开书籍**：点击书籍卡片
3. **TTS 朗读**：点击播放按钮 ▶️ 开始朗读
4. **停止朗读**：点击停止按钮 ⏹️
5. **翻页**：使用左右箭头按钮或键盘
6. **跳转页面**：点击菜单按钮，输入页码

## 📁 项目结构

```
BookReader/
├── main.py              # 应用入口
├── ui/                  # UI 组件
│   ├── bookshelf.py     # 书架界面
│   ├── book_viewer.py   # 阅读器界面
│   └── log_window.py    # 日志窗口
├── reader/              # 阅读器核心逻辑
│   ├── base.py         # 基类
│   ├── txt_reader.py   # TXT 格式
│   ├── epub_reader.py  # EPUB 格式
│   └── pdf_reader.py   # PDF 格式
├── assets/              # 资源文件
└── requirements.txt     # Python 依赖
```

## 🛠️ 技术栈

- **框架**：Flet 0.85.3
- **语言**：Python 3.10+
- **TTS 引擎（Edge TTS 统一后端，可打包）**：
  - 合成：所有平台统一使用 Edge TTS（微软在线语音，免费、支持中文男/女声、可调倍速、中国大陆可用）。
    由 `ui/edge_tts_lite` 提供——仅依赖 `websockets`+`certifi`（纯 Python，Flet 安卓打包环境可安装），
    完整复刻 edge_tts 协议，故安卓端也能用男/女声 + 倍速，无需 pyjnius、无需第三方 APK。
  - 桌面端：pygame 应用内播放（不调用外部播放器）；移动端（Android）：合成 mp3 经本地 HTTP 服务交给系统播放器。
  - 容错：Edge 合成失败（无网络等）时移动端自动回退 gTTS。
  - 注：官方 `edge_tts` 包（依赖安卓缺失的 `multidict`/`frozenlist` wheel）与 `pygame` 不列入 requirements，避免 `flet build apk` 失败；桌面端 `flet run` 时可本地 `pip install pygame`。
- **文件解析**：
  - EPUB：zipfile + html.parser（标准库）
  - PDF：pdfplumber
  - TXT：直接读取

## 📝 开发计划

- [x] 支持 EPUB 文件导入
- [x] TTS 语音朗读
- [x] 句子级高亮追踪
- [x] 自动翻页
- [x] 阅读位置保存/加载
- [ ] 添加书签和笔记功能
- [ ] 支持更多 TTS 引擎
- [ ] 实现跨设备同步

## 🐛 已知问题

- Web 模式下 TTS 功能受限（需要使用 Web Speech API）
- EPUB 格式支持基本可用，但复杂排版可能有问题

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 👤 作者

**idea2realClaw**

GitHub: [@idea2realClaw](https://github.com/idea2realClaw)
