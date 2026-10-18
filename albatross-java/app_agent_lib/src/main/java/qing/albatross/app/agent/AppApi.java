/*
 * Copyright 2025 QingWan (qingwanmail@foxmail.com)
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package qing.albatross.app.agent;

import qing.albatross.server.AsyncRpc;
import qing.albatross.server.Broadcast;

public interface AppApi {

  String getPackageName();

  @Broadcast
  void send(String content, String exception);

  @Broadcast
  void onLibLoad(String lib, String threadName);

  boolean traceCall(boolean onlyMainThread);

  boolean traceReturn(boolean onlyMainThread, int extraFlags);

  boolean stopTrace();

  boolean traceKeyword(String keyword, boolean mainThread);

  boolean changeTraceKeyword(String keyword);

  boolean traceString(String keyword, boolean mainThread);

  boolean traceTest(boolean mainThread);

  int traceCount();

  void setTraceScope(int traceScope);

  /**
   * 追踪窗口时长(毫秒): 到点自动停止, 0 = 不限时。
   * 默认 60000 兜底(未调用过本方法时); 追踪进行中调用同样生效(从现在起重新计时)。
   */
  void setTraceTimeout(int timeoutMs);

  /** 事件数上限(0 = 不限): 抓到该数量事件后自动停止 */
  void setTraceMaxEvents(int maxEvents);

  /**
   * 追踪状态(JSON 字符串): running/stop_reason(0 无·1 超时·2 上限)/timeout_ms/
   * max_events/elapsed_ms/events。窗口已过但事件回调还没触发时, 本查询会补停。
   */
  String traceStatus();

  /**
   * 动态 hook 一个 Java 方法, 并在每次调用期间 trace 它的执行流:
   * 进入方法时对该线程 arm 一轮 Java 方法级 trace(OceanTracker, 与 traceCall 同一引擎),
   * 方法退出即 disarm —— 单次调用就是一个追踪窗口, 递归/多线程按调用配对,
   * timeoutMs/maxEvents 只作单次调用的兜底上限。
   * 产物走既有日志通道(sinker 为 DefaultSinker, 方法与参数、按调用深度缩进):
   * 默认 logcat(tag Albatross), 注入带 FLAG_LOG 时是应用侧滚动文件(见 seLogger/flushLog)。
   * 追踪窗口本身仍是进程级共享(并发调用共享事件计数与超时)。
   *
   * @param className  目标类名(按应用类加载器查找, 与 dynHookMethod 同口径)
   * @param methodName 方法名; numArgs/args 消除重载歧义(同 findMethod)
   * @param events     EventType 位掩码, 0 = CALL|RETURN; EXEC(1)/DUMP(0x80) 不支持会被屏蔽
   *                   (kDexPcMoved 的监听器增删在 ART 34+ 要停世界, 不能出现在执行路径上)
   * @param timeoutMs  单次调用窗口上限: -1 = 默认 60s 兜底, 0 = 不限时
   * @param maxEvents  单次调用窗口事件数上限, 0 = 不限
   * @return 0 成功 / 1 同目标已安装(参数已更新, 下次调用生效) / -1 类找不到 /
   *         -2 方法找不到(含构造器) / -3 安装失败
   */
  int traceJavaMethod(String className, String methodName, int numArgs, String args,
                      int events, int timeoutMs, int maxEvents);

  /**
   * 卸载 traceJavaMethod 安装的按方法 trace: 只摘本特征那一层动态 hook 回调,
   * 不影响同方法上其它 dyn hook 层(dynHookMethod 等); 有在途调用时延后到该调用退出执行。
   *
   * @return 是否命中一个已安装目标
   */
  boolean untraceJavaMethod(String className, String methodName, int numArgs, String args);

  /**
   * 按方法 trace 的状态(JSON): count/targets[{target,events,timeout_ms,max_events,
   * invocations,live,cancelled,removed}], 以及进程级窗口状态
   * trace_running/stop_reason/stop_reason_name/window_events/window_timeout_ms/window_max_events。
   */
  String javaMethodTraceStatus();


  boolean addNotTracePackage(String pkg);

  void seLogger(String logDir, String baseName, boolean cleanOld);

  void flushLog();

  boolean redirectAppLog(String fileName);

  boolean finishRedirectAppLog();

  String getModules(boolean includeSys);

  void watchFunc(String symbol, long address);

  /**
   * 内置默认 native trace(寄存器级 + 访存字节, C++ 实现): 追踪一个 native 函数并记录
   * 运行过程(call/ret/block/exec + 参数/返回值/执行寄存器 + 访存读/写的数据字节),
   * 系统库事件被过滤; 结束(超时/上限/手动停)自动落盘到 logPath。
   *
   * <p>访存字节: 访存指令在其 EXEC 行下多打一行 mem —— 读侧是访问地址处读到的数据,
   * store 是从源寄存器/立即数重建的写入数据(W* = 源不可得, 显示写前快照), 宽度按
   * 访问宽度、上限 64 字节; 默认开启, 用 flags bit1 关闭。
   *
   * @param libName   目标库名(子串匹配即可, 如 "libtarget.so"); address!=0 时忽略
   * @param symbol    目标符号名; address!=0 时忽略
   * @param address   目标函数地址(0 = 按 libName+symbol 解析)
   * @param timeoutMs 窗口毫秒: -1 默认 60s 兜底, 0 不限时
   * @param maxEvents 事件数上限, 0 = 不限; 按引擎事件计数(含被过滤的系统库事件),
   *                  实际记录数见 nativeTraceStatus 的 appended
   * @param flags     bit0 = 只记录主线程; bit1 = 不记录访存字节(默认记录);
   *                  bit2 = 延迟登记(目标库未加载时先等加载, 加载后自动开始,
   *                  等待中状态见 nativeTraceStatus 的 pending)
   * @param logPath   落盘文件绝对路径; null = 不落盘(结果走 nativeTraceDump)
   * @return 是否启动成功(含"已登记等待加载"); 换目标在进程内不支持, 返回 false
   */
  @AsyncRpc
  boolean traceNativeFunction(String libName, String symbol, long address,
                              int timeoutMs, int maxEvents, int flags, String logPath);

  /** 停止默认 native trace 并落盘(含取消延迟登记); 未启动返回 false */
  boolean stopNativeTrace();

  /**
   * 默认 native trace 状态(JSON): running/started/pending/state/target/log_path/
   * stop_reason/stop_reason_name/timeout_ms/max_events/engine_events/appended/
   * dropped/readable/ring_cells/mem_bytes/file_written; 延迟等待中另有
   * lib/symbol/offset。已停未落盘时本查询会补写文件。
   */
  String nativeTraceStatus();

  /** 格式化的 trace 文本(运行过程); maxBytes&gt;0 时截断; 未启动返回空串 */
  String nativeTraceDump(int maxBytes);

  void initNativeLog();

  void watchLibraryLoad(boolean on);

}
