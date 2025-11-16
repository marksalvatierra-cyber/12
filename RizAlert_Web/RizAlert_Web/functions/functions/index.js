/**
 * Import function triggers from their respective submodules:
 *
 * const {onCall} = require("firebase-functions/v2/https");
 * const {onDocumentWritten} = require("firebase-functions/v2/firestore");
 *
 * See a full list of supported triggers at https://firebase.google.com/docs/functions
 */

const {setGlobalOptions} = require("firebase-functions");
const {onRequest} = require("firebase-functions/https");
const {onValueWritten} = require("firebase-functions/v2/database");
const logger = require("firebase-functions/logger");
const admin = require("firebase-admin");

// Initialize Firebase Admin with Realtime Database URL
admin.initializeApp({
  databaseURL: "https://rizalert-ca105-default-rtdb.asia-southeast1.firebasedatabase.app",
});

// For cost control, you can set the maximum number of containers that can be
// running at the same time. This helps mitigate the impact of unexpected
// traffic spikes by instead downgrading performance. This limit is a
// per-function limit. You can override the limit for each function using the
// `maxInstances` option in the function's options, e.g.
// `onRequest({ maxInstances: 5 }, (req, res) => { ... })`.
// NOTE: setGlobalOptions does not apply to functions using the v1 API. V1
// functions should each use functions.runWith({ maxInstances: 10 }) instead.
// In the v1 API, each function can only serve one request per container, so
// this will be the maximum concurrent request count.
setGlobalOptions({ maxInstances: 10 });

// ============================================
// TYPHOON SIREN FUNCTIONS
// ============================================

// Listen for changes to emergency_siren_typhoon in Realtime Database
exports.onTyphoonSirenChange = onValueWritten(
  {
    ref: "/emergency_siren_typhoon",
    instance: "rizalert-ca105-default-rtdb",
    region: "asia-southeast1",
  },
  async (event) => {
    const beforeData = event.data.before.val();
    const afterData = event.data.after.val();

    logger.info("🌪️ Typhoon Siren Change Detected", {
      before: beforeData,
      after: afterData,
    });

    if (afterData === true) {
      logger.warn("🚨 TYPHOON SIREN ACTIVATED! 🌪️");

      try {
        // Create an audit log entry
        await admin.firestore().collection("siren_activations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "TYPHOON",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Typhoon siren activation logged successfully");

        // Send FCM notification to all Android devices
        try {
          const message = {
            notification: {
              title: "🌪️ TYPHOON ALERT",
              body: `Emergency typhoon alert, seek shelter immediately, Stay safe.`,
            },
            data: {
              type: "TYPHOON_SIREN",
              siren_type: "TYPHOON",
              timestamp: new Date().toISOString(),
              priority: "HIGH",
            },
            topic: "emergency_alerts", // Send to all devices subscribed to emergency_alerts topic
            android: {
              priority: "high",
              notification: {
                channelId: "emergency_channel_siren",
                priority: "max",
                defaultSound: true,
                defaultVibrateTimings: true,
                color: "#dc2626", // Red color
              },
            },
          };

          const response = await admin.messaging().send(message);
          logger.info("✅ FCM notification sent successfully for Typhoon siren", {
            messageId: response,
          });
        } catch (fcmError) {
          logger.error("❌ Error sending FCM notification for Typhoon:", fcmError);
        }
      } catch (error) {
        logger.error("Error processing typhoon siren activation:", error);
      }
    } else if (afterData === false && beforeData === true) {
      logger.info("Typhoon siren deactivated");

      try {
        await admin.firestore().collection("siren_deactivations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "TYPHOON",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Typhoon siren deactivation logged successfully");
      } catch (error) {
        logger.error("Error processing typhoon siren deactivation:", error);
      }
    }

    return null;
  }
);

