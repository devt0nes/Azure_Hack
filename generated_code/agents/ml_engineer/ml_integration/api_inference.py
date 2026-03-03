from flask import Flask, request, jsonify
from pipeline import generate_response

app = Flask(__name__)

@app.route("/api/infer", methods=["POST"])
def infer():
    """
    API endpoint for generating responses using the GPT-4 model.
    """
    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Invalid request. 'prompt' is required."}), 400

    prompt = data["prompt"]
    response = generate_response(prompt)
    return jsonify({"response": response}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)