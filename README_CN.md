# AlbatrossServer

[English](README.md)

**AlbatrossServer** 是一个强大的Android动态插桩框架，专为动态代码注入、运行时Hook和Android应用程序的实时监控而设计。它使研究人员和开发者能够通过RPC控制向目标应用注入自定义逻辑，允许在运行时对应用程序行为进行细粒度的操作和分析。

> ⚠️ **免责声明**: 此工具仅用于安全研究、测试、学习和教育目的。**严禁任何未经授权的使用，包括但不限于软件破解、盗版或恶意活动。** 开发者对滥用行为不承担任何责任。

---

## 项目结构

项目分为三个主要组件：

### 1. `albatross-python` (PC端控制模块)
基于Python的接口，用于：
- 设备发现和选择
- 远程控制目标Android设备
- 启动和附加到目标应用程序
- 通过RPC管理注入工作流

### 2. `albatross-java` (设备端核心引擎)
在Android设备上运行的Java/Kotlin代码，负责：
- Hook系统进程（如`system_server`）和应用进程
- 加载和执行注入的代理
- 为插桩插件提供生命周期回调

包含一个**演示插件**来说明如何编写Albatross兼容的注入器。

### 3. `resource`
包含注入所需的基本运行时资源：
- 代理`.apk`或`.dex`文件
- 各种ABI的原生库（`.so`）
- 设备上使用的`albatross_server`二进制文件

---

## 系统要求

### 设备端
- 需要**Root权限**
- **Android版本**: 7到15（Nougat到Vanilla Ice Cream）
- **支持的ABI**: `x86`, `x86_64`, `arm`, `arm64`
- 必须支持**AlbatrossAndroid** Hook
- launch启动app时lsposed必须禁用，如果是注入app，则保证lsposed不在目标进程中

### 主机端
- 启用并可访问ADB
- Python 3.7+（用于`albatross-python`）
- Linux系统。其他系统尚未测试

---

## 核心概念

### 插件开发
所有插件必须继承`AlbatrossPlugin`类并重写生命周期方法：

> **插件开发参考**: https://github.com/AlbatrossHook/HideApp

```java
public class DemoInjector extends AlbatrossPlugin {
    public DemoInjector(String libName, String argString, int flags) {
        super(libName, argString, flags);
    }

    @Override
    public void beforeMakeApplication() {
        Albatross.log("DemoInjector beforeMakeApplication");
        // 在Application对象创建之前调用
        // 仅在`launch`（spawn模式）期间触发，不在`attach`期间
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
        // 在Application.onCreate()之后调用
    }
}
```

#### 生命周期回调

| 方法 | 触发条件 |
|------|----------|
| `beforeMakeApplication()` | 仅在`launch()`期间调用，在应用进程完全初始化之前。在`attach()`期间不调用。类似于Frida的*spawn*模式。 |
| `beforeApplicationCreate(Application app)` | 在`Application.onCreate()`之前调用。可以安全地执行早期Hook。 |
| `afterApplicationCreate(Application app)` | 在`Application.onCreate()`完成后调用。 |

---

## Python API (控制接口)

### 获取设备
```python
device = albatross.get_device(device_id)
```

### 核心注入API

#### `launch(...)`
以**spawn模式**启动目标应用，允许早期注入（调用`beforeMakeApplication`）。

```python
device.attach(
    package_or_pid="com.example.app",     # 包名或PID
    inject_dex="/path/to/injector.apk",   # 要注入的DEX文件
    dex_lib=None,                         # 可选的库名
    injector_class="your.package.DemoInjector",  # 注入器类
    arg_str="custom_arg",                 # 可选的字符串参数
    arg_int=0,                            # 可选的整数参数
    init_flags=LoadDexFlag.NONE          # 加载标志
)
```

#### `attach(...)`
附加到已运行的应用或正常启动它。**不会**触发`beforeMakeApplication`。

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

## 使用示例

```python
import albatross
import time
from albatross.config import Configuration

# 连接到设备
device = albatross.get_device(device_id)
assert device.is_root, "设备必须已Root"

# 唤醒并解锁
device.wake_up()

# 列出用户安装的包
user_pkgs = device.get_user_packages()

# 准备注入
inject_dex = Configuration.resource_dir + "plugins/injector_demo.apk"
inject_class = "qing/albatross/app/agent/DemoInjector"

for pkg in user_pkgs:
    if 'albatross' in pkg and 'inject_demo' not in pkg:
        continue

    print('测试包:', pkg)

    device.stop_app(pkg)
    device.start_app(pkg)
    time.sleep(5)

    # 附加注入器
    device.attach(pkg, inject_dex, None, inject_class)

    device.home()
    for i in range(3):
        device.switch_app()
        time.sleep(1)
        device.switch_app()

print('测试完成。')
```

---

## 支持的功能

- ✅ 实时代码插桩
- ✅ 早期进程注入（`spawn`模式）
- ✅ 跨ABI支持（x86, x86_64, arm, arm64）
- ✅ 系统应用和普通应用Hook
- ✅ 基于插件的可扩展架构

---

## 交流群

**QQ群**: 478564202

欢迎加入我们的交流群，讨论移动安全、逆向工程、风控等相关话题！

---

## ⚠️ 法律与道德声明

> **此工具仅用于学术和安全研究目的。**
>
> 在测试任何系统或应用程序之前，您必须获得**明确授权**。  
> 未经授权访问或修改软件可能违反法律法规。  
> **请勿将此工具用于非法或不道德的目的。**

---

## 文档与支持

有关详细指南、API参考和高级用法，请参阅内部文档或联系开发团队。

---

## 致谢

受到强大的动态插桩工具**Frida**的启发，AlbatrossServer旨在提供一个强大的、专注于Android的替代方案，增强对早期应用初始化和系统级交互的控制。

---

## 许可证

Apache License 2.0
详情请参见 [LICENSE](LICENSE)。

---

*© 2025 AlbatrossServer Project. 仅供研究使用。*

