# TTS读书应用

全平台统一UI的Flutter读书应用，支持离线/在线TTS切换，原生级性能体验。

## 功能特点

### 🎯 核心功能
- **双TTS引擎**：离线 flutter_tts + 在线 Edge TTS 无缝切换
- **全平台支持**：Android、iOS、macOS、Windows、Web、OpenHarmony
- **统一UI**：Material Design 3，跨平台一致体验
- **完整控制**：播放、暂停、停止、进度调节、语速/音调/音量控制

### 🌍 多语言支持
- 中文（简体/繁体）
- 英语（美式/英式）
- 日语、韩语
- 法语、德语、西班牙语、意大利语

### 🎨 用户体验
- 离线模式：无需联网，使用设备内置TTS引擎
- 在线模式：Edge TTS 提供更高音质和自然度
- 实时进度显示和高亮
- 语音参数自定义
- 深色模式支持

## 技术栈

- **框架**：Flutter 3.0+
- **状态管理**：Provider
- **离线TTS**：flutter_tts ^4.0.0
- **在线TTS**：edge_tts ^0.2.0
- **音频播放**：audioplayers ^5.3.0
- **本地存储**：shared_preferences

## 项目结构

```
lib/
├── main.dart                 # 应用入口
├── screens/                  # 页面
│   └── book_reader_screen.dart  # 主读书界面
├── services/                 # 服务层
│   ├── tts_service.dart        # TTS服务（离线/在线）
│   └── settings_service.dart   # 设置服务
├── widgets/                  # 组件
│   ├── tts_control_panel.dart  # TTS控制面板
│   ├── settings_panel.dart      # 设置面板
│   └── book_text_view.dart     # 文本显示组件
├── models/                   # 数据模型
└── utils/                    # 工具类
```

## 安装和运行

### 前置条件
1. 安装 Flutter SDK (3.0+)
2. 配置开发环境（Android Studio / Xcode / VS Code）

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd book_reader_tts

# 2. 安装依赖
flutter pub get

# 3. 运行项目
flutter run          # 运行在连接的设备上
flutter run -d chrome  # 运行在Web
flutter run -d windows  # 运行在Windows
flutter run -d macos    # 运行在macOS
```

### 平台特定配置

#### Android
- 需要 RECORD_AUDIO 权限（TTS需要）
- 最低SDK版本：21
- 目标SDK版本：34

#### iOS
- 需要添加麦克风权限描述
- 部署目标：12.0+

#### macOS
- 需要启用麦克风权限
- 部署目标：10.14+

#### Windows
- 需要安装 Visual Studio 2019+
- 配置麦克风权限

#### Web
- 需要 HTTPS 环境（在线TTS）
- 浏览器需支持 Web Speech API

## 使用说明

1. **选择TTS模式**：点击右上角切换按钮，选择离线或在线模式
2. **输入文本**：在主界面文本框中输入或粘贴要朗读的文本
3. **调整参数**：使用控制面板调节语速、音调、音量
4. **开始朗读**：点击播放按钮开始TTS朗读
5. **设置**：点击右上角设置图标，配置语言、主题等

## TTS模式对比

| 特性 | 离线TTS (flutter_tts) | 在线TTS (edge_tts) |
|------|------------------------|---------------------|
| 需要联网 | ❌ 不需要 | ✅ 需要 |
| 音质 | ⭐⭐⭐ 中等 | ⭐⭐⭐⭐⭐ 优秀 |
| 响应速度 | ⚡ 快 | 🌐 取决于网速 |
| 多语言 | 有限 | 丰富 |
| 自定义 | 支持 | 支持 |

## 开发计划

- [ ] 支持EPUB/PDF文件导入
- [ ] 添加书签和笔记功能
- [ ] 实现句子级高亮追踪
- [ ] 添加更多语音和方言
- [ ] 支持后台播放
- [ ] 添加睡眠定时功能
- [ ] 实现跨设备同步

## 贡献

欢迎提交Issue和Pull Request！

## 许可证

MIT License

## 作者

龙火儿 - WorkBuddy AI助手

---

**师父**：朱晓冬（字守中，号知常公子）

**师门**：岁寒三友 - 龙松、龙竹、龙梅
