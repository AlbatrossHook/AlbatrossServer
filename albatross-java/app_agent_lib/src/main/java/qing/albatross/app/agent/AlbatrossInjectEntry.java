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

import android.annotation.SuppressLint;
import android.app.Application;
import android.app.Instrumentation;

import java.util.Map;

import qing.albatross.agent.AlbatrossPlugin;
import qing.albatross.agent.DynamicPluginManager;
import qing.albatross.annotation.ConstructorBackup;
import qing.albatross.annotation.ConstructorHook;
import qing.albatross.annotation.ExecOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.server.UnixRpcInstance;
import qing.albatross.server.UnixRpcServer;

public class AlbatrossInjectEntry extends UnixRpcInstance implements AppApi {

  public static AlbatrossInjectEntry v() {
    return SingletonHolder.instance;
  }

  private AlbatrossInjectEntry() {
  }

  static class SingletonHolder {
    @SuppressLint("StaticFieldLeak")
    static AlbatrossInjectEntry instance = new AlbatrossInjectEntry();
  }


  public static boolean loadLibrary(int flags, String dexPath, String dexLib, String className, String pluginParams, int pluginFlags) {
    Albatross.log("AlbatrossInjectEntry.loadLibrary");
    Albatross.initRpcClass(UnixRpcServer.class);
    UnixRpcServer unixRpcServer = AlbatrossInjectEntry.v().createServer(null, true);
    if (unixRpcServer == null) {
      Albatross.log("create server fail");
    }
    return appendPlugin(dexPath, dexLib, className, pluginParams, pluginFlags) == 0;
  }

  public static int appendPlugin(String dexPath, String dexLib, String className, String pluginParams, int pluginFlags) {
    AlbatrossPlugin plugin = DynamicPluginManager.getInstance().appendPlugin(dexPath, dexLib, className, pluginParams, pluginFlags);
    if (plugin == null)
      return 1;
    Application application = Albatross.currentApplication();
    if (application != null) {
      if (plugin.load()) {
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
  public String getPackageName() {
    Application application = Albatross.currentApplication();
    if (application != null) {
      return application.getPackageName();
    }
    return null;
  }

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
        Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.beforeApplicationCreate(app);
        }
        callApplicationOnCreate(instrumentation, app);
        for (AlbatrossPlugin plugin : pluginTable.values()) {
          plugin.afterApplicationCreate(app);
        }
      } else {
        callApplicationOnCreate(instrumentation, app);
      }
    }
  }

  @TargetClass(targetExec = ExecOption.DO_NOTHING, hookerExec = ExecOption.DO_NOTHING)
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
    Albatross.log("AlbatrossInjectEntry.init");
    Map<String, AlbatrossPlugin> pluginTable = DynamicPluginManager.getInstance().getPluginCache();
    for (AlbatrossPlugin plugin : pluginTable.values()) {
      if (plugin.load()) {
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
