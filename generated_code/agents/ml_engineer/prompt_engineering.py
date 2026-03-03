import json

# Predefined prompt templates
PROMPT_TEMPLATES = {
    "generic_question": "Answer the following question clearly and concisely: {question}",
    "story_generation": "Generate a creative story based on: {input}",
    "technical_explanation": "Provide a detailed, technical explanation about: {topic}",
}

def generate_prompt(template_name, **kwargs):
    """
    Generate a prompt based on a template and provided arguments.
    :param template_name: Name of the prompt template
    :param kwargs: Arguments to populate the template
    :return: Generated prompt string
    """
    try:
        template = PROMPT_TEMPLATES[template_name]
        return template.format(**kwargs)
    except KeyError:
        raise ValueError(f"Template '{template_name}' not found.")
    except Exception as e:
        raise RuntimeError(f"Error generating prompt: {e}")

if __name__ == "__main__":
    # Example usage
    example_prompt = generate_prompt("generic_question", question="What is the capital of Germany?")
    print("Generated Prompt:", example_prompt)