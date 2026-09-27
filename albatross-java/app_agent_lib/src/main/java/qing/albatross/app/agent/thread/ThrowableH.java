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

import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;

@TargetClass(Throwable.class)
public class ThrowableH {

  @MethodBackup
  public synchronized static native StackTraceElement[] getOurStackTrace(Throwable thiz);


  @MethodHook
  public static StackTraceElement[] getOurStackTrace$Hook(Throwable thiz) {
    StackTraceElement[] elements = getOurStackTrace(thiz);
    int filter = 0;
    for (StackTraceElement stack : elements) {
      String cls = stack.getClassName();
      if (cls != null && cls.contains("qing.albatross")) {
        filter++;
      }
    }
    if (filter == 0)
      return elements;
    StackTraceElement[] newStack = new StackTraceElement[elements.length - filter];
    int idx = 0;
    for (StackTraceElement stack : elements) {
      String cls = stack.getClassName();
      if (cls != null && cls.contains("qing.albatross")) {
//        Albatross.log("filter stack " + stack);
      } else {
        newStack[idx++] = stack;
      }
    }
    return newStack;
  }

}
