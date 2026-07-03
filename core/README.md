# 共享架构配置

## Python 核心逻辑

核心逻辑位于 `core/src/`，可被以下平台调用：
- Flet (Python)
- Chaquopy (Android)

### 安装依赖
```bash
pip install -r requirements.txt
```

## Android 集成 (Chaquopy)

### 1. 配置 build.gradle
```gradle
plugins {
    id 'com.android.application'
    id 'com.chaquo.python'  // 添加这一行
}

android {
    defaultConfig {
        python {
            buildPython "python3"
            pip {
                install "pypdf"
            }
        }
    }
}

dependencies {
    implementation 'com.chaquo.python:gradle:15.0.1'
}
```

### 2. 在 Kotlin 中调用 Python
```kotlin
import com.chaquo.python.Python

// 初始化 Python
val py = Python.getInstance()

// 调用核心逻辑
val core = py.getModule("core.src")
val parser = core.callAttr("create_parser", filePath)
val book = parser.callAttr("parse", filePath)
```

## 目录结构

```
core/
├── src/
│   ├── __init__.py       # 导出核心类
│   ├── models.py         # 数据模型
│   ├── parsers.py        # 解析器
│   └── repository.py     # 仓库
└── requirements.txt      # Python 依赖
```

## 同步逻辑

当修改 `core/src/` 时，需确保：
1. Python 版本和 Kotlin 版本的数据模型一致
2. 方法签名对齐
3. 添加单元测试验证行为一致
