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

import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;

public class ThreadDumper {

  private static final String TAG = "ThreadDumper";

  /**
   * 获取并打印当前进程所有线程（包括 native 线程）的信息
   */
  public static String dumpAllThreadsIncludingNative() {
    StringBuilder builder = new StringBuilder();
    // Step 1: 获取所有 Java 线程（带 TID 映射）
    Map<Integer, Thread> javaThreadIdMap = new HashMap<>();
    Map<Thread, StackTraceElement[]> allStackTraces = Thread.getAllStackTraces();
    for (Thread t : allStackTraces.keySet()) {
      int tid = Albatross.getThreadTid(t);
      javaThreadIdMap.put(tid, t);
    }
    // Step 2: 读取 /proc/self/task/ 获取所有实际线程（TID 列表）
    File taskDir = new File("/proc/self/task/");
    File[] threadDirs = taskDir.listFiles();
    if (threadDirs == null) {
      Log.e(TAG, "无法访问 /proc/self/task/，可能无权限或系统限制");
      return null;
    }
    builder.append("========== 总线程数: ").append(threadDirs.length).append("（Java线程: ").append(javaThreadIdMap.size()).append("，Native线程: ").append(threadDirs.length - javaThreadIdMap.size()).append("）==========\n");
    // Step 3: 遍历每个 TID，读取 comm（线程名）和 stat（状态）
    for (File dir : threadDirs) {
      String tidStr = dir.getName();
      try {
        int tid = Integer.parseInt(tidStr);
        if (!ThreadConfig.canTraceThread(tid))
          continue;
        String comm = readThreadName(tid);
        String state = readThreadState(tid);
        boolean isJavaThread = javaThreadIdMap.containsKey(tid);
        String threadType = isJavaThread ? "Java" : "Native";
        builder.append("TID: ").append(tid).append(" | 类型: ").append(threadType).append(" | 名称: ").append(comm != null ? comm : "unknown").append(" | 状态: ").append(state != null ? state : "?").append("\n");
        // 如果是 Java 线程，打印详细信息
        if (isJavaThread) {
          Thread t = javaThreadIdMap.get(tid);
          builder.append("    Java 名称: ").append(t.getName());
          builder.append("    状态: ").append(t.getState());
          builder.append("\n    守护线程: ").append(t.isDaemon());
          builder.append("    优先级: ").append(t.getPriority());
          StackTraceElement[] stack = allStackTraces.get(t);
          if (stack != null && stack.length > 0) {
            builder.append("\n    堆栈:\n");
            int max = Math.min(15, stack.length);
            for (int i = 0; i < max; i++) {
              builder.append("      ").append(stack[i]).append("\n");
            }
          } else {
            builder.append("\n");
          }
        }
        builder.append("----------------------------------------\n");
      } catch (NumberFormatException e) {
        // 忽略非数字目录（理论上不会出现）
      }
    }
    return builder.toString();
  }

  private static String readThreadName(long tid) {
    try (BufferedReader reader = new BufferedReader(new FileReader("/proc/self/task/" + tid + "/comm"))) {
      String name = reader.readLine();
      return name != null ? name.trim() : null;
    } catch (IOException e) {
      return null;
    }
  }

  private static String readThreadState(long tid) {
    try (BufferedReader reader = new BufferedReader(new FileReader("/proc/self/task/" + tid + "/stat"))) {
      String line = reader.readLine();
      if (line != null) {
        // stat 格式: pid (comm) state ppid ...
        // 第3个字段是状态（单字符）
        String[] parts = line.split(" ");
        if (parts.length >= 3) {
          return parts[2]; // 'R'=running, 'S'=sleeping, 'D'=disk sleep, 'Z'=zombie, etc.
        }
      }
    } catch (IOException e) {
      // 可能线程已退出
    }
    return null;
  }
}