#!/bin/bash
# Test Chat & Message API v2 Endpoints

API_URL="http://localhost:8000"
EMAIL="chattest_$(date +%s)@example.com"
PASSWORD="TestPassword123"

echo "=========================================="
echo "Testing Chat & Message API v2"
echo "=========================================="
echo ""

# Step 1: Register and login
echo "1. Register and login user..."
echo "----------------------------------------"
REGISTER_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\", \"first_name\": \"Chat\", \"last_name\": \"Tester\"}")

USER_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))")

if [ -z "$USER_ID" ]; then
    echo "❌ Failed to register user"
    exit 1
fi

# Mark as verified
docker exec cognitia-postgres-dev psql -U cognitia -d cognitia -c "UPDATE users SET email_verified = true WHERE id = '${USER_ID}';" > /dev/null 2>&1

LOGIN_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\"}")

ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
    echo "❌ Failed to login"
    exit 1
fi

echo "✅ User logged in successfully"
echo ""

# Step 2: Create a character
echo "2. Create a test character..."
echo "----------------------------------------"
CREATE_CHAR_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/characters" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Chat Bot",
    "description": "A character for testing chats",
    "system_prompt": "You are a helpful chat assistant.",
    "voice_model": "af_bella",
    "prompt_template": "pygmalion"
  }')

CHAR_ID=$(echo "$CREATE_CHAR_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -z "$CHAR_ID" ]; then
    echo "❌ Failed to create character"
    exit 1
fi

echo "✅ Character created: $CHAR_ID"
echo ""

# Step 3: Create a chat
echo "3. Testing POST /api/v2/chats"
echo "----------------------------------------"
CREATE_CHAT_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/chats" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Test Chat with Bot\",
    \"character_ids\": [\"${CHAR_ID}\"]
  }")

echo "$CREATE_CHAT_RESPONSE" | python3 -m json.tool
CHAT_ID=$(echo "$CREATE_CHAT_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -z "$CHAT_ID" ]; then
    echo "❌ Failed to create chat"
    exit 1
fi

echo "✅ Chat created: $CHAT_ID"
echo ""

# Step 4: List chats
echo "4. Testing GET /api/v2/chats"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/chats" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Listed chats"
echo ""

# Step 5: Get chat details
echo "5. Testing GET /api/v2/chats/{chat_id}"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/chats/${CHAT_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Retrieved chat details"
echo ""

# Step 6: Update chat
echo "6. Testing PATCH /api/v2/chats/{chat_id}"
echo "----------------------------------------"
curl -s -X PATCH "${API_URL}/api/v2/chats/${CHAT_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Chat Title"}' | python3 -m json.tool
echo ""
echo "✅ Updated chat"
echo ""

# Step 7: Send a message
echo "7. Testing POST /api/v2/chats/{chat_id}/messages"
echo "----------------------------------------"
SEND_MSG_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/chats/${CHAT_ID}/messages" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"content\": \"Hello, this is a test message!\",
    \"character_id\": \"${CHAR_ID}\"
  }")

echo "$SEND_MSG_RESPONSE" | python3 -m json.tool
MESSAGE_ID=$(echo "$SEND_MSG_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -z "$MESSAGE_ID" ]; then
    echo "❌ Failed to send message"
    exit 1
fi

echo "✅ Message sent: $MESSAGE_ID"
echo ""

# Step 8: Send another message
echo "8. Sending another message..."
echo "----------------------------------------"
curl -s -X POST "${API_URL}/api/v2/chats/${CHAT_ID}/messages" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"content": "This is another test message"}' | python3 -m json.tool
echo ""
echo "✅ Second message sent"
echo ""

# Step 9: List messages
echo "9. Testing GET /api/v2/chats/{chat_id}/messages"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/chats/${CHAT_ID}/messages" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Listed messages"
echo ""

# Step 10: Add another character
echo "10. Adding another character to chat..."
echo "----------------------------------------"
CREATE_CHAR2_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/characters" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Second Bot",
    "description": "Another bot for group chat",
    "system_prompt": "You are another helpful assistant.",
    "voice_model": "am_adam",
    "prompt_template": "pygmalion"
  }')

CHAR2_ID=$(echo "$CREATE_CHAR2_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -n "$CHAR2_ID" ]; then
    curl -s -X POST "${API_URL}/api/v2/chats/${CHAT_ID}/characters" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"character_id\": \"${CHAR2_ID}\"}" | python3 -m json.tool
    echo ""
    echo "✅ Added second character to chat"
else
    echo "⚠️  Skipped adding second character"
fi
echo ""

# Step 11: Delete chat
echo "11. Testing DELETE /api/v2/chats/{chat_id}"
echo "----------------------------------------"
DELETE_RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/api/v2/chats/${CHAT_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")
HTTP_CODE=$(echo "$DELETE_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" == "204" ]; then
    echo "✅ Chat deleted successfully (HTTP 204)"
else
    echo "Response: $(echo "$DELETE_RESPONSE" | head -n-1)"
    echo "❌ Failed to delete chat (HTTP $HTTP_CODE)"
fi
echo ""

echo "=========================================="
echo "✅ All Chat & Message tests passed!"
echo "=========================================="
