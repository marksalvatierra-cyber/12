import firebase_admin
from firebase_admin import credentials, firestore, db, auth
import os

# Initialize Firebase
def initialize_firebase():
    cred_path = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')
    database_url = os.environ.get('FIREBASE_DATABASE_URL', 'https://rizalert-ca105-default-rtdb.asia-southeast1.firebasedatabase.app/')
    
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(cred_path)
            
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
            print(f"Please ensure your Firebase credentials file is at: {cred_path}")
    
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
