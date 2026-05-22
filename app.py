from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from functools import wraps
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import pickle
import os
import gc
import re
import random
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from openai import OpenAI
import requests
import json
import warnings
from datetime import datetime
from bson import ObjectId
import pymongo
from pymongo import MongoClient
import uuid
import hashlib
import base64
import imghdr
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

warnings.filterwarnings('ignore')

MAX_PROFILE_IMAGE_SIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def is_allowed_image(content_type, filename):
    """Check if uploaded image is allowed"""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return content_type in ['image/jpeg', 'image/png', 'image/gif'] and ext in ALLOWED_IMAGE_EXTENSIONS

def validate_image_base64(image_base64):
    """Validate and extract image data from base64 string"""
    if not image_base64:
        return None
    # Check format: data:image/xxx;base64,...
    if not image_base64.startswith('data:image/'):
        return None
    try:
        header, data = image_base64.split(',', 1)
        # Validate file size
        if len(data) > MAX_PROFILE_IMAGE_SIZE:
            return None
        # Decode to verify it's valid
        decoded = base64.b64decode(data)
        # Check image type
        image_type = imghdr.what(None, decoded)
        if image_type not in ALLOWED_IMAGE_EXTENSIONS:
            return None
        return image_base64  # store as is
    except Exception:
        return None

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here-change-in-production')
CORS(app, supports_credentials=True)

# MongoDB Configuration
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
MONGODB_DB = os.getenv('MONGODB_DB', 'mental_health_chatbot')

# Global MongoDB client
mongo_client = None
db = None
users_collection = None
conversations_collection = None
messages_collection = None
admins_collection = None

