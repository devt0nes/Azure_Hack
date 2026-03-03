import os
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# FastAPI initialization
app = FastAPI()

# ML Model Configuration
MODEL_NAME = "gpt-4o"  # Replace with actual model name
CACHE_DIR = "./model_cache"

# Load model and tokenizer
logging.info("Loading model and tokenizer...")
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
    gpt_pipeline = pipeline("text-generation", model=model, tokenizer=tokenizer)
    logging.info("Model loaded successfully.")
except Exception as e:
    logging.error(f"Error loading model: {e}")
    raise RuntimeError("Failed to load model.")

# Request schema
class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 100
    temperature: float = 0.7

# Health check endpoint
@app.get("/health")
def health_check():
    """
    Health check endpoint to ensure the service is running.
    """
    return {"status": "healthy"}

# Inference endpoint
@app.post("/generate")
def generate_text(request: PromptRequest):
    """
    Generate text using the AI model.
    :param request: PromptRequest containing the prompt, max_tokens, and temperature
    :return: Generated text
    """
    try:
        logging.info(f"Received prompt: {request.prompt}")
        result = gpt_pipeline(
            request.prompt,
            max_length=request.max_tokens,
            temperature=request.temperature,
            num_return_sequences=1
        )
        response_text = result[0]["generated_text"]
        logging.info(f"Generated text: {response_text}")
        return {"generated_text": response_text}
    except Exception as e:
        logging.error(f"Inference error: {e}")
        raise HTTPException(status_code=500, detail="Inference failed.")

# Run server (for local development)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)