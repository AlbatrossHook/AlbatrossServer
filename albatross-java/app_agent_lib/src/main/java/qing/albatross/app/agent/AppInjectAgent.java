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
import static qing.albatross.agent.Const.FLAG_LOG;
import static qing.albatross.agent.Const.REDIRECT_LOG;

import android.annotation.SuppressLint;
import android.app.Application;
import android.app.Instrumentation;
import android.content.Context;

import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.agent.DynamicPluginManager;
import qing.albatross.agent.PluginMessage;
import qing.albatross.annotation.ConstructorBackup;
import qing.albatross.annotation.ConstructorHook;
import qing.albatross.annotation.DefOption;
import qing.albatross.annotation.ExecutionOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.StaticMethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.app.agent.client.StackManager;
import qing.albatross.common.AppMetaInfo;
import qing.albatross.core.Albatross;
import qing.albatross.core.InstructionListener;
import qing.albatross.core.InvocationContext;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.server.UnixRpcInstance;
import qing.albatross.server.UnixRpcServer;
import qing.albatross.common.ThreadConfig;

public class AppInjectAgent extends UnixRpcInstance implements AppApi {

  public static AppInjectAgent v() {
    return SingletonHolder.instance;
  }

  private AppInjectAgent() {
  }

  static final int HOOK_SUCCESS = 0;
  static final int ALREADY_HOOK = 1;
  static final int CLASS_NOT_FIND = -1;
  static final int METHOD_NOT_FIND = -2;
  static final int HOOK_FAIL = -3;

  static class AgentInstructionListener extends InstructionListener {

    @Override
    public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
      if (dexPc == 0) {
        Object[] args = invocationContext.getArguments();
        if (args != null) {
          Albatross.log("Enter:" + method.getName() + " " + Arrays.toString(args) + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
        } else
          Albatross.log("Enter:" + method.getName(), new Exception(ThreadConfig.myId()));
      } else
        Albatross.log("M[" + dexPc + "] " + method.getName() + ":" + invocationContext.smaliString());
    }
  }


  Map<String, InstructionListener> listeners = new HashMap<>();