def init_mongodb():
    """Initialize MongoDB connection with retry logic"""
    global mongo_client, db, users_collection, conversations_collection, messages_collection, admins_collection
    
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping')
        
        db = mongo_client[MONGODB_DB]
        
        # Create collections if they don't exist
        users_collection = db['users']
        conversations_collection = db['conversations']
        messages_collection = db['messages']
        admins_collection = db['admins']
        
        # Create indexes
        if users_collection is not None:
            users_collection.create_index([("username", pymongo.ASCENDING)], unique=True)
            users_collection.create_index([("email", pymongo.ASCENDING)], unique=True)
            users_collection.create_index([("is_guest", pymongo.ASCENDING)])
        
        if conversations_collection is not None:
            conversations_collection.create_index([("user_id", pymongo.ASCENDING)])
            conversations_collection.create_index([("user_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])
        
        if messages_collection is not None:
            messages_collection.create_index([("conversation_id", pymongo.ASCENDING)])
            messages_collection.create_index([("conversation_id", pymongo.ASCENDING), ("timestamp", pymongo.ASCENDING)])
        
        print(f"✓ Connected to MongoDB: {MONGODB_DB}")
        
        # Create default admin if not exists
        if admins_collection is not None:
            if not admins_collection.find_one({'admin_id': 'admin001'}):
                default_admin = {
                    'admin_id': 'admin001',
                    'name': 'Super Admin',
                    'email': 'admin@mentalhealth.com',
                    'password_hash': generate_password_hash('admin123'),
                    'created_at': datetime.utcnow()
                }
                admins_collection.insert_one(default_admin)
                print("✓ Default admin created (ID: admin001, Password: admin123)")
        
        return True
        
    except Exception as e:
        print(f"⚠️ MongoDB connection error: {e}")
        mongo_client = None
        db = None
        users_collection = None
        conversations_collection = None
        messages_collection = None
        admins_collection = None
        return False

# In-memory storage for fallback when MongoDB is not available
IN_MEMORY_USERS = {}
IN_MEMORY_CONVERSATIONS = {}
IN_MEMORY_MESSAGES = {}

# Global variables
emotion_tokenizer = None
emotion_model = None
label_encoder = None

# API Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
current_api = DEFAULT_API = 'gemini'

# Device configuration
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Crisis keywords for safety
CRISIS_KEYWORDS = [
    'die', 'kill', 'suicide', 'end my life', 'want to die', 'better off dead', 
    'hurt myself', 'self harm', 'cut myself', 'overdose', 'jump', 'hang myself',
    'kill myself', 'take my life', 'end it all', 'no reason to live', 'want to end it',
    'commit suicide', 'suicidal', 'self-harm'
]

# Authentication decorator - now works for both registered and guest users
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required', 'redirect': '/login'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/user-profile', methods=['GET'])
@login_required
def get_user_profile():
    """Get current user's profile including email, age, gender, profile_image"""
    try:
        user_id = session['user_id']
        
        if is_mongodb_connected():
            user = users_collection.find_one({'user_id': user_id})
            if user:
                return jsonify({
                    'success': True,
                    'username': user.get('username'),
                    'email': user.get('email'),
                    'is_guest': user.get('is_guest', False),
                    'age': user.get('age'),
                    'gender': user.get('gender'),
                    'profile_image': user.get('profile_image')
                })
        else:
            if user_id in IN_MEMORY_USERS:
                user = IN_MEMORY_USERS[user_id]
                return jsonify({
                    'success': True,
                    'username': user.get('username'),
                    'email': user.get('email'),
                    'is_guest': user.get('is_guest', False),
                    'age': user.get('age'),
                    'gender': user.get('gender'),
                    'profile_image': user.get('profile_image')
                })
        
        return jsonify({'success': False, 'error': 'User not found'}), 404
        
    except Exception as e:
        print(f"Error fetching user profile: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/user-profile', methods=['PUT'])
@login_required
def update_user_profile():
    """Update user profile: name, age, gender, profile_image"""
    try:
        user_id = session['user_id']
        
        # Check if guest user
        if session.get('is_guest', False):
            return jsonify({'error': 'Guest accounts cannot edit profile. Please sign up.'}), 403
        
        data = request.json
        updates = {}
        
        # Update username (name)
        new_name = data.get('username', '').strip()
        if new_name:
            if len(new_name) < 2 or len(new_name) > 50:
                return jsonify({'error': 'Name must be between 2 and 50 characters'}), 400
            updates['username'] = new_name
        
        # Update age
        age = data.get('age')
        if age is not None:
            try:
                age_int = int(age)
                if age_int < 1 or age_int > 120:
                    return jsonify({'error': 'Age must be between 1 and 120'}), 400
                updates['age'] = age_int
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid age format'}), 400
        
        # Update gender
        gender = data.get('gender')
        if gender is not None:
            valid_genders = ['Male', 'Female', 'Other', 'Prefer not to say']
            if gender not in valid_genders and gender != '':
                return jsonify({'error': 'Invalid gender option'}), 400
            updates['gender'] = gender if gender else None
        
        # Update profile image
        profile_image = data.get('profile_image')
        if profile_image is not None:
            # Allow removing image by sending empty string or null
            if profile_image == '' or profile_image is None:
                updates['profile_image'] = None
            else:
                validated_image = validate_image_base64(profile_image)
                if not validated_image:
                    return jsonify({'error': 'Invalid image format or size too large (max 2MB)'}), 400
                updates['profile_image'] = validated_image
        
        if not updates:
            return jsonify({'error': 'No valid fields to update'}), 400
        
        updates['updated_at'] = datetime.utcnow()
        
        if is_mongodb_connected():
            result = users_collection.update_one(
                {'user_id': user_id},
                {'$set': updates}
            )
            if result.matched_count == 0:
                return jsonify({'error': 'User not found'}), 404
        else:
            if user_id in IN_MEMORY_USERS:
                IN_MEMORY_USERS[user_id].update(updates)
            else:
                return jsonify({'error': 'User not found'}), 404
        
        # Update session username if changed
        if 'username' in updates:
            session['username'] = updates['username']
        
        return jsonify({
            'success': True,
            'message': 'Profile updated successfully',
            'updated_fields': updates
        })
        
    except Exception as e:
        print(f"Error updating user profile: {e}")
        return jsonify({'error': str(e)}), 500

def check_safety(user_input):
    """Check for crisis situations"""
    user_lower = user_input.lower()
    for keyword in CRISIS_KEYWORDS:
        if keyword in user_lower:
            return True, keyword
    return False, None

def load_emotion_model():
    """Load the MobileBERT emotion detection model from local folder"""
    global emotion_tokenizer, emotion_model, label_encoder
    
    model_path = "emotion_model"
    
    if not os.path.exists(model_path):
        print(f"NOTE: {model_path} folder not found! Using keyword-based detection only.")
        return False
    
    try:
        print(f"\n📦 Loading emotion model from {model_path}...")
        
        # Load tokenizer from local folder
        emotion_tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=True,
            local_files_only=True
        )
        
        # Load model from local folder
        emotion_model = AutoModelForSequenceClassification.from_pretrained(
            model_path,
            trust_remote_code=True,
            local_files_only=True
        )
        emotion_model.to(device)
        emotion_model.eval()
        
        # Load label encoder
        label_path = os.path.join(model_path, "label_encoder.pkl")
        if os.path.exists(label_path):
            with open(label_path, 'rb') as f:
                label_encoder = pickle.load(f)
            print(f"✓ Loaded {len(label_encoder.classes_)} emotion labels: {list(label_encoder.classes_)}")
        else:
            print("⚠️ Label encoder not found, using default emotions")
            from sklearn.preprocessing import LabelEncoder
            label_encoder = LabelEncoder()
            default_emotions = ['sad', 'happy', 'angry', 'anxious', 'neutral', 'fear', 'surprise', 'love']
            label_encoder.fit(default_emotions)
        
        print("✓ Emotion model loaded successfully")
        return True
        
    except Exception as e:
        print(f"Error loading emotion model: {e}")
        return False

def enhanced_keyword_detection(text):
    """Enhanced keyword-based emotion detection with scoring system"""
    text_lower = text.lower()
    
    # Check for very short positive responses first
    short_positive = ['good', 'great', 'fine', 'ok', 'okay', 'im good', "i'm good", 'doing good', 'feeling good']
    if text_lower in short_positive:
        return 'happy', 0.95
    
    # Comprehensive emotion keywords with weights
    emotion_keywords = {
        'happy': {
            'primary': ['happy', 'joy', 'glad', 'wonderful', 'great', 'excited', 'amazing',
                    'awesome', 'fantastic', 'won', 'champion', 'victory', 'success', 'celebrate',
                    'blessed', 'grateful', 'thankful', 'delighted', 'pleased', 'thrilled',
                    'ecstatic', 'overjoyed', 'elated', 'cheerful', 'optimistic', 'bright',
                    'sunny', 'smile', 'laugh', 'fun', 'enjoy', 'love life', 'good day', 'good',
                    'feel good', 'looking forward', 'can\'t wait', 'so happy', 'very happy',
                    'bliss', 'blissful', 'content', 'satisfied', 'jubilant', 'exhilarated',
                    'radiant', 'upbeat', 'joyful', 'playful', 'hopeful', 'lighthearted',
                    'on cloud nine', 'over the moon', 'walking on air', 'in high spirits',
                    'made my day', 'best day ever', 'living the dream', 'couldn\'t be happier'],
            'weight': 2
        },
        'sad': {
            'primary': ['sad', 'depressed', 'unhappy', 'down', 'cry', 'lonely', 'hurt', 'grief',
                    'heartbroken', 'miserable', 'devastated', 'hopeless', 'despair', 'gloomy',
                    'tears', 'weep', 'sorrow', 'pain', 'suffering', 'empty', 'lost', 'alone',
                    'isolated', 'rejected', 'abandoned', 'worthless', 'useless', 'failure',
                    'so sad', 'very sad', 'feeling sad',
                    'gloom', 'melancholy', 'mourn', 'mourning', 'anguish', 'downcast',
                    'dismal', 'bleak', 'heavy heart', 'heartache', 'broken', 'crushed',
                    'defeated', 'numb', 'withdrawn', 'tearful', 'weepy', 'blue', 'feeling blue',
                    'in a funk', 'low', 'rough day', 'can\'t stop crying', 'no energy',
                    'what\'s the point', 'falling apart'],
            'weight': 2
        },
        'angry': {
            'primary': ['angry', 'mad', 'frustrated', 'annoyed', 'furious', 'rage', 'hate',
                    'irritated', 'upset', 'bitter', 'resentful', 'hostile', 'aggressive',
                    'enraged', 'livid', 'outraged', 'fuming', 'explode', 'fight', 'argue',
                    'yell', 'scream', 'shout', 'curse', 'damn', 'hateful', 'vengeful',
                    'exasperated', 'infuriated', 'incensed', 'indignant', 'irate', 'seething',
                    'wrath', 'wrathful', 'cross', 'grumpy', 'cranky', 'pissed', 'pissed off',
                    'fed up', 'sick of', 'boiling', 'heated', 'storming', 'bitter',
                    'grudge', 'vengeance', 'want to scream', 'seeing red', 'blowing off steam'],
            'weight': 2
        },
        'anxious': {
            'primary': ['anxious', 'nervous', 'worried', 'stressed', 'panic', 'overwhelmed',
                    'uneasy', 'restless', 'tense', 'apprehensive', 'dread', 'fearful',
                    'scared', 'terrified', 'frightened', 'horrified', 'alarmed', 'panicky',
                    'jittery', 'on edge', 'butterflies', 'heart racing', 'sweating',
                    'worry', 'concerned', 'unease',
                    'distressed', 'agitated', 'frazzled', 'rattled', 'high-strung',
                    'keyed up', 'wound up', 'freaked out', 'freaking out', 'losing sleep',
                    'racing thoughts', 'can\'t breathe', 'impending doom', 'worst case scenario',
                    'what if', 'overthinking', 'analysis paralysis', 'second guessing',
                    'biting nails', 'pacing', 'dreading tomorrow'],
            'weight': 2
        },
        'fear': {
            'primary': ['scared', 'afraid', 'terrified', 'fear', 'horror', 'nightmare',
                    'spooked', 'petrified', 'panicked', 'dreading', 'ominous', 'threatened',
                    'danger', 'unsafe', 'vulnerable', 'exposed', 'helpless', 'trapped',
                    'frightened', 'fearful',
                    'paranoid', 'cowering', 'trembling', 'shaking', 'frozen', 'paralyzed',
                    'horrifying', 'chilling', 'menacing', 'sinister', 'unease', 'creepy',
                    'haunted', 'terrifying', 'panic-stricken', 'hysterical', 'phobia',
                    'scared stiff', 'scared to death', 'heart in throat', 'can\'t move',
                    'running scared', 'hiding', 'bad feeling', 'something bad will happen'],
            'weight': 2
        },
        'love': {
            'primary': ['love', 'adore', 'care', 'passion', 'affection', 'fond', 'cherish',
                    'treasure', 'devoted', 'attached', 'romantic', 'heart', 'sweet',
                    'kindness', 'compassion', 'empathy', 'warmth', 'caring', 'tender',
                    'i love', 'loving',
                    'infatuated', 'enamored', 'smitten', 'captivated', 'besotted',
                    'worship', 'admire', 'respect deeply', 'care deeply', 'appreciate',
                    'close to my heart', 'mean the world', 'my everything', 'forever',
                    'soulmate', 'partner', 'my rock', 'supportive', 'gentle', 'thoughtful',
                    'cuddle', 'hug', 'kiss', 'holding hands', 'quality time'],
            'weight': 2
        },
        'surprise': {
            'primary': ['surprised', 'shocked', 'astonished', 'amazed', 'stunned', 'speechless',
                    'unexpected', 'startled', 'floored', 'dumbfounded', 'bewildered',
                    'mind blown', 'unbelievable', 'incredible', 'shocking', 'sudden',
                    'astounded', 'flabbergasted', 'dazzled', 'awestruck', 'thunderstruck',
                    'jaw dropped', 'caught off guard', 'out of nowhere', 'bolt from the blue',
                    'turn of events', 'whirlwind', 'who would have thought', 'no way',
                    'are you serious', 'stop it', 'you\'re kidding', 'impossible',
                    'how is that possible', 'staggering', 'mind-boggling'],
            'weight': 1.5
        },
        'neutral': {
            'primary': ['okay', 'fine', 'alright', 'so-so', 'nothing special', 'as usual',
                    'normal', 'regular', 'typical', 'standard', 'common',
                    'meh', 'decent', 'moderate', 'average', 'mediocre', 'unremarkable',
                    'ordinary', 'commonplace', 'everyday', 'neutral', 'indifferent',
                    'unbothered', 'whatever', 'don\'t care', 'no strong feelings',
                    'go with the flow', 'same old', 'nothing new', 'business as usual',
                    'just another day', 'nothing to report', 'could be worse'],
            'weight': 1
        }
    }
    
    # Calculate scores for each emotion
    scores = {emotion: 0 for emotion in emotion_keywords}
    
    for emotion, keywords_dict in emotion_keywords.items():
        score = 0
        # Check primary keywords
        for keyword in keywords_dict['primary']:
            if keyword in text_lower:
                score += keywords_dict['weight']
                # Bonus for exact word matches (word boundaries)
                if re.search(rf'\b{keyword}\b', text_lower):
                    score += 0.5
        
        # Check for negation (reverse some emotions if negated)
        negation_words = ['not', "n't", 'never', 'no longer', 'used to be', 'wasn\'t', 'weren\'t']
        has_negation = any(neg in text_lower for neg in negation_words)
        
        if has_negation and emotion in ['happy', 'hopeful']:
            score = max(0, score - 3)
        
        scores[emotion] = score
    
    # Find highest scoring emotion
    max_score = max(scores.values())
    if max_score > 0:
        detected = max(scores, key=scores.get)
        confidence = min(max_score / 10, 0.95)
    else:
        detected = 'neutral'
        confidence = 0.5
    
    return detected, confidence

def preprocess_text(text):
    """Clean and preprocess text for better emotion detection"""
    # Convert to lowercase
    text = text.lower()
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    # Handle common phrases
    text = re.sub(r'\bim\b', 'i am', text)
    text = re.sub(r'\bi\'m\b', 'i am', text)
    text = re.sub(r'\bhes\b', 'he is', text)
    text = re.sub(r'\bshes\b', 'she is', text)
    text = re.sub(r'\btheyre\b', 'they are', text)
    text = re.sub(r'\bwe\'re\b', 'we are', text)
    text = re.sub(r'\bthat\'s\b', 'that is', text)
    text = re.sub(r'\bit\'s\b', 'it is', text)
    
    return text

def detect_emotion(text):
    """Detect emotion with priority on keyword detection for accuracy"""
    
    # First, check for crisis
    is_crisis, keyword = check_safety(text)
    if is_crisis:
        return 'crisis', 1.0
    
    # Preprocess text
    clean_text = preprocess_text(text)
    text_lower = clean_text.lower()
    
    # PRIORITY 0: Check for positive affirmations FIRST (before anything else)
    positive_affirmations = [
        r'\bgood\b', r'\bgreat\b', r'\bfine\b', r'\bokay\b', r'\bok\b', r'\bhi\b',
        r'\bhappy\b', r'\bglad\b', r'\bjoy\b', r'\bwonderful\b', r'\bawesome\b', r'\bgreeting\b',
        r'\bdoing well\b', r'\bfeeling good\b', r"\bm good\b", r"\bm fine\b"
    ]
    
    for pattern in positive_affirmations:
        if re.search(pattern, text_lower):
            # Check if it's NOT negated
            if not re.search(rf'not\s+{pattern}|n\'t\s+{pattern}', text_lower):
                return 'happy', 0.95
    
    # Special case: "happy" detection - if user explicitly says "happy", it should be HAPPY
    if re.search(r'\bhappy\b', text_lower) or re.search(r'\bglad\b', text_lower) or re.search(r'\bjoy\b', text_lower):
        if 'sad' not in text_lower and 'unhappy' not in text_lower:
            return 'happy', 0.95
    
    # Special case: "good" or similar short positive responses
    if text_lower in ['good', 'great', 'fine', 'ok', 'okay', 'doing good', 'im good', "i'm good", 'feeling good']:
        return 'happy', 0.95
    
    # Special case: "sad" detection
    if re.search(r'\bsad\b', text_lower) or re.search(r'\bdepressed\b', text_lower):
        return 'sad', 0.95
    
    # Special case: "angry" detection
    if re.search(r'\bangry\b', text_lower) or re.search(r'\bmad\b', text_lower):
        return 'angry', 0.95
    
    # Special case: "anxious" detection
    if re.search(r'\banxious\b', text_lower) or re.search(r'\bnervous\b', text_lower):
        return 'anxious', 0.95
    
    # Special case: "love" detection
    if re.search(r'\blove\b', text_lower) or re.search(r'\badore\b', text_lower):
        return 'love', 0.95
    
    # PRIORITY 1: Use enhanced keyword detection (more reliable for specific emotions)
    keyword_emotion, keyword_confidence = enhanced_keyword_detection(clean_text)
    
    # If keyword confidence is high (>0.7), use keyword detection
    if keyword_confidence > 0.7:
        return keyword_emotion, keyword_confidence
    
    # PRIORITY 2: Try model prediction if available
    if emotion_tokenizer is not None and emotion_model is not None:
        try:
            # Tokenize input
            inputs = emotion_tokenizer(
                clean_text,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128
            )
            
            # Move to device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            
            # Get prediction
            with torch.no_grad():
                outputs = emotion_model(**inputs)
                probabilities = F.softmax(outputs.logits, dim=-1)
                predicted_class = torch.argmax(probabilities, dim=-1).item()
                model_confidence = probabilities[0][predicted_class].item()
                
                # Get emotion label
                if label_encoder is not None:
                    model_emotion = label_encoder.inverse_transform([predicted_class])[0]
                else:
                    model_emotion = 'neutral'
                
                # Map model emotion to our standard categories
                emotion_mapping = {
                    'joy': 'happy',
                    'sadness': 'sad',
                    'anger': 'angry',
                    'fear': 'anxious',
                    'love': 'love',
                    'surprise': 'surprise',
                    'neutral': 'neutral'
                }
                
                model_emotion = emotion_mapping.get(model_emotion, model_emotion)
            
            # If model confidence is high and not conflicting with keyword detection
            if model_confidence > 0.8:
                # Check if model and keyword agree
                if model_emotion == keyword_emotion:
                    return model_emotion, model_confidence
                else:
                    # If they disagree, trust keyword detection if it has reasonable confidence
                    if keyword_confidence > 0.5:
                        return keyword_emotion, keyword_confidence
                    else:
                        return model_emotion, model_confidence
            
            # If model confidence is medium, blend with keyword
            elif model_confidence > 0.6:
                if keyword_confidence > model_confidence:
                    return keyword_emotion, keyword_confidence
                else:
                    return model_emotion, model_confidence
            
        except Exception as e:
            print(f"Error in emotion detection: {e}")
            return keyword_emotion, keyword_confidence
    
    # PRIORITY 3: Fallback to keyword detection
    return keyword_emotion, keyword_confidence

def generate_response_with_gemini(user_input, emotion, confidence):
    """Generate response using Google's Gemini API"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""You are a compassionate mental health counselor. The user is feeling {emotion} (confidence: {confidence:.2%}). 
        User said: "{user_input}"
        
        Generate an empathetic, supportive response that directly addresses what the user said. Keep the response warm, professional, and helpful (2-3 sentences)."""
        
        response = model.generate_content(prompt)
        return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

def generate_response_with_fallback(user_input, emotion, confidence):
    """Fallback template-based responses if APIs fail"""
    
    # Crisis response
    is_crisis, _ = check_safety(user_input)
    if is_crisis:
        return get_crisis_response()
    
    # Template responses for different emotions
    responses = {
        'happy': [
            f"That's wonderful to hear! 😊 Tell me more about what's making you feel this way.",
            f"I'm glad you're feeling positive! What's contributing to your happiness?",
            f"Great to hear! 🎉 Would you like to share more about what's bringing you joy?",
            f"Your happiness brightens the conversation! What's been going well for you?",
            f"I love hearing that you're happy! What's making you feel this way?"
        ],
        'sad': [
            f"I hear that you're feeling down. I'm here to listen. What's been on your mind?",
            f"I'm sorry you're feeling this way. Would you like to talk about it?",
            f"Thank you for sharing. Sometimes talking helps. What's been happening?",
            f"It's okay to feel sad. I'm here with you. Can you tell me more?",
            f"Your feelings matter. What's been making you feel this way?"
        ],
        'angry': [
            f"I can sense your frustration. It's okay to feel angry. Would you like to tell me what happened?",
            f"That sounds really frustrating. I'm here to listen.",
            f"I hear your anger. Let's talk about what's causing these feelings.",
            f"Your anger is valid. What's been triggering these emotions?",
            f"It sounds like something has upset you. Want to talk about it?"
        ],
        'anxious': [
            f"I hear that you're feeling anxious. Let's take a moment. What's worrying you?",
            f"Anxiety can be tough. I'm here with you. Can you tell me what's making you feel this way?",
            f"It sounds like you're carrying a lot of worry. Would it help to talk through it?",
            f"Let's breathe together. What's causing your anxiety right now?",
            f"I'm here to help you work through these anxious feelings."
        ],
        'fear': [
            f"It's okay to feel afraid. I'm here with you. What's frightening you?",
            f"Fear can be overwhelming. Let's talk about what's making you feel this way.",
            f"You're safe here. Can you share what's causing your fear?",
            f"I understand feeling scared. Would it help to talk about it?"
        ],
        'love': [
            f"That's beautiful! 💕 Tell me more about these feelings.",
            f"Love is such a powerful emotion. What's making you feel this way?",
            f"I'm glad you're experiencing love. Would you like to share more?",
            f"Those are wonderful feelings to have. Tell me more!"
        ],
        'surprise': [
            f"That sounds surprising! Tell me more about what happened.",
            f"Wow, that's unexpected! How are you processing this?",
            f"I'm intrigued! Can you share more details?"
        ],
        'neutral': [
            f"Thanks for sharing that with me. How are you feeling about it?",
            f"I appreciate you telling me that. Is there more you'd like to share?",
            f"I hear you. How can I best support you right now?",
            f"Thank you for opening up. What's on your mind today?"
        ]
    }
    
    emotion_lower = emotion.lower()
    if emotion_lower not in responses:
        emotion_lower = 'neutral'
    
    return random.choice(responses[emotion_lower])

def get_crisis_response():
    """Emergency response for crisis situations"""
    return """I'm really concerned about what you just shared. Please know that you matter and help is available.

**Immediate Support Resources:**
- 🚨 **Crisis Hotline:** 988 (Suicide & Crisis Lifeline)
- 💬 **Crisis Text Line:** Text HOME to 741741
- 🏥 **Emergency Services:** Call 911

You don't have to go through this alone. Please reach out to these resources right now. Your safety is the most important thing."""

def is_mongodb_connected():
    """Check if MongoDB is connected"""
    return mongo_client is not None and users_collection is not None

def save_conversation_to_db(user_id, conversation_id, title=None):
    """Create or update conversation record (now with rating field)"""
    if is_mongodb_connected():
        try:
            existing = conversations_collection.find_one({
                "user_id": user_id,
                "conversation_id": conversation_id
            })
            
            if not existing:
                conversation_doc = {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "title": title or "New Conversation",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "message_count": 0,
                    "rating": None
                }
                conversations_collection.insert_one(conversation_doc)
            
            return conversation_id
        except Exception as e:
            print(f"Error saving conversation to DB: {e}")
    
    # Fallback to in-memory storage
    if user_id not in IN_MEMORY_CONVERSATIONS:
        IN_MEMORY_CONVERSATIONS[user_id] = {}
    
    if conversation_id not in IN_MEMORY_CONVERSATIONS[user_id]:
        IN_MEMORY_CONVERSATIONS[user_id][conversation_id] = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": title or "New Conversation",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "message_count": 0,
            "rating": None
        }
    
    return conversation_id

def save_message_to_db(conversation_id, user_message, bot_response, emotion, confidence, api_used):
    """Save individual message to database"""
    if is_mongodb_connected():
        try:
            message_doc = {
                "conversation_id": conversation_id,
                "user_message": user_message,
                "bot_response": bot_response,
                "emotion": emotion,
                "confidence": confidence,
                "api_used": api_used,
                "timestamp": datetime.utcnow()
            }
            
            result = messages_collection.insert_one(message_doc)
            
            conversations_collection.update_one(
                {"conversation_id": conversation_id},
                {
                    "$inc": {"message_count": 1},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            return str(result.inserted_id)
        except Exception as e:
            print(f"Error saving message to DB: {e}")
    
    # Fallback to in-memory storage
    if conversation_id not in IN_MEMORY_MESSAGES:
        IN_MEMORY_MESSAGES[conversation_id] = []
    
    message = {
        "message_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "user_message": user_message,
        "bot_response": bot_response,
        "emotion": emotion,
        "confidence": confidence,
        "api_used": api_used,
        "timestamp": datetime.utcnow()
    }
    
    IN_MEMORY_MESSAGES[conversation_id].append(message)
    
    for user_id, convs in IN_MEMORY_CONVERSATIONS.items():
        if conversation_id in convs:
            convs[conversation_id]["message_count"] += 1
            convs[conversation_id]["updated_at"] = datetime.utcnow()
            break
    
    return message["message_id"]

def get_conversation_messages(conversation_id, limit=100):
    """Retrieve all messages for a conversation"""
    if is_mongodb_connected():
        try:
            messages = list(messages_collection.find(
                {"conversation_id": conversation_id}
            ).sort("timestamp", pymongo.ASCENDING).limit(limit))
            
            for msg in messages:
                msg['_id'] = str(msg['_id'])
                if isinstance(msg['timestamp'], datetime):
                    msg['timestamp'] = msg['timestamp'].isoformat()
            
            return messages
        except Exception as e:
            print(f"Error retrieving messages: {e}")
    
    if conversation_id in IN_MEMORY_MESSAGES:
        messages = IN_MEMORY_MESSAGES[conversation_id][:limit]
        for msg in messages:
            if isinstance(msg['timestamp'], datetime):
                msg['timestamp'] = msg['timestamp'].isoformat()
        return messages
    
    return []

def get_user_conversations(user_id, limit=50):
    """Get all conversations for a user (includes rating)"""
    if is_mongodb_connected():
        try:
            conversations = list(conversations_collection.find(
                {"user_id": user_id}
            ).sort("updated_at", pymongo.DESCENDING).limit(limit))
            
            for conv in conversations:
                conv['_id'] = str(conv['_id'])
                if isinstance(conv['created_at'], datetime):
                    conv['created_at'] = conv['created_at'].isoformat()
                if isinstance(conv['updated_at'], datetime):
                    conv['updated_at'] = conv['updated_at'].isoformat()
                if 'rating' not in conv:
                    conv['rating'] = None
            
            return conversations
        except Exception as e:
            print(f"Error retrieving conversations: {e}")
    
    if user_id in IN_MEMORY_CONVERSATIONS:
        conversations = list(IN_MEMORY_CONVERSATIONS[user_id].values())
        conversations.sort(key=lambda x: x['updated_at'], reverse=True)
        return conversations[:limit]
    
    return []

def generate_response(user_input, emotion, confidence):
    """Main function to generate response using selected API"""
    
    # First check for crisis
    is_crisis, _ = check_safety(user_input)
    if is_crisis:
        return get_crisis_response()
    
    # Try to use selected API
    response = None
    
    if current_api == 'gemini' and GEMINI_API_KEY:
        response = generate_response_with_gemini(user_input, emotion, confidence)
    
    # Fallback to template if API fails
    if not response:
        print(f"⚠️ API {current_api} failed, using fallback response")
        response = generate_response_with_fallback(user_input, emotion, confidence)
    
    return response

# Load emotion model
print("\n" + "="*60)
print("EMOTION DETECTION & API-POWERED COUNSELING CHATBOT")
print("="*60)

emotion_loaded = load_emotion_model()

# Initialize MongoDB
mongodb_connected = init_mongodb()

print(f"\n🔑 Gemini API: {'✓ Configured' if GEMINI_API_KEY else '⚠️ Not configured'}")

print("\n" + "="*60)
print("SERVER STARTING...")
print("="*60)

# Routes - Updated to always serve chat page as default
@app.route('/')
def home():
    # Always serve chat.html - authentication handled by frontend modal
    return render_template('chat.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

# Guest login endpoint - creates a temporary user
@app.route('/api/guest-login', methods=['POST'])
def guest_login():
    """Create or retrieve a guest user session"""
    try:
        # Check if user already has a session (might be existing guest or registered)
        if 'user_id' in session:
            return jsonify({
                'success': True,
                'user_id': session['user_id'],
                'username': session.get('username', 'Guest'),
                'is_guest': session.get('is_guest', False)
            })
        
        # Generate unique guest ID
        guest_id = str(uuid.uuid4())
        guest_username = f"guest_{uuid.uuid4().hex[:8]}"
        guest_email = f"{guest_username}@guest.local"
        
        if is_mongodb_connected():
            # Check if guest with same ID exists (unlikely, but just in case)
            existing = users_collection.find_one({'user_id': guest_id})
            if existing:
                # If exists, use it
                session['user_id'] = existing['user_id']
                session['username'] = existing['username']
                session['is_guest'] = existing.get('is_guest', True)
                return jsonify({
                    'success': True,
                    'user_id': existing['user_id'],
                    'username': existing['username'],
                    'is_guest': True
                })
            
            # Create new guest user
            guest_user = {
                'user_id': guest_id,
                'username': guest_username,
                'email': guest_email,
                'password_hash': generate_password_hash(uuid.uuid4().hex),  # Random password
                'is_guest': True,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow()
            }
            guest_user['age'] = None
            guest_user['gender'] = None
            guest_user['profile_image'] = None
            users_collection.insert_one(guest_user)
        else:
            # In-memory fallback
            if guest_id in IN_MEMORY_USERS:
                session['user_id'] = guest_id
                session['username'] = IN_MEMORY_USERS[guest_id]['username']
                session['is_guest'] = True
                return jsonify({
                    'success': True,
                    'user_id': guest_id,
                    'username': IN_MEMORY_USERS[guest_id]['username'],
                    'is_guest': True
                })
            
            IN_MEMORY_USERS[guest_id] = {
                'user_id': guest_id,
                'username': guest_username,
                'email': guest_email,
                'password_hash': generate_password_hash(uuid.uuid4().hex),
                'is_guest': True,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow()
            }
        
        # Set session
        session['user_id'] = guest_id
        session['username'] = guest_username
        session['is_guest'] = True
        
        return jsonify({
            'success': True,
            'user_id': guest_id,
            'username': guest_username,
            'is_guest': True
        })
        
    except Exception as e:
        print(f"Guest login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        # Validation
        if not username or not email or not password:
            return jsonify({'error': 'All fields are required'}), 400
        
        if len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        user_id = str(uuid.uuid4())
        
        if is_mongodb_connected():
            # Check if user exists
            if users_collection.find_one({'$or': [{'username': username}, {'email': email}]}):
                return jsonify({'error': 'Username or email already exists'}), 400
            
            # Create user
            user_doc = {
                'user_id': user_id,
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password),
                'is_guest': False,
                'gender': 'Prefer not to say',
                'created_at': datetime.utcnow(),
                'last_login': None
            }
            
            user_doc['age'] = None
            user_doc['profile_image'] = None
            users_collection.insert_one(user_doc)
        else:
            # In-memory storage
            for existing_user in IN_MEMORY_USERS.values():
                if existing_user['username'] == username or existing_user['email'] == email:
                    return jsonify({'error': 'Username or email already exists'}), 400
            
            IN_MEMORY_USERS[user_id] = {
                'user_id': user_id,
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password),
                'is_guest': False,
                'gender': 'Prefer not to say',
                'created_at': datetime.utcnow(),
                'last_login': None
            }
        
        return jsonify({
            'success': True,
            'message': 'Registration successful! Please login.'
        })
        
    except Exception as e:
        print(f"Registration error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        user = None

        if is_mongodb_connected():
            user = users_collection.find_one({'email': email, 'is_guest': {'$ne': True}})
        else:
            for u in IN_MEMORY_USERS.values():
                if u['email'] == email and not u.get('is_guest', False):
                    user = u
                    break

        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'error': 'Invalid email or password'}), 401

        # Update last login
        if is_mongodb_connected():
            users_collection.update_one(
                {'user_id': user['user_id']},
                {'$set': {'last_login': datetime.utcnow()}}
            )
        else:
            user['last_login'] = datetime.utcnow()

        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session['is_guest'] = False

        return jsonify({
            'success': True,
            'user_id': user['user_id'],
            'username': user['username']
        })

    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_guest', None)
    #session.clear()
    return jsonify({'success': True})

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user_id': session['user_id'],
            'username': session['username'],
            'is_guest': session.get('is_guest', False)
        })
    return jsonify({'authenticated': False})

