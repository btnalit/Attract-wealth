# -*- coding: utf-8 -*-
"""
策略注册与解析引擎 (Skill Registry)
作用：从项目目录中热加载人类编写好的 `.md` 策略，将其提取为供 LangGraph 和 Agent 理解的上下文规则对象。
"""
import os
import glob
import yaml
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class SkillRule:
    """被解析出的人工策略规则实体"""
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.name = "Unknown Strategy"
        self.target_tickers = []
        self.trigger = ""
        self.rules_text = ""
        self.metadata = {}
        self._parse_md(filepath)

    def _parse_md(self, filepath: str):
        """解析带有 YAML frontmatter 的 Markdown 策略库文件"""
        if not os.path.exists(filepath):
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if content.startswith('---'):
            try:
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    self.rules_text = parts[2].strip()
                    
                    self.metadata = yaml.safe_load(frontmatter) or {}
                    self.name = self.metadata.get('name', 'Unnamed Strategy')
                    self.target_tickers = self.metadata.get('target_tickers', [])
                    self.trigger = self.metadata.get('trigger', '')
            except Exception as e:
                logger.error(f"Error parsing strategy frontmatter for {filepath}: {e}")
                self.rules_text = content
        else:
            self.rules_text = content

    def to_agent_context(self) -> str:
        """将其转化为准备注入给大模型作为 System Prompt 强规矩的字符串格式"""
        return f"""
        【强制策略纪律名称】: {self.name}
        【应用范围】: {self.target_tickers}
        【人工制定的核心铁律】:
        {self.rules_text}
        """


class SkillRegistry:
    """策略加载中心"""
    def __init__(self, base_path: str = None):
        if not base_path:
            # 默认从这往上找当前项目的 src/evolution/skills
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.base_path = os.path.join(current_dir, "skills")
        else:
            self.base_path = base_path
            
        self.human_skills: Dict[str, SkillRule] = {}
        self.derived_skills: Dict[str, SkillRule] = {}

    def reload_all(self):
        """热加载所有的 markdown 技能文件"""
        logger.info(f"🔄 正在从 {self.base_path} 重载所有人工干预策略...")
        
        # 加载人工池
        human_dir = os.path.join(self.base_path, "human")
        if os.path.exists(human_dir):
            for file_path in glob.glob(os.path.join(human_dir, "*.md")):
                rule = SkillRule(file_path)
                key = os.path.basename(file_path)
                self.human_skills[key] = rule
                
        # 加载 AI 演化池
        derived_dir = os.path.join(self.base_path, "derived")
        if os.path.exists(derived_dir):
            for file_path in glob.glob(os.path.join(derived_dir, "*.md")):
                rule = SkillRule(file_path)
                key = os.path.basename(file_path)
                self.derived_skills[key] = rule

        logger.info(f"✅ 载入完成：找到 {len(self.human_skills)} 条人工铁律， {len(self.derived_skills)} 条 AI 派生铁律。")

    def get_skill(self, name: str, source: str = "human") -> SkillRule:
        if source == "human":
            return self.human_skills.get(name)
        return self.derived_skills.get(name)
