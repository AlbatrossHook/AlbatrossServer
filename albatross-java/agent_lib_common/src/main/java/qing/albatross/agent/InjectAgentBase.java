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
import qing.albatross.core.CallFrame;
import qing.albatross.core.InstructionListener;
import qing.albatross.core.InvocationContext;
import qing.albatross.core.MethodCallHook;
import qing.albatross.core.MethodHookCallback;
import qing.albatross.nativehook.AlbNative;
import qing.albatross.nativehook.DlInfo;
import qing.albatross.reflection.ReflectUtils;
import qing.albatross.search.SearchClassCallback;
import qing.albatross.server.JsonFormatter;
import qing.albatross.server.UnixRpcInstance;

public abstract class InjectAgentBase extends UnixRpcInstance implements InjectApi {

  Map<String, InstructionListener> listeners = new HashMap<>();
  Map<String, MethodCallHook> dynHooks = new HashMap<>();

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

  /** hook 家族 RPC(hook/dynHook/traceJavaMethod 等)共用的返回码 */
  public static final int HOOK_SUCCESS = 0;
  /** 同目标已安装(幂等更新参数) */
  public static final int ALREADY_HOOK = 1;
  public static final int CLASS_NOT_FIND = -1;
  public static final int METHOD_NOT_FIND = -2;
  public static final int HOOK_FAIL = -3;

  /**
   * 内置回调的线程重入闸：命中回调自身（拿调用栈、SafeToString、logcat）可能再触发
   * 被 hook 的方法（如 hook Method.getName 后栈展开/hashCode 会再调 getName），不挡
   * 就是无限递归把进程顶死。回调链上的再入直接放行，不记录不打日志。
   */
  static final ThreadLocal<Boolean> HOOK_REENTRANCY = ThreadLocal.withInitial(() -> Boolean.FALSE);

  static boolean hookReentrancyEnter() {
    if (HOOK_REENTRANCY.get()) {
      return false;
    }
    HOOK_REENTRANCY.set(Boolean.TRUE);
    return true;
  }

  static void hookReentrancyExit() {
    HOOK_REENTRANCY.set(Boolean.FALSE);
  }

  static class AgentInstructionListener extends InstructionListener {

    boolean safeToString;

    AgentInstructionListener(boolean safeToString) {
      this.safeToString = safeToString;
      traceReturn = true;
    }

    @Override
    public void onEnter(Member method, Object self, int dexPc, InvocationContext invocationContext) {
      if (!hookReentrancyEnter()) {
        return;
      }
      try {
        onEnterInner(method, self, dexPc, invocationContext);
      } finally {
        hookReentrancyExit();
      }
    }

