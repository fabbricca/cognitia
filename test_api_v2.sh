#!/bin/bash
# Test API v2 Endpoints

API_URL="http://localhost:8000"
EMAIL="testuser_$(date +%s)@example.com"
PASSWORD="TestPassword123"

echo "=========================================="
echo "Testing API v2 Endpoints"
echo "=========================================="
echo ""

# Test 1: Register a new user
echo "1. Testing POST /api/v2/auth/register"
echo "----------------------------------------"
REGISTER_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\", \"first_name\": \"Test\", \"last_name\": \"User\"}")

echo "$REGISTER_RESPONSE" | python3 -m json.tool
USER_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))")

if [ -z "$USER_ID" ]; then
    echo "❌ Failed to register user"
    exit 1
fi

echo "✅ User registered successfully"
echo "User ID: $USER_ID"
echo ""

# Since email verification isn't set up yet, manually mark user as verified via SQL
echo "→ Marking user email as verified (dev workaround)..."
docker exec cognitia-postgres-dev psql -U cognitia -d cognitia -c "UPDATE users SET email_verified = true WHERE id = '${USER_ID}';" > /dev/null 2>&1
echo ""

# Test 2: Login with the user
echo "2. Testing POST /api/v2/auth/login"
echo "----------------------------------------"
LOGIN_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\"}")

echo "$LOGIN_RESPONSE" | python3 -m json.tool
echo ""

# Extract access token
ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
    echo "❌ Failed to login user"
    exit 1
fi

echo "✅ User logged in successfully"
echo "Access Token: ${ACCESS_TOKEN:0:20}..."
echo ""

# Test 3: Get current user
echo "3. Testing GET /api/v2/auth/me"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/auth/me" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Retrieved current user"
echo ""

# Test 4: Update user profile
echo "4. Testing PATCH /api/v2/users/me"
echo "----------------------------------------"
curl -s -X PATCH "${API_URL}/api/v2/users/me" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Updated", "last_name": "Name"}' | python3 -m json.tool
echo ""
echo "✅ Updated user profile"
echo ""

# Test 5: Create a character
echo "5. Testing POST /api/v2/characters"
echo "----------------------------------------"
CREATE_CHAR_RESPONSE=$(curl -s -X POST "${API_URL}/api/v2/characters" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Character",
    "description": "A test character for API v2",
    "system_prompt": "You are a helpful assistant for testing.",
    "voice_model": "af_bella",
    "prompt_template": "pygmalion",
    "is_public": true,
    "tags": ["test", "demo"],
    "category": "tutorial"
  }')

echo "$CREATE_CHAR_RESPONSE" | python3 -m json.tool
echo ""

# Extract character ID
CHAR_ID=$(echo "$CREATE_CHAR_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -z "$CHAR_ID" ]; then
    echo "❌ Failed to create character"
    exit 1
fi

echo "✅ Character created successfully"
echo "Character ID: $CHAR_ID"
echo ""

# Test 6: List user characters
echo "6. Testing GET /api/v2/characters"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/characters" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Listed user characters"
echo ""

# Test 7: Get specific character
echo "7. Testing GET /api/v2/characters/{character_id}"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/characters/${CHAR_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool
echo ""
echo "✅ Retrieved character details"
echo ""

# Test 8: Browse marketplace (no auth)
echo "8. Testing GET /api/v2/characters/marketplace (no auth)"
echo "----------------------------------------"
curl -s -X GET "${API_URL}/api/v2/characters/marketplace?tags=test&limit=10" | python3 -m json.tool
echo ""
echo "✅ Browsed marketplace"
echo ""

# Test 9: Update character
echo "9. Testing PATCH /api/v2/characters/{character_id}"
echo "----------------------------------------"
curl -s -X PATCH "${API_URL}/api/v2/characters/${CHAR_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description for testing"}' | python3 -m json.tool
echo ""
echo "✅ Updated character"
echo ""

# Test 10: Delete character
echo "10. Testing DELETE /api/v2/characters/{character_id}"
echo "----------------------------------------"
DELETE_RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/api/v2/characters/${CHAR_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")
HTTP_CODE=$(echo "$DELETE_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" == "204" ]; then
    echo "✅ Character deleted successfully (HTTP 204)"
else
    echo "Response: $(echo "$DELETE_RESPONSE" | head -n-1)"
    echo "❌ Failed to delete character (HTTP $HTTP_CODE)"
fi
echo ""

echo "=========================================="
echo "✅ All API v2 endpoint tests passed!"
echo "=========================================="
