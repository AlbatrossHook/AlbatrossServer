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

  String dumpAllThreads();

  void decompileAll();

  String printAllClassLoader();

  String findClass(String className, boolean applicationLoader, int execMode);

  String findSubClass(String className, boolean applicationLoader);

  String classLoaders(boolean sync);

  String getFunctions(String module);

  String dumpNativeMethod();
}
