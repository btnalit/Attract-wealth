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
from pydantic import BaseModel, Field, validator

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

    class Config:
        use_enum_values = True

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

    def write(self, memory_type: str, content: str, tags: List[str] = None, 
              importance_score: float = 0.5, metadata: Dict[str, Any] = None) -> str:
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

    def _write_warm(self, entry: MemoryEntry):
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
        except sqlite3.Error as e:
            logger.error(f"Failed to write to warm memory: {e}")

    def _write_cold(self, entry: MemoryEntry):
        dt = datetime.fromtimestamp(entry.created_at)
        month_dir = self.cold_root / dt.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = month_dir / f"{entry.id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Use json.dumps for compatibility
                f.write(entry.json() if hasattr(entry, 'json') else json.dumps(entry.dict()))
        except Exception as e:
            logger.error(f"Failed to write to cold memory file: {e}")

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
                                fw.write(entry.json() if hasattr(entry, 'json') else json.dumps(entry.dict()))
                            matches.append(entry)
                            if len(matches) >= limit:
                                break
                except Exception as e:
                    logger.error(f"Error reading cold memory file {f_path}: {e}")
        return matches

    def promote(self, memory_id: str):
        """Promote memory: COLD -> WARM -> HOT."""
        # Check COLD first
        entry = self._get_from_cold(memory_id)
        if entry:
            # COLD -> WARM
            entry.memory_type = "warm"
            self._write_warm(entry)
            self._delete_from_cold(memory_id)
            logger.info(f"Memory {memory_id} promoted: COLD -> WARM")
            return

        # Check WARM
        entry = self._get_from_warm(memory_id)
        if entry:
            # WARM -> HOT
            entry.memory_type = "hot"
            self._write_hot(entry)
            self._delete_from_warm(memory_id)
            logger.info(f"Memory {memory_id} promoted: WARM -> HOT")
            return
        
        logger.warning(f"Memory {memory_id} not found for promotion")

    def demote(self, memory_id: str):
        """Demote memory: HOT -> WARM -> COLD."""
        # Check HOT
        if memory_id in self.hot_memory:
            entry = self.hot_memory.pop(memory_id)
            entry.memory_type = "warm"
            self._write_warm(entry)
            logger.info(f"Memory {memory_id} demoted: HOT -> WARM")
            return
            
        # Check WARM
        entry = self._get_from_warm(memory_id)
        if entry:
            entry.memory_type = "cold"
            self._write_cold(entry)
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
        """
        logger.info("Executing auto maintenance...")
        now = time.time()
        
        # 1. HOT Memory Maintenance
        # 1.1 Expiry: 30 minutes
        hot_expiry_limit = now - (self.HOT_EXPIRY_MINS * 60)
        to_demote_hot = [mid for mid, entry in self.hot_memory.items() if entry.created_at < hot_expiry_limit]
        for mid in to_demote_hot:
            self.demote(mid)
            
        # 2. WARM Memory Maintenance
        # 2.1 Expiry: 7 days
        warm_expiry_limit = now - (self.WARM_EXPIRY_DAYS * 24 * 3600)
        try:
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                cursor = conn.execute("SELECT id FROM warm_memory WHERE created_at < ?", (warm_expiry_limit,))
                expired_ids = [row[0] for row in cursor.fetchall()]
                for mid in expired_ids:
                    self.demote(mid)
                    
            # 2.2 Capacity: 500 items
            with sqlite3.connect(str(self.warm_db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM warm_memory").fetchone()[0]
                if count > self.WARM_MAX_CAPACITY:
                    overflow_count = count - self.WARM_MAX_CAPACITY
                    # Demote oldest items
                    cursor = conn.execute("SELECT id FROM warm_memory ORDER BY created_at ASC LIMIT ?", (overflow_count,))
                    overflow_ids = [row[0] for row in cursor.fetchall()]
                    for mid in overflow_ids:
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
