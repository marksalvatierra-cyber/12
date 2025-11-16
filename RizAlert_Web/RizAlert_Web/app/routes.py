from flask import Blueprint, render_template, request, jsonify, send_file, make_response, session, redirect, url_for, current_app
from app.models import User, Emergency, EmergencyAlert, CaseType, EmergencyStatus
from app.firebase_config import get_realtime_db, get_db
from datetime import datetime, timedelta
import csv
import io
import os
import pyotp
import qrcode
from io import BytesIO
import base64
import firebase_admin
from firebase_admin import auth, firestore
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

main = Blueprint('main', __name__)
api = Blueprint('api', __name__)

@main.route('/weather')
def weather():
    """
    Render the weather map page.
    Uses active emergencies (falls back to filtering all emergencies) and current user for navbar.
    """
    try:
        # Prefer a helper that returns active emergencies if available
        try:
            all_emergencies = Emergency.get_active_emergencies()
        except Exception:
            # Fallback: filter all emergencies for active ones
            all_emergencies = [e for e in Emergency.get_all() if e.get('isActive')]
        
        all_users = User.get_all()
        user_lookup = {u['id']: u for u in all_users}
        
        emergencies = []
        for emergency in all_emergencies:
            user = user_lookup.get(emergency.get('user_id'))
            if emergency.get('case_type') and user:
                emergency = enrich_emergency_data(emergency)
                emergency['user'] = user
                emergencies.append(emergency)
        
        current_user = get_current_user()
        return render_template('weather.html', emergencies=emergencies, current_user=current_user)
    except Exception as e:
        print(f"Error loading weather page: {e}")
        # Render template with safe defaults on error
        return render_template('weather.html', emergencies=[], current_user=get_current_user())


# Helper function to get current user data
def get_current_user():
    """Get current logged-in user's data for navbar"""
    if not session.get('logged_in') or not session.get('user_id'):
        return None
    
    try:
        db = get_db()
        user_id = session.get('user_id')
        
        # Fetch user from Firestore
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return None
        
        user_data = user_doc.to_dict()
        
        # Return essential user data for navbar
        return {
            'id': user_id,
            'fullName': user_data.get('fullName', 'Admin User'),
            'username': user_data.get('username', 'admin'),
            'email': user_data.get('email', ''),
            'role': user_data.get('role', 'admin'),
            'profile_picture': user_data.get('profile_picture', 'https://api.dicebear.com/7.x/avataaars/svg?seed=admin')
        }
    except Exception as e:
        print(f"Error getting current user: {e}")
        return None

# Helper class to make enum values accessible in templates
class EnumValue:
    def __init__(self, value):
        self._value = value
    
    @property
    def value(self):
        """Return the display value of the enum"""
        try:
            # Try to get the enum value
            if hasattr(CaseType, self._value):
                return CaseType[self._value].value
            elif hasattr(EmergencyStatus, self._value):
                return EmergencyStatus[self._value].value
            return self._value
        except:
            return self._value
    
    def __eq__(self, other):
        return self.value == other
    
    def __str__(self):
        return self.value

def enrich_emergency_data(emergency):
    """Add EnumValue wrapper to status and case_type for template compatibility"""
    if emergency and 'status' in emergency:
        emergency['status'] = EnumValue(emergency['status'])
    if emergency and 'case_type' in emergency:
        emergency['case_type'] = EnumValue(emergency['case_type'])
    return emergency

@main.route('/')
def index():
    # Read from Firebase Realtime Database
    try:
        realtime_db = get_realtime_db()
        if realtime_db:
            print("\n" + "="*70)
            print("FIREBASE REALTIME DATABASE - EMERGENCY DATA")
            print("="*70)
            
            # Read emergencies from Realtime Database
            emergencies_ref = realtime_db.child('emergencies')
            realtime_emergencies = emergencies_ref.get()
            
            if realtime_emergencies:
                print(f"✅ Found {len(realtime_emergencies)} emergencies in Realtime Database")
                print(f"Emergency data: {realtime_emergencies}")
            else:
                print("ℹ️  No emergencies found in Realtime Database")
            
            print("="*70 + "\n")
        else:
            print("ℹ️  Realtime Database not configured (FIREBASE_DATABASE_URL not set)")
    except Exception as e:
        print(f"⚠️  Error reading from Realtime Database: {e}")
    
    # Get all data
    all_emergencies = Emergency.get_all()
    all_users = User.get_all()
    all_alerts = EmergencyAlert.get_all()
    
    alerts = []
    
    for emergency in all_emergencies:
        if emergency.get('isActive') and emergency.get('case_type'):
            emergency = enrich_emergency_data(emergency)
            alerts.append(emergency)
    
    # Sort by created_at and limit to 3
    alerts = sorted(alerts, key=lambda x: x.get('created_at', datetime.min), reverse=True)[:3]
    
    print(f"\n✅ Active Alerts: {len(alerts)}")
    for alert in alerts:
        print(f"  Alert Case Type: {alert.get('case_type')}, Status: {alert.get('status')}")

    # Query for Statistics Cards
    one_month_ago = datetime.utcnow() - timedelta(days=30)
    
    # Get all emergencies for statistics
    all_emergencies = Emergency.get_all()
    print("Total Emergencies:", len(all_emergencies))
    
    # Medical Emergency Resolved Rate
    medical_cases = 0
    medical_resolved = 0
    for emergency in all_emergencies:
        created_at = emergency.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        # Handle both datetime objects and skip if None
        if created_at and isinstance(created_at, datetime):
            # Make created_at timezone-naive if it's timezone-aware
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
        if created_at and created_at >= one_month_ago:
            if emergency.get('case_type') == CaseType.MEDICAL.name:
                medical_cases += 1
                if emergency.get('status') == EmergencyStatus.RESOLVED.name:
                    medical_resolved += 1
    
    medical_resolved_rate = (medical_resolved / medical_cases * 100) if medical_cases > 0 else 0

    # Fire Cases Resolved Rate
    fire_cases = 0
    fire_resolved = 0
    for emergency in all_emergencies:
        created_at = emergency.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        # Handle both datetime objects and skip if None
        if created_at and isinstance(created_at, datetime):
            # Make created_at timezone-naive if it's timezone-aware
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
        if created_at and created_at >= one_month_ago:
            if emergency.get('case_type') == CaseType.FIRE.name:
                fire_cases += 1
                if emergency.get('status') == EmergencyStatus.RESOLVED.name:
                    fire_resolved += 1
    
    fire_resolved_rate = (fire_resolved / fire_cases * 100) if fire_cases > 0 else 0

    # Disaster Cases Resolved Rate (Typhoon, Flood, and Disaster types)
    disaster_cases = 0
    disaster_resolved = 0
    for emergency in all_emergencies:
        created_at = emergency.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        # Handle both datetime objects and skip if None
        if created_at and isinstance(created_at, datetime):
            # Make created_at timezone-naive if it's timezone-aware
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
        if created_at and created_at >= one_month_ago:
            # Include all disaster-related case types
            case_type = emergency.get('case_type')
            if case_type in [CaseType.TYPHOON.name, CaseType.FLOOD.name, CaseType.DISASTER.name]:
                disaster_cases += 1
                if emergency.get('status') == EmergencyStatus.RESOLVED.name:
                    disaster_resolved += 1
                # Debug output
                print(f"Disaster case found: {case_type}, Status: {emergency.get('status')}, Date: {created_at}")
    
    disaster_resolved_rate = (disaster_resolved / disaster_cases * 100) if disaster_cases > 0 else 0
    print(f"Disaster stats: {disaster_resolved} resolved out of {disaster_cases} total = {disaster_resolved_rate}% resolved rate")

    # Crime Cases Resolved Rate
    crime_cases = 0
    crime_resolved = 0
    for emergency in all_emergencies:
        created_at = emergency.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        # Handle both datetime objects and skip if None
        if created_at and isinstance(created_at, datetime):
            # Make created_at timezone-naive if it's timezone-aware
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
        if created_at and created_at >= one_month_ago:
            if emergency.get('case_type') == CaseType.CRIME.name:
                crime_cases += 1
                if emergency.get('status') == EmergencyStatus.RESOLVED.name:
                    crime_resolved += 1
    
    crime_resolved_rate = (crime_resolved / crime_cases * 100) if crime_cases > 0 else 0
    print(f"Crime stats: {crime_resolved} resolved out of {crime_cases} total = {crime_resolved_rate}% resolved rate")

    # Calculate yearly incident statistics for chart
    current_year = datetime.utcnow().year
    yearly_stats = {
        'Fire': 0,
        'Crime': 0,
        'Medical': 0,
        'Disaster': 0
    }
    
    print(f"\n📈 Calculating yearly stats for {current_year}...")
    for emergency in all_emergencies:
        created_at = emergency.get('created_at')
        
        # Handle different datetime formats
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    created_at = None
            
            # If it's already a datetime object
            if created_at and isinstance(created_at, datetime):
                # Make created_at timezone-naive if it's timezone-aware
                if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
                
                # Count all emergencies from current year
                if created_at.year == current_year:
                    case_type_name = emergency.get('case_type')  # This should be raw string like 'FIRE'
                    print(f"  Found case_type: '{case_type_name}' from year {created_at.year}")
                    # Convert enum name to display value
                    if case_type_name == 'TYPHOON':
                        yearly_stats['Typhoon'] += 1
                    elif case_type_name == 'FIRE':
                        yearly_stats['Fire'] += 1
                    elif case_type_name == 'CRIME':
                        yearly_stats['Crime'] += 1
                    elif case_type_name == 'FLOOD':
                        yearly_stats['Flood'] += 1
                    elif case_type_name == 'DISASTER':
                        yearly_stats['Disaster'] += 1
                    elif case_type_name == 'MEDICAL':
                        yearly_stats['Medical'] += 1
                        print(f"  ✅ Medical case counted!")
    
    print(f"📊 Yearly Stats: {yearly_stats}\n")

    # Get recent cases with users
    recent_cases = Emergency.get_recent(limit=6)
    all_users = User.get_all()
    user_lookup = {user['id']: user for user in all_users}
    
    recent_cases_with_time = []
    for emergency in recent_cases:
        user = user_lookup.get(emergency.get('user_id'))
        if emergency.get('case_type') and user:
            emergency = enrich_emergency_data(emergency)
            emergency['user'] = user
            created_at = emergency.get('created_at')
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            # Handle both datetime objects and skip if None
            if created_at and isinstance(created_at, datetime):
                # Make created_at timezone-naive if it's timezone-aware
                if created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
            time_diff = (datetime.utcnow() - created_at).total_seconds() if created_at else 0
            recent_cases_with_time.append({
                'emergency': emergency,
                'time_diff': time_diff
            })

    # Get current user for navbar
    current_user = get_current_user()

    return render_template(
        'index.html',
        users=all_users,
        alerts=alerts,
        medical_resolved_rate=round(medical_resolved_rate, 1),
        fire_resolved_rate=round(fire_resolved_rate, 1),
        disaster_resolved_rate=round(disaster_resolved_rate, 1),
        crime_resolved_rate=round(crime_resolved_rate, 1),
        recent_cases=recent_cases_with_time,
        yearly_stats=yearly_stats,
        current_year=current_year,
        current_user=current_user
    )

