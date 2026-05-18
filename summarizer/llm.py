import logging
import httpx
import json
import os
from config import (
    KKU_API_KEY, LLM_PROVIDER, LLM_MODEL, GEMINI_API_KEY, 
    BACKUP_LLM_PROVIDER, BACKUP_LLM_MODEL, OPENROUTER_API_KEY,
    SIMPLE_TASK_LLM_PROVIDER, SIMPLE_TASK_LLM_MODEL, SIMPLE_TASK_LLM_API_KEY
)

def build_prompt(article):
    return f"""Summarize the following medical research article for a clinical audience (allergists/immunologists).
Structure your response EXACTLY with these sections:
1. **Key Finding** — 3-5 bullets, summarize the abstract
2. **Study Design** — Study type, population, method (brief)
3. **Main Results** — 3-5 bullet points
4. **Clinical Relevance** — Why this matters for allergists/immunologists
5. **Limitations** — Max 2 lines, only if mentioned in abstract

The output format must be compatible to display in Discord.
please proceeding each bullets with space. this is critical for rendering bullets accurately.

Title: {article.get('title', 'Unknown')}
Journal: {article.get('journal', 'Unknown')}
Abstract:
{article.get('abstract', 'No abstract available')}
"""

async def summarize_article(article):
    prompt = build_prompt(article)
    
    if LLM_PROVIDER == "kku":
        try:
            return await _call_kku(prompt)
        except Exception as e:
            logging.error(f"KKU API failed: {e}")
            if BACKUP_LLM_PROVIDER == "openrouter":
                logging.info("Falling back to OpenRouter...")
                return await _call_openrouter(prompt)
                
    elif LLM_PROVIDER == "openrouter":
        try:
            return await _call_openrouter(prompt)
        except Exception as e:
            logging.error(f"OpenRouter API failed: {e}")
            
    return "Summary unavailable. (LLM Generation Failed)"

def build_relevance_batch_prompt(articles):
    parts = ["Identify which of the following medical research articles are primarily related to the field of allergy and/or clinical immunology based on their titles and abstracts."]
    
    try:
        keywords_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'related-keyword.txt')
        with open(keywords_path, 'r', encoding='utf-8') as f:
            keywords = [line.strip() for line in f if line.strip()]
        if keywords:
            parts.append("IMPORTANT: Select ONLY those articles that are related to at least one of the following keywords:")
            parts.append("Keywords: " + ", ".join(keywords))
    except Exception as e:
        logging.warning(f"Could not load related-keyword.txt: {e}")

    parts.append('Respond ONLY with a valid JSON array of strings containing the PMIDs of the relevant articles. For example: ["12345678", "87654321"]. If none are relevant, return an empty array: []')
    parts.append("")
    for article in articles:
        parts.append(f"PMID: {article['pmid']}")
        parts.append(f"Title: {article.get('title', 'Unknown')}")
        parts.append(f"Abstract: {article.get('abstract', 'No abstract available')}")
        parts.append("---")
    return "\n".join(parts)

async def check_articles_relevance_batch(articles):
    if not articles:
        return []
    prompt = build_relevance_batch_prompt(articles)
    
    response = ""
    # Use existing call structure
    if LLM_PROVIDER == "kku":
        try:
            response = await _call_kku(prompt)
        except Exception as e:
            logging.error(f"KKU API failed for relevance batch: {e}")
            if BACKUP_LLM_PROVIDER == "openrouter":
                response = await _call_openrouter(prompt)
    elif LLM_PROVIDER == "openrouter":
        try:
            response = await _call_openrouter(prompt)
        except Exception as e:
            logging.error(f"OpenRouter API failed for relevance batch: {e}")
            
    # Try to parse JSON array from response
    try:
        # Strip backticks in case LLM wraps response in ```json ... ```
        if "```" in response:
            import re
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response, re.DOTALL)
            if match:
                response = match.group(1)
            else:
                response = response.replace("```json", "").replace("```", "")
                
        # Handle cases where response might be empty or purely formatting
        if not response.strip():
            return []
            
        relevant_pmids = json.loads(response)
        if isinstance(relevant_pmids, list):
            return [str(pmid) for pmid in relevant_pmids]
    except Exception as e:
        logging.error(f"Failed to parse relevance batch response: {response}. Error: {e}")
        
    return []

async def classify_article_type(article, summary):
    prompt = f"""Based on the following article and its summary, classify the article type.
Examples of article types include: Narrative review, RCT, Retrospective cohort, Case-control study, Observational study, Meta-analysis, Systematic review, etc.
If you cannot identify the article type, just reply exactly with "Journal article".
Respond ONLY with the article type and nothing else.

Title: {article.get('title', 'Unknown')}
Journal: {article.get('journal', 'Unknown')}
Abstract:
{article.get('abstract', 'No abstract available')}

Summary:
{summary}
"""
    
    try:
        if SIMPLE_TASK_LLM_PROVIDER == "openrouter":
            return await _call_openrouter(prompt, model=SIMPLE_TASK_LLM_MODEL, api_key=SIMPLE_TASK_LLM_API_KEY)
        elif SIMPLE_TASK_LLM_PROVIDER == "gemini":
            return await _call_gemini(prompt, model=SIMPLE_TASK_LLM_MODEL, api_key=SIMPLE_TASK_LLM_API_KEY)
        elif SIMPLE_TASK_LLM_PROVIDER == "kku":
            return await _call_kku(prompt, model=SIMPLE_TASK_LLM_MODEL, api_key=SIMPLE_TASK_LLM_API_KEY)
    except Exception as e:
        logging.error(f"Classification failed: {e}")
        
    return "Journal article"

async def _call_kku(prompt: str, model: str = LLM_MODEL, api_key: str = KKU_API_KEY):
    if not api_key:
        raise ValueError("KKU API key is not set")
        
    url = "https://gen.ai.kku.ac.th/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an allergy and immunology research assistant."},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        # "temperature": 0.2
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

async def _call_gemini(prompt: str, model: str = LLM_MODEL, api_key: str = GEMINI_API_KEY):
    if not api_key:
        raise ValueError("Gemini API key is not set")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.2
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            raise Exception("Unexpected Gemini API response format")

async def _call_openrouter(prompt: str, model: str = BACKUP_LLM_MODEL, api_key: str = OPENROUTER_API_KEY):
    if not api_key:
        raise ValueError("OpenRouter API key is not set")
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        # "HTTP-Referer": "https://journal-reader.local",
        "X-Title": "Journal Reader Bot"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
