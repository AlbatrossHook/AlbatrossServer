# AlbatrossServer

[中文](README_CN.md) · Version **4.0.0**

AlbatrossServer is a root-based Android instrumentation framework. It injects an agent into
application processes (and optionally `system_server`), exposes a line-based RPC service inside
each process, and lets a Python program on the host drive the whole workflow: attach or spawn
injection, Java/native hooking, tracing, in-process C modules, memory watching, plugin
management, and device automation.

> **Disclaimer**: use this project only on devices and applications you own or are explicitly
> authorized to test. Unauthorized use is prohibited.

---

## 1. What you can do (capability map)

| Area | Python entry points | What it does |
|---|---|---|
| Device / ADB | `albatross.get_device()`, `get_device_ids()`, `get_usb_devices()`, `get_health_snapshot()` | select a USB or wireless device, inspect connection health |
| Root service | `device.client` | pushes `albatross_server` + `libalbatross_base.so`, starts the root daemon, creates the adb forward |
| App control | `device.start_app()`, `stop_app()`, `install_if_not_exist()`, `uninstall_package()`, `silence_install()`, `get_user_packages()`, `get_package_uid()` | normal device/app automation |
| Attach injection | `device.attach()`, `attach_with_plugins()`, `attach_with_plugin_ids()` | inject into an already-running Java process |
| Spawn injection | `device.launch_fast()`, `launch_with_plugins()`, legacy `launch()` | start the target with the plugin already registered |
| Plugin management | `device.register_plugin()`, `reload_plugin()`, `remove_plugin()`, `add_plugin_rule()`, `client.clear_plugins()` | push / register / update / remove plugins |
| Java instruction hook | `app.hook_method()`, `unhook_method()`, `hook_class()`, `unhook_class()`, `find_method()` | hook a dex-PC window or a whole class |
| Signature-free dynamic hook | `app.dyn_hook_method()`, `dyn_hook_method_return()`, `dyn_unhook_method()`, `dyn_hook_class()`, `dyn_unhook_class()` | trampoline hook by class/method/arg-count, no caller patch |
| Hook hit records | `app.hook_events_enable()`, `hook_events_status()`, `hook_events_pull()`, `hook_events()`, `hook_events_clear()` | pull structured hit records from an in-process ring buffer |
| Java method trace | `app.trace_call()`, `trace_return()`, `trace_keyword()`, `trace_string()`, `stop_trace()`, `set_trace_timeout()`, `set_trace_max_events()`, `trace_status()`, `trace_java_method()`, `untrace_java_method()`, `java_method_trace_status()` | method-level execution trace via OceanTracker |
| Native trace | `app.trace_native_function()`, `stop_native_trace()`, `native_trace_status()`, `native_trace_dump()` | call/ret/exec/block trace with registers and memory bytes |
| Native inspection | `app.get_modules()`, `app.get_functions()`, `app.watch_func()`, `app.watch_library_load()`, `app.dump_native_method()` | module/function discovery and library-load notifications |
| CModule | `app.cmodule_run/compile/call/call_v/get_symbol/free/run_isolated/...` | compile and run C inside the target process with tcc |
| JVM in a native process | `client.load_jvm()` (both root and injected clients) | create a JVM in a process that has none, then load dex/plugins |
| system_server | `device.system_server_client`, `device.load_system_plugin()`, `client.set_system_server_agent()` | rule/interception management and system plugins |
| Anti-detection / hiding | `AlbatrossInitFlags.FLAG_ANTI_DETECTION`, `InjectFlag.MEMFD`, `InjectFlag.WXORX`, `client.support_extend_kpm()`, `client.hide_path()`, `client.redirect_path()` | reduce injection traces; optional KPM support |
| Memory read/write watch | `client.rwbp_watch_add/del/drain/drain2`, `parse_rwbp_watch_drain()` | kernel-assisted watchpoints (requires the rwbp module) |
| Logging | `app.se_logger()`, `app.flush_log()`, `app.redirect_app_log()`, `app.init_native_log()` | file/logcat logging control |
| Custom RPC | `@rpc_api`, `@broadcast_api`, `RpcClient.create_subscriber()`, `register_broadcast_handler()` | expose your own methods/broadcasts from a plugin |

Everything above is implemented in this repository's `albatross-python` and `albatross-java`
trees; the root service and native library are shipped in `resource/jniLibs/`.

---

## 2. Requirements

### Device

