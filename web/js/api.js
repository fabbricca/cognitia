/**
 * Cognitia API Client
 * REST API wrapper for authentication and data management
 */

export class ApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
        // Auth service runs on a dedicated host in production.
        // But if the public edge proxy is not routing auth.cognitia.iberu.me correctly yet,
        // we can use same-origin via ingress routing (/api/auth -> cognitia-auth).
        try {
            const host = window?.location?.hostname || '';
            this.authBaseUrl = host.endsWith('cognitia.iberu.me') ? '' : baseUrl;
        } catch {
            this.authBaseUrl = baseUrl;
        }
        this.token = localStorage.getItem('glados_token');
        this.refreshToken = localStorage.getItem('glados_refresh_token');
    }

    setToken(token, refreshToken = null) {
        this.token = token;
        localStorage.setItem('glados_token', token);
        if (refreshToken) {
            this.refreshToken = refreshToken;
            localStorage.setItem('glados_refresh_token', refreshToken);
        }
    }

    clearToken() {
        this.token = null;
        this.refreshToken = null;
        localStorage.removeItem('glados_token');
        localStorage.removeItem('glados_refresh_token');
    }

    isAuthenticated() {
        return !!this.token;
    }

    async request(method, endpoint, data = null, isFormData = false) {
        const headers = {};
        
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        if (!isFormData && data) {
            headers['Content-Type'] = 'application/json';
        }

        const options = {
            method,
            headers
        };

        if (data) {
            if (isFormData) {
                const formData = new FormData();
                for (const [key, value] of Object.entries(data)) {
                    formData.append(key, value);
                }
                options.body = formData;
            } else {
                options.body = JSON.stringify(data);
            }
        }

        const response = await fetch(`${this.baseUrl}${endpoint}`, options);

        // Handle 401 - try refresh token
        if (response.status === 401 && this.refreshToken) {
            const refreshed = await this.refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${this.token}`;
                const retryResponse = await fetch(`${this.baseUrl}${endpoint}`, {
                    ...options,
                    headers
                });
                return this.handleResponse(retryResponse);
            }
        }

        return this.handleResponse(response);
    }

    async handleResponse(response) {
        const contentType = response.headers.get('content-type');
        let data = null;
        
        if (contentType && contentType.includes('application/json')) {
            data = await response.json();
        } else {
            data = await response.text();
        }

        if (!response.ok) {
            const error = new Error(data.detail || data || 'Request failed');
            error.status = response.status;
            error.data = data;
            throw error;
        }

        return data;
    }

    async refreshAccessToken() {
        try {
            const response = await fetch(`${this.authBaseUrl}/api/auth/refresh`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ refresh_token: this.refreshToken })
            });

            if (response.ok) {
                const data = await response.json();
                this.setToken(data.access_token, data.refresh_token);
                return true;
            }
        } catch (error) {
            console.error('Token refresh failed:', error);
        }

        this.clearToken();
        return false;
    }

    // Auth endpoints
    async register(email, password) {
        const data = await fetch(`${this.authBaseUrl}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const payload = await this.handleResponse(data);
        if (payload.access_token) {
            this.setToken(payload.access_token, payload.refresh_token);
        }
        return payload;
    }

    async login(email, password) {
        const response = await fetch(`${this.authBaseUrl}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const payload = await this.handleResponse(response);
        if (payload.access_token) {
            this.setToken(payload.access_token, payload.refresh_token);
        }
        return payload;
    }

    async logout() {
        await this.request('POST', '/api/auth/logout');
        this.clearToken();
    }

    async getProfile() {
        return this.request('GET', '/api/auth/me');
    }

    /**
     * Upload avatar for the current user.
     * @param {File} avatarFile - The avatar image file
     * @returns {Promise<object>} - Updated user data
     */
    async uploadUserAvatar(avatarFile) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('avatar_file', avatarFile);

            const xhr = new XMLHttpRequest();

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve(xhr.responseText);
                    }
                } else {
                    let errorDetail = 'Upload failed';
                    try {
                        const errData = JSON.parse(xhr.responseText);
                        errorDetail = errData.detail || errData.message || errorDetail;
                    } catch (e) {
                        errorDetail = xhr.responseText || errorDetail;
                    }
                    const error = new Error(errorDetail);
                    error.status = xhr.status;
                    reject(error);
                }
            });

            xhr.addEventListener('error', () => {
                reject(new Error('Network error during upload'));
            });

            xhr.open('POST', `${this.baseUrl}/api/auth/me/avatar`);
            
            if (this.token) {
                xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            }
            
            xhr.send(formData);
        });
    }

    // Character endpoints
    async getCharacters() {
        return this.request('GET', '/api/characters/');
    }

    async getCharacter(id) {
        return this.request('GET', `/api/characters/${id}`);
    }

    async createCharacter(name, systemPrompt, personaPrompt = null, voiceModel = 'glados', promptTemplate = 'pygmalion') {
        const data = {
            name,
            system_prompt: systemPrompt,
            voice_model: voiceModel,
            prompt_template: promptTemplate
        };
        if (personaPrompt) {
            data.persona_prompt = personaPrompt;
        }
        return this.request('POST', '/api/characters/', data);
    }

    async updateCharacter(id, data) {
        return this.request('PUT', `/api/characters/${id}`, data);
    }

    async deleteCharacter(id) {
        return this.request('DELETE', `/api/characters/${id}`);
    }

    /**
     * Upload avatar for a character.
     * @param {string} characterId - The character ID
     * @param {File} avatarFile - The avatar image file
     * @returns {Promise<object>} - Updated character data
     */
    async uploadCharacterAvatar(characterId, avatarFile) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('avatar_file', avatarFile);

            const xhr = new XMLHttpRequest();

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve(xhr.responseText);
                    }
                } else {
                    let errorDetail = 'Upload failed';
                    try {
                        const errData = JSON.parse(xhr.responseText);
                        errorDetail = errData.detail || errData.message || errorDetail;
                    } catch (e) {
                        errorDetail = xhr.responseText || errorDetail;
                    }
                    const error = new Error(errorDetail);
                    error.status = xhr.status;
                    reject(error);
                }
            });

            xhr.addEventListener('error', () => {
                reject(new Error('Network error during upload'));
            });

            xhr.open('POST', `${this.baseUrl}/api/characters/${characterId}/avatar`);
            
            if (this.token) {
                xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            }
            
            xhr.send(formData);
        });
    }

    /**
     * Upload RVC voice model for a character with progress tracking.
     * @param {string} characterId - The character ID
     * @param {File} pthFile - The .pth model file
     * @param {File|null} indexFile - Optional .index file
     * @param {function|null} onProgress - Progress callback (0-100)
     * @returns {Promise<object>} - Updated character data
     */
    uploadVoiceModel(characterId, pthFile, indexFile = null, onProgress = null) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('pth_file', pthFile);
            if (indexFile) {
                formData.append('index_file', indexFile);
            }

            const xhr = new XMLHttpRequest();
            
            // Track upload progress
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    onProgress(percent);
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve(xhr.responseText);
                    }
                } else {
                    let errorDetail = 'Upload failed';
                    try {
                        const errData = JSON.parse(xhr.responseText);
                        errorDetail = errData.detail || errData.message || errorDetail;
                    } catch (e) {
                        errorDetail = xhr.responseText || errorDetail;
                    }
                    const error = new Error(errorDetail);
                    error.status = xhr.status;
                    reject(error);
                }
            });

            xhr.addEventListener('error', () => {
                reject(new Error('Network error during upload'));
            });

            xhr.addEventListener('timeout', () => {
                reject(new Error('Upload timed out'));
            });

            xhr.open('POST', `${this.baseUrl}/api/characters/${characterId}/voice-model`);
            
            if (this.token) {
                xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            }
            
            // Extended timeout for large files (5 minutes)
            xhr.timeout = 300000;
            
            xhr.send(formData);
        });
    }

    // Chat endpoints
    async getChats() {
        return this.request('GET', '/api/chats/');
    }

    async getChat(id) {
        return this.request('GET', `/api/chats/${id}`);
    }

    async createChat(characterId, title = null) {
        return this.request('POST', '/api/chats/', { character_id: characterId, title });
    }

    async updateChat(id, data) {
        return this.request('PUT', `/api/chats/${id}`, data);
    }

    async deleteChat(id) {
        return this.request('DELETE', `/api/chats/${id}`);
    }

    async getChatMessages(chatId, limit = 50, offset = 0) {
        return this.request('GET', `/api/chats/${chatId}/messages?limit=${limit}&offset=${offset}`);
    }

    /**
     * Get messages with cursor-based pagination (v2 API).
     * @param {string} chatId - The chat ID
     * @param {number} limit - Number of messages to fetch (1-100)
     * @param {string|null} cursor - Cursor for pagination
     * @param {string} direction - 'older' or 'newer'
     * @returns {Promise<object>} - Paginated messages with cursors
     */
    async getChatMessagesV2(chatId, limit = 50, cursor = null, direction = 'older') {
        let url = `/api/v2/chats/${chatId}/messages?limit=${limit}&direction=${direction}`;
        if (cursor) {
            url += `&cursor=${encodeURIComponent(cursor)}`;
        }
        return this.request('GET', url);
    }

    async createMessage(chatId, content, role = 'user', audioUrl = null) {
        return this.request('POST', `/api/chats/${chatId}/messages`, {
            content,
            role,
            audio_url: audioUrl
        });
    }

    /**
     * Delete a single message from a chat.
     * @param {string} chatId - The chat ID
     * @param {string} messageId - The message ID to delete
     * @returns {Promise<object>} - Success status and deleted count
     */
    async deleteMessage(chatId, messageId) {
        return this.request('DELETE', `/api/chats/${chatId}/messages/${messageId}`);
    }

    /**
     * Delete a message and all messages after it in a chat.
     * @param {string} chatId - The chat ID
     * @param {string} messageId - The message ID to start deleting from
     * @returns {Promise<object>} - Success status and deleted count
     */
    async deleteMessageAndAfter(chatId, messageId) {
        return this.request('DELETE', `/api/chats/${chatId}/messages/${messageId}/and-after`);
    }

    // Model/Voice endpoints
    
    /**
     * Get available TTS voice models.
     * @returns {Promise<object>} - List of voice models
     */
    async getVoiceModels() {
        return this.request('GET', '/api/models/voices');
    }

    /**
     * Get available RVC voice conversion models.
     * @returns {Promise<object>} - List of RVC models
     */
    async getRVCModels() {
        return this.request('GET', '/api/models/rvc');
    }

    /**
     * Assign an existing RVC model to a character.
     * @param {string} characterId - The character ID
     * @param {string} rvcModelPath - The RVC model path
     * @param {string} rvcIndexPath - The RVC index path (optional)
     * @returns {Promise<object>} - Updated character data
     */
    async assignRVCModel(characterId, rvcModelPath, rvcIndexPath = null) {
        return this.request('PUT', `/api/characters/${characterId}/rvc-model`, {
            rvc_model_path: rvcModelPath,
            rvc_index_path: rvcIndexPath
        });
    }

    /**
     * Get Core GPU server status.
     * @returns {Promise<object>} - Core server status
     */
    async getCoreStatus() {
        return this.request('GET', '/api/core/status');
    }

    /**
     * Request the Core server to reload a model.
     * @param {string} modelType - Type of model (asr, tts, llm, rvc)
     * @returns {Promise<object>} - Reload status
     */
    async reloadCoreModel(modelType) {
        return this.request('POST', `/api/core/reload-model?model_type=${modelType}`);
    }

    // ==========================================================================
    // Memory System Endpoints
    // ==========================================================================

    /**
     * Get full memory context for a character.
     * @param {string} characterId - The character ID
     * @returns {Promise<object>} - Memory context (relationship, facts, memories)
     */
    async getMemoryContext(characterId) {
        return this.request('GET', `/api/memory/${characterId}/context`);
    }

    /**
     * Get all user facts for a character.
     * @param {string} characterId - The character ID
     * @param {string} category - Optional category filter
     * @returns {Promise<object>} - List of facts
     */
    async getUserFacts(characterId, category = null) {
        const url = category 
            ? `/api/memory/${characterId}/facts?category=${encodeURIComponent(category)}`
            : `/api/memory/${characterId}/facts`;
        return this.request('GET', url);
    }

    /**
     * Update a user fact.
     * @param {string} characterId - The character ID
     * @param {string} factId - The fact ID
     * @param {object} update - Update data {category, key, value, confidence}
     * @returns {Promise<object>} - Updated fact
     */
    async updateUserFact(characterId, factId, update) {
        return this.request('PUT', `/api/memory/${characterId}/facts/${factId}`, update);
    }

    /**
     * Delete a user fact.
     * @param {string} characterId - The character ID
     * @param {string} factId - The fact ID
     * @returns {Promise<void>}
     */
    async deleteUserFact(characterId, factId) {
        return this.request('DELETE', `/api/memory/${characterId}/facts/${factId}`);
    }

    /**
     * Get all memories for a character.
     * @param {string} characterId - The character ID
     * @param {string} memoryType - Optional type filter (episodic, semantic, event)
     * @param {number} limit - Max memories to return
     * @returns {Promise<object>} - List of memories
     */
    async getMemories(characterId, memoryType = null, limit = 50) {
        let url = `/api/memory/${characterId}/memories?limit=${limit}`;
        if (memoryType) {
            url += `&memory_type=${encodeURIComponent(memoryType)}`;
        }
        return this.request('GET', url);
    }

    /**
     * Update a memory.
     * @param {string} characterId - The character ID
     * @param {string} memoryId - The memory ID
     * @param {object} update - Update data {content, summary, emotional_tone, importance}
     * @returns {Promise<object>} - Updated memory
     */
    async updateMemory(characterId, memoryId, update) {
        return this.request('PUT', `/api/memory/${characterId}/memories/${memoryId}`, update);
    }

    /**
     * Delete a memory.
     * @param {string} characterId - The character ID
     * @param {string} memoryId - The memory ID
     * @returns {Promise<void>}
     */
    async deleteMemory(characterId, memoryId) {
        return this.request('DELETE', `/api/memory/${characterId}/memories/${memoryId}`);
    }

    /**
     * Get relationship status with a character.
     * @param {string} characterId - The character ID
     * @returns {Promise<object>} - Relationship status
     */
    async getRelationship(characterId) {
        return this.request('GET', `/api/memory/${characterId}/relationship`);
    }

    /**
     * Update relationship status.
     * @param {string} characterId - The character ID
     * @param {object} update - Update data {stage, trust_level}
     * @returns {Promise<object>} - Updated relationship
     */
    async updateRelationship(characterId, update) {
        return this.request('PUT', `/api/memory/${characterId}/relationship`, update);
    }

    /**
     * Delete an inside joke from a relationship.
     * @param {string} characterId - The character ID
     * @param {number} jokeIndex - The index of the joke to delete
     * @returns {Promise<void>}
     */
    async deleteInsideJoke(characterId, jokeIndex) {
        return this.request('DELETE', `/api/memory/${characterId}/relationship/inside-jokes/${jokeIndex}`);
    }

    /**
     * Delete a milestone from a relationship.
     * @param {string} characterId - The character ID
     * @param {number} milestoneIndex - The index of the milestone to delete
     * @returns {Promise<void>}
     */
    async deleteMilestone(characterId, milestoneIndex) {
        return this.request('DELETE', `/api/memory/${characterId}/relationship/milestones/${milestoneIndex}`);
    }

    /**
     * Get diary entries for a character.
     * @param {string} characterId - The character ID
     * @param {string} entryType - Entry type (daily, weekly, monthly)
     * @param {number} limit - Max entries to return
     * @returns {Promise<object>} - List of diary entries
     */
    async getDiaryEntries(characterId, entryType = 'daily', limit = 30) {
        return this.request('GET', `/api/memory/${characterId}/diary?entry_type=${entryType}&limit=${limit}`);
    }

    /**
     * Get a knowledge graph snapshot (nodes + edges) for this user-character pair.
     * @param {string} characterId
     * @returns {Promise<object>} - Graph response {available, group_id, nodes, edges}
     */
    async getMemoryGraph(characterId) {
        return this.request('GET', `/api/memory/${characterId}/graph`);
    }
}

// Singleton instance
export const api = new ApiClient();
