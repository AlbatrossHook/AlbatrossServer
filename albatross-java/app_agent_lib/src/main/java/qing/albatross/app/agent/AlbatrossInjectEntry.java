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

import android.app.Application;
import android.app.Instrumentation;

import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.util.HashMap;
import java.util.Map;

import dalvik.system.DexClassLoader;
import qing.albatross.annotation.ConstructorBackup;
import qing.albatross.annotation.ConstructorHook;
import qing.albatross.annotation.ExecOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;

public class AlbatrossInjectEntry {


  static Map<String, AlbatrossInjector> injectorMap;
  static Map<String, DexClassLoader> dexClassLoaderMap;


  public static boolean loadLibrary(int flags, String dexPath, String dexLib, String className, String argString, int argInt) {
    injectorMap = new HashMap<>();
    dexClassLoaderMap = new HashMap<>();
    return appendInjector(dexPath, dexLib, className, argString, argInt) == 0;
  }

  static int appendInjector(String dexPath, String dexLib, String className, String argString, int argInt) {
    String injectorKey = dexPath + className;
    if (injectorMap.containsKey(injectorKey))
      return 1;
    DexClassLoader dexClassLoader = dexClassLoaderMap.get(dexPath);
    String libDir;
    String libName;
    if (dexLib == null || dexLib.length() < 5) {
      libDir = null;
      libName = null;
    } else {
      int i = dexLib.lastIndexOf('/');
      libDir = dexLib.substring(0, i);
      libName = dexLib.substring(i + 4, dexLib.length() - 3);
    }
    if (dexClassLoader == null) {
      dexClassLoader = new DexClassLoader(dexPath, null, libDir, AlbatrossInjectEntry.class.getClassLoader());
      dexClassLoaderMap.put(dexPath, dexClassLoader);
    }
    AlbatrossInjector injector;
    try {
      Class<AlbatrossInjector> initClass = (Class<AlbatrossInjector>) dexClassLoader.loadClass(className);
      Constructor<AlbatrossInjector> constructor = initClass.getDeclaredConstructor(String.class, String.class, int.class);
      constructor.setAccessible(true);
      injector = constructor.newInstance(libName, argString, argInt);
      injectorMap.put(injectorKey, injector);
    } catch (ClassNotFoundException e) {
      Albatross.log("inject", e);
      return 2;
    } catch (IllegalAccessException e) {
      Albatross.log("inject", e);
      return 3;
    } catch (InstantiationException e) {
      Albatross.log("inject", e);
      return 4;
    } catch (InvocationTargetException e) {
      Albatross.log("inject", e.getCause());
      return 5;
    } catch (NoSuchMethodException e) {
      Albatross.log("inject", e);
      return 6;
    }
    Application application = Albatross.currentApplication();
    if (application != null) {
      if (injector.load()) {
        injector.beforeApplicationCreate(application);
        injector.afterApplicationCreate(application);
      } else {
        return 7;
      }
    }
    return 0;
  }

  static boolean isApplicationOnCreateCalled = false;

  @TargetClass
  static class InstrumentationHook {

    @MethodBackup
    static native void callApplicationOnCreate(Instrumentation instrumentation, Application app);

    @MethodHook
    static void callApplicationOnCreate$Hook(Instrumentation instrumentation, Application app) {
      if (!isApplicationOnCreateCalled) {
        isApplicationOnCreateCalled = true;
        for (AlbatrossInjector injector : injectorMap.values()) {
          injector.beforeApplicationCreate(app);
        }
        callApplicationOnCreate(instrumentation, app);
        for (AlbatrossInjector injector : injectorMap.values()) {
          injector.afterApplicationCreate(app);
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
    for (AlbatrossInjector injector : injectorMap.values()) {
      if (injector.load()) {
        injector.beforeMakeApplication();
      } else {
        Albatross.log("injector load return false:" + injector.getClass());
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