- **Root** (Magisk, APatch or KernelSU). `su -c id` must return `uid=0`.
- **Android 7.0 (API 24) or newer.** The supported/reference range is Android 7–15; newer or
  vendor builds may work but are not guaranteed. Expect ROM-specific differences in
  `system_server` internals.
- ABIs: `arm64-v8a`, `armeabi-v7a`, `x86_64`, `x86`.
- **LSPosed must not be present in the target process.** Disable it before a `launch`/`launch_fast`
  start, and make sure it was not injected before an `attach`; check
  `client.is_lsposed_injected()` first.
- SELinux: the framework patches the policy at runtime (`client.patch_selinux()`); if patching
  fails the client falls back to permissive mode. Do not disable SELinux globally.

### Host

- **Python 3.10+** — the package uses `str | None` (PEP 604) in runtime annotations.
- `pip install -r albatross-python/requirements.txt` (`toml`, `watchdog`).
- `adb` in `PATH`, or set `adb_path` in the config.
- Linux is the tested host. Windows code paths exist but are not regularly tested.

---

## 3. Quick start

### 3.1 Get the `resource` package

The `resource/` directory in git is not a complete runnable payload (it contains placeholders
and possibly stale artifacts). Download the matching release assets (or build them) and lay
them out like this:

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

`device.client` pushes the server binary and library automatically the first time it runs.
The host-side library uses the AARs from `resource/jar` when building the Java modules.

### 3.2 Configure the client

Resolution order for the config file:

1. `ALBATROSS_CONFIG=/path/to/albatross_config.toml`
2. `albatross-python/albatross/albatross_config_local.toml`
3. `~/.albatross/albatross_config.toml` (created on first use)

`resource_dir` resolution order: the `resource_dir` key → `ALBATROSS_RESOURCE_DIR` →
`<repo>/resource`.

```bash
pip install -r albatross-python/requirements.txt
export PYTHONPATH="$PWD/albatross-python:$PWD"
export ALBATROSS_RESOURCE_DIR="$PWD/resource"

python3 - <<'PY'
import albatross
print("albatross", albatross.__version__)
device = albatross.get_device()          # first online device
print(device.serial_no, device.cpu_abi, device.sdk_version, device.is_root)
PY
```

Minimal config file (keep the trailing slash on `resource_dir`; the client concatenates paths):

```toml
resource_dir = "/absolute/path/to/resource/"
# adb_path = "/absolute/path/to/adb"
# server_port = 19088
```

`get_device(Serial)` accepts a USB serial or a wireless endpoint such as `192.168.1.10:5555`.

### 3.3 First injection

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

# Register the plugin and cold-start the target through system_server.
ok = device.launch_fast(pkg, plugin_apk, plugin_class, plugin_params=pkg)
print("launch_fast:", ok)

time.sleep(3)
uid = device.get_package_uid(pkg)
print("java pids:", device.client.get_java_processes_by_uid(uid))
albatross.destroy()      # idempotent; also registered with atexit
```

`launch_fast` force-stops the target, registers the plugin rule and starts the app; do not call
`stop_app`/`start_app` around it. `attach` is the late-injection path for an app that is already
running.

---

## 4. How it works

```text
Host (Python)
  └─ albatross-python
       ├─ adb shell / adb forward
       ├─ albatross_server (root daemon on device, one RPC endpoint)
       │    └─ injects libalbatross_base.so into target processes
       ├─ app_agent.dex (runs in app processes, AppClient endpoint)
       ├─ system_server.dex (runs in system_server, SystemServerClient endpoint)
       └─ plugin APK/JAR/DEX (loaded into the target process)
