# BookReader - 共享架构版本

这个分支尝试用**一套核心代码**维护 Flet (Python) 和原生 Android (Kotlin) 两个平台。

## 🏗️ 架构设计

```
BookReader/
├── core/                      # 共享核心逻辑 (Python)
│   └── src/
│       └── __init__.py       # BookParser, BookRepository 等
│
├── platforms/
│   ├── flet_app/             # Flet UI (Python)
│   │   └── main.py          # 调用 core 逻辑
│   │
│   └── android_app/         # 原生 Android (Kotlin)
│       └── app/src/main/java/com/bookreader/core/
│           ├── Models.kt     # 数据模型 (与 Python 对应)
│           └── BookParser.kt # 解析器 (与 Python 对应)
│
└── README.md
```

## 🎯 设计原则

### 1. 核心逻辑共享
- **Python 版本** (`core/src/`): 纯逻辑，无 UI 依赖
- **Kotlin 版本** (`platforms/android_app/.../core/`): 相同逻辑的 Kotlin 实现

### 2. 数据模型对齐
| Python (core) | Kotlin (Android) |
|---------------|------------------|
| `Book` dataclass | `Book` data class |
| `Page` dataclass | `Page` data class |
| `BookParser` ABC | `BookParser` interface |

### 3. 平台适配层
每个平台有自己的 UI 层，但调用相同的核心逻辑：
- **Flet**: `platforms/flet_app/main.py`
- **Android**: `platforms/android_app/.../MainActivity.kt`

## 📦 依赖关系

```
┌─────────────────┐          ┌─────────────────┐
│   Flet UI       │          │  Android UI     │
│  (Python)       │          │  (Kotlin)       │
└────────┬────────┘          └────────┬────────┘
         │                            │
         │ 调用                       │ 调用
         ▼                            ▼
┌─────────────────────────────────────────────┐
│          核心逻辑层 (Core Layer)            │
│  - BookParser (TXT/EPUB/PDF)              │
│  - BookRepository (书籍管理)               │
│  - 分页算法                                 │
│  - 阅读进度管理                             │
└─────────────────────────────────────────────┘
```

## 🚀 使用方法

### Flet 版本
```bash
cd platforms/flet_app
python main.py
```

### Android 版本
1. 使用 Android Studio 打开 `platforms/android_app`
2. 同步 Gradle
3. 运行应用

## ⚠️ 当前状态

这是一个**概念验证 (POC)** 分支，展示如何共享核心逻辑。

### ✅ 已完成
- [x] Python 核心逻辑层 (`core/src/`)
- [x] Flet UI 调用核心逻辑
- [x] Kotlin 核心逻辑层 (数据模型 + TXT 解析器)

### 🚧 进行中
- [ ] 完善 Kotlin 版本的 PDF/EPUB 解析器
- [ ] 实现 Android UI 调用 Kotlin 核心逻辑
- [ ] 添加单元测试确保两个版本行为一致

### 💡 未来改进方向

#### 方案 A: 代码生成
使用工具从 Python 类型注解自动生成 Kotlin 代码：
```bash
# 伪代码
python generate_kotlin.py core/src/__init__.py > Models.kt
```

#### 方案 B: Chaquopy (推荐)
在 Android 中直接调用 Python 代码：
```kotlin
// build.gradle
implementation 'com.chaquo.python:gradle:15.0.1'

// MainActivity.kt
val py = Python.getInstance()
val core = py.getModule("core.src")
val book = core.callAttr("create_parser", filePath)
```

这样只需维护 Python 核心逻辑，Android 通过 Chaquopy 直接调用！

## 📊 对比

| 方案 | 代码重复 | 维护成本 | 性能 | 推荐度 |
|------|---------|---------|------|--------|
| 当前 (双实现) | 高 | 高 | 高 | ⭐⭐ |
| Chaquopy | 无 | 低 | 中 | ⭐⭐⭐⭐⭐ |
| 代码生成 | 低 | 中 | 高 | ⭐⭐⭐⭐ |

## 🔗 相关链接

- [Chaquopy - Python SDK for Android](https://chaquo.com/chaquopy/)
- [Main 分支 (Flet 版本)](https://github.com/idea2realClaw/BookReader/tree/main)
- [Native Android 分支](https://github.com/idea2realClaw/BookReader/tree/native-android)

## 许可证

MIT License
