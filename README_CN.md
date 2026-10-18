# AlbatrossServer

[English](README.md) · 版本 **4.0.0**

AlbatrossServer 是一个基于 root 的 Android 动态插桩框架。它把 agent 注入到应用进程（可选注入
`system_server`），在每个进程内提供一套行协议 RPC 服务，宿主机上的 Python 程序据此完成整条工作流：
attach / spawn 注入、Java / native hook、trace、进程内 C 模块、内存读写监听、插件管理以及设备自动化。

> **免责声明**：仅可在你拥有或获得明确授权的设备与应用上使用本项目，禁止未经授权的使用。

---

## 1. 能做什么（功能地图）

| 能力 | Python 入口 | 说明 |
|---|---|---|
| 设备 / ADB | `albatross.get_device()`、`get_device_ids()`、`get_usb_devices()`、`get_health_snapshot()` | 选择 USB 或无线设备，查看连接健康度 |
| 根服务 | `device.client` | 自动推送 `albatross_server` + `libalbatross_base.so`，启动 root 守护进程并建立 adb forward |
| 应用控制 | `device.start_app()`、`stop_app()`、`install_if_not_exist()`、`uninstall_package()`、`silence_install()`、`get_user_packages()`、`get_package_uid()` | 常规设备/应用自动化 |
| attach 注入 | `device.attach()`、`attach_with_plugins()`、`attach_with_plugin_ids()` | 注入已经在运行的 Java 进程 |
| spawn 注入 | `device.launch_fast()`、`launch_with_plugins()`、旧接口 `launch()` | 启动目标时插件已经登记好 |
| 插件管理 | `device.register_plugin()`、`reload_plugin()`、`remove_plugin()`、`add_plugin_rule()`、`client.clear_plugins()` | 推送 / 登记 / 更新 / 删除插件 |
| Java 指令级 hook | `app.hook_method()`、`unhook_method()`、`hook_class()`、`unhook_class()`、`find_method()` | 按 dex-PC 窗口或整个类 hook |
| 免签名动态 hook | `app.dyn_hook_method()`、`dyn_hook_method_return()`、`dyn_unhook_method()`、`dyn_hook_class()`、`dyn_unhook_class()` | trampoline 路线，不改调用方代码 |
| hook 命中记录 | `app.hook_events_enable()`、`hook_events_status()`、`hook_events_pull()`、`hook_events()`、`hook_events_clear()` | 从进程内环形缓冲结构化拉取命中记录 |
| Java 方法级 trace | `app.trace_call()`、`trace_return()`、`trace_keyword()`、`trace_string()`、`stop_trace()`、`set_trace_timeout()`、`set_trace_max_events()`、`trace_status()`、`trace_java_method()`、`untrace_java_method()`、`java_method_trace_status()` | 基于 OceanTracker 的方法级执行追踪 |
| native trace | `app.trace_native_function()`、`stop_native_trace()`、`native_trace_status()`、`native_trace_dump()` | call/ret/exec/block 事件，含寄存器与访存字节 |
| native 信息 | `app.get_modules()`、`app.get_functions()`、`app.watch_func()`、`app.watch_library_load()`、`app.dump_native_method()` | 模块/函数发现与库加载通知 |
| CModule | `app.cmodule_run/compile/call/call_v/get_symbol/free/run_isolated/...` | 在目标进程内用 tcc 编译并运行 C |
| 无 Java VM 进程加载 JVM | `client.load_jvm()`（根客户端与注入客户端都支持） | 给原生进程创建 JVM，之后可加载 dex / 插件 |
| system_server | `device.system_server_client`、`device.load_system_plugin()`、`client.set_system_server_agent()` | 规则/拦截管理与系统插件 |
| 反检测 / 隐藏 | `AlbatrossInitFlags.FLAG_ANTI_DETECTION`、`InjectFlag.MEMFD`、`InjectFlag.WXORX`、`client.support_extend_kpm()`、`client.hide_path()`、`client.redirect_path()` | 降低注入痕迹；可选 KPM 支持 |
| 内存读写监听 | `client.rwbp_watch_add/del/drain/drain2`、`parse_rwbp_watch_drain()` | 内核辅助的 watchpoint（需要 rwbp 模块） |
| 日志 | `app.se_logger()`、`app.flush_log()`、`app.redirect_app_log()`、`app.init_native_log()` | 文件 / logcat 日志控制 |
| 自定义 RPC | `@rpc_api`、`@broadcast_api`、`RpcClient.create_subscriber()`、`register_broadcast_handler()` | 在插件里暴露自己的方法与广播 |

以上能力的实现都在本仓库的 `albatross-python` 与 `albatross-java` 中；根服务与 native 库位于
`resource/jniLibs/`。

---

## 2. 环境要求

### 设备端

- **Root 权限**（Magisk / APatch / KernelSU）。`su -c id` 必须返回 `uid=0`。
- **Android 7.0（API 24）及以上**。支持/参考范围是 Android 7–15；更高版本或厂商 ROM 可能可用，
  但不做保证，`system_server` 内部实现差异需要按 ROM 处理。