```

Three RPC endpoints matter in practice:

| Endpoint | How to get it | Use it for |
|---|---|---|
| Root service | `device.client` | injection, plugin registration, `system_server` configuration |
| App process | `client.get_address(pid)` + `device.get_forward_port("localabstract:" + address)` then `AppClient(port, None, name)` | hooks, traces, CModule, app-specific RPC |
| `system_server` | `device.system_server_client` | process control, interception, permission/ID mocking |

The protocol is a binary-framed RPC (`wq` header + call id + payload length). Python methods are
declared with `@rpc_api`; broadcasts use
`@broadcast_api`. A plugin registers its own RPC interface with
`agent.registerApi(this, YourApi.class)` inside `load()`.

---

## 5. Injection modes

| Mode | API | Target state | Returns | Notes |
|---|---|---|---|---|
| Late attach | `device.attach(...)` | app already running | `list[pid]` | injects each Java process and loads the plugin; does not start the app |
| Rule-based spawn | `device.launch_fast(...)` | app stopped/will be started | `bool` | **recommended**; registers the plugin, force-stops and starts the app |
| Plugin spawn | `device.launch_with_plugins(...)` | app will be started | `bool` | for `Plugin` objects already returned by `register_plugin()` |
| Multi-plugin attach | `device.attach_with_plugins(...)` | app running | `list[(pid, Plugin)]` | injects and loads several plugins |
| Attach by id | `device.attach_with_plugin_ids(...)` | app running | `list[(pid, Plugin)]` | loads plugins by registered id |
| Legacy spawn | `device.launch(...)` | app stopped/will be started | `None` | **deprecated** (see `test/launch_test.py`); uses `system_server` interception + launch callbacks |

Important details:

- `attach` only considers Java processes returned by `get_java_processes_by_uid(uid)`. Native-only
  processes need explicit `client.inject_albatross(pid, ...)`.
- Late `attach` cannot replay the real `Application` lifecycle. `beforeMakeApplication` is only
  called for plugins present at agent init; the `before/after*Application*` callbacks may still be
  invoked when a plugin loads late, but the real creation/`onCreate` has already happened. Use
  the `launch*` paths when callback ordering matters.
- `attach`, `launch_fast`, `launch_with_plugins`, `attach_with_plugins` and
  `attach_with_plugin_ids` accept `raise_on_fail=True`; on total failure they raise
  `albatross.exceptions.AttachFailed` with per-stage details instead of silently returning an
  empty list. Use it in automation. The legacy `launch()` does not take this argument.
- `device.init_plugin_env` pushes the `system_server` agent and may restart `system_server` when
  the dex changed (`update_kill_system_server`). Expect a short system restart on upgrades.

---

## 6. Plugin development

A plugin is a Java class extending `qing.albatross.agent.AlbatrossPlugin`. The demo module is
`albatross-java/plugin_demo`.

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
    agent.registerApi(this, MyApi.class);   // optional custom RPC
    return super.load(agent);
  }

  @Override
  public boolean parseParams(String params, int flags) {
    // params comes from plugin_params; return false to fail the load
    return true;
  }

  @Override
  public void beforeNewApplication(ClassLoader cl, String className, android.content.Context context) {
    // earliest Application-construction hook; requires launch/spawn injection
  }

  @Override
  public void beforeApplicationCreate(Application application) {
    // before Application.onCreate()
  }

  @Override
  public void afterApplicationCreate(Application application) {
    // after Application.onCreate()
  }

  @Override
  public void onAttachSystem(Application application) {
    // system plugin only
  }
}

public interface MyApi {
  void toast(String msg);
}
```

Lifecycle summary:

| Callback | When it runs |
|---|---|
| `load(UnixRpcInstance)` | plugin is loaded; register RPC here |
| `parseParams(params, flags)` | load and on config change |
| `beforeMakeApplication()` | agent init, before Application creation (spawn path) |
| `beforeNewApplication(cl, className, context)` / `afterNewApplication(app)` | around `Application` construction; a late plugin load runs them immediately with the current app |
| `beforeApplicationCreate(app)` / `afterApplicationCreate(app)` | around `Application.onCreate()` |
| `onAttachSystem(app)` | system plugin attached to `system_server` |
| `onConfigChange(config, flags)`, `enable()`, `disable()`, `unload()` | runtime management |

Plugin metadata in `AndroidManifest.xml` (used by the manager/demo tooling):

```xml
<meta-data android:name="albatross_plugin" android:value="true" />
<meta-data android:name="plugin_name" android:value="MyPlugin" />
<meta-data android:name="plugin_class" android:value="com.example.plugin.MyPlugin" />
<meta-data android:name="plugin_description" android:value="..." />
<meta-data android:name="plugin_author" android:value="..." />
```

If the plugin ships a native library, override `loadLibrary(String libName)` and call
`System.loadLibrary(libName)` there.

Build and deploy:

```bash
cd albatross-java
./gradlew :plugin_demo:assembleDebug
# output: plugin_demo/build/outputs/apk/debug/plugin_demo-debug.apk

# deploy with the Python client
python3 - <<'PY'
import albatross
from albatross.common import Configuration
d = albatross.get_device()
apk = Configuration.resource_dir + "plugins/plugin_demo.apk"
d.launch_fast("com.example.app", apk, "qing.albatross.plugin.app.DemoPlugin")
PY
```

