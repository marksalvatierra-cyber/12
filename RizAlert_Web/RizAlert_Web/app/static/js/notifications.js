async function showNotifications() {
    try {
        const res = await fetch('/api/notifications');
        if (!res.ok) throw new Error('Failed to load notifications');
        const data = await res.json();

        // Mark notifications as read when modal is opened
        try {
            await fetch('/api/notifications/mark-read', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            // Update the counter immediately after marking as read
            setTimeout(updateCounters, 100);
        } catch (err) {
            console.error('Failed to mark notifications as read:', err);
        }

        // Build modal
        const modal = document.createElement('dialog');
        modal.className = 'modal';
        modal.id = 'notificationsModal';

        let content = `
            <div class="modal-box w-11/12 max-w-3xl">
                <h3 class="font-bold text-lg mb-4"><i class="fas fa-bell text-primary mr-2"></i>Notifications</h3>
                <div class="space-y-3 overflow-y-auto" style="max-height: 60vh;">
        `;

        if (!data || data.length === 0) {
            content += '<div class="text-center opacity-60">No notifications</div>';
        } else {
            data.forEach(n => {
                const time = n.timestamp ? new Date(n.timestamp).toLocaleString() : '';
                if (n.type === 'alert') {
                    content += `
                        <div class="card bg-base-200 p-3">
                            <div class="flex items-center justify-between">
                                <div>
                                    <div class="font-semibold">${n.alert_type || 'ALERT'}</div>
                                    <div class="text-sm opacity-70">${n.message || ''}</div>
                                    <div class="text-xs opacity-50 mt-1">${time}</div>
                                </div>
                                <div class="text-right">
                                    <div class="badge ${n.list === 'people_safe' ? 'badge-success' : n.list === 'people_danger' ? 'badge-error' : 'badge-warning'}">${n.list_label}</div>
                                </div>
                            </div>
                        </div>
                    `;
                } else if (n.type === 'responder') {
                    content += `
                        <div class="card bg-base-200 p-3">
                            <div class="flex items-center justify-between">
                                <div>
                                    <div class="font-semibold">Responder Update: ${n.responder_name || n.responder_id}</div>
                                    <div class="text-sm opacity-70">${n.emergency_type || ''} — ${n.status || ''} ${n.arrived ? '(Arrived)' : ''}</div>
                                    <div class="text-xs opacity-50 mt-1">${time}</div>
                                </div>
                                <div class="text-right">
                                    <button class="btn btn-xs btn-ghost" onclick="viewEmergencyFromNotification('${n.emergency_id}')">View</button>
                                </div>
                            </div>
                        </div>
                    `;
                }
            });
        }

        content += `
                </div>
                <div class="modal-action">
                    <button class="btn" onclick="document.getElementById('notificationsModal').close(); document.getElementById('notificationsModal').remove();">Close</button>
                </div>
            </div>
            <form method="dialog" class="modal-backdrop"><button>close</button></form>
        `;

        modal.innerHTML = content;
        document.body.appendChild(modal);
        modal.showModal();
    } catch (err) {
        console.error(err);
        alert('Failed to load notifications');
    }
}

// Function to update notification and emergency counters
async function updateCounters() {
    try {
        // Update notification counter
        const notifRes = await fetch('/api/notifications/count');
        if (notifRes.ok) {
            const notifData = await notifRes.json();
            const notifCount = notifData.count || 0;
            updateNotificationCounter(notifCount);
        }

        // Update emergency counter
        const emergRes = await fetch('/api/emergencies/count');
        if (emergRes.ok) {
            const emergData = await emergRes.json();
            const emergCount = emergData.count || 0;
            updateEmergencyCounter(emergCount);
        }
    } catch (err) {
        console.error('Failed to update counters:', err);
    }
}

// Function to update notification counter in sidebar
function updateNotificationCounter(count) {
    const notificationLinks = document.querySelectorAll('a[onclick="showNotifications()"]');
    notificationLinks.forEach(link => {
        // Remove existing badge
        const existingBadge = link.querySelector('.notification-badge');
        if (existingBadge) {
            existingBadge.remove();
        }

        // Add new badge if count > 0
        if (count > 0) {
            const badge = document.createElement('span');
            badge.className = 'notification-badge badge badge-error badge-sm ml-auto';
            badge.textContent = count > 99 ? '99+' : count;
            link.appendChild(badge);
        }
    });
}

// Function to update emergency counter in sidebar
function updateEmergencyCounter(count) {
    const emergencyLinks = document.querySelectorAll('a[href="/emergencies"]');
    emergencyLinks.forEach(link => {
        // Remove existing badge
        const existingBadge = link.querySelector('.emergency-badge');
        if (existingBadge) {
            existingBadge.remove();
        }

        // Add new badge if count > 0
        if (count > 0) {
            const badge = document.createElement('span');
            badge.className = 'emergency-badge badge badge-warning badge-sm ml-auto';
            badge.textContent = count > 99 ? '99+' : count;
            link.appendChild(badge);
        }
    });
}

// Initialize counters when page loads
document.addEventListener('DOMContentLoaded', function() {
    updateCounters();
    
    // Update counters every 30 seconds
    setInterval(updateCounters, 30000);
});

// Function to view emergency from notification and mark as viewed
async function viewEmergencyFromNotification(emergencyId) {
    try {
        // Mark emergency as viewed
        await fetch('/api/emergencies/mark-viewed', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ emergency_id: emergencyId })
        });
        
        // Update counters
        setTimeout(updateCounters, 100);
        
        // Close notifications modal
        const modal = document.getElementById('notificationsModal');
        if (modal) {
            modal.close();
            modal.remove();
        }
        
        // Navigate to emergencies page
        window.location.href = '/emergencies';
    } catch (err) {
        console.error('Failed to mark emergency as viewed:', err);
        // Still navigate even if marking failed
        window.location.href = '/emergencies';
    }
}

// Mark emergency as viewed when opening emergency details (for emergencies page)
async function markEmergencyViewed(emergencyId) {
    try {
        await fetch('/api/emergencies/mark-viewed', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ emergency_id: emergencyId })
        });
        
        // Update counters
        setTimeout(updateCounters, 100);
    } catch (err) {
        console.error('Failed to mark emergency as viewed:', err);
    }
}
