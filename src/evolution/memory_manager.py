import os
import time
import json
import sqlite3
import logging
import uuid
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
from collections import OrderedDict
from pydantic import BaseModel, ConfigDict, Field

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MemoryManager")

# Data Model
class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    memory_type: str  # "hot" | "warm" | "cold"
    tags: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    access_count: int = 0
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)

class MemoryManager:
    """
    Memory Manager for LaiCai project implementing HOT/WARM/COLD tiered storage.
    """
    HOT_MAX_CAPACITY = 50
    WARM_MAX_CAPACITY = 500
    HOT_EXPIRY_MINS = 30
    WARM_EXPIRY_DAYS = 7

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # Match storage.py logic: ../../data relative to src/evolution/
            self.data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        
        self.warm_db_path = self.data_dir / "memory_warm.db"
        self.cold_root = self.data_dir / "memory" / "cold"
        
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cold_root.mkdir(parents=True, exist_ok=True)
        
        # HOT Memory: OrderedDict for LRU behavior
        self.hot_memory: OrderedDict[str, MemoryEntry] = OrderedDict()
        
        # Initialize SQLite for WARM storage
        self._init_warm_db()
        
        logger.info(f"MemoryManager initialized with data_dir: {self.data_dir}")

    def _init_warm_db(self):
        """Initialize the SQLite database for warm memory."""
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS warm_memory (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        tags TEXT,
                        created_at REAL NOT NULL,
                        access_count INTEGER DEFAULT 0,
                        importance_score REAL DEFAULT 0.5,
                        metadata TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_warm_created_at ON warm_memory(created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_warm_importance ON warm_memory(importance_score)")
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize warm database: {e}")

    def write(self, memory_type: str, content: str, tags: Optional[List[str]] = None,
              importance_score: float = 0.5, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Write a new memory entry to the specified tier.
        """
        entry = MemoryEntry(
            content=content,
            memory_type=memory_type,
            tags=tags or [],
            importance_score=importance_score,
            metadata=metadata or {}
        )
        
        if memory_type == "hot":
            self._write_hot(entry)
        elif memory_type == "warm":
            self._write_warm(entry)
        elif memory_type == "cold":
            self._write_cold(entry)
        else:
            logger.error(f"Invalid memory type: {memory_type}")
            raise ValueError(f"Invalid memory type: {memory_type}")
        
        logger.info(f"Memory [{entry.id}] written to {memory_type}")
        return entry.id

    def _write_hot(self, entry: MemoryEntry):
        # LRU implementation
        if entry.id in self.hot_memory:
            self.hot_memory.move_to_end(entry.id)
        elif len(self.hot_memory) >= self.HOT_MAX_CAPACITY:
            # Remove oldest (first) item
            self.hot_memory.popitem(last=False)
        self.hot_memory[entry.id] = entry

    def _write_warm(self, entry: MemoryEntry) -> bool:
        """写入 WARM 层。G7-2：返回是否成功，供 promote/demote 决策。"""
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO warm_memory
                    (id, content, tags, created_at, access_count, importance_score, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.id,
                    entry.content,
                    json.dumps(entry.tags),
                    entry.created_at,
                    entry.access_count,
                    entry.importance_score,
                    json.dumps(entry.metadata)
                ))
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to write to warm memory: {e}")
            return False

    def _write_cold(self, entry: MemoryEntry) -> bool:
        """写入 COLD 层。G7-2：返回是否成功，供 promote/demote 决策。"""
        dt = datetime.fromtimestamp(entry.created_at)
        month_dir = self.cold_root / dt.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        file_path = month_dir / f"{entry.id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(entry.model_dump_json())
            return True
        except Exception as e:
            logger.error(f"Failed to write to cold memory file: {e}")
            return False

    def search(self, query: str, memory_type: Optional[str] = None, limit: int = 10) -> List[MemoryEntry]:
        """
        Search for memory entries across tiers.
        """
        results = []
        target_types = [memory_type] if memory_type else ["hot", "warm", "cold"]
        
        # Search HOT
        if "hot" in target_types:
            hot_results = self._search_hot(query, limit)
            results.extend(hot_results)
            
        # Search WARM
        if "warm" in target_types and len(results) < limit:
            warm_results = self._search_warm(query, limit - len(results))
            results.extend(warm_results)
            
        # Search COLD
        if "cold" in target_types and len(results) < limit:
            cold_results = self._search_cold(query, limit - len(results))
            results.extend(cold_results)
            
        return results[:limit]

    def _search_hot(self, query: str, limit: int) -> List[MemoryEntry]:
        matches = []
        # Search in reverse order (most recent first)
        for entry in reversed(self.hot_memory.values()):
            if query.lower() in entry.content.lower() or any(query.lower() in t.lower() for t in entry.tags):
                entry.access_count += 1
                matches.append(entry)
                if len(matches) >= limit:
                    break
        return matches

    def _search_warm(self, query: str, limit: int) -> List[MemoryEntry]:
        matches = []
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM warm_memory 
                    WHERE content LIKE ? OR tags LIKE ? OR metadata LIKE ?
                    ORDER BY created_at DESC LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
                
                for row in cursor:
                    entry = MemoryEntry(
                        id=row['id'],
                        content=row['content'],
                        memory_type="warm",
                        tags=json.loads(row['tags']),
                        created_at=row['created_at'],
                        access_count=row['access_count'] + 1,
                        importance_score=row['importance_score'],
                        metadata=json.loads(row['metadata'])
                    )
                    # Update access count
                    conn.execute("UPDATE warm_memory SET access_count = access_count + 1 WHERE id = ?", (entry.id,))
                    matches.append(entry)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error searching warm memory: {e}")
        return matches

    def _search_cold(self, query: str, limit: int) -> List[MemoryEntry]:
        matches = []
        # Scan cold files (most recent month first)
        month_dirs = sorted([d for d in self.cold_root.iterdir() if d.is_dir()], reverse=True)
        
        for m_dir in month_dirs:
            if len(matches) >= limit:
                break
            # Scan files in month dir
            for f_path in sorted(m_dir.glob("*.json"), reverse=True):
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if query.lower() in data['content'].lower() or any(query.lower() in t.lower() for t in data.get('tags', [])):
                            entry = MemoryEntry(**data)
                            entry.access_count += 1
                            # Update file with new access count
                            with open(f_path, "w", encoding="utf-8") as fw:
                                fw.write(entry.model_dump_json())
                            matches.append(entry)
                            if len(matches) >= limit:
                                break
                except Exception as e:
                    logger.error(f"Error reading cold memory file {f_path}: {e}")
        return matches

    def promote(self, memory_id: str):
        """Promote memory: COLD -> WARM -> HOT.

        G7-2 修复：先写入目标层，确认成功后再删除源层，避免
        COLD/WARM 写入失败时数据永久丢失。
        """
        # Check COLD first
        entry = self._get_from_cold(memory_id)
        if entry:
            # COLD -> WARM
            entry.memory_type = "warm"
            if not self._write_warm(entry):
                logger.error(f"Promote COLD->WARM failed for {memory_id}, keep COLD copy")
                return
            self._delete_from_cold(memory_id)
            logger.info(f"Memory {memory_id} promoted: COLD -> WARM")
            return

        # Check WARM
        entry = self._get_from_warm(memory_id)
        if entry:
            # WARM -> HOT
            entry.memory_type = "hot"
            self._write_hot(entry)
            # HOT 是内存结构，写入必成功；WARM 可安全删除
            self._delete_from_warm(memory_id)
            logger.info(f"Memory {memory_id} promoted: WARM -> HOT")
            return

        logger.warning(f"Memory {memory_id} not found for promotion")

    def demote(self, memory_id: str):
        """Demote memory: HOT -> WARM -> COLD.

        G7-2 修复：WARM->COLD 时先写 COLD 文件，确认成功后再删 WARM，
        避免 COLD 写入失败导致条目永久丢失。
        """
        # Check HOT
        if memory_id in self.hot_memory:
            entry = self.hot_memory.pop(memory_id)
            entry.memory_type = "warm"
            if not self._write_warm(entry):
                # WARM 写失败，把条目放回 HOT，避免丢失
                entry.memory_type = "hot"
                self.hot_memory[memory_id] = entry
                logger.error(f"Demote HOT->WARM failed for {memory_id}, restored to HOT")
                return
            logger.info(f"Memory {memory_id} demoted: HOT -> WARM")
            return

        # Check WARM
        entry = self._get_from_warm(memory_id)
        if entry:
            entry.memory_type = "cold"
            if not self._write_cold(entry):
                logger.error(f"Demote WARM->COLD failed for {memory_id}, keep WARM record")
                return
            self._delete_from_warm(memory_id)
            logger.info(f"Memory {memory_id} demoted: WARM -> COLD")
            return

        logger.warning(f"Memory {memory_id} not found for demotion")

    def _get_from_warm(self, memory_id: str) -> Optional[MemoryEntry]:
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM warm_memory WHERE id = ?", (memory_id,)).fetchone()
                if row:
                    return MemoryEntry(
                        id=row['id'],
                        content=row['content'],
                        memory_type="warm",
                        tags=json.loads(row['tags']),
                        created_at=row['created_at'],
                        access_count=row['access_count'],
                        importance_score=row['importance_score'],
                        metadata=json.loads(row['metadata'])
                    )
        except sqlite3.Error as e:
            logger.error(f"Error fetching from warm memory: {e}")
        return None

    def _get_from_cold(self, memory_id: str) -> Optional[MemoryEntry]:
        for f_path in self.cold_root.glob("**/*.json"):
            if f_path.stem == memory_id:
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        return MemoryEntry(**json.load(f))
                except Exception:
                    pass
        return None

    def _delete_from_warm(self, memory_id: str):
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                conn.execute("DELETE FROM warm_memory WHERE id = ?", (memory_id,))
                conn.commit()
        except sqlite3.Error:
            pass

    def _delete_from_cold(self, memory_id: str):
        for f_path in self.cold_root.glob("**/*.json"):
            if f_path.stem == memory_id:
                try:
                    f_path.unlink()
                except Exception:
                    pass

    def auto_maintenance(self):
        """
        Maintenance task for capacity and expiry management.

        G7-3 修复：
        - 过期 demote 与容量 demote 合并为单次扫描，避免同一 batch
          里的条目被重复 demote（过期 demote 后容量可能已下降）。
        - 用集合去重，避免一个 id 被处理两次（demote 后从 WARM 消失，
          再次 demote 会 warning 噪音）。
        """
        logger.info("Executing auto maintenance...")
        now = time.time()

        # 1. HOT Memory Maintenance
        # 1.1 Expiry: 30 minutes
        hot_expiry_limit = now - (self.HOT_EXPIRY_MINS * 60)
        to_demote_hot = [mid for mid, entry in self.hot_memory.items() if entry.created_at < hot_expiry_limit]
        for mid in to_demote_hot:
            self.demote(mid)

        # 2. WARM Memory Maintenance（过期 + 容量合并）
        # 2.1 Expiry: 7 days
        warm_expiry_limit = now - (self.WARM_EXPIRY_DAYS * 24 * 3600)
        try:
            demote_ids: set = set()
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                cursor = conn.execute(
                    "SELECT id FROM warm_memory WHERE created_at < ?",
                    (warm_expiry_limit,),
                )
                for row in cursor.fetchall():
                    demote_ids.add(row[0])

                # 2.2 Capacity: 500 items（仅当仍超容时才补选最老的）
                count = conn.execute("SELECT COUNT(*) FROM warm_memory").fetchone()[0]
                # 减去即将被过期 demote 的数量，避免过度 demote
                projected = count - len(demote_ids)
                if projected > self.WARM_MAX_CAPACITY:
                    overflow_count = projected - self.WARM_MAX_CAPACITY
                    cursor = conn.execute(
                        "SELECT id FROM warm_memory WHERE created_at >= ? "
                        "ORDER BY created_at ASC LIMIT ?",
                        (warm_expiry_limit, overflow_count),
                    )
                    for row in cursor.fetchall():
                        demote_ids.add(row[0])

            # 统一执行 demote（顺序无关：每个 id 只处理一次）
            for mid in demote_ids:
                self.demote(mid)
        except sqlite3.Error as e:
            logger.error(f"Maintenance error for warm memory: {e}")

        logger.info("Auto maintenance finished.")

if __name__ == "__main__":
    # Simple self-test
    manager = MemoryManager()
    mid = manager.write("hot", "Test hot memory", tags=["test"])
    print(f"Created hot memory: {mid}")
    
    results = manager.search("Test")
    print(f"Search results: {len(results)} items found.")
    
    manager.demote(mid)
    print("Demoted to warm.")
    
    manager.auto_maintenance()
    print("Maintenance done.")