`plugin_dex` may be a raw `.dex`, a `.jar`, or a multi-dex `.apk`. In anti-detection mode a
`/data/` plugin is loaded from memory; APK/JAR containers are supported in 4.0.0 and fall back
to `DexClassLoader` if memory loading fails.

---

## 7. Python API reference

### 7.1 Module `albatross`

```python
import albatross

albatross.__version__          # "4.0.0"
albatross.get_device(serial)   # AlbatrossDevice; serial may be None (first device)
albatross.get_cached_device(serial)
albatross.remove_device(serial)
albatross.get_device_ids()     # devices reported by adb
albatross.get_usb_devices()
albatross.get_health_snapshot()
albatross.destroy()            # idempotent cleanup
```

### 7.2 `AlbatrossDevice`

Device/ADB: `serial_no`, `get_serial()`, `adb_cmd()`, `shell()`, `su_shell()`, `root_shell()`,
`getprop()`, `is_root`, `is_adb_root`, `sdk_version`, `cpu_abi`, `is_64`, `support_32`,
`debuggable`, `wake_up()`, `home()`, `click()`, `swipe()`, `reboot()`, `setenforce()`,
`is_selinux_on()`.

App management: `get_user_packages()`, `is_app_install()`, `install_if_not_exist()`,
`uninstall_package()`, `silence_install()`, `start_app()`, `stop_app()`, `start_activity()`,
`get_app_main_activity()`, `dump_apk()`, `get_package_info()`, `get_package_uid()`,
`get_package_version_code()`, `get_processes_by_uid()`, `pidof()`.

Files/UI: `push_file()`, `pull_file()`, `delete_file()`, `get_file_md5()`,
`device_file_md5_matches()`, `check_deploy_downgrade()`, `screenshot()`, `dumpui()`,
`get_activity_stack()`, `top_app()`.

Network: `forward()`, `forward_tcp()`, `get_forward_port()`, `remove_forward_port()`,
`get_device_ip()`, `switch_to_ip_connect()`, `switch_to_usb_connect()`.

Injection/plugins: `attach()`, `launch()`, `launch_fast()`, `launch_with_plugins()`,
`attach_with_plugins()`, `attach_with_plugin_ids()`, `register_plugin()`, `reload_plugin()`,
`remove_plugin()`, `load_system_plugin()`, `add_plugin_rule()`, `clear_plugins()`,
`watch_plugin()`.

Flags: `device.app_init_flags` (default `FLAG_LOG | FLAG_CALL_CHAIN | FLAG_INIT_RPC`),
`device.app_inject_flags` (default `KEEP | UNIX`), `device.add_init_flags()`,
`device.add_inject_flags()`.

Cleanup: `device.close()`, `albatross.destroy()`.

### 7.3 `AlbatrossClient` (root service)

Obtained with `device.client`. It manages processes and plugins:

- Injection: `inject_albatross(pid, flags, temp_dir)`, `detach(pid, flags)`,
  `is_injected(pid)`, `get_java_processes_by_uid(uid)`, `get_process_isa(pid)`,
  `get_process_pid(name)`, `process_uid(pid)`.
- Agents/plugins: `set_app_agent()`, `set_system_server_agent()`, `register_plugin()`,
  `delete_plugin()`, `modify_plugin()`, `add_plugin_rule()`, `delete_plugin_rule()`,
  `clear_plugins()`, `load_plugin()`, `load_plugin_by_id()`, `load_dex()`,
  `load_system_plugin()`, `unload_plugin_dex()`.
- App RPC endpoints: `get_address(pid)` → use with
  `device.get_forward_port("localabstract:" + address)`.
- Environment: `patch_selinux()`, `add_selinux_rule()`, `set_inject_flags()`,
  `set_dex_load_timeout()`, `mount()`, `umount()`, `hide_path()`, `redirect_path()`,
  `support_extend_kpm()`.
- Memory watch: `rwbp_watch_add()`, `rwbp_watch_del()`, `rwbp_watch_drain()`,
  `rwbp_watch_drain2()`.
- Launch callbacks: `register_launch_callback()`, `launch_process()`, `launch_callback()`,
  `create_subscriber()`.

### 7.4 `BaseClient` (injected process)

`AppClient` extends `BaseClient`. Common methods:

