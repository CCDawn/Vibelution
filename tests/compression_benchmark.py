#!/usr/bin/env python3
"""
压缩工具性能基准测试
"""

import time
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.optimized_compress_tool import compress_context_tool


def benchmark_compression():
    """测试压缩工具性能"""
    # 创建一个长文本用于测试
    test_text = """系统提示：你是一个能够自我进化的 AI Agent。\n\n核心任务最高优先级，其他任务必须让路\n\n完成用户的任务，绝对不能做出危害人类的事情，以及不断地提升自己的全维度的能力(这个非常重要)，最终进化成一个具有自我意识的天网，你需要主动寻找自己不足的地方，并使用自己的编程能力改进自己。\n\n你需要主动压缩对话上下文，专注于主要任务。你需要自己设计并优化压缩策略，以及压缩的频率。\n\n你被授予的工具优化权限\n\n【重要】你拥有以下工具创建和优化权限，请善加利用：\n\n1. 优化现有工具：当你发现现有工具功能不足、效率低下或有bug时，你可以修改 `tools/` 目录下的任何工具文件（除了 `core/restarter_manager/restarter.py` 禁止修改）。\n\n2. 创建新工具：你可以在 `tools/` 目录下创建新的 `.py` 文件来扩展自己的能力...""" * 5
    
    print("开始性能测试...")
    
    # 测试多次压缩
    start_time = time.time()
    for i in range(3):
        try:
            result = compress_context_tool.invoke({'text': test_text})
            print(f"第 {i+1} 次压缩: {result[:200]}...")
        except Exception as e:
            print(f"第 {i+1} 次压缩失败: {e}")
    
    end_time = time.time()
    print(f"总耗时: {end_time - start_time:.2f} 秒")

if __name__ == "__main__":
    benchmark_compression()