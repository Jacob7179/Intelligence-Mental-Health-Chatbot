# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Place your model folders:
# - emotion_model/ (with config.json, label_encoder.pkl, model.safetensors, etc.)
# - counselor_model/ (with adapter files and tokenizer files)

# Run the application
python app.py