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
        this.pendingUserAudio = null;        // Pending user audio awaiting transcription
        this.pendingAssistantText = '';      // Accumulated text for audio responses

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

            // Usage widget
            usageWidget: document.getElementById('usage-widget'),
            usagePlan: document.getElementById('usage-plan'),
            messagesUsage: document.getElementById('messages-usage'),
            messagesProgress: document.getElementById('messages-progress'),
            audioUsage: document.getElementById('audio-usage'),
            audioProgress: document.getElementById('audio-progress'),
            usageUpgradeBtn: document.getElementById('usage-upgrade-btn'),

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
            promptTemplateSelect: document.getElementById('prompt-template-select'),
            voiceModelSelect: document.getElementById('voice-model-select'),
            rvcModelSelect: document.getElementById('rvc-model-select'),
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
            
            // Memory Modal
            memoryBtn: document.getElementById('memory-btn'),
            memoryModal: document.getElementById('memory-modal'),
            closeMemoryModal: document.getElementById('close-memory-modal'),
            memoryTabs: document.querySelectorAll('.memory-tab'),
            memoryTabContents: document.querySelectorAll('.memory-tab-content'),
            // Graph tab
            graphSearch: document.getElementById('graph-search'),
            graphRefreshBtn: document.getElementById('graph-refresh-btn'),
            graphNodesList: document.getElementById('graph-nodes-list'),
            graphEdgesList: document.getElementById('graph-edges-list'),
            graphDetails: document.getElementById('graph-details'),
            // Relationship tab
            relStage: document.getElementById('rel-stage'),
            relStageSelect: document.getElementById('rel-stage-select'),
            relTrustBar: document.getElementById('rel-trust-bar'),
            relTrustValue: document.getElementById('rel-trust-value'),
            relTrustSlider: document.getElementById('rel-trust-slider'),
            relConversations: document.getElementById('rel-conversations'),
            relMessages: document.getElementById('rel-messages'),
            relFirstChat: document.getElementById('rel-first-chat'),
            editRelationshipBtn: document.getElementById('edit-relationship-btn'),
            saveRelationshipBtn: document.getElementById('save-relationship-btn'),
            cancelRelationshipBtn: document.getElementById('cancel-relationship-btn'),
            insideJokesList: document.getElementById('inside-jokes-list'),
            milestonesList: document.getElementById('milestones-list'),
            // Facts tab
            factsCategoryFilter: document.getElementById('facts-category-filter'),
            addFactBtn: document.getElementById('add-fact-btn'),
            factsList: document.getElementById('facts-list'),
            // Memories tab
            memoriesTypeFilter: document.getElementById('memories-type-filter'),
            memoriesList: document.getElementById('memories-list'),
            // Diary tab
            diaryTypeFilter: document.getElementById('diary-type-filter'),
            diaryList: document.getElementById('diary-list'),
            // Fact Edit Modal
            factEditModal: document.getElementById('fact-edit-modal'),
            closeFactEditModal: document.getElementById('close-fact-edit-modal'),
            factEditForm: document.getElementById('fact-edit-form'),
            factEditId: document.getElementById('fact-edit-id'),
            factEditTitle: document.getElementById('fact-edit-title'),
            factEditCategory: document.getElementById('fact-edit-category'),
            factEditKey: document.getElementById('fact-edit-key'),
            factEditValue: document.getElementById('fact-edit-value'),
            factEditConfidence: document.getElementById('fact-edit-confidence'),
            cancelFactEditBtn: document.getElementById('cancel-fact-edit-btn'),
            saveFactEditBtn: document.getElementById('save-fact-edit-btn'),
            // Memory Edit Modal
            memoryEditModal: document.getElementById('memory-edit-modal'),
            closeMemoryEditModal: document.getElementById('close-memory-edit-modal'),
            memoryEditForm: document.getElementById('memory-edit-form'),
            memoryEditId: document.getElementById('memory-edit-id'),
            memoryEditSummary: document.getElementById('memory-edit-summary'),
            memoryEditContent: document.getElementById('memory-edit-content'),
            memoryEditTone: document.getElementById('memory-edit-tone'),
            memoryEditImportance: document.getElementById('memory-edit-importance'),
            cancelMemoryEditBtn: document.getElementById('cancel-memory-edit-btn'),
            saveMemoryEditBtn: document.getElementById('save-memory-edit-btn'),
            
            // Toast container
            toastContainer: document.getElementById('toast-container')
        };
        
        // Store pending audio data for preview
        this.pendingAudioData = null;
        
        // Store user info
        this.currentUser = null;
    }

    bindEvents() {
        // Global click handler to close message action menus
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.message-actions')) {
                document.querySelectorAll('.message-actions-menu.show').forEach(m => m.classList.remove('show'));
            }
        });

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

        // Auto-resize textarea as user types
        this.elements.messageInput.addEventListener('input', () => {
            const textarea = this.elements.messageInput;
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
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

        // Usage upgrade button
        if (this.elements.usageUpgradeBtn) {
            this.elements.usageUpgradeBtn.addEventListener('click', () => {
                window.location.href = '/pricing.html';
            });
        }

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

        // Memory modal
        this.elements.memoryBtn?.addEventListener('click', () => {
            this.showMemoryModal();
        });
        
        this.elements.closeMemoryModal?.addEventListener('click', () => {
            this.hideMemoryModal();
        });
        
        this.elements.memoryModal?.addEventListener('click', (e) => {
            if (e.target === this.elements.memoryModal) {
                this.hideMemoryModal();
            }
        });
        
        // Memory tabs
        this.elements.memoryTabs?.forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchMemoryTab(tab.dataset.tab);
            });
        });

        // Graph events
        this.elements.graphRefreshBtn?.addEventListener('click', () => {
            this.loadGraph();
        });

        this.elements.graphSearch?.addEventListener('input', () => {
            this.renderGraphNodes();
        });
        
        // Relationship edit
        this.elements.editRelationshipBtn?.addEventListener('click', () => {
            this.toggleRelationshipEdit(true);
        });
        
        this.elements.saveRelationshipBtn?.addEventListener('click', () => {
            this.saveRelationship();
        });
        
        this.elements.cancelRelationshipBtn?.addEventListener('click', () => {
            this.toggleRelationshipEdit(false);
            this.loadRelationship(); // Reset to saved values
        });
        
        // Facts filter
        this.elements.factsCategoryFilter?.addEventListener('change', () => {
            this.loadFacts();
        });
        
        this.elements.addFactBtn?.addEventListener('click', () => {
            this.showFactEditModal(null); // null = new fact
        });
        
        // Memories filter
        this.elements.memoriesTypeFilter?.addEventListener('change', () => {
            this.loadMemories();
        });
        
        // Diary filter
        this.elements.diaryTypeFilter?.addEventListener('change', () => {
            this.loadDiary();
        });
        
        // Fact edit modal
        this.elements.closeFactEditModal?.addEventListener('click', () => {
            this.hideFactEditModal();
        });
        
        this.elements.cancelFactEditBtn?.addEventListener('click', () => {
            this.hideFactEditModal();
        });
        
        this.elements.saveFactEditBtn?.addEventListener('click', () => {
            this.saveFact();
        });
        
        this.elements.factEditModal?.addEventListener('click', (e) => {
            if (e.target === this.elements.factEditModal) {
                this.hideFactEditModal();
            }
        });
        
        // Memory edit modal
        this.elements.closeMemoryEditModal?.addEventListener('click', () => {
            this.hideMemoryEditModal();
        });
        
        this.elements.cancelMemoryEditBtn?.addEventListener('click', () => {
            this.hideMemoryEditModal();
        });
        
        this.elements.saveMemoryEditBtn?.addEventListener('click', () => {
            this.saveMemory();
        });
        
        this.elements.memoryEditModal?.addEventListener('click', (e) => {
            if (e.target === this.elements.memoryEditModal) {
                this.hideMemoryEditModal();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideCharacterModal();
                this.hideSettingsModal();
                this.hideMemoryModal();
                this.hideFactEditModal();
                this.hideMemoryEditModal();
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
        await this.loadUsage();
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

        this.ws.on('user_transcription', (msg) => {
            this.handleUserTranscription(msg);
        });

        this.ws.on('memory_update', (msg) => {
            this.handleMemoryUpdate(msg);
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

    async loadUsage() {
        try {
            const usage = await api.request('GET', '/api/subscription/usage');

            // Show widget
            this.elements.usageWidget.classList.remove('hidden');

            // Update plan name
            this.elements.usagePlan.textContent = usage.plan.display_name;

            // Update messages
            const messagesUsed = usage.usage.messages;
            const messagesLimit = usage.limits.messages;
            const messagesPercent = usage.percentage.messages;
            this.elements.messagesUsage.textContent = `${messagesUsed} / ${messagesLimit}`;
            this.elements.messagesProgress.style.width = `${Math.min(messagesPercent, 100)}%`;

            // Update audio
            const audioUsed = usage.usage.audio_minutes.toFixed(1);
            const audioLimit = usage.limits.audio_minutes;
            const audioPercent = usage.percentage.audio;
            this.elements.audioUsage.textContent = `${audioUsed} / ${audioLimit} min`;
            this.elements.audioProgress.style.width = `${Math.min(audioPercent, 100)}%`;

            // Color code progress bars
            this.updateProgressColor(this.elements.messagesProgress, messagesPercent);
            this.updateProgressColor(this.elements.audioProgress, audioPercent);

            // Show upgrade button if approaching limit
            if (messagesPercent >= 80 || audioPercent >= 80) {
                this.elements.usageUpgradeBtn.classList.remove('hidden');
            } else {
                this.elements.usageUpgradeBtn.classList.add('hidden');
            }
        } catch (error) {
            console.error('Failed to load usage:', error);
            // Hide widget on error (user might not have subscription)
            this.elements.usageWidget.classList.add('hidden');
        }
    }

    updateProgressColor(progressBar, percentage) {
        // Remove all color classes
        progressBar.classList.remove('low', 'medium', 'high');

        // Add appropriate color class
        if (percentage < 50) {
            progressBar.classList.add('low');
        } else if (percentage < 80) {
            progressBar.classList.add('medium');
        } else {
            progressBar.classList.add('high');
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
            this.appendMessage(msg.role, msg.content, msg.audio_url, msg.created_at || msg.timestamp, msg.id);
        }

        this.scrollToBottom();
    }

    appendMessage(role, content, audioUrl = null, timestamp = null, messageId = null) {
        const div = document.createElement('div');
        div.className = `message ${role === 'user' ? 'sent' : 'received'}`;
        if (messageId) {
            div.dataset.messageId = messageId;
        }

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

        // Message actions menu (three dots)
        const actionsHtml = messageId ? `
            <div class="message-actions">
                <button class="message-actions-btn" title="Message options">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="12" cy="5" r="2"/>
                        <circle cx="12" cy="12" r="2"/>
                        <circle cx="12" cy="19" r="2"/>
                    </svg>
                </button>
                <div class="message-actions-menu">
                    <button class="message-action-item delete-single" data-message-id="${messageId}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                        </svg>
                        Delete this message
                    </button>
                    <button class="message-action-item delete-after" data-message-id="${messageId}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                            <path d="M12 10v8M8 14l4 4 4-4"/>
                        </svg>
                        Delete this and all after
                    </button>
                </div>
            </div>
        ` : '';

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
                ${actionsHtml}
            `;
            isAudioMessage = true;
        } else if (audioUrl && audioUrl.trim()) {
            // Has audio URL - display as audio-only message
            bubbleHtml = `
                <div class="message-bubble audio-message">
                    ${this.createAudioPlayerHTML(audioUrl)}
                    <div class="message-meta">
                        <span class="message-time">${timeStr}</span>
                    </div>
                </div>
                ${actionsHtml}
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
                ${actionsHtml}
            `;
        }

        div.innerHTML = avatarHtml + bubbleHtml;

        // Add event listeners for message actions
        if (messageId) {
            const actionsBtn = div.querySelector('.message-actions-btn');
            const actionsMenu = div.querySelector('.message-actions-menu');
            
            if (actionsBtn && actionsMenu) {
                actionsBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    console.log('Actions menu clicked for message:', messageId);
                    // Close any other open menus
                    document.querySelectorAll('.message-actions-menu.show').forEach(m => {
                        if (m !== actionsMenu) m.classList.remove('show');
                    });
                    actionsMenu.classList.toggle('show');
                });

                // Delete single message
                const deleteSingleBtn = div.querySelector('.delete-single');
                if (deleteSingleBtn) {
                    deleteSingleBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        console.log('Delete single clicked for message:', messageId);
                        actionsMenu.classList.remove('show');
                        this.showDeleteConfirmation(messageId, 'single');
                    });
                }

                // Delete this and after
                const deleteAfterBtn = div.querySelector('.delete-after');
                if (deleteAfterBtn) {
                    deleteAfterBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        console.log('Delete after clicked for message:', messageId);
                        actionsMenu.classList.remove('show');
                        this.showDeleteConfirmation(messageId, 'after');
                    });
                }
            } else {
                console.warn('Message actions elements not found for message:', messageId);
            }
        }

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
        // Reset textarea height after sending
        this.elements.messageInput.style.height = 'auto';

        // Show user message
        this.appendMessage('user', text);

        // Save to database
        try {
            await api.createMessage(this.currentChat.id, text, 'user');
            // Refresh usage after sending message
            this.loadUsage().catch(err => console.error('Failed to refresh usage:', err));
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
        
        // Each sentence is a separate message
        const sentence = msg.content;
        if (sentence && sentence.trim()) {
            if (this.expectingAudioResponse) {
                // Accumulate text for saving with audio later
                this.pendingAssistantText = (this.pendingAssistantText || '') + sentence + ' ';
                return;
            }
            
            // Text-only mode: display and save immediately
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
        this.pendingAssistantText = '';
        
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
                
                // Save with text in content, audio in audio_url
                if (this.currentChat) {
                    const textContent = (this.pendingAssistantText || '').trim() || '[Audio message]';
                    api.createMessage(
                        this.currentChat.id, 
                        textContent,  // Text for memory
                        'assistant', 
                        wavDataUri    // Audio for playback
                    ).catch(console.error);
                    
                    // Add to local messages with text
                    this.messages.push({ role: 'assistant', content: textContent });
                    
                    // Clear pending text
                    this.pendingAssistantText = '';
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

    handleUserTranscription(msg) {
        // Backend transcribed user's audio - now save the message with text + audio
        if (msg.content && this.pendingUserAudio && this.currentChat) {
            const { audioDataUri } = this.pendingUserAudio;

            // Save message with transcribed text in content, audio in audio_url
            api.createMessage(
                this.currentChat.id,
                msg.content,  // Transcribed text for memory
                'user',
                audioDataUri  // Audio data URI for playback
            ).catch(console.error);

            // Add to local messages array with text
            this.messages.push({ role: 'user', content: msg.content });

            // Clear pending audio
            this.pendingUserAudio = null;

            console.log('Saved user audio message with transcription:', msg.content);
        }
    }

    handleMemoryUpdate(msg) {
        // Memory was extracted and saved - refresh UI if memory modal is open
        console.log('Memory update received:', msg);

        if (msg.facts_extracted > 0 || msg.memory_created) {
            // Show subtle notification
            const summary = [];
            if (msg.facts_extracted > 0) {
                summary.push(`${msg.facts_extracted} new fact${msg.facts_extracted > 1 ? 's' : ''}`);
            }
            if (msg.memory_created) {
                summary.push('new memory');
            }
            if (msg.trust_change > 0) {
                summary.push(`+${msg.trust_change} trust`);
            }

            // Only show toast if not too spammy
            if (msg.facts_extracted > 0 || msg.memory_created) {
                this.showToast(`Learned: ${summary.join(', ')}`, 'info', 3000);
            }

            // Refresh memory tab if it's currently open
            if (this.elements.memoryModal?.classList.contains('active')) {
                const activeTab = document.querySelector('.memory-tab.active')?.dataset?.tab;
                if (activeTab === 'facts') {
                    this.loadFacts();
                } else if (activeTab === 'memories') {
                    this.loadMemories();
                } else if (activeTab === 'relationship') {
                    this.loadRelationship();
                }
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
        
        // Store audio data URI for when transcription arrives
        // The message will be saved with text + audio when user_transcription is received
        const audioDataUri = `data:audio/webm;base64,${data}`;
        this.pendingUserAudio = { audioDataUri };
        
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
    async showCharacterModal(character = null) {
        this.elements.characterModal.classList.add('active');
        
        // Load available RVC models
        try {
            const rvcModels = await api.getRVCModels();
            this.populateRVCModelSelect(rvcModels);
        } catch (error) {
            console.error('Failed to load RVC models:', error);
            // Continue without RVC models - they can still upload new ones
        }
        
        if (character) {
            this.elements.modalTitle.textContent = 'Edit Character';
            this.elements.characterId.value = character.id;
            this.elements.characterNameInput.value = character.name;
            this.elements.characterPreprompt.value = character.system_prompt;
            if (this.elements.characterPersona) {
                this.elements.characterPersona.value = character.persona_prompt || '';
            }
            this.elements.promptTemplateSelect.value = character.prompt_template || 'pygmalion';
            this.elements.voiceModelSelect.value = character.voice_model || 'glados';
            this.elements.rvcModelSelect.value = character.rvc_model_path || '';
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
            this.elements.promptTemplateSelect.value = 'pygmalion';
            this.elements.voiceModelSelect.value = 'glados';
            this.elements.rvcModelSelect.value = '';
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

    populateRVCModelSelect(rvcModels) {
        const select = this.elements.rvcModelSelect;
        
        // Clear existing options except the first one
        while (select.options.length > 1) {
            select.remove(1);
        }
        
        // Extract models array from response object
        const models = rvcModels?.models || rvcModels || [];
        
        // Add available RVC models
        if (models && models.length > 0) {
            models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.model_path || model.name;
                option.textContent = model.name;
                select.appendChild(option);
            });
        }
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
        const promptTemplate = this.elements.promptTemplateSelect.value;
        const voiceModel = this.elements.voiceModelSelect.value;
        const selectedRVCModel = this.elements.rvcModelSelect.value;
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
                    prompt_template: promptTemplate,
                    voice_model: voiceModel
                });
                
                // Upload avatar if provided
                if (avatarFile) {
                    await api.uploadCharacterAvatar(id, avatarFile);
                }
                
                // Handle RVC model assignment
                if (selectedRVCModel) {
                    // Assign existing RVC model
                    await api.assignRVCModel(id, selectedRVCModel);
                } else if (pthFile) {
                    // Upload new voice model files
                    showProgress(true);
                    this.elements.saveCharacter.textContent = 'Uploading...';
                    
                    await api.uploadVoiceModel(id, pthFile, indexFile, updateProgress);
                    
                    showProgress(false);
                }
            } else {
                // Create new character first
                character = await api.createCharacter(name, preprompt, personaPrompt || null, voiceModel, promptTemplate);
                
                // Upload avatar if provided
                if (avatarFile) {
                    await api.uploadCharacterAvatar(character.id, avatarFile);
                }
                
                // Handle RVC model assignment
                if (selectedRVCModel) {
                    // Assign existing RVC model
                    await api.assignRVCModel(character.id, selectedRVCModel);
                } else if (pthFile) {
                    // Upload new voice model files
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

    // ==========================================================================
    // Memory Panel Methods
    // ==========================================================================

    async showMemoryModal() {
        if (!this.currentCharacter) {
            this.showToast('Please select a character first', 'warning');
            return;
        }
        
        this.elements.memoryModal?.classList.add('active');
        
        // Load initial data
        this.switchMemoryTab('graph');
    }
    
    hideMemoryModal() {
        this.elements.memoryModal?.classList.remove('active');
    }
    
    switchMemoryTab(tabName) {
        // Update tab buttons
        this.elements.memoryTabs?.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabName);
        });
        
        // Update tab contents
        this.elements.memoryTabContents?.forEach(content => {
            content.classList.toggle('active', content.id === `tab-${tabName}`);
        });
        
        // Load data for the active tab
        switch (tabName) {
            case 'graph':
                this.loadGraph();
                break;
            case 'facts':
                this.loadFacts();
                break;
            case 'memories':
                this.loadMemories();
                break;
        }
    }

    // Graph (knowledge graph snapshot)
    async loadGraph() {
        if (!this.currentCharacter) return;

        const nodesContainer = this.elements.graphNodesList;
        const edgesContainer = this.elements.graphEdgesList;
        const detailsContainer = this.elements.graphDetails;

        try {
            if (nodesContainer) {
                nodesContainer.innerHTML = '<p class="empty-message">Loading graph…</p>';
            }
            if (edgesContainer) {
                edgesContainer.innerHTML = '<p class="empty-message">Loading…</p>';
            }
            if (detailsContainer) {
                detailsContainer.innerHTML = '<p class="empty-message">Select a node or edge</p>';
            }

            const graph = await api.getMemoryGraph(this.currentCharacter.id);
            this._graphCache = graph || { available: false, nodes: [], edges: [], group_id: null };
            this._selectedGraphNodeId = null;
            this._selectedGraphEdgeId = null;

            this.renderGraphNodes();
            this.renderGraphEdges();
        } catch (error) {
            console.error('Failed to load graph:', error);
            this._graphCache = { available: false, nodes: [], edges: [], group_id: null };
            if (nodesContainer) {
                nodesContainer.innerHTML = '<p class="empty-message">Graph unavailable</p>';
            }
            if (edgesContainer) {
                edgesContainer.innerHTML = '<p class="empty-message">Graph unavailable</p>';
            }
            this.showToast('Failed to load graph', 'error');
        }
    }

    getGraphNodeLabel(node) {
        const props = node?.properties || {};
        return (
            props.name ||
            props.title ||
            props.label ||
            props.id ||
            node.id
        );
    }

    renderGraphNodes() {
        const container = this.elements.graphNodesList;
        if (!container) return;

        const graph = this._graphCache || { available: false, nodes: [], edges: [] };
        if (!graph.available) {
            container.innerHTML = '<p class="empty-message">Graph not available (Graphiti/Neo4j not connected)</p>';
            return;
        }

        const query = (this.elements.graphSearch?.value || '').trim().toLowerCase();
        const nodes = (graph.nodes || []).slice();

        const filtered = query
            ? nodes.filter(n => {
                const label = this.getGraphNodeLabel(n).toLowerCase();
                const labels = (n.labels || []).join(' ').toLowerCase();
                return label.includes(query) || labels.includes(query);
            })
            : nodes;

        if (filtered.length === 0) {
            container.innerHTML = '<p class="empty-message">No nodes</p>';
            return;
        }

        container.innerHTML = filtered
            .sort((a, b) => this.getGraphNodeLabel(a).localeCompare(this.getGraphNodeLabel(b)))
            .map(n => {
                const selected = this._selectedGraphNodeId === n.id ? 'selected' : '';
                const labels = (n.labels || []).slice(0, 3).join(', ');
                return `
                    <div class="graph-item ${selected}" onclick="app.selectGraphNode('${n.id}')">
                        <div class="graph-item-title">${this.escapeHtml(this.getGraphNodeLabel(n))}</div>
                        <div class="graph-item-subtitle">${this.escapeHtml(labels || 'node')}</div>
                    </div>
                `;
            })
            .join('');
    }

    renderGraphEdges() {
        const container = this.elements.graphEdgesList;
        if (!container) return;

        const graph = this._graphCache || { available: false, nodes: [], edges: [] };
        if (!graph.available) {
            container.innerHTML = '<p class="empty-message">Graph not available</p>';
            return;
        }

        const edges = graph.edges || [];
        if (!this._selectedGraphNodeId) {
            container.innerHTML = '<p class="empty-message">Select a node to see connections</p>';
            return;
        }

        const nodeMap = (graph.nodes || []).reduce((acc, n) => { acc[n.id] = n; return acc; }, {});
        const connected = edges.filter(e => e.source === this._selectedGraphNodeId || e.target === this._selectedGraphNodeId);

        if (connected.length === 0) {
            container.innerHTML = '<p class="empty-message">No edges for this node</p>';
            return;
        }

        container.innerHTML = connected.map(e => {
            const selected = this._selectedGraphEdgeId === e.id ? 'selected' : '';
            const otherId = e.source === this._selectedGraphNodeId ? e.target : e.source;
            const otherNode = nodeMap[otherId];
            const otherLabel = otherNode ? this.getGraphNodeLabel(otherNode) : otherId;
            return `
                <div class="graph-item ${selected}" onclick="app.selectGraphEdge('${e.id}')">
                    <div class="graph-item-title">${this.escapeHtml(e.type || 'RELATED_TO')}</div>
                    <div class="graph-item-subtitle">${this.escapeHtml(otherLabel)}</div>
                </div>
            `;
        }).join('');
    }

    selectGraphNode(nodeId) {
        this._selectedGraphNodeId = nodeId;
        this._selectedGraphEdgeId = null;

        this.renderGraphNodes();
        this.renderGraphEdges();
        this.showGraphDetails({ kind: 'node', id: nodeId });
    }

    selectGraphEdge(edgeId) {
        this._selectedGraphEdgeId = edgeId;
        this.renderGraphEdges();
        this.showGraphDetails({ kind: 'edge', id: edgeId });
    }

    showGraphDetails(selection) {
        const container = this.elements.graphDetails;
        if (!container) return;

        const graph = this._graphCache || { nodes: [], edges: [] };
        const nodeMap = (graph.nodes || []).reduce((acc, n) => { acc[n.id] = n; return acc; }, {});
        const edgeMap = (graph.edges || []).reduce((acc, e) => { acc[e.id] = e; return acc; }, {});

        if (!selection) {
            container.innerHTML = '<p class="empty-message">Select a node or edge</p>';
            return;
        }

        if (selection.kind === 'node') {
            const node = nodeMap[selection.id];
            if (!node) {
                container.innerHTML = '<p class="empty-message">Node not found</p>';
                return;
            }

            const props = node.properties || {};
            const rows = Object.entries(props)
                .slice(0, 40)
                .map(([k, v]) => `
                    <div class="graph-k">${this.escapeHtml(String(k))}</div>
                    <div class="graph-v">${this.escapeHtml(typeof v === 'string' ? v : JSON.stringify(v))}</div>
                `)
                .join('');

            container.innerHTML = `
                <div class="graph-item-title">${this.escapeHtml(this.getGraphNodeLabel(node))}</div>
                <div class="graph-item-subtitle">${this.escapeHtml((node.labels || []).join(', ') || 'node')}</div>
                <div style="height: 12px"></div>
                <div class="graph-kv">${rows || '<div class="graph-k">(no properties)</div><div class="graph-v"></div>'}</div>
            `;
            return;
        }

        if (selection.kind === 'edge') {
            const edge = edgeMap[selection.id];
            if (!edge) {
                container.innerHTML = '<p class="empty-message">Edge not found</p>';
                return;
            }

            const fromNode = nodeMap[edge.source];
            const toNode = nodeMap[edge.target];
            const fromLabel = fromNode ? this.getGraphNodeLabel(fromNode) : edge.source;
            const toLabel = toNode ? this.getGraphNodeLabel(toNode) : edge.target;

            const props = edge.properties || {};
            const rows = Object.entries(props)
                .slice(0, 40)
                .map(([k, v]) => `
                    <div class="graph-k">${this.escapeHtml(String(k))}</div>
                    <div class="graph-v">${this.escapeHtml(typeof v === 'string' ? v : JSON.stringify(v))}</div>
                `)
                .join('');

            container.innerHTML = `
                <div class="graph-item-title">${this.escapeHtml(edge.type || 'RELATIONSHIP')}</div>
                <div class="graph-item-subtitle">${this.escapeHtml(fromLabel)} → ${this.escapeHtml(toLabel)}</div>
                <div style="height: 12px"></div>
                <div class="graph-kv">${rows || '<div class="graph-k">(no properties)</div><div class="graph-v"></div>'}</div>
            `;
        }
    }
    
    async loadRelationship() {
        if (!this.currentCharacter) return;
        
        try {
            const relationship = await api.getRelationship(this.currentCharacter.id);
            
            // Update display
            this.elements.relStage.textContent = (relationship.stage || 'stranger').replace('_', ' ');
            this.elements.relStageSelect.value = relationship.stage || 'stranger';
            this.elements.relTrustBar.style.width = `${relationship.trust_level || 0}%`;
            this.elements.relTrustValue.textContent = relationship.trust_level || 0;
            this.elements.relTrustSlider.value = relationship.trust_level || 0;
            this.elements.relConversations.textContent = relationship.total_conversations || 0;
            this.elements.relMessages.textContent = relationship.total_messages || 0;
            this.elements.relFirstChat.textContent = relationship.first_conversation 
                ? new Date(relationship.first_conversation).toLocaleDateString()
                : '-';
            
            // Load inside jokes
            this.renderInsideJokes(relationship.inside_jokes || []);
            
            // Load milestones
            this.renderMilestones(relationship.milestones || []);
            
        } catch (error) {
            console.error('Failed to load relationship:', error);
            this.showToast('Failed to load relationship data', 'error');
        }
    }
    
    renderInsideJokes(jokes) {
        const container = this.elements.insideJokesList;
        if (!container) return;
        
        if (jokes.length === 0) {
            container.innerHTML = '<p class="empty-message">No inside jokes yet</p>';
            return;
        }
        
        container.innerHTML = jokes.map((joke, index) => `
            <div class="joke-item memory-item">
                <div class="memory-item-content">
                    <div class="joke-text">"${this.escapeHtml(joke.joke)}"</div>
                    <div class="joke-context">${this.escapeHtml(joke.context)}</div>
                    <div class="joke-date">${joke.created_at ? new Date(joke.created_at).toLocaleDateString() : ''}</div>
                </div>
                <div class="memory-item-actions">
                    <button class="btn-icon delete" onclick="app.deleteInsideJoke(${index})" title="Delete">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    }
    
    renderMilestones(milestones) {
        const container = this.elements.milestonesList;
        if (!container) return;
        
        if (milestones.length === 0) {
            container.innerHTML = '<p class="empty-message">No milestones yet</p>';
            return;
        }
        
        container.innerHTML = milestones.map((milestone, index) => `
            <div class="milestone-item memory-item">
                <div class="memory-item-content">
                    <div class="milestone-name">${this.escapeHtml(milestone.name?.replace('_', ' ') || '')}</div>
                    <div class="milestone-description">${this.escapeHtml(milestone.description || '')}</div>
                    <div class="milestone-date">${milestone.date ? new Date(milestone.date).toLocaleDateString() : ''}</div>
                </div>
                <div class="memory-item-actions">
                    <button class="btn-icon delete" onclick="app.deleteMilestone(${index})" title="Delete">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    }
    
    toggleRelationshipEdit(editing) {
        // Toggle visibility
        this.elements.relStage.classList.toggle('hidden', editing);
        this.elements.relStageSelect.classList.toggle('hidden', !editing);
        this.elements.relTrustSlider.classList.toggle('hidden', !editing);
        
        this.elements.editRelationshipBtn.classList.toggle('hidden', editing);
        this.elements.saveRelationshipBtn.classList.toggle('hidden', !editing);
        this.elements.cancelRelationshipBtn.classList.toggle('hidden', !editing);
    }
    
    async saveRelationship() {
        if (!this.currentCharacter) return;
        
        const update = {
            stage: this.elements.relStageSelect.value,
            trust_level: parseInt(this.elements.relTrustSlider.value, 10)
        };
        
        try {
            await api.updateRelationship(this.currentCharacter.id, update);
            this.showToast('Relationship updated', 'success');
            this.toggleRelationshipEdit(false);
            await this.loadRelationship();
        } catch (error) {
            console.error('Failed to update relationship:', error);
            this.showToast('Failed to update relationship', 'error');
        }
    }
    
    async deleteInsideJoke(index) {
        if (!this.currentCharacter) return;
        if (!confirm('Delete this inside joke?')) return;
        
        try {
            await api.deleteInsideJoke(this.currentCharacter.id, index);
            this.showToast('Inside joke deleted', 'success');
            await this.loadRelationship();
        } catch (error) {
            console.error('Failed to delete inside joke:', error);
            this.showToast('Failed to delete inside joke', 'error');
        }
    }
    
    async deleteMilestone(index) {
        if (!this.currentCharacter) return;
        if (!confirm('Delete this milestone?')) return;
        
        try {
            await api.deleteMilestone(this.currentCharacter.id, index);
            this.showToast('Milestone deleted', 'success');
            await this.loadRelationship();
        } catch (error) {
            console.error('Failed to delete milestone:', error);
            this.showToast('Failed to delete milestone', 'error');
        }
    }
    
    // Facts Management
    async loadFacts() {
        if (!this.currentCharacter) return;
        
        const category = this.elements.factsCategoryFilter?.value || '';
        
        try {
            const response = await api.getUserFacts(this.currentCharacter.id, category || null);
            this.renderFacts(response.facts || []);
        } catch (error) {
            console.error('Failed to load facts:', error);
            this.showToast('Failed to load facts', 'error');
        }
    }
    
    renderFacts(facts) {
        const container = this.elements.factsList;
        if (!container) return;
        
        if (facts.length === 0) {
            container.innerHTML = '<p class="empty-message">No facts extracted yet</p>';
            return;
        }
        
        container.innerHTML = facts.map(fact => `
            <div class="memory-item">
                <div class="memory-item-content">
                    <div class="memory-item-header">
                        <span class="memory-item-category">${this.escapeHtml(fact.category)}</span>
                        <span class="memory-item-key">${this.escapeHtml(fact.key)}</span>
                    </div>
                    <div class="memory-item-value">${this.escapeHtml(fact.value)}</div>
                    <div class="memory-item-meta">
                        <span>Confidence: ${Math.round(fact.confidence * 100)}%</span>
                        <span>Updated: ${new Date(fact.updated_at).toLocaleDateString()}</span>
                    </div>
                </div>
                <div class="memory-item-actions">
                    <button class="btn-icon" onclick="app.showFactEditModal('${fact.id}')" title="Edit">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <button class="btn-icon delete" onclick="app.deleteFact('${fact.id}')" title="Delete">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
        
        // Store facts for editing
        this._factsCache = facts.reduce((acc, f) => { acc[f.id] = f; return acc; }, {});
    }
    
    showFactEditModal(factId) {
        const isNew = !factId;
        
        this.elements.factEditTitle.textContent = isNew ? 'Add Fact' : 'Edit Fact';
        this.elements.factEditId.value = factId || '';
        
        if (isNew) {
            this.elements.factEditCategory.value = 'personal';
            this.elements.factEditKey.value = '';
            this.elements.factEditValue.value = '';
            this.elements.factEditConfidence.value = '1';
        } else {
            const fact = this._factsCache?.[factId];
            if (fact) {
                this.elements.factEditCategory.value = fact.category || 'personal';
                this.elements.factEditKey.value = fact.key || '';
                this.elements.factEditValue.value = fact.value || '';
                this.elements.factEditConfidence.value = fact.confidence || 1;
            }
        }
        
        this.elements.factEditModal.classList.add('active');
    }
    
    hideFactEditModal() {
        this.elements.factEditModal.classList.remove('active');
    }
    
    async saveFact() {
        if (!this.currentCharacter) return;
        
        const factId = this.elements.factEditId.value;
        const isNew = !factId;
        
        const data = {
            category: this.elements.factEditCategory.value,
            key: this.elements.factEditKey.value.trim(),
            value: this.elements.factEditValue.value.trim(),
            confidence: parseFloat(this.elements.factEditConfidence.value) || 1
        };
        
        if (!data.key || !data.value) {
            this.showToast('Please fill in key and value', 'warning');
            return;
        }
        
        try {
            if (isNew) {
                // Create new fact via POST
                await api.request('POST', `/api/memory/${this.currentCharacter.id}/facts`, data);
                this.showToast('Fact created', 'success');
            } else {
                await api.updateUserFact(this.currentCharacter.id, factId, data);
                this.showToast('Fact updated', 'success');
            }
            
            this.hideFactEditModal();
            await this.loadFacts();
        } catch (error) {
            console.error('Failed to save fact:', error);
            this.showToast('Failed to save fact', 'error');
        }
    }
    
    async deleteFact(factId) {
        if (!this.currentCharacter) return;
        if (!confirm('Delete this fact?')) return;
        
        try {
            await api.deleteUserFact(this.currentCharacter.id, factId);
            this.showToast('Fact deleted', 'success');
            await this.loadFacts();
        } catch (error) {
            console.error('Failed to delete fact:', error);
            this.showToast('Failed to delete fact', 'error');
        }
    }
    
    // Memories Management
    async loadMemories() {
        if (!this.currentCharacter) return;
        
        const memoryType = this.elements.memoriesTypeFilter?.value || '';
        
        try {
            const response = await api.getMemories(this.currentCharacter.id, memoryType || null, 50);
            this.renderMemories(response.memories || []);
        } catch (error) {
            console.error('Failed to load memories:', error);
            this.showToast('Failed to load memories', 'error');
        }
    }
    
    renderMemories(memories) {
        const container = this.elements.memoriesList;
        if (!container) return;
        
        if (memories.length === 0) {
            container.innerHTML = '<p class="empty-message">No memories created yet</p>';
            return;
        }
        
        const getImportanceClass = (importance) => {
            if (importance >= 0.8) return 'critical';
            if (importance >= 0.6) return 'high';
            if (importance >= 0.4) return 'medium';
            return 'low';
        };
        
        container.innerHTML = memories.map(memory => `
            <div class="memory-item">
                <div class="memory-item-content">
                    <div class="memory-item-header">
                        <span class="memory-type-badge ${memory.memory_type}">${memory.memory_type}</span>
                        <span class="importance-indicator">
                            <span class="importance-dot ${getImportanceClass(memory.importance)}"></span>
                            ${Math.round(memory.importance * 100)}%
                        </span>
                        ${memory.emotional_tone ? `<span class="memory-item-category">${memory.emotional_tone}</span>` : ''}
                    </div>
                    ${memory.summary ? `<div class="memory-item-key">${this.escapeHtml(memory.summary)}</div>` : ''}
                    <div class="memory-item-value">${this.escapeHtml(memory.content)}</div>
                    <div class="memory-item-meta">
                        <span>Created: ${new Date(memory.created_at).toLocaleDateString()}</span>
                        <span>Accessed: ${memory.access_count}x</span>
                    </div>
                </div>
                <div class="memory-item-actions">
                    <button class="btn-icon" onclick="app.showMemoryEditModal('${memory.id}')" title="Edit">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </button>
                    <button class="btn-icon delete" onclick="app.deleteMemoryItem('${memory.id}')" title="Delete">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
        
        // Store memories for editing
        this._memoriesCache = memories.reduce((acc, m) => { acc[m.id] = m; return acc; }, {});
    }
    
    showMemoryEditModal(memoryId) {
        const memory = this._memoriesCache?.[memoryId];
        if (!memory) return;
        
        this.elements.memoryEditId.value = memoryId;
        this.elements.memoryEditSummary.value = memory.summary || '';
        this.elements.memoryEditContent.value = memory.content || '';
        this.elements.memoryEditTone.value = memory.emotional_tone || 'neutral';
        this.elements.memoryEditImportance.value = memory.importance || 0.5;
        
        this.elements.memoryEditModal.classList.add('active');
    }
    
    hideMemoryEditModal() {
        this.elements.memoryEditModal.classList.remove('active');
    }
    
    async saveMemory() {
        if (!this.currentCharacter) return;
        
        const memoryId = this.elements.memoryEditId.value;
        if (!memoryId) return;
        
        const data = {
            summary: this.elements.memoryEditSummary.value.trim() || null,
            content: this.elements.memoryEditContent.value.trim(),
            emotional_tone: this.elements.memoryEditTone.value,
            importance: parseFloat(this.elements.memoryEditImportance.value) || 0.5
        };
        
        try {
            await api.updateMemory(this.currentCharacter.id, memoryId, data);
            this.showToast('Memory updated', 'success');
            this.hideMemoryEditModal();
            await this.loadMemories();
        } catch (error) {
            console.error('Failed to save memory:', error);
            this.showToast('Failed to save memory', 'error');
        }
    }
    
    async deleteMemoryItem(memoryId) {
        if (!this.currentCharacter) return;
        if (!confirm('Delete this memory?')) return;
        
        try {
            await api.deleteMemory(this.currentCharacter.id, memoryId);
            this.showToast('Memory deleted', 'success');
            await this.loadMemories();
        } catch (error) {
            console.error('Failed to delete memory:', error);
            this.showToast('Failed to delete memory', 'error');
        }
    }
    
    // Diary
    async loadDiary() {
        if (!this.currentCharacter) return;
        
        const entryType = this.elements.diaryTypeFilter?.value || 'daily';
        
        try {
            const response = await api.getDiaryEntries(this.currentCharacter.id, entryType, 30);
            this.renderDiary(response.entries || []);
        } catch (error) {
            console.error('Failed to load diary:', error);
            this.showToast('Failed to load diary', 'error');
        }
    }
    
    renderDiary(entries) {
        const container = this.elements.diaryList;
        if (!container) return;
        
        if (entries.length === 0) {
            container.innerHTML = '<p class="empty-message">No diary entries yet</p>';
            return;
        }
        
        container.innerHTML = entries.map(entry => `
            <div class="diary-item">
                <div class="diary-date">${new Date(entry.entry_date).toLocaleDateString()} - ${entry.entry_type}</div>
                <div class="diary-summary">${this.escapeHtml(entry.summary)}</div>
                ${entry.highlights?.length ? `
                    <div class="diary-highlights">
                        ${entry.highlights.map(h => `<span class="diary-highlight">${this.escapeHtml(h)}</span>`).join('')}
                    </div>
                ` : ''}
                ${entry.emotional_summary ? `<div class="diary-emotional">Mood: ${this.escapeHtml(entry.emotional_summary)}</div>` : ''}
            </div>
        `).join('');
    }

    // =========================================================================
    // Message Deletion
    // =========================================================================

    showDeleteConfirmation(messageId, deleteType) {
        console.log('showDeleteConfirmation called:', messageId, deleteType);
        const modal = document.getElementById('deleteMessageModal');
        if (!modal) {
            // Create modal if it doesn't exist
            console.log('Creating delete modal');
            this.createDeleteModal();
            return this.showDeleteConfirmation(messageId, deleteType);
        }

        const title = modal.querySelector('.modal-title');
        const message = modal.querySelector('.delete-message-text');
        const confirmBtn = modal.querySelector('.confirm-delete-btn');

        if (deleteType === 'single') {
            title.textContent = 'Delete Message';
            message.textContent = 'Are you sure you want to delete this message? This action cannot be undone.';
        } else {
            title.textContent = 'Delete Messages';
            message.textContent = 'Are you sure you want to delete this message and all messages after it? This action cannot be undone.';
        }

        // Store the delete info
        confirmBtn.dataset.messageId = messageId;
        confirmBtn.dataset.deleteType = deleteType;

        console.log('Showing modal');
        modal.classList.add('show');
    }

    createDeleteModal() {
        const modal = document.createElement('div');
        modal.id = 'deleteMessageModal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content delete-modal-content">
                <div class="modal-header">
                    <h3 class="modal-title">Delete Message</h3>
                    <button class="modal-close">&times;</button>
                </div>
                <div class="modal-body">
                    <p class="delete-message-text">Are you sure you want to delete this message?</p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary cancel-delete-btn">Cancel</button>
                    <button class="btn btn-danger confirm-delete-btn">Delete</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Add event listeners
        modal.querySelector('.modal-close').addEventListener('click', () => {
            modal.classList.remove('show');
        });

        modal.querySelector('.cancel-delete-btn').addEventListener('click', () => {
            modal.classList.remove('show');
        });

        // Store reference to app instance
        const app = this;
        modal.querySelector('.confirm-delete-btn').addEventListener('click', async (e) => {
            const messageId = e.target.dataset.messageId;
            const deleteType = e.target.dataset.deleteType;
            await app.executeMessageDelete(messageId, deleteType);
            modal.classList.remove('show');
        });

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('show');
            }
        });
    }

    async executeMessageDelete(messageId, deleteType) {
        if (!this.currentChat) return;

        try {
            let result;
            if (deleteType === 'single') {
                result = await api.deleteMessage(this.currentChat.id, messageId);
            } else {
                result = await api.deleteMessageAndAfter(this.currentChat.id, messageId);
            }

            if (result.success) {
                // Reload messages
                const messagesData = await api.getChatMessages(this.currentChat.id);
                this.messages = messagesData.messages || [];
                this.renderMessages();
                this.showToast(`Deleted ${result.deleted_count} message(s)`, 'success');
            }
        } catch (error) {
            console.error('Failed to delete message:', error);
            this.showToast('Failed to delete message: ' + error.message, 'error');
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
