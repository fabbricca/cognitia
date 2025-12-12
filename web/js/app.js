/**
 * Cognitia Web Interface
 * Main Application
 */

import { WebSocketManager } from './websocket.js';
import { AudioManager } from './audio.js';
import { api } from './api.js';

class CognitiaApp {
    constructor() {
        // State
        this.currentChat = null;
        this.currentCharacter = null;
        this.characters = [];
        this.chats = [];
        this.messages = [];
        this.isInCall = false;

        // Managers
        this.ws = null;
        this.audio = new AudioManager();

        // Config - use wss:// for HTTPS, ws:// for HTTP
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.wsUrl = `${wsProtocol}//${window.location.host}/ws`;

        // DOM elements
        this.elements = {};
    }

    async init() {
        this.bindElements();
        this.bindEvents();

        // Initialize audio
        await this.audio.init();

        // Check authentication
        if (api.isAuthenticated()) {
            try {
                await api.getProfile();
                await this.showMainInterface();
            } catch (error) {
                api.clearToken();
                this.showLoginScreen();
            }
        } else {
            this.showLoginScreen();
        }
    }

    bindElements() {
        this.elements = {
            // Screens
            loginScreen: document.getElementById('login-screen'),
            mainScreen: document.getElementById('main-screen'),

            // Login form
            loginForm: document.getElementById('login-form'),
            loginEmail: document.getElementById('login-email'),
            loginPassword: document.getElementById('login-password'),
            loginSubmit: document.getElementById('login-submit'),
            loginError: document.getElementById('login-error'),
            showRegister: document.getElementById('show-register'),
            registerForm: document.getElementById('register-form'),
            registerEmail: document.getElementById('register-email'),
            registerPassword: document.getElementById('register-password'),
            registerSubmit: document.getElementById('register-submit'),
            registerError: document.getElementById('register-error'),
            showLogin: document.getElementById('show-login'),

            // Header
            connectionStatus: document.getElementById('connection-status'),
            logoutBtn: document.getElementById('logout-btn'),

            // Chat list
            chatList: document.getElementById('chat-list'),
            newChatBtn: document.getElementById('new-chat-btn'),

            // Chat view
            emptyState: document.getElementById('empty-state'),
            chatView: document.getElementById('chat-view'),
            chatTitle: document.getElementById('chat-title'),
            characterName: document.getElementById('character-name'),
            editCharacterBtn: document.getElementById('edit-character-btn'),
            messagesContainer: document.getElementById('messages-container'),

            // Input
            messageInput: document.getElementById('message-input'),
            sendBtn: document.getElementById('send-btn'),
            recordBtn: document.getElementById('record-btn'),
            callBtn: document.getElementById('call-btn'),
            recordingIndicator: document.getElementById('recording-indicator'),
            callOverlay: document.getElementById('call-overlay'),
            endCallBtn: document.getElementById('end-call-btn'),
            volumeLevel: document.getElementById('volume-level'),

            // Modal
            characterModal: document.getElementById('character-modal'),
            closeModal: document.getElementById('close-modal'),
            characterForm: document.getElementById('character-form'),
            characterId: document.getElementById('character-id'),
            characterNameInput: document.getElementById('character-name-input'),
            characterPreprompt: document.getElementById('character-preprompt'),
            voiceModelSelect: document.getElementById('voice-model-select'),
            pthFile: document.getElementById('pth-file'),
            indexFile: document.getElementById('index-file'),
            saveCharacter: document.getElementById('save-character'),
            deleteCharacter: document.getElementById('delete-character')
        };
    }