- ABI：`arm64-v8a`、`armeabi-v7a`、`x86_64`、`x86`。
- **目标进程里不能有 LSPosed**。`launch` / `launch_fast` 启动前先禁用它；`attach` 前也要确认它
  没有被注入。先调用 `client.is_lsposed_injected()` 检查。
- SELinux：框架会在运行时修补策略（`client.patch_selinux()`）；修补失败时客户端会退到 permissive。
  不要把全局 SELinux 关掉当作常规做法。

### 宿主机

- **Python 3.10+** —— 包内使用了 `str | None`（PEP 604）运行时注解。
- `pip install -r albatross-python/requirements.txt`（`toml`、`watchdog`）。
- `adb` 在 `PATH` 中，或在配置里设置 `adb_path`。
- 主要验证平台是 Linux；Windows 有代码分支但未定期验证。

---

## 3. 快速开始

### 3.1 准备 `resource`

仓库里的 `resource/` 不是完整可运行载荷（含占位文件，也可能有陈旧产物）。请从对应版本 Release
下载资源（或自行构建），目录结构如下：

```text
resource/
├── jniLibs/
│   └── <abi>/
│       ├── albatross_server
│       └── libalbatross_base.so
├── agent/
│   ├── app_agent.dex
│   └── system_server.dex
├── jar/
│   ├── annotation-release.aar
│   ├── core-release.aar
│   ├── server-release.aar
│   └── ocean-release.aar
└── plugins/
    └── plugin_demo.apk
```

第一次访问 `device.client` 时，客户端会自动把 server 二进制与 so 推到设备。宿主机侧编译 Java
模块时使用 `resource/jar` 里的 AAR。

### 3.2 配置客户端

配置文件查找顺序：

1. `ALBATROSS_CONFIG=/path/to/albatross_config.toml`
2. `albatross-python/albatross/albatross_config_local.toml`
3. `~/.albatross/albatross_config.toml`（首次使用自动创建）

`resource_dir` 查找顺序：配置项 `resource_dir` → 环境变量 `ALBATROSS_RESOURCE_DIR` →
仓库下的 `resource/`。

```bash
pip install -r albatross-python/requirements.txt
export PYTHONPATH="$PWD/albatross-python:$PWD"
export ALBATROSS_RESOURCE_DIR="$PWD/resource"

python3 - <<'PY'
import albatross
print("albatross", albatross.__version__)
device = albatross.get_device()          # 默认选择第一台在线设备
print(device.serial_no, device.cpu_abi, device.sdk_version, device.is_root)
PY
```

最小配置示例（`resource_dir` 末尾保留 `/`，客户端会直接拼接路径）：

```toml
resource_dir = "/absolute/path/to/resource/"
# adb_path = "/absolute/path/to/adb"
# server_port = 19088
```

`get_device(serial)` 支持 USB serial，也支持无线地址（如 `192.168.1.10:5555`）。

### 3.3 第一次注入

```python
import time
import albatross
from albatross.common import Configuration

device = albatross.get_device("emulator-5554")
assert device.is_root, "device must be rooted"
device.wake_up()

pkg = "com.example.app"
plugin_apk = Configuration.resource_dir + "plugins/plugin_demo.apk"
plugin_class = "qing.albatross.plugin.app.DemoPlugin"

# 登记插件并通过 system_server 冷启动目标
ok = device.launch_fast(pkg, plugin_apk, plugin_class, plugin_params=pkg)
print("launch_fast:", ok)

time.sleep(3)
uid = device.get_package_uid(pkg)
print("java pids:", device.client.get_java_processes_by_uid(uid))
albatross.destroy()      # 幂等；同时注册在 atexit
```

`launch_fast` 会 force-stop 目标、登记插件规则并启动应用；不要再额外 `stop_app` / `start_app`。
`attach` 是给已经在运行的应用做后期注入。

---

## 4. 工作方式

```text
宿主机（Python）
  └─ albatross-python
       ├─ adb shell / adb forward
       ├─ albatross_server（设备上的 root 守护进程，一个 RPC 端点）
       │    └─ 把 libalbatross_base.so 注入目标进程
       ├─ app_agent.dex（运行在应用进程，AppClient 端点）
       ├─ system_server.dex（运行在 system_server，SystemServerClient 端点）
       └─ 插件 APK/JAR/DEX（加载进目标进程）
```

实际使用中主要涉及三个 RPC 端点：

| 端点 | 获取方式 | 用途 |
|---|---|---|
| 根服务 | `device.client` | 注入、插件登记、`system_server` 配置 |
| 应用进程 | `client.get_address(pid)` + `device.get_forward_port("localabstract:" + address)`，然后 `AppClient(port, None, name)` | hook、trace、CModule、应用自定义 RPC |
| `system_server` | `device.system_server_client` | 进程控制、拦截、权限/ID 模拟 |

