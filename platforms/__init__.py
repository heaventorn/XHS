# -*- coding: utf-8 -*-
"""platforms/ — 平台采集器包
每个采集器是一个类，统一提供 .platform 属性和 run() 方法：
  run() 返回线索池/联系池行列表（对齐 core.storage 的字段）

现有采集器：
  xhs — 小红书（社交渠道 → 线索池）
未来新增（照葫芦画瓢）：
  qcc — 企查查/工商（→ 联系池）
  zhihu — 知乎（→ 线索池）
  bilibili — B站（→ 线索池）
"""
