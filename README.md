# AlbatrossServer

[中文](README_CN.md)

**AlbatrossServer** is a powerful Android instrumentation framework designed for dynamic code injection, runtime hooking, and real-time monitoring of Android applications. It enables researchers and developers to inject custom logic into target apps via RPC control, allowing fine-grained manipulation and analysis of application behavior at runtime.

> ⚠️ **Disclaimer**: This tool is intended **solely** for security research, testing, learning, and educational purposes. **Any unauthorized use, including but not limited to software cracking, piracy, or malicious activities, is strictly prohibited.** The developers assume no liability for misuse.

---

## Project Structure

The project is organized into three main components:

### 1. `albatross-python` (PC-side Control Module)
A Python-based interface for:
- Device discovery and selection
- Remote control of target Android devices
- Launching and attaching to target applications
- Managing injection workflows via RPC

### 2. `albatross-java` (Device-side Core Engine)
Java/Kotlin code running on the Android device, responsible for:
- Hooking into system processes (e.g., `system_server`) and app processes
- Loading and executing injected agents
- Providing lifecycle callbacks for instrumentation plugins

Includes a **demo plugin** to illustrate how to write Albatross-compatible injectors.

### 3. `resource`
Contains essential runtime assets required for injection:
- Agent `.apk` or `.dex` files
- Native libraries (`.so`) for various ABIs
- `albatross_server` binary used on device

---

##  Requirements

### Device
- **Root access** required
- **Android version**: 7 through 15 (Nougat to Vanilla Ice Cream)
- **Supported ABIs**: `x86`, `x86_64`, `arm`, `arm64`
- Must support **AlbatrossAndroid** hooking
- Lsposed must be disabled when launch the target app. If injecting app, it ensures that lsposed is not in the target process

### Host
-  ADB enabled and accessible
-  Python 3.7+ (for `albatross-python`)
-  Linux system. Other systems have not been tested yet

---

## Core Concepts

### Plugin Development
All plugins must extend the `AlbatrossPlugin` class and override lifecycle methods:

> **Plugin Development Reference**: https://github.com/AlbatrossHook/HideApp

```java
public class DemoInjector extends AlbatrossPlugin {
    public DemoInjector(String libName, String argString, int flags) {
        super(libName, argString, flags);
    }

    @Override
    public void beforeMakeApplication() {
        Albatross.log("DemoInjector beforeMakeApplication");
        // Called before the Application object is created
        // Only triggered during `launch` (spawn mode), not `attach`
    }

    @Override
    public void beforeApplicationCreate(Application application) {
        Albatross.log("DemoInjector beforeApplicationCreate");
        try {
            Albatross.hookClass(ActivityH.class);
        } catch (AlbatrossErr e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void afterApplicationCreate(Application application) {
        Albatross.log("DemoInjector afterApplicationCreate");
        // Called after Application.onCreate()
    }
}
```

#### Lifecycle Callbacks

| Method | Trigger Condition |
|-------|-------------------|
| `beforeMakeApplication()` | Called **only during `launch()`**, before the app process is fully initialized. Not called during `attach()`. Similar to Frida's *spawn* mode. |
| `beforeApplicationCreate(Application app)` | Called **before** `Application.onCreate()`. Safe to perform early hooks. |
| `afterApplicationCreate(Application app)` | Called **after** `Application.onCreate()` completes. |

---

## Python API (Control Interface)

### Get Device
```python
device = albatross.get_device(device_id)
```

### Core Injection APIs

#### `launch(...)`
Launches the target app in **spawn mode**, allowing early injection (`beforeMakeApplication` is called).

```python
device.attach(
    package_or_pid="com.example.app",     # Package name or PID
    inject_dex="/path/to/injector.apk",   # DEX file to inject
    dex_lib=None,                         # Optional library name
    injector_class="your.package.DemoInjector",  # Injector class
    arg_str="custom_arg",                 # Optional string argument
    arg_int=0,                            # Optional integer argument
    init_flags=LoadDexFlag.NONE          # Flags for loading
)

```

#### `attach(...)`
Attaches to an already running app or starts it normally. `beforeMakeApplication` **will not** be triggered.

```python
device.launch(
    target_package="com.example.app",
    inject_dex="/path/to/injector.apk",
    dex_lib=None,
    injector_class="your.package.DemoInjector",
    arg_str="custom_arg",
    arg_int=0
)
```

---

## Usage Example

```python
import albatross
import time
from albatross.config import Configuration

# Connect to device
device = albatross.get_device(device_id)
assert device.is_root, "Device must be rooted"

# Wake up and unlock
device.wake_up()

# List user-installed packages
user_pkgs = device.get_user_packages()

# Prepare injection
inject_dex = Configuration.resource_dir + "plugins/injector_demo.apk"
inject_class = "qing/albatross/app/agent/DemoInjector"

for pkg in user_pkgs:
    if 'albatross' in pkg and 'inject_demo' not in pkg:
        continue

    print('Testing package:', pkg)

    device.stop_app(pkg)
    device.start_app(pkg)
    time.sleep(5)

    # Attach injector
    device.attach(pkg, inject_dex, None, inject_class)

    device.home()
    for i in range(3):
        device.switch_app()
        time.sleep(1)
        device.switch_app()

print('Test completed.')
```

---

## Supported Features

- ✅ Real-time code instrumentation
- ✅ Early process injection (`spawn` mode)
- ✅ Cross-ABI support (x86, x86_64, arm, arm64)
- ✅ System app and regular app hooking
- ✅ Plugin-based architecture for extensibility

---

## ⚠️ Legal & Ethical Notice

> **This tool is developed for academic and security research purposes only.**
>
> You must have **explicit authorization** before testing on any system or application.  
> Unauthorized access or modification of software may violate laws and regulations.  
> **Do not use this tool for illegal or unethical purposes.**

---

## Community

**QQ Group**: 478564202

Join our community to discuss mobile security, reverse engineering, risk control, and related topics!

---

## Documentation & Support

For detailed guides, API references, and advanced usage, please refer to the internal documentation or contact the development team.

---

## Acknowledgments

Inspired by powerful dynamic instrumentation tools  **Frida**, AlbatrossServer aims to provide a robust, Android-focused alternative with enhanced control over early-stage app initialization and system-level interactions.

---

## License

Apache License 2.0
See [LICENSE](LICENSE) for details.


*© 2025 AlbatrossServer Project. For research use only.*
