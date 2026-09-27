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
package qing.albatross.agent;

import android.app.Application;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

import qing.albatross.annotation.ExecutionOption;
import qing.albatross.common.SafeToString;
import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;
import qing.albatross.core.InstructionListener;
import qing.albatross.core.InvocationContext;
import qing.albatross.nativehook.AlbNative;
import qing.albatross.nativehook.DlInfo;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.search.SearchClassCallback;
import qing.albatross.server.JsonFormatter;
import qing.albatross.server.UnixRpcInstance;

public abstract class InjectAgentBase extends UnixRpcInstance implements InjectApi {

  Map<String, InstructionListener> listeners = new HashMap<>();

  @Override
  public void setToStringConfig(int length, boolean showBytes) {
    SafeToString.setMaxTotalLength(length, showBytes);
  }

  @Override
  protected Class<?>[] getApis() {
    return new Class[]{InjectApi.class, getApi()};
  }

  @Override
  public String getClassFields(String clsName, boolean application) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(clsName);
    } else {
      clz = Albatross.findClass(clsName);
    }
    if (clz == null) {
      return null;
    }
    Field[] fields = clz.getDeclaredFields();
    StringBuilder builder = new StringBuilder();
    for (Field field : fields) {
      builder.append(field.getName()).append(":").append(field.getType()).append("\n");
    }
    return builder.toString();
  }

  @Override
  public String getClassMethods(String clsName, boolean application) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(clsName);
    } else {
      clz = Albatross.findClass(clsName);
    }
    if (clz == null) {
      return null;
    }
    Method[] methods = clz.getDeclaredMethods();
    StringBuilder builder = new StringBuilder();
    for (Method method : methods) {
      builder.append(Albatross.methodToString(method)).append("\n");
    }
    return builder.toString();
  }

  @Override
  public String readFile(String path) {
    BufferedReader br = null;
    StringBuilder sb = new StringBuilder();
    try {
      FileInputStream fis = new FileInputStream(path);
      br = new BufferedReader(new InputStreamReader(fis));
      String line;
      while ((line = br.readLine()) != null) {
        sb.append(line).append("\n");
      }
      return sb.toString();
    } catch (Exception e) {
      Albatross.log("read local file maps error", e);
      return null;
    } finally {
      try {
        if (br != null) br.close();
      } catch (IOException ignored) {
      }
    }
  }


  @Override
  public String findMethod(String className, String methodName, int numArgs, String args) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return "class not find";
    }
    try {
      Member method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
      return Albatross.methodToString(method);
    } catch (NoSuchMethodException e) {
      return "method not find";
    }
  }

  static final int HOOK_SUCCESS = 0;
  static final int ALREADY_HOOK = 1;
  static final int CLASS_NOT_FIND = -1;
  static final int METHOD_NOT_FIND = -2;
  static final int HOOK_FAIL = -3;

  static class AgentInstructionListener extends InstructionListener {

    boolean safeToString;

    AgentInstructionListener(boolean safeToString) {
      this.safeToString = safeToString;
      traceReturn = true;
    }

    @Override
    public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
      if (dexPc == 0) {
        Object[] args = invocationContext.getArguments();
        if (args != null) {
          if (!safeToString)
            Albatross.log("Enter:" + method.getName() + " " + SafeToString.arrayToString(args) + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
          else
            Albatross.log("Enter:" + method.getName() + " " + Arrays.toString(args) + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
        } else
          Albatross.log("Enter:" + method.getName(), new Exception(ThreadConfig.myId()));
      } else
        Albatross.log("M[" + dexPc + "] " + method.getName() + ":" + invocationContext.smaliString());
    }

    @Override
    public void onReturn(Member method, Object ret, int dexPc, InvocationContext invocationContext) {
      if (ret != null) {
        if (!safeToString)
          Albatross.log("Leave:" + method.getName() + ":" + dexPc + " " + SafeToString.safeToString(ret));
        else {
          String output;
          if (ret instanceof byte[]) {
            try {
              output = new String((byte[]) ret);
            } catch (Exception e) {
              output = ret.toString();
            }
          } else {
            output = ret.toString();
          }
          Albatross.log("Leave:" + method.getName() + ":" + dexPc + " " + output);
        }
      }
    }
  }

  @Override
  public int hookMethod(String className, String methodName, int numArgs, String args, int minDexPc, int maxDexPc, boolean safeToString) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return CLASS_NOT_FIND;
    }
    String key = className + "." + methodName + "|" + numArgs;
    if (listeners.containsKey(key))
      return ALREADY_HOOK;
    try {
      Member method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
      AgentInstructionListener listener = new AgentInstructionListener(safeToString);
      boolean res = Albatross.hookInstruction(method, minDexPc, maxDexPc, listener);
      if (!res)
        return HOOK_FAIL;
      listeners.put(key, listener);
      return HOOK_SUCCESS;
    } catch (NoSuchMethodException e) {
      return METHOD_NOT_FIND;
    }
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
  public void decompileAll() {
    Albatross.decompileAll();
  }

  @Override
  public String printAllClassLoader() {
    return Albatross.getClassLoaderList().toString();
  }


  @Override
  public String dumpAllThreads() {
    return ThreadDumper.dumpAllThreadsIncludingNative();
  }

  @Override
  public String findClass(String className, boolean application, int execMode) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return null;
    }
    if (execMode != ExecutionOption.DO_NOTHING) {
      Albatross.compileClass(clz, execMode);
    }
    return Objects.requireNonNull(clz.getClassLoader()).toString();
  }

  @Override
  public String findSubClass(String className, boolean application) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return null;
    }
    List<Class<?>> subClasses = new ArrayList<>();
    Albatross.searchSubClass((c, l) -> {
      subClasses.add(c);
      return SearchClassCallback.CONTINUE;
    }, clz, SearchClassCallback.SCOPE_ALL);
    return JsonFormatter.fmt(subClasses);
  }

  @Override
  public String hookClass(String className, boolean application, int scope, boolean safeToString) {
    Class<?> clz;
    StringBuilder builder = new StringBuilder();
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return null;
    }
    if ((scope & 3) != 0) {
      Method[] methods = clz.getDeclaredMethods();
      boolean containStatic = (scope & 1) != 0;
      boolean containInstance = (scope & 2) != 0;
      for (Method method : methods) {
        boolean isStatic = Modifier.isStatic(method.getModifiers());
        boolean doHook;
        if (isStatic) {
          doHook = containStatic;
        } else
          doHook = containInstance;
        if (doHook) {
          AgentInstructionListener listener = new AgentInstructionListener(safeToString);
          boolean res = Albatross.hookInstruction(method, 0, 0, listener);
          if (res) {
            String key = Albatross.methodToString(method);
            listeners.put(key, listener);
            builder.append(key).append(";");
          }
        }
      }
    }
    if ((scope & 4) == 4) {
      Constructor<?>[] constructors = clz.getDeclaredConstructors();
      for (Constructor<?> constructor : constructors) {
        boolean isStatic = Modifier.isStatic(constructor.getModifiers());
        if (isStatic)
          continue;
        AgentInstructionListener listener = new AgentInstructionListener(safeToString);
        boolean res = Albatross.hookInstruction(constructor, 0, 0, listener);
        if (res) {
          String key = Albatross.methodToString(constructor);
          listeners.put(key, listener);
          builder.append(key).append(";");
        }
      }
    }
    return builder.toString();
  }


  @Override
  public String unhookClass(String className, boolean application, int scope) {
    Class<?> clz;
    StringBuilder builder = new StringBuilder();
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return "class not find";
    }
    if ((scope & 3) != 0) {
      Method[] methods = clz.getDeclaredMethods();
      boolean containStatic = (scope & 1) != 0;
      boolean containInstance = (scope & 2) != 0;
      for (Method method : methods) {
        boolean isStatic = Modifier.isStatic(method.getModifiers());
        boolean doHook;
        if (isStatic) {
          doHook = containStatic;
        } else
          doHook = containInstance;
        if (doHook) {
          String key = Albatross.methodToString(method);
          InstructionListener listener = listeners.remove(key);
          if (listener != null) {
            listener.unHook();
            builder.append(key).append(";");
          }
        }
      }
    }
    if ((scope & 4) == 4) {
      Constructor<?>[] constructors = clz.getDeclaredConstructors();
      for (Constructor<?> constructor : constructors) {
        boolean isStatic = Modifier.isStatic(constructor.getModifiers());
        if (isStatic)
          continue;
        String key = Albatross.methodToString(constructor);
        InstructionListener listener = listeners.remove(key);
        if (listener != null) {
          listener.unHook();
          builder.append(key).append(";");
        }
      }
    }
    return builder.toString();
  }

  @Override
  public String classLoaders(boolean sync) {
    List<ClassLoader> classLoaders = Albatross.getClassLoaderList();
    if (sync)
      Albatross.syncAppClassLoader();
    return classLoaders.toString();
  }

  @Override
  public String getFunctions(String module) {
    DlInfo dl = AlbNative.openLib(module);
    if (dl == null)
      return "[]";
    List<Object> list = new ArrayList<>();
    dl.enumerateFunctions((symbol, addr, size, idx) -> {
      list.add(new Object[]{symbol, addr, size});
      return true;
    });
    dl.close();
    return JsonFormatter.fmt(list);
  }

  @Override
  public String dumpNativeMethod() {
    Application application = Albatross.currentApplication();
    File logDIr;
    if (application == null) {
      return null;
    }
    logDIr = new File(application.getFilesDir(), "native");
    if (!logDIr.exists()) {
      logDIr.mkdirs();
    }
    final SimpleDateFormat DATE_FORMAT = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault());
    String today = DATE_FORMAT.format(new Date());
    String filePath = logDIr.getAbsolutePath() + "/" + "method_" + today + ".txt";
    if (AlbNative.dumpNativeMethod(filePath))
      return filePath;
    return null;
  }


}
