import firebase_admin
from firebase_admin import credentials, firestore, db, auth
import os
import json
import base64


# Initialize Firebase
def initialize_firebase():
    """
    Initialize Firebase using credentials provided either as:
    - a filesystem path to the service account JSON file (default),
    - the raw JSON content of the service account, or
    - a base64-encoded JSON string.

    The environment variable `FIREBASE_CREDENTIALS` may contain any of the above.
    """
    cred_source = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')
    database_url = os.environ.get('FIREBASE_DATABASE_URL', 'https://rizalert-ca105-default-rtdb.asia-southeast1.firebasedatabase.app/')

    if not firebase_admin._apps:
        try:
            cred = None

            # Case 1: FIREBASE_CREDENTIALS contains raw JSON
            if isinstance(cred_source, str) and cred_source.strip().startswith('{'):
                try:
                    cred_dict = json.loads(cred_source)
                    cred = credentials.Certificate(cred_dict)
                except Exception:
                    raise

            # Case 2: FIREBASE_CREDENTIALS is a path to a file
            if cred is None:
                # If the string looks like a valid path on disk, use it
                if os.path.exists(cred_source):
                    cred = credentials.Certificate(cred_source)
                else:
                    # Case 3: maybe base64-encoded JSON
                    try:
                        decoded = base64.b64decode(cred_source).decode('utf-8')
                        cred_dict = json.loads(decoded)
                        cred = credentials.Certificate(cred_dict)
                    except Exception:
                        # Fall back to raising a clearer error
                        raise FileNotFoundError(f"Credentials not found as file and not valid JSON/base64 data: {cred_source[:100]}...")

            # Initialize with database URL if provided
            if database_url:
                firebase_admin.initialize_app(cred, {
                    'databaseURL': database_url
                })
                print("Firebase initialized successfully with Firestore and Realtime Database")
            else:
                firebase_admin.initialize_app(cred)
                print("Firebase initialized successfully with Firestore only")
                print("Note: Set FIREBASE_DATABASE_URL to enable Realtime Database")
        except Exception as e:
            print(f"Error initializing Firebase: {e}")
            print("Please ensure your Firebase credentials are provided either as a file path, raw JSON, or base64-encoded JSON in the FIREBASE_CREDENTIALS environment variable.")

    return firestore.client()

# Get Firestore client
def get_db():
    """Get Firestore database client"""
    return firestore.client()

# Get Realtime Database reference
def get_realtime_db():
    """
    Get Firebase Realtime Database reference
    Returns the root reference to the Realtime Database
    
    Usage:
        ref = get_realtime_db()
        users_ref = ref.child('users')
        users_ref.set({'user1': {'name': 'John'}})
    
    Note: Requires FIREBASE_DATABASE_URL to be set in environment
    """
    try:
        return db.reference()
    except Exception as e:
        print(f"Error getting Realtime Database reference: {e}")
        print("Make sure FIREBASE_DATABASE_URL is set in your environment")
        return None

# Get Firebase Auth
def get_auth():
    """
    Get Firebase Authentication module
    
    Usage:
        auth_module = get_auth()
        user = auth_module.create_user(email='user@example.com', password='password')
    """
    return auth
