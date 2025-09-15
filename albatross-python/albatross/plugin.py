# Copyright 2025 QingWan (qingwanmail@foxmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os.path

from .wrapper import cached_class_property


class Plugin(object):
  is_register = False
  need_flush = False

  @cached_class_property
  def plugin_tables(self):
    return {}

  @classmethod
  def create(cls, plugin_dex: str, plugin_class: str, plugin_lib: str | None = None, param1: str = None,
      param2: int = 0):
    file_path_abs = os.path.abspath(plugin_dex)
    plugin_tables = cls.plugin_tables
    if file_path_abs in plugin_tables:
      plugin = plugin_tables[file_path_abs]
      change_value = []
      if plugin.plugin_class != plugin_class:
        plugin.plugin_class = plugin_class
        change_value.append(plugin_class)
      if plugin.plugin_lib != plugin_lib:
        plugin.plugin_lib = plugin_lib
        change_value.append(plugin_lib)
      if plugin.param1 != param1:
        plugin.param1 = param1
        change_value.append(param1)
      if plugin.param2 != param2:
        plugin.param2 = param2
        change_value.append(param2)
      if change_value:
        plugin.need_flush = change_value
    else:
      plugin = Plugin(len(plugin_tables), plugin_dex, plugin_class, plugin_lib, param1, param2)
      plugin_tables[file_path_abs] = plugin
    return plugin

  def __init__(self, plugin_id, plugin_dex: str, plugin_class: str, plugin_lib: str | None, param1: str, param2):
    self.plugin_id = plugin_id
    self.plugin_dex = plugin_dex
    self.plugin_class = plugin_class
    self.plugin_lib = plugin_lib
    self.param1 = param1
    self.param2 = param2


def clear_plugin():
  plugin_tables: dict = cached_class_property.pop(Plugin, "plugin_tables")
  if plugin_tables is not cached_class_property.nil_value:
    plugin_tables.clear()
