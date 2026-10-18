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

import static qing.albatross.agent.Const.CLEANUP_LOG;
import static qing.albatross.agent.Const.DEX_LOAD_FAIL;
import static qing.albatross.agent.Const.FLAG_LOG;
import static qing.albatross.agent.Const.REDIRECT_LOG;

import android.annotation.SuppressLint;
import android.app.Application;
import android.app.Instrumentation;
import android.content.Context;
import android.content.pm.ApplicationInfo;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.agent.DynamicPluginManager;
import qing.albatross.agent.InjectAgentBase;
import qing.albatross.agent.PluginMessage;
import qing.albatross.annotation.ConstructorBackup;
import qing.albatross.annotation.ConstructorHook;
import qing.albatross.annotation.DefOption;
import qing.albatross.annotation.ExecutionOption;
import qing.albatross.annotation.FuzzyMatch;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.StaticMethodBackup;
import qing.albatross.annotation.StaticMethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.app.agent.thread.ThreadHook;
import qing.albatross.app.agent.thread.ThreadPoolExecutorH;
import qing.albatross.app.agent.thread.ThrowableH;
import qing.albatross.common.AppMetaInfo;
import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;
import qing.albatross.core.InstructionListener;
import qing.albatross.core.InvocationContext;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.nativehook.AlbNative;
import qing.albatross.nativehook.SearchCallback;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.server.JsonFormatter;
import qing.albatross.server.UnixRpcServer;
import qing.albatross.tracker.DefaultSinker;
import qing.albatross.tracker.EmptySinker;
import qing.albatross.tracker.EventType;
import qing.albatross.tracker.KeyWordSinker;
import qing.albatross.tracker.OceanLogger;
import qing.albatross.tracker.OceanSinker;
import qing.albatross.tracker.OceanTracker;
import qing.albatross.tracker.StringSinker;

public class AppInjectAgent extends InjectAgentBase implements AppApi {

  public static AppInjectAgent v() {
    return SingletonHolder.instance;
  }

  private AppInjectAgent() {
  }


  @Override
  public native void onLibLoad(String lib, String threadName);


  static class MySinker extends DefaultSinker {

  }


  @Override
  public boolean traceCall(boolean onlyMainThread) {
    return tryTrace(new DefaultSinker(onlyMainThread), onlyMainThread, EventType.CALL);
  }

  @Override
  public boolean traceReturn(boolean onlyMainThread, int externFlags) {
    return tryTrace(new DefaultSinker(onlyMainThread), onlyMainThread, EventType.RETURN | externFlags);
  }

  @Override
  public boolean stopTrace() {
    if (!onlyMainThread)
      return OceanTracker.stopTraceGlobal();
    else {
      if (sinker != null) {
        Boolean[] res = new Boolean[]{null};
        Albatross.getMainHandler().post(() -> {
          boolean result = OceanTracker.stopTraceMe();
          synchronized (res) {
            res[0] = result;
            res.notify();
          }
        });
        synchronized (res) {
          try {
            if (res[0] == null)
              res.wait(15000);
          } catch (InterruptedException ignore) {
          }
        }
        return res[0] != null ? res[0] : false;
      }
      return false;
    }
  }

  OceanSinker sinker;
  boolean onlyMainThread;

  @Override
  public boolean traceKeyword(String keyword, boolean mainThread) {
    return tryTrace(new KeyWordSinker(keyword), mainThread, EventType.CALL);
  }

  @Override
  public boolean changeTraceKeyword(String keyword) {
    if (sinker == null) {
      return false;
    }
    if (sinker instanceof KeyWordSinker keyWordSinker) {
      keyWordSinker.changeKeyWord(keyword);
    }
    return false;
  }

