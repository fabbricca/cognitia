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
        this.expectingAudioResponse = false; // Track if we sent audio and expect audio back

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
        
        // Initialize theme
        this.initTheme();

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
    
    initTheme() {
        const savedTheme = localStorage.getItem('theme') || 'light';
        this.setTheme(savedTheme);
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

            // Sidebar
            sidebar: document.getElementById('sidebar'),
            userAvatar: document.getElementById('user-avatar'),
            userAvatarImg: document.getElementById('user-avatar-img'),
            userInitial: document.getElementById('user-initial'),
            userName: document.getElementById('user-name'),
            connectionStatus: document.getElementById('connection-status'),
            logoutBtn: document.getElementById('logout-btn'),
            searchInput: document.getElementById('search-input'),

            // Chat list
            chatList: document.getElementById('chat-list'),
            newChatBtn: document.getElementById('new-chat-btn'),

            // Chat area
            chatArea: document.getElementById('chat-area'),
            emptyState: document.getElementById('empty-state'),
            chatView: document.getElementById('chat-view'),
            mobileBackBtn: document.getElementById('mobile-back-btn'),
            chatHeaderAvatar: document.getElementById('chat-header-avatar'),
            chatAvatarInitial: document.getElementById('chat-avatar-initial'),
            chatAvatarImg: document.getElementById('chat-avatar-img'),
            characterName: document.getElementById('character-name'),
            editCharacterBtn: document.getElementById('edit-character-btn'),
            messagesContainer: document.getElementById('messages-container'),

            // Input
            messageInput: document.getElementById('message-input'),
            sendBtn: document.getElementById('send-btn'),
            recordBtn: document.getElementById('record-btn'),
            callBtn: document.getElementById('call-btn'),
            recordingIndicator: document.getElementById('recording-indicator'),
            recordingTime: document.getElementById('recording-time'),
            
            // Call overlay
            callOverlay: document.getElementById('call-overlay'),
            callAvatar: document.getElementById('call-avatar'),
            callAvatarInitial: document.getElementById('call-avatar-initial'),
            callAvatarImg: document.getElementById('call-avatar-img'),
            callCharacterName: document.getElementById('call-character-name'),
            callStatus: document.getElementById('call-status'),
            callTimer: document.getElementById('call-timer'),
            endCallBtn: document.getElementById('end-call-btn'),
            muteBtn: document.getElementById('mute-btn'),
            speakerBtn: document.getElementById('speaker-btn'),

            // Character Modal
            characterModal: document.getElementById('character-modal'),
            modalTitle: document.getElementById('modal-title'),
            closeModal: document.getElementById('close-modal'),
            characterForm: document.getElementById('character-form'),
            characterId: document.getElementById('character-id'),
            avatarPreview: document.getElementById('avatar-preview'),
            avatarPreviewImg: document.getElementById('avatar-preview-img'),
            avatarFile: document.getElementById('avatar-file'),
            characterNameInput: document.getElementById('character-name-input'),
            characterPreprompt: document.getElementById('character-preprompt'),
            characterPersona: document.getElementById('character-persona'),
            voiceModelSelect: document.getElementById('voice-model-select'),
            pthFile: document.getElementById('pth-file'),
            indexFile: document.getElementById('index-file'),
            saveCharacter: document.getElementById('save-character'),
            deleteCharacter: document.getElementById('delete-character'),
            // Upload progress
            uploadProgressContainer: document.getElementById('upload-progress-container'),
            uploadProgressFill: document.getElementById('upload-progress-fill'),
            uploadProgressText: document.getElementById('upload-progress-text'),
            
            // Audio Preview Modal
            audioPreviewModal: document.getElementById('audio-preview-modal'),
            closeAudioPreview: document.getElementById('close-audio-preview'),
            previewPlayBtn: document.getElementById('preview-play-btn'),
            previewBars: document.getElementById('preview-bars'),
            previewTime: document.getElementById('preview-time'),
            previewAudio: document.getElementById('preview-audio'),
            previewCancelBtn: document.getElementById('preview-cancel-btn'),
            previewRerecordBtn: document.getElementById('preview-rerecord-btn'),
            previewSendBtn: document.getElementById('preview-send-btn'),
            
            // Settings Modal
            settingsBtn: document.getElementById('settings-btn'),
            settingsModal: document.getElementById('settings-modal'),
            closeSettings: document.getElementById('close-settings'),
            closeSettingsBtn: document.getElementById('close-settings-btn'),
            settingsUserAvatar: document.getElementById('settings-user-avatar'),
            settingsUserInitial: document.getElementById('settings-user-initial'),
            settingsUserAvatarImg: document.getElementById('settings-user-avatar-img'),
            userAvatarInput: document.getElementById('user-avatar-input'),
            changeUserAvatarBtn: document.getElementById('change-user-avatar-btn'),
            settingsEmail: document.getElementById('settings-email'),
            coreStatus: document.getElementById('core-status'),
            coreVersion: document.getElementById('core-version'),
            themeSelect: document.getElementById('theme-select'),
            
            // Toast container
            toastContainer: document.getElementById('toast-container')
        };
        
        // Store pending audio data for preview
        this.pendingAudioData = null;
        
        // Store user info
        this.currentUser = null;
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

        // Emoji button
        const emojiBtn = document.getElementById('emoji-btn');
        if (emojiBtn) {
            emojiBtn.addEventListener('click', () => this.showEmojiPicker());
        }

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

        // Audio Preview Modal
        this.elements.closeAudioPreview.addEventListener('click', () => this.hideAudioPreview());
        this.elements.previewCancelBtn.addEventListener('click', () => this.hideAudioPreview());
        this.elements.previewRerecordBtn.addEventListener('click', () => this.rerecordAudio());
        this.elements.previewSendBtn.addEventListener('click', () => this.sendPreviewedAudio());
        this.elements.previewPlayBtn.addEventListener('click', () => this.togglePreviewPlayback());
        this.elements.previewAudio.addEventListener('timeupdate', () => this.updatePreviewProgress());
        this.elements.previewAudio.addEventListener('ended', () => this.onPreviewEnded());
        this.elements.previewAudio.addEventListener('loadedmetadata', () => this.onPreviewLoaded());
        
        // Mobile back button
        this.elements.mobileBackBtn.addEventListener('click', () => this.showSidebar());
        
        // Avatar file input
        this.elements.avatarFile.addEventListener('change', (e) => this.handleAvatarSelect(e));
        
        // Search input
        this.elements.searchInput.addEventListener('input', (e) => this.filterChats(e.target.value));

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

        // Make chat header info clickable to edit character
        const chatHeaderInfo = document.querySelector('.chat-header-info');
        if (chatHeaderInfo) {
            chatHeaderInfo.addEventListener('click', () => {
                if (this.currentCharacter) {
                    this.showCharacterModal(this.currentCharacter);
                }
            });
        }

        // Close modal on outside click
        this.elements.characterModal.addEventListener('click', (e) => {
            if (e.target === this.elements.characterModal) {
                this.hideCharacterModal();
            }
        });

        // Settings modal
        this.elements.settingsBtn?.addEventListener('click', () => {
            this.showSettingsModal();
        });
        
        this.elements.closeSettings?.addEventListener('click', () => {
            this.hideSettingsModal();
        });
        
        this.elements.closeSettingsBtn?.addEventListener('click', () => {
            this.hideSettingsModal();
        });
        
        this.elements.settingsModal?.addEventListener('click', (e) => {
            if (e.target === this.elements.settingsModal) {
                this.hideSettingsModal();
            }
        });
        
        // User avatar upload
        this.elements.changeUserAvatarBtn?.addEventListener('click', () => {
            this.elements.userAvatarInput?.click();
        });
        
        this.elements.userAvatarInput?.addEventListener('change', async (e) => {
            const file = e.target.files?.[0];
            if (file) {
                await this.uploadUserAvatar(file);
            }
        });
        
        // Theme select
        this.elements.themeSelect?.addEventListener('change', (e) => {
            this.setTheme(e.target.value);
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideCharacterModal();
                this.hideSettingsModal();
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

        // Load user profile
        try {
            this.currentUser = await api.getProfile();
            this.updateUserUI();
        } catch (error) {
            console.error('Failed to load profile:', error);
        }

        // Connect WebSocket
        await this.connectWebSocket();

        // Load data
        await this.loadChats();
        await this.loadCharacters();
    }
    
    updateUserUI() {
        if (!this.currentUser) return;
        
        const email = this.currentUser.email || 'User';
        const initial = email.charAt(0).toUpperCase();
        
        this.elements.userName.textContent = email.split('@')[0];
        
        if (this.currentUser.avatar_url) {
            this.elements.userAvatarImg.src = this.currentUser.avatar_url;
            this.elements.userAvatarImg.classList.remove('hidden');
            this.elements.userInitial.classList.add('hidden');
        } else {
            this.elements.userInitial.textContent = initial;
            this.elements.userInitial.classList.remove('hidden');
            this.elements.userAvatarImg.classList.add('hidden');
        }
    }

    // WebSocket
    async connectWebSocket() {
        this.ws = new WebSocketManager(this.wsUrl);

        this.ws.on('connected', () => {
            this.elements.connectionStatus.textContent = 'Online';
            this.elements.connectionStatus.classList.add('online');
            
            // Authenticate
            this.ws.send({
                type: 'auth',
                token: api.token
            });
        });

        this.ws.on('disconnected', () => {
            this.elements.connectionStatus.textContent = 'Offline';
            this.elements.connectionStatus.classList.remove('online');
        });

        this.ws.on('error', (error) => {
            console.error('WebSocket error:', error);
        });

        // Handle incoming messages
        this.ws.on('typing', (msg) => {
            this.handleTypingIndicator(msg);
        });

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

            const name = chat.title || 'New Chat';
            const initial = name.charAt(0).toUpperCase();
            const avatarUrl = chat.character_avatar_url || '';
            const preview = this.formatChatPreview(chat.last_message);

            item.innerHTML = `
                <div class="chat-item-avatar">
                    ${avatarUrl ? `<img src="${avatarUrl}" alt="${name}">` : `<span>${initial}</span>`}
                </div>
                <div class="chat-item-content">
                    <div class="chat-item-name">${this.escapeHtml(name)}</div>
                    <div class="chat-item-preview">${preview}</div>
                </div>
                <div class="chat-item-meta">
                    <span class="chat-item-time">${this.formatChatTime(chat.updated_at)}</span>
                </div>
            `;

            item.addEventListener('click', () => this.selectChat(chat));
            this.elements.chatList.appendChild(item);
        }
    }

    formatChatPreview(lastMessage) {
        if (!lastMessage) {
            return '<span style="color: var(--text-muted);">Tap to start chatting</span>';
        }

        // Check if it's an audio message (data URI)
        if (lastMessage.startsWith('data:audio/')) {
            return '<span style="color: var(--text-muted);">🎤 Audio message</span>';
        }

        // Regular text message - truncate if too long
        const maxLength = 40;
        const escaped = this.escapeHtml(lastMessage);
        if (escaped.length > maxLength) {
            return escaped.substring(0, maxLength) + '...';
        }
        return escaped;
    }

    formatChatTime(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        // Today: show time
        if (messageDate.getTime() === today.getTime()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        }

        // Yesterday
        if (messageDate.getTime() === yesterday.getTime()) {
            return 'Yesterday';
        }

        // This week: show day name
        const daysDiff = Math.floor((today - messageDate) / (1000 * 60 * 60 * 24));
        if (daysDiff < 7) {
            return date.toLocaleDateString([], { weekday: 'short' });
        }

        // Older: show date
        return date.toLocaleDateString([], { day: 'numeric', month: 'numeric', year: '2-digit' });
    }

    formatRelativeTime(dateStr) {
        // Keep this for backwards compatibility
        return this.formatChatTime(dateStr);
    }
    
    filterChats(query) {
        const items = this.elements.chatList.querySelectorAll('.chat-item');
        const lowerQuery = query.toLowerCase();
        
        items.forEach(item => {
            const name = item.querySelector('.chat-item-name')?.textContent.toLowerCase() || '';
            if (name.includes(lowerQuery)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }
    
    // Mobile navigation
    showSidebar() {
        this.elements.sidebar.classList.remove('hidden-mobile');
    }
    
    hideSidebar() {
        this.elements.sidebar.classList.add('hidden-mobile');
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
        
        // Hide sidebar on mobile when chat is selected
        this.hideSidebar();
    }

    renderChatView() {
        this.elements.emptyState.classList.add('hidden');
        this.elements.chatView.classList.remove('hidden');
        this.elements.chatView.style.display = 'flex';

        // Update header
        const name = this.currentCharacter?.name || 'Unknown';
        this.elements.characterName.textContent = name;
        
        // Update avatar
        const avatarUrl = this.currentCharacter?.avatar_url;
        const initial = name.charAt(0).toUpperCase();
        
        if (avatarUrl) {
            this.elements.chatAvatarImg.src = avatarUrl;
            this.elements.chatAvatarImg.classList.remove('hidden');
            this.elements.chatAvatarInitial.classList.add('hidden');
        } else {
            this.elements.chatAvatarInitial.textContent = initial;
            this.elements.chatAvatarInitial.classList.remove('hidden');
            this.elements.chatAvatarImg.classList.add('hidden');
        }

        this.renderMessages();
    }

    renderMessages() {
        this.elements.messagesContainer.innerHTML = '';

        for (const msg of this.messages) {
            this.appendMessage(msg.role, msg.content, msg.audio_url, msg.created_at || msg.timestamp);
        }

        this.scrollToBottom();
    }

    appendMessage(role, content, audioUrl = null, timestamp = null) {
        const div = document.createElement('div');
        div.className = `message ${role === 'user' ? 'sent' : 'received'}`;

        // Get avatar info
        let avatarHtml = '';
        if (role === 'user') {
            const userAvatarUrl = this.currentUser?.avatar_url;
            const userInitial = (this.currentUser?.email?.charAt(0) || 'U').toUpperCase();
            avatarHtml = `<div class="message-avatar">${userAvatarUrl ? `<img src="${userAvatarUrl}" alt="You">` : userInitial}</div>`;
        } else {
            const charAvatarUrl = this.currentCharacter?.avatar_url;
            const charInitial = (this.currentCharacter?.name?.charAt(0) || 'A').toUpperCase();
            avatarHtml = `<div class="message-avatar">${charAvatarUrl ? `<img src="${charAvatarUrl}" alt="${this.currentCharacter?.name}">` : charInitial}</div>`;
        }

        // Format timestamp
        const timeStr = this.formatMessageTime(timestamp || new Date());

        let bubbleHtml = '';
        let isAudioMessage = false;

        // Check if content is an audio data URI (stored voice message)
        if (content && content.startsWith('data:audio/')) {
            // Content is audio - display as custom audio player
            bubbleHtml = `
                <div class="message-bubble audio-message">
                    ${this.createAudioPlayerHTML(content)}
                    <div class="message-meta">
                        <span class="message-time">${timeStr}</span>
                    </div>
                </div>
            `;
            isAudioMessage = true;
        } else {
            // Regular text content
            bubbleHtml = `
                <div class="message-bubble">
                    <div class="message-text">${this.escapeHtml(content)}</div>
                    <div class="message-meta">
                        <span class="message-time">${timeStr}</span>
                    </div>
                </div>
            `;
            
            if (audioUrl) {
                bubbleHtml += `
                    <div class="message-bubble audio-message">
                        ${this.createAudioPlayerHTML(audioUrl)}
                    </div>
                `;
                isAudioMessage = true;
            }
        }

        div.innerHTML = avatarHtml + bubbleHtml;
        
        if (this.elements.messagesContainer) {
            this.elements.messagesContainer.appendChild(div);
            
            // Initialize audio player if this is an audio message
            if (isAudioMessage) {
                const audioMessage = div.querySelector('.audio-message');
                if (audioMessage) {
                    this.initAudioPlayer(audioMessage);
                }
            }
            
            this.scrollToBottom();
        }
        return div;
    }
    
    formatMessageTime(date) {
        if (!(date instanceof Date) || isNaN(date)) date = new Date();
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    }

    appendStreamingMessage(role) {
        const div = document.createElement('div');
        div.className = `message ${role === 'user' ? 'sent' : 'received'}`;
        
        // Get avatar info
        let avatarHtml = '';
        if (role === 'user') {
            const userAvatarUrl = this.currentUser?.avatar_url;
            const userInitial = (this.currentUser?.email?.charAt(0) || 'U').toUpperCase();
            avatarHtml = `<div class="message-avatar">${userAvatarUrl ? `<img src="${userAvatarUrl}" alt="You">` : userInitial}</div>`;
        } else {
            const charAvatarUrl = this.currentCharacter?.avatar_url;
            const charInitial = (this.currentCharacter?.name?.charAt(0) || 'A').toUpperCase();
            avatarHtml = `<div class="message-avatar">${charAvatarUrl ? `<img src="${charAvatarUrl}" alt="${this.currentCharacter?.name}">` : charInitial}</div>`;
        }
        
        div.innerHTML = avatarHtml + '<div class="message-bubble"><div class="message-text"></div></div>';
        if (this.elements.messagesContainer) {
            this.elements.messagesContainer.appendChild(div);
        }
        return div;
    }

    updateStreamingMessage(element, content) {
        const contentDiv = element.querySelector('.message-text');
        if (contentDiv) {
            contentDiv.textContent = content;
        }
        this.scrollToBottom();
    }

    scrollToBottom() {
        if (this.elements.messagesContainer) {
            this.elements.messagesContainer.scrollTop = this.elements.messagesContainer.scrollHeight;
        }
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

        // Show typing indicator (will be replaced when first chunk arrives)
        this.showTypingIndicator();
        this.currentStreamingElement = null;
        this.currentStreamingText = '';

        // Send to WebSocket
        if (this.ws) {
            this.ws.sendText(text, this.currentChat.id, this.currentCharacter?.id);
        }
    }

    showTypingIndicator() {
        // Safety check - ensure container exists
        if (!this.elements.messagesContainer) {
            console.warn('Messages container not found, cannot show typing indicator');
            return;
        }
        
        this.hideTypingIndicator();
        
        const charAvatarUrl = this.currentCharacter?.avatar_url;
        const charInitial = (this.currentCharacter?.name?.charAt(0) || 'A').toUpperCase();
        const avatarHtml = `<div class="message-avatar">${charAvatarUrl ? `<img src="${charAvatarUrl}" alt="${this.currentCharacter?.name}">` : charInitial}</div>`;
        
        const indicator = document.createElement('div');
        indicator.className = 'message received';
        indicator.id = 'typing-indicator';
        indicator.innerHTML = `
            ${avatarHtml}
            <div class="typing-indicator">
                <div class="typing-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        this.elements.messagesContainer.appendChild(indicator);
        this.scrollToBottom();
    }

    hideTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    handleTypingIndicator(msg) {
        // Server sent typing indicator, show it if not already showing
        if (!document.getElementById('typing-indicator')) {
            this.showTypingIndicator();
        }
    }

    handleTextChunk(msg) {
        // Hide typing indicator on first chunk
        this.hideTypingIndicator();
        
        // Skip text if we're expecting audio response (user sent audio)
        if (this.expectingAudioResponse) {
            return;
        }
        
        // Each sentence is a separate message
        const sentence = msg.content;
        if (sentence && sentence.trim()) {
            // Create a new message element for this sentence
            this.appendMessage('assistant', sentence);
            
            // Save to database
            if (this.currentChat) {
                api.createMessage(this.currentChat.id, sentence, 'assistant').catch(console.error);
            }
            
            this.messages.push({ role: 'assistant', content: sentence });
        }
    }

    handleTextComplete(msg) {
        // Hide typing indicator
        this.hideTypingIndicator();
        
        // In sentence-by-sentence mode, messages were already created in handleTextChunk
        // This handler is mainly for cleanup and non-streaming fallback
        
        // Reset streaming state
        this.currentStreamingText = '';
        this.currentStreamingElement = null;
        
        // Reset audio expectation flag
        this.expectingAudioResponse = false;
    }

    handleAudioResponse(msg) {
        // Core sends 'content', but also support 'data' for backwards compatibility
        const audioData = msg.content || msg.data;
        const sampleRate = msg.sample_rate || 24000;
        
        if (audioData) {
            // Hide typing indicator
            this.hideTypingIndicator();
            
            if (this.isInCall) {
                // Phone call mode: auto-play audio in background
                this.audio.playAudio(audioData, 'pcm');
            } else {
                // Chat mode: display audio as a message with custom player
                // Convert PCM audio data to a WAV data URI (persists across reloads)
                const wavDataUri = this.pcmToWavDataUri(audioData, sampleRate);
                
                // Create a blob URL for playback (temporary, for this session)
                const audioUrl = this.dataUriToObjectUrl(wavDataUri);
                this.appendAudioMessage('assistant', audioUrl);
                
                // Save the data URI to database (persists across reloads)
                if (this.currentChat) {
                    api.createMessage(this.currentChat.id, wavDataUri, 'assistant').catch(console.error);
                }
            }
        }
    }
    
    // Convert data URI to object URL for playback
    dataUriToObjectUrl(dataUri) {
        const [header, base64] = dataUri.split(',');
        const mimeType = header.match(/:(.*?);/)[1];
        const bytes = atob(base64);
        const buffer = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) {
            buffer[i] = bytes.charCodeAt(i);
        }
        const blob = new Blob([buffer], { type: mimeType });
        return URL.createObjectURL(blob);
    }
    
    // Convert PCM base64 to WAV data URI for persistence
    pcmToWavDataUri(base64Pcm, sampleRate = 24000) {
        // Decode base64 PCM
        const pcmBytes = atob(base64Pcm);
        const pcmLength = pcmBytes.length;
        
        // WAV header is 44 bytes
        const wavLength = 44 + pcmLength;
        const buffer = new ArrayBuffer(wavLength);
        const view = new DataView(buffer);
        
        // Write WAV header
        // "RIFF" chunk descriptor
        this.writeString(view, 0, 'RIFF');
        view.setUint32(4, wavLength - 8, true); // File size - 8
        this.writeString(view, 8, 'WAVE');
        
        // "fmt " sub-chunk
        this.writeString(view, 12, 'fmt ');
        view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
        view.setUint16(20, 1, true); // AudioFormat (1 = PCM)
        view.setUint16(22, 1, true); // NumChannels (1 = mono)
        view.setUint32(24, sampleRate, true); // SampleRate
        view.setUint32(28, sampleRate * 2, true); // ByteRate (SampleRate * NumChannels * BitsPerSample/8)
        view.setUint16(32, 2, true); // BlockAlign (NumChannels * BitsPerSample/8)
        view.setUint16(34, 16, true); // BitsPerSample
        
        // "data" sub-chunk
        this.writeString(view, 36, 'data');
        view.setUint32(40, pcmLength, true); // Subchunk2Size
        
        // Write PCM data
        const uint8Array = new Uint8Array(buffer);
        for (let i = 0; i < pcmLength; i++) {
            uint8Array[44 + i] = pcmBytes.charCodeAt(i);
        }
        
        // Convert to base64 data URI for persistence
        let binary = '';
        for (let i = 0; i < uint8Array.length; i++) {
            binary += String.fromCharCode(uint8Array[i]);
        }
        const base64 = btoa(binary);
        return `data:audio/wav;base64,${base64}`;
    }
    
    // Helper to write string to DataView
    writeString(view, offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }

    handleTranscription(msg) {
        // Backend sent transcription of user's audio
        // We already displayed and saved the audio message in stopRecording()
        // Just log the transcription - don't duplicate the message
        if (msg.text) {
            console.log('Transcription received:', msg.text);
            // Optionally, we could update the audio message to show the transcription
            // but for now, the audio message itself is sufficient
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
        
        try {
            const audioData = await this.audio.stopRecording();
            if (audioData && this.ws && this.currentChat) {
                // Store pending audio data for preview
                const audioBlob = this.base64ToBlob(audioData.data, 'audio/webm');
                const audioUrl = URL.createObjectURL(audioBlob);
                
                this.pendingAudioData = {
                    data: audioData.data,
                    format: audioData.format,
                    sampleRate: audioData.sampleRate,
                    blob: audioBlob,
                    url: audioUrl
                };
                
                // Show audio preview modal instead of immediately sending
                this.showAudioPreview(audioUrl);
            }
        } catch (error) {
            console.error('Error processing audio recording:', error);
            this.expectingAudioResponse = false;
        }
    }
    
    // =========================================================================
    // Audio Preview Modal (WhatsApp-style)
    // =========================================================================
    
    showAudioPreview(audioUrl) {
        // Generate waveform bars
        const barCount = 30;
        let barsHTML = '';
        for (let i = 0; i < barCount; i++) {
            const height = Math.floor(Math.random() * 30) + 10; // 10-40px
            barsHTML += `<div class="bar" style="height: ${height}px;"></div>`;
        }
        this.elements.previewBars.innerHTML = barsHTML;
        
        // Set audio source
        this.elements.previewAudio.src = audioUrl;
        this.elements.previewTime.textContent = '0:00';
        
        // Reset play button icon
        this.elements.previewPlayBtn.innerHTML = `
            <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
        `;
        
        // Show modal
        this.elements.audioPreviewModal.classList.add('active');
    }
    
    hideAudioPreview() {
        // Stop playback
        this.elements.previewAudio.pause();
        this.elements.previewAudio.currentTime = 0;
        
        // Clean up pending audio data
        if (this.pendingAudioData?.url) {
            URL.revokeObjectURL(this.pendingAudioData.url);
        }
        this.pendingAudioData = null;
        
        // Hide modal
        this.elements.audioPreviewModal.classList.remove('active');
    }
    
    togglePreviewPlayback() {
        const audio = this.elements.previewAudio;
        if (audio.paused) {
            audio.play();
            this.elements.previewPlayBtn.innerHTML = `
                <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16"></rect>
                    <rect x="14" y="4" width="4" height="16"></rect>
                </svg>
            `;
        } else {
            audio.pause();
            this.elements.previewPlayBtn.innerHTML = `
                <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
            `;
        }
    }
    
    updatePreviewProgress() {
        const audio = this.elements.previewAudio;
        if (audio.duration) {
            this.elements.previewTime.textContent = this.formatTime(audio.currentTime);
            
            // Update bar colors based on progress
            const bars = this.elements.previewBars.querySelectorAll('.bar');
            const progressPercent = (audio.currentTime / audio.duration) * 100;
            bars.forEach((bar, index) => {
                const barPercent = (index / bars.length) * 100;
                if (barPercent <= progressPercent) {
                    bar.style.opacity = '1';
                } else {
                    bar.style.opacity = '0.4';
                }
            });
        }
    }
    
    onPreviewEnded() {
        this.elements.previewPlayBtn.innerHTML = `
            <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
        `;
        // Reset bar colors
        const bars = this.elements.previewBars.querySelectorAll('.bar');
        bars.forEach(bar => bar.style.opacity = '0.4');
    }
    
    onPreviewLoaded() {
        const audio = this.elements.previewAudio;
        this.elements.previewTime.textContent = this.formatTime(audio.duration);
    }
    
    formatTime(seconds) {
        if (!seconds || !isFinite(seconds) || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    formatMessageTime(timestamp) {
        // Format message timestamp WhatsApp-style
        const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
        if (isNaN(date.getTime())) {
            date = new Date(); // Fallback to current time
        }

        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        // Today: show time only
        if (messageDate.getTime() === today.getTime()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        }

        // Yesterday: show "Yesterday" + time
        if (messageDate.getTime() === yesterday.getTime()) {
            const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            return `Yesterday, ${time}`;
        }

        // This week: show day name + time
        const daysDiff = Math.floor((today - messageDate) / (1000 * 60 * 60 * 24));
        if (daysDiff < 7) {
            const dayName = date.toLocaleDateString([], { weekday: 'short' });
            const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            return `${dayName}, ${time}`;
        }

        // Older: show date + time
        const dateStr = date.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
        const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        return `${dateStr}, ${time}`;
    }
    
    rerecordAudio() {
        // Hide preview modal
        this.hideAudioPreview();
        
        // Start new recording automatically
        setTimeout(() => this.startRecording(), 100);
    }
    
    sendPreviewedAudio() {
        if (!this.pendingAudioData || !this.ws || !this.currentChat) return;
        
        const { data, format, sampleRate, url } = this.pendingAudioData;
        
        // Display user's audio message in chat
        this.appendAudioMessage('user', url);
        
        // Save user's audio message to database
        const audioDataUri = `data:audio/webm;base64,${data}`;
        api.createMessage(this.currentChat.id, audioDataUri, 'user').catch(console.error);
        
        // Show typing indicator for AI response
        this.showTypingIndicator();
        
        // Mark that we expect audio response
        this.expectingAudioResponse = true;
        
        // Send to backend
        this.ws.sendAudio(
            data,
            format,
            sampleRate,
            this.currentChat.id,
            this.currentCharacter?.id
        );
        
        // Hide modal (but don't revoke URL since it's now in the chat)
        this.elements.previewAudio.pause();
        this.pendingAudioData = null;
        this.elements.audioPreviewModal.classList.remove('active');
    }
    
    // Helper to convert base64 to Blob
    base64ToBlob(base64, mimeType) {
        const byteCharacters = atob(base64);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        return new Blob([byteArray], { type: mimeType });
    }
    
    // Create custom audio player HTML
    createAudioPlayerHTML(audioUrl) {
        // Generate random waveform bars for visual effect
        const barCount = 25;
        let barsHTML = '';
        for (let i = 0; i < barCount; i++) {
            const height = Math.floor(Math.random() * 16) + 8; // 8-24px
            barsHTML += `<div class="audio-bar" style="height: ${height}px;"></div>`;
        }
        
        return `
            <div class="audio-player" data-audio-url="${audioUrl}">
                <button class="audio-play-btn" title="Play/Pause">▶</button>
                <div class="audio-waveform">
                    <div class="audio-bars">${barsHTML}</div>
                    <input type="range" class="audio-progress" value="0" min="0" max="100" step="0.1">
                </div>
                <span class="audio-time">0:00</span>
                <span class="audio-mic-icon">🎤</span>
            </div>
            <audio preload="metadata">
                <source src="${audioUrl}" type="audio/webm">
                <source src="${audioUrl}" type="audio/wav">
            </audio>
        `;
    }
    
    // Initialize audio player controls
    initAudioPlayer(container) {
        const audio = container.querySelector('audio');
        const playBtn = container.querySelector('.audio-play-btn');
        const progress = container.querySelector('.audio-progress');
        const timeDisplay = container.querySelector('.audio-time');
        const bars = container.querySelectorAll('.audio-bar');
        
        if (!audio || !playBtn) return;
        
        // Format time as M:SS
        const formatTime = (seconds) => {
            if (!seconds || !isFinite(seconds) || isNaN(seconds)) return '0:00';
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        };
        
        // Update time display when metadata loads
        audio.addEventListener('loadedmetadata', () => {
            if (isFinite(audio.duration)) {
                timeDisplay.textContent = formatTime(audio.duration);
                progress.max = audio.duration;
            }
        });
        
        // Fallback for when duration becomes available later (blob URLs)
        audio.addEventListener('durationchange', () => {
            if (isFinite(audio.duration) && audio.duration > 0) {
                timeDisplay.textContent = formatTime(audio.duration);
                progress.max = audio.duration;
            }
        });
        
        // Play/Pause toggle
        playBtn.addEventListener('click', () => {
            if (audio.paused) {
                // Pause any other playing audio
                document.querySelectorAll('audio').forEach(a => {
                    if (a !== audio && !a.paused) {
                        a.pause();
                        const otherPlayBtn = a.closest('.audio-message')?.querySelector('.audio-play-btn');
                        if (otherPlayBtn) {
                            otherPlayBtn.classList.remove('playing');
                            otherPlayBtn.textContent = '▶';
                        }
                    }
                });
                audio.play();
                playBtn.classList.add('playing');
                playBtn.textContent = '⏸';
            } else {
                audio.pause();
                playBtn.classList.remove('playing');
                playBtn.textContent = '▶';
            }
        });
        
        // Update progress as audio plays
        audio.addEventListener('timeupdate', () => {
            progress.value = audio.currentTime;
            timeDisplay.textContent = formatTime(audio.currentTime);
            
            // Update waveform bars to show progress
            const progressPercent = (audio.currentTime / audio.duration) * 100;
            bars.forEach((bar, index) => {
                const barPercent = (index / bars.length) * 100;
                if (barPercent <= progressPercent) {
                    bar.classList.add('played');
                } else {
                    bar.classList.remove('played');
                }
            });
        });
        
        // Seek when progress bar is changed
        progress.addEventListener('input', () => {
            audio.currentTime = progress.value;
        });
        
        // Reset when audio ends
        audio.addEventListener('ended', () => {
            playBtn.classList.remove('playing');
            playBtn.textContent = '▶';
            progress.value = 0;
            timeDisplay.textContent = formatTime(audio.duration);
            bars.forEach(bar => bar.classList.remove('played'));
        });
    }
    
    // Append audio message (for voice messages)
    appendAudioMessage(role, audioUrl) {
        const div = document.createElement('div');
        div.className = `message ${role === 'user' ? 'sent' : 'received'}`;
        
        // Get avatar info
        let avatarHtml = '';
        if (role === 'user') {
            const userAvatarUrl = this.currentUser?.avatar_url;
            const userInitial = (this.currentUser?.email?.charAt(0) || 'U').toUpperCase();
            avatarHtml = `<div class="message-avatar">${userAvatarUrl ? `<img src="${userAvatarUrl}" alt="You">` : userInitial}</div>`;
        } else {
            const charAvatarUrl = this.currentCharacter?.avatar_url;
            const charInitial = (this.currentCharacter?.name?.charAt(0) || 'A').toUpperCase();
            avatarHtml = `<div class="message-avatar">${charAvatarUrl ? `<img src="${charAvatarUrl}" alt="${this.currentCharacter?.name}">` : charInitial}</div>`;
        }
        
        div.innerHTML = `
            ${avatarHtml}
            <div class="message-bubble audio-message">
                ${this.createAudioPlayerHTML(audioUrl)}
                <div class="message-meta">
                    <span class="message-time">${this.formatMessageTime(new Date())}</span>
                </div>
            </div>
        `;
        if (this.elements.messagesContainer) {
            this.elements.messagesContainer.appendChild(div);
            this.initAudioPlayer(div.querySelector('.audio-message'));
            this.scrollToBottom();
        }
        return div;
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
        this.elements.characterModal.classList.add('active');
        
        if (character) {
            this.elements.modalTitle.textContent = 'Edit Character';
            this.elements.characterId.value = character.id;
            this.elements.characterNameInput.value = character.name;
            this.elements.characterPreprompt.value = character.system_prompt;
            if (this.elements.characterPersona) {
                this.elements.characterPersona.value = character.persona_prompt || '';
            }
            this.elements.voiceModelSelect.value = character.voice_model || 'glados';
            this.elements.deleteCharacter.classList.remove('hidden');
            
            // Show avatar if exists
            if (character.avatar_url) {
                this.elements.avatarPreviewImg.src = character.avatar_url;
                this.elements.avatarPreviewImg.classList.remove('hidden');
                this.elements.avatarPreview.querySelector('svg')?.classList.add('hidden');
            } else {
                this.elements.avatarPreviewImg.classList.add('hidden');
                this.elements.avatarPreview.querySelector('svg')?.classList.remove('hidden');
            }
        } else {
            this.elements.modalTitle.textContent = 'New Character';
            this.elements.characterId.value = '';
            this.elements.characterNameInput.value = '';
            this.elements.characterPreprompt.value = '';
            if (this.elements.characterPersona) {
                this.elements.characterPersona.value = '';
            }
            this.elements.voiceModelSelect.value = 'glados';
            this.elements.pthFile.value = '';
            this.elements.indexFile.value = '';
            this.elements.avatarFile.value = '';
            this.elements.avatarPreviewImg.classList.add('hidden');
            this.elements.avatarPreview.querySelector('svg')?.classList.remove('hidden');
            this.elements.deleteCharacter.classList.add('hidden');
        }
    }

    hideCharacterModal() {
        this.elements.characterModal.classList.remove('active');
    }
    
    // Settings Modal
    async showSettingsModal() {
        // Show modal
        this.elements.settingsModal?.classList.add('active');
        
        // Load user info
        if (this.currentUser) {
            this.elements.settingsEmail.value = this.currentUser.email || '';
            
            // Update avatar display
            const initial = (this.currentUser.email || 'U')[0].toUpperCase();
            this.elements.settingsUserInitial.textContent = initial;
            
            if (this.currentUser.avatar_url) {
                this.elements.settingsUserAvatarImg.src = this.currentUser.avatar_url;
                this.elements.settingsUserAvatarImg.classList.remove('hidden');
                this.elements.settingsUserInitial.classList.add('hidden');
            } else {
                this.elements.settingsUserAvatarImg.classList.add('hidden');
                this.elements.settingsUserInitial.classList.remove('hidden');
            }
        }
        
        // Load current theme
        const savedTheme = localStorage.getItem('theme') || 'light';
        this.elements.themeSelect.value = savedTheme;
        
        // Check core status
        this.checkCoreStatus();
    }
    
    hideSettingsModal() {
        this.elements.settingsModal?.classList.remove('active');
    }
    
    async checkCoreStatus() {
        try {
            const status = await api.getCoreStatus();
            if (status.available) {
                this.elements.coreStatus.textContent = 'Online';
                this.elements.coreStatus.classList.add('online');
                this.elements.coreStatus.classList.remove('offline');
                this.elements.coreVersion.textContent = status.version || 'Unknown';
            } else {
                this.elements.coreStatus.textContent = 'Offline';
                this.elements.coreStatus.classList.add('offline');
                this.elements.coreStatus.classList.remove('online');
                this.elements.coreVersion.textContent = '-';
            }
        } catch (error) {
            this.elements.coreStatus.textContent = 'Error';
            this.elements.coreStatus.classList.add('offline');
            this.elements.coreVersion.textContent = '-';
        }
    }
    
    async uploadUserAvatar(file) {
        // Validate file size
        if (file.size > 2 * 1024 * 1024) {
            this.showToast('Image must be less than 2MB', 'error');
            return;
        }
        
        try {
            this.showToast('Uploading avatar...', 'info');
            const updatedUser = await api.uploadUserAvatar(file);
            this.currentUser = updatedUser;
            
            // Update settings modal
            if (updatedUser.avatar_url) {
                this.elements.settingsUserAvatarImg.src = updatedUser.avatar_url;
                this.elements.settingsUserAvatarImg.classList.remove('hidden');
                this.elements.settingsUserInitial.classList.add('hidden');
            }
            
            // Update sidebar
            this.updateUserDisplay(updatedUser);
            
            this.showToast('Avatar updated!', 'success');
        } catch (error) {
            console.error('Avatar upload failed:', error);
            this.showToast('Failed to upload avatar: ' + error.message, 'error');
        }
        
        // Clear input
        this.elements.userAvatarInput.value = '';
    }
    
    setTheme(theme) {
        if (theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
        localStorage.setItem('theme', theme);
    }
    
    updateUserDisplay(user) {
        const initial = (user.email || 'U')[0].toUpperCase();
        this.elements.userInitial.textContent = initial;
        this.elements.userName.textContent = user.email?.split('@')[0] || 'User';
        
        if (user.avatar_url) {
            this.elements.userAvatarImg.src = user.avatar_url;
            this.elements.userAvatarImg.classList.remove('hidden');
            this.elements.userInitial.classList.add('hidden');
        } else {
            this.elements.userAvatarImg.classList.add('hidden');
            this.elements.userInitial.classList.remove('hidden');
        }
    }
    
    handleAvatarSelect(e) {
        const file = e.target.files[0];
        if (file) {
            // Validate file size (2MB max)
            if (file.size > 2 * 1024 * 1024) {
                this.showToast('Image must be less than 2MB', 'error');
                e.target.value = '';
                return;
            }
            
            // Preview image
            const reader = new FileReader();
            reader.onload = (event) => {
                this.elements.avatarPreviewImg.src = event.target.result;
                this.elements.avatarPreviewImg.classList.remove('hidden');
                this.elements.avatarPreview.querySelector('svg')?.classList.add('hidden');
            };
            reader.readAsDataURL(file);
        }
    }
    
    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        this.elements.toastContainer.appendChild(toast);
        
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    async saveCharacter() {
        const id = this.elements.characterId.value;
        const name = this.elements.characterNameInput.value.trim();
        const preprompt = this.elements.characterPreprompt.value.trim();
        const personaPrompt = this.elements.characterPersona?.value.trim() || '';
        const voiceModel = this.elements.voiceModelSelect.value;
        const pthFile = this.elements.pthFile.files[0];
        const indexFile = this.elements.indexFile.files[0];
        const avatarFile = this.elements.avatarFile.files[0];

        if (!name || !preprompt) {
            this.showToast('Please fill in all required fields', 'error');
            return;
        }

        // Helper to update upload progress UI
        const updateProgress = (percent) => {
            this.elements.uploadProgressFill.style.width = `${percent}%`;
            this.elements.uploadProgressText.textContent = `${percent}%`;
        };

        // Helper to show/hide progress bar
        const showProgress = (show) => {
            if (show) {
                this.elements.uploadProgressContainer.classList.remove('hidden');
                updateProgress(0);
            } else {
                this.elements.uploadProgressContainer.classList.add('hidden');
            }
        };

        try {
            let character;
            
            this.elements.saveCharacter.disabled = true;
            this.elements.saveCharacter.textContent = 'Saving...';
            
            if (id) {
                // Update existing
                character = await api.updateCharacter(id, {
                    name,
                    system_prompt: preprompt,
                    persona_prompt: personaPrompt || null,
                    voice_model: voiceModel
                });
                
                // Upload avatar if provided
                if (avatarFile) {
                    await api.uploadCharacterAvatar(id, avatarFile);
                }
                
                // Upload new voice models if provided
                if (pthFile) {
                    showProgress(true);
                    this.elements.saveCharacter.textContent = 'Uploading...';
                    
                    await api.uploadVoiceModel(id, pthFile, indexFile, updateProgress);
                    
                    showProgress(false);
                }
            } else {
                // Create new character first
                character = await api.createCharacter(name, preprompt, personaPrompt || null, voiceModel);
                
                // Upload avatar if provided
                if (avatarFile) {
                    await api.uploadCharacterAvatar(character.id, avatarFile);
                }
                
                // Upload voice models if provided
                if (pthFile) {
                    showProgress(true);
                    this.elements.saveCharacter.textContent = 'Uploading...';
                    
                    await api.uploadVoiceModel(character.id, pthFile, indexFile, updateProgress);
                    
                    showProgress(false);
                }
                
                // Create chat with this character
                const chat = await api.createChat(character.id, name);
                await this.loadChats();
                await this.selectChat(chat);
            }

            await this.loadCharacters();
            this.hideCharacterModal();
            this.showToast('Character saved successfully', 'success');
            
            this.elements.saveCharacter.disabled = false;
            this.elements.saveCharacter.textContent = 'Save Character';
        } catch (error) {
            console.error('Failed to save character:', error);
            this.showToast('Failed to save character: ' + error.message, 'error');
            
            // Reset UI on error
            this.elements.saveCharacter.disabled = false;
            this.elements.saveCharacter.textContent = 'Save Character';
            this.elements.uploadProgressContainer.classList.add('hidden');
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

    // Emoji picker
    showEmojiPicker() {
        const emojis = ['😊', '😂', '❤️', '👍', '👏', '🙏', '😍', '🎉', '🔥', '✨', '💯', '🤔', '😎', '🥰', '😢', '😭', '🤗', '🙌', '👀', '💪', '🎊', '🌟', '💖', '😅', '🤣', '😏', '🥺', '😳', '🤩', '😱'];

        // Create a simple emoji picker
        const picker = document.createElement('div');
        picker.className = 'emoji-picker';
        picker.style.cssText = `
            position: absolute;
            bottom: 80px;
            left: 20px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 12px;
            display: grid;
            grid-template-columns: repeat(8, 1fr);
            gap: 8px;
            box-shadow: var(--shadow-lg);
            z-index: 1000;
            animation: slideUp 0.2s ease-out;
        `;

        emojis.forEach(emoji => {
            const btn = document.createElement('button');
            btn.textContent = emoji;
            btn.style.cssText = `
                font-size: 24px;
                width: 40px;
                height: 40px;
                border: none;
                background: transparent;
                cursor: pointer;
                border-radius: var(--radius-sm);
                transition: var(--transition-smooth);
            `;
            btn.onmouseover = () => btn.style.background = 'var(--accent-light)';
            btn.onmouseout = () => btn.style.background = 'transparent';
            btn.onclick = () => {
                this.elements.messageInput.value += emoji;
                this.elements.messageInput.focus();
                picker.remove();
            };
            picker.appendChild(btn);
        });

        // Close picker when clicking outside
        const closeOnClickOutside = (e) => {
            if (!picker.contains(e.target) && e.target.id !== 'emoji-btn') {
                picker.remove();
                document.removeEventListener('click', closeOnClickOutside);
            }
        };

        // Remove existing picker if any
        const existingPicker = document.querySelector('.emoji-picker');
        if (existingPicker) {
            existingPicker.remove();
        } else {
            // Add picker to chat input area
            const inputArea = document.querySelector('.chat-input-area');
            if (inputArea) {
                inputArea.style.position = 'relative';
                inputArea.appendChild(picker);
                setTimeout(() => document.addEventListener('click', closeOnClickOutside), 100);
            }
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