协议是二进制分帧 RPC（`wq` 头 + call id + payload 长度）。Python 方法用 `@rpc_api` 声明，
广播用 `@broadcast_api`。插件在 `load()` 里调用
`agent.registerApi(this, YourApi.class)` 注册自己的 RPC 接口。

---

## 5. 注入模式

| 模式 | API | 目标状态 | 返回 | 说明 |
|---|---|---|---|---|
| 后期 attach | `device.attach(...)` | 应用已在运行 | `list[pid]` | 注入每个 Java 进程并加载插件；不会启动应用 |
| 规则 spawn | `device.launch_fast(...)` | 应用未启动/将被启动 | `bool` | **推荐**；登记插件后 force-stop 再启动 |
| 插件 spawn | `device.launch_with_plugins(...)` | 应用将被启动 | `bool` | 传入 `register_plugin()` 返回的 `Plugin` 对象 |
| 多插件 attach | `device.attach_with_plugins(...)` | 应用运行中 | `list[(pid, Plugin)]` | 一次注入并加载多个插件 |
| 按 ID attach | `device.attach_with_plugin_ids(...)` | 应用运行中 | `list[(pid, Plugin)]` | 按已登记插件 ID 加载 |
| 旧 spawn | `device.launch(...)` | 应用未启动/将被启动 | `None` | **已过时**（见 `test/launch_test.py`）；基于 `system_server` 拦截与 launch 回调 |

关键细节：

- `attach` 只会注入 `get_java_processes_by_uid(uid)` 返回的 Java 进程。纯 native 进程需要显式调用
  `client.inject_albatross(pid, ...)`。
- 后期 `attach` 无法重放真实的 `Application` 生命周期。`beforeMakeApplication` 只对 agent 初始化
  时就已存在的插件调用；`before/after*Application*` 在插件后期加载时仍可能被调用，但真实的
  `Application` 创建 / `onCreate` 已经发生。需要严格顺序时请使用 `launch*` 路径。
- `attach`、`launch_fast`、`launch_with_plugins`、`attach_with_plugins`、
  `attach_with_plugin_ids` 支持 `raise_on_fail=True`；全部失败时会抛出
  `albatross.exceptions.AttachFailed`，带每个阶段的失败详情，而不是静默返回空列表。自动化脚本
  建议使用。旧接口 `launch()` 没有这个参数。
- `device.init_plugin_env` 会推送 `system_server` agent；dex 变化时可能重启 `system_server`
  （`update_kill_system_server`），升级时请预期一次系统短暂重启。

---

## 6. 插件开发

插件是一个继承 `qing.albatross.agent.AlbatrossPlugin` 的 Java 类。示例模块在
`albatross-java/plugin_demo`。

```java
package com.example.plugin;

import android.app.Application;
import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.server.UnixRpcInstance;

public class MyPlugin extends AlbatrossPlugin {
  public MyPlugin(String libName, String params, int flags) {
    super(libName, params, flags);
  }

  @Override
  public boolean load(UnixRpcInstance agent) {
    agent.registerApi(this, MyApi.class);   // 可选：注册自定义 RPC
    return super.load(agent);
  }

  @Override
  public boolean parseParams(String params, int flags) {
    // params 来自 plugin_params；返回 false 表示加载失败
    return true;
  }

  @Override
  public void beforeNewApplication(ClassLoader cl, String className, android.content.Context context) {
    // 最早的 Application 构造前回调；需要 launch/spawn 注入
  }

  @Override
  public void beforeApplicationCreate(Application application) {
    // Application.onCreate() 之前
  }

  @Override
  public void afterApplicationCreate(Application application) {
    // Application.onCreate() 之后
  }

  @Override
  public void onAttachSystem(Application application) {
    // 仅 system 插件
  }
}

public interface MyApi {
  void toast(String msg);
}
```

生命周期：

| 回调 | 触发时机 |
|---|---|
| `load(UnixRpcInstance)` | 插件加载；在这里注册 RPC |
| `parseParams(params, flags)` | 加载时与配置变更时 |
| `beforeMakeApplication()` | agent 初始化、Application 创建前（spawn 路径） |
| `beforeNewApplication(cl, className, context)` / `afterNewApplication(app)` | `Application` 构造前后；插件后期加载时立即以当前 Application 调用 |
| `beforeApplicationCreate(app)` / `afterApplicationCreate(app)` | `Application.onCreate()` 前后 |
| `onAttachSystem(app)` | system 插件挂到 `system_server` 时 |
| `onConfigChange(config, flags)`、`enable()`、`disable()`、`unload()` | 运行时管理 |

`AndroidManifest.xml` 里的插件元数据（管理器/demo 工具会读取）：

```xml
<meta-data android:name="albatross_plugin" android:value="true" />
<meta-data android:name="plugin_name" android:value="MyPlugin" />
<meta-data android:name="plugin_class" android:value="com.example.plugin.MyPlugin" />
<meta-data android:name="plugin_description" android:value="..." />
<meta-data android:name="plugin_author" android:value="..." />
```

