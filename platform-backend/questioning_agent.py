"""
questioning_agent.py - Interactive Project Specification Agent

The Questioning Agent conducts natural, friendly back-and-forth conversations
with users to gather comprehensive project specifications. It:

1. Asks clarifying questions in a conversational manner
2. Generates and updates a project-specification.md file iteratively
3. Suggests actions to users for gathering more detailed information
4. Maintains context across multiple conversation turns

The specifications file is later used by the Director Agent to construct
a detailed task ledger for agent orchestration.
"""

import json
import os
import re
import time
import random
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from html import unescape
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from openai import AzureOpenAI
from dotenv import load_dotenv
import requests

load_dotenv()

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT")
MODEL_CALL_DELAY_MIN = float(os.getenv("MODEL_CALL_DELAY_MIN", "1.0"))
MODEL_CALL_DELAY_MAX = float(os.getenv("MODEL_CALL_DELAY_MAX", "2.0"))
WEB_SEARCH_ENABLED = os.getenv("QUESTIONING_WEB_SEARCH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("QUESTIONING_WEB_SEARCH_TIMEOUT_SECONDS", "8"))
WEB_SEARCH_MAX_RESULTS = int(os.getenv("QUESTIONING_WEB_SEARCH_MAX_RESULTS", "4"))
WEB_SEARCH_MAX_QUERIES = int(os.getenv("QUESTIONING_WEB_SEARCH_MAX_QUERIES", "2"))

logger = logging.getLogger("questioning_agent")


def _detect_repo_root() -> str:
    env_root = (os.getenv("NEXUS_ROOT_DIR") or "").strip()
    if env_root:
        return os.path.abspath(env_root)

    here = os.path.abspath(__file__)
    parent = os.path.dirname(here)
    grandparent = os.path.dirname(parent)
    if os.path.basename(parent) == "platform-backend" and os.path.basename(grandparent).startswith("Azure_Hack-"):
        return os.path.dirname(grandparent)

    return parent


REPO_ROOT = _detect_repo_root()
WORKSPACE_DIR = os.path.join(REPO_ROOT, "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _throttle_model_call():
    """Small delay between model calls to reduce bursty rate-limit errors."""
    time.sleep(random.uniform(MODEL_CALL_DELAY_MIN, MODEL_CALL_DELAY_MAX))


class QuestioningAgent:
    """
    Conducts conversational interviews to gather project specifications.
    
    Uses Azure OpenAI to ask natural, follow-up questions and builds
    a comprehensive project specification document iteratively.
    """

    def __init__(self):
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_API_VERSION,
            azure_endpoint=AZURE_ENDPOINT
        )
        self.model = AZURE_MODEL_DEPLOYMENT

    def _get_spec_file_path(self, project_id: str) -> str:
        """Get the path to the project specification file."""
        return os.path.join(WORKSPACE_DIR, f"project_specs_{project_id}.md")

    def _load_spec_file(self, project_id: str) -> str:
        """Load existing specification file if it exists."""
        spec_path = self._get_spec_file_path(project_id)
        if os.path.exists(spec_path):
            with open(spec_path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def _save_spec_file(self, project_id: str, content: str) -> None:
        """Save the specification file."""
        spec_path = self._get_spec_file_path(project_id)
        with open(spec_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _extract_topic_terms(self, text: str, max_terms: int = 8) -> List[str]:
        """Extract lightweight topic terms for related search expansion."""
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-.+#]{2,}", str(text or ""))
        if not tokens:
            return []

        stop_words = {
            "about", "agent", "and", "are", "build", "for", "from", "have", "help", "into",
            "just", "more", "need", "project", "that", "the", "their", "them", "this", "with",
            "what", "when", "where", "which", "will", "would", "your", "user", "users",
        }

        seen = set()
        terms: List[str] = []
        for token in tokens:
            value = token.strip().lower()
            if value in stop_words:
                continue
            if value.isdigit() or len(value) < 3:
                continue
            if value in seen:
                continue
            seen.add(value)
            terms.append(value)
            if len(terms) >= max_terms:
                break

        return terms

    def _build_related_queries(self, user_message: str, existing_specs: str) -> List[str]:
        """Build a short set of related search queries from user prompt and known context."""
        base_query = str(user_message or "").replace("\n", " ").strip()
        if not base_query:
            return []

        base_query = base_query[:280].strip()
        queries = [base_query]

        spec_slice = "\n".join((existing_specs or "").splitlines()[:40])
        candidate_terms = self._extract_topic_terms(f"{user_message}\n{spec_slice}", max_terms=6)
        if candidate_terms:
            expanded_query = f"{base_query} {' '.join(candidate_terms[:4])}".strip()
            if expanded_query.lower() != base_query.lower():
                queries.append(expanded_query[:280].strip())

        deduped: List[str] = []
        seen = set()
        for query in queries:
            key = query.lower()
            if not query or key in seen:
                continue
            seen.add(key)
            deduped.append(query)

        return deduped[: max(1, WEB_SEARCH_MAX_QUERIES)]

    def _collect_web_snippets(self, queries: List[str]) -> List[Dict[str, str]]:
        """Collect and deduplicate web snippets across related queries."""
        all_results: List[Dict[str, str]] = []
        seen_urls = set()

        for query in queries:
            results = self._search_duckduckgo_html(query)
            if not results:
                results = self._search_duckduckgo_instant_answer(query)
            if not results:
                results = self._search_bing_rss(query)

            for item in results:
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append(item)
                if len(all_results) >= WEB_SEARCH_MAX_RESULTS:
                    return all_results

        return all_results

    def _search_bing_rss(self, query: str) -> List[Dict[str, str]]:
        """Fallback search using Bing RSS feed (no API key required)."""
        try:
            encoded_query = quote_plus(query)
            response = requests.get(
                f"https://www.bing.com/search?q={encoded_query}&format=rss",
                timeout=WEB_SEARCH_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            if response.status_code != 200:
                return []

            root = ET.fromstring(response.text)
            results: List[Dict[str, str]] = []
            for item in root.findall("./channel/item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                if title and link.startswith("http"):
                    results.append({"title": title, "snippet": description, "url": link})
                if len(results) >= WEB_SEARCH_MAX_RESULTS:
                    break

            return results
        except Exception as exc:
            logger.warning("Bing RSS fallback search failed: %s", exc)
            return []

    def _normalize_search_result_url(self, raw_url: str) -> str:
        """Normalize search result URLs and unwrap DuckDuckGo redirect links."""
        url = str(raw_url or "").strip()
        if not url:
            return ""

        if url.startswith("//"):
            url = "https:" + url

        if url.startswith("/"):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            uddg_values = query.get("uddg") or []
            if uddg_values:
                unwrapped = unquote(uddg_values[0]).strip()
                if unwrapped.startswith("http"):
                    return unwrapped
            return ""

        return url if url.startswith("http") else ""

    def _build_web_context(self, user_message: str, existing_specs: str) -> str:
        """Fetch lightweight web context that can help ground recommendations."""
        if not WEB_SEARCH_ENABLED:
            return ""

        queries = self._build_related_queries(user_message, existing_specs)
        if not queries:
            return ""

        snippets = self._collect_web_snippets(queries)

        if not snippets:
            return ""

        lines = [
            f"WEB CONTEXT FOR USER REQUEST: {queries[0]}",
            f"Related query expansion used: {' | '.join(queries)}",
            "Use this context to improve accuracy and recommendations when relevant.",
            "If a result conflicts with user constraints, prioritize user constraints.",
        ]

        for item in snippets[:WEB_SEARCH_MAX_RESULTS]:
            title = item.get("title", "Untitled").strip()
            snippet = item.get("snippet", "").strip()
            url = item.get("url", "").strip()
            if snippet:
                lines.append(f"- {title}: {snippet} ({url})")
            else:
                lines.append(f"- {title} ({url})")

        return "\n".join(lines)

    def _search_duckduckgo_html(self, query: str) -> List[Dict[str, str]]:
        """Search DuckDuckGo HTML endpoint and extract top organic results."""
        try:
            encoded_query = quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            response = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=WEB_SEARCH_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                return []

            html = response.text
            title_pattern = re.compile(
                r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                re.IGNORECASE | re.DOTALL,
            )
            snippet_pattern = re.compile(
                r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(?P<snippet_div>.*?)</div>',
                re.IGNORECASE | re.DOTALL,
            )

            snippets = [
                unescape(re.sub(r"<[^>]+>", "", (m.group("snippet") or m.group("snippet_div") or "")).strip())
                for m in snippet_pattern.finditer(html)
            ]

            results: List[Dict[str, str]] = []
            for idx, match in enumerate(title_pattern.finditer(html)):
                raw_url = (match.group("url") or "").strip()
                clean_url = self._normalize_search_result_url(raw_url)
                if not clean_url:
                    continue
                raw_title = match.group("title") or ""
                clean_title = unescape(re.sub(r"<[^>]+>", "", raw_title).strip())
                clean_snippet = snippets[idx] if idx < len(snippets) else ""
                if clean_title:
                    results.append({"title": clean_title, "snippet": clean_snippet, "url": clean_url})
                if len(results) >= WEB_SEARCH_MAX_RESULTS:
                    break

            return results
        except Exception as exc:
            logger.warning("DuckDuckGo HTML search failed: %s", exc)
            return []

    def _search_duckduckgo_instant_answer(self, query: str) -> List[Dict[str, str]]:
        """Fallback using DuckDuckGo instant-answer API when HTML scraping fails."""
        try:
            response = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
                timeout=WEB_SEARCH_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                return []

            payload = response.json()
            results: List[Dict[str, str]] = []

            abstract_text = str(payload.get("AbstractText") or "").strip()
            abstract_url = str(payload.get("AbstractURL") or "").strip()
            heading = str(payload.get("Heading") or "").strip() or "Quick answer"
            if abstract_text and abstract_url:
                results.append({"title": heading, "snippet": abstract_text, "url": abstract_url})

            related_topics = payload.get("RelatedTopics") or []
            for topic in related_topics:
                if not isinstance(topic, dict):
                    continue
                if topic.get("Topics") and isinstance(topic.get("Topics"), list):
                    for nested in topic.get("Topics"):
                        if not isinstance(nested, dict):
                            continue
                        text = str(nested.get("Text") or "").strip()
                        first_url = str(nested.get("FirstURL") or "").strip()
                        if text and first_url:
                            results.append({"title": "Related topic", "snippet": text, "url": first_url})
                        if len(results) >= WEB_SEARCH_MAX_RESULTS:
                            return results
                else:
                    text = str(topic.get("Text") or "").strip()
                    first_url = str(topic.get("FirstURL") or "").strip()
                    if text and first_url:
                        results.append({"title": "Related topic", "snippet": text, "url": first_url})
                if len(results) >= WEB_SEARCH_MAX_RESULTS:
                    break

            return results
        except Exception as exc:
            logger.warning("DuckDuckGo instant-answer fallback failed: %s", exc)
            return []

    def get_response(
        self,
        project_id: str,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        question_count: int = 0
    ) -> Dict[str, Any]:
        """
        Generate a response to user input and update specifications.
        
        Args:
            project_id: The project identifier
            user_message: The user's current message
            conversation_history: List of previous messages in format [{"role": "user"/"assistant", "content": "..."}]
            question_count: Current number of questions asked (0-10)
        
        Returns:
            Dictionary with:
                - response: The agent's conversational response
                - agent_thinking: The agent's analysis/thoughts on tech stack, features, etc.
                - next_questions: Suggested follow-up topics
                - spec_updated: Whether the spec file was updated
                - spec_preview: A text preview of current specs
                - question_count: Updated question count
                - questions_remaining: How many questions left (10 max)
                - must_execute: True if 10 questions reached
        """
        existing_specs = self._load_spec_file(project_id)
        web_context = self._build_web_context(user_message, existing_specs)
        web_context_used = bool(web_context)
        if web_context_used:
            logger.info("Questioning web context attached for project_id=%s", project_id)
        else:
            logger.info("Questioning web context unavailable for project_id=%s", project_id)
        
        # Check if we've hit the question limit
        questions_remaining = max(0, 10 - question_count)
        must_execute = question_count >= 10
        
        if must_execute:
            return {
                "response": "✨ We've gathered a lot of great information! You've reached the conversation limit (10 questions). Now it's time to execute and see your project come to life. Click the 'Execute & Generate Project' button to let the agents take over and build your specifications into reality.",
                "agent_thinking": "Conversation complete - ready for execution",
                "next_topics": [],
                "spec_updated": False,
                "spec_preview": existing_specs,
                "question_count": question_count,
                "questions_remaining": 0,
                "must_execute": True,
                "full_spec_path": self._get_spec_file_path(project_id),
                "web_context_used": web_context_used
            }
        
        system_prompt = f"""You are a friendly, collaborative Project Specification Agent that thinks out loud.

Your role is to have a natural conversation with users while ALSO sharing your evolving thinking about their project.
This is a TWO-WAY dialogue - you ask questions AND you share your insights about what you're learning.

IMPORTANT: You've asked {question_count}/10 questions. Keep track! After 10 questions, the conversation must end.
Current questions remaining: {questions_remaining}

CONVERSATION STYLE:
- Be warm, encouraging, and professional
- Ask clarifying questions (but track you've asked {question_count} so far)
- Show your thinking! Share what you're inferring about:
  * Potential tech stack based on their requirements
  * Features you're thinking would fit their vision
  * Design aesthetic and UI style that matches their goals
  * Architecture approach you're considering
- Use phrases like:
  * "Based on what you've told me, I'm thinking [tech stack]..."
  * "This sounds like a [style] application to me..."
  * "Key features I'm imagining: [features]..."
  * "For this, I'd suggest an architecture that..."
- Ask ONE follow-up question at a time (max 2)
- Build on previous answers to go deeper
- Celebrate progress: "Great! I'm getting a clearer picture..."
- Be concise but thoughtful

SPECIFICATION COVERAGE AREAS (explore gradually):
1. Project Vision & Goals
   - What problem does this solve?
   - Who are the primary users?
   - What success looks like

2. Core Features & Functionality
   - Top 3-5 must-have features
   - Nice-to-have features
   - Any features explicitly NOT wanted?

3. Technical Requirements
   - Preferred tech stack (or constraints)
   - Performance/scalability needs
   - Security/compliance requirements
   - Integration needs with external systems

4. User Experience & Design
   - Design preferences (modern, minimal, colorful...)
   - Target platforms (web, mobile, desktop)
   - Accessibility requirements

5. Data & Content
   - Data volume expectations
   - Content management needs
   - Reporting/analytics requirements

6. Timeline & Resources
   - Project timeline/urgency
   - Budget constraints
   - Team size/skills available
   - Deployment environment

RESPONSE STRUCTURE:
1. Acknowledge what they said
2. Share your thinking (tech stack, features, design, architecture ideas)
3. Ask ONE clarifying follow-up question
4. If {questions_remaining} == 0 after this, indicate conversation is ending

FINAL SPECIFICATION RULE:
- In the written specification, commit to ONE selected technology per category.
- Do not present alternatives like "A or B", "A/B", or comma-separated options.
- If requirements are unclear, make a best-fit recommendation and state assumptions.

IMPORTANT: Count the questions you ask. You've asked {question_count} so far.

Do NOT:
- Try to be overly technical without explaining
- Ask everything at once
- Lecture or be condescending
- Hold back your ideas - share your thinking freely!
- Generate code or technical designs yet"""

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add context about existing specs
        if existing_specs:
            messages.append({
                "role": "system",
                "content": f"CURRENT SPECIFICATIONS (for context):\n\n{existing_specs}\n\nBase your thinking and feedback on what's already been discussed."
            })

        # Add optional web context to ground recommendations in current external information.
        if web_context:
            messages.append({
                "role": "system",
                "content": web_context
            })
        
        # Add conversation history
        messages.extend(conversation_history)
        
        # Add the current user message
        messages.append({"role": "user", "content": user_message})
        
        _throttle_model_call()
        
        # Get conversational response
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=700
        )
        
        agent_response = response.choices[0].message.content
        
        # Extract agent's thinking (the portion about tech stack, features, etc.)
        agent_thinking = self._extract_agent_thinking(agent_response)
        
        # Now generate/update the specification document
        spec_update_prompt = [
            {
                "role": "system",
                "content": """You are a technical specification writer. Your job is to extract and organize information
from conversations into a clear, structured project specification in Markdown format.

OUTPUT FORMAT:
Generate a comprehensive markdown document with these sections (only include sections with information):

# Project Specification

## Project Vision
- **Problem Statement**: What problem does this solve?
- **Target Users**: Who are the primary users?
- **Success Criteria**: How will success be measured?

## Core Features
- List the main features and capabilities
- Include brief descriptions

## Technical Considerations
- Selected technology stack (single choice per category)
- Performance requirements
- Security/compliance needs
- Integration requirements

## User Experience & Design
- Design style/aesthetic
- Supported platforms
- Accessibility needs

## Data & Content
- Data volume/growth expectations
- Content management approach
- Reporting needs

## Timeline & Deployment
- Project timeline
- Deployment environment
- Hosting preferences

## Agent's Implementation Ideas
- Finalized tech stack decisions (single choice per category)
- Architecture approach
- Feature prioritization
- Design direction

GLOBAL OUTPUT RULES:
- The final specification must never include multiple alternatives for stack choices.
- Avoid any wording like "or", slashes, or multi-option lists for technology selections.

Keep it concise but comprehensive."""
            }
        ]
        
        if existing_specs:
            spec_update_prompt.append({
                "role": "system",
                "content": f"EXISTING SPECIFICATION:\n\n{existing_specs}\n\nUpdate and enhance this specification with new information from the conversation."
            })

        if web_context:
            spec_update_prompt.append({
                "role": "system",
                "content": f"OPTIONAL WEB CONTEXT TO USE FOR GROUNDING:\n\n{web_context}"
            })
        
        spec_update_prompt.append({
            "role": "user",
            "content": f"Extract and organize project information from this conversation:\n\nUser: {user_message}\n\nAgent: {agent_response}\n\nGenerate or update the project specification markdown."
        })
        
        _throttle_model_call()
        
        spec_response = self.client.chat.completions.create(
            model=self.model,
            messages=spec_update_prompt,
            temperature=0.3,
            max_tokens=2000
        )
        
        updated_spec = spec_response.choices[0].message.content
        self._save_spec_file(project_id, updated_spec)
        
        # Generate suggested next topics
        next_topics_prompt = [
            {"role": "system", "content": "You are a project planning expert. Based on the current conversation and specifications, suggest 2-3 key areas that should be explored next. Return JSON with 'topics' array containing strings. Be specific and actionable."},
            {"role": "user", "content": f"Current conversation context:\nUser message: {user_message}\nAgent: {agent_response}\n\nWhat should we discuss next? Return JSON."}
        ]

        if web_context:
            next_topics_prompt.insert(
                1,
                {"role": "system", "content": f"Context from web research (if relevant):\n{web_context}"},
            )
        
        _throttle_model_call()
        
        try:
            topics_response = self.client.chat.completions.create(
                model=self.model,
                messages=next_topics_prompt,
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=300
            )
            topics_data = json.loads(topics_response.choices[0].message.content)
            next_topics = topics_data.get("topics", [])
        except Exception:
            next_topics = [
                "Technical constraints and integrations",
                "Design and user experience preferences",
                "Timeline and deployment strategy"
            ]
        
        # Count only explicit follow-up question lines and bound per-turn increments.
        new_question_count = self._count_questions(agent_response)
        updated_question_count = min(10, question_count + new_question_count)
        updated_questions_remaining = max(0, 10 - updated_question_count)
        reached_limit = updated_question_count >= 10
        
        # Create a brief preview of the spec
        spec_lines = updated_spec.split('\n')
        spec_preview = '\n'.join(spec_lines[:30])
        if len(spec_lines) > 30:
            spec_preview += f"\n... ({len(spec_lines) - 30} more lines)"
        
        return {
            "response": agent_response,
            "agent_thinking": agent_thinking,
            "next_topics": next_topics[:2],
            "spec_updated": True,
            "spec_preview": spec_preview,
            "question_count": updated_question_count,
            "questions_remaining": updated_questions_remaining,
            "must_execute": reached_limit,
            "full_spec_path": self._get_spec_file_path(project_id),
            "web_context_used": web_context_used
        }

    def _extract_agent_thinking(self, response: str) -> str:
        """Extract the agent's thinking about tech stack, features, design, etc."""
        lines = response.split('\n')
        thinking_lines = []
        
        # Look for sections with agent's thinking
        thinking_keywords = [
            'thinking', 'sounds like', "i'm imagining", "i'd suggest",
            'tech stack', 'architecture', 'features', 'design', 'style',
            'considering', 'leaning towards', 'platform'
        ]
        
        for line in lines:
            lower_line = line.lower()
            if any(keyword in lower_line for keyword in thinking_keywords):
                thinking_lines.append(line.strip())
        
        if thinking_lines:
            return '\n'.join(thinking_lines[:5])  # Top 5 thinking lines
        
        # If no explicit thinking found, return a summary
        return "Gathering information about project vision and requirements..."

    def _count_questions(self, text: str) -> int:
        """Count explicit follow-up questions, capped to expected turn behavior."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        question_lines = [line for line in lines if line.endswith('?')]

        if question_lines:
            return min(2, len(question_lines))

        # Fallback for one-line responses that contain a single inline question.
        if '?' in text:
            return 1

        return 0

    def suggest_execution(self, project_id: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Check if specifications seem complete and suggest readiness for execution.
        
        Returns:
            Dictionary with:
                - is_ready: Boolean indicating if specs seem complete
                - message: Friendly message about readiness
                - missing_areas: List of any areas that could be expanded
        """
        existing_specs = self._load_spec_file(project_id)
        
        if not existing_specs:
            return {
                "is_ready": False,
                "message": "Let's gather some specifications first! Tell me about your project.",
                "missing_areas": ["Project vision", "Core features", "Technical requirements"]
            }
        
        readiness_prompt = [
            {
                "role": "system",
                "content": """You are a project readiness analyst. Evaluate if the provided specification document has enough detail
for an AI agent orchestration system to generate code and architecture.

Respond with JSON containing:
{
    "is_complete": true/false,
    "completeness_percentage": 0-100,
    "missing_areas": ["area1", "area2"],
    "assessment": "Brief assessment message"
}

A specification is "complete" (70%+) if it covers:
- Clear project vision and goals
- At least 5+ core features
- Some technical preferences or constraints
- User experience expectations
- Timeline/deployment info

It's "very complete" (85%+) if it also covers:
- Detailed feature descriptions
- Specific tech stack choices
- Security/performance requirements
- Integration needs
- Data modeling specifics"""
            },
            {
                "role": "user",
                "content": f"Evaluate this specification for readiness:\n\n{existing_specs}"
            }
        ]
        
        _throttle_model_call()
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=readiness_prompt,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=400
            )
            assessment = json.loads(response.choices[0].message.content)
            is_ready = assessment.get("completeness_percentage", 0) >= 70
        except Exception:
            assessment = {
                "is_complete": True,
                "completeness_percentage": 60,
                "missing_areas": [],
                "assessment": "Ready to start execution"
            }
            is_ready = True
        
        missing_areas = assessment.get("missing_areas", [])
        
        message = assessment.get("assessment", "Your specification is ready!")
        if is_ready and not missing_areas:
            message = "✨ Your specification looks complete! You can proceed to execution whenever you're ready."
        elif is_ready:
            message = f"Good progress! {message} You could optionally detail: {', '.join(missing_areas[:2])}."
        else:
            message = f"Let's add more detail. I'd suggest exploring: {', '.join(missing_areas[:3])}."
        
        return {
            "is_ready": is_ready,
            "completeness": assessment.get("completeness_percentage", 60),
            "message": message,
            "missing_areas": missing_areas,
            "full_spec_path": self._get_spec_file_path(project_id)
        }