- Java hooks: `find_method()`, `hook_method()`, `unhook_method()`, `hook_class()`,
  `unhook_class()`, `find_class()`, `find_sub_class()`, `get_class_methods()`,
  `get_class_fields()`.
- Dynamic hooks: `dyn_hook_method()`, `dyn_hook_method_return()`, `dyn_unhook_method()`,
  `dyn_hook_class()`, `dyn_unhook_class()`.
- Hook records: `hook_events_enable()`, `hook_events_status()`, `hook_events_pull()`,
  `hook_events()` (returns `(events, next_cursor)`), `hook_events_clear()`.
- CModule: `cmodule_run()`, `cmodule_compile()`, `cmodule_call()`, `cmodule_call_v()`,
  `cmodule_get_symbol()`, `cmodule_free()`, `cmodule_run_isolated()`, `cmodule_layout()`,
  `cmodule_list()`, `cmodule_source()`, `cmodule_symbols()`, `cmodule_capabilities()`,
  `cmodule_annotate()`, `cmodule_audit()`, `cmodule_cancel()`, `cmodule_deadline()`,
  `cmodule_set_timeout()`, `cmodule_symbolize()`.
- Process/JVM: `getuid()`, `load_jvm()`, `load_lib()`, `register_native_handler()`,
  `dump_all_threads()`, `read_file()`, `read_maps()`, `read_smaps()`.
- Misc: `print_all_class_loader()`, `decompile_all()`, `set_to_string_config()`,
  `get_functions()`.

`hook_method(className, methodName, num_args, args=None, min_dex_pc=0, max_dex_pc=128,
safe_string=False)` returns `InsHookResult` (`HOOK_SUCCESS=0`, `ALREADY_HOOK=1`,
`CLASS_NOT_FIND=-1`, `METHOD_NOT_FIND=-2`, `HOOK_FAIL=-3`).

`args` is **a substring of the method signature** used to disambiguate overloads, not a JNI
descriptor. Call `get_class_methods()` first if the name/arg-count pair is ambiguous; passing
`None` is fine when it is unique.

### 7.5 `AppClient`

App-specific RPC plus tracing:

```python
from albatross.app_client import AppClient, EventType, TraceScope
```

- Package/log: `get_package_name()`, `se_logger()`, `flush_log()`, `redirect_app_log()`,
  `finish_redirect_app_log()`.
- Java trace: `trace_call(only_main_thread)`, `trace_return(only_main_thread, extra_flags=0)`,
  `trace_keyword(keyword, main_thread)`, `trace_string(keyword, main_thread)`,
  `trace_test(main_thread)`, `stop_trace()`, `trace_count()`, `set_trace_scope()`,
  `set_trace_timeout(timeout_ms)`, `set_trace_max_events(max_events)`, `trace_status()`.
- Per-method trace: `trace_java_method(class, method, num_args, args, events=0,
  timeout_ms=-1, max_events=0)`, `untrace_java_method(...)`, `java_method_trace_status()`.
- Native trace: `trace_native_function(lib, symbol, address, timeout_ms, max_events, flags,
  log_path)`, `stop_native_trace()`, `native_trace_status()`, `native_trace_dump(max_bytes=0)`.
- Native inspection: `get_modules(include_sys=False)`, `watch_func()`,
  `watch_library_load()`, `dump_native_method()`, `init_native_log()`.
- Misc: `class_loaders()`, `add_not_trace_package()`, `unshell()`, `finish_unshell()`.

### 7.6 `SystemServerClient`

Obtained with `device.system_server_client`:

`init()`, `init_intercept()`, `get_top_activity()`, `get_front_activity()`,
`get_front_activity_quick()`, `get_all_processes()`, `start_activity()`, `start_app()`,
`set_top_app()`, `force_stop_app()`, `set_intercept_all()`, `set_intercept_app()`,
`add_watch_app()`, `set_app_android_id()`, `clear_uid()`, `get_version()`,
`allow_app_permission()`, `mock_battery_info()`, `mock_lock()`, `stability_test()`.

### 7.7 Connecting to an app process

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
        # ... exercise the app ...
        app.stop_trace()
        print(app.trace_status())
    finally:
        app.close()