如果插件自带 native 库，重写 `loadLibrary(String libName)` 并在里面
`System.loadLibrary(libName)`。

构建与部署：

```bash
cd albatross-java
./gradlew :plugin_demo:assembleDebug
# 产物：plugin_demo/build/outputs/apk/debug/plugin_demo-debug.apk

# 用 Python 客户端部署
python3 - <<'PY'
import albatross
from albatross.common import Configuration
d = albatross.get_device()
apk = Configuration.resource_dir + "plugins/plugin_demo.apk"
d.launch_fast("com.example.app", apk, "qing.albatross.plugin.app.DemoPlugin")
PY
```

`plugin_dex` 可以是裸 `.dex`、`.jar` 或多 dex `.apk`。反检测模式下 `/data/` 下的插件会走内存
dex 加载；4.0.0 已支持 APK/JAR 容器，内存加载失败时会回退 `DexClassLoader`。

---

## 7. Python API 参考

### 7.1 模块 `albatross`

```python
import albatross

albatross.__version__          # "4.0.0"
albatross.get_device(serial)   # AlbatrossDevice；serial 为 None 时取第一台设备
albatross.get_cached_device(serial)
albatross.remove_device(serial)
albatross.get_device_ids()     # adb 报出的设备列表
albatross.get_usb_devices()
albatross.get_health_snapshot()
albatross.destroy()            # 幂等清理
```

### 7.2 `AlbatrossDevice`

设备/ADB：`serial_no`、`get_serial()`、`adb_cmd()`、`shell()`、`su_shell()`、`root_shell()`、
`getprop()`、`is_root`、`is_adb_root`、`sdk_version`、`cpu_abi`、`is_64`、`support_32`、
`debuggable`、`wake_up()`、`home()`、`click()`、`swipe()`、`reboot()`、`setenforce()`、
`is_selinux_on()`。

应用管理：`get_user_packages()`、`is_app_install()`、`install_if_not_exist()`、
`uninstall_package()`、`silence_install()`、`start_app()`、`stop_app()`、`start_activity()`、
`get_app_main_activity()`、`dump_apk()`、`get_package_info()`、`get_package_uid()`、
`get_package_version_code()`、`get_processes_by_uid()`、`pidof()`。

文件/UI：`push_file()`、`pull_file()`、`delete_file()`、`get_file_md5()`、
`device_file_md5_matches()`、`check_deploy_downgrade()`、`screenshot()`、`dumpui()`、
`get_activity_stack()`、`top_app()`。

网络：`forward()`、`forward_tcp()`、`get_forward_port()`、`remove_forward_port()`、
`get_device_ip()`、`switch_to_ip_connect()`、`switch_to_usb_connect()`。

注入/插件：`attach()`、`launch()`、`launch_fast()`、`launch_with_plugins()`、
`attach_with_plugins()`、`attach_with_plugin_ids()`、`register_plugin()`、`reload_plugin()`、
`remove_plugin()`、`load_system_plugin()`、`add_plugin_rule()`、`clear_plugins()`、
`watch_plugin()`。

Flag：`device.app_init_flags`（默认 `FLAG_LOG | FLAG_CALL_CHAIN | FLAG_INIT_RPC`）、
`device.app_inject_flags`（默认 `KEEP | UNIX`）、`device.add_init_flags()`、
`device.add_inject_flags()`。

清理：`device.close()`、`albatross.destroy()`。

### 7.3 `AlbatrossClient`（根服务）

通过 `device.client` 获取，负责进程与插件管理：

- 注入：`inject_albatross(pid, flags, temp_dir)`、`detach(pid, flags)`、`is_injected(pid)`、
  `get_java_processes_by_uid(uid)`、`get_process_isa(pid)`、`get_process_pid(name)`、
  `process_uid(pid)`。
- agent/插件：`set_app_agent()`、`set_system_server_agent()`、`register_plugin()`、
  `delete_plugin()`、`modify_plugin()`、`add_plugin_rule()`、`delete_plugin_rule()`、
  `clear_plugins()`、`load_plugin()`、`load_plugin_by_id()`、`load_dex()`、
  `load_system_plugin()`、`unload_plugin_dex()`。
- 应用 RPC 端点：`get_address(pid)` → 配合
  `device.get_forward_port("localabstract:" + address)` 使用。
- 环境：`patch_selinux()`、`add_selinux_rule()`、`set_inject_flags()`、
  `set_dex_load_timeout()`、`mount()`、`umount()`、`hide_path()`、`redirect_path()`、
  `support_extend_kpm()`。
- 内存监听：`rwbp_watch_add()`、`rwbp_watch_del()`、`rwbp_watch_drain()`、
  `rwbp_watch_drain2()`。
- 启动回调：`register_launch_callback()`、`launch_process()`、`launch_callback()`、
  `create_subscriber()`。

### 7.4 `BaseClient`（注入进程内）

