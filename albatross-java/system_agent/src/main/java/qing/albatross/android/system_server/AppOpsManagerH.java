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
package qing.albatross.android.system_server;

import android.app.AppOpsManager;

import qing.albatross.annotation.FieldRef;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.TargetClass;


@TargetClass(AppOpsManager.class)
public class AppOpsManagerH {

  @MethodBackup
  public static native void setUidMode(Object thiz, String appOp, int uid, int mode);

  @MethodBackup
  public static native void setMode(Object thiz, int code, int uid, String packageName, int mode);

  @FieldRef
  static int OP_SYSTEM_ALERT_WINDOW;//24

  @FieldRef
  static int OP_RUN_IN_BACKGROUND;//63

  @FieldRef
  static int OP_RUN_ANY_IN_BACKGROUND;//70
}