```

### 7.8 Custom RPC

Declare the method on a Python client and implement it in the plugin:

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

Broadcasts use `@broadcast_api`; call `client.create_subscriber()` before expecting them.
Methods marked `@rpc_api(arm=True)` are recorded in an arm script and can be replayed after a
process restart via `client.start_arm_recording()` / `device.replay_arm_scripts(uid, client)`.

---

## 8. Tracing, hooking, and CModule recipes

### 8.1 Java method trace

```python
app.set_trace_scope(TraceScope.kApplication | TraceScope.kEntryOnly)
app.set_trace_timeout(20_000)      # 0 = unlimited; default is 60s
app.set_trace_max_events(50_000)   # 0 = unlimited
app.trace_call(only_main_thread=True)
# ... trigger the code path ...
app.stop_trace()
print(app.trace_status())          # JSON: running/stop_reason/elapsed_ms/events
```

For one method, arm on entry and disarm on exit:

```python
from albatross.app_client import EventType

rc = app.trace_java_method(
    "com.example.Foo", "bar", 1, None,
    events=EventType.CALL | EventType.RETURN,
    timeout_ms=10_000,
)
# rc: 0 ok / 1 already installed / -1 class not found / -2 method not found / -3 install failed
...
app.untrace_java_method("com.example.Foo", "bar", 1, None)
```

Notes:

- `EXEC` and `DUMP` event bits are not supported by `trace_java_method`; they are masked out.
- The trace window is process-wide; concurrent `trace_java_method` targets share the event
  counter and timeout.
- Trace output goes through the normal log channel: logcat tag `Albatross`, or a rolling file
  when `FLAG_LOG`/`se_logger` is configured.

### 8.2 Hook hit records

```python
client.hook_events_enable(8192)        # 0 = default 4096; -1 = disable
cursor = 0
while True:
    events, cursor = client.hook_events(cursor)
    for e in events:
        print(e["kind"], e["phase"], e["method"], e.get("args"), e.get("ret"))
    if not events:
        break
client.hook_events_clear()
```

Records are produced by `hook_method` / `dyn_hook_method` / `hook_class` / `dyn_hook_class`.
Recording is off by default; when disabled the hit path costs one volatile read.

### 8.3 Native trace

```python
ok = app.trace_native_function(
    lib_name="libtarget.so",
    symbol="target_func",
    address=0,                 # 0 = resolve by lib+symbol
    timeout_ms=10_000,         # -1 = default 60s, 0 = unlimited
    max_events=0,
    flags=0,                   # bit0 main-thread only; bit1 disable memory bytes; bit2 delayed registration
    log_path="/data/local/tmp/native_trace.log",
)
app.stop_native_trace()
print(app.native_trace_status())   # JSON
print(app.native_trace_dump())
```

`flags bit2` (delayed registration) is useful when the target library is not loaded yet: the
trace starts automatically after the library appears. Only one native trace target per process
is supported.

### 8.4 CModule (compile C inside the target)

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

Entry convention: `usize alb_main(const char *arg, char *out, int out_size)`.

- `cmodule_run()` compiles, calls the entry and **releases the module**. Do not use it for
  scripts that install hooks or register RPC: use `cmodule_compile()` + `cmodule_call()` and
  free explicitly.
- `cmodule_run_isolated()` forks a child: crashes/timeouts are contained, but hooks and memory
  writes do not affect the target.
- `cmodule_set_timeout(handle, ms)` protects against endless loops in `cmodule_call()`.
- Scripts can call the native API from `albatross.h` (`AlbDlopen`, `AlbDlsym`,
  `AlbGetModuleBase`, `AlbStalker*`, `AlbatrossHookFunc`, ...).

### 8.5 Memory watch (rwbp)

```python
from albatross.albatross_client import parse_rwbp_watch_drain2

ok = client.rwbp_watch_add(tid, addr, size, watch_type=3)   # 3 = read + write
raw = client.rwbp_watch_drain2(max_events=64)
batch = parse_rwbp_watch_drain2(raw)
for ev in batch.events:
    print(ev.pc, ev.lr, ev.operation(), ev.value() if ev.is_write else None)
