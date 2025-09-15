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

import java.lang.reflect.Constructor;
import java.util.HashMap;
import java.util.Map;

import dalvik.system.DexClassLoader;
import qing.albatross.core.Albatross;

public class DynamicPluginManager {

  Map<String, AlbatrossPlugin> pluginCache;
  Map<String, DexClassLoader> classLoaderCache;

  private DynamicPluginManager() {
    pluginCache = new HashMap<>();
    classLoaderCache = new HashMap<>();
  }

  public static DynamicPluginManager getInstance() {
    return Holder.INSTANCE;
  }

  // 使用Holder模式实现线程安全的单例
  private static class Holder {
    static final DynamicPluginManager INSTANCE = new DynamicPluginManager();
  }


  public Map<String, AlbatrossPlugin> getPluginCache() {
    return pluginCache;
  }


  private String generatePluginKey(String dexPath, String className) {
    return dexPath + className;
  }


  /**
   * 加载并添加新插件
   *
   * @param pluginDexPath   插件dex文件路径
   * @param nativeLibPath   本地库路径(可选)
   * @param pluginClassName 插件主类名
   * @param arguments       字符串参数
   * @param flag            整型标志参数
   * @return 加载成功的插件实例，如果已存在或加载失败则返回null
   */
  public AlbatrossPlugin appendPlugin(String pluginDexPath,
                                      String nativeLibPath,
                                      String pluginClassName,
                                      String arguments,
                                      int flag) {
    String pluginKey = generatePluginKey(pluginDexPath, pluginClassName);

    if (pluginCache.containsKey(pluginKey)) {
      return null;
    }
    DexClassLoader dexClassLoader = classLoaderCache.get(pluginDexPath);
    String libDir;
    String libName;
    if (nativeLibPath == null || nativeLibPath.length() < 5) {
      libDir = null;
      libName = null;
    } else {
      int i = nativeLibPath.lastIndexOf('/');
      libDir = nativeLibPath.substring(0, i);
      libName = nativeLibPath.substring(i + 4, nativeLibPath.length() - 3);
    }
    if (dexClassLoader == null) {
      dexClassLoader = new DexClassLoader(pluginDexPath, null, libDir, DynamicPluginManager.class.getClassLoader());
      classLoaderCache.put(pluginDexPath, dexClassLoader);
    }
    AlbatrossPlugin plugin;
    try {
      Class<AlbatrossPlugin> initClass = (Class<AlbatrossPlugin>) dexClassLoader.loadClass(pluginClassName);
      Constructor<AlbatrossPlugin> constructor = initClass.getDeclaredConstructor(String.class, String.class, int.class);
      constructor.setAccessible(true);
      plugin = constructor.newInstance(libName, arguments, flag);
      pluginCache.put(pluginKey, plugin);
      return plugin;
    } catch (Throwable e) {
      Albatross.log("Failed to load plugin: " + pluginClassName, e);
    }
    return null;
  }


}
