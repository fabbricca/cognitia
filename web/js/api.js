/**
 * Cognitia API Client
 * REST API wrapper for authentication and data management
 */

export class ApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
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
            const response = await fetch(`${this.baseUrl}/api/auth/refresh`, {
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
        return this.request('POST', '/api/auth/register', { email, password });
    }

    async login(email, password) {
        const data = await this.request('POST', '/api/auth/login', { email, password });
        if (data.access_token) {
            this.setToken(data.access_token, data.refresh_token);
        }
        return data;
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

    async createCharacter(name, systemPrompt, personaPrompt = null, voiceModel = 'glados') {
        const data = { 
            name, 
            system_prompt: systemPrompt, 
            voice_model: voiceModel 
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
}

// Singleton instance
export const api = new ApiClient();
