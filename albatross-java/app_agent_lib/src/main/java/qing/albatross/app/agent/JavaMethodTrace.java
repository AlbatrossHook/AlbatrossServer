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

import static qing.albatross.agent.InjectAgentBase.ALREADY_HOOK;
import static qing.albatross.agent.InjectAgentBase.CLASS_NOT_FIND;
import static qing.albatross.agent.InjectAgentBase.HOOK_FAIL;
import static qing.albatross.agent.InjectAgentBase.HOOK_SUCCESS;
import static qing.albatross.agent.InjectAgentBase.METHOD_NOT_FIND;

import android.os.Looper;

import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import qing.albatross.core.Albatross;
import qing.albatross.core.CallFrame;
import qing.albatross.core.MethodCallHook;
import qing.albatross.core.MethodHookCallback;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.tracker.DefaultSinker;
import qing.albatross.tracker.EventType;
import qing.albatross.tracker.MethodCallContext;
import qing.albatross.tracker.MethodReturnContext;
import qing.albatross.tracker.OceanSinker;
import qing.albatross.tracker.OceanTracker;

/**
 * 「动态 hook 一个 Java 方法 + 每次调用期间 trace 它的执行流, 方法退出即 untrace」。
 *
 * <p>生命周期(与 native trace 的 enter→follow arm / leave→disarm 同构):
 * <ol>
 *   <li>安装: 免签名动态 hook 目标方法(trampoline 路线), 并把 app 类方法拉回解释器
 *       ({@link OceanTracker#syncTrace()}, 否则事件不派发);</li>
 *   <li>每次调用进入(beforeCall): 当前线程还没在追就 arm 一轮 OceanTracker 线程级追踪
 *       (事件集见 {@link #ALLOWED_EVENTS}), 递归/重入按深度配对, 只在最外层 arm;</li>
 *   <li>方法退出(afterCall): 最外层退出即 disarm, 该轮追踪产物已经全部产生;</li>
 *   <li>卸载: {@link #untrace} 只摘本特征挂上去的那一层回调
 *       ({@link MethodCallHook#unHook(MethodHookCallback)}), 不影响同方法上其它 dyn hook 层。</li>
 * </ol>
 *
 * <p>产物走既有日志通道: sinker 是 {@link DefaultSinker}(方法与参数、按调用深度缩进),
 * 事件行经 OceanLogger.log 输出 —— 默认 logcat(tag Albatross), 注入带 FLAG_LOG 时是
 * 应用侧滚动文件(se_logger 指定目录/baseName, flush_log 落盘)。
 *
 * <p>与既有 Java trace RPC 的关系: traceCall/traceReturn 是"装一次追整个窗口"(进程级会话,
 * 手动/窗口停); 本特征按目标方法的**每次调用**开合一个线程级窗口, timeout/maxEvents
 * 只作单次调用的兜底上限。追踪窗口本身仍是进程级共享的(OceanTracker 既有设计):
 * 并发调用/嵌套会共享事件计数与超时。
 *
 * <p>坑见 doc/pitfalls/pitfall-java-method-trace-per-invocation-20261006.md
 */
public final class JavaMethodTrace {

  /**
   * 允许的事件位: 显式屏蔽 EXEC(1, →kDexPcMoved) 与 DUMP(0x80)。
   * 带 kDexPcMoved 的 AddListener/RemoveListener 在 ART 34+ 会遍历所有线程栈
   * (UpdateNeedsDexPcEventsOnStack), 只能在"其它线程静止"的上下文里执行 —— 本特征的
   * arm/disarm 就跑在被 hook 方法的调用路径上, 绝不能带上该事件位。见
   * src/android/instrumentation.cpp 头部注释与 doc/pitfalls/README.md 的 INS 栈遍历条目。
   */
  public static final int ALLOWED_EVENTS = EventType.CALL | EventType.RETURN | EventType.BLOCK
      | EventType.FILE_READ | EventType.FIELD_WRITE;
  /** events 传 0 时的默认事件集 */
  public static final int DEFAULT_EVENTS = EventType.CALL | EventType.RETURN;
  /** untrace 时有在途调用、且最后一次 afterCall 迟迟不来的兜底摘除延时 */
  private static final long UNHOOK_FALLBACK_MS = 5000;

  /** 安装中的目标: key = Albatross.methodToString(method)(含完整签名, 重载不撞) */
  private static final Map<String, Target> TARGETS = new ConcurrentHashMap<>();
  private static final Object LOCK = new Object();
  private static volatile boolean engineWhitelisted;

  /** 事件行输出器工厂: 默认 {@link DefaultSinker}(false) —— 经 OceanLogger 走 logcat / FLAG_LOG 文件 */
  public interface SinkerFactory {
    OceanSinker create();
  }

