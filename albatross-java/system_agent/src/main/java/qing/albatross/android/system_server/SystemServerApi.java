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


import qing.albatross.server.Broadcast;

public interface SystemServerApi {

  String getTopActivity(boolean detail);

  String getLaunchPackage();

  String getAllProcesses();

  String startActivity(String pkgName, String activity, int uid);

  String getTargetProcess(String pkgName);

  String sendBroadcast(String pkgName, String receiver, String action, int uid);

  String getAppProcesses();

  boolean init();

  int setInterceptApp(String packageName, boolean clear);

  void setIntercept(int uid);

  void removeIntercept(int uid);

  void clearIntercept();

  boolean forceStopApp(String pkgName);

  boolean setTopApp(String pkgName);

  boolean setInterceptAll(boolean intercept);

  int initIntercept();


  String getFrontActivity();

  String getFrontActivityQuick();



  @Broadcast
  byte launchProcess(int uid, int pid, String data);


}
