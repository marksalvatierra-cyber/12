# RizAlert Firebase Cloud Functions

This directory contains Firebase Cloud Functions for the RizAlert emergency management system.

## Functions

### 1. `onEmergencySirenChange`
**Trigger**: Realtime Database `/emergency_siren` value changes  
**Purpose**: Monitors the emergency siren status and takes action when activated

**Behavior**:
- Triggers when `/emergency_siren` value changes in Realtime Database
- When `emergency_siren` becomes `true`:
  - Logs warning with 🚨 emoji
  - Fetches all active emergencies from Firestore
  - Creates an audit log entry in `siren_activations` collection
  - Ready to integrate with notification systems, IoT devices, SMS alerts
- When `emergency_siren` becomes `false`:
  - Logs deactivation
  - Creates audit entry in `siren_deactivations` collection

**Data Logged**:
```javascript
// siren_activations collection
{
  timestamp: ServerTimestamp,
  active_emergencies_count: Number,
  active_emergencies: [{
    id: String,
    case_type: String,
    created_at: Timestamp
  }],
  triggered_by: "realtime_database"
}
```

### 2. `getEmergencySirenStatus` (HTTP Endpoint)
**URL**: `https://<region>-<project-id>.cloudfunctions.net/getEmergencySirenStatus`  
**Method**: GET  
**Purpose**: Check current emergency siren status

**Response**:
```json
{
  "success": true,
  "emergency_siren": true,
  "timestamp": "2025-10-27T02:30:00.000Z"
}
```

### 3. `setEmergencySiren` (HTTP Endpoint)
**URL**: `https://<region>-<project-id>.cloudfunctions.net/setEmergencySiren`  
**Method**: POST  
**Purpose**: Manually set emergency siren status

**Request Body**:
```json
{
  "status": true
}
```

**Response**:
```json
{
  "success": true,
  "emergency_siren": true,
  "timestamp": "2025-10-27T02:30:00.000Z"
}
```

## Setup

### Prerequisites
- Firebase CLI installed: `npm install -g firebase-tools`
- Node.js 22 (specified in package.json)
- Firebase project configured

### Install Dependencies
```bash
cd functions/functions
npm install
```

## Deployment

### Deploy All Functions
```bash
firebase deploy --only functions
```

### Deploy Specific Function
```bash
firebase deploy --only functions:onEmergencySirenChange
firebase deploy --only functions:getEmergencySirenStatus
firebase deploy --only functions:setEmergencySiren
```

## Local Testing

### Start Emulator
```bash
cd functions/functions
npm run serve
```

### Test Realtime Database Trigger
1. Start Firebase emulator
2. Open Realtime Database in emulator UI
3. Set `/emergency_siren` to `true`
4. Check function logs in emulator

### Test HTTP Endpoints
```bash
# Get status
curl http://localhost:5001/<project-id>/us-central1/getEmergencySirenStatus

# Set status
curl -X POST http://localhost:5001/<project-id>/us-central1/setEmergencySiren \
  -H "Content-Type: application/json" \
  -d '{"status": true}'
```

## Monitoring

### View Logs
```bash
# Real-time logs
firebase functions:log

# Specific function logs
firebase functions:log --only onEmergencySirenChange
```

### Firebase Console
Visit: https://console.firebase.google.com/project/<project-id>/functions

## Integration with RizAlert Flask App

### Set Siren Status from Python
```python
from app.firebase_config import get_realtime_db

# Activate siren
realtime_db = get_realtime_db()
realtime_db.child('emergency_siren').set(True)

# Deactivate siren
realtime_db.child('emergency_siren').set(False)
```

### Check Siren Activations
```python
from app.firebase_config import db

# Get recent activations
activations = db.collection('siren_activations').order_by('timestamp', direction='DESCENDING').limit(10).get()

for activation in activations:
    data = activation.to_dict()
    print(f"Activated at: {data['timestamp']}")
    print(f"Active emergencies: {data['active_emergencies_count']}")
```

## Future Enhancements

- [ ] Send push notifications to all users when siren activates
- [ ] Trigger physical IoT siren devices via MQTT/HTTP
- [ ] Send SMS alerts to emergency contacts
- [ ] Integration with third-party emergency services APIs
- [ ] Automated emergency response workflows
- [ ] Real-time analytics and reporting

## Environment Variables

If needed, set environment variables:
```bash
firebase functions:config:set notification.api_key="your-key"
```

Access in code:
```javascript
const config = functions.config();
const apiKey = config.notification.api_key;
```

## Troubleshooting

### Function not deploying
- Check Node.js version: `node --version` (should be 22)
- Verify Firebase project: `firebase use`
- Check IAM permissions in Firebase Console

### Function not triggering
- Verify Realtime Database rules allow writes
- Check function logs: `firebase functions:log`
- Test with emulator first

### Memory/timeout issues
- Increase timeout in function options:
  ```javascript
  exports.myFunction = onValueWritten({
    ref: "/path",
    timeoutSeconds: 540,
    memory: "1GiB"
  }, handler);
  ```

## Cost Considerations

- Realtime Database triggers: Free tier includes 2M invocations/month
- HTTP functions: Charged per invocation after free tier
- Monitor usage in Firebase Console > Usage and Billing

## Support

For issues or questions:
- Firebase Functions Docs: https://firebase.google.com/docs/functions
- RizAlert GitHub: [Your repo URL]