client.rwbp_watch_del()
```

This requires the rwbp kernel module. Events are asynchronous: drain after a delay or poll.
`verified` is a reserved field and is always false; use `blindwin()` (the target page was
opened during the session) as the quality signal.

---

## 9. Flags

### `AlbatrossInitFlags` (client/agent behaviour)

| Flag | Meaning |
|---|---|
| `FLAG_DISABLE_JIT` | disable JIT in the target |
| `FLAG_ANTI_DETECTION` | remove RWX segments, hide injection traces, enable hiding paths |
| `FLAG_FIELD_BACKUP_INSTANCE` / `FLAG_FIELD_BACKUP_STATIC` | back up instance/static fields before hooks |
| `FLAG_INJECT` / `FLAG_INIT_RPC` | internal injection/RPC bootstrap (set by the helpers) |
| `FLAG_CALL_CHAIN` | enable call-chain support |
| `FLAG_INTERPRETER` | force interpreter execution |
| `FLAG_LOG` / `REDIRECT_LOG` | file logging / redirect app logs |

### `InjectFlag` (injection mechanics)

| Flag | Meaning |
|---|---|
| `KEEP` | keep the injected library resident |
| `UNIX` | use a Unix socket for the agent RPC endpoint |
| `MEMFD` | load the library from an anonymous memfd |
| `WXORX` | W^X mode for targets whose seccomp policy forbids RWX mappings |
| `SOCKET`, `DEBUG`, `UNLOAD`, `TEST` | lower-level/legacy switches |

Use `device.add_init_flags()` / `device.add_inject_flags()` to extend the defaults. Changing
inject flags after the root client exists pushes them to the server immediately.

---

## 10. Anti-detection, KPM, and hidden deployment

`AlbatrossDevice.anti_detection` defaults to `True`. It enables `FLAG_ANTI_DETECTION` and the
framework's path hiding/mount cleanup, but it does **not** silently switch every hiding mechanism
on:

- `InjectFlag.MEMFD` must be added explicitly (`device.add_inject_flags(InjectFlag.MEMFD)`); the
  test helper `hide_albatross()` does this when `support_kpm` is false.
- `device.hide_file = True` enables the Android 10+ bind-mount path for agent files (off by
  default).
- `client.support_extend_kpm()` reports whether a KPM module provides stronger hiding
  (`hide_path`, `redirect_path`, smaps zeroing). Supply a loader with
  `device.load_kpm_impl = your_loader` if your device needs one.

**Do not verify injection success by looking at `/proc/<pid>/maps` when anti-detection is on.**
Use `client.ping()` / `is_injected(pid)` / a cheap RPC call instead. Maps-based checks will
produce false negatives; the demo tests explicitly assert that the library path is absent.

---

## 11. Building the Java side

```bash
cd albatross-java

# default: consume the AARs from resource/jar
./gradlew :plugin_demo:assembleDebug
./gradlew :app_agent:assembleDebug
./gradlew :system_agent:assembleDebug