  private static final SinkerFactory DEFAULT_SINKER_FACTORY = LogSinker::new;
  private static volatile SinkerFactory sinkerFactory = DEFAULT_SINKER_FACTORY;

  /**
   * 换 sinker 工厂(null = 复位默认日志 sinker)。想自建缓冲/自定义过滤(如只留目标方法自身的调用树)
   * 时用; 对之后安装的目标生效, 已安装目标沿用安装时的 sinker。
   */
  public static void setSinkerFactory(SinkerFactory factory) {
    sinkerFactory = factory == null ? DEFAULT_SINKER_FACTORY : factory;
  }

  private JavaMethodTrace() {
  }

  /** 单线程上目标方法的调用状态(ThreadLocal) */
  private static final class Armed {
    /** 本线程上目标方法的调用深度(递归/重入配对) */
    int depth;
    /** 当前线程的 tracer 是本特征 arm 的(而不是别人的会话) */
    boolean owner;
    /** 主线程: 已投递停止、还没执行(期间重入则沿用这一轮, 不再重复 arm) */
    boolean stopPending;
  }

  private static final class Target {
    final String key;
    final Method method;
    final OceanSinker sinker;
    final MethodHookCallback callback = new TraceCallback(this);
    final ThreadLocal<Armed> armed = new ThreadLocal<Armed>() {
      @Override
      protected Armed initialValue() {
        return new Armed();
      }
    };
    final AtomicInteger live = new AtomicInteger();
    final AtomicInteger invocations = new AtomicInteger();
    final AtomicBoolean removed = new AtomicBoolean();
    volatile MethodCallHook hook;
    volatile int events;
    volatile int timeoutMs;
    volatile int maxEvents;
    /** untrace 已请求: 后续调用不再 arm(在途调用仍正常退出配对) */
    volatile boolean cancelled;

    Target(String key, Method method, OceanSinker sinker, int events, int timeoutMs, int maxEvents) {
      this.key = key;
      this.method = method;
      this.sinker = sinker;
      this.events = events;
      this.timeoutMs = timeoutMs;
      this.maxEvents = maxEvents;
    }
  }

