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

public class Const {

  public static final byte SET_OK = 0;
  public static final byte SET_ALREADY = 1;
  public static final byte NOT_EXISTS = 2;
  public static final byte SYSTEM_CRASHED = 3;
  public static final byte DATA_ERR = 4;
  public static final byte PKG_NOT_INSTALL = 5;
  public static final byte MISS_INFO = 6;

  public static final String PKG_SYSTEM_SERVER = "system_server";
  public static final int SYSTEM_UID = 1000;

  public static final int INJECT_KEEP = 0x10;
  public static final int INJECT_UNIX = 0x20;
  public static final int INJECT_MEMFD = 0x80;
  public static final int INJECT_DEFAULT = INJECT_UNIX | INJECT_KEEP;

}