`AppClient` 继承 `BaseClient`。常用方法：

- Java hook：`find_method()`、`hook_method()`、`unhook_method()`、`hook_class()`、
  `unhook_class()`、`find_class()`、`find_sub_class()`、`get_class_methods()`、
  `get_class_fields()`。
- 动态 hook：`dyn_hook_method()`、`dyn_hook_method_return()`、`dyn_unhook_method()`、
  `dyn_hook_class()`、`dyn_unhook_class()`。
- hook 记录：`hook_events_enable()`、`hook_events_status()`、`hook_events_pull()`、
  `hook_events()`（返回 `(events, next_cursor)`）、`hook_events_clear()`。
- CModule：`cmodule_run()`、`cmodule_compile()`、`cmodule_call()`、`cmodule_call_v()`、
  `cmodule_get_symbol()`、`cmodule_free()`、`cmodule_run_isolated()`、`cmodule_layout()`、
  `cmodule_list()`、`cmodule_source()`、`cmodule_symbols()`、`cmodule_capabilities()`、
  `cmodule_annotate()`、`cmodule_audit()`、`cmodule_cancel()`、`cmodule_deadline()`、
  `cmodule_set_timeout()`、`cmodule_symbolize()`。
- 进程/JVM：`getuid()`、`load_jvm()`、`load_lib()`、`register_native_handler()`、
  `dump_all_threads()`、`read_file()`、`read_maps()`、`read_smaps()`。
- 其它：`print_all_class_loader()`、`decompile_all()`、`set_to_string_config()`、
  `get_functions()`。

`hook_method(className, methodName, num_args, args=None, min_dex_pc=0, max_dex_pc=128,
safe_string=False)` 返回 `InsHookResult`（`HOOK_SUCCESS=0`、`ALREADY_HOOK=1`、
`CLASS_NOT_FIND=-1`、`METHOD_NOT_FIND=-2`、`HOOK_FAIL=-3`）。

`args` 是**方法签名的子串**，用于消解重载歧义，不是 JNI 描述符。名字 + 参数个数不唯一时先调用
`get_class_methods()` 查看真实签名；唯一时传 `None` 即可。

### 7.5 `AppClient`

应用级 RPC 与 trace：

```python
from albatross.app_client import AppClient, EventType, TraceScope
```

- 包名/日志：`get_package_name()`、`se_logger()`、`flush_log()`、`redirect_app_log()`、
  `finish_redirect_app_log()`。
- Java trace：`trace_call(only_main_thread)`、`trace_return(only_main_thread, extra_flags=0)`、
  `trace_keyword(keyword, main_thread)`、`trace_string(keyword, main_thread)`、
  `trace_test(main_thread)`、`stop_trace()`、`trace_count()`、`set_trace_scope()`、
  `set_trace_timeout(timeout_ms)`、`set_trace_max_events(max_events)`、`trace_status()`。
- 按方法 trace：`trace_java_method(class, method, num_args, args, events=0,
  timeout_ms=-1, max_events=0)`、`untrace_java_method(...)`、`java_method_trace_status()`。
- native trace：`trace_native_function(lib, symbol, address, timeout_ms, max_events, flags,
  log_path)`、`stop_native_trace()`、`native_trace_status()`、`native_trace_dump(max_bytes=0)`。
- native 信息：`get_modules(include_sys=False)`、`watch_func()`、`watch_library_load()`、
  `dump_native_method()`、`init_native_log()`。
- 其它：`class_loaders()`、`add_not_trace_package()`、`unshell()`、`finish_unshell()`。

### 7.6 `SystemServerClient`

通过 `device.system_server_client` 获取：

`init()`、`init_intercept()`、`get_top_activity()`、`get_front_activity()`、
`get_front_activity_quick()`、`get_all_processes()`、`start_activity()`、`start_app()`、
`set_top_app()`、`force_stop_app()`、`set_intercept_all()`、`set_intercept_app()`、
`add_watch_app()`、`set_app_android_id()`、`clear_uid()`、`get_version()`、
`allow_app_permission()`、`mock_battery_info()`、`mock_lock()`、`stability_test()`。

### 7.7 连接应用进程

```python
from albatross.app_client import AppClient

root = device.client
uid = device.get_package_uid("com.example.app")
for pid in root.get_java_processes_by_uid(uid):
    address = root.get_address(pid)
    port = device.get_forward_port("localabstract:" + address)
    app = AppClient(port, None, f"com.example.app:{pid}")
    try:
        print(app.get_package_name(), app.getuid())
        app.set_trace_timeout(30_000)
        app.trace_call(True)
        # ... 触发目标代码 ...
        app.stop_trace()
        print(app.trace_status())
    finally:
        app.close()
```

### 7.8 自定义 RPC

在 Python 客户端声明方法，在插件里实现：

```python
from albatross.rpc_common import rpc_api, void

class MyClient(AppClient):
    @rpc_api
    def toast_msg(self, msg: str) -> void:
        pass
```