// HTTP endpoint to get typhoon siren status
exports.getTyphoonSirenStatus = onRequest(async (request, response) => {
  try {
    const snapshot = await admin
      .database()
      .ref("/emergency_siren_typhoon")
      .once("value");
    const sirenStatus = snapshot.val();

    response.json({
      success: true,
      siren_type: "TYPHOON",
      status: sirenStatus,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error getting typhoon siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to set typhoon siren status
exports.setTyphoonSiren = onRequest(async (request, response) => {
  try {
    const { status } = request.body;

    if (typeof status !== "boolean") {
      response.status(400).json({
        success: false,
        error: "Status must be a boolean value",
      });
      return;
    }

    await admin.database().ref("/emergency_siren_typhoon").set(status);

    logger.info(`Typhoon siren manually set to: ${status}`);

    response.json({
      success: true,
      siren_type: "TYPHOON",
      status: status,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error setting typhoon siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// ============================================
// FLOOD SIREN FUNCTIONS
// ============================================

// Listen for changes to emergency_siren_flood in Realtime Database
exports.onFloodSirenChange = onValueWritten(
  {
    ref: "/emergency_siren_flood",
    instance: "rizalert-ca105-default-rtdb",
    region: "asia-southeast1",
  },
  async (event) => {
    const beforeData = event.data.before.val();
    const afterData = event.data.after.val();

    logger.info("💧 Flood Siren Change Detected", {
      before: beforeData,
      after: afterData,
    });

    if (afterData === true) {
      logger.warn("🚨 FLOOD SIREN ACTIVATED! �");

      try {
        // Create an audit log entry
        await admin.firestore().collection("siren_activations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "FLOOD",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Flood siren activation logged successfully");

        // Send FCM notification to all Android devices
        try {
          const message = {
            notification: {
              title: "💧 FLOOD WARNING",
              body: `Emergency flood warning, Move to higher ground immediately.`,
            },
            data: {
              type: "FLOOD_SIREN",
              siren_type: "FLOOD",
              timestamp: new Date().toISOString(),
              priority: "HIGH",
            },
            topic: "emergency_alerts",
            android: {
              priority: "high",
              notification: {
                channelId: "emergency_channel_siren",
                priority: "max",
                defaultSound: true,
                defaultVibrateTimings: true,
                color: "#3b82f6", // Blue color
              },
            },
          };

          const response = await admin.messaging().send(message);
          logger.info("✅ FCM notification sent successfully for Flood siren", {
            messageId: response,
          });
        } catch (fcmError) {
          logger.error("❌ Error sending FCM notification for Flood:", fcmError);
        }
      } catch (error) {
        logger.error("Error processing flood siren activation:", error);
      }
    } else if (afterData === false && beforeData === true) {
      logger.info("Flood siren deactivated");

      try {
        await admin.firestore().collection("siren_deactivations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "FLOOD",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Flood siren deactivation logged successfully");
      } catch (error) {
        logger.error("Error processing flood siren deactivation:", error);
      }
    }

    return null;
  }
);

// HTTP endpoint to get flood siren status
exports.getFloodSirenStatus = onRequest(async (request, response) => {
  try {
    const snapshot = await admin
      .database()
      .ref("/emergency_siren_flood")
      .once("value");
    const sirenStatus = snapshot.val();

    response.json({
      success: true,
      siren_type: "FLOOD",
      status: sirenStatus,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error getting flood siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to set flood siren status
exports.setFloodSiren = onRequest(async (request, response) => {
  try {
    const { status } = request.body;

    if (typeof status !== "boolean") {
      response.status(400).json({
        success: false,
        error: "Status must be a boolean value",
      });
      return;
    }

    await admin.database().ref("/emergency_siren_flood").set(status);

    logger.info(`Flood siren manually set to: ${status}`);

    response.json({
      success: true,
      siren_type: "FLOOD",
      status: status,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error setting flood siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// ============================================
// EARTHQUAKE SIREN FUNCTIONS
// ============================================

// Listen for changes to emergency_siren_earthquake in Realtime Database
exports.onEarthquakeSirenChange = onValueWritten(
  {
    ref: "/emergency_siren_earthquake",
    instance: "rizalert-ca105-default-rtdb",
    region: "asia-southeast1",
  },
  async (event) => {
    const beforeData = event.data.before.val();
    const afterData = event.data.after.val();

    logger.info("🏚️ Earthquake Siren Change Detected", {
      before: beforeData,
      after: afterData,
    });

    if (afterData === true) {
      logger.warn("🚨 EARTHQUAKE SIREN ACTIVATED! 🏚️");

      try {
        // Create an audit log entry
        await admin.firestore().collection("siren_activations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "EARTHQUAKE",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Earthquake siren activation logged successfully");

        // Send FCM notification to all Android devices
        try {
          const message = {
            notification: {
              title: "🏚️ EARTHQUAKE ALERT",
              body: `Emergency earthquake alert. DROP, COVER, and HOLD ON!`,
            },
            data: {
              type: "EARTHQUAKE_SIREN",
              siren_type: "EARTHQUAKE",
              timestamp: new Date().toISOString(),
              priority: "HIGH",
            },
            topic: "emergency_alerts",
            android: {
              priority: "high",
              notification: {
                channelId: "emergency_channel_siren",
                priority: "max",
                defaultSound: true,
                defaultVibrateTimings: true,
                color: "#f59e0b", // Yellow/Warning color
              },
            },
          };

          const response = await admin.messaging().send(message);
          logger.info("✅ FCM notification sent successfully for Earthquake siren", {
            messageId: response,
          });
        } catch (fcmError) {
          logger.error("❌ Error sending FCM notification for Earthquake:", fcmError);
        }
      } catch (error) {
        logger.error("Error processing earthquake siren activation:", error);
      }
    } else if (afterData === false && beforeData === true) {
      logger.info("Earthquake siren deactivated");

      try {
        await admin.firestore().collection("siren_deactivations").add({
          timestamp: admin.firestore.FieldValue.serverTimestamp(),
          siren_type: "EARTHQUAKE",
          triggered_by: "realtime_database",
        });

        logger.info("✅ Earthquake siren deactivation logged successfully");
      } catch (error) {
        logger.error("Error processing earthquake siren deactivation:", error);
      }
    }

    return null;
  }
);

// HTTP endpoint to get earthquake siren status
exports.getEarthquakeSirenStatus = onRequest(async (request, response) => {
  try {
    const snapshot = await admin
      .database()
      .ref("/emergency_siren_earthquake")
      .once("value");
    const sirenStatus = snapshot.val();

    response.json({
      success: true,
      siren_type: "EARTHQUAKE",
      status: sirenStatus,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error getting earthquake siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to set earthquake siren status
exports.setEarthquakeSiren = onRequest(async (request, response) => {
  try {
    const { status } = request.body;

    if (typeof status !== "boolean") {
      response.status(400).json({
        success: false,
        error: "Status must be a boolean value",
      });
      return;
    }

    await admin.database().ref("/emergency_siren_earthquake").set(status);

    logger.info(`Earthquake siren manually set to: ${status}`);

    response.json({
      success: true,
      siren_type: "EARTHQUAKE",
      status: status,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error setting earthquake siren status:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// ============================================
// UTILITY FUNCTION - Get All Siren Status
// ============================================

// HTTP endpoint to get all siren statuses at once
exports.getAllSirenStatus = onRequest(async (request, response) => {
  try {
    const typhoonSnapshot = await admin
      .database()
      .ref("/emergency_siren_typhoon")
      .once("value");
    const floodSnapshot = await admin
      .database()
      .ref("/emergency_siren_flood")
      .once("value");
    const earthquakeSnapshot = await admin
      .database()
      .ref("/emergency_siren_earthquake")
      .once("value");

    response.json({
      success: true,
      sirens: {
        typhoon: typhoonSnapshot.val() || false,
        flood: floodSnapshot.val() || false,
        earthquake: earthquakeSnapshot.val() || false,
      },
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    logger.error("Error getting all siren statuses:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// ============================================
// FCM NOTIFICATION UTILITY FUNCTIONS
// ============================================

// HTTP endpoint to send custom FCM notification
exports.sendCustomNotification = onRequest(async (request, response) => {
  try {
    const { title, body, type, topic, tokens } = request.body;

    if (!title || !body) {
      response.status(400).json({
        success: false,
        error: "Title and body are required",
      });
      return;
    }

    const message = {
      notification: {
        title: title,
        body: body,
      },
      data: {
        type: type || "CUSTOM",
        timestamp: new Date().toISOString(),
      },
      android: {
        priority: "high",
        notification: {
          channelId: "emergency_channel_siren",
          priority: "max",
          defaultSound: true,
          defaultVibrateTimings: true,
        },
      },
    };

    let result;
    if (tokens && Array.isArray(tokens) && tokens.length > 0) {
      // Send to specific devices
      const multicastMessage = {
        ...message,
        tokens: tokens,
      };
      result = await admin.messaging().sendEachForMulticast(multicastMessage);
      logger.info(`✅ Sent to ${result.successCount} devices, ${result.failureCount} failed`);
    } else {
      // Send to topic
      message.topic = topic || "emergency_alerts";
      result = await admin.messaging().send(message);
      logger.info(`✅ Sent to topic: ${topic || "emergency_alerts"}`);
    }

    response.json({
      success: true,
      result: result,
      message: "Notification sent successfully",
    });
  } catch (error) {
    logger.error("Error sending custom notification:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to subscribe device token to emergency alerts topic
exports.subscribeToEmergencyAlerts = onRequest(async (request, response) => {
  try {
    const { token, tokens } = request.body;

    if (!token && (!tokens || !Array.isArray(tokens))) {
      response.status(400).json({
        success: false,
        error: "Token or tokens array is required",
      });
      return;
    }

    const tokensToSubscribe = token ? [token] : tokens;
    const result = await admin
      .messaging()
      .subscribeToTopic(tokensToSubscribe, "emergency_alerts");

    logger.info(`✅ Subscribed ${tokensToSubscribe.length} devices to emergency_alerts topic`);

    response.json({
      success: true,
      subscribed: result.successCount,
      failed: result.failureCount,
      message: "Devices subscribed to emergency alerts successfully",
    });
  } catch (error) {
    logger.error("Error subscribing to topic:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to unsubscribe device token from emergency alerts topic
exports.unsubscribeFromEmergencyAlerts = onRequest(async (request, response) => {
  try {
    const { token, tokens } = request.body;

    if (!token && (!tokens || !Array.isArray(tokens))) {
      response.status(400).json({
        success: false,
        error: "Token or tokens array is required",
      });
      return;
    }

    const tokensToUnsubscribe = token ? [token] : tokens;
    const result = await admin
      .messaging()
      .unsubscribeFromTopic(tokensToUnsubscribe, "emergency_alerts");

    logger.info(`✅ Unsubscribed ${tokensToUnsubscribe.length} devices from emergency_alerts topic`);

    response.json({
      success: true,
      unsubscribed: result.successCount,
      failed: result.failureCount,
      message: "Devices unsubscribed from emergency alerts successfully",
    });
  } catch (error) {
    logger.error("Error unsubscribing from topic:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// HTTP endpoint to send notification to specific user by ID
exports.sendNotificationToUser = onRequest(async (request, response) => {
  try {
    const { userId, title, body, type } = request.body;

    if (!userId || !title || !body) {
      response.status(400).json({
        success: false,
        error: "userId, title, and body are required",
      });
      return;
    }

    // Get user's FCM token from Firestore
    const userDoc = await admin.firestore().collection("users").doc(userId).get();

    if (!userDoc.exists) {
      response.status(404).json({
        success: false,
        error: "User not found",
      });
      return;
    }

    const userData = userDoc.data();
    const fcmToken = userData.fcmToken || userData.fcm_token;

    if (!fcmToken) {
      response.status(400).json({
        success: false,
        error: "User does not have an FCM token registered",
      });
      return;
    }

    const message = {
      notification: {
        title: title,
        body: body,
      },
      data: {
        type: type || "USER_NOTIFICATION",
        userId: userId,
        timestamp: new Date().toISOString(),
      },
      token: fcmToken,
      android: {
        priority: "high",
        notification: {
          channelId: "emergency_channel_siren",
          priority: "max",
          defaultSound: true,
          defaultVibrateTimings: true,
        },
      },
    };

    const result = await admin.messaging().send(message);
    logger.info(`✅ Notification sent to user ${userId}`, { messageId: result });

    response.json({
      success: true,
      messageId: result,
      message: "Notification sent to user successfully",
    });
  } catch (error) {
    logger.error("Error sending notification to user:", error);
    response.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

// Create and deploy your first functions
// https://firebase.google.com/docs/functions/get-started

// exports.helloWorld = onRequest((request, response) => {
//   logger.info("Hello logs!", {structuredData: true});
//   response.send("Hello from Firebase!");
// });
