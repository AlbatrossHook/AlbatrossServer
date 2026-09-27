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
