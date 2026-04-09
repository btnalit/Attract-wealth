"""
来财 (Attract-wealth) — 统一新闻与网络数据工具

提供多渠道新闻抓取及整合，并调用 LLM 提供初步摘要与情感得分
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Dict

from src.dataflows.source_manager import data_manager
from src.llm.openai_compat import create_quick_llm


class UnifiedNewsTool:
    """统一的研报及新闻抓取模块"""

    @staticmethod
    async def get_analyzed_news(ticker: str, limit: int = 5) -> Dict:
        """
        获取新闻并由 Quick LLM 输出情感判定
        返回值包含 news 列表及一个总览对象
        """
        try:
            raw_news = data_manager.get_news(ticker, limit)
        except Exception:
            raw_news = []
        if not raw_news:
            return {"ticker": ticker, "status": "no_news", "sentiment_score": 0.0, "summary": "近期暂无新闻", "articles": []}

        # 构建给 LLM 分析的简报文本
        prompt_text = f"请简要分析以下关于股票 {ticker} 的近期新闻，给出情感得分(1-100，越高越利好，50为中性)和一句话总结。\n"
        prompt_text += "要求严格按照 JSON 格式返回: {'sentiment_score': float, 'summary': 'string'}\n\n"
        
        for idx, item in enumerate(raw_news):
            prompt_text += f"{idx+1}. {item.get('title', '')} - {item.get('content', '')[:100]}...\n"

        llm = create_quick_llm()
        try:
            analysis_result = await llm.chat_simple(
                prompt=prompt_text,
                system="你是一个专业的金融新闻舆情分析师，必须返回合法的 JSON"
            )
            
            # 清理可能的 markdown 代码块符号
            raw_json = analysis_result.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(raw_json)
            
            return {
                "ticker": ticker,
                "status": "success",
                "sentiment_score": float(parsed.get("sentiment_score", 50.0)),
                "summary": parsed.get("summary", "无法总结"),
                "articles": raw_news
            }
        except Exception as e:
            # 兼容性降级
            return {
                "ticker": ticker,
                "status": "error_llm",
                "sentiment_score": 50.0,
                "summary": f"LLM 情感分析失败: {str(e)}",
                "articles": raw_news
            }