    private void onEnterInner(Member method, Object self, int dexPc, InvocationContext invocationContext) {
      if (dexPc == 0) {
        Object[] args = invocationContext.getArguments();
        if (args != null) {
          if (!safeToString) {
            String argsDesc = SafeToString.arrayToString(args);
            if (HookEventBuffer.ENABLED) {
              HookEventBuffer.record("ins", "enter", method.getName(), self, argsDesc, null, Albatross.getTid());
            }
            Albatross.log("Enter:" + method.getName() + " " + argsDesc + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
          } else {
            String argsDesc = Arrays.toString(args);
            if (HookEventBuffer.ENABLED) {
              HookEventBuffer.record("ins", "enter", method.getName(), self, argsDesc, null, Albatross.getTid());
            }
            Albatross.log("Enter:" + method.getName() + " " + argsDesc + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
          }
        } else {
          if (HookEventBuffer.ENABLED) {
            HookEventBuffer.record("ins", "enter", method.getName(), self, null, null, Albatross.getTid());
          }
          Albatross.log("Enter:" + method.getName(), new Exception(ThreadConfig.myId()));
        }
      } else {
        if (HookEventBuffer.ENABLED) {
          HookEventBuffer.record("ins", "pc", method.getName() + "@" + dexPc, null, invocationContext.smaliString(), null, Albatross.getTid());
        }
        Albatross.log("M[" + dexPc + "] " + method.getName() + ":" + invocationContext.smaliString());
      }
    }

    @Override
    public void onReturn(Member method, Object ret, int dexPc, InvocationContext invocationContext) {
      if (!hookReentrancyEnter()) {
        return;
      }
      try {
        onReturnInner(method, ret, dexPc, invocationContext);
      } finally {
        hookReentrancyExit();
      }
    }

    private void onReturnInner(Member method, Object ret, int dexPc, InvocationContext invocationContext) {
      if (ret != null) {
        if (!safeToString) {
          String retDesc = SafeToString.safeToString(ret);
          if (HookEventBuffer.ENABLED) {
            HookEventBuffer.record("ins", "leave", method.getName(), null, null, retDesc, Albatross.getTid());
          }
          Albatross.log("Leave:" + method.getName() + ":" + dexPc + " " + retDesc);
        } else {
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
          if (HookEventBuffer.ENABLED) {
            HookEventBuffer.record("ins", "leave", method.getName(), null, null, output, Albatross.getTid());
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

  /** 动态 hook 日志回调：Enter 记录参数与调用栈，Leave 记录返回值。 */
  static class AgentMethodHook extends MethodHookCallback {

    final boolean safeToString;

    AgentMethodHook(boolean safeToString) {
      this.safeToString = safeToString;
    }

    @Override
    public boolean beforeCall(CallFrame frame) {
      if (!hookReentrancyEnter()) {
        return true;
      }
      try {
        return beforeCallInner(frame);
      } finally {
        hookReentrancyExit();
      }
    }

    private boolean beforeCallInner(CallFrame frame) {
      Object[] args = frame.getArguments();
      if (args != null && args.length > 0) {
        String argsDesc = safeToString ? Arrays.toString(args) : SafeToString.arrayToString(args);
        if (HookEventBuffer.ENABLED) {
          HookEventBuffer.record("dyn", "enter", frame.getMethod().getName(), frame.getThis(), argsDesc, null, Albatross.getTid());
        }
        Albatross.log("DynEnter:" + frame.getMethod().getName() + " " + argsDesc
            + "\nstack:" + StackManager.getExceptionDesc(new Exception(ThreadConfig.myId())));
      } else {
        if (HookEventBuffer.ENABLED) {
          HookEventBuffer.record("dyn", "enter", frame.getMethod().getName(), frame.getThis(), null, null, Albatross.getTid());
        }
        Albatross.log("DynEnter:" + frame.getMethod().getName(), new Exception(ThreadConfig.myId()));
      }
      return true;
    }

    @Override
    public void afterCall(CallFrame frame) {
      if (!hookReentrancyEnter()) {
        return;
      }
      try {
        afterCallInner(frame);
      } finally {
        hookReentrancyExit();
      }
    }

    private void afterCallInner(CallFrame frame) {
      Object ret = frame.getResult();
      if (ret != null) {
        String retDesc = safeToString ? ret.toString() : SafeToString.safeToString(ret);
        if (HookEventBuffer.ENABLED) {
          HookEventBuffer.record("dyn", "leave", frame.getMethod().getName(), null, null, retDesc, Albatross.getTid());
        }
        Albatross.log("DynLeave:" + frame.getMethod().getName() + " " + retDesc);
      }
    }
  }

  /** 动态 hook 固定返回值回调：跳过原方法。 */
  static class AgentReturnHook extends MethodHookCallback {

    final Object result;
    final boolean hasResult;

    AgentReturnHook(Object result, boolean hasResult) {
      this.result = result;
      this.hasResult = hasResult;
    }

    @Override
    public boolean beforeCall(CallFrame frame) {
      if (hasResult)
        frame.setResult(result);
      return false;
    }
  }

  /** 按目标方法返回类型解析 RPC 传入的固定返回值字符串。 */
  static Object parseReturnValue(Class<?> type, String value) {
    if (type == void.class || type == Void.class)
      return null;
    if (value == null || "null".equals(value))
      return null;
    try {
      if (type == boolean.class || type == Boolean.class)
        return Boolean.parseBoolean(value);
      if (type == int.class || type == Integer.class)
        return Integer.parseInt(value);
      if (type == long.class || type == Long.class)
        return Long.parseLong(value);
      if (type == float.class || type == Float.class)
        return Float.parseFloat(value);
      if (type == double.class || type == Double.class)
        return Double.parseDouble(value);
      if (type == char.class || type == Character.class)
        return value.charAt(0);
      if (type == byte.class || type == Byte.class)
        return Byte.parseByte(value);
      if (type == short.class || type == Short.class)
        return Short.parseShort(value);
    } catch (Exception e) {
      Albatross.log("parse return value fail: '" + value + "' for " + type, e);
      return null;
    }
    if (type == String.class)
      return value;
    return null; // 其他引用类型无法从字符串构造，返回 null
  }

  @Override
  public int dynHookMethod(String className, String methodName, int numArgs, String args, boolean safeToString) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return CLASS_NOT_FIND;
    }
    String key = className + "." + methodName + "|" + numArgs;
    try {
      Member method = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
      if (!(method instanceof Method))
        return METHOD_NOT_FIND; // 动态 hook 不支持构造器
      // 同一方法重复调用按叠加处理（每层日志独立）；句柄复用，卸载走 dynUnhookMethod 整链摘除
      MethodCallHook hook = Albatross.hookMethod(method, new AgentMethodHook(safeToString));
      if (hook == null)
        return HOOK_FAIL;
      dynHooks.put(key, hook);
      return HOOK_SUCCESS;
    } catch (NoSuchMethodException e) {
      return METHOD_NOT_FIND;
    }
  }

  @Override
  public int dynHookMethodReturn(String className, String methodName, int numArgs, String args, String resultValue) {
    Class<?> clz = Albatross.findClassFromApplication(className);
    if (clz == null) {
      return CLASS_NOT_FIND;
    }
    String key = className + "." + methodName + "|" + numArgs;
    try {
      Member member = ReflectUtils.findDeclaredMethodWithCount(clz, methodName, numArgs, args);
      if (!(member instanceof Method))
        return METHOD_NOT_FIND;
      Method method = (Method) member;
      boolean hasResult = method.getReturnType() != void.class && resultValue != null && !"null".equals(resultValue);
      // 多个 return hook 叠加时，后装层的 setResult 生效（正序执行前者被覆盖）
      MethodCallHook hook = Albatross.hookMethod(method,
          new AgentReturnHook(parseReturnValue(method.getReturnType(), resultValue), hasResult));
      if (hook == null)
        return HOOK_FAIL;
      dynHooks.put(key, hook);
      return HOOK_SUCCESS;
    } catch (NoSuchMethodException e) {
      return METHOD_NOT_FIND;
    }
  }

  @Override
  public boolean dynUnhookMethod(String className, String methodName, int numArgs, String args) {
    String key = className + "." + methodName + "|" + numArgs;
    MethodCallHook hook = dynHooks.remove(key);
    if (hook != null) {
      hook.unHook();
      return true;
    }
    return false;
  }

  @Override
  public String dynHookClass(String className, boolean application, int scope, boolean safeToString) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return null;
    }
    StringBuilder builder = new StringBuilder();
    if ((scope & 3) != 0) {
      Method[] methods = clz.getDeclaredMethods();
      boolean containStatic = (scope & 1) != 0;
      boolean containInstance = (scope & 2) != 0;
      for (Method method : methods) {
        boolean isStatic = Modifier.isStatic(method.getModifiers());
        if (isStatic ? !containStatic : !containInstance)
          continue;
        if (Modifier.isAbstract(method.getModifiers()))
          continue; // 动态 hook 不支持 abstract
        String key = Albatross.methodToString(method);
        if (dynHooks.containsKey(key))
          continue;
        MethodCallHook hook = Albatross.hookMethod(method, new AgentMethodHook(safeToString));
        if (hook != null) {
          dynHooks.put(key, hook);
          builder.append(key).append(";");
        }
      }
    }
    // scope&4（构造器）当前不支持，忽略
    return builder.toString();
  }

  @Override
  public String dynUnhookClass(String className, boolean application, int scope) {
    Class<?> clz;
    if (application) {
      clz = Albatross.findClassFromApplication(className);
    } else {
      clz = Albatross.findClass(className);
    }
    if (clz == null) {
      return "class not find";
    }
    StringBuilder builder = new StringBuilder();
    if ((scope & 3) != 0) {
      Method[] methods = clz.getDeclaredMethods();
      boolean containStatic = (scope & 1) != 0;
      boolean containInstance = (scope & 2) != 0;
      for (Method method : methods) {
        boolean isStatic = Modifier.isStatic(method.getModifiers());
        if (isStatic ? !containStatic : !containInstance)
          continue;
        String key = Albatross.methodToString(method);
        MethodCallHook hook = dynHooks.remove(key);
        if (hook != null) {
          hook.unHook();
          builder.append(key).append(";");
        }
      }
    }
    return builder.toString();
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

  @Override
  public boolean hookEventsEnable(int maxRecords) {
    if (maxRecords < 0) {
      HookEventBuffer.disable();
    } else {
      HookEventBuffer.enable(maxRecords);
    }
    return HookEventBuffer.ENABLED;
  }

  @Override
  public String hookEventsStatus() {
    return HookEventBuffer.status();
  }

  @Override
  public String hookEventsPull(long cursor, int maxBytes) {
    return HookEventBuffer.pull(cursor, maxBytes);
  }

  @Override
  public boolean hookEventsClear() {
    HookEventBuffer.clear();
    return true;
  }

}
