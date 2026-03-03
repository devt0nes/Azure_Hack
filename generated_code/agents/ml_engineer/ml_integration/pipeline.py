import os
import json
import logging
from transformers import GPT4Tokenizer, GPT4Model, pipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "your_openai_api_key")
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO")
logging.getLogger().setLevel(LOGGING_LEVEL)

# Ensure responsible AI practices
def validate_input(prompt):
    """
    Validate the user's input to avoid harmful or malicious content.
    Args:
        prompt (str): The user's input prompt.
    Returns:
        bool: True if the input is valid, False otherwise.
    """
    prohibited_keywords = ["hate speech", "violence", "illegal"]
    for keyword in prohibited_keywords:
        if keyword.lower() in prompt.lower():
            return False
    return True

# Load GPT-4 model
def load_model():
    """
    Load the GPT-4 model using Hugging Face or OpenAI API.
    Returns:
        pipeline: A transformer pipeline object for inference.
    """
    try:
        logger.info("Loading GPT-4 model...")
        tokenizer = GPT4Tokenizer.from_pretrained(MODEL_NAME)
        model = GPT4Model.from_pretrained(MODEL_NAME)
        text_generator = pipeline("text-generation", model=model, tokenizer=tokenizer)
        logger.info("Model loaded successfully.")
        return text_generator
    except Exception as e:
        logger.error(f"Error loading model: {e}")
        raise e

# Initialize the inference pipeline
model_pipeline = load_model()

# Inference function
def generate_response(prompt):
    """
    Generate a response using the GPT-4 model.
    Args:
        prompt (str): The user's input prompt.
    Returns:
        str: The model's response.
    """
    if not validate_input(prompt):
        return "Input contains prohibited content and cannot be processed."

    try:
        logger.info(f"Generating response for prompt: {prompt}")
        response = model_pipeline(prompt, max_length=200, num_return_sequences=1)
        return response[0]['generated_text']
    except Exception as e:
        logger.error(f"Error during inference: {e}")
        return "An error occurred during processing. Please try again later."