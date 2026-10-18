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

public interface InjectApi {

  void setToStringConfig(int maxLength, boolean showBytes);

  String getClassFields(String clsName, boolean application);

  String getClassMethods(String clsName, boolean application);

  String readFile(String path);

  String findMethod(String className, String methodName, int numArgs, String args);

  int hookMethod(String className, String methodName, int numArgs, String args, int minDexPc, int maxDexPc, boolean safeToString);

  String hookClass(String className, boolean application, int scope, boolean safeToString);

  String unhookClass(String className, boolean application, int scope);

  boolean unhookMethod(String className, String methodName, int numArgs, String args);

  /**
   * 免签名动态 hook 单个方法（trampoline 路线，不去优化、不影响解释执行性能基线，
   * 回调为 beforeCall/afterCall 两段式日志）。参数含义与 {@link #hookMethod} 一致，
   * 但无 dexPc 范围（方法级而非指令级）。构造器不支持。
   */
  int dynHookMethod(String className, String methodName, int numArgs, String args, boolean safeToString);

  /**
   * 动态 hook 并跳过原方法、返回固定值：resultValue 按目标方法返回类型解析
   * （boolean/int/long/float/double/char 等按字面量，String 原样，"null" 或引用类型返回 null，
   * void 仅跳过不设值）。
   */
  int dynHookMethodReturn(String className, String methodName, int numArgs, String args, String resultValue);

  /** 卸载 dynHookMethod / dynHookMethodReturn 安装的动态 hook。 */
  boolean dynUnhookMethod(String className, String methodName, int numArgs, String args);

  /**
   * 免签名动态 hook 整个类（scope 位含义同 {@link #hookClass}：1=静态方法、2=实例方法、
   * 4=构造器——构造器当前不支持，该位被忽略）。返回成功 hook 的方法描述（";"分隔）。
   */
  String dynHookClass(String className, boolean application, int scope, boolean safeToString);

  /** 卸载 dynHookClass 安装的动态 hook（scope 位含义同上）。 */
  String dynUnhookClass(String className, boolean application, int scope);

  String dumpAllThreads();

  void decompileAll();

  String printAllClassLoader();

  String findClass(String className, boolean applicationLoader, int execMode);

  String findSubClass(String className, boolean applicationLoader);

  String classLoaders(boolean sync);

  String getFunctions(String module);

  String dumpNativeMethod();

  /**
   * 开启 hook 命中记录（结构化取数通道）：之后 hookMethod/dynHookMethod/hookClass/
   * dynHookClass 的每次命中都会写进进程内环形缓冲，经 {@link #hookEventsPull} 拉取。
   *
   * @param maxRecords 环容量（条）：&gt;0 设置容量并开启，0 用默认（4096）并开启，
   *                   &lt;0 关闭记录。换容量会清空已积累记录。
   * @return 是否处于开启状态
   */
  boolean hookEventsEnable(int maxRecords);

  /**
   * 命中记录状态（JSON）：enabled/capacity/appended/dropped/next_seq/readable。
   */
  String hookEventsStatus();

  /**
   * 拉取 cursor 之后的命中记录：首行 "#{" 开头的游标元信息（first_seq/next_seq/
   * dropped/capacity/skipped），随后每行一条 JSON 记录（seq/ts/tid/thread/kind/
   * phase/method/this/args/ret）。maxBytes&gt;0 时按行边界截断（下次继续拉）。
   */
  String hookEventsPull(long cursor, int maxBytes);

  /** 清空已积累的命中记录（游标不回退） */
  boolean hookEventsClear();
}
