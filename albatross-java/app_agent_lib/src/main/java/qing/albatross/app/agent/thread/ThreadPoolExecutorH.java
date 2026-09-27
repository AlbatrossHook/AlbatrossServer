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

import java.util.concurrent.Callable;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadPoolExecutor;

import qing.albatross.agent.PluginMessage;
import qing.albatross.annotation.DefOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.MethodHookBackup;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;

@TargetClass(ThreadPoolExecutor.class)
public class ThreadPoolExecutorH {


  @MethodBackup
  private static native void execute$Backup(ThreadPoolExecutor executor, Runnable command);

  @MethodHook(option = DefOption.VIRTUAL)
  private static void execute(ThreadPoolExecutor executor, Runnable command) {
    String name = Albatross.getCallerClass().getName();
    if (!name.startsWith("okhttp3."))
      PluginMessage.log(name + " execute:" + command.getClass().getName() + "@" + Integer.toHexString(System.identityHashCode(command)) + " from ThreadPoolExecutor " + executor);
    execute$Backup(executor, command);
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static <T> Future<T> submit(ThreadPoolExecutor executor, Runnable task, T result) {
    String name = Albatross.getCallerClass().getName();
    if (!name.startsWith("okhttp3."))
      PluginMessage.log(name + " submit:" + task.getClass().getName() + "@" + Integer.toHexString(System.identityHashCode(task)) + " from ThreadPoolExecutor " + executor);
    return submit(executor, task, result);
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static <T> Future<T> submit(ThreadPoolExecutor executor, Callable<T> task) {
    String name = Albatross.getCallerClass().getName();
    if (!name.startsWith("okhttp3."))
      PluginMessage.log(name + " submit:" + task.getClass().getName() + "@" + Integer.toHexString(System.identityHashCode(task)) + " from ThreadPoolExecutor " + executor);
    return submit(executor, task);
  }


}
