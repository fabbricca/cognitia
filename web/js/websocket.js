/**
 * Cognitia WebSocket Manager
 */

export class WebSocketManager {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;
        this.listeners = {};
    }

    connect() {
        return new Promise((resolve, reject) => {
            try {
                this.ws = new WebSocket(this.url);
                
                this.ws.onopen = () => {
                    console.log('WebSocket connected');
                    this.connected = true;
                    this.reconnectAttempts = 0;
                    this.emit('connected');
                    resolve();
                };

                this.ws.onclose = (event) => {
                    console.log('WebSocket closed:', event.code);
                    this.connected = false;
                    this.emit('disconnected');
                    
                    // Attempt reconnect
                    if (this.reconnectAttempts < this.maxReconnectAttempts) {
                        this.reconnectAttempts++;
                        setTimeout(() => this.connect(), this.reconnectDelay);
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.emit('error', error);
                    reject(error);
                };

                this.ws.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        this.emit('message', msg);
                        this.emit(msg.type, msg);
                    } catch (e) {
                        console.error('Failed to parse message:', e);
                    }
                };
            } catch (error) {
                reject(error);
            }
        });
    }

    send(message) {
        if (this.ws && this.connected) {
            this.ws.send(JSON.stringify(message));
            return true;
        }
        return false;
    }

    sendText(text, chatId, characterId) {
        return this.send({
            type: 'text',
            message: text,
            chatId: chatId,
            characterId: characterId
        });
    }

    sendAudio(audioData, format, sampleRate, chatId, characterId) {
        return this.send({
            type: 'audio',
            data: audioData,
            format: format,
            sampleRate: sampleRate,
            chatId: chatId,
            characterId: characterId
        });
    }

    switchCharacter(characterId, systemPrompt, voiceModel, rvcModelPath, rvcIndexPath) {
        return this.send({
            type: 'character_switch',
            characterId: characterId,
            systemPrompt: systemPrompt,
            voiceModel: voiceModel,
            rvcModelPath: rvcModelPath,
            rvcIndexPath: rvcIndexPath
        });
    }

    startCall(chatId, characterId) {
        return this.send({
            type: 'call_start',
            chatId: chatId,
            characterId: characterId
        });
    }

    endCall() {
        return this.send({
            type: 'call_end'
        });
    }

    stopPlayback() {
        return this.send({
            type: 'stop_playback'
        });
    }

    disconnect() {
        if (this.ws) {
            this.maxReconnectAttempts = 0; // Prevent reconnect
            this.ws.close();
        }
    }

    on(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }

    off(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
        }
    }

    emit(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(callback => callback(data));
        }
    }
}
