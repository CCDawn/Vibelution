# -*- coding: utf-8 -*-
"""
存储工具

提供宠物数据的持久化存储功能
"""

import json
import os
from typing import Dict, Any, Optional


class Storage:
    """数据存储工具类"""

    def __init__(self, save_path: str = "workspace/memory/pet_info.json"):
        self.save_path = save_path
        self._ensure_directory()

    def _ensure_directory(self):
        """确保目录存在"""
        directory = os.path.dirname(self.save_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def save(self, data: Dict[str, Any]) -> bool:
        """
        保存数据到文件

        Args:
            data: 要保存的数据字典

        Returns:
            是否保存成功
        """
        try:
            self._ensure_directory()
            with open(self.save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.error(f"保存宠物数据失败: {e}")
            return False

    def load(self) -> Optional[Dict[str, Any]]:
        """
        从文件加载数据

        Returns:
            加载的数据字典，失败返回 None
        """
        if not os.path.exists(self.save_path):
            return None

        try:
            with open(self.save_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.error(f"加载宠物数据失败: {e}")
            return None

    def exists(self) -> bool:
        """检查数据文件是否存在"""
        return os.path.exists(self.save_path)

    def delete(self) -> bool:
        """删除数据文件"""
        try:
            if os.path.exists(self.save_path):
                os.remove(self.save_path)
            return True
        except Exception:
            return False
