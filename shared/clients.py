"""
Azure OpenAI client utilities for Agentic Nexus.
Provides wrappers for gpt-4o and gpt-4o-mini models.
"""

import os
import json
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize Azure OpenAI client
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_DEPLOYMENT_MINI = os.getenv("AZURE_OPENAI_DEPLOYMENT_MINI", "gpt-4o-mini")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)


def call_gpt4o(prompt: str, temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """
    Call GPT-4o model with the provided prompt.
    
    Args:
        prompt: The input prompt
        temperature: Temperature for response creativity (0.0-1.0)
        max_tokens: Maximum tokens in response
        
    Returns:
        The model's response as a string
    """
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Error calling GPT-4o: {str(e)}")


def call_gpt4o_mini(prompt: str, temperature: float = 0.7, max_tokens: int = 2048) -> str:
    """
    Call GPT-4o-mini model with the provided prompt (faster, cheaper).
    
    Args:
        prompt: The input prompt
        temperature: Temperature for response creativity (0.0-1.0)
        max_tokens: Maximum tokens in response
        
    Returns:
        The model's response as a string
    """
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_MINI,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Error calling GPT-4o-mini: {str(e)}")
