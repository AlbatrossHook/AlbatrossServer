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

import threading
import sys
from collections import defaultdict


def __get_nil():
  class __NIL:
    def __str__(self):
      return "NIL"

    __repr__ = __str__

    def __bool__(self):
      return False

    def __len__(self):
      return 0

  return __NIL()


nil_value = __get_nil()


class TimeoutLock:
  """带超时功能的锁上下文管理器"""

  acquire_lock = False

  def __init__(self, lock=None, timeout=10):
    # 默认为可重入锁，兼容你之前的 threading.RLock
    self.lock = lock or threading.RLock()
    self.timeout = timeout

  def acquire(self, timeout=None):
    """获取锁，支持覆盖默认超时时间"""
    actual_timeout = timeout if timeout is not None else self.timeout
    # 带超时获取锁
    acquired = self.lock.acquire(timeout=actual_timeout)
    self.acquire_lock = acquired

  def release(self):
    """释放锁"""
    if self.acquire_lock:
      self.lock.release()
      self.acquire_lock = False

  def __enter__(self):
    """with 语句进入时调用"""
    # if not self.acquire():
    #   raise TimeoutError(f"获取锁超时（超时时间：{self.timeout} 秒）")
    self.acquire()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    """with 语句退出时调用"""
    self.release()
    # 不抑制异常，让异常正常抛出
    return False


class cached_property(object):
  nil_value = nil_value

  def __init__(self, func):
    self.__doc__ = getattr(func, "__doc__")
    self.func = func
    self.lock = threading.RLock()

  def __get__(self, obj, cls):
    func = self.func
    if obj is None:
      return self
    attr_name = func.__name__
    obj_dict = obj.__dict__
    val = obj_dict.get(attr_name, nil_value)
    if val is nil_value:
      with TimeoutLock(self.lock, 10):
        val = obj_dict.get(attr_name, nil_value)
        if val is nil_value:
          val = func(obj)
          if val is not nil_value:
            obj_dict[attr_name] = val
    return val

  @staticmethod
  def reset(obj, attr, v):
    obj.__dict__[attr] = v

  @staticmethod
  def delete(obj, attr):
    obj.__dict__.pop(attr, None)

  @staticmethod
  def get(obj, attr):
    return obj.__dict__.get(attr, nil_value)

  @staticmethod
  def pop(obj, attr):
    return obj.__dict__.pop(attr, nil_value)


class cached_class_property(object):
  v = nil_value
  nil_value = nil_value

  cls_property_tables = defaultdict(dict)

  def __init__(self, func):
    self.__doc__ = getattr(func, "__doc__")
    if sys.gettrace():
      v = [False]

      def _wrapper(*args, **kwargs):
        if v[0] is True:
          return nil_value
        v[0] = True
        ret = func(*args, **kwargs)
        v[0] = False
        return ret

      _wrapper.__name__ = func.__name__
      self.func = _wrapper
    else:
      self.func = func
    self.lock = threading.RLock()

  @staticmethod
  def reset(cls, attr, v):
    setattr(cls, attr, v)

  @staticmethod
  def delete(cls, attr):
    try:
      delattr(cls, attr)
      cls_property = cached_class_property.cls_property_tables[cls][attr]
      cls_property.v = nil_value
      setattr(cls, attr, cls_property)
      return True
    except:
      return False

  @staticmethod
  def pop(cls, attr):
    if hasattr(cls, attr):
      v = getattr(cls, attr)
      delattr(cls, attr)
      return v
    return nil_value

  @staticmethod
  def try_get(cls, attr, default_value=nil_value):
    if attr not in cls.__dict__:
      return default_value
    v = cls.__dict__[attr]
    if isinstance(v, cached_class_property):
      return default_value
    if hasattr(cls, attr):
      v = getattr(cls, attr)
      return v
    return default_value

  def __get__(self, obj, cls):
    func = self.func
    func_name = func.__name__
    v = self.v
    cls_base = cls
    while func_name not in cls_base.__dict__:
      cls_base = cls_base.__base__
    if v is nil_value:
      with self.lock:
        v = self.v
        if v is nil_value:
          v = func(cls)
          if v is not nil_value:
            setattr(cls_base, func_name, v)
            self.cls_property_tables[cls_base][func_name] = self
            self.v = v
    else:
      setattr(cls, func_name, v)
    if obj is not None and v.__class__.__name__ == 'function':
      return getattr(obj, func_name)
    return v


class cached_subclass_property(cached_class_property):

  def __init__(self, func):
    super().__init__(func)
    self.value_tables = {}

  @staticmethod
  def try_get(cls, attr, default_value=nil_value):
    if attr not in cls.__dict__:
      return default_value
    if hasattr(cls, attr):
      v = getattr(cls, attr)
      return v
    return default_value

  @staticmethod
  def delete(cls, attr):
    try:
      delattr(cls, attr)
      return True
    except:
      return False

  def __get__(self, obj, cls):
    func = self.func
    func_name = func.__name__
    if func_name in cls.__dict__:
      raise Exception("can not call class property in abstract class {}".format(cls.__name__))
    value_tables = self.value_tables
    v = value_tables.get(cls, nil_value)
    if v is nil_value:
      with self.lock:
        v = value_tables.get(cls, nil_value)
        if v is nil_value:
          v = func(cls)
          if v is not nil_value:
            setattr(cls, func_name, v)
            value_tables[cls] = v
    else:
      setattr(cls, func_name, v)
    value_tables.pop(cls, None)
    if obj is not None and v.__class__.__name__ == 'function':
      return getattr(obj, func_name)
    return v