# ------------------- RATING SYSTEM ENDPOINTS -------------------
@app.route('/api/conversation/<conversation_id>/rating', methods=['GET'])
@login_required
def get_conversation_rating(conversation_id):
    """Get the rating (1-5) for a conversation, or null if not rated"""
    try:
        # Verify ownership
        conv = None
        if is_mongodb_connected():
            conv = conversations_collection.find_one({
                "conversation_id": conversation_id,
                "user_id": session['user_id']
            })
        else:
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                conv = IN_MEMORY_CONVERSATIONS[session['user_id']].get(conversation_id)
        
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        rating = conv.get('rating')
        return jsonify({'success': True, 'rating': rating})
    
    except Exception as e:
        print(f"Error getting rating: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversation/<conversation_id>/rating', methods=['POST'])
@login_required
def set_conversation_rating(conversation_id):
    """Set or update the rating (1-5) for a conversation"""
    try:
        data = request.json
        rating = data.get('rating')
        
        # Validate rating
        if rating is None or not isinstance(rating, int) or rating < 1 or rating > 5:
            return jsonify({'error': 'Rating must be an integer between 1 and 5'}), 400
        
        # Verify ownership and update
        if is_mongodb_connected():
            result = conversations_collection.update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": session['user_id']
                },
                {"$set": {"rating": rating, "updated_at": datetime.utcnow()}}
            )
            if result.matched_count == 0:
                return jsonify({'error': 'Conversation not found'}), 404
        else:
            # In-memory fallback
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                conv = IN_MEMORY_CONVERSATIONS[session['user_id']].get(conversation_id)
                if conv:
                    conv['rating'] = rating
                    conv['updated_at'] = datetime.utcnow()
                else:
                    return jsonify({'error': 'Conversation not found'}), 404
            else:
                return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({'success': True, 'rating': rating})
    
    except Exception as e:
        print(f"Error setting rating: {e}")
        return jsonify({'error': str(e)}), 500