    bindEvents() {
        // Login form
        this.elements.loginSubmit.addEventListener('click', (e) => {
            e.preventDefault();
            this.handleLogin();
        });

        this.elements.showRegister.addEventListener('click', (e) => {
            e.preventDefault();
            this.elements.loginForm.classList.add('hidden');
            this.elements.registerForm.classList.remove('hidden');
        });

        // Register form
        this.elements.registerSubmit.addEventListener('click', (e) => {
            e.preventDefault();
            this.handleRegister();
        });

        this.elements.showLogin.addEventListener('click', (e) => {
            e.preventDefault();
            this.elements.registerForm.classList.add('hidden');
            this.elements.loginForm.classList.remove('hidden');
        });

        // Logout
        this.elements.logoutBtn.addEventListener('click', () => this.handleLogout());

        // New chat
        this.elements.newChatBtn.addEventListener('click', () => this.showCharacterModal());

        // Send message
        this.elements.sendBtn.addEventListener('click', () => this.sendMessage());
        this.elements.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Recording
        this.elements.recordBtn.addEventListener('mousedown', () => this.startRecording());
        this.elements.recordBtn.addEventListener('mouseup', () => this.stopRecording());
        this.elements.recordBtn.addEventListener('mouseleave', () => this.stopRecording());

        // Touch support for recording
        this.elements.recordBtn.addEventListener('touchstart', (e) => {
            e.preventDefault();
            this.startRecording();
        });
        this.elements.recordBtn.addEventListener('touchend', (e) => {
            e.preventDefault();
            this.stopRecording();
        });

        // Call
        this.elements.callBtn.addEventListener('click', () => this.toggleCall());
        this.elements.endCallBtn.addEventListener('click', () => this.endCall());

        // Character modal
        this.elements.closeModal.addEventListener('click', () => this.hideCharacterModal());
        this.elements.saveCharacter.addEventListener('click', () => this.saveCharacter());
        this.elements.deleteCharacter.addEventListener('click', () => this.deleteCharacter());
        this.elements.editCharacterBtn.addEventListener('click', () => {
            if (this.currentCharacter) {
                this.showCharacterModal(this.currentCharacter);
            }
        });

        // Close modal on outside click
        this.elements.characterModal.addEventListener('click', (e) => {
            if (e.target === this.elements.characterModal) {
                this.hideCharacterModal();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideCharacterModal();
                if (this.isInCall) this.endCall();
            }
        });
    }

    // Authentication
    async handleLogin() {
        const email = this.elements.loginEmail.value.trim();
        const password = this.elements.loginPassword.value;

        if (!email || !password) {
            this.showLoginError('Please enter email and password');
            return;
        }

        try {
            this.elements.loginSubmit.disabled = true;
            await api.login(email, password);
            await this.showMainInterface();
        } catch (error) {
            this.showLoginError(error.message || 'Login failed');
        } finally {
            this.elements.loginSubmit.disabled = false;
        }
    }

    async handleRegister() {
        const email = this.elements.registerEmail.value.trim();
        const password = this.elements.registerPassword.value;

        if (!email || !password) {
            this.showRegisterError('Please enter email and password');
            return;
        }

        if (password.length < 8) {
            this.showRegisterError('Password must be at least 8 characters');
            return;
        }

        try {
            this.elements.registerSubmit.disabled = true;
            await api.register(email, password);
            await api.login(email, password);
            await this.showMainInterface();
        } catch (error) {
            this.showRegisterError(error.message || 'Registration failed');
        } finally {
            this.elements.registerSubmit.disabled = false;
        }
    }

    async handleLogout() {
        try {
            await api.logout();
        } catch (error) {
            console.error('Logout error:', error);
        }
        
        if (this.ws) {
            this.ws.disconnect();
        }
        
        this.showLoginScreen();
    }

    showLoginError(message) {
        this.elements.loginError.textContent = message;
        this.elements.loginError.classList.remove('hidden');
    }

    showRegisterError(message) {
        this.elements.registerError.textContent = message;
        this.elements.registerError.classList.remove('hidden');
    }

    // Screens
    showLoginScreen() {
        this.elements.loginScreen.classList.remove('hidden');
        this.elements.mainScreen.classList.add('hidden');
        this.elements.loginEmail.value = '';
        this.elements.loginPassword.value = '';
        this.elements.loginError.classList.add('hidden');
    }

