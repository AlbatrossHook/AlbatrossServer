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

import qing.albatross.core.Albatross;

public abstract class AlbatrossPlugin {

  String argString;
  int flags;
  String libName;


  public AlbatrossPlugin(String libName, String argString, int flags) {
    this.argString = argString;
    this.flags = flags;
    this.libName = libName;
  }

  public boolean load() {
    try {
      if (libName != null)
        System.loadLibrary(libName);
      return true;
    } catch (Throwable e) {
      Albatross.log("plugin load err", e);
      return false;
    }
  }

  abstract public void beforeApplicationCreate(Application application);

  public void beforeMakeApplication() {
  }

  public void onAttachSystem(Application application) {
  }


  abstract public void afterApplicationCreate(Application application);
}