  private boolean tryTrace(OceanSinker sinker, boolean mainThread, int event) {
    if (!OceanTracker.init(0))
      return false;
    if (OceanTracker.isCurrentThreadTraced())
      return false;
    if (mainThread) {
      /* 没有 ActivityThread 的进程(load_jvm 之后的原生宿主/无 Activity 环境):
       * getMainHandler() 会 NPE, 也没有可投递的主线程 —— 主线程追踪不可用。 */
      if (Albatross.mainHandlerOrNull() == null)
        return false;
      Boolean[] result = new Boolean[]{null};
      Albatross.getMainHandler().post(() -> {
        if (OceanTracker.traceMe(sinker, event)) {
          synchronized (result) {
            result[0] = true;
            result.notify();
          }
          OceanTracker.syncTrace();
          this.sinker = sinker;
          onlyMainThread = true;
        } else {
          synchronized (result) {
            result[0] = false;
            result.notify();
          }
        }
      });
      synchronized (result) {
        if (result[0] == null) {
          try {
            result.wait(5000);
          } catch (InterruptedException ignore) {
          }
        }
      }
      return result[0] != null ? result[0] : false;
    } else {
      boolean result = OceanTracker.traceGlobal(sinker, event);
      if (result) {
        OceanTracker.syncTrace();
        this.sinker = sinker;
        onlyMainThread = false;
      }
      return result;
    }
  }

  @Override
  public boolean traceString(String keyword, boolean mainThread) {
    return tryTrace(new StringSinker(keyword), mainThread, EventType.CALL);
  }

  @Override
  public boolean traceTest(boolean mainThread) {
    return tryTrace(new EmptySinker(), mainThread, EventType.CALL);
  }

  @Override
  public int traceCount() {
    if (sinker == null)
      return 0;
    return sinker.callCount;
  }

  @Override
  public void setTraceScope(int traceScope) {
    if (OceanTracker.init(0))
      OceanTracker.setTraceScope(traceScope);
  }

  @Override
  public void setTraceTimeout(int timeoutMs) {
    // 追踪窗口配置是进程级的, 任意线程可调; 追踪进行中调用从现在起重新计时
    OceanTracker.setTraceTimeout(timeoutMs);
  }

  @Override
  public void setTraceMaxEvents(int maxEvents) {
    OceanTracker.setTraceMaxEvents(maxEvents);
  }

  @Override
  public String traceStatus() {
    boolean running = OceanTracker.isTraceRunning();
    int reason = OceanTracker.getStopReason();
    /*
     * 窗口已过但目标线程空闲、事件回调还没触发时在这里补停:
     * 主线程追踪要在主线程上停(与 stopTrace 同一路径), 全局追踪任意线程可停。
     */
    if (running && OceanTracker.windowStopReason(-1) != OceanTracker.REASON_NONE) {
      reason = OceanTracker.windowStopReason(-1);
      OceanTracker.noteStopReason(reason);
      /*
       * 只投递停止请求不等待: 主线程可能正忙于被追踪的代码, 别把 RPC 线程卡住。
       * 没有 ActivityThread(原生宿主)时没有可投递的主线程, 只能就地停(同
       * OceanTracker.requestStop 的降级路径)。
       */
      if (!onlyMainThread)
        OceanTracker.stopTraceGlobal();
      else if (Albatross.mainHandlerOrNull() != null)
        Albatross.getMainHandler().post(OceanTracker::stopTraceMe);
      else
        OceanTracker.stopTraceMe();
      running = OceanTracker.isTraceRunning();
    }
    /* events 用窗口计数(所有事件类型); sinker.callCount 只计 CALL/RETURN,
     * 配了 exec/block/字段事件时会少报。sinker 计数另有 traceCount() RPC。 */
    int events = OceanTracker.getWindowEventCount();
    StringBuilder sb = new StringBuilder(160);
    sb.append("{\"running\":").append(running)
        .append(",\"mode\":\"").append(onlyMainThread ? "main" : "global").append('"')
        .append(",\"stop_reason\":").append(reason)
        .append(",\"stop_reason_name\":\"").append(OceanTracker.stopReasonName(reason)).append('"')
        .append(",\"timeout_ms\":").append(OceanTracker.getTraceTimeout())
        .append(",\"max_events\":").append(OceanTracker.getTraceMaxEvents())
        .append(",\"elapsed_ms\":").append(OceanTracker.getWindowElapsedMs())
        .append(",\"events\":").append(events)
        .append('}');
    return sb.toString();
  }