```java
@Override
public boolean load(UnixRpcInstance agent) {
  agent.registerApi(this, MyApi.class);
  return super.load(agent);
}
public void toastMsg(String msg) { /* ... */ }
```

广播用 `@broadcast_api`；接收前先调用 `client.create_subscriber()`。标注了 `@rpc_api(arm=True)` 的
方法会进入武装脚本，可在进程重启后通过 `client.start_arm_recording()` /
`device.replay_arm_scripts(uid, client)` 重放。

---

## 8. trace、hook 与 CModule 配方

### 8.1 Java 方法级 trace

```python
app.set_trace_scope(TraceScope.kApplication | TraceScope.kEntryOnly)
app.set_trace_timeout(20_000)      # 0 = 不限时；默认 60s 兜底
app.set_trace_max_events(50_000)   # 0 = 不限
app.trace_call(only_main_thread=True)
# ... 触发代码路径 ...
app.stop_trace()
print(app.trace_status())          # JSON：running/stop_reason/elapsed_ms/events
```

只追单个方法（进入时 arm、退出即 disarm）：

```python
from albatross.app_client import EventType

rc = app.trace_java_method(
    "com.example.Foo", "bar", 1, None,
    events=EventType.CALL | EventType.RETURN,
    timeout_ms=10_000,
)
# rc：0 成功 / 1 同目标已安装 / -1 类找不到 / -2 方法找不到 / -3 安装失败
...
app.untrace_java_method("com.example.Foo", "bar", 1, None)
```

注意：

- `trace_java_method` 不支持 `EXEC` / `DUMP` 事件位，会被屏蔽。
- trace 窗口是进程级共享的；并发多个按方法 trace 会共享事件计数与超时。
- trace 输出走普通日志通道：logcat tag `Albatross`；配置了 `FLAG_LOG` / `se_logger` 时写滚动文件。

### 8.2 hook 命中记录

```python
client.hook_events_enable(8192)        # 0 = 默认 4096；-1 = 关闭
cursor = 0
while True:
    events, cursor = client.hook_events(cursor)
    for e in events:
        print(e["kind"], e["phase"], e["method"], e.get("args"), e.get("ret"))
    if not events:
        break
client.hook_events_clear()
```

记录由 `hook_method` / `dyn_hook_method` / `hook_class` / `dyn_hook_class` 产生。默认关闭；关闭时
命中路径只做一次 volatile 读。

### 8.3 native trace

```python
ok = app.trace_native_function(
    lib_name="libtarget.so",
    symbol="target_func",
    address=0,                 # 0 = 按 lib+symbol 解析
    timeout_ms=10_000,         # -1 = 默认 60s，0 = 不限
    max_events=0,
    flags=0,                   # bit0 只记录主线程；bit1 不记录访存字节；bit2 延迟登记
    log_path="/data/local/tmp/native_trace.log",
)
app.stop_native_trace()
print(app.native_trace_status())   # JSON
print(app.native_trace_dump())
```

`flags bit2`（延迟登记）适合目标库还没加载的场景：库加载后自动开始。每个进程只支持一个
native trace 目标。

### 8.4 CModule（在目标进程里编译 C）

```python
r = app.cmodule_run(r'''
#include <albatross.h>
#include <stdio.h>
long alb_main(const char *arg, char *out, int out_size) {
  snprintf(out, out_size, "arg=%s", arg);
  return 42;
}
''', arg="hello")
print(r.value, r.output, r.error)
```

入口约定：`usize alb_main(const char *arg, char *out, int out_size)`。

- `cmodule_run()` 编译、调用入口、**释放模块**。不要在一次性脚本里装 hook 或注册 RPC；这类场景用
  `cmodule_compile()` + `cmodule_call()`，最后显式 `cmodule_free()`。
- `cmodule_run_isolated()` 会 fork 子进程：崩溃/超时被隔离，但 hook 和内存写入不会影响目标进程。
- `cmodule_set_timeout(handle, ms)` 用来防 `cmodule_call()` 里的死循环。
- 脚本里可以直接调用 `albatross.h` 的 native API（`AlbDlopen`、`AlbDlsym`、
  `AlbGetModuleBase`、`AlbStalker*`、`AlbatrossHookFunc` 等）。

### 8.5 内存监听（rwbp）

```python
from albatross.albatross_client import parse_rwbp_watch_drain2

ok = client.rwbp_watch_add(tid, addr, size, watch_type=3)   # 3 = 读 + 写
raw = client.rwbp_watch_drain2(max_events=64)
batch = parse_rwbp_watch_drain2(raw)
for ev in batch.events:
    print(ev.pc, ev.lr, ev.operation(), ev.value() if ev.is_write else None)
client.rwbp_watch_del()
```

需要 rwbp 内核模块。事件是异步的：延迟后再 drain，或轮询。`verified` 是保留字段，恒为 false；
质量判据用 `blindwin()`（会话期间目标页被放开过）。

