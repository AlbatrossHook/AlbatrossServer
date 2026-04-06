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

import android.os.IInterface;

import qing.albatross.annotation.ByName;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.exception.AlbatrossErr;
import qing.albatross.reflection.FieldDef;
import qing.albatross.reflection.MethodDef;
import qing.albatross.reflection.VoidMethodDef;

@TargetClass(className = "android.app.ApplicationPackageManager")
public class ApplicationPackageManagerH {
  public static FieldDef<IInterface> mPM;

//  public static FieldDef<Object> mPermissionManager;

  public static MethodDef<Object> getPermissionManager;

//  @MethodBackup
//  public static native void updatePermissionFlags(Object self, String permissionName, String packageName, int flagMask,
//                                                  int flagValues, boolean checkAdjustPolicyFlagPermission, int userId);


  @TargetClass
  public static class IPackageManager {
    //void grantRuntimePermission(String packageName, String permissionName, int userId);
    @ByName(onlyAnno = false)
    public static VoidMethodDef grantRuntimePermission;
    @ByName(onlyAnno = false)
    public static VoidMethodDef updatePermissionFlags;

  }

  @TargetClass
  public static class IPermissionManager {

//    @MethodBackup
//    private native void grantRuntimePermission(String packageName, String permissionName, int userId);

    @ByName(onlyAnno = false)
    public static VoidMethodDef grantRuntimePermission;

//    @MethodBackup
//    private native void updatePermissionFlags(String packageName, String permissionName, int flagMask,
//                                              int flagValues, boolean checkAdjustPolicyFlagPermission, int userId);

    @ByName(onlyAnno = false)
    public static VoidMethodDef updatePermissionFlags;

  }

  @TargetClass
  public static class PermissionManager {
    public static FieldDef<IPermissionManager> mPermissionManager;
  }


  static {
    try {
      Albatross.hookClass(ApplicationPackageManagerH.class);
      if (ApplicationPackageManagerH.getPermissionManager != null) {
        Albatross.hookClass(PermissionManager.class, ApplicationPackageManagerH.getPermissionManager.method.getReturnType());
      } else {
        Albatross.hookClass(IPackageManager.class, ApplicationPackageManagerH.mPM.getType());
      }
      Albatross.hookClass(AppOpsManagerH.class);
    } catch (AlbatrossErr e) {
      Albatross.log("init package fail", e);
      throw new RuntimeException(e);
    }
  }


}