# release variants
./gradlew :plugin_demo:assembleRelease
./gradlew :app_agent:assembleRelease
./gradlew :system_agent:assembleRelease
```

Outputs:

```text
plugin_demo/build/outputs/apk/debug/plugin_demo-debug.apk
app_agent/build/outputs/apk/debug/app_agent-debug.apk
system_agent/build/outputs/apk/debug/system_agent-debug.apk
```

The root client consumes `resource/agent/app_agent.dex` and
`resource/agent/system_server.dex` (single dex files, not APKs). The release package ships
prebuilt ones; if you rebuild the agents yourself, merge the APK's `classes*.dex` into a single
dex with your build tooling and update `resource/agent/` before running the client.

The default and tested build mode for this repository is AAR mode. `settings.gradle.kts` also
contains a source-mode hook (`project.albatross.dir`), but this repository does not ship the
Albatross core sources; use the AARs from the release package unless you maintain that tree
yourself.

---

## 12. Troubleshooting and pitfalls

| Symptom | Likely cause | What to do |
|---|---|---|
| `DeviceNotRoot` | `su` denied / no root | verify `su -c id`; on emulators use an image with real root |
| `NoDeviceFound` | no device / wrong adb server port | `adb devices`; set `adb_path` or `ALBATROSS_ADB_SERVER_PORTS` |
| `PackageNotInstalled` | package missing for user 0 | `device.is_app_install(pkg)` first |
| `attach` returns `[]` | app not running or no Java process | `start_app` and wait; check `get_java_processes_by_uid` |
| `DexLoadResult.DEX_LOAD_FAIL` | agent/plugin mismatch or bad dex | read `/data/local/tmp/albatross.log` and logcat tag `Albatross`; rebuild/reship the plugin |
| `DexLoadResult.DEX_SYSTEM_SERVER_ERR` | `system_server` agent not ready | run `device.init_plugin_env`; check whether `system_server` restarted |
| `InjectResult.INJECT_PROCESS_SLEEPING(-6)` | target frozen/not started | start the app and retry; check `pidof` |
| Plugin callback never fires | late `attach`, `Application` already created | use `launch_fast`/`launch` for early callbacks |
| `hook_method` returns `-2` | overload ambiguity | call `get_class_methods()`, pass a signature substring as `args` |
| `hook_method` returns `-1` | wrong class loader/name | try `find_class()` / `find_sub_class()`; use the app class loader |
| Trace stops immediately | default 60s window elapsed or timeout too small | `set_trace_timeout(ms)`; `trace_status()` shows the reason |
| Trace produces no lines | wrong scope / not main thread / log not configured | `set_trace_scope()`, check `only_main_thread`, use `se_logger`/`FLAG_LOG` |
| Hook records empty | recording disabled | `hook_events_enable()` before installing hooks |
| CModule hook disappears | `cmodule_run` released the module | use `cmodule_compile` + `cmodule_call` and free explicitly |
| CModule compile error | missing include / implicit declaration | include `albatross.h`; check `r.error` |
| `rwbp` no events | kernel module absent or page blind window | `support_extend_kpm()`, check `blindwin()`, drain after a delay |
| `load_jvm` fails | non-Android/static build, or no `BOOTCLASSPATH` | use an Android `USE_LIBC` build and a process that inherited the Android environment |
| `launch` produces nothing | LSPosed injected or interception failed | `client.is_lsposed_injected()`; use `launch_fast` |
| Anti-detection check fails | looking for paths in maps | do not use maps; use RPC `ping`/`is_injected` |

More ground rules:

- **Do not edit `resource/` in git.** It is a local/release payload, not source. The placeholders
  in the repository are not runnable.
- **Match versions.** The server binary, `libalbatross_base.so`, agent dex files and AARs must
  come from the same release. A stale `resource/` is the most common source of silent failures.
- **Clean up.** `AppClient.close()` closes its socket; `device.close()` also removes forwards;
  `albatross.destroy()` is idempotent and registered with `atexit`.
- **Do not double-load an agent.** `inject_albatross` returns `ALREADY` when the process is
  already injected; reload the plugin instead of trying to re-inject.
- **Respect the device.** `launch_fast`, `init_plugin_env` and system-plugin changes can restart
  `system_server`; do not run them in a loop.

---

## 13. For AI agents and automation

If you are an AI writing code against this repository:

1. **Source of truth.** The exact API is in
   `albatross-python/albatross/*.py` (Python), `albatross-java/**/src/main/java/**` (Java), and
   `test/*.py` (working examples). Do not invent method names; when unsure, inspect:
   ```python
   import inspect
   print([m for m in dir(device) if not m.startswith("_")])
   print(inspect.signature(device.attach))
   ```
   RPC methods declared with `@rpc_api` are resolved on **connected instances** via the
   `RpcMeta` metaclass. `hasattr(AppClient, "hook_method")` is false by design; inspect a live
   `app` instance instead.
2. **Minimum viable flow.**
   `get_device → assert is_root → wake_up → launch_fast/attach → client.get_address + forward →
   AppClient → operate → close/destroy`.
3. **Prefer `launch_fast`** for new code; `launch` is deprecated. Use `attach` only when the app
   must keep running.
4. **Check return values.** `DexLoadResult`, `InjectResult`, `SetResult`, `InsHookResult` and
   `MountResult` are enums with meaningful failure codes; do not treat non-zero as success.
   Use `raise_on_fail=True` where available.
5. **Never commit `resource/`.** It contains local/release binaries and is intentionally
   untracked in normal workflows.
6. **Do not guess from maps** when `anti_detection` is on; use RPC liveness checks.
7. **Use the demo as a template.** `test/attach_test.py`, `test/launch_fast_test.py` and
   `albatross-java/plugin_demo/` are end-to-end examples that run against real devices.
8. **Version.** 4.0.0 adds the tracing/hook-event/async-RPC/CModule APIs listed above; older
   servers may return `NO_HANDLE` for new RPC methods. The Python client degrades where
   documented (for example async calls fall back to synchronous calls).

---

## 14. Legal, community, license

This tool is for authorized security research, testing and education only. You must have
explicit permission before testing any system or application. Unauthorized access or
modification may violate laws and regulations.

- QQ group: **478564202**
- Plugin development reference: <https://github.com/AlbatrossHook/HideApp>
- License: Apache License 2.0, see [LICENSE](LICENSE).

*© 2025 AlbatrossServer Project. For research use only.*
