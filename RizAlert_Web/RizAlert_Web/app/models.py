from werkzeug.security import generate_password_hash, check_password_hash
from enum import Enum
from datetime import datetime
from app.firebase_config import get_db, get_auth

class CaseType(Enum):
    TYPHOON = "Typhoon"
    FIRE = "Fire"
    CRIME = "Crime"
    FLOOD = "Flood"
    MEDICAL = "Medical"
    DISASTER = "Disaster"

class EmergencyStatus(Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    UNDER_INVESTIGATION = "Under Investigation"
    MONITORING = "Monitoring"
    RESOLVED = "Resolved"

class UserRole(Enum):
    CITIZEN = "citizen"
    ADMIN = "admin"
    RESPONDER = "responder"

class UserStatus(Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"

# Helper class to make enum values accessible like objects
class EnumValue:
    """Wrapper to make enum values accessible with .value attribute for template compatibility"""
    def __init__(self, enum_class, enum_name):
        if enum_name and hasattr(enum_class, enum_name):
            self.enum_obj = enum_class[enum_name]
            self.value = self.enum_obj.value
            self.name = enum_name
        else:
            self.value = enum_name if enum_name else "Unknown"
            self.name = enum_name
    
    def __str__(self):
        return self.value
    
    def __repr__(self):
        return f"EnumValue({self.value})"

class FirestoreModel:
    """Base class for Firestore models"""
    collection_name = None
    
    @classmethod
    def get_collection(cls):
        """Get Firestore collection reference"""
        db = get_db()
        return db.collection(cls.collection_name)
    
    @classmethod
    def get_by_id(cls, doc_id):
        """Get document by ID"""
        doc = cls.get_collection().document(doc_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    
    @classmethod
    def get_all(cls):
        """Get all documents in collection"""
        docs = cls.get_collection().stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    
    @classmethod
    def create(cls, data, doc_id=None):
        """Create a new document with optional custom document ID"""
        if doc_id:
            doc_ref = cls.get_collection().document(doc_id)
            doc_ref.set(data)
            return doc_id
        else:
            doc_ref = cls.get_collection().document()
            doc_ref.set(data)
            return doc_ref.id
    
    @classmethod
    def update(cls, doc_id, data):
        """Update a document"""
        cls.get_collection().document(doc_id).update(data)
    
    @classmethod
    def delete(cls, doc_id):
        """Delete a document"""
        cls.get_collection().document(doc_id).delete()

class User(FirestoreModel):
    collection_name = 'users'
    
    @staticmethod
    def set_password(password):
        """Hash a password"""
        return generate_password_hash(password)
    
    @staticmethod
    def check_password(password_hash, password):
        """Check a password against a hash"""
        return check_password_hash(password_hash, password)
    
    @classmethod
    def create_user(cls, username, email, fullName, password, address=None, role='admin', department=None, status='ACTIVE', profile_image=None, municipality='Rizal', barangay=None):
        """Create a new user with Firebase Authentication and Firestore record"""
        try:
            # Step 1: Create Firebase Authentication user
            auth_module = get_auth()
            
            # Create auth user with email and password
            auth_user = auth_module.create_user(
                email=email,
                password=password,
                display_name=fullName,
                photo_url=profile_image if profile_image else None
            )
            
            # Get the Firebase Auth UID
            user_id = auth_user.uid
            
            # Step 2: Create Firestore document with the same UID
            data = {
                'username': username,
                'email': email,
                'fullName': fullName,
                'password_hash': cls.set_password(password),  # Store hashed password as backup
                'address': address,
                'role': role,
                'department': department,
                'status': status,
                'municipality': municipality,
                'barangay': barangay,
                'last_active': None,
                'profile_image': profile_image
            }
            
            # Use the Firebase Auth UID as the document ID
            cls.create(data, doc_id=user_id)
            
            print(f"✅ Created Firebase Auth user and Firestore document with ID: {user_id}")
            return user_id
            
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            # If Firestore creation fails but auth user was created, delete the auth user
            if 'user_id' in locals():
                try:
                    auth_module.delete_user(user_id)
                    print(f"Rolled back: Deleted Firebase Auth user {user_id}")
                except:
                    pass
            raise e
    
    @classmethod
    def get_by_username(cls, username):
        """Get user by username"""
        docs = cls.get_collection().where('username', '==', username).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    
    @classmethod
    def get_by_email(cls, email):
        """Get user by email"""
        docs = cls.get_collection().where('email', '==', email).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    
    @classmethod
    def delete_user(cls, user_id):
        """Delete user from both Firebase Auth and Firestore"""
        try:
            # Delete from Firebase Authentication
            auth_module = get_auth()
            try:
                auth_module.delete_user(user_id)
                print(f"✅ Deleted Firebase Auth user: {user_id}")
            except Exception as auth_error:
                print(f"⚠️ Could not delete Firebase Auth user: {auth_error}")
            
            # Delete from Firestore
            cls.delete(user_id)
            print(f"✅ Deleted Firestore document: {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error deleting user: {e}")
            raise e

class Emergency(FirestoreModel):
    collection_name = 'emergency'
    
    @classmethod
    def create_emergency(cls, case_type, user_id, message=None, latitude=None, longitude=None, file_id=None, isActive=True, status='PENDING', location_text=None, responders=None):
        """Create a new emergency"""
        data = {
            'case_type': case_type,
            'user_id': user_id,
            'message': message,
            'created_at': datetime.utcnow(),
            'isActive': isActive,
            'status': status,
            'latitude': latitude,
            'longitude': longitude,
            'file_id': file_id,
            'location_text': location_text,
            'responders': responders if responders else []
        }
        return cls.create(data)
    
    @classmethod
    def get_active_emergencies(cls):
        """Get all active emergencies"""
        docs = cls.get_collection().where('isActive', '==', True).stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    
    @classmethod
    def get_recent(cls, limit=10):
        """Get recent emergencies ordered by created_at"""
        docs = cls.get_collection().order_by('created_at', direction='DESCENDING').limit(limit).stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    
    @classmethod
    def get_by_case_type(cls, case_type):
        """Get emergencies by case type"""
        docs = cls.get_collection().where('case_type', '==', case_type).stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    
    @classmethod
    def count_by_status(cls, status):
        """Count emergencies by status"""
        docs = cls.get_collection().where('status', '==', status).stream()
        return len(list(docs))
    
    @classmethod
    def add_responder(cls, emergency_id, responder_data):
        """Add a responder to the emergency
        responder_data should contain: responder_id, response_datetime, status, isArrived
        """
        emergency = cls.get_by_id(emergency_id)
        if not emergency:
            return None
        
        responders = emergency.get('responders', [])
        responders.append(responder_data)
        
        cls.update(emergency_id, {'responders': responders})
        return True
    
    @classmethod
    def update_responder_status(cls, emergency_id, responder_id, status=None, isArrived=None):
        """Update a specific responder's status or arrival state"""
        emergency = cls.get_by_id(emergency_id)
        if not emergency:
            return None
        
        responders = emergency.get('responders', [])
        
        for responder in responders:
            if responder.get('responder_id') == responder_id:
                if status is not None:
                    responder['status'] = status
                if isArrived is not None:
                    responder['isArrived'] = isArrived
                break
        
        cls.update(emergency_id, {'responders': responders})
        return True

class EmergencyAlert(FirestoreModel):
    collection_name = 'emergency_alerts'
    
    @classmethod
    def create_alert(cls, emergency_type, emergency_descriptions):
        """Create a new emergency alert"""
        data = {
            'date_created': datetime.utcnow(),
            'emergency_type': emergency_type,
            'emergency_descriptions': emergency_descriptions,
            'people_safe': [],
            'people_danger': [],
            'people_evacuating': []
        }
        return cls.create(data)
    
    @classmethod
    def add_person_to_list(cls, alert_id, list_name, person_data):
        """Add a person to one of the lists (people_safe, people_danger, people_evacuating)"""
        alert = cls.get_by_id(alert_id)
        if not alert:
            return None
        
        if list_name not in ['people_safe', 'people_danger', 'people_evacuating']:
            raise ValueError(f"Invalid list_name: {list_name}")
        
        current_list = alert.get(list_name, [])
        current_list.append(person_data)
        
        cls.update(alert_id, {list_name: current_list})
        return True
    
    @classmethod
    def remove_person_from_list(cls, alert_id, list_name, person_identifier):
        """Remove a person from one of the lists by identifier"""
        alert = cls.get_by_id(alert_id)
        if not alert:
            return None
        
        if list_name not in ['people_safe', 'people_danger', 'people_evacuating']:
            raise ValueError(f"Invalid list_name: {list_name}")
        
        current_list = alert.get(list_name, [])
        # Filter out the person (assuming person_data has an 'id' or unique identifier)
        updated_list = [p for p in current_list if p.get('id') != person_identifier]
        
        cls.update(alert_id, {list_name: updated_list})
        return True
    
    @classmethod
    def get_by_emergency_type(cls, emergency_type):
        """Get alerts by emergency type"""
        docs = cls.get_collection().where('emergency_type', '==', emergency_type).stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    
    @classmethod
    def get_recent_alerts(cls, limit=10):
        """Get recent alerts ordered by date_created"""
        docs = cls.get_collection().order_by('date_created', direction='DESCENDING').limit(limit).stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
