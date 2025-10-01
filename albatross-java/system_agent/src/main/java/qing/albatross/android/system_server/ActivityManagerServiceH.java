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

import static qing.albatross.android.system_server.SystemServerInjectAgent.shouldInterceptUid;

import android.content.pm.ApplicationInfo;
import android.os.Build;
import android.util.SparseArray;

import org.json.JSONObject;

import qing.albatross.annotation.ExecOption;
import qing.albatross.annotation.MethodBackup;
import qing.albatross.annotation.MethodHook;
import qing.albatross.annotation.TargetClass;
import qing.albatross.core.Albatross;
import qing.albatross.reflection.FieldDef;

@TargetClass(className = "com.android.server.am.ActivityManagerService", hookerExec = ExecOption.DO_NOTHING)
public class ActivityManagerServiceH {


  @TargetClass(className = "com.android.server.am.ActivityManagerService$PidMap", required = false)
  public static class PidMapH {
    @MethodBackup
    public static native Object get(Object pidMap, int pid);
  }

  // PidMap mPidsSelfLocked androidQ  ProcessRecord
  //android9 final SparseArray<ProcessRecord> mPidsSelfLocked = new SparseArray<ProcessRecord>();
  static FieldDef<Object> mPidsSelfLocked;


  @MethodBackup
  @MethodHook({"android.app.IApplicationThread", "int", "int", "long"})
  static boolean attachApplicationLocked(Object ams, Object iApplicationThread,
                                         int pid, int callingUid, long startSeq) {
    interceptCheck(ams, pid, callingUid);
    return attachApplicationLocked(ams, iApplicationThread, pid, callingUid, startSeq);
  }


  @MethodBackup
  @MethodHook({"android.app.IApplicationThread", "int", "int", "long"})
  static void attachApplicationLocked$Hook_U(Object ams, Object iApplicationThread,
                                             int pid, int callingUid, long startSeq) {
    interceptCheck(ams, pid, callingUid);
    attachApplicationLocked$Hook_U(ams, iApplicationThread, pid, callingUid, startSeq);
  }

  private static void interceptCheck(Object ams, int pid, int callingUid) {
    if (shouldInterceptUid(callingUid) && SystemServerInjectAgent.v().getSubscriberSize() > 0) {
      try {
        JSONObject jsonObject = new JSONObject();
        Object pids = mPidsSelfLocked.get(ams);
        Object processRecord;
        if (pids instanceof SparseArray) {
          SparseArray sparseArray = (SparseArray) (pids);
          processRecord = sparseArray.get(pid);
        } else
          processRecord = PidMapH.get(pids, pid);
        String processName = ProcessRecordH.processName.get(processRecord);
        ApplicationInfo applicationInfo = ProcessRecordH.info.get(processRecord);
        if (applicationInfo != null) {
          jsonObject.put("pkg", applicationInfo.packageName);
        }
        jsonObject.put("process", processName);
        String name = null;
        String componentType = null;
        if (ProcessRecordH.hostingNameStr != null) {
          name = ProcessRecordH.hostingNameStr.get(processRecord);
          componentType = ProcessRecordH.hostingType.get(processRecord);
        } else {
          if (Build.VERSION.SDK_INT >= 29) {
            Object hostingRecord = ProcessRecordH.hostingRecord.get(processRecord);
            name = HostingRecordH.getName(hostingRecord);
            componentType = HostingRecordH.getType(hostingRecord);
          }
        }
        if (componentType != null) {
          jsonObject.put("type", componentType);
          jsonObject.put("name", name);
        }
        SystemServerInjectAgent.v().notifyProcessLaunch(callingUid, pid, jsonObject.toString());
      } catch (Exception e) {
        Albatross.log("interceptCheck", e);
      }
    }
  }

}
