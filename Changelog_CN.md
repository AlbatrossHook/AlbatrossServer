version 4.0.0
- 新增结构化的 hook 命中记录：进程内环形缓冲（HookEventBuffer）与 hook_events_enable / status / pull / clear，覆盖指令级 hook 与动态 hook（方法、参数、this、返回值、tid）。
- 新增按方法的 Java trace：trace_java_method 在进入方法时 arm OceanTracker、退出即 disarm，配套 untrace_java_method 与 java_method_trace_status；新增 trace 窗口超时、事件数上限与 trace_status。
- 新增内置 native trace：trace_native_function / stop_native_trace / native_trace_status / native_trace_dump，记录 call / ret / exec / block 事件、寄存器现场、访存读写字节，支持系统库过滤与延迟登记。
- 暴露免签名动态 hook：dyn_hook_method / dyn_hook_method_return / dyn_unhook_method / dyn_hook_class / dyn_unhook_class。
- RPC：新增异步调用（MSG_ASYNC_CALL，服务端超时与过载代答）、武装脚本记录/重放、typed 广播自动发现（MSG_APIS v2）与参数签名校验。
- CModule：新增 compile / call / call_v、隔离执行、layout / list / source / symbols / capabilities、annotate / audit / cancel / deadline / timeout 与地址符号化。
- Python：attach / launch 系列新增 AttachFailed 与 raise_on_fail 失败汇总、部署降级守卫、带校验的文件推送/拉取、JVM 加载参数，以及 rwbp 命中事件解析（v1 / v2）。
- 插件：内存 dex 加载支持 APK / JAR 与多 dex（失败回退 DexClassLoader）；新增注入 flag / KPM 链路（setInjectFlags / supportExtendKpm）与 ocean trace AAR 依赖。
- 测试改用 plugin_demo.apk。

version 3.6.1
- 修复注入时未传入设备临时路径（temp_path）的问题。
- 测试新增共享 helper（check_client / hide_albatross），并为测试脚本添加 python path 引导，确保 albatross 与 test 包能正确 import。

version 3.6.0
- 新增 InjectApi 接口与 InjectAgentBase，并配套 Python 端 inject_client，向上层暴露统一的注入 API。
- 新增 adb 连接管理：adb server / 端点探测、设备列表、带冷却与失败隔离及恢复探测的连接协调器，以及连接指标与健康快照。
- 重构原生日志：有界队列、批量写盘、按天滚动与保留，以及丢弃 / 写入错误上报。
- 新增线程 hook 工具：ThreadDumper，以及线程池执行器与未捕获异常的 hook。
- 注入 agent 新增注入标志（inject flags）与路径重定向；destroy 幂等并注册到 atexit。
- shell 命令超时时结束整个进程组。

version 3.5.0
- 新增类 hook API：hook_class / unhook_class，支持静态、实例与构造方法作用域，并可开启 safe tostring。
- 新增 native 库监控 API：获取模块 / 函数、监视函数、监听库加载、dump native 方法及 onLibLoad 回调。
- 新增 read_file / read_maps / read_smaps，以及用于配置 SafeToString 输出的 set_to_string_config。
- 新增 dump_all_threads，dump 目标应用的全部 java 线程。
- system_server 新增：stability_test、clear_uid、set_intercept_all 与 set_app_android_id。
- 新增 mount / umount、launch mount / umount 与 hide_path；新增 set_dex_load_timeout。
- 添加规则时自动补充应用的包名与版本信息；新增 set_app_info / get_app_info。
- 应用进程崩溃时自动将崩溃日志保存到本地。
- 优化系统应用的拦截：支持 Android 13+ 的 PidMap 与 registerReceiver hook，并适配小米的 attachApplicationLocked 变体。
- 插件加载失败时返回具体的失败原因（dex load result）。

version 3.4.0
- 新增授予权限的 API。
- 优化系统应用的拦截。
- 指令 hook 支持 trace 返回值。
- 优化对无线设备的支持。

version 3.3.0
- Rpc 调用改进。
- 优化对 inline 方法的 hook。

version 3.2.0
- 插件新增 beforeNewApplication 与 afterNewApplication 回调方法。
- 优化方法指令的 hook，在应用创建前后实现插件相关方法的回调。
- 新增插件 rpc 调用示例。
- 支持通过读取环境变量获取配置文件。
- 注册插件时同时发送应用的包名与版本信息。

version 3.1.0
- 优化消息发送，新增日志保存与应用日志重定向支持。
- rpc 增加长字符串解析，新增应用注入成功回调。
- 优化测试代码并增加异常捕获。

version 2.1.0
- 通过移除可写可执行内存片段实现反检测。

version 2.0.2:
- rpc 改进。
- 为 rpc 方法添加注解。
- 新增 AlbatrossServerApi。

version 2.0.1:
- 支持监控插件的本地变化，重新编译后自动重新注入。
- 优化 attach，基于 uid 获取应用的所有 java 进程。
- 优化插件的管理、状态切换与方法回调。
- 新增一系列插件相关 api。

version 2.0.0:
- 新增 clean api。
- 新增插件的增删改查 api。
- 支持系统插件。
- 新增 launch fast 注入模式，速度更快。

version 1.0.2:
- Java rpc 调用改进。

version 1.0.1:
- 兼容 window 系统。
- 默认不关闭 Selinux。

version 1.0.0:
- 初始版本。
