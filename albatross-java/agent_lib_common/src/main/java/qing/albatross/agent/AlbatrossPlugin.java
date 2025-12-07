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

import android.app.Application;
import android.content.Context;

import qing.albatross.core.Albatross;
import qing.albatross.server.UnixRpcInstance;

public abstract class AlbatrossPlugin {

  protected String params;
  protected int flags;
  protected String libName;
  protected boolean enable;


  public AlbatrossPlugin(String libName, String params, int flags) {
    this.params = params;
    this.flags = flags;
    this.libName = libName;
  }

  public String pluginName() {
    return this.getClass().getName();
  }

  public void loadLibrary(String libName) {
//    System.loadLibrary(libName); //The plugin only needs to remove the comments
    throw new RuntimeException("Plugins containing the so library must implement the loadLibrary method");
  }


  public boolean load(UnixRpcInstance agent) {
    try {
      if (libName != null)
        loadLibrary(libName);
      this.enable = true;
      return parseParams(params, flags);
    } catch (Throwable e) {
      this.enable = false;
      Albatross.log("plugin load err", e);
      return false;
    }
  }

  public void beforeApplicationCreate(Application application) {
  }


  public void beforeMakeApplication() {
  }

  public void beforeNewApplication(ClassLoader cl, String className, Context context) {

  }

  public void afterNewApplication(Application application) {

  }

  public boolean parseParams(String params, int flags) {
    return true;
  }

  public void onAttachSystem(Application application) {
  }

  public void onConfigChange(String config, int flags) {
    this.params = config;
    this.flags = flags;
    if (this.enable)
      parseParams(config, flags);
  }

  public void unload() {
    disable();
  }

  public void disable() {
    this.enable = false;
    Albatross.log("plugin " + this.pluginName() + " disable");
    parseParams(null, 0);
  }

  public void enable() {
    this.enable = true;
    parseParams(params, flags);
  }

  public boolean isEnable() {
    return this.enable;
  }


  public void afterApplicationCreate(Application application) {
  }


  // native avoid inline
  public native void send(String msg);

  //native avoid inline
  public native void send(String msg, Throwable tr);

  public native void log(String msg);

}
