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

import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.agent.DynamicPluginManager;
import qing.albatross.agent.PluginMessage;
import qing.albatross.annotation.ConstructorBackup;
import qing.albatross.annotation.ConstructorHook;
import qing.albatross.annotation.ExecutionOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.core.InstructionCallback;
import qing.albatross.core.InstructionListener;
import qing.albatross.core.InvocationContext;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.server.UnixRpcInstance;
import qing.albatross.server.UnixRpcServer;
import qing.albatross.common.ThreadConfig;

public class AppInjectAgent extends UnixRpcInstance implements AppApi, InstructionCallback {

  public static AppInjectAgent v() {
    return SingletonHolder.instance;
  }

  private AppInjectAgent() {
  }

  static final int CLASS_NO_FIND = -1;
  static final int METHOD_NO_FIND = -2;

  @Override
  public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
    if (dexPc == 0)
      PluginMessage.send("onEnter:" + method.getName(), new Exception(self == null ? "null" : self.toString()));
    else
      PluginMessage.send("M[" + dexPc + "] " + method.getName());
  }

  Map<Integer, InstructionListener> listeners = new HashMap<>();
  int keyCount = 0;

  @Override
  public int hookMethod(String className, String methodName, int numArgs, String args, int dexPc) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return CLASS_NO_FIND;
    }
    if (args == null) {
      try {
        Method method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs);
        InstructionListener listener = listeners.get(dexPc);
        Albatross.hookInstruction(method, dexPc, this);
        int key = keyCount++;
        listeners.put(key, listener);
        return key;
      } catch (NoSuchMethodException e) {
        return METHOD_NO_FIND;
      }
    }
    return 0;
  }

  @Override
  public boolean unhookMethod(int listenerId) {
    InstructionListener listener = listeners.remove(listenerId);
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




  static class SingletonHolder {
    @SuppressLint("StaticFieldLeak")
    static AppInjectAgent instance = new AppInjectAgent();
  }

  static int initFlags;

  public static boolean loadLibrary(int albatrossInitFlags, String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    initFlags = albatrossInitFlags;
    ThreadConfig.notTraceMe();
    Albatross.log("AppInjectAgent.loadLibrary:" + Albatross.currentProcessName());
    Albatross.initRpcClass(UnixRpcServer.class);
    AppInjectAgent injectEntry = AppInjectAgent.v();
    UnixRpcServer unixRpcServer = injectEntry.createServer(null, true);
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
        if (Albatross.currentApplication() != null) {
          appCreateInit("attach");
        }
      } else {
        PluginMessage.registerPluginMethod();
      }
    }

    return appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags) == 0;
  }

  private static void appCreateInit(String logName) {
    if ((initFlags & FLAG_LOG) != 0) {
      if ((initFlags & REDIRECT_LOG) != 0) {
        PluginMessage.redirectLog(logName + "_app");
      }
      PluginMessage.setLogger(null, logName + "_" + Albatross.currentProcessName(), (initFlags & CLEANUP_LOG) != 0);
      Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
        Albatross.log("exception occur:" + t.getName(), e);
        System.exit(1);
      });
    }
  }

  public static int appendPlugin(String pluginDexPath, String pluginLibrary, String className, String pluginParams, int pluginFlags) {
    DynamicPluginManager instance = DynamicPluginManager.getInstance();
    AlbatrossPlugin plugin = instance.appendPlugin(pluginDexPath, pluginLibrary, className, pluginParams, pluginFlags);
    if (plugin == null)
      return 1;
    Application application = Albatross.currentApplication();
    if (application != null) {
      if (plugin.load(AppInjectAgent.v())) {
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


  @Override
  protected Class<?> getApi() {
    return AppApi.class;
  }

  @TargetClass
  static class InstrumentationHook {

    @MethodBackup
    static native void callApplicationOnCreate(Instrumentation instrumentation, Application app);

    @MethodHook
    static void callApplicationOnCreate$Hook(Instrumentation instrumentation, Application app) {
      if (!isApplicationOnCreateCalled) {
        isApplicationOnCreateCalled = true;
        appCreateInit("launch");
        Albatross.syncAppClassLoader();
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.beforeApplicationCreate(app);
        }
        callApplicationOnCreate(instrumentation, app);
        Albatross.syncAppClassLoader();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.afterApplicationCreate(app);
        }
      } else {
        callApplicationOnCreate(instrumentation, app);
      }
    }
  }

  @TargetClass(targetExec = ExecutionOption.DO_NOTHING, hookerExec = ExecutionOption.DO_NOTHING)
  static class InstrumentationConstructorHook {
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