@main.route('/users')
def users():
    # Query all users for the user management page
    users = User.get_all()
    # Get current user for navbar
    current_user = get_current_user()
    return render_template(
        'users.html',
        users=users,
        current_user=current_user
    )

@main.route('/sirens')
def siren():
    try:
        db = get_realtime_db()
        if db:
            # Get current siren statuses
            typhoon_status = db.child('emergency_siren_typhoon').get() or False
            flood_status = db.child('emergency_siren_flood').get() or False
            earthquake_status = db.child('emergency_siren_earthquake').get() or False
        else:
            typhoon_status = False
            flood_status = False
            earthquake_status = False
    except Exception as e:
        print(f"Error fetching siren status: {e}")
        typhoon_status = False
        flood_status = False
        earthquake_status = False
    
    # Get siren activation and deactivation logs from Firestore
    activation_logs = []
    deactivation_logs = []
    
    try:
        firestore_db = get_db()
        
        # Get activation logs (last 20, ordered by timestamp desc)
        activations_ref = firestore_db.collection('siren_activations').order_by('timestamp', direction='DESCENDING').limit(20)
        activations_docs = activations_ref.stream()
        
        for doc in activations_docs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id
            # Convert timestamp to datetime if it exists
            if 'timestamp' in log_data and log_data['timestamp']:
                log_data['timestamp_str'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                log_data['timestamp_str'] = 'N/A'
            activation_logs.append(log_data)
        
        # Get deactivation logs (last 20, ordered by timestamp desc)
        deactivations_ref = firestore_db.collection('siren_deactivations').order_by('timestamp', direction='DESCENDING').limit(20)
        deactivations_docs = deactivations_ref.stream()
        
        for doc in deactivations_docs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id
            # Convert timestamp to datetime if it exists
            if 'timestamp' in log_data and log_data['timestamp']:
                log_data['timestamp_str'] = log_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                log_data['timestamp_str'] = 'N/A'
            deactivation_logs.append(log_data)
            
    except Exception as e:
        print(f"Error fetching siren logs: {e}")
    
    # Get current user for navbar
    current_user = get_current_user()
    
    return render_template(
        'iot-siren.html',
        typhoon_status=typhoon_status,
        flood_status=flood_status,
        earthquake_status=earthquake_status,
        activation_logs=activation_logs,
        deactivation_logs=deactivation_logs,
        current_user=current_user
    )

@main.route('/admin/profile')
def admin_profile():
    # Check if user is logged in
    if not session.get('logged_in') or not session.get('user_id'):
        return redirect(url_for('main.admin_login'))
    
    try:
        db = get_db()
        user_id = session.get('user_id')
        
        # Fetch user from Firestore
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return redirect(url_for('main.admin_login'))
        
        user_data = user_doc.to_dict()
        
        # Verify user is admin
        if user_data.get('role') != 'admin':
            return redirect(url_for('main.admin_login'))
        
        admin = {
            'id': user_id,
            'fullName': user_data.get('fullName', 'Admin User'),
            'username': user_data.get('username', 'admin'),
            'email': user_data.get('email', ''),
            'phone': user_data.get('phone', ''),
            'emergencyPhone': user_data.get('emergencyPhone', ''),
            'emergencyName': user_data.get('emergencyName', ''),
            'role': user_data.get('role', 'admin'),
            'department': user_data.get('department', 'Emergency Management'),
            'address': user_data.get('address', ''),
            'joined_date': user_data.get('createdAt', datetime.now().strftime('%Y-%m-%d')),
            'last_login': session.get('last_login', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            'two_factor_enabled': user_data.get('two_factor_enabled', False),
            'profile_picture': user_data.get('profile_picture', 'https://api.dicebear.com/7.x/avataaars/svg?seed=admin')
        }
        
        return render_template('admin-profile.html', admin=admin)
    except Exception as e:
        print(f"Error loading admin profile: {e}")
        return redirect(url_for('main.admin_login'))

@main.route('/admin/profile/update', methods=['POST'])
def update_admin_profile():
    if not session.get('logged_in') or not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        data = request.json
        profile_type = data.get('type')  # 'personal', 'contact', or 'account'
        
        print(f"DEBUG: Received profile update request - Type: {profile_type}, Data: {data}")
        
        db = get_db()
        user_id = session.get('user_id')
        user_ref = db.collection('users').document(user_id)
        
        # Verify user exists
        user_doc = user_ref.get()
        if not user_doc.exists:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404
        
        # Update based on profile type
        if profile_type == 'personal':
            # Validate required fields
            full_name = data.get('fullName', '').strip()
            if not full_name:
                return jsonify({
                    'success': False,
                    'error': 'Full name is required'
                }), 400
            
            update_data = {
                'fullName': full_name,
                'department': data.get('department', '').strip(),
                'address': data.get('address', '').strip(),
                'updatedAt': firestore.SERVER_TIMESTAMP
            }
            
        elif profile_type == 'contact':
            # Validate required fields
            email = data.get('email', '').strip()
            if not email:
                return jsonify({
                    'success': False,
                    'error': 'Email is required'
                }), 400
            
            # Basic email validation
            import re
            email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
            if not re.match(email_pattern, email):
                return jsonify({
                    'success': False,
                    'error': 'Please enter a valid email address'
                }), 400
            
            update_data = {
                'email': email,
                'phone': data.get('phone', '').strip(),
                'emergencyPhone': data.get('emergencyPhone', '').strip(),
                'emergencyName': data.get('emergencyName', '').strip(),
                'updatedAt': firestore.SERVER_TIMESTAMP
            }
            
            # Also update Firebase Auth email if different
            try:
                current_user = auth.get_user(user_id)
                if current_user.email != email:
                    auth.update_user(user_id, email=email)
            except Exception as auth_error:
                print(f"Warning: Could not update Firebase Auth email: {auth_error}")
                # Continue with Firestore update even if Auth update fails
            
        elif profile_type == 'account':
            current_password = data.get('currentPassword', '').strip()
            new_password = data.get('newPassword', '').strip()
            
            if not current_password or not new_password:
                return jsonify({
                    'success': False,
                    'error': 'Both current and new passwords are required'
                }), 400
            
            if len(new_password) < 6:
                return jsonify({
                    'success': False,
                    'error': 'New password must be at least 6 characters long'
                }), 400
            
            # Update password in Firebase Auth
            try:
                auth.update_user(user_id, password=new_password)
                
                # Update password change timestamp in Firestore
                user_ref.update({
                    'passwordChangedAt': firestore.SERVER_TIMESTAMP,
                    'updatedAt': firestore.SERVER_TIMESTAMP
                })
                
                return jsonify({
                    'success': True,
                    'message': 'Password updated successfully'
                })
            except Exception as auth_error:
                return jsonify({
                    'success': False,
                    'error': f'Failed to update password: {str(auth_error)}'
                }), 500
                
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid profile type'
            }), 400
        
        # Update Firestore (for personal and contact types)
        if profile_type in ['personal', 'contact']:
            print(f"DEBUG: Updating Firestore with data: {update_data}")
            user_ref.update(update_data)
            print(f"DEBUG: Firestore update completed successfully")
        
        print(f"DEBUG: Profile update successful - Type: {profile_type}")
        return jsonify({
            'success': True,
            'message': f'{profile_type.capitalize()} information updated successfully'
        })
        
    except Exception as e:
        print(f"Error updating admin profile: {e}")
        return jsonify({
            'success': False,
            'error': f'An error occurred while updating profile: {str(e)}'
        }), 500

@main.route('/admin/profile/upload-picture', methods=['POST'])
def upload_profile_picture():
    if not session.get('logged_in') or not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        # Check if file is present
        if 'profile_picture' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['profile_picture']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            return jsonify({'success': False, 'error': 'Invalid file type. Please use PNG, JPG, JPEG, GIF, or WebP'}), 400
        
        # Create uploads directory if it doesn't exist
        import os
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generate unique filename
        import uuid
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{session.get('user_id')}_{uuid.uuid4().hex[:8]}.{file_extension}"
        file_path = os.path.join(upload_dir, unique_filename)
        
        # Save the file
        file.save(file_path)
        
        # Generate URL for the uploaded file
        picture_url = f"/static/uploads/profiles/{unique_filename}"
        
        # Update user profile in Firestore
        db = get_db()
        user_id = session.get('user_id')
        user_ref = db.collection('users').document(user_id)
        
        user_ref.update({
            'profile_picture': picture_url,
            'updatedAt': firestore.SERVER_TIMESTAMP
        })
        
        return jsonify({
            'success': True,
            'message': 'Profile picture updated successfully',
            'picture_url': picture_url
        })
        
    except Exception as e:
        print(f"Error uploading profile picture: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to upload profile picture: {str(e)}'
        }), 500

@main.route('/admin/2fa/setup')
def setup_2fa():
    if not session.get('logged_in') or not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    # Generate a secret key for 2FA
    secret = pyotp.random_base32()
    session['temp_2fa_secret'] = secret
    
    # Get user email for QR code
    user_id = session.get('user_id')
    try:
        db = get_db()
        user_doc = db.collection('users').document(user_id).get()
        email = user_doc.to_dict().get('email', 'admin@rizalert.com')
    except:
        email = 'admin@rizalert.com'
    
    # Generate QR code
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=email,
        issuer_name='RizAlert'
    )
    
    # Create QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return jsonify({
        'success': True,
        'qr_code': f'data:image/png;base64,{img_str}',
        'secret': secret
    })

