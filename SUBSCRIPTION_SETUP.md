# Cognitia Subscription System - Setup Guide

This document explains how to set up and use the newly implemented subscription management system.

## Overview

The subscription system enables:
- **Multiple subscription tiers** (Free, Basic, Pro, Enterprise)
- **Rate limiting** (messages/day, audio minutes/day)
- **Feature gates** (custom voices, phone calls, API access, etc.)
- **Usage tracking** for analytics and billing
- **Automatic enforcement** via middleware

---

## 🚀 Quick Start

### 1. Run Database Migration

```bash
# Navigate to your project directory
cd /home/iberu/Documents/cognitia

# Run the migration script
python scripts/migrate_add_subscriptions.py
```

This will:
- ✅ Create all subscription tables
- ✅ Seed 4 default plans (free, basic, pro, enterprise)
- ✅ Assign all existing users to the free tier

### 2. Start the Server

```bash
# The subscription system is automatically enabled
# Just start your entrance server as normal
python -m cognitia.entrance.server
```

---

## 📊 Subscription Tiers

| Feature | **Free** | **Basic** ($9.99/mo) | **Pro** ($24.99/mo) | **Enterprise** |
|---------|----------|----------------------|---------------------|----------------|
| Characters | 3 | 10 | Unlimited | Unlimited |
| Messages/Day | 50 | 500 | 5,000 | Unlimited |
| Audio/Day | 10 min | 60 min | 300 min | Unlimited |
| Voice Clones | 0 | 1 | 5 | Unlimited |
| Context Depth | 10 msgs | 50 msgs | 200 msgs | Unlimited |
| LLM Models | Basic (7B) | Mid (14B) | All (70B+) | Custom |
| TTS Voices | 3 | 10 | All | Custom |
| Phone Calls | ❌ | ❌ | ✅ | ✅ |
| API Access | ❌ | ❌ | ✅ | ✅ |
| Webhooks | ❌ | ❌ | ✅ | ✅ |
| Priority Queue | ❌ | ❌ | ✅ | ✅ |

---

## 🔌 API Endpoints

### Public Endpoints (No Auth Required)

```bash
# Get all subscription plans
GET /api/subscription/plans

Response:
{
  "plans": [
    {
      "id": "uuid",
      "name": "free",
      "display_name": "Free Tier",
      "price_monthly": 0.00,
      "max_characters": 3,
      "max_messages_per_day": 50,
      "max_audio_minutes_per_day": 10,
      ...
    }
  ]
}
```

### Authenticated Endpoints

```bash
# Get current subscription
GET /api/subscription/current
Headers: Authorization: Bearer <token>

Response:
{
  "id": "uuid",
  "plan_name": "free",
  "plan_display_name": "Free Tier",
  "status": "active",
  "limits": {
    "max_characters": 3,
    "max_messages_per_day": 50,
    ...
  },
  "usage": {
    "characters": 2
  },
  "features": {
    "can_use_custom_voices": false,
    ...
  }
}

# Get usage statistics
GET /api/subscription/usage
Headers: Authorization: Bearer <token>

Response:
{
  "usage": {
    "messages": 23,
    "audio_minutes": 5.2,
    "tokens": 15420,
    "date": "2025-01-15"
  },
  "limits": {
    "messages": 50,
    "audio_minutes": 10
  },
  "percentage": {
    "messages": 46.0,
    "audio": 52.0
  },
  "plan": {
    "name": "free",
    "display_name": "Free Tier"
  }
}

# Get monthly usage
GET /api/subscription/usage/monthly/2025/1
Headers: Authorization: Bearer <token>

Response:
{
  "year": 2025,
  "month": 1,
  "total_messages": 450,
  "total_audio_minutes": 85.5,
  "total_tokens": 125000,
  "days_active": 15
}

# Cancel subscription
POST /api/subscription/cancel
Headers: Authorization: Bearer <token>

Response:
{
  "message": "Subscription will be cancelled at the end of the billing period",
  "cancel_at": "2025-02-15T00:00:00"
}

# Reactivate cancelled subscription
POST /api/subscription/reactivate
Headers: Authorization: Bearer <token>
```

---

## 🛡️ Rate Limiting

The middleware automatically checks limits BEFORE processing requests:

### Message Creation

```bash
POST /api/chats/{chat_id}/messages

# If limit exceeded:
HTTP 429 Too Many Requests
{
  "error": "daily_limit_exceeded",
  "message": "You've reached your daily limit of 50 messages.",
  "limit": 50,
  "used": 50,
  "reset_at": "2025-01-16T00:00:00",
  "current_plan": "free",
  "upgrade_url": "/subscription/plans"
}
```

### Character Creation

```bash
POST /api/characters

# If limit exceeded:
HTTP 403 Forbidden
{
  "error": "character_limit_exceeded",
  "message": "You've reached your character limit of 3.",
  "limit": 3,
  "used": 3,
  "current_plan": "free",
  "upgrade_url": "/subscription/plans"
}
```

---

## 📈 Usage Tracking

Usage is tracked automatically for:

1. **Messages** - Every message sent increments the counter
2. **Audio Generation** - Duration tracked when TTS is used
3. **Voice Cloning** - Tracked when RVC models are uploaded

Example tracking call (already integrated):

