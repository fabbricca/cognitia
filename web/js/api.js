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

    // Character endpoints
    async getCharacters() {
        return this.request('GET', '/api/characters/');
    }

    async getCharacter(id) {
        return this.request('GET', `/api/characters/${id}`);
    }

    async createCharacter(name, preprompt, voiceModel = 'glados', pthFile = null, indexFile = null) {
        if (pthFile || indexFile) {
            const formData = {
                name,
                preprompt,
                voice_model: voiceModel
            };
            if (pthFile) formData.pth_file = pthFile;
            if (indexFile) formData.index_file = indexFile;
            return this.request('POST', '/api/characters/', formData, true);
        }
        return this.request('POST', '/api/characters/', { name, preprompt, voice_model: voiceModel });
    }

    async updateCharacter(id, data) {
        return this.request('PUT', `/api/characters/${id}`, data);
    }

    async deleteCharacter(id) {
        return this.request('DELETE', `/api/characters/${id}`);
    }

    async uploadVoiceModel(characterId, pthFile, indexFile = null) {
        const data = { pth_file: pthFile };
        if (indexFile) data.index_file = indexFile;
        return this.request('POST', `/api/characters/${id}/voice-model`, data, true);
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

    async createMessage(chatId, content, role = 'user', audioUrl = null) {
        return this.request('POST', `/api/chats/${chatId}/messages`, {
            content,
            role,
            audio_url: audioUrl
        });
    }
}

// Singleton instance
export const api = new ApiClient();
