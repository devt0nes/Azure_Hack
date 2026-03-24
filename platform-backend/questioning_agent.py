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
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT")
MODEL_CALL_DELAY_MIN = float(os.getenv("MODEL_CALL_DELAY_MIN", "1.0"))
MODEL_CALL_DELAY_MAX = float(os.getenv("MODEL_CALL_DELAY_MAX", "2.0"))


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
                "full_spec_path": self._get_spec_file_path(project_id)
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
- Technology stack ideas based on requirements
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
- Tech stack considerations
- Architecture approach
- Feature prioritization
- Design direction

Keep it concise but comprehensive."""
            }
        ]
        
        if existing_specs:
            spec_update_prompt.append({
                "role": "system",
                "content": f"EXISTING SPECIFICATION:\n\n{existing_specs}\n\nUpdate and enhance this specification with new information from the conversation."
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
        
        # Count questions in the agent response
        new_question_count = self._count_questions(agent_response)
        updated_question_count = question_count + new_question_count
        updated_questions_remaining = max(0, 10 - updated_question_count)
        
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
            "must_execute": False,
            "full_spec_path": self._get_spec_file_path(project_id)
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
        """Count the number of questions in a text (by counting '?')."""
        return text.count('?')

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