    async showMainInterface() {
        this.elements.loginScreen.classList.add('hidden');
        this.elements.mainScreen.classList.remove('hidden');

        // Connect WebSocket
        await this.connectWebSocket();

        // Load data
        await this.loadChats();
        await this.loadCharacters();
    }

    // WebSocket
    async connectWebSocket() {
        this.ws = new WebSocketManager(this.wsUrl);

        this.ws.on('connected', () => {
            this.elements.connectionStatus.textContent = 'Connected';
            this.elements.connectionStatus.classList.add('connected');
            
            // Authenticate
            this.ws.send({
                type: 'auth',
                token: api.token
            });
        });

        this.ws.on('disconnected', () => {
            this.elements.connectionStatus.textContent = 'Disconnected';
            this.elements.connectionStatus.classList.remove('connected');
        });

        this.ws.on('error', (error) => {
            console.error('WebSocket error:', error);
        });

        // Handle incoming messages
        this.ws.on('text_chunk', (msg) => {
            this.handleTextChunk(msg);
        });

        this.ws.on('text_complete', (msg) => {
            this.handleTextComplete(msg);
        });

        this.ws.on('audio', (msg) => {
            this.handleAudioResponse(msg);
        });

        this.ws.on('transcription', (msg) => {
            this.handleTranscription(msg);
        });

        this.ws.on('status', (msg) => {
            console.log('Status:', msg.message);
        });

        this.ws.on('error', (msg) => {
            console.error('Server error:', msg.message);
        });

        try {
            await this.ws.connect();
        } catch (error) {
            console.error('WebSocket connection failed:', error);
        }
    }

    // Data loading
    async loadChats() {
        try {
            const response = await api.getChats();
            this.chats = response.chats || [];
            this.renderChatList();
        } catch (error) {
            console.error('Failed to load chats:', error);
            this.chats = [];
        }
    }

    async loadCharacters() {
        try {
            const response = await api.getCharacters();
            this.characters = response.characters || [];
        } catch (error) {
            console.error('Failed to load characters:', error);
            this.characters = [];
        }
    }

    // Chat list
    renderChatList() {
        this.elements.chatList.innerHTML = '';

        for (const chat of this.chats) {
            const item = document.createElement('div');
            item.className = 'chat-item';
            if (this.currentChat && this.currentChat.id === chat.id) {
                item.classList.add('active');
            }

            item.innerHTML = `
                <div class="chat-item-title">${this.escapeHtml(chat.title || 'New Chat')}</div>
                <div class="chat-item-preview">${this.escapeHtml(chat.last_message || '')}</div>
            `;

            item.addEventListener('click', () => this.selectChat(chat));
            this.elements.chatList.appendChild(item);
        }
    }

    async selectChat(chat) {
        this.currentChat = chat;
        
        // Load character
        if (chat.character_id) {
            try {
                this.currentCharacter = await api.getCharacter(chat.character_id);
            } catch (error) {
                console.error('Failed to load character:', error);
            }
        }

        // Switch character on backend
        if (this.currentCharacter && this.ws) {
            this.ws.switchCharacter(
                this.currentCharacter.id,
                this.currentCharacter.system_prompt,
                this.currentCharacter.voice_model,
                this.currentCharacter.rvc_model_path,
                this.currentCharacter.rvc_index_path
            );
        }

        // Load messages
        try {
            const messagesData = await api.getChatMessages(chat.id);
            this.messages = messagesData.messages || [];
        } catch (error) {
            console.error('Failed to load messages:', error);
            this.messages = [];
        }

        this.renderChatView();
        this.renderChatList();
    }

    renderChatView() {
        this.elements.emptyState.classList.add('hidden');
        this.elements.chatView.classList.remove('hidden');

        this.elements.chatTitle.textContent = this.currentChat?.title || 'Chat';
        this.elements.characterName.textContent = this.currentCharacter?.name || 'Unknown';

        this.renderMessages();
    }

