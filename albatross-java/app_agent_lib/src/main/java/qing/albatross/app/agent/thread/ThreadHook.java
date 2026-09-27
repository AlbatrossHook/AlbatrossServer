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
package qing.albatross.app.agent.thread;


import java.util.Objects;

import qing.albatross.agent.PluginMessage;
import qing.albatross.annotation.ExecutionOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;
import qing.albatross.reflection.FieldDef;


@TargetClass(value = Thread.class, targetExec = ExecutionOption.DO_NOTHING, hookerExec = ExecutionOption.DO_NOTHING)
public class ThreadHook {
  @MethodHook(isStatic = true)
  public static void setDefaultUncaughtExceptionHandler$Hook(Thread.UncaughtExceptionHandler eh) {
    Albatross.log("setDefaultUncaughtExceptionHandler:" + (eh != null ? eh.getClass().getName() : "null"), new Exception("uncaughtException"));
//    setDefaultUncaughtExceptionHandler$Hook(eh);
  }

  static FieldDef<Runnable> target;


  public static boolean watchThread = false;

  @MethodBackup(triggerFieldName = "watchThread")
  public synchronized static native void start$Backup(Thread thread);

  @MethodHook(triggerFieldName = "watchThread")
  public static void start(Thread t) {
    Runnable runnable = target.get(t);
    String threadClass = Objects.requireNonNullElse(runnable, t).getClass().getName();
    if (threadClass.startsWith("java.util.concurrent.ThreadPoolExecutor$")) {
//      Albatross.log("thread pool create:" + t);
      start$Backup(t);
      return;
    }
    PluginMessage.log("thread create:" + threadClass + "|" + t + " from " + Albatross.getCallerClass().getName());
    start$Backup(t);
    Albatross.getMainHandler().postDelayed(() -> {
      int tid = Albatross.getThreadTid(t);
      if (!ThreadConfig.canTraceThread(tid)) {
        return;
      }
      StringBuilder builder = new StringBuilder();
      builder.append("TID: ").append(tid).append(" | 名称: ").append(t.getName()).append(" | 状态: ").append(t.getState()).append("\n");
      builder.append("    守护线程: ").append(t.isDaemon());
      builder.append("    优先级: ").append(t.getPriority());
      builder.append("    class: ").append(threadClass);
      if (t.isAlive()) {
        StackTraceElement[] stack = t.getStackTrace();
        if (stack != null && stack.length > 0) {
          builder.append("\n    堆栈:\n");
          int max = Math.min(15, stack.length);
          for (int i = 0; i < max; i++) {
            builder.append("      ").append(stack[i]).append("\n");
          }
        }
      }
      PluginMessage.log(builder.toString());
    }, 1500);
  }
}