---

## 9. Flag

### `AlbatrossInitFlags`（客户端/agent 行为）

| Flag | 含义 |
|---|---|
| `FLAG_DISABLE_JIT` | 关闭目标 JIT |
| `FLAG_ANTI_DETECTION` | 移除 RWX 段、隐藏注入痕迹、启用路径隐藏 |
| `FLAG_FIELD_BACKUP_INSTANCE` / `FLAG_FIELD_BACKUP_STATIC` | hook 前备份实例/静态字段 |
| `FLAG_INJECT` / `FLAG_INIT_RPC` | 内部注入/RPC 引导（辅助方法会自动设置） |
| `FLAG_CALL_CHAIN` | 启用调用链支持 |
| `FLAG_INTERPRETER` | 强制解释执行 |
| `FLAG_LOG` / `REDIRECT_LOG` | 文件日志 / 重定向应用日志 |

### `InjectFlag`（注入机制）

| Flag | 含义 |
|---|---|
| `KEEP` | 注入库常驻 |
| `UNIX` | agent RPC 端点使用 Unix socket |
| `MEMFD` | 从匿名 memfd 加载库 |
| `WXORX` | 目标 seccomp 禁止 RWX 映射时使用的 W^X 模式 |
| `SOCKET`、`DEBUG`、`UNLOAD`、`TEST` | 底层/历史开关 |

用 `device.add_init_flags()` / `device.add_inject_flags()` 在默认值上追加。根客户端已存在后修改
inject flags 会立即下发到服务端。

---

## 10. 反检测、KPM 与隐藏部署

`AlbatrossDevice.anti_detection` 默认是 `True`。它会启用 `FLAG_ANTI_DETECTION` 以及框架的路径
隐藏/mount 清理，但**不会**自动把所有隐藏手段都打开：

- `InjectFlag.MEMFD` 需要显式追加（`device.add_inject_flags(InjectFlag.MEMFD)`）；测试 helper
  `hide_albatross()` 会在 `support_kpm` 为 false 时这样做。
- `device.hide_file = True` 才会启用 Android 10+ 的 agent 文件 bind mount 隐藏（默认关闭）。
- `client.support_extend_kpm()` 报告是否有 KPM 模块提供更强隐藏（`hide_path`、`redirect_path`、
  smaps 归零）。需要时用 `device.load_kpm_impl = your_loader` 提供加载器。

**反检测开启时不要通过 `/proc/<pid>/maps` 判断注入是否成功。** 用 `client.ping()` /
`is_injected(pid)` / 一次便宜的 RPC 调用判断。maps 检查会产生假阴性；demo 测试会显式断言库路径
不存在。

---

## 11. 构建 Java 侧

```bash
cd albatross-java

# 默认：使用 resource/jar 里的 AAR
./gradlew :plugin_demo:assembleDebug
./gradlew :app_agent:assembleDebug
./gradlew :system_agent:assembleDebug

# release 变体
./gradlew :plugin_demo:assembleRelease
./gradlew :app_agent:assembleRelease
./gradlew :system_agent:assembleRelease
```

产物：

```text
plugin_demo/build/outputs/apk/debug/plugin_demo-debug.apk
app_agent/build/outputs/apk/debug/app_agent-debug.apk
system_agent/build/outputs/apk/debug/system_agent-debug.apk
```

根客户端消费的是 `resource/agent/app_agent.dex` 与 `resource/agent/system_server.dex`
（单 dex 文件，不是 APK）。Release 包自带预构建版本；如果自行重建 agent，需要把 APK 里的
`classes*.dex` 合并成一个 dex 并更新 `resource/agent/`，再运行客户端。

本仓库默认且验证过的是 AAR 模式。`settings.gradle.kts` 里也保留了源码模式入口
（`project.albatross.dir`），但本仓库不包含 Albatross core 源码；除非你自己维护那棵源码树，
否则请使用 Release 包里的 AAR。

---

