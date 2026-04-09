# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 知识库核心 (Knowledge Core)

职责:
- 使用 LanceDB 存储交易模式、经验教训和专家规则。
- 提供语义搜索接口 (RAG)。
- 与记忆系统集成，从记忆中提取高价值内容。
- 与进化器集成，将知识转化为交易技能。
"""

import os
import time
import uuid
import logging
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Union, Callable

# Try to import lancedb and dependencies
try:
    import lancedb
    import pandas as pd
    import numpy as np
    HAS_LANCEDB = True
except ImportError:
    HAS_LANCEDB = False
    logger = logging.getLogger("KnowledgeCore")
    logger.warning("lancedb or pandas/numpy not installed. Falling back to memory-based search.")

logger = logging.getLogger("KnowledgeCore")

@dataclass
class KnowledgeEntry:
    id: str
    entry_type: str  # "pattern" | "lesson" | "rule"
    title: str
    content: str
    tags: List[str]
    metadata: Dict[str, Any]
    created_at: float
    vector_id: str  # LanceDB 中的 ID

class KnowledgeCore:
    """知识库核心 — LanceDB 向量存储 + RAG 检索"""
    
    TABLE_PATTERNS = "trading_patterns"
    TABLE_LESSONS = "lessons"
    TABLE_RULES = "expert_knowledge"

    def __init__(self, db_path: Optional[str] = None, embedding_fn: Callable[[str], List[float]] = None):
        """
        初始化知识库。
        
        :param db_path: 数据库存储路径。如果不提供，将使用相对于 src/evolution/ 的 ../../data/knowledge。
        :param embedding_fn: 自定义 embedding 函数。如果不提供，将使用默认 fallback。
        """
        if db_path is None:
            # Match MemoryManager logic: ../../data relative to src/evolution/
            from pathlib import Path
            self.db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "knowledge")
        else:
            self.db_path = db_path

        self.embedding_fn = embedding_fn
        self.use_lancedb = HAS_LANCEDB
        self.db = None
        
        # Ensure directories exist
        os.makedirs(self.db_path, exist_ok=True)
        
        if self.use_lancedb:
            try:
                self.db = lancedb.connect(self.db_path)
                self._ensure_tables()
                logger.info(f"KnowledgeCore initialized with LanceDB at {self.db_path}")
            except Exception as e:
                logger.error(f"Failed to connect to LanceDB: {e}. Falling back to memory storage.")
                self.use_lancedb = False
        
        if not self.use_lancedb:
            # Memory fallback: list of dicts for each table
            self.memory_db = {
                self.TABLE_PATTERNS: [],
                self.TABLE_LESSONS: [],
                self.TABLE_RULES: []
            }
            logger.info("KnowledgeCore initialized with memory-based storage (Fallback mode)")

    def _ensure_tables(self):
        """确保 LanceDB 中的表存在"""
        existing_tables = self.db.table_names()
        
        # Trading Patterns Table
        if self.TABLE_PATTERNS not in existing_tables:
            # Create with empty schema if needed, or wait for first insert
            pass
            
        # Lessons Table
        if self.TABLE_LESSONS not in existing_tables:
            pass
            
        # Expert Rules Table
        if self.TABLE_RULES not in existing_tables:
            pass

    def _get_embedding(self, text: str) -> List[float]:
        """获取文本的 Embedding 向量"""
        if self.embedding_fn:
            try:
                return self.embedding_fn(text)
            except Exception as e:
                logger.error(f"Custom embedding function failed: {e}")
        
        # Fallback 策略 (开发阶段)
        # 实际生产中应调用 OpenAI Embedding API 或本地模型
        # 这里使用确定性的伪随机向量以便开发测试 (基于 hash)
        import hashlib
        h = hashlib.sha256(text.encode('utf-8')).digest()
        # 生成 1536 维向量 (OpenAI 标准)
        np.random.seed(int.from_bytes(h[:4], 'little'))
        return np.random.rand(1536).tolist()

    # -- Public API: Adding Content --------------------------------------------

    def add_pattern(self, name: str, description: str, context: dict, embedding: list[float] = None) -> str:
        """添加交易模式到知识库"""
        entry_id = str(uuid.uuid4())
        vector = embedding if embedding else self._get_embedding(f"{name} {description}")
        
        data = {
            "id": entry_id,
            "name": name,
            "description": description,
            "context": json.dumps(context),
            "vector": vector,
            "created_at": time.time()
        }
        
        self._insert_into_table(self.TABLE_PATTERNS, data)
        logger.info(f"Added pattern: {name} ({entry_id})")
        return entry_id

    def add_lesson(self, title: str, content: str, tags: list[str], embedding: list[float] = None) -> str:
        """添加经验教训"""
        entry_id = str(uuid.uuid4())
        vector = embedding if embedding else self._get_embedding(f"{title} {content} {' '.join(tags)}")
        
        data = {
            "id": entry_id,
            "title": title,
            "content": content,
            "tags": json.dumps(tags),
            "vector": vector,
            "created_at": time.time()
        }
        
        self._insert_into_table(self.TABLE_LESSONS, data)
        logger.info(f"Added lesson: {title} ({entry_id})")
        return entry_id

    def add_expert_rule(self, rule_text: str, priority: int = 0, embedding: list[float] = None) -> str:
        """添加专家知识规则"""
        entry_id = str(uuid.uuid4())
        vector = embedding if embedding else self._get_embedding(rule_text)
        
        data = {
            "id": entry_id,
            "rule_text": rule_text,
            "priority": priority,
            "vector": vector,
            "created_at": time.time()
        }
        
        self._insert_into_table(self.TABLE_RULES, data)
        logger.info(f"Added expert rule (priority {priority}): {entry_id}")
        return entry_id

    def _insert_into_table(self, table_name: str, data: Dict[str, Any]):
        """通用插入逻辑"""
        if self.use_lancedb:
            try:
                if table_name in self.db.table_names():
                    table = self.db.open_table(table_name)
                    table.add([data])
                else:
                    self.db.create_table(table_name, data=[data])
            except Exception as e:
                logger.error(f"LanceDB insert failed for {table_name}: {e}")
                # Optional: Fallback to memory for this session
        else:
            self.memory_db[table_name].append(data)

    # -- Public API: Searching -------------------------------------------------

    def search_patterns(self, query: str, top_k: int = 5) -> list[dict]:
        """语义搜索交易模式"""
        return self._search_table(self.TABLE_PATTERNS, query, top_k)

    def search_lessons(self, query: str, top_k: int = 5) -> list[dict]:
        """语义搜索经验教训"""
        return self._search_table(self.TABLE_LESSONS, query, top_k)

    def search_rules(self, query: str, top_k: int = 5) -> list[dict]:
        """语义搜索专家规则"""
        return self._search_table(self.TABLE_RULES, query, top_k)

    def search_all(self, query: str, top_k: int = 5) -> dict[str, list]:
        """全库语义搜索，返回三类结果"""
        return {
            "patterns": self.search_patterns(query, top_k),
            "lessons": self.search_lessons(query, top_k),
            "rules": self.search_rules(query, top_k)
        }

    def _search_table(self, table_name: str, query: str, top_k: int) -> list[dict]:
        """通用搜索逻辑"""
        if self.use_lancedb:
            try:
                if table_name not in self.db.table_names():
                    return []
                table = self.db.open_table(table_name)
                query_vec = self._get_embedding(query)
                results = table.search(query_vec).limit(top_k).to_list()
                return results
            except Exception as e:
                logger.error(f"LanceDB search failed for {table_name}: {e}")
                return []
        else:
            # Memory search fallback (simple string match since we don't have vector search logic here)
            matches = []
            pool = self.memory_db.get(table_name, [])
            for item in pool:
                # Concatenate all text fields to search
                searchable_text = " ".join([str(v) for k, v in item.items() if k != "vector"])
                if query.lower() in searchable_text.lower():
                    matches.append(item)
            return matches[:top_k]

    def delete_entry(self, entry_id: str) -> bool:
        """删除指定条目 (遍历所有表)"""
        deleted = False
        for table_name in [self.TABLE_PATTERNS, self.TABLE_LESSONS, self.TABLE_RULES]:
            if self.use_lancedb:
                try:
                    if table_name in self.db.table_names():
                        table = self.db.open_table(table_name)
                        table.delete(f"id = '{entry_id}'")
                        deleted = True
                except Exception:
                    pass
            else:
                original_len = len(self.memory_db[table_name])
                self.memory_db[table_name] = [item for item in self.memory_db[table_name] if item["id"] != entry_id]
                if len(self.memory_db[table_name]) < original_len:
                    deleted = True
        
        if deleted:
            logger.info(f"Deleted entry: {entry_id}")
        return deleted

    def get_stats(self) -> dict:
        """返回知识库统计信息"""
        stats = {}
        for table_name in [self.TABLE_PATTERNS, self.TABLE_LESSONS, self.TABLE_RULES]:
            if self.use_lancedb:
                try:
                    if table_name in self.db.table_names():
                        table = self.db.open_table(table_name)
                        stats[table_name] = len(table.to_pandas())
                    else:
                        stats[table_name] = 0
                except Exception:
                    stats[table_name] = 0
            else:
                stats[table_name] = len(self.memory_db[table_name])
        return stats

    # -- Integration Methods ---------------------------------------------------

    def ingest_from_memory(self, memory_manager: Any, min_importance: float = 0.8):
        """
        从记忆系统中提取高价值内容向量化存储。
        
        :param memory_manager: MemoryManager 实例
        :param min_importance: 提取记忆的最低重要性阈值
        """
        # 假设 MemoryManager 有类似 getAllEntries 或 search 的方法
        # 这里模拟搜索高重要性的温/冷记忆
        logger.info(f"Ingesting high-value memories (importance >= {min_importance})...")
        
        # 实际上可以通过 memory_manager.search("") 获得一部分
        # 这里假设我们能访问到 warm 和 cold 存储
        
        # 示例逻辑: 搜索 "insight", "lesson", "pattern" 等关键词
        for kw in ["insight", "lesson", "pattern", "error"]:
            mems = memory_manager.search(kw, limit=50)
            for mem in mems:
                if mem.importance_score >= min_importance:
                    # 根据内容分类
                    content_lower = mem.content.lower()
                    if "pattern" in content_lower:
                        self.add_pattern(f"From Memory: {mem.id}", mem.content, mem.metadata)
                    elif "rule" in content_lower or "expert" in content_lower:
                        self.add_expert_rule(mem.content, priority=1)
                    else:
                        self.add_lesson(f"Memory Lesson: {mem.id}", mem.content, mem.tags)

    def export_to_skill(self, evolver: Any, entry_id: str) -> Optional[Any]:
        """
        将知识条目转化为策略技能。
        通过 StrategyEvolver 的 CAPTURED 模式实现。
        """
        # 先找到条目
        entry = None
        for table in [self.TABLE_PATTERNS, self.TABLE_LESSONS, self.TABLE_RULES]:
            results = self._search_table(table, entry_id, 1)
            for r in results:
                if r["id"] == entry_id:
                    entry = r
                    break
            if entry: break
            
        if not entry:
            logger.warning(f"Entry {entry_id} not found for skill export.")
            return None

        # 构建进化器需要的 DiagnosisReport
        # 注意: 需要从 strategy_evolver 导入 DiagnosisReport 和 EvolutionMode
        from src.evolution.strategy_evolver import DiagnosisReport, EvolutionMode
        
        content = entry.get("description") or entry.get("content") or entry.get("rule_text")
        title = entry.get("name") or entry.get("title") or "Expert Rule"
        
        report = DiagnosisReport(
            strategy_name=title,
            strategy_content="", # 新捕获，无原内容
            mode=EvolutionMode.CAPTURED,
            trade_examples=[{"insight": content}],
            context=entry.get("context", {}) if isinstance(entry.get("context"), dict) else {}
        )
        
        logger.info(f"Exporting knowledge {entry_id} to skill via Evolver...")
        return evolver.evolve(report)

    # -- RAG Context Building --------------------------------------------------

    def build_agent_context(self, query: str, max_tokens: int = 4000) -> str:
        """
        为 Agent 构建检索增强的 System Prompt。
        """
        results = self.search_all(query, top_k=3)
        
        sections = ["## 知识库检索 (RAG Context)"]
        
        if results["patterns"]:
            sections.append("### 相关交易模式")
            for p in results["patterns"]:
                sections.append(f"- **{p['name']}**: {p['description']}")
                
        if results["lessons"]:
            sections.append("### 历史经验教训")
            for l in results["lessons"]:
                sections.append(f"- **{l['title']}**: {l['content']} (Tags: {l['tags']})")
                
        if results["rules"]:
            sections.append("### 专家知识规则")
            for r in results["rules"]:
                sections.append(f"- [Priority {r['priority']}] {r['rule_text']}")
                
        if len(sections) == 1:
            return "## 知识库检索\n未找到与当前上下文相关的明确知识。"
            
        context_str = "\n".join(sections)
        # 简单截断 (按字符算，粗略估算 token)
        if len(context_str) > max_tokens * 4:
            context_str = context_str[:max_tokens * 4] + "..."
            
        return context_str

if __name__ == "__main__":
    # 单元测试逻辑
    logging.basicConfig(level=logging.INFO)
    core = KnowledgeCore(db_path="data/knowledge_test")
    
    # 测试添加
    pid = core.add_pattern("双底反转", "股价两次回踩支撑位不破，成交量萎缩后放大", {"threshold": 0.02})
    lid = core.add_lesson("不要在重大利好出尽时追涨", "典型的割韭菜场景", ["风险提示", "情绪控制"])
    rid = core.add_expert_rule("单笔亏损超过 2% 必须无条件止损", priority=10)
    
    # 测试搜索
    print("\n搜索 '反转':")
    print(core.search_patterns("反转"))
    
    print("\n全库搜索 '止损':")
    print(core.search_all("止损"))
    
    print("\n统计信息:")
    print(core.get_stats())
    
    # 测试 RAG
    print("\nAgent Context:")
    print(core.build_agent_context("如何处理回踩支撑位?"))