# ---------- END RATING ENDPOINTS ----------

@app.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    """Get all conversations for current user"""
    try:
        conversations = get_user_conversations(session['user_id'])
        
        return jsonify({
            'success': True,
            'conversations': conversations
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversation/<conversation_id>', methods=['GET'])
@login_required
def get_conversation(conversation_id):
    """Get a specific conversation with all messages"""
    try:
        # Verify conversation belongs to user
        conv = None
        
        if is_mongodb_connected():
            conv = conversations_collection.find_one({
                "conversation_id": conversation_id,
                "user_id": session['user_id']
            })
        else:
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                conv = IN_MEMORY_CONVERSATIONS[session['user_id']].get(conversation_id)
        
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Get messages
        messages = get_conversation_messages(conversation_id)
        
        return jsonify({
            'success': True,
            'conversation': {
                'conversation_id': conversation_id,
                'title': conv.get('title', 'Conversation'),
                'created_at': conv['created_at'].isoformat() if isinstance(conv['created_at'], datetime) else conv['created_at'],
                'updated_at': conv['updated_at'].isoformat() if isinstance(conv['updated_at'], datetime) else conv['updated_at'],
                'message_count': conv.get('message_count', 0),
                'rating': conv.get('rating')
            },
            'messages': messages or []
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversation/<conversation_id>/update-title', methods=['POST'])
@login_required
def update_conversation_title(conversation_id):
    """Update conversation title"""
    try:
        data = request.json
        title = data.get('title', '')
        
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        
        if is_mongodb_connected():
            result = conversations_collection.update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": session['user_id']
                },
                {"$set": {"title": title, "updated_at": datetime.utcnow()}}
            )
        else:
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                if conversation_id in IN_MEMORY_CONVERSATIONS[session['user_id']]:
                    IN_MEMORY_CONVERSATIONS[session['user_id']][conversation_id]['title'] = title
                    IN_MEMORY_CONVERSATIONS[session['user_id']][conversation_id]['updated_at'] = datetime.utcnow()
                    result = type('obj', (object,), {'matched_count': 1})()
                else:
                    result = type('obj', (object,), {'matched_count': 0})()
            else:
                result = type('obj', (object,), {'matched_count': 0})()
        
        if result.matched_count == 0:
            return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/conversation/<conversation_id>/delete', methods=['DELETE'])
@login_required
def delete_conversation(conversation_id):
    """Delete a conversation and all its messages"""
    try:
        # Verify conversation belongs to user
        if is_mongodb_connected():
            conv = conversations_collection.find_one({
                "conversation_id": conversation_id,
                "user_id": session['user_id']
            })
        else:
            conv = None
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                conv = IN_MEMORY_CONVERSATIONS[session['user_id']].get(conversation_id)
        
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        if is_mongodb_connected():
            # Delete messages
            messages_collection.delete_many({"conversation_id": conversation_id})
            # Delete conversation record
            conversations_collection.delete_one({"conversation_id": conversation_id})
        else:
            # Delete from memory
            if conversation_id in IN_MEMORY_MESSAGES:
                del IN_MEMORY_MESSAGES[conversation_id]
            if session['user_id'] in IN_MEMORY_CONVERSATIONS:
                if conversation_id in IN_MEMORY_CONVERSATIONS[session['user_id']]:
                    del IN_MEMORY_CONVERSATIONS[session['user_id']][conversation_id]
        
        return jsonify({
            'success': True,
            'message': 'Conversation deleted successfully'
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    try:
        data = request.json
        user_message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id')
        
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400
        
        # Generate new conversation_id if not provided
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            # Get first few words as title
            title = user_message[:50] + ('...' if len(user_message) > 50 else '')
            save_conversation_to_db(session['user_id'], conversation_id, title)
        
        print(f"\n📝 User ({session['username']}): {user_message}")
        print(f"💬 Conversation ID: {conversation_id}")
        
        # Detect emotion
        emotion, confidence = detect_emotion(user_message)
        print(f"🎭 Detected emotion: {emotion.upper()} (confidence: {confidence:.2%})")
        
        # Generate response using API
        api_used = 'gemini' if GEMINI_API_KEY else 'fallback'
        response = generate_response(user_message, emotion, confidence)
        print(f"🤖 Response: {response[:150]}...")
        
        # Save to database
        saved_id = save_message_to_db(
            conversation_id=conversation_id,
            user_message=user_message,
            bot_response=response,
            emotion=emotion,
            confidence=confidence,
            api_used=api_used
        )
        
        if saved_id:
            print(f"💾 Message saved (ID: {saved_id})")
        
        return jsonify({
            'response': response,
            'emotion': emotion,
            'confidence': confidence,
            'api_used': api_used,
            'conversation_id': conversation_id,
            'saved': saved_id is not None
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    """Change user password (non-guest only)"""
    try:
        user_id = session['user_id']
        
        # Guest accounts cannot change password
        if session.get('is_guest', False):
            return jsonify({'error': 'Guest accounts cannot change password. Please sign up first.'}), 403
        
        data = request.json
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        
        if not old_password or not new_password:
            return jsonify({'error': 'Both old and new password are required'}), 400
        
        if len(new_password) < 6:
            return jsonify({'error': 'New password must be at least 6 characters'}), 400
        
        # Retrieve user
        user = None
        if is_mongodb_connected() and users_collection is not None:
            user = users_collection.find_one({'user_id': user_id})
        else:
            user = IN_MEMORY_USERS.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Verify old password
        if not check_password_hash(user['password_hash'], old_password):
            return jsonify({'error': 'Old password is incorrect'}), 401
        
        # Update password
        new_hash = generate_password_hash(new_password)
        if is_mongodb_connected() and users_collection is not None:
            users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'password_hash': new_hash, 'updated_at': datetime.utcnow()}}
            )
        else:
            IN_MEMORY_USERS[user_id]['password_hash'] = new_hash
        
        return jsonify({'success': True, 'message': 'Password changed successfully'})
        
    except Exception as e:
        print(f"Error changing password: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-api-status', methods=['GET'])
@login_required
def get_api_status():
    """Get current API status"""
    return jsonify({
        'current_api': 'gemini',
        'gemini_configured': bool(GEMINI_API_KEY),
        'emotion_model_loaded': emotion_loaded,
        'mongodb_connected': is_mongodb_connected()
    })

@app.route('/api/clear', methods=['POST'])
@login_required
def clear():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    return jsonify({'status': 'cleared'})


def init_admin_collection():
    global admins_collection
    if is_mongodb_connected():
        admins_collection = db['admins']
        # Create default admin if not exists
        if not admins_collection.find_one({'admin_id': 'admin001'}):
            default_admin = {
                'admin_id': 'admin001',
                'name': 'Super Admin',
                'email': 'admin@mentalhealth.com',
                'password_hash': generate_password_hash('admin123'),
                'created_at': datetime.utcnow()
            }
            admins_collection.insert_one(default_admin)
            print("✓ Default admin created (ID: admin001, Password: admin123)")

# Call this after MongoDB connection
init_admin_collection()

@app.route('/admin/login')
def admin_login_page():
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.json
        admin_id = data.get('admin_id', '').strip()
        password = data.get('password', '')
        
        if not admin_id or not password:
            return jsonify({'error': 'Admin ID and password required'}), 400
        
        admin = None
        if is_mongodb_connected() and admins_collection is not None:
            admin = admins_collection.find_one({
                '$or': [
                    {'admin_id': admin_id},
                    {'email': admin_id}
                ]
            })
        
        if not admin or not check_password_hash(admin['password_hash'], password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        session['admin_id'] = admin['admin_id']
        session['admin_name'] = admin['name']
        session['admin_email'] = admin['email']
        session['is_admin'] = True
        
        return jsonify({
            'success': True,
            'admin': {
                'admin_id': admin['admin_id'],
                'name': admin['name'],
                'email': admin['email']
            }
        })
        
    except Exception as e:
        print(f"Admin login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/check-auth', methods=['GET'])
def admin_check_auth():
    if session.get('is_admin') and session.get('admin_id'):
        return jsonify({
            'authenticated': True,
            'admin': {
                'admin_id': session['admin_id'],
                'name': session['admin_name'],
                'email': session['admin_email']
            }
        })
    return jsonify({'authenticated': False})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_name', None)
    session.pop('admin_email', None)
    session.pop('is_admin', None)
    return jsonify({'success': True})

# ============= ADMIN CONVERSATION ROUTES =============

@app.route('/api/admin/conversations', methods=['GET'])
def admin_get_all_conversations():
    """Get all conversations with user info for admin"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        all_conversations = []
        
        if is_mongodb_connected() and conversations_collection is not None:
            # Get all conversations with user details
            conversations_cursor = conversations_collection.find().sort("updated_at", pymongo.DESCENDING)
            
            for conv in conversations_cursor:
                # Get user info
                user = users_collection.find_one({'user_id': conv['user_id']})
                
                all_conversations.append({
                    'conversation_id': conv['conversation_id'],
                    'user_id': conv['user_id'],
                    'username': user['username'] if user else 'Unknown',
                    'title': conv.get('title', 'Conversation'),
                    'message_count': conv.get('message_count', 0),
                    'rating': conv.get('rating'),
                    'created_at': conv['created_at'].isoformat() if isinstance(conv.get('created_at'), datetime) else conv.get('created_at'),
                    'updated_at': conv['updated_at'].isoformat() if isinstance(conv.get('updated_at'), datetime) else conv.get('updated_at')
                })
        else:
            # In-memory fallback
            for user_id, convs in IN_MEMORY_CONVERSATIONS.items():
                user = IN_MEMORY_USERS.get(user_id, {})
                username = user.get('username', 'Unknown')
                for conv_id, conv in convs.items():
                    all_conversations.append({
                        'conversation_id': conv_id,
                        'user_id': user_id,
                        'username': username,
                        'title': conv.get('title', 'Conversation'),
                        'message_count': conv.get('message_count', 0),
                        'rating': conv.get('rating'),
                        'created_at': conv['created_at'].isoformat() if isinstance(conv.get('created_at'), datetime) else conv.get('created_at'),
                        'updated_at': conv['updated_at'].isoformat() if isinstance(conv.get('updated_at'), datetime) else conv.get('updated_at')
                    })
            
            # Sort by updated_at descending
            all_conversations.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        
        return jsonify({'success': True, 'conversations': all_conversations})
        
    except Exception as e:
        print(f"Error getting conversations: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/conversation/<conversation_id>', methods=['GET'])
def admin_get_conversation_details(conversation_id):
    """Get full conversation details with messages for admin"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        conversation = None
        messages = []
        
        if is_mongodb_connected() and conversations_collection is not None:
            conversation = conversations_collection.find_one({'conversation_id': conversation_id})
            
            if conversation:
                # Get user info
                user = users_collection.find_one({'user_id': conversation['user_id']})
                
                # Get messages
                messages_cursor = messages_collection.find({'conversation_id': conversation_id}).sort('timestamp', pymongo.ASCENDING)
                
                for msg in messages_cursor:
                    messages.append({
                        'sender': 'user',
                        'content': msg.get('user_message', ''),
                        'timestamp': msg['timestamp'].isoformat() if isinstance(msg.get('timestamp'), datetime) else msg.get('timestamp')
                    })
                    messages.append({
                        'sender': 'bot',
                        'content': msg.get('bot_response', ''),
                        'emotion': msg.get('emotion'),
                        'confidence': msg.get('confidence'),
                        'timestamp': msg['timestamp'].isoformat() if isinstance(msg.get('timestamp'), datetime) else msg.get('timestamp')
                    })
        else:
            # In-memory fallback
            for user_id, convs in IN_MEMORY_CONVERSATIONS.items():
                if conversation_id in convs:
                    conversation = convs[conversation_id]
                    user = IN_MEMORY_USERS.get(user_id, {})
                    break
            
            if conversation_id in IN_MEMORY_MESSAGES:
                for msg in IN_MEMORY_MESSAGES[conversation_id]:
                    messages.append({
                        'sender': 'user',
                        'content': msg.get('user_message', ''),
                        'timestamp': msg['timestamp'].isoformat() if isinstance(msg.get('timestamp'), datetime) else msg.get('timestamp')
                    })
                    messages.append({
                        'sender': 'bot',
                        'content': msg.get('bot_response', ''),
                        'emotion': msg.get('emotion'),
                        'confidence': msg.get('confidence'),
                        'timestamp': msg['timestamp'].isoformat() if isinstance(msg.get('timestamp'), datetime) else msg.get('timestamp')
                    })
        
        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({
            'success': True,
            'conversation': {
                'conversation_id': conversation_id,
                'user_id': conversation['user_id'],
                'username': user.get('username', 'Unknown') if 'user' in locals() else 'Unknown',
                'title': conversation.get('title', 'Conversation'),
                'message_count': conversation.get('message_count', 0),
                'rating': conversation.get('rating')
            },
            'messages': messages
        })
        
    except Exception as e:
        print(f"Error getting conversation details: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    """Get all users with conversation counts for admin (exclude guests or include based on need)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        users_list = []
        
        if is_mongodb_connected() and users_collection is not None:
            # Include all users including guests for admin visibility
            users_cursor = users_collection.find({}, {'password_hash': 0})
            
            for user in users_cursor:
                conv_count = conversations_collection.count_documents({'user_id': user['user_id']}) if conversations_collection is not None else 0
                
                users_list.append({
                    'user_id': user['user_id'],
                    'username': user['username'],
                    'email': user['email'],
                    'is_guest': user.get('is_guest', False),
                    'age': user.get('age'),
                    'gender': user.get('gender'),
                    'profile_image': user.get('profile_image'),
                    'created_at': user['created_at'].isoformat() if isinstance(user.get('created_at'), datetime) else user.get('created_at'),
                    'last_login': user['last_login'].isoformat() if isinstance(user.get('last_login'), datetime) else user.get('last_login'),
                    'conversation_count': conv_count
                })
        else:
            for user_id, user in IN_MEMORY_USERS.items():
                conv_count = len(IN_MEMORY_CONVERSATIONS.get(user_id, {}))
                users_list.append({
                    'user_id': user_id,
                    'username': user['username'],
                    'email': user['email'],
                    'is_guest': user.get('is_guest', False),
                    'age': user.get('age'),
                    'gender': user.get('gender'),
                    'profile_image': user.get('profile_image'),
                    'created_at': user['created_at'].isoformat() if isinstance(user.get('created_at'), datetime) else user.get('created_at'),
                    'last_login': user['last_login'].isoformat() if isinstance(user.get('last_login'), datetime) else user.get('last_login'),
                    'conversation_count': conv_count
                })
        
        return jsonify({'success': True, 'users': users_list})
        
    except Exception as e:
        print(f"Error getting users: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users', methods=['POST'])
def admin_create_user():
    """Create a new user (non-guest)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not username or not email or not password:
            return jsonify({'error': 'Username, email, and password required'}), 400
        
        user_id = str(uuid.uuid4())
        
        if is_mongodb_connected() and users_collection is not None:
            if users_collection.find_one({'$or': [{'username': username}, {'email': email}]}):
                return jsonify({'error': 'Username or email already exists'}), 400
            
            user_doc = {
                'user_id': user_id,
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password),
                'is_guest': False,
                'created_at': datetime.utcnow(),
                'last_login': None
            }
            users_collection.insert_one(user_doc)
        else:
            for existing in IN_MEMORY_USERS.values():
                if existing['username'] == username or existing['email'] == email:
                    return jsonify({'error': 'Username or email already exists'}), 400
            IN_MEMORY_USERS[user_id] = {
                'user_id': user_id,
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password),
                'is_guest': False,
                'created_at': datetime.utcnow(),
                'last_login': None
            }
        
        return jsonify({'success': True, 'user_id': user_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<user_id>', methods=['PUT'])
def admin_update_user(user_id):
    """Update user information (non-guest users only or allow updating guests?)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password')
        
        if not username or not email:
            return jsonify({'error': 'Username and email required'}), 400
        
        update_data = {
            'username': username,
            'email': email,
            'updated_at': datetime.utcnow()
        }
        
        if password:
            update_data['password_hash'] = generate_password_hash(password)
        
        if is_mongodb_connected() and users_collection is not None:
            # Check if username/email already taken by another user
            existing = users_collection.find_one({
                '$and': [
                    {'user_id': {'$ne': user_id}},
                    {'$or': [{'username': username}, {'email': email}]}
                ]
            })
            if existing:
                return jsonify({'error': 'Username or email already exists'}), 400
            
            result = users_collection.update_one({'user_id': user_id}, {'$set': update_data})
            if result.matched_count == 0:
                return jsonify({'error': 'User not found'}), 404
        else:
            if user_id in IN_MEMORY_USERS:
                # Check conflicts
                for uid, u in IN_MEMORY_USERS.items():
                    if uid != user_id and (u['username'] == username or u['email'] == email):
                        return jsonify({'error': 'Username or email already exists'}), 400
                IN_MEMORY_USERS[user_id].update(update_data)
            else:
                return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    """Delete a user and all associated data"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if is_mongodb_connected() and users_collection is not None and conversations_collection is not None and messages_collection is not None:
            # Get all conversation IDs for this user
            conversations = list(conversations_collection.find({'user_id': user_id}, {'conversation_id': 1}))
            
            # Delete all messages from user's conversations
            for conv in conversations:
                messages_collection.delete_many({'conversation_id': conv['conversation_id']})
            
            # Delete all conversations
            conversations_collection.delete_many({'user_id': user_id})
            
            # Delete the user
            result = users_collection.delete_one({'user_id': user_id})
            if result.deleted_count == 0:
                return jsonify({'error': 'User not found'}), 404
        else:
            # In-memory cleanup
            if user_id in IN_MEMORY_USERS:
                # Find and delete user's conversations
                convs_to_delete = []
                if user_id in IN_MEMORY_CONVERSATIONS:
                    convs_to_delete = list(IN_MEMORY_CONVERSATIONS[user_id].keys())
                    del IN_MEMORY_CONVERSATIONS[user_id]
                
                # Delete messages from those conversations
                for conv_id in convs_to_delete:
                    if conv_id in IN_MEMORY_MESSAGES:
                        del IN_MEMORY_MESSAGES[conv_id]
                
                # Delete user
                del IN_MEMORY_USERS[user_id]
            else:
                return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error deleting user: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)