    renderMessages() {
        this.elements.messagesContainer.innerHTML = '';

        for (const msg of this.messages) {
            this.appendMessage(msg.role, msg.content, msg.audio_url);
        }

        this.scrollToBottom();
    }

    appendMessage(role, content, audioUrl = null) {
        const div = document.createElement('div');
        div.className = `message ${role}`;

        let html = `<div class="message-content">${this.escapeHtml(content)}</div>`;
        
        if (audioUrl) {
            html += `
                <audio class="message-audio" controls>
                    <source src="${audioUrl}" type="audio/wav">
                </audio>
            `;
        }

        div.innerHTML = html;
        this.elements.messagesContainer.appendChild(div);
        this.scrollToBottom();
        return div;
    }

    appendStreamingMessage(role) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        div.innerHTML = '<div class="message-content"></div>';
        this.elements.messagesContainer.appendChild(div);
        return div;
    }

    updateStreamingMessage(element, content) {
        const contentDiv = element.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.textContent = content;
        }
        this.scrollToBottom();
    }

    scrollToBottom() {
        this.elements.messagesContainer.scrollTop = this.elements.messagesContainer.scrollHeight;
    }

    // Message handling
    async sendMessage() {
        const text = this.elements.messageInput.value.trim();
        if (!text || !this.currentChat) return;

        this.elements.messageInput.value = '';

        // Show user message
        this.appendMessage('user', text);

        // Save to database
        try {
            await api.createMessage(this.currentChat.id, text, 'user');
        } catch (error) {
            console.error('Failed to save message:', error);
        }

        // Create streaming element for response
        this.currentStreamingElement = this.appendStreamingMessage('assistant');
        this.currentStreamingText = '';

        // Send to WebSocket
        if (this.ws) {
            this.ws.sendText(text, this.currentChat.id, this.currentCharacter?.id);
        }
    }

    handleTextChunk(msg) {
        if (this.currentStreamingElement) {
            this.currentStreamingText += msg.chunk;
            this.updateStreamingMessage(this.currentStreamingElement, this.currentStreamingText);
        }
    }

    handleTextComplete(msg) {
        const fullText = msg.full_text || this.currentStreamingText;
        
        if (this.currentStreamingElement) {
            this.updateStreamingMessage(this.currentStreamingElement, fullText);
            this.currentStreamingElement = null;
        }

        // Save assistant message
        if (this.currentChat) {
            api.createMessage(this.currentChat.id, fullText, 'assistant').catch(console.error);
        }

        this.messages.push({ role: 'assistant', content: fullText });
    }

    handleAudioResponse(msg) {
        if (msg.data) {
            this.audio.playAudio(msg.data, msg.format || 'wav');
        }
    }

    handleTranscription(msg) {
        // Show transcribed text as user message
        if (msg.text) {
            this.appendMessage('user', msg.text);
            
            // Save transcription
            if (this.currentChat) {
                api.createMessage(this.currentChat.id, msg.text, 'user').catch(console.error);
            }
        }
    }

    // Recording
    async startRecording() {
        if (!this.currentChat) return;

        const started = await this.audio.startRecording();
        if (started) {
            this.elements.recordingIndicator.classList.remove('hidden');
        }
    }

    async stopRecording() {
        if (!this.audio.isRecording) return;

        this.elements.recordingIndicator.classList.add('hidden');
        
        const audioData = await this.audio.stopRecording();
        if (audioData && this.ws) {
            // Create streaming element for response
            this.currentStreamingElement = this.appendStreamingMessage('assistant');
            this.currentStreamingText = '';

            this.ws.sendAudio(
                audioData.data,
                audioData.format,
                audioData.sampleRate,
                this.currentChat.id,
                this.currentCharacter?.id
            );
        }
    }

    // Call mode
    async toggleCall() {
        if (this.isInCall) {
            this.endCall();
        } else {
            await this.startCall();
        }
    }

    async startCall() {
        if (!this.currentChat || !this.currentCharacter) return;

        this.isInCall = true;
        this.elements.callOverlay.classList.remove('hidden');
        this.elements.callBtn.classList.add('active');

        // Start call on backend
        if (this.ws) {
            this.ws.startCall(this.currentChat.id, this.currentCharacter.id);
        }

        // Start VAD audio processing
        await this.audio.startCallMode((audioData, format, sampleRate) => {
            if (this.ws && this.isInCall) {
                this.ws.sendAudio(audioData, format, sampleRate, this.currentChat.id, this.currentCharacter.id);
            }
        });

        // Volume meter animation
        this.volumeInterval = setInterval(() => {
            const volume = this.audio.getVolume();
            this.elements.volumeLevel.style.width = `${volume * 100}%`;
        }, 100);
    }

    endCall() {
        this.isInCall = false;
        this.elements.callOverlay.classList.add('hidden');
        this.elements.callBtn.classList.remove('active');

        // Stop call on backend
        if (this.ws) {
            this.ws.endCall();
        }

        // Stop audio
        this.audio.stopCallMode();
        this.audio.stopPlayback();

        if (this.volumeInterval) {
            clearInterval(this.volumeInterval);
        }
    }

    // Character modal
    showCharacterModal(character = null) {
        this.elements.characterModal.classList.remove('hidden');
        
        if (character) {
            this.elements.characterId.value = character.id;
            this.elements.characterNameInput.value = character.name;
            this.elements.characterPreprompt.value = character.system_prompt;
            this.elements.voiceModelSelect.value = character.voice_model || 'glados';
            this.elements.deleteCharacter.classList.remove('hidden');
        } else {
            this.elements.characterId.value = '';
            this.elements.characterNameInput.value = '';
            this.elements.characterPreprompt.value = '';
            this.elements.voiceModelSelect.value = 'glados';
            this.elements.pthFile.value = '';
            this.elements.indexFile.value = '';
            this.elements.deleteCharacter.classList.add('hidden');
        }
    }

    hideCharacterModal() {
        this.elements.characterModal.classList.add('hidden');
    }

    async saveCharacter() {
        const id = this.elements.characterId.value;
        const name = this.elements.characterNameInput.value.trim();
        const preprompt = this.elements.characterPreprompt.value.trim();
        const voiceModel = this.elements.voiceModelSelect.value;
        const pthFile = this.elements.pthFile.files[0];
        const indexFile = this.elements.indexFile.files[0];

        if (!name || !preprompt) {
            alert('Please fill in all required fields');
            return;
        }

        try {
            let character;
            
            if (id) {
                // Update existing
                character = await api.updateCharacter(id, {
                    name,
                    system_prompt: preprompt,
                    voice_model: voiceModel
                });
                
                // Upload new voice models if provided
                if (pthFile) {
                    await api.uploadVoiceModel(id, pthFile, indexFile);
                }
            } else {
                // Create new
                character = await api.createCharacter(name, preprompt, voiceModel, pthFile, indexFile);
                
                // Create chat with this character
                const chat = await api.createChat(character.id, name);
                await this.loadChats();
                await this.selectChat(chat);
            }

            await this.loadCharacters();
            this.hideCharacterModal();
        } catch (error) {
            console.error('Failed to save character:', error);
            alert('Failed to save character: ' + error.message);
        }
    }

    async deleteCharacter() {
        const id = this.elements.characterId.value;
        if (!id) return;

        if (!confirm('Are you sure you want to delete this character? All associated chats will be deleted.')) {
            return;
        }

        try {
            await api.deleteCharacter(id);
            await this.loadChats();
            await this.loadCharacters();
            
            this.currentChat = null;
            this.currentCharacter = null;
            this.elements.chatView.classList.add('hidden');
            this.elements.emptyState.classList.remove('hidden');
            
            this.hideCharacterModal();
        } catch (error) {
            console.error('Failed to delete character:', error);
            alert('Failed to delete character: ' + error.message);
        }
    }

    // Utilities
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    window.app = new CognitiaApp();
    window.app.init().catch(console.error);
});