  @Override
  public String findMethod(String className, String methodName, int numArgs, String args) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return "class not find";
    }
    if (args == null) {
      try {
        Method method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs);
        return Albatross.methodToString(method);
      } catch (NoSuchMethodException e) {
        return "method not find";
      }
    }
    return "not support";

  }

  @Override
  public int hookMethod(String className, String methodName, int numArgs, String args, int minDexPc, int maxDexPc) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return CLASS_NOT_FIND;
    }
    if (args == null) {
      String key = className + "." + methodName + "|" + numArgs;
      if (listeners.containsKey(key))
        return ALREADY_HOOK;
      try {
        Method method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs);
        AgentInstructionListener listener = new AgentInstructionListener();
        boolean res = Albatross.hookInstruction(method, minDexPc, maxDexPc, listener);
        if (!res)
          return HOOK_FAIL;
        listeners.put(key, listener);
        return HOOK_SUCCESS;
      } catch (NoSuchMethodException e) {
        return METHOD_NOT_FIND;
      }
    }
    return HOOK_FAIL;
  }

  @Override
  public boolean unhookMethod(String className, String methodName, int numArgs, String args) {
    String key = className + "." + methodName + "|" + numArgs;
    InstructionListener listener = listeners.remove(key);
    if (listener != null) {
      listener.unHook();
      return true;
    }
    return false;
  }


  @Override
  public String printAllClassLoader() {
    return Albatross.getClassLoaderList().toString();
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
  public String findClass(String className, boolean application) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return null;
    }
    return Objects.requireNonNull(clz.getClassLoader()).toString();
  }

  @Override
  public String classLoaders(boolean sync) {
    List<ClassLoader> classLoaders = Albatross.getClassLoaderList();
    if (sync)
      Albatross.syncAppClassLoader();
    return classLoaders.toString();
  }


  static class SingletonHolder {
    @SuppressLint("StaticFieldLeak")
    static AppInjectAgent instance = new AppInjectAgent();
  }

  private static void resetExceptionHandler() {
    Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
      Albatross.log("exception occur:" + t.getName(), e);
      System.exit(1);
    });
  }


  static int initFlags;

  public static boolean loadLibrary(String extraInfo, int albatrossInitFlags, String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    initFlags = albatrossInitFlags;
    ThreadConfig.notTraceMe();
    Albatross.initRpcClass(UnixRpcServer.class);
    AppInjectAgent injectEntry = AppInjectAgent.v();
    UnixRpcServer unixRpcServer = injectEntry.createServer(null, true);
    Application application = Albatross.currentApplication();
    if (application == null && extraInfo != null) {
      try {
        String[] ss = extraInfo.split(":");
        AppMetaInfo.packageName = ss[0];
        AppMetaInfo.versionCode = Integer.parseInt(ss[1]);
//        initLog("launch");
      } catch (Exception e) {
        Albatross.log("parse app meta info fail", e);
      }
      Albatross.log("AppInjectAgent launch:" + AppMetaInfo.packageName);
    } else {
      Albatross.log("AppInjectAgent attach:" + Albatross.currentPackageName());
    }
    resetExceptionHandler();
    if (unixRpcServer == null) {
      Albatross.log("create server fail");
      PluginMessage.registerPluginMethod();
    } else {
      if ((albatrossInitFlags & FLAG_LOG) != 0) {
        try {
          PluginMessage.setMessageSender(injectEntry);
        } catch (Exception e) {
          throw new RuntimeException(e);
        }
        if (application != null) {
          appContextCreateInit("attach", application);
        }
      } else {
        PluginMessage.registerPluginMethod();
      }
    }
    return appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags) == 0;
  }

  private static void initLog(String logName) {
    if ((initFlags & FLAG_LOG) != 0) {
      if ((initFlags & REDIRECT_LOG) != 0) {
        PluginMessage.redirectLog(logName + "_app");
      }
      PluginMessage.setLogger(null, logName + "_albatross_" + Albatross.currentProcessName(), (initFlags & CLEANUP_LOG) != 0);
    }
  }

  private static void appContextCreateInit(String logName, Context app) {
    AppMetaInfo.fetchFromContext(app);
    if (!PluginMessage.isLogInit())
      initLog(logName);
  }

  public static int appendPlugin(String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    DynamicPluginManager instance = DynamicPluginManager.getInstance();
    AlbatrossPlugin plugin = instance.appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags);
    if (plugin == null)
      return 1;
    Application application = Albatross.currentApplication();
    if (application != null) {
      if (plugin.load(AppInjectAgent.v())) {
        Class<? extends Application> applicationClass = application.getClass();
        plugin.beforeNewApplication(applicationClass.getClassLoader(), applicationClass.getName(), application.getBaseContext());
        plugin.afterNewApplication(application);
        plugin.beforeApplicationCreate(application);
        plugin.afterApplicationCreate(application);
      } else {
        return 2;
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
        appContextCreateInit("launch", context);
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
          plugin.beforeApplicationCreate(app);
        }
        Albatross.log("begin call app beforeApplicationCreate");
        callApplicationOnCreate(instrumentation, app);
        Albatross.syncAppClassLoader();
        Albatross.log("begin call plugin afterApplicationCreate");
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.afterApplicationCreate(app);
        }
      } else {
        callApplicationOnCreate(instrumentation, app);
      }
      resetExceptionHandler();
    }
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


    @ConstructorBackup
    static native void init$Backup(Instrumentation instrumentation);

    @ConstructorHook
    static void init(Instrumentation instrumentation) throws AlbatrossErr {
      Albatross.hookObject(InstrumentationHook.class, instrumentation);
      init$Backup(instrumentation);
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


}