@main.route('/admin/2fa/verify', methods=['POST'])
def verify_2fa():
    if not session.get('logged_in') or not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        data = request.json
        code = data.get('code')
        secret = session.get('temp_2fa_secret')
        
        if not secret:
            return jsonify({
                'success': False,
                'error': '2FA not set up'
            }), 400
        
        totp = pyotp.TOTP(secret)
        
        if totp.verify(code):
            # Save the secret to Firestore
            db = get_db()
            user_id = session.get('user_id')
            user_ref = db.collection('users').document(user_id)
            user_ref.update({
                'two_factor_secret': secret,
                'two_factor_enabled': True,
                'two_factor_setup_date': firestore.SERVER_TIMESTAMP
            })
            
            # Clear temp secret from session
            session.pop('temp_2fa_secret', None)
            
            return jsonify({
                'success': True,
                'message': '2FA enabled successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid verification code'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main.route('/admin/2fa/disable', methods=['POST'])
def disable_2fa():
    if not session.get('logged_in') or not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        data = request.json
        code = data.get('code')
        
        # Get secret from Firestore
        db = get_db()
        user_id = session.get('user_id')
        user_doc = db.collection('users').document(user_id).get()
        
        if not user_doc.exists:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404
        
        user_data = user_doc.to_dict()
        secret = user_data.get('two_factor_secret')
        
        if not secret:
            return jsonify({
                'success': False,
                'error': '2FA not enabled'
            }), 400
        
        totp = pyotp.TOTP(secret)
        
        if totp.verify(code):
            # Remove 2FA from Firestore
            user_ref = db.collection('users').document(user_id)
            user_ref.update({
                'two_factor_secret': firestore.DELETE_FIELD,
                'two_factor_enabled': False,
                'two_factor_disabled_date': firestore.SERVER_TIMESTAMP
            })
            
            return jsonify({
                'success': True,
                'message': '2FA disabled successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid verification code'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        data = request.json
        email = data.get('email') or data.get('username')  # Accept email or username
        password = data.get('password')
        two_factor_code = data.get('two_factor_code')
        
        try:
            db = get_db()
            
            # If username provided instead of email, find the email
            if email and '@' not in email:
                # Search for user by username
                users_ref = db.collection('users').where('email', '==', email).limit(1)
                users = list(users_ref.stream())
                if not users:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid credentials'
                    }), 401
                email = users[0].to_dict().get('email')
            
            # Try to sign in with Firebase Authentication
            # Note: Firebase Admin SDK doesn't verify passwords directly
            # We need to verify the user exists and check their role
            user_by_email = auth.get_user_by_email(email)
            uid = user_by_email.uid
            
            # Fetch user from Firestore to check role
            user_ref = db.collection('users').document(uid)
            user_doc = user_ref.get()
            
            if not user_doc.exists:
                return jsonify({
                    'success': False,
                    'error': 'User not found'
                }), 401
            
            user_data = user_doc.to_dict()
            
            # Check if user is admin
            if user_data.get('role') != 'admin':
                return jsonify({
                    'success': False,
                    'error': 'Access denied. Admin role required.'
                }), 403
            
            # 2FA is REQUIRED for all admin logins
            two_factor_secret = user_data.get('two_factor_secret')
            two_factor_enabled = user_data.get('two_factor_enabled', False)
            
            if not two_factor_secret and not two_factor_enabled:
                # Admin doesn't have 2FA set up yet - allow ONE-TIME login to set it up
                # Create temporary session to access profile
                session['logged_in'] = True
                session['user_id'] = uid
                session['username'] = user_data.get('username')
                session['email'] = email
                session['role'] = 'admin'
                session['requires_2fa_setup'] = True  # Flag for first-time setup
                session['last_login'] = datetime.now().isoformat()
                
                return jsonify({
                    'success': True,
                    'requires_2fa_setup': True,
                    'message': '2FA setup required. Redirecting to profile...',
                    'redirect': '/admin/profile'
                })
            
            # Check if 2FA code was provided
            if not two_factor_code:
                # First step: credentials valid, but need 2FA code
                session['pending_login_uid'] = uid
                session['pending_login_email'] = email
                return jsonify({
                    'success': False,
                    'requires_2fa': True,
                    'message': 'Two-factor authentication is required. Please enter your 6-digit code.'
                })
            
            # Second step: verify 2FA code
            totp = pyotp.TOTP(two_factor_secret)
            
            if not totp.verify(two_factor_code):
                return jsonify({
                    'success': False,
                    'error': 'Invalid 2FA code. Please try again.'
                }), 400
            
            # Clear pending login
            session.pop('pending_login_uid', None)
            session.pop('pending_login_email', None)
            
            # Login successful - create session
            session['logged_in'] = True
            session['user_id'] = uid
            session['username'] = user_data.get('username')
            session['email'] = email
            session['role'] = 'admin'
            session['last_login'] = datetime.now().isoformat()
            
            # Update last login in Firestore
            user_ref.update({
                'lastLogin': firestore.SERVER_TIMESTAMP
            })
            
            return jsonify({
                'success': True,
                'message': 'Login successful',
                'redirect': '/'
            })
            
        except auth.UserNotFoundError:
            return jsonify({
                'success': False,
                'error': 'Invalid credentials'
            }), 401
        except Exception as e:
            print(f"Login error: {e}")
            return jsonify({
                'success': False,
                'error': 'An error occurred during login. Please try again.'
            }), 500
    
    return render_template('admin-login.html')

@main.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('main.admin_login'))

@api.route('/firebase-config')
def get_firebase_config():
    """Get Firebase configuration for client-side use"""
    try:
        # Read Firebase config from credentials file or environment
        config = {
            'apiKey': os.environ.get('FIREBASE_API_KEY', 'AIzaSyC6tPMZSJzP8acllPuHSNxkO5fIYsnPv20'),
            'authDomain': os.environ.get('FIREBASE_AUTH_DOMAIN', 'rizalert-ca105.firebaseapp.com'),
            'projectId': os.environ.get('FIREBASE_PROJECT_ID', 'rizalert-ca105'),
            'storageBucket': os.environ.get('FIREBASE_STORAGE_BUCKET', 'rizalert-ca105.appspot.com'),
            'messagingSenderId': os.environ.get('FIREBASE_MESSAGING_SENDER_ID', '521656736381'),
            'appId': os.environ.get('FIREBASE_APP_ID', '1:521656736381:web:d2e05b0a407226a247af14')
        }
        
        # If environment variables aren't set, provide defaults or read from credentials
        if not config['projectId']:
            # Try to extract project ID from credentials file
            import json
            cred_path = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')
            try:
                with open(cred_path, 'r') as f:
                    cred_data = json.load(f)
                    project_id = cred_data.get('project_id')
                    if project_id:
                        config.update({
                            'projectId': project_id,
                            'authDomain': f"{project_id}.firebaseapp.com",
                            'storageBucket': f"{project_id}.appspot.com"
                        })
            except Exception as e:
                print(f"Could not read Firebase credentials: {e}")
        
        return jsonify(config)
    except Exception as e:
        print(f"Error getting Firebase config: {e}")
        return jsonify({'error': 'Firebase configuration not available'}), 500

@main.route('/setup-admin/<email>/<password>')
def setup_admin(email, password):
    """Helper route to create an admin user - REMOVE THIS IN PRODUCTION"""
    try:
        db = get_db()
        
        # Check if user already exists in Firebase Auth
        try:
            user = auth.get_user_by_email(email)
            uid = user.uid
            print(f"User already exists with UID: {uid}")
        except auth.UserNotFoundError:
            # Create user in Firebase Authentication
            user = auth.create_user(
                email=email,
                password=password,
                email_verified=True
            )
            uid = user.uid
            print(f"Created new user with UID: {uid}")
        
        # Create or update user document in Firestore
        user_ref = db.collection('users').document(uid)
        user_ref.set({
            'email': email,
            'username': email.split('@')[0],
            'fullName': 'Admin User',
            'role': 'admin',
            'department': 'Emergency Management',
            'status': 'ACTIVE',
            'phone': '',
            'address': '',
            'two_factor_enabled': False,
            'createdAt': datetime.now().strftime('%Y-%m-%d'),
            'lastLogin': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        return jsonify({
            'success': True,
            'message': f'Admin user created/updated: {email}',
            'uid': uid,
            'instructions': [
                f'1. Login at /admin/login with email: {email}',
                f'2. Password: {password}',
                '3. Go to Profile → Security tab',
                '4. Click "Enable 2FA" and scan QR code',
                '5. IMPORTANT: Remove this setup route in production!'
            ]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main.route('/map')
def map_view():
    # Get active emergencies with users
    all_emergencies = Emergency.get_active_emergencies()
    all_users = User.get_all()
    
    user_lookup = {user['id']: user for user in all_users}
    
    emergencies = []
    for emergency in all_emergencies:
        user = user_lookup.get(emergency.get('user_id'))
        if emergency.get('case_type') and user:
            emergency = enrich_emergency_data(emergency)
            emergency['user'] = user
            emergencies.append(emergency)
            print(emergency.get('latitude'), emergency.get('longitude'))
    
    # Get current user for navbar
    current_user = get_current_user()
    
    return render_template('map.html', emergencies=emergencies, current_user=current_user)

@main.route('/emergencies')
def emergencies_page():
    # Get all emergencies with user information
    all_emergencies = Emergency.get_all()
    all_users = User.get_all()
    
    user_lookup = {user['id']: user for user in all_users}
    
    emergencies = []
    for emergency in all_emergencies:
        user = user_lookup.get(emergency.get('user_id'))
        if user:
            emergency = enrich_emergency_data(emergency)
            emergency['user'] = user
            
            # Enrich responders with user information
            responders = emergency.get('responders', [])
            enriched_responders = []
            for responder in responders:
                responder_user = user_lookup.get(responder.get('responder_id'))
                enriched_responder = {
                    'responder_id': responder.get('responder_id'),
                    'fullName': responder_user.get('fullName') if responder_user else 'Unknown User',
                    'username': responder_user.get('username') if responder_user else 'unknown',
                    'response_datetime': responder.get('response_datetime'),
                    'status': responder.get('status'),
                    'isArrived': responder.get('isArrived')
                }
                enriched_responders.append(enriched_responder)
            emergency['responders'] = enriched_responders
            
            emergencies.append(emergency)
    
    # Sort by created_at descending (most recent first)
    emergencies = sorted(emergencies, key=lambda x: x.get('created_at', datetime.min), reverse=True)
    
    # Get case types for the create form
    case_types = [{'name': ct.name, 'value': ct.value} for ct in CaseType]
    statuses = [{'name': st.name, 'value': st.value} for st in EmergencyStatus]
    users_list = User.get_all()
    
    # Get current user for navbar
    current_user = get_current_user()
    
    return render_template(
        'emergencies.html',
        emergencies=emergencies,
        case_types=case_types,
        statuses=statuses,
        users=users_list,
        current_user=current_user
    )

@main.route('/emergencies/<string:emergency_id>')
def emergency_details(emergency_id):
    """View detailed information about a specific emergency"""
    try:
        # Get the specific emergency
        emergency = Emergency.get_by_id(emergency_id)
        if not emergency:
            return render_template('404.html', message='Emergency not found'), 404
        
        # Get all users for lookup
        all_users = User.get_all()
        user_lookup = {user['id']: user for user in all_users}
        
        # Get the user who reported this emergency
        user = user_lookup.get(emergency.get('user_id'))
        if not user:
            return render_template('404.html', message='Reporter not found'), 404
        
        # Enrich emergency data
        emergency = enrich_emergency_data(emergency)
        emergency['user'] = user
        
        # Enrich responders with user information
        responders = emergency.get('responders', [])
        enriched_responders = []
        for responder in responders:
            responder_user = user_lookup.get(responder.get('responder_id'))
            enriched_responder = {
                'responder_id': responder.get('responder_id'),
                'fullName': responder_user.get('fullName') if responder_user else 'Unknown User',
                'username': responder_user.get('username') if responder_user else 'unknown',
                'email': responder_user.get('email') if responder_user else 'N/A',
                'phone': responder_user.get('phone') if responder_user else 'N/A',
                'response_datetime': responder.get('response_datetime'),
                'status': responder.get('status'),
                'isArrived': responder.get('isArrived')
            }
            enriched_responders.append(enriched_responder)
        emergency['responders'] = enriched_responders
        
        # Get case types and statuses for editing
        case_types = [{'name': ct.name, 'value': ct.value} for ct in CaseType]
        statuses = [{'name': st.name, 'value': st.value} for st in EmergencyStatus]
        users_list = User.get_all()
        
        return render_template(
            'emergency-details.html',
            emergency=emergency,
            case_types=case_types,
            statuses=statuses,
            users=users_list
        )
    except Exception as e:
        print(f"Error loading emergency details: {e}")
        return render_template('404.html', message='Error loading emergency details'), 500

@main.route('/emergencies/<string:emergency_id>/edit')
def emergency_edit(emergency_id):
    """Edit a specific emergency"""
    try:
        # Get the specific emergency
        emergency = Emergency.get_by_id(emergency_id)
        if not emergency:
            return render_template('404.html', message='Emergency not found'), 404
        
        # Get all users for lookup
        all_users = User.get_all()
        user_lookup = {user['id']: user for user in all_users}
        
        # Get the user who reported this emergency
        user = user_lookup.get(emergency.get('user_id'))
        if not user:
            return render_template('404.html', message='Reporter not found'), 404
        
        # Enrich emergency data
        emergency = enrich_emergency_data(emergency)
        emergency['user'] = user
        
        # Enrich responders with user information
        responders = emergency.get('responders', [])
        enriched_responders = []
        for responder in responders:
            responder_user = user_lookup.get(responder.get('responder_id'))
            enriched_responder = {
                'responder_id': responder.get('responder_id'),
                'fullName': responder_user.get('fullName') if responder_user else 'Unknown User',
                'username': responder_user.get('username') if responder_user else 'unknown',
                'response_datetime': responder.get('response_datetime'),
                'status': responder.get('status'),
                'isArrived': responder.get('isArrived')
            }
            enriched_responders.append(enriched_responder)
        emergency['responders'] = enriched_responders
        
        # Get case types and statuses for editing
        case_types = [{'name': ct.name, 'value': ct.value} for ct in CaseType]
        statuses = [{'name': st.name, 'value': st.value} for st in EmergencyStatus]
        users_list = User.get_all()
        responders_list = [u for u in all_users if u.get('role') == 'responder']
        
        return render_template(
            'emergency-edit.html',
            emergency=emergency,
            case_types=case_types,
            statuses=statuses,
            users=users_list,
            responders=responders_list
        )
    except Exception as e:
        print(f"Error loading emergency for editing: {e}")
        return render_template('404.html', message='Error loading emergency for editing'), 500

@main.route('/reports')
def reports_page():
    try:
        # Get filter parameters
        filter_barangay = request.args.get('barangay', '')
        filter_municipality = request.args.get('municipality', 'Rizal')
        
        # Define barangays list at the top (barangays of Rizal, Nueva Ecija)
        barangays = [ "Adela", "Aguas", "Magsikap", "Malawaan", "Manoot", "Pitogo","Rizal", "Salvacion", "San Pedro", "Sto Nino", "Rumbang"]
        
        # Get all data for reports
        all_emergencies = Emergency.get_all()
        all_users = User.get_all()
        all_alerts = EmergencyAlert.get_all()
        
        # Filter users by barangay if specified
        filtered_users = all_users
        if filter_barangay:
            # Case-insensitive and trimmed comparison to match barangay_stats calculation
            filtered_users = [
                u for u in all_users 
                if u.get('barangay') and u.get('barangay').strip().lower() == filter_barangay.strip().lower()
            ]
        
        # Get barangay statistics
        barangay_stats = {}
        for barangay in barangays:
            # Case-insensitive and trimmed comparison to handle data inconsistencies
            barangay_stats[barangay] = sum(
                1 for u in all_users 
                if u.get('barangay') and u.get('barangay').strip().lower() == barangay.lower()
            )
        
        # Debug: Print barangay statistics and actual user barangays
        print(f"\n🏘️  Barangay Statistics Debug:")
        print(f"Total users: {len(all_users)}")
        for barangay in barangays:
            count = barangay_stats[barangay]
            print(f"  {barangay}: {count} users")
        
        # Check what barangay values actually exist in the database
        unique_barangays = set()
        for u in all_users:
            user_barangay = u.get('barangay')
            if user_barangay:
                unique_barangays.add(user_barangay.strip())
        print(f"\nActual barangay values in database: {sorted(unique_barangays)}")
        print(f"Expected barangays: {barangays}\n")
        
        # Debug filter
        if filter_barangay:
            print(f"🔍 Filter applied: '{filter_barangay}'")
            print(f"   Filtered users: {len(filtered_users)}")
        
        # Create user lookup for enrichment
        user_lookup = {user['id']: user for user in all_users}
        
        # Enrich emergencies with user info and filter by barangay
        enriched_emergencies = []
        for emergency in all_emergencies:
            e = emergency.copy()
            user = user_lookup.get(e.get('user_id'))
            e['reported_by'] = user.get('username', 'Unknown') if user else 'Unknown'
            e['user_barangay'] = user.get('barangay', 'N/A') if user else 'N/A'
            
            # Filter emergencies by barangay if specified
            if not filter_barangay or (
                user and 
                user.get('barangay') and 
                user.get('barangay').strip().lower() == filter_barangay.strip().lower()
            ):
                enriched_emergencies.append(e)
        
        # Debug filter results
        if filter_barangay:
            print(f"   Filtered emergencies: {len(enriched_emergencies)}")
        
        # Calculate statistics (using filtered data)
        total_emergencies = len(enriched_emergencies)
        total_users = len(filtered_users)
        total_alerts = len(all_alerts)
        
        # Overall statistics (unfiltered)
        overall_emergencies = len(all_emergencies)
        overall_users = len(all_users)
        
        # Emergency statistics by status
        pending_count = sum(1 for e in enriched_emergencies if e.get('status') == 'PENDING')
        in_progress_count = sum(1 for e in enriched_emergencies if e.get('status') == 'IN_PROGRESS')
        resolved_count = sum(1 for e in enriched_emergencies if e.get('status') == 'RESOLVED')
        active_count = sum(1 for e in enriched_emergencies if e.get('isActive'))
        
        # Emergency statistics by type (excluding Typhoon and Flood)
        case_type_stats = {}
        excluded_types = ['TYPHOON', 'FLOOD']
        for ct in CaseType:
            if ct.name not in excluded_types:
                case_type_stats[ct.value] = sum(1 for e in enriched_emergencies if e.get('case_type') == ct.name)
        
        # User statistics by role (filtered)
        role_stats = {
            'citizen': sum(1 for u in filtered_users if u.get('role') == 'citizen'),
            'admin': sum(1 for u in filtered_users if u.get('role') == 'admin'),
            'responder': sum(1 for u in filtered_users if u.get('role') == 'responder')
        }
        
        # User statistics by status (filtered)
        active_users = sum(1 for u in filtered_users if u.get('status') == 'ACTIVE')
        inactive_users = sum(1 for u in filtered_users if u.get('status') == 'INACTIVE')
        
        # Monthly trend data (last 6 months)
        from datetime import timezone
        current_date = datetime.now(timezone.utc)
        monthly_data = []
        for i in range(5, -1, -1):
            month_start = (current_date - timedelta(days=i*30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            month_emergencies = []
            for e in enriched_emergencies:
                created_at = e.get('created_at')
                if created_at and isinstance(created_at, datetime):
                    # Make sure both datetimes are timezone-aware for comparison
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if month_start <= created_at < month_end:
                        month_emergencies.append(e)
            
            monthly_data.append({
                'month': month_start.strftime('%b %Y'),
                'count': len(month_emergencies)
            })
    
        # Get current user for navbar
        current_user = get_current_user()
    
        return render_template(
            'reports.html',
            total_emergencies=total_emergencies,
            total_users=total_users,
            total_alerts=total_alerts,
            overall_emergencies=overall_emergencies,
            overall_users=overall_users,
            pending_count=pending_count,
            in_progress_count=in_progress_count,
            resolved_count=resolved_count,
            active_count=active_count,
            case_type_stats=case_type_stats,
            role_stats=role_stats,
            active_users=active_users,
            inactive_users=inactive_users,
            monthly_data=monthly_data,
            emergencies=enriched_emergencies,
            users=filtered_users,
            all_users=all_users,
            alerts=all_alerts,
            barangays=barangays,
            barangay_stats=barangay_stats,
            filter_barangay=filter_barangay,
            filter_municipality=filter_municipality,
            current_user=current_user
        )
    except Exception as e:
        print(f"Error in reports_page: {e}")
        # Return template with default empty data
        barangays = ["Rizal", "Adela", "Aguas", "Magsikap", "Malawaan", "Manoot", "Pitogo", "Salvacion", "San Pedro", "Sto Nino", "Rumbang"]
        return render_template(
            'reports.html',
            total_emergencies=0,
            total_users=0,
            total_alerts=0,
            overall_emergencies=0,
            overall_users=0,
            pending_count=0,
            in_progress_count=0,
            resolved_count=0,
            active_count=0,
            case_type_stats={ct.value: 0 for ct in CaseType if ct.name not in ['TYPHOON', 'FLOOD']},
            role_stats={'citizen': 0, 'admin': 0, 'responder': 0},
            active_users=0,
            inactive_users=0,
            monthly_data=[],
            emergencies=[],
            users=[],
            all_users=[],
            alerts=[],
            barangays=barangays,
            barangay_stats={b: 0 for b in barangays},
            filter_barangay='',
            filter_municipality='Rizal'
        )

@main.route('/alerts')
def alerts_page():
    """Emergency Alerts page with filtering by response status"""
    try:
        # Get filter parameters
        filter_status = request.args.get('status', '')  # 'safe', 'danger', 'evacuating', or ''
        
        # Get all emergency alerts
        all_alerts = EmergencyAlert.get_all()
        all_users = User.get_all()
        
        # Create user lookup for enriching people data
        user_lookup = {user['id']: user for user in all_users}
        
        # Enrich alerts with detailed people information
        enriched_alerts = []
        for alert in all_alerts:
            enriched_alert = alert.copy()
            
            # Enrich people_safe
            people_safe = []
            for person in alert.get('people_safe', []):
                user = user_lookup.get(person.get('userId'))
                if user:
                    people_safe.append({
                        'userId': person.get('userId'),
                        'fullName': user.get('fullName', 'Unknown'),
                        'username': user.get('username', 'unknown'),
                        'barangay': user.get('barangay', 'N/A'),
                        'date_created': person.get('date_created'),
                        'status': 'safe'
                    })
            
            # Enrich people_danger
            people_danger = []
            for person in alert.get('people_danger', []):
                user = user_lookup.get(person.get('userId'))
                if user:
                    people_danger.append({
                        'userId': person.get('userId'),
                        'fullName': user.get('fullName', 'Unknown'),
                        'username': user.get('username', 'unknown'),
                        'barangay': user.get('barangay', 'N/A'),
                        'date_created': person.get('date_created'),
                        'status': 'danger'
                    })
            
            # Enrich people_evacuating
            people_evacuating = []
            for person in alert.get('people_evacuating', []):
                user = user_lookup.get(person.get('userId'))
                if user:
                    people_evacuating.append({
                        'userId': person.get('userId'),
                        'fullName': user.get('fullName', 'Unknown'),
                        'username': user.get('username', 'unknown'),
                        'barangay': user.get('barangay', 'N/A'),
                        'date_created': person.get('date_created'),
                        'status': 'evacuating'
                    })
            
            enriched_alert['people_safe'] = people_safe
            enriched_alert['people_danger'] = people_danger
            enriched_alert['people_evacuating'] = people_evacuating
            enriched_alert['total_responses'] = len(people_safe) + len(people_danger) + len(people_evacuating)
            
            enriched_alerts.append(enriched_alert)
        
        # Sort by date_created descending (most recent first)
        enriched_alerts = sorted(enriched_alerts, key=lambda x: x.get('date_created', datetime.min), reverse=True)
        
        # Apply filtering based on status if specified
        filtered_alerts = enriched_alerts
        if filter_status:
            filtered_alerts = []
            for alert in enriched_alerts:
                should_include = False
                
                if filter_status == 'safe' and len(alert.get('people_safe', [])) > 0:
                    should_include = True
                elif filter_status == 'danger' and len(alert.get('people_danger', [])) > 0:
                    should_include = True
                elif filter_status == 'evacuating' and len(alert.get('people_evacuating', [])) > 0:
                    should_include = True
                
                if should_include:
                    filtered_alerts.append(alert)
            
            print(f"🔍 Alert Filtering Debug:")
            print(f"   Filter status: '{filter_status}'")
            print(f"   Total alerts: {len(enriched_alerts)}")
            print(f"   Filtered alerts: {len(filtered_alerts)}")
            for alert in enriched_alerts:
                safe_count = len(alert.get('people_safe', []))
                danger_count = len(alert.get('people_danger', []))
                evacuating_count = len(alert.get('people_evacuating', []))
                print(f"   Alert {alert.get('id', 'unknown')}: Safe={safe_count}, Danger={danger_count}, Evacuating={evacuating_count}")
        
        # Calculate statistics (using filtered alerts for display but all alerts for totals)
        total_alerts = len(enriched_alerts)  # Total of all alerts
        total_people_safe = sum(len(a.get('people_safe', [])) for a in enriched_alerts)
        total_people_danger = sum(len(a.get('people_danger', [])) for a in enriched_alerts)
        total_people_evacuating = sum(len(a.get('people_evacuating', [])) for a in enriched_alerts)
        total_responses = total_people_safe + total_people_danger + total_people_evacuating
        
        # Get case types for display
        case_types = [ct.value for ct in CaseType]
        
        # Get current user for navbar
        current_user = get_current_user()
        
        return render_template(
            'alerts.html',
            alerts=filtered_alerts,  # Use filtered alerts instead of all alerts
            total_alerts=total_alerts,
            total_people_safe=total_people_safe,
            total_people_danger=total_people_danger,
            total_people_evacuating=total_people_evacuating,
            total_responses=total_responses,
            filter_status=filter_status,
            case_types=case_types,
            filtered_count=len(filtered_alerts),  # Add count of filtered results
            current_user=current_user
        )
    except Exception as e:
        print(f"Error in alerts_page: {e}")
        import traceback
        traceback.print_exc()
        return render_template(
            'alerts.html',
            alerts=[],
            total_alerts=0,
            total_people_safe=0,
            total_people_danger=0,
            total_people_evacuating=0,
            total_responses=0,
            filter_status='',
            case_types=[ct.value for ct in CaseType]
        )


@api.route('/notifications', methods=['GET'])
def get_notifications():
    """Aggregate recent notifications from emergency alerts and emergency responder updates"""
    try:
        notifications = []

        # recent alerts and their people lists
        alerts = EmergencyAlert.get_recent_alerts(limit=20)
        all_users = User.get_all()
        user_lookup = {u['id']: u for u in all_users}

        for alert in alerts:
            alert_id = alert.get('id')
            alert_type = alert.get('emergency_type')
            alert_desc = alert.get('emergency_descriptions')
            alert_date = alert.get('date_created')

            for list_name in ['people_safe', 'people_danger', 'people_evacuating']:
                people = alert.get(list_name, []) or []
                for person in people:
                    # person may contain userId or id, and possibly date_created
                    user_id = person.get('userId') or person.get('id') or person.get('responder_id')
                    user = user_lookup.get(user_id)
                    notif = {
                        'type': 'alert',
                        'alert_id': alert_id,
                        'alert_type': alert_type,
                        'message': alert_desc,
                        'list': list_name,
                        'list_label': 'Safe' if list_name == 'people_safe' else 'Danger' if list_name == 'people_danger' else 'Evacuating',
                        'user_id': user_id,
                        'user_name': user.get('fullName') if user else person.get('fullName') if person.get('fullName') else user_id,
                        'timestamp': None
                    }
                    # prefer a person-level timestamp, fallback to alert date
                    pd = person.get('date_created') or person.get('response_datetime')
                    if isinstance(pd, datetime):
                        notif['timestamp'] = pd.isoformat()
                    elif isinstance(alert_date, datetime):
                        notif['timestamp'] = alert_date.isoformat()
                    else:
                        notif['timestamp'] = None

                    notifications.append(notif)

        # recent emergency responder updates
        recent_emergencies = Emergency.get_recent(limit=50)
        for em in recent_emergencies:
            em_id = em.get('id')
            case_type = em.get('case_type')
            responders = em.get('responders', []) or []
            for responder in responders:
                resp_id = responder.get('responder_id')
                resp_user = user_lookup.get(resp_id)
                rd = responder.get('response_datetime')
                notif = {
                    'type': 'responder',
                    'emergency_id': em_id,
                    'emergency_type': case_type,
                    'responder_id': resp_id,
                    'responder_name': resp_user.get('fullName') if resp_user else responder.get('fullName') or resp_id,
                    'status': responder.get('status'),
                    'arrived': bool(responder.get('isArrived')),
                    'timestamp': rd.isoformat() if isinstance(rd, datetime) else (rd if isinstance(rd, str) else None)
                }
                notifications.append(notif)

        # sort by timestamp desc (placing None at the end)
        def _ts(n):
            t = n.get('timestamp')
            try:
                return datetime.fromisoformat(t) if t else datetime.min
            except Exception:
                return datetime.min

        notifications = sorted(notifications, key=_ts, reverse=True)[:50]

        return jsonify(notifications)
    except Exception as e:
        print(f"Error building notifications: {e}")
        return jsonify([])

@api.route('/notifications/count', methods=['GET'])
def get_notifications_count():
    """Get count of unread notifications"""
    try:
        # Get read notifications from session
        read_notifications = session.get('read_notifications', set())
        notifications = []

        # recent alerts and their people lists
        alerts = EmergencyAlert.get_recent_alerts(limit=20)
        
        for alert in alerts:
            alert_id = alert.get('id')
            for list_name in ['people_safe', 'people_danger', 'people_evacuating']:
                people = alert.get(list_name, []) or []
                for person in people:
                    # Create unique notification ID
                    notif_id = f"alert_{alert_id}_{list_name}_{person.get('userId', person.get('id', ''))}"
                    if notif_id not in read_notifications:
                        notifications.append(notif_id)

        # recent emergency responder updates
        recent_emergencies = Emergency.get_recent(limit=50)
        for em in recent_emergencies:
            em_id = em.get('id')
            responders = em.get('responders', []) or []
            for responder in responders:
                # Create unique notification ID
                resp_id = responder.get('responder_id')
                notif_id = f"responder_{em_id}_{resp_id}"
                if notif_id not in read_notifications:
                    notifications.append(notif_id)

        return jsonify({'count': len(notifications)})
    except Exception as e:
        print(f"Error counting notifications: {e}")
        return jsonify({'count': 0})

@api.route('/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    """Mark notifications as read"""
    try:
        # When user opens notifications modal, mark all current notifications as read
        read_notifications = set(session.get('read_notifications', []))
        
        # Get all current notification IDs
        alerts = EmergencyAlert.get_recent_alerts(limit=20)
        for alert in alerts:
            alert_id = alert.get('id')
            for list_name in ['people_safe', 'people_danger', 'people_evacuating']:
                people = alert.get(list_name, []) or []
                for person in people:
                    notif_id = f"alert_{alert_id}_{list_name}_{person.get('userId', person.get('id', ''))}"
                    read_notifications.add(notif_id)

        recent_emergencies = Emergency.get_recent(limit=50)
        for em in recent_emergencies:
            em_id = em.get('id')
            responders = em.get('responders', []) or []
            for responder in responders:
                resp_id = responder.get('responder_id')
                notif_id = f"responder_{em_id}_{resp_id}"
                read_notifications.add(notif_id)

        # Store back in session (convert set to list for JSON serialization)
        session['read_notifications'] = list(read_notifications)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error marking notifications as read: {e}")
        return jsonify({'success': False})

@api.route('/emergencies/count', methods=['GET'])
def get_emergencies_count():
    """Get count of unviewed recent emergencies"""
    try:
        # Get viewed emergencies from session
        viewed_emergencies = set(session.get('viewed_emergencies', []))
        
        # Get emergencies from the last 24 hours
        from datetime import datetime, timedelta
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        all_emergencies = Emergency.get_all()
        new_unviewed_emergencies = []
        
        for emergency in all_emergencies:
            emergency_id = emergency.get('id')
            created_at = emergency.get('created_at')
            
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00').replace('+00:00', ''))
                except:
                    continue
            elif isinstance(created_at, datetime):
                # Make timezone-naive if timezone-aware
                if created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
            else:
                continue
                
            # Only count if it's new (last 24 hours) and not viewed
            if created_at >= twenty_four_hours_ago and emergency_id not in viewed_emergencies:
                new_unviewed_emergencies.append(emergency)

        return jsonify({'count': len(new_unviewed_emergencies)})
    except Exception as e:
        print(f"Error counting emergencies: {e}")
        return jsonify({'count': 0})

@api.route('/emergencies/mark-viewed', methods=['POST'])
def mark_emergency_viewed():
    """Mark an emergency as viewed"""
    try:
        data = request.json
        emergency_id = data.get('emergency_id')
        
        if not emergency_id:
            return jsonify({'success': False, 'error': 'Emergency ID required'})
        
        # Get viewed emergencies from session
        viewed_emergencies = set(session.get('viewed_emergencies', []))
        viewed_emergencies.add(emergency_id)
        
        # Store back in session
        session['viewed_emergencies'] = list(viewed_emergencies)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error marking emergency as viewed: {e}")
        return jsonify({'success': False, 'error': str(e)})

@main.route('/add_user/<username>/<email>')
def add_user(username, email):
    user_id = User.create({
        'username': username,
        'email': email,
        'fullName': username,
        'password_hash': User.set_password('default'),
        'role': 'admin',
        'status': 'ACTIVE'
    })
    return f'Added {username} with ID {user_id}'

# User Routes
@api.route('/users', methods=['GET'])
def get_users():
    users = User.get_all()
    return jsonify([{
        'id': u['id'],
        'username': u.get('username'),
        'email': u.get('email'),
        'address': u.get('address'),
        'fullName': u.get('fullName'),
        'profile_image': u.get('profile_image'),
        'role': u.get('role'),
        'department': u.get('department'),
        'status': u.get('status')
    } for u in users])

@api.route('/users', methods=['POST'])
def add_api_user():
    data = request.get_json()
    user_id = User.create_user(
        username=data['username'],
        email=data['email'],
        fullName=data['fullName'],
        password=data['password'],
        address=data.get('address'),
        role=data.get('role', 'admin'),
        department=data.get('department'),
        status=data.get('status', 'ACTIVE'),
        profile_image=data.get('profile_image')
    )
    return jsonify({'message': f'Added {data["username"]}', 'id': user_id}), 201

@api.route('/users/<string:id>', methods=['GET'])
def get_user(id):
    user = User.get_by_id(id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'id': user['id'],
        'username': user.get('username'),
        'email': user.get('email'),
        'address': user.get('address'),
        'fullName': user.get('fullName'),
        'profile_image': user.get('profile_image'),
        'role': user.get('role'),
        'department': user.get('department'),
        'status': user.get('status'),
        'barangay': user.get('barangay'),
        'municipality': user.get('municipality')
    })

@api.route('/users/<string:id>', methods=['PUT'])
def update_user(id):
    print(f"DEBUG: Received PUT request for user ID: {id}")
    
    user = User.get_by_id(id)
    if not user:
        print(f"DEBUG: User not found with ID: {id}")
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    print(f"DEBUG: Received data: {data}")
    
    update_data = {}
    
    if 'username' in data:
        update_data['username'] = data['username']
    if 'email' in data:
        update_data['email'] = data['email']
    if 'address' in data:
        update_data['address'] = data['address']
    if 'fullName' in data:
        update_data['fullName'] = data['fullName']
    if 'password' in data:
        update_data['password_hash'] = User.set_password(data['password'])
    if 'profile_image' in data:
        update_data['profile_image'] = data['profile_image']
    if 'role' in data:
        update_data['role'] = data['role']
    if 'department' in data:
        update_data['department'] = data['department']
    if 'status' in data:
        update_data['status'] = data['status']
    if 'barangay' in data:
        update_data['barangay'] = data['barangay']
    if 'municipality' in data:
        update_data['municipality'] = data['municipality']
    
    # Add timestamp for last update
    from google.cloud import firestore
    update_data['updatedAt'] = firestore.SERVER_TIMESTAMP
    
    print(f"DEBUG: Update data to be applied: {update_data}")
    
    try:
        # Update Firebase Auth if email or password changed
        auth_updates = {}
        if 'email' in data and data['email'] != user.get('email'):
            auth_updates['email'] = data['email']
        if 'fullName' in data and data['fullName'] != user.get('fullName'):
            auth_updates['display_name'] = data['fullName']
        if 'password' in data:
            auth_updates['password'] = data['password']
        
        # Update Firebase Auth if there are changes
        if auth_updates:
            from app.firebase_config import get_auth
            auth_module = get_auth()
            try:
                auth_module.update_user(id, **auth_updates)
                print(f"DEBUG: Successfully updated Firebase Auth for user {id}")
            except Exception as auth_error:
                print(f"DEBUG: Warning - Could not update Firebase Auth: {auth_error}")
                # Continue with Firestore update even if Auth update fails
        
        # Update Firestore
        User.update(id, update_data)
        print(f"DEBUG: Successfully updated user {id}")
        return jsonify({'message': f'Updated {user.get("username")}'})
    except Exception as e:
        print(f"DEBUG: Error updating user: {e}")
        return jsonify({'error': f'Failed to update user: {str(e)}'}), 500

@api.route('/users/<string:id>', methods=['DELETE'])
def delete_user(id):
    user = User.get_by_id(id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        User.delete_user(id)
        return jsonify({'message': f'Deleted {user.get("username")}'})
    except Exception as e:
        return jsonify({'error': f'Failed to delete user: {str(e)}'}), 500

# Case Routes
# Emergency Routes
@api.route('/emergencies', methods=['GET'])
def get_emergencies():
    emergencies = Emergency.get_all()
    all_users = User.get_all()
    
    user_lookup = {user['id']: user for user in all_users}
    
    result = []
    for e in emergencies:
        user = user_lookup.get(e.get('user_id'))
        
        created_at = e.get('created_at')
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        
        # Enrich responders with user information
        responders = e.get('responders', [])
        enriched_responders = []
        for responder in responders:
            responder_user = user_lookup.get(responder.get('responder_id'))
            enriched_responder = {
                'responder_id': responder.get('responder_id'),
                'fullName': responder_user.get('fullName') if responder_user else 'Unknown User',
                'username': responder_user.get('username') if responder_user else 'unknown',
                'response_datetime': responder.get('response_datetime'),
                'status': responder.get('status'),
                'isArrived': responder.get('isArrived')
            }
            enriched_responders.append(enriched_responder)
        
        result.append({
            'id': e['id'],
            'case_type': e.get('case_type'),
            'user_id': e.get('user_id'),
            'username': user.get('username') if user else 'Unknown',
            'message': e.get('message'),
            'created_at': created_at,
            'isActive': e.get('isActive'),
            'status': e.get('status'),
            'latitude': e.get('latitude'),
            'longitude': e.get('longitude'),
            'file_id': e.get('file_id'),
            'location_text': e.get('location_text'),
            'responders': enriched_responders
        })
    
    return jsonify(result)

@api.route('/emergencies', methods=['POST'])
def add_emergency():
    data = request.get_json()
    
    user = User.get_by_id(data['user_id'])
    
    if not user:
        return jsonify({'error': 'Invalid user_id'}), 400
    
    if 'case_type' not in data:
        return jsonify({'error': 'case_type is required'}), 400
    
    emergency_id = Emergency.create_emergency(
        case_type=data['case_type'],
        user_id=data['user_id'],
        message=data.get('message'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        file_id=data.get('file_id'),
        isActive=data.get('isActive', True),
        status=data.get('status', 'PENDING'),
        location_text=data.get('location_text'),
        responders=data.get('responders', [])
    )
    
    return jsonify({'message': f'Added emergency {emergency_id}', 'id': emergency_id}), 201

@api.route('/emergencies/<string:id>', methods=['GET'])
def get_emergency(id):
    emergency = Emergency.get_by_id(id)
    if not emergency:
        return jsonify({'error': 'Emergency not found'}), 404
    user = User.get_by_id(emergency.get('user_id'))
    
    created_at = emergency.get('created_at')
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    
    # Enrich responders with user information
    responders = emergency.get('responders', [])
    enriched_responders = []
    for responder in responders:
        responder_user = User.get_by_id(responder.get('responder_id'))
        enriched_responder = {
            'responder_id': responder.get('responder_id'),
            'fullName': responder_user.get('fullName') if responder_user else 'Unknown User',
            'username': responder_user.get('username') if responder_user else 'unknown',
            'response_datetime': responder.get('response_datetime'),
            'status': responder.get('status'),
            'isArrived': responder.get('isArrived')
        }
        enriched_responders.append(enriched_responder)
    
    return jsonify({
        'id': emergency['id'],
        'case_type': CaseType[emergency.get('case_type')].value if emergency.get('case_type') else 'Unknown',
        'user_id': emergency.get('user_id'),
        'username': user.get('username') if user else 'Unknown',
        'reported_by': user.get('fullName') if user else 'Unknown',
        'message': emergency.get('message'),
        'created_at': created_at,
        'isActive': emergency.get('isActive'),
        'status': EmergencyStatus[emergency.get('status')].value if emergency.get('status') else 'Unknown',
        'latitude': emergency.get('latitude'),
        'longitude': emergency.get('longitude'),
        'file_id': emergency.get('file_id'),
        'location_text': emergency.get('location_text'),
        'responders': enriched_responders
    })

@api.route('/emergencies/<string:id>', methods=['PUT'])
def update_emergency(id):
    emergency = Emergency.get_by_id(id)
    if not emergency:
        return jsonify({'error': 'Emergency not found'}), 404
    
    data = request.get_json()
    update_data = {}
    
    if 'case_type' in data:
        update_data['case_type'] = data['case_type']
    
    if 'message' in data:
        update_data['message'] = data['message']
    
    if 'file_id' in data:
        update_data['file_id'] = data['file_id']
    
    if 'user_id' in data:
        user = User.get_by_id(data['user_id'])
        if not user:
            return jsonify({'error': 'Invalid user_id'}), 400
        update_data['user_id'] = data['user_id']
    
    if 'isActive' in data:
        update_data['isActive'] = data['isActive']
    if 'status' in data:
        update_data['status'] = data['status']
    if 'latitude' in data:
        update_data['latitude'] = data['latitude']
    if 'longitude' in data:
        update_data['longitude'] = data['longitude']
    if 'location_text' in data:
        update_data['location_text'] = data['location_text']
    if 'responders' in data:
        update_data['responders'] = data['responders']
    
    Emergency.update(id, update_data)
    return jsonify({'message': f'Updated emergency {id}'})


@api.route('/emergencies/<string:id>', methods=['DELETE'])
def delete_emergency(id):
    emergency = Emergency.get_by_id(id)
    if not emergency:
        return jsonify({'error': 'Emergency not found'}), 404
    
    Emergency.delete(id)
    return jsonify({'message': f'Deleted emergency {id}'})

# Emergency Responder Routes
@api.route('/emergencies/<string:id>/add-responder', methods=['POST'])
def add_responder_to_emergency(id):
    data = request.get_json()
    
    if 'responder_id' not in data:
        return jsonify({'error': 'responder_id is required'}), 400
    
    responder_data = {
        'responder_id': data['responder_id'],
        'response_datetime': datetime.utcnow(),
        'status': data.get('status', 'IN_PROGRESS'),
        'isArrived': data.get('isArrived', False)
    }
    
    result = Emergency.add_responder(id, responder_data)
    if result:
        return jsonify({'message': 'Responder added successfully'})
    else:
        return jsonify({'error': 'Emergency not found'}), 404

@api.route('/emergencies/<string:id>/update-responder', methods=['POST'])
def update_responder_in_emergency(id):
    data = request.get_json()
    
    if 'responder_id' not in data:
        return jsonify({'error': 'responder_id is required'}), 400
    
    result = Emergency.update_responder_status(
        id,
        data['responder_id'],
        status=data.get('status'),
        isArrived=data.get('isArrived')
    )
    
    if result:
        return jsonify({'message': 'Responder status updated successfully'})
    else:
        return jsonify({'error': 'Emergency not found'}), 404

# Emergency Alert Routes
@api.route('/emergency-alerts', methods=['GET'])
def get_emergency_alerts():
    alerts = EmergencyAlert.get_all()
    result = []
    for alert in alerts:
        date_created = alert.get('date_created')
        if isinstance(date_created, datetime):
            date_created = date_created.isoformat()
        
        result.append({
            'id': alert['id'],
            'emergency_type': alert.get('emergency_type'),
            'emergency_descriptions': alert.get('emergency_descriptions'),
            'date_created': date_created,
            'people_safe': alert.get('people_safe', []),
            'people_danger': alert.get('people_danger', []),
            'people_evacuating': alert.get('people_evacuating', [])
        })
    return jsonify(result)

@api.route('/emergency-alerts', methods=['POST'])
def create_emergency_alert():
    data = request.get_json()
    
    if 'emergency_type' not in data:
        return jsonify({'error': 'emergency_type is required'}), 400
    
    if 'emergency_descriptions' not in data:
        return jsonify({'error': 'emergency_descriptions is required'}), 400
    
    alert_id = EmergencyAlert.create_alert(
        emergency_type=data['emergency_type'],
        emergency_descriptions=data['emergency_descriptions']
    )
    
    return jsonify({'message': 'Emergency alert created successfully', 'id': alert_id}), 201

@api.route('/emergency-alerts/<string:id>', methods=['GET'])
def get_emergency_alert(id):
    alert = EmergencyAlert.get_by_id(id)
    if not alert:
        return jsonify({'error': 'Emergency alert not found'}), 404
    
    date_created = alert.get('date_created')
    if isinstance(date_created, datetime):
        date_created = date_created.isoformat()
    
    return jsonify({
        'id': alert['id'],
        'emergency_type': alert.get('emergency_type'),
        'emergency_descriptions': alert.get('emergency_descriptions'),
        'date_created': date_created,
        'people_safe': alert.get('people_safe', []),
        'people_danger': alert.get('people_danger', []),
        'people_evacuating': alert.get('people_evacuating', [])
    })

@api.route('/emergency-alerts/<string:id>/add-person', methods=['POST'])
def add_person_to_alert(id):
    data = request.get_json()
    
    if 'list_name' not in data or 'person_data' not in data:
        return jsonify({'error': 'list_name and person_data are required'}), 400
    
    try:
        result = EmergencyAlert.add_person_to_list(id, data['list_name'], data['person_data'])
        if result:
            return jsonify({'message': 'Person added successfully'})
        else:
            return jsonify({'error': 'Alert not found'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

@api.route('/emergency-alerts/<string:id>/remove-person', methods=['POST'])
def remove_person_from_alert(id):
    data = request.get_json()
    
    if 'list_name' not in data or 'person_id' not in data:
        return jsonify({'error': 'list_name and person_id are required'}), 400
    
    try:
        result = EmergencyAlert.remove_person_from_list(id, data['list_name'], data['person_id'])
        if result:
            return jsonify({'message': 'Person removed successfully'})
        else:
            return jsonify({'error': 'Alert not found'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

@api.route('/emergency-alerts/<string:id>', methods=['DELETE'])
def delete_emergency_alert(id):
    alert = EmergencyAlert.get_by_id(id)
    if not alert:
        return jsonify({'error': 'Emergency alert not found'}), 404
    
    try:
        EmergencyAlert.delete(id)
        return jsonify({'success': True, 'message': f'Emergency alert deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to delete alert: {str(e)}'}), 500

# Shorter alias route for alerts deletion
@api.route('/alerts/<string:id>', methods=['DELETE'])
def delete_alert_alias(id):
    return delete_emergency_alert(id)

# Export Routes
@api.route('/export/users/csv', methods=['GET'])
def export_users_csv():
    users = User.get_all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'Username', 'Full Name', 'Email', 'Role', 'Department', 'Status', 'Address'])
    
    # Write data
    for user in users:
        writer.writerow([
            user.get('id', ''),
            user.get('username', ''),
            user.get('fullName', ''),
            user.get('email', ''),
            user.get('role', ''),
            user.get('department', ''),
            user.get('status', ''),
            user.get('address', '')
        ])
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=users_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@api.route('/export/emergencies/csv', methods=['GET'])
def export_emergencies_csv():
    emergencies = Emergency.get_all()
    all_users = User.get_all()
    user_lookup = {user['id']: user for user in all_users}
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'Case Type', 'Status', 'Reported By', 'Message', 'Location Text', 'Latitude', 'Longitude', 'Created At', 'Is Active', 'Responders Count'])
    
    # Write data
    for emergency in emergencies:
        user = user_lookup.get(emergency.get('user_id'))
        created_at = emergency.get('created_at')
        if isinstance(created_at, datetime):
            created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
        
        writer.writerow([
            emergency.get('id', ''),
            emergency.get('case_type', ''),
            emergency.get('status', ''),
            user.get('username', 'Unknown') if user else 'Unknown',
            emergency.get('message', ''),
            emergency.get('location_text', ''),
            emergency.get('latitude', ''),
            emergency.get('longitude', ''),
            created_at or '',
            emergency.get('isActive', False),
            len(emergency.get('responders', []))
        ])
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=emergencies_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@api.route('/export/alerts/csv', methods=['GET'])
def export_alerts_csv():
    alerts = EmergencyAlert.get_all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'Emergency Type', 'Description', 'Date Created', 'People Safe', 'People in Danger', 'People Evacuating'])
    
    # Write data
    for alert in alerts:
        date_created = alert.get('date_created')
        if isinstance(date_created, datetime):
            date_created = date_created.strftime('%Y-%m-%d %H:%M:%S')
        
        writer.writerow([
            alert.get('id', ''),
            alert.get('emergency_type', ''),
            alert.get('emergency_descriptions', ''),
            date_created or '',
            len(alert.get('people_safe', [])),
            len(alert.get('people_danger', [])),
            len(alert.get('people_evacuating', []))
        ])
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=alerts_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@api.route('/export/users/pdf', methods=['GET'])
def export_users_pdf():
    users = User.get_all()
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#3b82f6'))
    
    # Title
    elements.append(Paragraph('Users Report', title_style))
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Table data
    data = [['Username', 'Full Name', 'Email', 'Role', 'Status']]
    for user in users:
        data.append([
            user.get('username', '')[:20],
            user.get('fullName', '')[:25],
            user.get('email', '')[:30],
            user.get('role', '')[:15],
            user.get('status', '')
        ])
    
    # Create table
    table = Table(data, colWidths=[1.2*inch, 1.5*inch, 2*inch, 1*inch, 0.8*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f'Total Users: {len(users)}', styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'users_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf', mimetype='application/pdf')

@api.route('/export/emergencies/pdf', methods=['GET'])
def export_emergencies_pdf():
    emergencies = Emergency.get_all()
    all_users = User.get_all()
    user_lookup = {user['id']: user for user in all_users}
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#3b82f6'))
    
    # Title
    elements.append(Paragraph('Emergencies Report', title_style))
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Statistics
    total = len(emergencies)
    active = sum(1 for e in emergencies if e.get('isActive'))
    resolved = sum(1 for e in emergencies if e.get('status') == 'RESOLVED')
    
    stats_text = f'Total Emergencies: {total} | Active: {active} | Resolved: {resolved}'
    elements.append(Paragraph(stats_text, styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Table data
    data = [['Type', 'Status', 'Reported By', 'Location', 'Created']]
    for emergency in emergencies[:50]:  # Limit to 50 for PDF
        user = user_lookup.get(emergency.get('user_id'))
        created_at = emergency.get('created_at')
        if isinstance(created_at, datetime):
            created_at = created_at.strftime('%Y-%m-%d %H:%M')
        
        data.append([
            emergency.get('case_type', '')[:10],
            emergency.get('status', '')[:12],
            user.get('username', 'Unknown')[:15] if user else 'Unknown',
            emergency.get('location_text', '')[:30] if emergency.get('location_text') else 'N/A',
            created_at or ''
        ])
    
    # Create table
    table = Table(data, colWidths=[1*inch, 1.2*inch, 1.2*inch, 2.5*inch, 1.5*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ef4444')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'emergencies_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf', mimetype='application/pdf')

@api.route('/export/complete/pdf', methods=['GET'])
def export_complete_pdf():
    """Export complete system report with all data"""
    all_emergencies = Emergency.get_all()
    all_users = User.get_all()
    all_alerts = EmergencyAlert.get_all()
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=28, textColor=colors.HexColor('#3b82f6'), spaceAfter=20)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=16, textColor=colors.HexColor('#1e40af'), spaceAfter=10)
    
    # Title
    elements.append(Paragraph('RizAlert Complete System Report', title_style))
    elements.append(Paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', styles['Normal']))
    elements.append(Spacer(1, 0.5*inch))
    
    # Summary Statistics
    elements.append(Paragraph('System Overview', section_style))
    summary_data = [
        ['Metric', 'Count'],
        ['Total Users', str(len(all_users))],
        ['Total Emergencies', str(len(all_emergencies))],
        ['Active Emergencies', str(sum(1 for e in all_emergencies if e.get('isActive')))],
        ['Emergency Alerts', str(len(all_alerts))],
        ['Resolved Cases', str(sum(1 for e in all_emergencies if e.get('status') == 'RESOLVED'))]
    ]
    
    summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Emergency Types Breakdown
    elements.append(Paragraph('Emergency Types Breakdown', section_style))
    type_data = [['Type', 'Count']]
    for ct in CaseType:
        count = sum(1 for e in all_emergencies if e.get('case_type') == ct.name)
        type_data.append([ct.value, str(count)])
    
    type_table = Table(type_data, colWidths=[3*inch, 2*inch])
    type_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ef4444')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 1), (-1, -1), colors.lightcoral),
    ]))
    
    elements.append(type_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Emergency Alerts Section
    elements.append(Paragraph('Emergency Alerts Overview', section_style))
    alert_summary_data = [
        ['Metric', 'Count'],
        ['Total Alerts', str(len(all_alerts))],
        ['Total People Safe', str(sum(len(a.get('people_safe', [])) for a in all_alerts))],
        ['Total People in Danger', str(sum(len(a.get('people_danger', [])) for a in all_alerts))],
        ['Total People Evacuating', str(sum(len(a.get('people_evacuating', [])) for a in all_alerts))]
    ]
    
    alert_summary_table = Table(alert_summary_data, colWidths=[3*inch, 2*inch])
    alert_summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f59e0b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 1), (-1, -1), colors.lightyellow),
    ]))
    
    elements.append(alert_summary_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Footer
    elements.append(Spacer(1, 0.5*inch))
    elements.append(Paragraph('Report generated by RizAlert Emergency Management System', styles['Italic']))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'complete_system_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf', mimetype='application/pdf')

@api.route('/export/alerts/pdf', methods=['GET'])
def export_alerts_pdf():
    """Export emergency alerts to PDF"""
    alerts = EmergencyAlert.get_all()
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#f59e0b'))
    
    # Title
    elements.append(Paragraph('Emergency Alerts Report', title_style))
    elements.append(Spacer(1, 0.3*inch))
    elements.append(Paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Statistics
    total = len(alerts)
    total_safe = sum(len(a.get('people_safe', [])) for a in alerts)
    total_danger = sum(len(a.get('people_danger', [])) for a in alerts)
    total_evacuating = sum(len(a.get('people_evacuating', [])) for a in alerts)
    
    stats_text = f'Total Alerts: {total} | People Safe: {total_safe} | People in Danger: {total_danger} | People Evacuating: {total_evacuating}'
    elements.append(Paragraph(stats_text, styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Table data
    data = [['Type', 'Description', 'Date Created', 'Safe', 'Danger', 'Evacuating']]
    for alert in alerts[:50]:  # Limit to 50 for PDF
        date_created = alert.get('date_created')
        if isinstance(date_created, datetime):
            date_created = date_created.strftime('%Y-%m-%d %H:%M')
        
        description = alert.get('emergency_descriptions', '')[:50]
        if len(alert.get('emergency_descriptions', '')) > 50:
            description += '...'
        
        data.append([
            alert.get('emergency_type', '')[:10],
            description,
            date_created or '',
            str(len(alert.get('people_safe', []))),
            str(len(alert.get('people_danger', []))),
            str(len(alert.get('people_evacuating', [])))
        ])
    
    # Create table
    table = Table(data, colWidths=[0.8*inch, 2.5*inch, 1.3*inch, 0.6*inch, 0.7*inch, 0.9*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f59e0b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'alerts_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf', mimetype='application/pdf')

# ============================================
# SIREN CONTROL API ENDPOINTS
# ============================================

@api.route('/sirens/status', methods=['GET'])
def get_all_sirens_status():
    """Get status of all three sirens"""
    try:
        db = get_realtime_db()
        if not db:
            return jsonify({'error': 'Realtime Database not configured'}), 500
        
        typhoon_status = db.child('emergency_siren_typhoon').get() or False
        flood_status = db.child('emergency_siren_flood').get() or False
        earthquake_status = db.child('emergency_siren_earthquake').get() or False
        
        return jsonify({
            'success': True,
            'sirens': {
                'typhoon': typhoon_status,
                'flood': flood_status,
                'earthquake': earthquake_status
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/sirens/<string:siren_type>/toggle', methods=['POST'])
def toggle_siren(siren_type):
    """Toggle siren status (activate/deactivate)"""
    try:
        # Validate siren type
        valid_types = ['typhoon', 'flood', 'earthquake']
        if siren_type not in valid_types:
            return jsonify({'error': f'Invalid siren type. Must be one of: {", ".join(valid_types)}'}), 400
        
        db = get_realtime_db()
        if not db:
            return jsonify({'error': 'Realtime Database not configured'}), 500
        
        # Get database path
        db_path = f'emergency_siren_{siren_type}'
        
        # Get current status
        current_status = db.child(db_path).get()
        if current_status is None:
            current_status = False
        
        # Toggle the status
        new_status = not current_status
        
        # Update in Realtime Database
        db.child(db_path).set(new_status)
        
        return jsonify({
            'success': True,
            'siren_type': siren_type.upper(),
            'previous_status': current_status,
            'new_status': new_status,
            'action': 'activated' if new_status else 'deactivated'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/sirens/<string:siren_type>/activate', methods=['POST'])
def activate_siren(siren_type):
    """Activate a specific siren"""
    try:
        # Validate siren type
        valid_types = ['typhoon', 'flood', 'earthquake']
        if siren_type not in valid_types:
            return jsonify({'error': f'Invalid siren type. Must be one of: {", ".join(valid_types)}'}), 400
        
        db = get_realtime_db()
        if not db:
            return jsonify({'error': 'Realtime Database not configured'}), 500
        
        # Get database path
        db_path = f'emergency_siren_{siren_type}'
        
        # Set to true (activate)
        db.child(db_path).set(True)
        
        return jsonify({
            'success': True,
            'siren_type': siren_type.upper(),
            'status': True,
            'action': 'activated',
            'message': f'{siren_type.capitalize()} siren has been activated'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/sirens/<string:siren_type>/deactivate', methods=['POST'])
def deactivate_siren(siren_type):
    """Deactivate a specific siren"""
    try:
        # Validate siren type
        valid_types = ['typhoon', 'flood', 'earthquake']
        if siren_type not in valid_types:
            return jsonify({'error': f'Invalid siren type. Must be one of: {", ".join(valid_types)}'}), 400
        
        db = get_realtime_db()
        if not db:
            return jsonify({'error': 'Realtime Database not configured'}), 500
        
        # Get database path
        db_path = f'emergency_siren_{siren_type}'
        
        # Set to false (deactivate)
        db.child(db_path).set(False)
        
        return jsonify({
            'success': True,
            'siren_type': siren_type.upper(),
            'status': False,
            'action': 'deactivated',
            'message': f'{siren_type.capitalize()} siren has been deactivated'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@main.route('/configuration')
def configuration():
    """Configuration page for managing system settings"""
    if not session.get('logged_in'):
        return redirect(url_for('main.admin_login'))
    
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('main.admin_login'))
    
    try:
        db = get_db()
        config_ref = db.collection('configuration').document('emergency_settings')
        config_doc = config_ref.get()
        
        # Default configuration if none exists
        config_data = {
            'emergency_number': '911'
        }
        
        if config_doc.exists:
            saved_config = config_doc.to_dict()
            config_data.update(saved_config)
        
        return render_template('configuration.html', 
                               current_user=current_user, 
                               config=config_data)
    except Exception as e:
        print(f"Configuration error: {e}")
        return render_template('configuration.html', 
                               current_user=current_user, 
                               config={'emergency_number': '911'},
                               error="Failed to load configuration")

@main.route('/configuration/update', methods=['POST'])
def update_configuration():
    """Update configuration settings"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        data = request.get_json()
        emergency_number = data.get('emergency_number', '').strip()
        
        # Validate emergency number
        if not emergency_number:
            return jsonify({'error': 'Emergency number is required'}), 400
        
        if not emergency_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            return jsonify({'error': 'Emergency number must contain only digits, spaces, hyphens, and plus signs'}), 400
        
        # Save to Firestore
        db = get_db()
        config_ref = db.collection('configuration').document('emergency_settings')
        config_ref.set({
            'emergency_number': emergency_number,
            'updated_at': datetime.now(),
            'updated_by': session.get('user_id')
        }, merge=True)
        
        return jsonify({
            'success': True,
            'message': 'Configuration updated successfully',
            'emergency_number': emergency_number
        })
        
    except Exception as e:
        print(f"Configuration update error: {e}")
        return jsonify({'error': 'Failed to update configuration'}), 500