  @Override
  public int traceJavaMethod(String className, String methodName, int numArgs, String args,
                             int events, int timeoutMs, int maxEvents) {
    return JavaMethodTrace.install(className, methodName, numArgs, args, events, timeoutMs, maxEvents);
  }

  @Override
  public boolean untraceJavaMethod(String className, String methodName, int numArgs, String args) {
    return JavaMethodTrace.untrace(className, methodName, numArgs, args);
  }

  @Override
  public String javaMethodTraceStatus() {
    return JavaMethodTrace.status();
  }

  @Override
  public boolean addNotTracePackage(String pkg) {
    return OceanTracker.addWhitePackage(pkg);
  }


  @Override
  public void seLogger(String logDir, String baseName, boolean cleanOld) {
    PluginMessage.setLogger(logDir, baseName, cleanOld);
  }

  @Override
  public void flushLog() {
    PluginMessage.flushLog();
  }

  @Override
  public boolean redirectAppLog(String fileName) {
    return PluginMessage.redirectLog(fileName);
  }

  @Override
  public boolean finishRedirectAppLog() {
    if (PluginMessage.cancelRedirectLog()) {
      PluginMessage.log("rollingLogger finish app log mark");
      Albatross.log("Albatross.log finish app log mark");
      return true;
    }
    return false;
  }

  @Override
  public String getModules(boolean includeSys) {
    List<Object> list = new ArrayList<>();
    AlbNative.enumerateModules((path, addr, offset, idx) -> {
      if (!includeSys) {
        if (!path.startsWith("/data/"))
          return true;
      }
      list.add(new Object[]{path, addr, offset});
      return true;
    });
    return JsonFormatter.fmt(list);
  }


  @Override
  public void watchFunc(String symbol, long address) {
    AlbNative.watchFunc(symbol, address);
  }

  @Override
  public boolean traceNativeFunction(String libName, String symbol, long address,
                                     int timeoutMs, int maxEvents, int flags, String logPath) {
    String path = logPath;
    if (path == null) {
      // 默认落盘到应用 files/native 下, 时间戳命名防覆盖
      path = new File(nativeLogDir(),
          "native_trace_" + new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(new Date())
              + ".log").getAbsolutePath();
    }
    return AlbNative.stalkerTraceFunction(libName, symbol, address, timeoutMs, maxEvents, flags, path);
  }

  @Override
  public boolean stopNativeTrace() {
    return AlbNative.stalkerTraceStop();
  }

  @Override
  public String nativeTraceStatus() {
    return AlbNative.stalkerTraceStatus();
  }

  @Override
  public String nativeTraceDump(int maxBytes) {
    return AlbNative.stalkerTraceDump(maxBytes);
  }

  /** native 日志/trace 落盘目录: 应用 files/native(无 Application 时按包名兜底) */
  private static File nativeLogDir() {
    Application application = Albatross.currentApplication();
    File logDir;
    if (application == null) {
      String packageName = AppMetaInfo.packageName;
      logDir = new File("/data/data/" + packageName + "/files/native");
    } else {
      logDir = new File(application.getFilesDir(), "native");
    }
    if (!logDir.exists()) {
      logDir.mkdirs();
    }
    return logDir;
  }

