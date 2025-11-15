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

import java.io.PrintWriter;
import java.io.StringWriter;

import qing.albatross.annotation.StaticMethodHook;
import qing.albatross.annotation.TargetClass;

@TargetClass(Log.class)
public final class LogH {

  // Log levels (match Android's values)
  public static final int ASSERT = 7;
  public static final int DEBUG = 3;
  public static final int ERROR = 6;
  public static final int INFO = 4;
  public static final int VERBOSE = 2;
  public static final int WARN = 5;

  // Optional: simulate a log ID counter (not required, but realistic)
  private static volatile int nextId = 1;

  // Helper to generate a simple log ID
  private static int getNextId() {
    return nextId++;
  }

  // Core output method
  @StaticMethodHook
  public static int println(int priority, String tag, String msg) {
    if (PluginMessage.appLogger != null) {
      if (tag == null) tag = "<null>";
      if (msg == null) msg = "<null>";
      String levelStr = getPriorityString(priority);
      String output = levelStr + "/" + tag + ": " + msg;
      PluginMessage.appLogger.log(output);
    }
    return getNextId(); // or just return 0 if you don't care about ID
  }

  private static String getPriorityString(int priority) {
    return switch (priority) {
      case VERBOSE -> "V";
      case DEBUG -> "D";
      case INFO -> "I";
      case WARN -> "W";
      case ERROR -> "E";
      case ASSERT -> "A";
      default -> "UNKNOWN";
    };
  }

  // ---- Debug ----
  @StaticMethodHook
  public static int d(String tag, String msg) {
    return println(DEBUG, tag, msg);
  }

  @StaticMethodHook
  public static int d(String tag, String msg, Throwable tr) {
    return println(DEBUG, tag, msg + '\n' + getStackTraceString(tr));
  }

  // ---- Error ----
  @StaticMethodHook
  public static int e(String tag, String msg) {
    return println(ERROR, tag, msg);
  }

  @StaticMethodHook
  public static int e(String tag, String msg, Throwable tr) {
    return println(ERROR, tag, msg + '\n' + getStackTraceString(tr));
  }

  // ---- Info ----
  @StaticMethodHook
  public static int i(String tag, String msg) {
    return println(INFO, tag, msg);
  }

  @StaticMethodHook
  public static int i(String tag, String msg, Throwable tr) {
    return println(INFO, tag, msg + '\n' + getStackTraceString(tr));
  }

  // ---- Verbose ----
  @StaticMethodHook
  public static int v(String tag, String msg) {
    return println(VERBOSE, tag, msg);
  }

  @StaticMethodHook
  public static int v(String tag, String msg, Throwable tr) {
    return println(VERBOSE, tag, msg + '\n' + getStackTraceString(tr));
  }

  // ---- Warn ----
  @StaticMethodHook
  public static int w(String tag, String msg) {
    return println(WARN, tag, msg);
  }

  @StaticMethodHook
  public static int w(String tag, String msg, Throwable tr) {
    return println(WARN, tag, msg + '\n' + getStackTraceString(tr));
  }

  @StaticMethodHook
  public static int w(String tag, Throwable tr) {
    return println(WARN, tag, getStackTraceString(tr));
  }

  // ---- WTF (What a Terrible Failure) ----
  @StaticMethodHook
  public static int wtf(String tag, String msg) {
    return println(ASSERT, tag, msg);
  }

  @StaticMethodHook
  public static int wtf(String tag, String msg, Throwable tr) {
    return println(ASSERT, tag, msg + '\n' + getStackTraceString(tr));
  }

  @StaticMethodHook
  public static int wtf(String tag, Throwable tr) {
    return println(ASSERT, tag, getStackTraceString(tr));
  }

  // ---- Utility ----
//  @StaticMethodHook
  public static String getStackTraceString(Throwable tr) {
    if (tr == null) {
      return "";
    }
    StringWriter sw = new StringWriter();
    PrintWriter pw = new PrintWriter(sw);
    tr.printStackTrace(pw);
    pw.flush();
    return sw.toString();
  }

  public static String getExceptionDesc(Exception e) {
    StringWriter sw = new StringWriter();
    PrintWriter pw = new PrintWriter(sw);
    e.printStackTrace(pw);
    return sw.toString();
  }
}