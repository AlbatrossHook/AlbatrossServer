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
package qing.albatross.app.agent.client;

import java.io.File;
import java.io.IOException;
import java.util.HashMap;
import java.util.Locale;

import qing.albatross.agent.BufferedDailyRollingLogger;
import qing.albatross.agent.PluginMessage;
import qing.albatross.common.AppMetaInfo;
import qing.albatross.common.ThreadConfig;
import qing.albatross.core.Albatross;

public class StackManager {


  public static int BKDRHash(String s) {
    int h = 0;
    final int len = s.length();
    for (int i = 0; i < len; i += 3) {
      h = 131 * h + s.charAt(i);
    }
    return h & 0x7FFFFFFF;
  }

  public static class StackLabel {
    public final String stackId;
    public short label = 0;

    StackLabel(String id) {
      this.stackId = id;
    }
  }


  public static final HashMap<String, StackLabel> stackTables;
  static BufferedDailyRollingLogger stackLogger;

  static {
    stackTables = new HashMap<>();
  }

  public static StackLabel getStackId(String s, String extra) {
    int length = s.length();
    long _stack_key = ((long) s.hashCode() << 32) + BKDRHash(s);
    String stack_id = _stack_key + "." + length;
    if (!stackTables.containsKey(stack_id)) {
      synchronized (stackTables) {
        if (stackLogger == null) {
          File file = new File("/data/data/" + AppMetaInfo.packageName + "/files/log/");
          try {
            file.mkdirs();
            stackLogger = new BufferedDailyRollingLogger(file, "stack_" + Albatross.currentProcessName(), 1024 * 1024 * 2);
          } catch (IOException e) {
            return null;
          }
        }
        StackLabel stackLabel = new StackLabel(stack_id);
        if (stackTables.put(stack_id, stackLabel) == null) {
          String string = String.format(Locale.getDefault(), "[\"%s\"]\nthread=%s\ntime=%d\ndetail=%s\nextra=%s\n\n", stack_id, ThreadConfig.myId(), System.currentTimeMillis(), s, extra);
          PluginMessage.send(string);
          stackLogger.log(string);
          return stackLabel;
        }
      }
    }
    return stackTables.get(stack_id);
  }

  public static String getExceptionDesc(Throwable e) {
    StringBuilder omitInfo = new StringBuilder("cause:" + e.toString() + "\nstack:");
    StringBuilder builder = new StringBuilder();
    StackTraceElement[] stackTraces = e.getStackTrace();
    for (StackTraceElement stackTraceElement : stackTraces) {
      String stack = stackTraceElement.toString();
      if (stack.startsWith("qing.albatross.")) {
        omitInfo.append(stack).append("\n");
      } else {
        builder.append(stack);
        builder.append("\n");
      }
    }
    String s = builder.toString();
    Throwable cause = e.getCause();
    if (cause != null && !cause.equals(e)) {
      omitInfo.append("\ncauseException:");
      omitInfo.append(getExceptionDesc(cause));
      omitInfo.append("\n");
    }
    StackLabel stackId = getStackId(s, omitInfo.toString());
    if (stackId != null)
      return stackId.stackId;
    return null;
  }


}