## 12. 排障与常见坑

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `DeviceNotRoot` | `su` 被拒 / 没有 root | 确认 `su -c id`；模拟器用带真实 root 的镜像 |
| `NoDeviceFound` | 没设备 / adb server 端口不对 | `adb devices`；设置 `adb_path` 或 `ALBATROSS_ADB_SERVER_PORTS` |
| `PackageNotInstalled` | 包不存在（user 0） | 先 `device.is_app_install(pkg)` |
| `attach` 返回 `[]` | 应用没运行或没有 Java 进程 | `start_app` 后等待；检查 `get_java_processes_by_uid` |
| `DexLoadResult.DEX_LOAD_FAIL` | agent/插件不匹配或 dex 损坏 | 看 `/data/local/tmp/albatross.log` 与 logcat tag `Albatross`；重打/重推插件 |
| `DexLoadResult.DEX_SYSTEM_SERVER_ERR` | `system_server` agent 未就绪 | 执行 `device.init_plugin_env`；确认 `system_server` 是否重启 |
| `InjectResult.INJECT_PROCESS_SLEEPING(-6)` | 目标冻结/未启动 | 启动应用后重试；检查 `pidof` |
| 插件回调不触发 | 后期 `attach`，`Application` 已创建 | 早期回调改用 `launch_fast` / `launch` |
| `hook_method` 返回 `-2` | 重载歧义 | 先 `get_class_methods()`，把签名子串传给 `args` |
| `hook_method` 返回 `-1` | 类加载器/类名不对 | 试 `find_class()` / `find_sub_class()`；使用应用类加载器 |
| trace 立刻停 | 默认 60s 窗口已到 / 超时太短 | `set_trace_timeout(ms)`；原因看 `trace_status()` |
| trace 没有输出 | scope 不对 / 只追主线程 / 日志没配置 | `set_trace_scope()`、检查 `only_main_thread`、配置 `se_logger`/`FLAG_LOG` |
| hook 记录为空 | 记录没开 | 装 hook 前先 `hook_events_enable()` |
| CModule 装的 hook 消失 | `cmodule_run` 已释放模块 | 改用 `cmodule_compile` + `cmodule_call`，最后显式 free |
| CModule 编译报错 | 缺 include / 隐式声明 | 引入 `albatross.h`；检查 `r.error` |
| `rwbp` 没有事件 | 内核模块未加载 / 页面盲窗 | `support_extend_kpm()`；检查 `blindwin()`；延迟后 drain |
| `load_jvm` 失败 | 非 Android/静态构建，或没有 `BOOTCLASSPATH` | 用 Android `USE_LIBC` 构建；目标进程需继承 Android 启动环境 |
| `launch` 没反应 | LSPosed 已注入或拦截失败 | `client.is_lsposed_injected()`；改用 `launch_fast` |
| 反检测校验失败 | 在 maps 里找路径 | 不要用 maps；用 RPC `ping`/`is_injected` |

更多硬规则：

- **不要提交 `resource/`。** 它是本地/Release 载荷，不是源码；仓库里的占位文件不可运行。
- **版本要配套。** server 二进制、`libalbatross_base.so`、agent dex、AAR 必须来自同一个 Release。
  `resource/` 陈旧是最常见的“静默失败”来源。
- **注意清理。** `AppClient.close()` 关闭 socket；`device.close()` 还会清 forward；
  `albatross.destroy()` 幂等且已注册到 `atexit`。
- **不要重复注入。** 进程已注入时 `inject_albatross` 返回 `ALREADY`；此时应重载插件，而不是再次注入。
- **别折腾设备。** `launch_fast`、`init_plugin_env`、system 插件变更都可能重启 `system_server`，
  不要在循环里反复执行。

---

## 13. 给 AI / 自动化脚本的约定

如果你是根据本仓库写代码的 AI：

1. **以源码为准。** 精确 API 在 `albatross-python/albatross/*.py`（Python）、
   `albatross-java/**/src/main/java/**`（Java）、`test/*.py`（可运行示例）。不要臆造方法名；
   不确定时直接检查：
   ```python
   import inspect
   print([m for m in dir(device) if not m.startswith("_")])
   print(inspect.signature(device.attach))
   ```
   `@rpc_api` 声明的方法由 `RpcMeta` 元类在**已连接的实例**上动态解析；
   `hasattr(AppClient, "hook_method")` 按设计是 false，请检查活的 `app` 实例。
2. **最小流程。**
   `get_device → assert is_root → wake_up → launch_fast/attach → client.get_address + forward →
   AppClient → 操作 → close/destroy`。
3. **新代码优先用 `launch_fast`**；`launch` 已过时。只有必须保持应用运行态时才用 `attach`。
4. **检查返回值。** `DexLoadResult`、`InjectResult`、`SetResult`、`InsHookResult`、`MountResult`
   都是有含义的枚举，不能把非零一律当成功；能传 `raise_on_fail=True` 的地方就用。
5. **永不提交 `resource/`。** 它是本地/Release 二进制，正常流程下不入库。
6. **反检测开启时不要用 maps 猜结果**；用 RPC 存活检查。
7. **照着 demo 写。** `test/attach_test.py`、`test/launch_fast_test.py`、`albatross-java/plugin_demo/`
   都是可在真机跑通的端到端示例。
8. **版本。** 4.0.0 新增了上文列出的 trace / hook events / async RPC / CModule 接口；旧服务端对新
   RPC 可能返回 `NO_HANDLE`，客户端在文档说明处会降级（例如 async 调用回退同步）。

---

## 14. 法律、社区与许可证

本工具仅用于授权范围内的安全研究、测试与教学。测试任何系统或应用前必须获得明确授权；未经授权
的访问或修改可能违反法律法规。

- QQ 群：**478564202**
- 插件开发参考：<https://github.com/AlbatrossHook/HideApp>
- 许可证：Apache License 2.0，见 [LICENSE](LICENSE)。

*© 2025 AlbatrossServer Project. 仅供研究使用。*