```python
from cognitia.entrance.usage_tracker import usage_tracker

# Track a message (done automatically in create_message endpoint)
await usage_tracker.record_message(
    user_id=user_id,
    chat_id=chat_id,
    character_id=character_id,
    tokens=1500  # Optional: LLM tokens used
)

# Track audio generation
await usage_tracker.record_audio(
    user_id=user_id,
    duration_seconds=45.5,
    character_id=character_id,
    chat_id=chat_id
)

# Track voice clone upload
await usage_tracker.record_voice_clone(
    user_id=user_id,
    character_id=character_id,
    model_size_mb=15.2
)
```

---

## 🎨 Frontend Integration

### Update Web UI to Show Usage

Add to your `/web/js/api.js`:

```javascript
async getSubscription() {
    return this.request('/api/subscription/current');
}

async getUsage() {
    return this.request('/api/subscription/usage');
}

async getPlans() {
    return this.request('/api/subscription/plans');
}
```

### Display Usage Widget

```javascript
// In your app.js
async displayUsage() {
    const usage = await api.getUsage();

    // Show progress bar for messages
    const messagePercent = usage.percentage.messages;
    document.getElementById('message-progress').style.width = `${messagePercent}%`;
    document.getElementById('message-text').textContent =
        `${usage.usage.messages} / ${usage.limits.messages} messages today`;

    // Show warning if > 80%
    if (messagePercent > 80) {
        showUpgradePrompt();
    }
}
```

### Handle Rate Limit Errors

```javascript
// In your API client
async request(endpoint, options = {}) {
    const response = await fetch(endpoint, options);

    if (response.status === 429) {
        const error = await response.json();

        // Show paywall modal
        showPaywall({
            title: "Daily Limit Reached",
            message: error.message,
            upgradeUrl: error.upgrade_url,
            resetAt: error.reset_at
        });

        throw new Error(error.message);
    }

    return response.json();
}
```

---

## 🔧 Database Schema

### Main Tables

**subscription_plans**
- Defines available tiers (free, basic, pro, enterprise)
- Contains limits and feature flags

**user_subscriptions**
- Links users to their current plan
- Tracks billing period and status

**daily_usage_cache**
- Fast lookup for rate limiting
- Resets daily at midnight

**usage_records**
- Detailed audit log of all usage
- Used for analytics and billing

**payment_transactions**
- Records all payments (for future Stripe integration)

---

## 🔐 Middleware Flow

```
1. Request arrives
   ↓
2. SubscriptionMiddleware checks route
   ↓
3. If public route → skip checks
   ↓
4. If authenticated route:
   - Check message limit (for POST /messages)
   - Check character limit (for POST /characters)
   - Check audio limit (for audio endpoints)
   ↓
5. If limit exceeded → HTTP 429 or 403
   ↓
6. If OK → proceed to route handler
   ↓
7. Route handler processes request
   ↓
8. UsageTracker records usage (async)
   ↓
9. Response returned
```

---

## 🎯 Next Steps

### Immediate

1. ✅ Database migration complete
2. ✅ Middleware active
3. ✅ Usage tracking implemented
4. ⏳ Add usage widgets to frontend
5. ⏳ Add paywall modals

### Future Enhancements

1. **Stripe Integration**
   - Create `/api/subscription/checkout` endpoint
   - Add webhook handler for payment events
   - Implement automatic plan upgrades

2. **Admin Dashboard**
   - View all users and their subscriptions
   - Manually adjust user plans
   - View platform analytics

3. **Analytics**
   - Track conversion rates
   - Monitor MRR (Monthly Recurring Revenue)
   - Identify popular features

4. **Referral Program**
   - Generate referral codes for users
   - Track referrals and reward both parties

---

## 📝 Configuration

### Environment Variables

```bash
# Already using DATABASE_URL
DATABASE_URL=postgresql+asyncpg://user:pass@host/db

# Future: Add for Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### Modifying Plans

To adjust subscription limits:

```sql
-- Update free tier limits
UPDATE subscription_plans
SET max_messages_per_day = 100,
    max_audio_minutes_per_day = 20
WHERE name = 'free';

-- Add new feature flag
ALTER TABLE subscription_plans
ADD COLUMN can_use_video_chat BOOLEAN DEFAULT false;

UPDATE subscription_plans
SET can_use_video_chat = true
WHERE name IN ('pro', 'enterprise');
```

---

## 🐛 Troubleshooting

### "No subscription found" error

All users should have a free subscription. If a user doesn't:

```python
# Add free subscription manually
python scripts/migrate_add_subscriptions.py  # Re-run migration
```

### Middleware not working

Check logs for:
```
✓ Subscription system enabled
```

If missing, ensure server.py has:
```python
app.add_middleware(SubscriptionMiddleware)
app.include_router(subscription_module.router)
```

### Usage not tracking

Check database:
```sql
SELECT * FROM daily_usage_cache
WHERE user_id = 'your-user-id'
AND date = CURRENT_DATE;
```

If empty, check logs for errors in `usage_tracker.record_message()`.

---

## 📞 Support

For questions or issues:
1. Check logs: `tail -f cognitia-entrance.log`
2. Verify database tables exist: `\dt subscription_*` in psql
3. Test endpoints with curl:
   ```bash
   curl http://localhost:8000/api/subscription/plans
   ```

---

**Built with ❤️ for Cognitia**
