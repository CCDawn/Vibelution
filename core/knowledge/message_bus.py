#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息总线 (MessageBus) - 模块间通信机制

Phase 4 核心模块

设计原则：
- 发布/订阅模式：松耦合的组件通信
- 主题过滤：支持通配符订阅
- 异步支持：支持同步和异步处理器
- 消息持久化：可选的消息持久化
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum
from queue import Queue, Empty
import threading


# ============================================================================
# 消息定义
# ============================================================================

class MessagePriority(Enum):
    """消息优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Message:
    """消息"""
    topic: str
    data: Any
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    sender: Optional[str] = None
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.message_id is None:
            self.message_id = f"{self.topic}_{self.timestamp.timestamp()}"


@dataclass
class Subscription:
    """订阅"""
    topic: str
    handler: Callable
    subscriber: str
    async_handler: bool = False
    created_at: datetime = field(default_factory=datetime.now)


# ============================================================================
# 消息过滤器
# ============================================================================

class MessageFilter:
    """消息过滤器"""

    @staticmethod
    def match(topic: str, pattern: str) -> bool:
        """
        匹配主题

        支持通配符：
        - * 匹配单个层级 (agent.*.task)
        - ** 匹配多层级 (agent.**)

        Args:
            topic: 实际主题
            pattern: 模式

        Returns:
            是否匹配
        """
        if pattern == topic:
            return True

        if pattern == "**":
            return True

        if "**" in pattern:
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                if prefix and not topic.startswith(prefix.rstrip(".")):
                    return False
                if suffix and not topic.endswith(suffix.lstrip(".")):
                    return False
                return True

        if "*" in pattern:
            topic_parts = topic.split(".")
            pattern_parts = pattern.split(".")

            if len(topic_parts) != len(pattern_parts):
                return False

            for tp, pp in zip(topic_parts, pattern_parts):
                if pp != "*" and tp != pp:
                    return False

            return True

        return False


# ============================================================================
# 消息总线
# ============================================================================

class MessageBus:
    """
    消息总线

    发布/订阅模式的消息总线，支持：
    - 主题订阅（支持通配符）
    - 异步/同步消息处理
    - 消息过滤和优先级
    - 消息持久化（可选）

    使用方式：
        bus = MessageBus()
        bus.subscribe("agent.task.*", handler)
        bus.publish("agent.task.completed", {"task_id": "123"})
    """

    def __init__(self, persist_messages: bool = False, max_queue_size: int = 1000):
        """
        初始化消息总线

        Args:
            persist_messages: 是否持久化消息
            max_queue_size: 最大队列大小
        """
        self.logger = logging.getLogger("MessageBus")
        self.persist_messages = persist_messages
        self.max_queue_size = max_queue_size

        # 订阅者
        self._subscriptions: Dict[str, List[Subscription]] = defaultdict(list)

        # 消息队列
        self._message_queue: Queue = Queue(maxsize=max_queue_size)
        self._pending_messages: List[Message] = []

        # 统计
        self._stats = {
            "messages_sent": 0,
            "messages_delivered": 0,
            "messages_dropped": 0,
            "subscriptions_count": 0,
        }

        # 锁
        self._lock = threading.RLock()

        # 运行状态
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

    # =========================================================================
    # 订阅管理
    # =========================================================================

    def subscribe(
        self,
        topic: str,
        handler: Callable,
        subscriber: str = "anonymous",
        async_handler: bool = False,
    ) -> Subscription:
        """
        订阅主题

        Args:
            topic: 主题（支持通配符）
            handler: 处理函数
            subscriber: 订阅者名称
            async_handler: 是否为异步处理器

        Returns:
            订阅对象
        """
        with self._lock:
            subscription = Subscription(
                topic=topic,
                handler=handler,
                subscriber=subscriber,
                async_handler=async_handler,
            )
            self._subscriptions[topic].append(subscription)
            self._stats["subscriptions_count"] = sum(
                len(s) for s in self._subscriptions.values()
            )

            self.logger.debug(f"订阅主题: {topic} by {subscriber}")
            return subscription

    def unsubscribe(self, topic: str, handler: Callable) -> bool:
        """
        取消订阅

        Args:
            topic: 主题
            handler: 处理函数

        Returns:
            是否成功取消
        """
        with self._lock:
            if topic in self._subscriptions:
                original_len = len(self._subscriptions[topic])
                self._subscriptions[topic] = [
                    s for s in self._subscriptions[topic] if s.handler != handler
                ]
                removed = original_len - len(self._subscriptions[topic])
                self._stats["subscriptions_count"] = sum(
                    len(s) for s in self._subscriptions.values()
                )
                return removed > 0
            return False

    def unsubscribe_all(self, subscriber: str) -> int:
        """
        取消订阅者的所有订阅

        Args:
            subscriber: 订阅者名称

        Returns:
            取消的订阅数量
        """
        with self._lock:
            count = 0
            for topic in list(self._subscriptions.keys()):
                original_len = len(self._subscriptions[topic])
                self._subscriptions[topic] = [
                    s for s in self._subscriptions[topic]
                    if s.subscriber != subscriber
                ]
                count += original_len - len(self._subscriptions[topic])

            self._stats["subscriptions_count"] = sum(
                len(s) for s in self._subscriptions.values()
            )
            return count

    def get_subscriptions(self, topic: Optional[str] = None) -> List[Subscription]:
        """
        获取订阅列表

        Args:
            topic: 主题过滤（可选）

        Returns:
            订阅列表
        """
        with self._lock:
            if topic:
                return list(self._subscriptions.get(topic, []))
            return [
                sub for subs in self._subscriptions.values() for sub in subs
            ]

    # =========================================================================
    # 消息发布
    # =========================================================================

    def publish(
        self,
        topic: str,
        data: Any,
        priority: MessagePriority = MessagePriority.NORMAL,
        sender: Optional[str] = None,
    ) -> bool:
        """
        发布消息

        Args:
            topic: 主题
            data: 消息数据
            priority: 优先级
            sender: 发送者

        Returns:
            是否成功发布
        """
        message = Message(
            topic=topic,
            data=data,
            priority=priority,
            sender=sender,
        )

        # 持久化
        if self.persist_messages:
            self._persist_message(message)

        # 放入队列
        try:
            self._message_queue.put_nowait(message)
        except Exception:
            self._stats["messages_dropped"] += 1
            return False

        self._stats["messages_sent"] += 1

        # 同步分发（直接调用处理器）
        self._dispatch_sync(message)

        return True

    def publish_async(
        self,
        topic: str,
        data: Any,
        priority: MessagePriority = MessagePriority.NORMAL,
        sender: Optional[str] = None,
    ) -> None:
        """
        异步发布消息（不等待处理）

        Args:
            topic: 主题
            data: 消息数据
            priority: 优先级
            sender: 发送者
        """
        message = Message(
            topic=topic,
            data=data,
            priority=priority,
            sender=sender,
        )

        if self.persist_messages:
            self._persist_message(message)

        try:
            self._message_queue.put_nowait(message)
        except Exception:
            self._stats["messages_dropped"] += 1

        self._stats["messages_sent"] += 1

    # =========================================================================
    # 消息分发
    # =========================================================================

    def _dispatch_sync(self, message: Message) -> None:
        """同步分发消息"""
        with self._lock:
            # 收集匹配的订阅
            handlers = []
            for topic_pattern, subscriptions in self._subscriptions.items():
                if MessageFilter.match(message.topic, topic_pattern):
                    handlers.extend(subscriptions)

        # 调用处理器
        for subscription in handlers:
            try:
                if subscription.async_handler:
                    # 异步处理器放入队列
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        executor.submit(subscription.handler, message)
                else:
                    subscription.handler(message)

                self._stats["messages_delivered"] += 1

            except Exception as e:
                self.logger.error(
                    f"消息处理失败: {subscription.topic} - {e}"
                )

    def start_worker(self) -> None:
        """启动消息处理工作线程"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="MessageBus-Worker",
            daemon=True,
        )
        self._worker_thread.start()
        self.logger.info("消息总线工作线程已启动")

    def stop_worker(self) -> None:
        """停止消息处理工作线程"""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        self.logger.info("消息总线工作线程已停止")

    def _worker_loop(self) -> None:
        """工作线程主循环"""
        while self._running:
            try:
                message = self._message_queue.get(timeout=1)
                self._dispatch_async(message)
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"消息处理错误: {e}")

    def _dispatch_async(self, message: Message) -> None:
        """异步分发消息"""
        # 与同步分发类似，但处理异常
        self._dispatch_sync(message)

    # =========================================================================
    # 持久化
    # =========================================================================

    def _persist_message(self, message: Message) -> None:
        """持久化消息"""
        try:
            import os
            from pathlib import Path

            persist_dir = Path("workspace") / "message_bus"
            persist_dir.mkdir(parents=True, exist_ok=True)

            message_file = persist_dir / f"{message.topic.replace('.', '_')}.jsonl"
            with open(message_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "topic": message.topic,
                    "data": message.data,
                    "timestamp": message.timestamp.isoformat(),
                    "sender": message.sender,
                }, ensure_ascii=False) + "\n")

        except Exception as e:
            self.logger.warning(f"消息持久化失败: {e}")

    # =========================================================================
    # 统计和调试
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self._stats,
                "queue_size": self._message_queue.qsize(),
                "topics_count": len(self._subscriptions),
                "running": self._running,
            }

    def clear_stats(self) -> None:
        """清除统计信息"""
        with self._lock:
            self._stats = {
                "messages_sent": 0,
                "messages_delivered": 0,
                "messages_dropped": 0,
                "subscriptions_count": 0,
            }

    def get_topics(self) -> List[str]:
        """获取所有主题"""
        with self._lock:
            return list(self._subscriptions.keys())


# ============================================================================
# 全局单例
# ============================================================================

_message_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """获取消息总线单例"""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus


def reset_message_bus() -> None:
    """重置消息总线"""
    global _message_bus
    if _message_bus:
        _message_bus.stop_worker()
    _message_bus = None