  @Override
  public void initNativeLog() {
    final SimpleDateFormat DATE_FORMAT = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault());
    String today = DATE_FORMAT.format(new Date());
    AlbNative.hookInit(new File(nativeLogDir(), today + ".txt").getAbsolutePath());
  }

  static SearchCallback loadCallback;

  @Override
  public void watchLibraryLoad(boolean on) {
    if (on) {
      if (loadCallback == null) {
        loadCallback = (libName, handler_ptr, flags, idx) -> {
          if (loadCallback == null)
            return false;
          onLibLoad(libName, ThreadConfig.myId());
          return true;
        };
        AlbNative.registerLibraryCallback(loadCallback, null);
      }
    } else {
      loadCallback = null;
    }
  }


  static class SingletonHolder {
    @SuppressLint("StaticFieldLeak")
    static AppInjectAgent instance = new AppInjectAgent();
  }


  /**
   * 将崩溃异常写入本地文件，所有日志统一放在同一个文件夹
   */
  private static void writeCrashLogToLocal(Context context, String threadName, Throwable throwable) {
    SimpleDateFormat sdf = new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US);
    String timeStr = sdf.format(new Date());

    // 统一崩溃日志根目录，不再按日期分分子文件夹
    File logDir;
    if (context != null)
      logDir = new File(context.getFilesDir(), "crash_logs");
    else if (AppMetaInfo.packageName != null) {
      logDir = new File("/data/data/" + AppMetaInfo.packageName + "/files/crash_logs");
    } else {
      Albatross.log("crash log create failed");
      return;
    }
    if (!logDir.exists()) {
      boolean mkdirSuccess = logDir.mkdirs();
      if (!mkdirSuccess) {
        Albatross.log("crash log directory create failed: " + logDir.getAbsolutePath());
        return;
      }
    }
    // 独立文件：crash_时间戳.log，每条崩溃单独一个文件
    File crashFile = new File(logDir, "crash_" + timeStr + ".log");
    // try-with-resources 自动关闭IO流
    try (FileOutputStream fos = new FileOutputStream(crashFile);
         OutputStreamWriter osw = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
         PrintWriter printWriter = new PrintWriter(osw)) {
      printWriter.println("=============================================");
      printWriter.println("Crash Time: " + timeStr);
      printWriter.println("Crash Thread: " + threadName);
      printWriter.println("=============================================");
      throwable.printStackTrace(printWriter);
      printWriter.flush();

    } catch (Exception ioException) {
      Albatross.log("write crash log file failed", ioException);
    }
  }


  private static void resetExceptionHandler() {
    Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
      Context context = Albatross.currentApplication();
      writeCrashLogToLocal(context, t.getName(), e);
      Albatross.log("exception occur:" + t.getName(), e);
      try {
        Thread.sleep(1200);
      } catch (InterruptedException ex) {
        throw new RuntimeException(ex);
      }
      System.exit(1);
    });
  }

  static void checkAppCreate() {
    Application application = Albatross.currentApplication();
    if (application != null) {
      InstrumentationConstructorHook.checkApplicationCreate();
    } else if (!isNewApplication) {
      Albatross.getMainHandler().postDelayed(AppInjectAgent::checkAppCreate, 1000);
    }
  }


  @TargetClass(className = "android.app.ContextImpl", targetExec = ExecutionOption.DO_NOTHING)
  static class ContextImpl {
    @StaticMethodBackup
    static native Context createAppContext(@FuzzyMatch Object mainThread, Albatross.LoadedApk packageInfo);

    static {
      int r = Albatross.hookClass();
      if (r == 0) {
        Albatross.log("hook ContextImpl fail");
      }
    }
  }

  static int initFlags;
  static Context fakeContext;
  static String injectStatus;

  public static boolean loadLibrary(String extraInfo, int albatrossInitFlags, String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    initFlags = albatrossInitFlags;
    ThreadConfig.notTraceMe();
    Albatross.initRpcClass(UnixRpcServer.class);
    AppInjectAgent injectEntry = AppInjectAgent.v();
    UnixRpcServer unixRpcServer = injectEntry.createServer(null, true);
    Application application = Albatross.currentApplication();

    if (application == null) {
      Instrumentation instrumentation = Albatross.currentInstrumentation();
      if (instrumentation != null) {
        injectStatus = "patch";
        Context context = instrumentation.getContext();
        if (context == null) {
          var thread = Albatross.ActivityThreadH.currentActivityThread();
          ApplicationInfo appInfo = thread.mBoundApplication.appInfo;
          AppMetaInfo.packageName = appInfo.packageName;
          fakeContext = ContextImpl.createAppContext(thread, thread.mBoundApplication.info);
        }
        Albatross.getMainHandler().post(AppInjectAgent::checkAppCreate);
      } else {
        injectStatus = "launch";
      }
      if (extraInfo != null) {
        if (extraInfo.contains(":")) {
          try {
            String[] ss = extraInfo.split(":");
            AppMetaInfo.packageName = ss[0];
            AppMetaInfo.versionCode = Integer.parseInt(ss[1]);
          } catch (Exception e) {
            Albatross.log("parse app meta info fail", e);
          }
        } else {
          AppMetaInfo.signature = extraInfo;
        }
      }
    } else {
      injectStatus = "attach";
      Albatross.setInlineMaxCodeUnits(20);
      Albatross.log("AppInjectAgent attach:" + Albatross.currentPackageName());
      if (extraInfo != null && !extraInfo.contains(":")) {
        AppMetaInfo.signature = extraInfo;
      }
    }
    resetExceptionHandler();
    if (unixRpcServer == null) {
      Albatross.log("create server fail");
      PluginMessage.registerPluginMethod();
      OceanLogger.registerLogger();
    } else {
      if ((albatrossInitFlags & FLAG_LOG) != 0) {
        try {
          PluginMessage.setMessageSender(injectEntry);
        } catch (Exception e) {
          throw new RuntimeException(e);
        }
        try {
          OceanLogger.registerLogger(PluginMessage.class.getDeclaredMethod("log", String.class));
        } catch (NoSuchMethodException e) {
          Albatross.log("registerLogger fail", e);
        }
      } else {
        PluginMessage.registerPluginMethod();
        OceanLogger.registerLogger();
      }
    }
    if (application != null) {
      appContextCreateInit(injectStatus, application);
    } else if (fakeContext != null) {
      appContextCreateInit(injectStatus, fakeContext);
    }
    Albatross.log("AppInjectAgent " + injectStatus + ":" + AppMetaInfo.packageName);
    return appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags) == 0;
  }

  private static void initLog(String logName) {
    if ((initFlags & FLAG_LOG) != 0) {
      if ((initFlags & REDIRECT_LOG) != 0) {
        PluginMessage.redirectLog(logName + "_app");
      }
      PluginMessage.setLogger(null, logName + "_albatross_" + Albatross.currentProcessName(), (initFlags & CLEANUP_LOG) != 0);
      try {
        if (ThreadHook.watchThread) {
          Albatross.log("try hook thread");
          int r = Albatross.hookClass(ThreadHook.class);
          Albatross.log("hook thread result：" + r);
          Albatross.hookClass(ThreadPoolExecutorH.class);
        } else {
          Albatross.log("skip hook thread");
        }
      } catch (Throwable e) {
        Albatross.log("hook thread fail", e);
      }
    }
  }

  static boolean isCallContext;

  private static void appContextCreateInit(String logName, Context app) {
    if (isCallContext)
      return;
    isCallContext = true;
    resetExceptionHandler();
    AppMetaInfo.fetchFromContext(app);
    if ((initFlags & FLAG_LOG) == 0)
      return;
    if (logName != null)
      if (!PluginMessage.isLogInit())
        initLog(logName);
  }

  public static int appendPlugin(String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    DynamicPluginManager instance = DynamicPluginManager.getInstance();
    int[] reason = new int[1];
    AlbatrossPlugin plugin = instance.appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags, reason);
    if (plugin == null)
      return reason[0];
    Application application = Albatross.currentApplication();
    if (application != null) {
      if (plugin.load(AppInjectAgent.v())) {
        Class<? extends Application> applicationClass = application.getClass();
        plugin.beforeNewApplicationCall(applicationClass.getClassLoader(), applicationClass.getName(), application.getBaseContext());
        plugin.afterNewApplicationCall(application);
        plugin.beforeApplicationCreateCall(application);
        plugin.afterApplicationCreateCall(application);
      } else {
        return DEX_LOAD_FAIL;
      }
    } else {
      Instrumentation instrumentation = Albatross.currentInstrumentation();
      if (instrumentation != null) {
        /**
         at xxxx.XxxxApplication.attachBaseContext(SourceFile:16777544)
         at android.app.Application.attach(Application.java:361)
         at android.app.Instrumentation.newApplication(Instrumentation.java:1302)
         at android.app.LoadedApk.makeApplicationInner(LoadedApk.java:1545)
         at android.app.LoadedApk.makeApplicationInner(LoadedApk.java:1463)
         at android.app.ActivityThread.handleBindApplication(ActivityThread.java:7539)
         at android.app.ActivityThread.-$$Nest$mhandleBindApplication(Unknown Source:0)
         at android.app.ActivityThread$H.handleMessage(ActivityThread.java:2428)
         */
        Context context = instrumentation.getContext();
        if (context == null) {
          context = fakeContext;
        }
        if (context == null) {
          var thread = Albatross.ActivityThreadH.currentActivityThread();
          context = ContextImpl.createAppContext(thread, thread.mBoundApplication.info);
          fakeContext = context;
        }
        if (plugin.load(AppInjectAgent.v())) {
          plugin.beforeNewApplicationCall(null, null, context);
        } else {
          return DEX_LOAD_FAIL;
        }
      }
    }
    return 0;
  }

  public static boolean disablePlugin(String pluginDexPath, String pluginClassName) {
    return DynamicPluginManager.getInstance().disablePlugin(pluginDexPath, pluginClassName);
  }

  public static boolean unloadPluginDex(String pluginDexPath) {
    return DynamicPluginManager.getInstance().unloadPluginDex(pluginDexPath);
  }


  static boolean isApplicationOnCreateCalled = false;
  static boolean isNewApplication = false;


  @Override
  protected Class<?> getApi() {
    return AppApi.class;
  }


  @TargetClass(targetExec = ExecutionOption.DO_NOTHING, hookerExec = ExecutionOption.DO_NOTHING)
  static class InstrumentationHook {

    @MethodBackup(option = DefOption.VIRTUAL)
    private native static Application newApplication(Instrumentation instrumentation, ClassLoader cl, String className, Context context);

    @MethodHook(option = DefOption.VIRTUAL)
    public static Application newApplication$Hook(Instrumentation instrumentation, ClassLoader cl, String className, Context context) {
      if (!isNewApplication) {
        isNewApplication = true;
        Albatross.setInlineMaxCodeUnits(20);
        appContextCreateInit(injectStatus, context);
        Albatross.log("begin call plugin beforeNewApplication");
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            plugin.beforeNewApplication(cl, className, context);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " beforeNewApplication err", e);
          }
        }
        Albatross.log("begin call app newApplication");
        Application application = newApplication(instrumentation, cl, className, context);
        Albatross.log("begin call plugin afterNewApplication");
        resetExceptionHandler();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            plugin.afterNewApplication(application);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " afterNewApplication err", e);
          }
        }
        return application;
      }
      return newApplication(instrumentation, cl, className, context);
    }

    @MethodBackup(option = DefOption.VIRTUAL)
    static native void callApplicationOnCreate(Instrumentation instrumentation, Application app);

    @MethodHook(option = DefOption.VIRTUAL)
    static void callApplicationOnCreate$Hook(Instrumentation instrumentation, Application app) {
      if (!isApplicationOnCreateCalled) {
        isApplicationOnCreateCalled = true;
        Albatross.syncAppClassLoader();
        Albatross.log("begin call plugin beforeApplicationCreate");
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.beforeApplicationCreateCall(app);
        }
        Albatross.log("begin call app callApplicationOnCreate");
        callApplicationOnCreate(instrumentation, app);
        Albatross.syncAppClassLoader();
        resetExceptionHandler();
        Albatross.log("begin call plugin afterApplicationCreate");
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.afterApplicationCreateCall(app);
        }
      } else {
        callApplicationOnCreate(instrumentation, app);
      }
      resetExceptionHandler();
    }
  }


  static boolean hookInstrumentation(Class<? extends Instrumentation> instrumentationClass) {
    try {
      //instance method
      Method newApplication = ReflectUtils.findMethod(instrumentationClass, "newApplication", ClassLoader.class, String.class, Context.class);
      //instance method
      Method callApplicationOnCreate = ReflectUtils.findMethod(instrumentationClass, "callApplicationOnCreate", Application.class);
      Albatross.hookInstruction(newApplication, 0, new InstructionListener(true) {

        @Override
        public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
          if (!isNewApplication) {
            isNewApplication = true;
            Albatross.setInlineMaxCodeUnits(20);
            Context context = invocationContext.getParamObject(3, Context.class);
            String className = invocationContext.getParamObject(2, String.class);
            ClassLoader cl = invocationContext.getParamObject(1, ClassLoader.class);
            appContextCreateInit(injectStatus, context);
            Albatross.log("begin call plugin beforeNewApplication");
            Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
            for (AlbatrossPlugin plugin : pluginTable.values()) {
              try {
                plugin.beforeNewApplication(cl, className, context);
              } catch (Throwable e) {
                Albatross.log("call " + plugin.pluginName() + " beforeNewApplication err", e);
              }
            }
            Albatross.log("begin call app newApplication");
          }

        }

        @Override
        public void onReturn(Member method, Object ret, int dexPc, InvocationContext invocationContext) {
          Albatross.log("begin call plugin afterNewApplication:" + ret);
          Application application = (Application) ret;
          resetExceptionHandler();
          Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
          for (AlbatrossPlugin plugin : pluginTable.values()) {
            try {
              plugin.afterNewApplication(application);
            } catch (Throwable e) {
              Albatross.log("call " + plugin.pluginName() + " afterNewApplication err", e);
            }
          }
        }
      });


      Albatross.hookInstruction(callApplicationOnCreate, 0, new InstructionListener(true) {
        Application app;

        @Override
        public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
          if (!isApplicationOnCreateCalled) {
            isApplicationOnCreateCalled = true;
            Albatross.syncAppClassLoader();
            Albatross.log("begin call plugin beforeApplicationCreate by hookInstruction");
            Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
            Application app = invocationContext.getParamObject(1, Application.class);
            this.app = app;
            for (AlbatrossPlugin plugin : pluginTable.values()) {
              plugin.beforeApplicationCreateCall(app);
            }
            Albatross.log("begin call app callApplicationOnCreate");
          } else {
            this.app = null;
          }

        }

        @Override
        public void onReturn(Member method, Object ret, int dexPc, InvocationContext invocationContext) {
          Albatross.syncAppClassLoader();
          resetExceptionHandler();
          if (this.app != null) {
            Albatross.log("begin call plugin afterApplicationCreate");
            Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
            for (AlbatrossPlugin plugin : pluginTable.values()) {
              plugin.afterApplicationCreateCall(app);
            }
            resetExceptionHandler();
            this.app = null;
          }
        }
      });
      Albatross.log("hook instrumentation:" + instrumentationClass.getName());
      return true;
    } catch (NoSuchMethodException e) {
      Albatross.log("hook instrumentation err", e);
    }
    return false;
  }


  @TargetClass(targetExec = ExecutionOption.DO_NOTHING, hookerExec = ExecutionOption.DO_NOTHING)
  static class InstrumentationConstructorHook {


    @StaticMethodHook(targetClass = Instrumentation.class)
    static native Application newApplication(Class<?> clazz, Context context);

    @StaticMethodHook(targetClass = Instrumentation.class)
    public static Application newApplication$Hook(Class<?> clazz, Context context) {
      if (!isNewApplication) {
        isNewApplication = true;
        appContextCreateInit("launch", context);
        Albatross.log("begin call plugin beforeNewApplication from class");
        Albatross.setInlineMaxCodeUnits(20);
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            plugin.beforeNewApplication(clazz.getClassLoader(), clazz.getName(), context);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " beforeNewApplication err", e);
          }
        }
        Albatross.log("begin call app newApplication by class");
        Application application = newApplication(clazz, context);
        Albatross.log("begin call plugin afterNewApplication from class");
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            plugin.afterNewApplication(application);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " afterNewApplication err", e);
          }
        }
        return application;
      }
      return newApplication(clazz, context);
    }


    static void checkApplicationCreate() {
      if (!isNewApplication) {
        isNewApplication = true;//fakeContext=null;
        Application application1 = Albatross.currentApplication();
        Context context = application1.getBaseContext();
        appContextCreateInit("launch", context);
        Albatross.log("application create and  call plugin beforeNewApplication from " + injectStatus);
        Albatross.setInlineMaxCodeUnits(20);
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        Class<?> clazz = application1.getClass();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            if (!plugin.beforeNewApplicationCall)
              plugin.beforeNewApplicationCall(clazz.getClassLoader(), clazz.getName(), context);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " beforeNewApplication err", e);
          }
        }
        Albatross.log("begin call plugin afterNewApplication from class");
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          try {
            if (!plugin.afterNewApplicationCall)
              plugin.afterNewApplicationCall(application1);
          } catch (Throwable e) {
            Albatross.log("call " + plugin.pluginName() + " afterNewApplication err", e);
          }
        }
      }
      if (!isApplicationOnCreateCalled) {
        isApplicationOnCreateCalled = true;
        Albatross.syncAppClassLoader();
        Application application = Albatross.currentApplication();
        Albatross.log("begin call plugin beforeApplicationCreate from init");
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.beforeApplicationCreateCall(application);
        }
        Albatross.log("begin call plugin afterApplicationCreate");
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.afterApplicationCreateCall(application);
        }
      }
    }


    @ConstructorBackup
    static native void init$Backup(Instrumentation instrumentation);

    @ConstructorHook
    static void init(Instrumentation instrumentation) throws AlbatrossErr {
      if (Albatross.containsFlags(Albatross.FLAG_ANTI_DETECTION)) {
        Albatross.hookClass(ThrowableH.class);
      }
      int res = Albatross.hookObject(InstrumentationHook.class, instrumentation);
      init$Backup(instrumentation);
      if (res == Albatross.CLASS_ALREADY_HOOK) {
        Albatross.log("get new instrumentation:" + instrumentation.getClass().getName());
        Albatross.getMainHandler().postDelayed(InstrumentationConstructorHook::checkApplicationCreate, 1000);
      }
    }

  }

  public static void init() {
    Albatross.log("AppInjectAgent.init");
    Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
    for (AlbatrossPlugin plugin : pluginTable.values()) {
      if (plugin.load(AppInjectAgent.v())) {
        plugin.beforeMakeApplication();
      } else {
        Albatross.log("plugin load return false:" + plugin.getClass());
        return;
      }
    }
    try {
      Albatross.hookClass(InstrumentationConstructorHook.class, Instrumentation.class);
    } catch (AlbatrossErr e) {
      throw new RuntimeException(e);
    }
  }

  public static String dumpJavaThreads() {
    StringBuilder stringBuilder = new StringBuilder(1024);
    // 获取所有线程及其堆栈
    Map<Thread, StackTraceElement[]> allThreads = Thread.getAllStackTraces();
    stringBuilder.append("========== 共 ").append(allThreads.size()).append(" 个线程 ==========\n");
    for (Map.Entry<Thread, StackTraceElement[]> entry : allThreads.entrySet()) {
      Thread thread = entry.getKey();
      StackTraceElement[] stackTrace = entry.getValue();
      // 打印线程基本信息
      stringBuilder.append("线程名称: ").append(thread.getName()).append("\n");
      stringBuilder.append("线程ID: ").append(thread.getId()).append("\n");
      stringBuilder.append("状态: ").append(thread.getState()).append("\n");
      stringBuilder.append("是否守护线程: ").append(thread.isDaemon()).append("\n");
      stringBuilder.append("优先级: ").append(thread.getPriority()).append("\n");
      // 可选：打印堆栈（建议仅在 DEBUG 模式下开启）
      stringBuilder.append("堆栈跟踪:\n");
      for (StackTraceElement ste : stackTrace) {
        stringBuilder.append("\tat ").append(ste.toString()).append("\n");
      }
      stringBuilder.append("----------------------------------------");
    }
    return stringBuilder.toString();
  }
}