  /**
   * 安装/更新按方法调用的 trace。
   *
   * @return {@link qing.albatross.agent.InjectAgentBase} 的 hook 家族返回码:
   *         0 成功 / 1 同目标已安装(参数已更新, 下一次调用生效) / -1 类找不到 /
   *         -2 方法找不到(含构造器) / -3 安装失败(事件位全被屏蔽或 hook 失败)
   */
  public static int install(String className, String methodName, int numArgs, String args,
      int events, int timeoutMs, int maxEvents) {
    int wanted = events == 0 ? DEFAULT_EVENTS : (events & ALLOWED_EVENTS);
    if (wanted == 0) {
      Albatross.log("traceJavaMethod: 事件位全被屏蔽(EXEC/DUMP 不在支持范围), events=" + events);
      return HOOK_FAIL;
    }
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null)
      return CLASS_NOT_FIND;
    Member member;
    try {
      member = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
    } catch (NoSuchMethodException e) {
      return METHOD_NOT_FIND;
    }
    if (!(member instanceof Method))
      return METHOD_NOT_FIND; // 与动态 hook 同口径: 构造器不支持
    Method method = (Method) member;
    String key = Albatross.methodToString(method);
    synchronized (LOCK) {
      Target exist = TARGETS.get(key);
      if (exist != null) {
        /* 同目标重复安装: 幂等更新参数(类比 native trace 对同目标的 rearm), 下一次调用生效 */
        exist.events = wanted;
        exist.timeoutMs = timeoutMs;
        exist.maxEvents = maxEvents;
        OceanTracker.setTraceMaxEvents(maxEvents);
        return ALREADY_HOOK;
      }
      if (!OceanTracker.init(0))
        return HOOK_FAIL;
      ensureEngineWhitelisted();
      Target target = new Target(key, method, sinkerFactory.create(), wanted, timeoutMs, maxEvents);
      MethodCallHook hook = Albatross.hookMethod(method, target.callback);
      if (hook == null)
        return HOOK_FAIL;
      target.hook = hook;
      TARGETS.put(key, target);
      OceanTracker.setTraceMaxEvents(maxEvents);
      /* app 类方法要拉回解释器才会派发事件(与 tryTrace 的 traceMe+syncTrace 同一步) */
      OceanTracker.syncTrace();
    }
    Albatross.log("traceJavaMethod: " + key + " events=0x" + Integer.toHexString(wanted)
        + " timeoutMs=" + timeoutMs + " maxEvents=" + maxEvents);
    return HOOK_SUCCESS;
  }

  /**
   * 卸载按方法调用的 trace: 摘本特征那一层回调 + 清理追踪状态。
   * 有在途调用时延后到最后一个调用退出(在途轮次的 afterCall 会自行 disarm)。
   *
   * @return 是否命中一个已安装目标(与 dynUnhookMethod 的 true=摘掉了 语义一致)
   */
  public static boolean untrace(String className, String methodName, int numArgs, String args) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null)
      return false;
    Member member;
    try {
      member = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
    } catch (NoSuchMethodException e) {
      return false;
    }
    if (!(member instanceof Method))
      return false;
    String key = Albatross.methodToString(member);
    Target target = TARGETS.remove(key);
    if (target == null)
      return false;
    target.cancelled = true; // 在途调用退出后不再 arm
    if (target.live.get() == 0) {
      removeLayer(target); // 不在执行路径上, 直接摘
    } else {
      /* 有在途调用: 正常由最后一次 afterCall 投递摘除; 这里加延时兜底,
         防 live 计数被异常路径(别的回调层抛异常打断 dispatchAfter)卡住。 */
      Albatross.getMainHandler().postDelayed(() -> removeLayer(target), UNHOOK_FALLBACK_MS);
    }
    return true;
  }

  /** 状态(JSON): 已安装目标 + 进程级窗口状态, 供脚本/测试断言 */
  public static String status() {
    List<String> keys = new ArrayList<>(TARGETS.keySet());
    Collections.sort(keys);
    StringBuilder sb = new StringBuilder(256);
    sb.append("{\"count\":").append(keys.size()).append(",\"targets\":[");
    boolean first = true;
    for (String key : keys) {
      Target target = TARGETS.get(key);
      if (target == null)
        continue;
      if (!first)
        sb.append(',');
      first = false;
      sb.append("{\"target\":");
      appendJsonString(sb, key);
      sb.append(",\"events\":").append(target.events)
          .append(",\"timeout_ms\":").append(target.timeoutMs)
          .append(",\"max_events\":").append(target.maxEvents)
          .append(",\"invocations\":").append(target.invocations.get())
          .append(",\"live\":").append(target.live.get())
          .append(",\"cancelled\":").append(target.cancelled)
          .append(",\"removed\":").append(target.removed.get())
          .append('}');
    }
    int reason = OceanTracker.getStopReason();
    sb.append("],\"trace_running\":").append(OceanTracker.isTraceRunning())
        .append(",\"stop_reason\":").append(reason)
        .append(",\"stop_reason_name\":");
    appendJsonString(sb, OceanTracker.stopReasonName(reason));
    sb.append(",\"window_events\":").append(OceanTracker.getWindowEventCount())
        .append(",\"window_timeout_ms\":").append(OceanTracker.getTraceTimeout())
        .append(",\"window_max_events\":").append(OceanTracker.getTraceMaxEvents())
        .append('}');
    return sb.toString();
  }

  /**
   * 默认输出 sinker: 行格式与 trace_call 一致({@link DefaultSinker}), 但滤掉
   * **dyn hook 调用路径上的框架自身调用** —— arm 发生在 trampoline 回调里, 原方法体
   * 走 invokeOriginal 的反射备份路径(MethodCallHook.invokeOriginalMethod → Method.invoke),
   * 这些行既不是目标方法体的内容、又占窗口相当大一块(实测 50 次叶子调用的窗口 = 134 事件:
   * 其中分发/反射 ~37、JDK 装箱/集合等 ~46)。想更严格(只留目标方法自身的调用树),
   * 用 {@link #setSinkerFactory} 换自己的 sinker(见 skill references/java-trace.md)。
   * 窗口里仍能看到目标方法自己的 entry 行(备份方法解释执行时的 kMethodEntered)。
   */
  private static final class LogSinker extends DefaultSinker {

    LogSinker() {
      super(false);
    }

    @Override
    public void call(MethodCallContext context, Member member) {
      if (isInvocationPath(member))
        return;
      super.call(context, member);
    }

    @Override
    public void ret(MethodReturnContext context, Member member, int dexPc, Object returnValue) {
      if (isInvocationPath(member))
        return;
      super.ret(context, member, dexPc, returnValue);
    }

    @Override
    public void retPrimitive(MethodReturnContext context, Member member, int dexPc,
        Class<?> returnType, long rawValue) {
      if (isInvocationPath(member))
        return;
      super.retPrimitive(context, member, dexPc, returnType, rawValue);
    }
  }

  /** dyn hook 分发与反射备份调用路径上的框架自身调用(见 LogSinker 注释) */
  private static boolean isInvocationPath(Member member) {
    String cls = member.getDeclaringClass().getName();
    return cls.startsWith("qing.albatross.core.") || cls.startsWith("java.lang.reflect.");
  }

  /**
   * 加白本引擎自己的调用: arm/disarm 链(JavaMethodTrace/OceanTracker)发生在被追窗口之内,
   * 不加白每轮窗口尾部都会多出几行框架自身的调用记录(默认 OceanTracker.init 已给
   * Albatross/SinkerDelegate 等加白, 但这两个类不在其列)。
   */
  private static void ensureEngineWhitelisted() {
    if (engineWhitelisted)
      return;
    synchronized (LOCK) {
      if (engineWhitelisted)
        return;
      boolean oceanChanged = OceanTracker.addWhiteClass(OceanTracker.class);
      boolean selfChanged = OceanTracker.addWhiteClass(JavaMethodTrace.class);
      Albatross.log("traceJavaMethod 引擎加白: OceanTracker=" + oceanChanged
          + " JavaMethodTrace=" + selfChanged);
      engineWhitelisted = true;
    }
  }

  /** 摘除 trampoline 上本特征那一层回调(幂等) */  private static void removeLayer(Target target) {
    if (!target.removed.compareAndSet(false, true))
      return;
    MethodCallHook hook = target.hook;
    if (hook == null)
      return;
    try {
      hook.unHook(target.callback);
      Albatross.log("untraceJavaMethod: " + target.key
          + " (invocations=" + target.invocations.get() + ")");
    } catch (Throwable e) {
      Albatross.log("untraceJavaMethod fail: " + target.key, e);
    }
  }

  /**
   * 投递摘除: native 卸载会等在途调用 drain(dyn_quiesce), 直接在 trampoline 路径里调用
   * 会自我等待, 所以一律挪到执行路径之外(与 stop 走主线程投递同一个理由)。
   */
  private static void scheduleRemove(Target target) {
    Albatross.getMainHandler().post(() -> removeLayer(target));
  }

  /**
   * 退出 disarm: 与 {@link OceanTracker#requestStop} 同策略 —— 主线程上拆 tracer
   * 不安全(栈上还有插桩帧), 投递到主线程稍后执行; 其它线程没有可投递的 Looper,
   * 直接停当前线程(既有的超时停止路径同样这么做)。
   */
  private static void stopCurrentThread(Armed armed) {
    if (Looper.myLooper() == Looper.getMainLooper()) {
      armed.stopPending = true;
      Albatross.getMainHandler().post(() -> {
        /* 投递期间可能又进入了目标方法: 让新的一轮在它自己的退出点再投递 */
        if (armed.stopPending && armed.depth == 0) {
          armed.stopPending = false;
          OceanTracker.stopTraceMe();
        }
      });
    } else {
      OceanTracker.stopTraceMe();
    }
  }

  private static void appendJsonString(StringBuilder sb, String value) {
    sb.append('"');
    for (int i = 0; i < value.length(); i++) {
      char c = value.charAt(i);
      if (c == '"' || c == '\\')
        sb.append('\\').append(c);
      else if (c < 0x20)
        sb.append(' ');
      else
        sb.append(c);
    }
    sb.append('"');
  }

  /** 进入 arm / 退出 disarm 的回调 */
  private static final class TraceCallback extends MethodHookCallback {

    private final Target target;

    TraceCallback(Target target) {
      this.target = target;
    }

    @Override
    public boolean beforeCall(CallFrame frame) {
      /* 回调不能抛: dispatchBefore/dispatchAfter 的异常会打断同方法上其它回调层 */
      try {
        target.live.incrementAndGet();
        if (target.cancelled)
          return true; // 卸载中: 不再 arm, 计数保持配对
        Armed armed = target.armed.get();
        if (armed.depth != 0 && !OceanTracker.isCurrentThreadTraced()) {
          /* 上一轮 afterCall 缺席(别的回调层抛异常打断 dispatchAfter 等): 配平自愈,
             否则本线程此后永远 arm 不起来 */
          armed.depth = 0;
          armed.owner = false;
          armed.stopPending = false;
        }
        if (armed.depth++ == 0) {
          target.invocations.incrementAndGet();
          OceanTracker.setTraceMaxEvents(target.maxEvents);
          if (OceanTracker.isCurrentThreadTraced()) {
            /* 已在追: 别人的会话不碰; 也可能是本特征在主线程上已投递停止、还没执行 —— 沿用该轮 */
            armed.owner = armed.stopPending;
            armed.stopPending = false;
          } else {
            armed.owner = OceanTracker.traceMe(target.sinker, target.events, target.timeoutMs);
          }
        }
      } catch (Throwable e) {
        Albatross.log("java trace arm fail: " + target.key, e);
      }
      return true;
    }

    @Override
    public void afterCall(CallFrame frame) {
      try {
        Armed armed = target.armed.get();
        if (armed.depth > 0 && --armed.depth == 0 && armed.owner) {
          armed.owner = false;
          stopCurrentThread(armed);
        }
      } catch (Throwable e) {
        Albatross.log("java trace disarm fail: " + target.key, e);
      } finally {
        if (target.live.decrementAndGet() == 0 && target.cancelled)
          scheduleRemove(target);
      }
    }
  }
}
