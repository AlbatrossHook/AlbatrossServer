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

import java.io.PrintStream;
import java.util.Locale;

import qing.albatross.annotation.DefOption;
import qing.albatross.annotation.MethodHookBackup;
import qing.albatross.annotation.TargetClass;

@TargetClass(PrintStream.class)
public class PrintStreamH {

  static StringBuffer errBuilder;
  static StringBuffer outBuilder;

  static {
    errBuilder = new StringBuffer();
    outBuilder = new StringBuffer();
  }

  static void printInternal(String s, boolean isOut) {
    if (PluginMessage.appLogger != null) {
      String prefix;
      if (isOut) {
        if (outBuilder.length() > 0) {
          outBuilder.append(s);
          s = outBuilder.toString();
          outBuilder.setLength(0);
        }
        prefix = "System.out: ";
      } else {
        if (errBuilder.length() > 0) {
          errBuilder.append(s);
          s = errBuilder.toString();
          errBuilder.setLength(0);
        }
        prefix = "System.err: ";
      }
      PluginMessage.appLogger.log(prefix + s);
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static void print(PrintStream printStream, Object obj) {
    if (printStream != System.out && printStream != System.err) {
      print(printStream, obj);
    } else if (obj != null) {
      if (printStream == System.out) {
        outBuilder.append(obj);
      } else {
        errBuilder.append(obj);
      }
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static void print(PrintStream printStream, String s) {
    if ((printStream != System.out && printStream != System.err) || s == null) {
      print(printStream, s);
    } else {
      if (printStream == System.out) {
        if (s.contains("\n"))
          printInternal(s, true);
        else
          outBuilder.append(s);
      } else {
        if (s.contains("\n"))
          printInternal(s, false);
        else
          errBuilder.append(s);
      }
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static PrintStream printf(PrintStream printStream, String format, Object... args) {
    if ((printStream != System.out && printStream != System.err) || format == null) {
      return printf(printStream, format, args);
    } else {
      String string = String.format(format, args);
      if (printStream == System.out) {
        if (string.contains("\n"))
          printInternal(string, true);
        else
          outBuilder.append(string);
      } else {
        if (string.contains("\n"))
          printInternal(string, false);
        else
          errBuilder.append(string);
      }
      return printStream;
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static PrintStream printf(PrintStream printStream, Locale l, String format, Object... args) {
    if ((printStream != System.out && printStream != System.err) || format == null || l == null) {
      return printf(printStream, l, format, args);
    } else {
      String string = String.format(l, format, args);
      if (printStream == System.out) {
        if (string.contains("\n"))
          printInternal(string, true);
        else
          outBuilder.append(string);
      } else {
        if (string.contains("\n"))
          printInternal(string, false);
        else
          errBuilder.append(string);
      }
      return printStream;
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static void println(PrintStream printStream, Object x) {
    if ((printStream != System.out && printStream != System.err) || x == null) {
      println(printStream, x);
    } else {
      printInternal(x.toString(), printStream == System.out);
    }
  }

  @MethodHookBackup(option = DefOption.VIRTUAL)
  public static void println(PrintStream printStream, String x) {
    if ((printStream != System.out && printStream != System.err) || x == null) {
      println(printStream, x);
    } else {
      printInternal(x, printStream == System.out);
    }
  }

  public static void flush() {
    if (errBuilder.length() > 0) {
      printInternal(" !!flush", false);
    }
    if (outBuilder.length() > 0) {
      printInternal(" !!flush", true);
    }
  }

}
