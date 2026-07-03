# BookReader Android (with Chaquopy)

This is the native Android version of BookReader that uses **Chaquopy** to call Python core logic directly.

## 🐍 Chaquopy Integration

Chaquopy allows you to run Python code directly in Android apps. This means:
- ✅ Only ONE codebase to maintain (Python core logic)
- ✅ Android UI calls Python via Chaquopy API
- ✅ No need to rewrite core logic in Kotlin

## 📁 Project Structure

```
android/
├── app/
│   ├── build.gradle              # Chaquopy configuration
│   └── src/main/
│       ├── python/               # Python modules (auto-detected by Chaquopy)
│       │   └── core/
│       │       └── __init__.py   # Copied from ../../core/src/
│       ├── java/com/bookreader/
│       │   ├── MainActivity.kt   # Calls Python via Chaquopy
│       │   └── ReaderActivity.kt
│       └── res/                  # Android layouts
├── build.gradle                  # Top-level with Chaquopy plugin
├── settings.gradle
└── gradle.properties
```

## 🚀 Building and Running

### Prerequisites
1. Android Studio installed
2. Python 3.x installed on your system (for Chaquopy build)
3. ANDROID_HOME environment variable set

### Steps

1. **Open project in Android Studio**
   ```bash
   # Open the android/ directory in Android Studio
   ```

2. **Sync Gradle**
   - Android Studio will automatically download Chaquopy and Python packages
   - Wait for Gradle sync to complete

3. **Run the app**
   - Connect Android device or start emulator
   - Click "Run" button or press Shift+F10

### How Chaquopy Works

#### 1. Initialize Python in MainActivity
```kotlin
if (!Python.isStarted()) {
    Python.start(AndroidPlatform(this))
}
```

#### 2. Call Python functions
```kotlin
val py = Python.getInstance()
val core = py.getModule("core")  // Import core module
val parser = core.callAttr("create_parser", filePath)
val book = parser.callAttr("parse", filePath)
```

#### 3. Access Python objects
```kotlin
val title = book["title"].toString()
val totalPages = book["total_pages"].toInt()
```

## 📦 Dependencies

- **Chaquopy**: `com.chaquo.python:gradle:15.0.1`
- **Python packages**: `pypdf` (installed via Chaquopy pip)

## ⚠️ Important Notes

1. **Python code location**: Chaquopy looks for Python modules in `app/src/main/python/`
2. **Copying core module**: The `core` Python module is copied from `../../core/src/` to `app/src/main/python/core/`
3. **Build Python**: Make sure Python 3 is in your PATH when building

## 🔧 Troubleshooting

### Chaquopy build fails
- Make sure Python 3.x is installed and in PATH
- Check `gradle.properties` for correct Python path

### Python module not found
- Verify `app/src/main/python/core/__init__.py` exists
- Check `settings.gradle` has Chaquopy repository

### App crashes on startup
- Check Logcat for Python initialization errors
- Make sure all Python dependencies are listed in `app/build.gradle`

## 📊 Comparison

| Approach | Code Reuse | APK Size | Performance |
|----------|-----------|----------|------------|
| Flet only | N/A | ~50MB | Medium |
| Native Android (no Chaquopy) | Low | <10MB | High |
| **Native Android + Chaquopy** | **High** | **~15-20MB** | **Medium-High** |

## 🎯 Benefits

1. **Single codebase**: Maintain Python core logic only
2. **Native UI**: Fast, responsive Android UI
3. **Easy maintenance**: Fix bugs in one place (Python core)
4. **Flexible**: Can add platform-specific features easily

## 🔗 Resources

- [Chaquopy Documentation](https://chaquo.com/chaquopy/doc/current/)
- [Chaquopy API Reference](https://chaquo.com/chaquopy/doc/current/api.html)
- [Main Project README](../README_SHARED.md)
