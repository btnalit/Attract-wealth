import os
import re
from typing import Dict, Any

class PromptTemplate:
    """
    Prompt 模板加载器，支持从 Markdown 文件读取并进行变量替换。
    """
    def __init__(self, template_path: str):
        self.template_path = template_path
        self.raw_content = ""
        self.metadata = {}
        self.template = ""
        self._load()

    def _load(self):
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Prompt 模板文件未找到: {self.template_path}")
        
        with open(self.template_path, 'r', encoding='utf-8') as f:
            content = f.read()
            self.raw_content = content
            
            # 解析 YAML Frontmatter (简单正则解析)
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if frontmatter_match:
                yaml_str = frontmatter_match.group(1)
                for line in yaml_str.split('\n'):
                    if ':' in line:
                        k, v = line.split(':', 1)
                        self.metadata[k.strip()] = v.strip()
                self.template = content[frontmatter_match.end():].strip()
            else:
                self.template = content.strip()

    def format(self, **kwargs) -> str:
        """
        进行变量替换
        """
        return self.template.format(**kwargs)

    @classmethod
    def load_by_name(cls, name: str, base_dir: str = None) -> 'PromptTemplate':
        """
        通过名称加载模板 (不含扩展名)
        """
        if base_dir is None:
            base_dir = os.path.dirname(__file__)
        path = os.path.join(base_dir, f"{name}.md")
        return cls(path)

def get_prompt(name: str, **variables) -> str:
    """
    便捷函数：获取格式化后的 Prompt
    """
    template = PromptTemplate.load_by_name(name)
    return template.format(**variables)
