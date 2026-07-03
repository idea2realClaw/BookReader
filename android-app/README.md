# BookReader - 原生 Android 版本

这是一个使用原生 Android (Kotlin) 开发的电子书阅读器，相比 Flet 版本，APK 体积更小。

## 功能特性

- 📄 支持 PDF、EPUB、TXT 格式
- 📚 简洁的书架界面
- 🎨 Material Design 3 风格
- 🚀 轻量级，APK 体积小（预计 < 10MB）

## 项目结构

```
android-app/
├── app/
│   ├── build.gradle          # 应用级 Gradle 配置
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/bookreader/
│       │   ├── MainActivity.kt      # 书架界面
│       │   ├── ReaderActivity.kt   # 阅读界面
│       │   └── BookAdapter.kt      # 书籍列表适配器
│       └── res/
│           ├── layout/
│           │   ├── activity_main.xml
│           │   ├── activity_reader.xml
│           │   └── item_book.xml
│           └── values/
│               ├── strings.xml
│               ├── colors.xml
│               └── styles.xml
```

## 构建步骤

1. 使用 Android Studio 打开 `android-app` 目录
2. 等待 Gradle 同步完成
3. 连接 Android 设备或启动模拟器
4. 点击运行按钮或使用 `./gradlew assembleDebug`

## 依赖库

- **PDF 阅读**: `android-pdf-viewer`
- **EPUB 阅读**: `epub4j`
- **UI**: Material Design Components

## 已知问题

- [ ] EPUB 阅读功能尚未实现
- [ ] 需要添加图标资源（ic_add, ic_back, ic_prev, ic_next）
- [ ] ViewBinding 需要完善
- [ ] 需要添加持久化存储（SharedPreferences）
- [ ] TTS 朗读功能待实现

## 对比 Flet 版本

| 特性 | Flet 版本 | 原生 Android 版本 |
|------|----------|------------------|
| APK 大小 | ~50MB+ | 预计 < 10MB |
| 性能 | 中等 | 优秀 |
| 开发速度 | 快 | 中等 |
| 原生功能 | 受限 | 完全访问 |

## 下一步

- [ ] 实现 EPUB 解析和阅读
- [ ] 添加书签功能
- [ ] 实现阅读进度保存
- [ ] 添加 TTS 朗读
- [ ] 优化 UI/UX
- [ ] 添加夜间模式

## 许可证

MIT License
